from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    UPDATE_INTERVAL,
    # config keys
    CONF_SOC_ENTITY,
    CONF_PV_ENTITY,
    CONF_PRICE_EXPORT_ENTITY,
    CONF_PRICE_NOW_ENTITY,
    CONF_AC_MODE_ENTITY,
    CONF_INPUT_LIMIT_ENTITY,
    CONF_OUTPUT_LIMIT_ENTITY,
    CONF_GRID_MODE,
    CONF_GRID_POWER_ENTITY,
    CONF_GRID_IMPORT_ENTITY,
    CONF_GRID_EXPORT_ENTITY,
    CONF_SOC_LIMIT_ENTITY,         
    CONF_PACK_CAPACITY_KWH,
    CONF_BATTERY_AC_POWER_ENTITY,
    GRID_MODE_NONE,
    GRID_MODE_SINGLE,
    GRID_MODE_SPLIT,
    # settings keys (entry.options)
    SETTING_SOC_MIN,
    SETTING_SOC_MAX,
    SETTING_MAX_CHARGE,
    SETTING_MAX_DISCHARGE,
    SETTING_PRICE_THRESHOLD,
    SETTING_VERY_EXPENSIVE_THRESHOLD,
    SETTING_EMERGENCY_SOC,
    SETTING_EMERGENCY_CHARGE,
    SETTING_PROFIT_MARGIN_PCT,
    SETTING_BATTERY_PACKS,
    SETTING_PEAK_FACTOR,
    # defaults
    DEFAULT_SOC_MIN,
    DEFAULT_SOC_MAX,
    DEFAULT_MAX_CHARGE,
    DEFAULT_MAX_DISCHARGE,
    DEFAULT_PRICE_THRESHOLD,
    DEFAULT_VERY_EXPENSIVE_THRESHOLD,
    DEFAULT_EMERGENCY_SOC,
    DEFAULT_EMERGENCY_CHARGE,
    DEFAULT_PROFIT_MARGIN_PCT,
    DEFAULT_BATTERY_PACKS,
    DEFAULT_PEAK_FACTOR,
    # modes
    AI_MODE_AUTOMATIC,
    AI_MODE_SUMMER,
    AI_MODE_WINTER,
    AI_MODE_MANUAL,
    MANUAL_STANDBY,
    MANUAL_CHARGE,
    MANUAL_DISCHARGE,
    # statuses
    STATUS_OK,
    STATUS_SENSOR_INVALID,
    AI_STATUS_STANDBY,
    AI_STATUS_CHARGE_SURPLUS,
    AI_STATUS_COVER_DEFICIT,
    AI_STATUS_EXPENSIVE_DISCHARGE,
    AI_STATUS_VERY_EXPENSIVE_FORCE,
    AI_STATUS_EMERGENCY_CHARGE,
    AI_STATUS_MANUAL,
    RECO_STANDBY,
    RECO_CHARGE,
    RECO_DISCHARGE,
    RECO_EMERGENCY,
    ZENDURE_MODE_INPUT,
    ZENDURE_MODE_OUTPUT,
    CONF_DEVICE_PROFILE,
    DEFAULT_DEVICE_PROFILE,
)

from .device_profiles import DEVICE_PROFILES
from .decision_engine import DecisionEngine, DecisionContext, PricePoint  # <-- neu

_LOGGER = logging.getLogger(__name__)
STORE_VERSION = 1


def _to_float(v: Any, default: float | None = None) -> float | None:
    try:
        if v is None:
            return default
        if isinstance(v, (int, float)):
            return float(v)
        s = str(v).strip()
        if s == "" or s.lower() in ("unknown", "unavailable", "none"):
            return default
        return float(s)
    except Exception:
        return default


@dataclass
class SelectedEntities:
    soc: str
    pv: str
    price_export: str | None
    price_now: str | None
    ac_mode: str
    input_limit: str
    output_limit: str
    battery_ac_power: str

    soc_limit: str | None

    grid_mode: str
    grid_power: str | None
    grid_import: str | None
    grid_export: str | None


class ZendureSmartFlowCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry

        # --- Device profile selection ---
        self.device_profile_key = (
            entry.options.get(CONF_DEVICE_PROFILE)
            or entry.data.get(CONF_DEVICE_PROFILE)
            or DEFAULT_DEVICE_PROFILE
        )

        self._device_profile_cfg = DEVICE_PROFILES.get(
            self.device_profile_key,
            DEVICE_PROFILES[DEFAULT_DEVICE_PROFILE],
        )

        # runtime settings mirror of entry.options (used by number entities)
        self.runtime_settings: dict[str, float] = dict(entry.options)

        self.entities = SelectedEntities(
            soc=str(entry.data[CONF_SOC_ENTITY]),
            pv=str(entry.data[CONF_PV_ENTITY]),
            battery_ac_power=str(entry.data.get(CONF_BATTERY_AC_POWER_ENTITY, "")),
            price_export=entry.data.get(CONF_PRICE_EXPORT_ENTITY),
            price_now=entry.data.get(CONF_PRICE_NOW_ENTITY),
            ac_mode=str(entry.data[CONF_AC_MODE_ENTITY]),
            input_limit=str(entry.data[CONF_INPUT_LIMIT_ENTITY]),
            output_limit=str(entry.data[CONF_OUTPUT_LIMIT_ENTITY]),
            soc_limit=entry.data.get(CONF_SOC_LIMIT_ENTITY),
            grid_mode=str(entry.data.get(CONF_GRID_MODE, GRID_MODE_NONE)),
            grid_power=entry.data.get(CONF_GRID_POWER_ENTITY),
            grid_import=entry.data.get(CONF_GRID_IMPORT_ENTITY),
            grid_export=entry.data.get(CONF_GRID_EXPORT_ENTITY),
        )

        self.runtime_mode: dict[str, Any] = {
            "ai_mode": AI_MODE_AUTOMATIC,
            "manual_action": MANUAL_STANDBY,
        }

        self._engine = DecisionEngine()

        self._store = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._persist: dict[str, Any] = {
            "runtime_mode": dict(self.runtime_mode),

            # last applied setpoints
            "last_set_mode": None,
            "last_set_input_w": None,
            "last_set_output_w": None,
            "prev_discharge_w": 0.0,
            "prev_charge_w": 0.0,

            # basic state
            "power_state": "idle",  # idle|charging|discharging
            "emergency_active": False,

            # analytics
            "trade_avg_charge_price": None,
            "trade_charged_kwh": 0.0,
            "prev_soc": None,

            "avg_charge_price": None,
            "charged_kwh": 0.0,
            "discharged_kwh": 0.0,
            "profit_eur": 0.0,
            "last_ts": None,

            # season detection (Option A)
            "season_mode": "winter",        # winter|summer
            "season_counter": 0,

            # debug
            "debug": "init",
        }

        super().__init__(
            hass,
            _LOGGER,
            name="Battery SmartFlow AI",
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )

    async def _load(self) -> None:
        data = await self._store.async_load()
        if isinstance(data, dict):
            self._persist.update(data)
            if "runtime_mode" in data and isinstance(data["runtime_mode"], dict):
                self.runtime_mode.update(data["runtime_mode"])

    async def _save(self) -> None:
        self._persist["runtime_mode"] = dict(self.runtime_mode)
        await self._store.async_save(self._persist)

    def _state(self, entity_id: str | None) -> Any:
        if not entity_id:
            return None
        st = self.hass.states.get(entity_id)
        return st.state if st else None

    def _attr(self, entity_id: str | None, attr: str) -> Any:
        if not entity_id:
            return None
        st = self.hass.states.get(entity_id)
        if not st:
            return None
        return st.attributes.get(attr)

    def set_ai_mode(self, mode: str) -> None:
        self.runtime_mode["ai_mode"] = mode

    def set_manual_action(self, action: str) -> None:
        self.runtime_mode["manual_action"] = action

    async def _set_ac_mode(self, mode: str) -> None:
        current = self._state(self.entities.ac_mode)
        if current == mode:
            self._persist["last_set_mode"] = mode
            return

        self._persist["last_set_mode"] = mode
        await self.hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": self.entities.ac_mode, "option": mode},
            blocking=False,
        )

    async def _set_input_limit(self, watts: float) -> None:
        val = int(round(float(watts), 0))
        last = self._persist.get("last_set_input_w")
        if last == val:
            return
        self._persist["last_set_input_w"] = val
        await self.hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": self.entities.input_limit, "value": val},
            blocking=False,
        )

    async def _set_output_limit(self, watts: float) -> None:
        val = int(round(float(watts), 0))
        last = self._persist.get("last_set_output_w")
        if last == val:
            return
        self._persist["last_set_output_w"] = val
        await self.hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": self.entities.output_limit, "value": val},
            blocking=False,
        )

    def _get_setting(self, key: str, default: float) -> float:
        try:
            val = self.entry.options.get(key, default)
            return float(val)
        except Exception:
            return float(default)

    def _get_grid(self) -> tuple[float | None, float | None]:
        """
        Returns (import_w, export_w).
        import_w > 0 means importing from grid
        export_w > 0 means exporting to grid
        """
        mode = self.entities.grid_mode

        if mode == GRID_MODE_NONE:
            return None, None

        if mode == GRID_MODE_SINGLE and self.entities.grid_power:
            gp = _to_float(self._state(self.entities.grid_power), None)
            if gp is None:
                return None, None
            gp = float(gp)
            if gp >= 0:
                return gp, 0.0
            return 0.0, abs(gp)

        if mode == GRID_MODE_SPLIT and self.entities.grid_import and self.entities.grid_export:
            gi = _to_float(self._state(self.entities.grid_import), None)
            ge = _to_float(self._state(self.entities.grid_export), None)
            if gi is None or ge is None:
                return None, None
            return float(gi), float(ge)

        return None, None

    def _get_price_now(self) -> float | None:
        if self.entities.price_now:
            p = _to_float(self._state(self.entities.price_now), None)
            if p is not None:
                return float(p)
        return None

    def _get_soc_limit(self) -> int | None:
        if not self.entities.soc_limit:
            return None
        raw = self._state(self.entities.soc_limit)
        val = _to_float(raw, None)
        if val is None:
            return None
        try:
            return int(val)
        except Exception:
            return None

    def _get_battery_capacity(self) -> float:
        pack_capacity = float(
            self.entry.data.get(CONF_PACK_CAPACITY_KWH, 0)
        )

        packs = self._get_setting(
            SETTING_BATTERY_PACKS,
            DEFAULT_BATTERY_PACKS,
        )

        try:
            packs = int(packs)
        except Exception:
            packs = DEFAULT_BATTERY_PACKS

        if pack_capacity <= 0 or packs <= 0:
            return 0.0

        return pack_capacity * packs

    def _parse_price_points(self, now) -> list[PricePoint]:
        """
        Universal price parser (production hardened).

        Supports:
        - Tibber (attributes.data[])
        - Octopus (attributes.rates[])
        - Octopus Germany (unit_rate_forecast[])
        - EPEX style exports
        - Generic 15min APIs

        Handles:
        - Mixed timezones (UTC / CET)
        - Broken Octopus slots (end <= start)
        - DST edge cases
        """

        if not self.entities.price_export:
            return []

        st = self.hass.states.get(self.entities.price_export)
        if not st:
            return []

        attrs = st.attributes or {}

        # --------------------------------------------
        # 1️⃣ Prefer Octopus "rates" if available
        # --------------------------------------------
        raw = (
            attrs.get("rates")
            or attrs.get("data")
            or attrs.get("unit_rate_forecast")
        )

        if not raw:
            return []

        if isinstance(raw, dict):
            raw = raw.get("rates") or raw.get("data") or raw.get("timeslots")

        if not isinstance(raw, list):
            return []

        tz = dt_util.get_default_time_zone()

        def normalize(dt):
            if not dt:
                return None
            if dt.tzinfo is None:
                return dt_util.replace(dt, tzinfo=tz)
            return dt.astimezone(tz)

        now = normalize(now)

        out: list[PricePoint] = []

        for item in raw:
            if not isinstance(item, dict):
                continue

            # ==================================================
            # 🟢 Octopus Germany unit_rate_forecast format
            # ==================================================
            if "validFrom" in item and "validTo" in item:
                start = item.get("validFrom")
                end = item.get("validTo")

                cents = None
                uinfo = item.get("unitRateInformation") or {}
                rates_list = uinfo.get("rates") or []
                if rates_list and isinstance(rates_list[0], dict):
                    cents = _to_float(
                        rates_list[0].get("latestGrossUnitRateCentsPerKwh"),
                        None,
                    )

                if not start or not end or cents is None:
                    continue

                t_start = normalize(dt_util.parse_datetime(str(start)))
                t_end = normalize(dt_util.parse_datetime(str(end)))

                if not t_start or not t_end:
                    continue

                # Skip broken slots (Octopus DST bug)
                if t_end <= t_start:
                    continue

                if t_end <= now:
                    continue

                price = float(cents) / 100.0  # cents → €
                out.append(PricePoint(start=t_start, end=t_end, price=price))
                continue

            # ==================================================
            # 🔵 Generic / Tibber / Octopus "rates" format
            # ==================================================
            start = (
                item.get("start_time")
                or item.get("starts_at")
                or item.get("start")
                or item.get("time")
            )

            end = (
                item.get("end_time")
                or item.get("ends_at")
                or item.get("end")
            )

            p = _to_float(
                item.get("price_per_kwh")
                or item.get("value_inc_vat")
                or item.get("value")
                or item.get("unit_rate")
                or item.get("price"),
                None,
            )

            if not start or p is None:
                continue

            t_start = normalize(dt_util.parse_datetime(str(start)))
            if not t_start:
                continue

            if end:
                t_end = normalize(dt_util.parse_datetime(str(end)))
                if not t_end:
                    continue
            else:
                t_end = t_start + timedelta(minutes=15)

            # Skip broken slots
            if t_end <= t_start:
                continue

            if t_end <= now:
                continue

            out.append(PricePoint(start=t_start, end=t_end, price=float(p)))

        # Final safety: sort chronologically
        out.sort(key=lambda x: x.start)

        return out
    
    def _season_detection(self, pv_w: float, export_w: float) -> str:
        """
        Option A: Season detection stays here.
        Very slow moving anti-flip counter.
        """
        season = self._persist.get("season_mode", "winter")
        counter = int(self._persist.get("season_counter", 0))

        summer_signal = (pv_w > 800.0 and export_w > 300.0)
        winter_signal = (pv_w < 400.0 and export_w < 100.0)

        if summer_signal:
            counter += 1
        elif winter_signal:
            counter -= 1
        else:
            if counter > 0:
                counter -= 1
            elif counter < 0:
                counter += 1

        THRESH = 30
        if counter > THRESH:
            season = "summer"
        elif counter < -THRESH:
            season = "winter"

        self._persist["season_mode"] = season
        self._persist["season_counter"] = counter
        return season

    def _map_ai_status(self, ai_mode: str, action: str, reason: str) -> str:
        if ai_mode == AI_MODE_MANUAL:
            return AI_STATUS_MANUAL
        if action == "emergency":
            return AI_STATUS_EMERGENCY_CHARGE
        if action == "charge":
            return AI_STATUS_CHARGE_SURPLUS
        if action == "discharge":
            if "very_expensive" in reason or "adaptive_peak" in reason:
                return AI_STATUS_VERY_EXPENSIVE_FORCE
            if "price" in reason:
                return AI_STATUS_EXPENSIVE_DISCHARGE
            return AI_STATUS_COVER_DEFICIT
        return AI_STATUS_STANDBY

    def _map_reco(self, action: str) -> str:
        if action == "charge":
            return RECO_CHARGE
        if action == "discharge":
            return RECO_DISCHARGE
        if action == "emergency":
            return RECO_EMERGENCY
        return RECO_STANDBY

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            if self._persist.get("last_ts") is None:
                await self._load()
                self._persist["last_ts"] = dt_util.utcnow().isoformat()

            now = dt_util.utcnow()

            soc = _to_float(self._state(self.entities.soc), None)
            pv = _to_float(self._state(self.entities.pv), None)

            if soc is None or pv is None:
                return {
                    "status": STATUS_SENSOR_INVALID,
                    "ai_status": AI_STATUS_STANDBY,
                    "recommendation": RECO_STANDBY,
                    "debug": "SENSOR_INVALID",
                    "details": {
                        "soc_raw": self._state(self.entities.soc),
                        "pv_raw": self._state(self.entities.pv),
                    },
                    "decision_reason": "sensor_invalid",
                    "next_action_time": None,
                    "next_action_state": "none",
                    "device_profile": self.device_profile_key,
                    "season_mode": self._persist.get("season_mode", "winter"),
                    "fault_level_status": "normal",
                }

            soc = float(soc)
            pv_w = float(pv)

            # -----------------------------
            # Battery capacity (Hybrid detection)
            # -----------------------------
            battery_capacity_kwh = self._get_battery_capacity()

            # -----------------------------
            # Energy delta calculation
            # -----------------------------
            prev_soc = self._persist.get("prev_soc")
            delta_kwh = 0.0

            if prev_soc is not None and battery_capacity_kwh > 0:
                soc_delta_pct = soc - prev_soc
                delta_kwh = battery_capacity_kwh * (soc_delta_pct / 100.0)

            self._persist["prev_soc"] = soc

            profile = self._device_profile_cfg

            soc_min = self._get_setting(SETTING_SOC_MIN, profile.get("SOC_MIN", DEFAULT_SOC_MIN))
            soc_max = self._get_setting(SETTING_SOC_MAX, profile.get("SOC_MAX", DEFAULT_SOC_MAX))

            max_charge = self._get_setting(SETTING_MAX_CHARGE, profile.get("MAX_CHARGE_W", DEFAULT_MAX_CHARGE))
            max_discharge = self._get_setting(SETTING_MAX_DISCHARGE, profile.get("MAX_DISCHARGE_W", DEFAULT_MAX_DISCHARGE))

            # Clamp against profile hard limits
            profile_max_in = float(profile.get("MAX_INPUT_W", max_charge))
            profile_max_out = float(profile.get("MAX_OUTPUT_W", max_discharge))
            max_charge = min(float(max_charge), profile_max_in)
            max_discharge = min(float(max_discharge), profile_max_out)

            expensive = self._get_setting(SETTING_PRICE_THRESHOLD, DEFAULT_PRICE_THRESHOLD)
            very_expensive = self._get_setting(SETTING_VERY_EXPENSIVE_THRESHOLD, DEFAULT_VERY_EXPENSIVE_THRESHOLD)
            emergency_soc = self._get_setting(SETTING_EMERGENCY_SOC, DEFAULT_EMERGENCY_SOC)
            emergency_w = self._get_setting(SETTING_EMERGENCY_CHARGE, DEFAULT_EMERGENCY_CHARGE)
            profit_margin_pct = self._get_setting(SETTING_PROFIT_MARGIN_PCT, DEFAULT_PROFIT_MARGIN_PCT)

            ai_mode = str(self.runtime_mode.get("ai_mode", AI_MODE_AUTOMATIC))
            manual_action = str(self.runtime_mode.get("manual_action", MANUAL_STANDBY))

            grid_import, grid_export = self._get_grid()
            if grid_import is None or grid_export is None:
                grid_import = 0.0
                grid_export = 0.0

            price_now = self._get_price_now()
            price_points = self._parse_price_points(now)

            # --- Daily price average ---
            daily_avg_price = None
            if price_points:
                prices = [p.price for p in price_points]
                if prices:
                     daily_avg_price = sum(prices) / len(prices)

            # --- Current peak threshold ---
            peak_factor = float(
                self.runtime_settings.get(
                    SETTING_PEAK_FACTOR,
                    DEFAULT_PEAK_FACTOR,
                )
            )

            current_peak_threshold = None
            if daily_avg_price is not None:
                current_peak_threshold = max(
                    daily_avg_price * peak_factor,
                    daily_avg_price + 0.03,
                )

            # --- Engine health ---
            engine_health = "ok"
            if not price_points:
                engine_health = "no_price_data"
            elif price_now is None:
                engine_health = "no_current_price"
            elif soc is None or pv is None:
                engine_health = "sensor_invalid"

            # -----------------------------
            # house load estimate (FIXED)
            # -----------------------------
            # Ziel: Hauslast = Netzbezug + Eigenverbrauch
            # Eigenverbrauch basiert auf: PV + (Batterie-Entladung) - Einspeisung
            # Zusätzlich: Batterie-Ladung ist ein Verbraucher und muss zur Hauslast addiert werden.
            #
            # Erwartung für battery_ac_power Sensor:
            #  - Entladung:   positiver Wert (W)
            #  - Ladung:      negativer Wert (W)
            #
            # Wenn dein Sensor umgekehrt ist, musst du ihn über einen Helfer invertieren
            # (oder wir machen das später konfigurierbar).

            battery_w_raw = _to_float(self._state(self.entities.battery_ac_power), 0.0)
            battery_w = float(battery_w_raw or 0.0)

            # Richtungsauftrennung
            battery_discharge_w = max(0.0, battery_w)             # Erzeugung durch Batterie
            battery_charge_w = abs(min(0.0, battery_w))           # Verbrauch durch Batterie (Laden)

            # Eigenverbrauch = PV + Batterie-Entladung - Einspeisung
            eigenverbrauch = max(
                0.0,
                float(pv_w) + float(battery_discharge_w) - float(grid_export),
            )

            # Hauslast = Netzbezug + Eigenverbrauch + Batterie-Ladung
            house_load = max(
                0.0,
                float(grid_import) + float(eigenverbrauch) + float(battery_charge_w),
            )
            
            # -----------------------------
            # Season detection (Option A)
            # -----------------------------
            season = self._season_detection(pv_w=pv_w, export_w=float(grid_export))

            peak_factor = float(
                self.runtime_settings.get(
                    SETTING_PEAK_FACTOR,
                    DEFAULT_PEAK_FACTOR,
                )
            )
            
            # -----------------------------
            # Engine Context
            # -----------------------------
            ctx = DecisionContext(
                now=now,

                soc=soc,
                soc_min=float(soc_min),
                soc_max=float(soc_max),

                emergency_soc=float(emergency_soc),
                emergency_charge_w=float(emergency_w),

                max_charge_w=float(max_charge),
                max_discharge_w=float(max_discharge),

                grid_import_w=float(grid_import),
                grid_export_w=float(grid_export),
                pv_w=float(pv_w),
                house_load_w=float(house_load),

                price_now=price_now,
                avg_charge_price=self._persist.get("trade_avg_charge_price"),
                expensive_threshold=float(expensive),
                very_expensive_threshold=float(very_expensive),
                profit_margin_pct=float(profit_margin_pct),
                price_points=price_points,

                ai_mode=ai_mode,
                manual_action=manual_action,
                season=season,

                # --- V2 additions ---
                profile=profile,
                prev_discharge_w=float(self._persist.get("prev_discharge_w", 0.0)),
                prev_charge_w=float(self._persist.get("prev_charge_w", 0.0)),
                battery_capacity_kwh=battery_capacity_kwh,
                peak_factor=peak_factor,
            )

            decision = self._engine.evaluate(ctx)

            # -----------------------------
            # Profit Tracking – Charging
            # -----------------------------
            if delta_kwh > 0 and price_now is not None:
                charged_kwh = self._persist.get("trade_charged_kwh", 0.0)
                avg_price = self._persist.get("trade_avg_charge_price")

                new_total_kwh = charged_kwh + delta_kwh

                if avg_price is None:
                    new_avg = price_now
                else:
                    new_avg = ((avg_price * charged_kwh + price_now * delta_kwh) / new_total_kwh)

                self._persist["trade_charged_kwh"] = new_total_kwh
                self._persist["trade_avg_charge_price"] = new_avg

            # -----------------------------
            # Profit Tracking – Discharging
            # -----------------------------
            if (
                delta_kwh < 0
                and price_now is not None
                and decision.ac_mode == "output"
                and float(decision.discharge_w or 0.0) > 0.0
            ):
                sold_kwh = abs(float(delta_kwh))
                avg_price = self._persist.get("trade_avg_charge_price")

                if avg_price is not None and sold_kwh > 0:
                    profit = (float(price_now) - float(avg_price)) * sold_kwh

                    self._persist["profit_eur"] = (
                        float(self._persist.get("profit_eur", 0.0))
                        + float(profit)
                    )

                    remaining_kwh = (
                        float(self._persist.get("trade_charged_kwh", 0.0))
                        - sold_kwh
                    )

                    remaining_kwh = max(0.0, remaining_kwh)
                    self._persist["trade_charged_kwh"] = remaining_kwh

                    if remaining_kwh <= 0:
                        self._persist["trade_avg_charge_price"] = None

            adaptive_peak_active = decision.reason == "adaptive_peak_discharge"

            # Persist previous discharge for delta controller
            self._persist["prev_discharge_w"] = float(decision.discharge_w or 0.0)

            # charge memory for delta controller
            if decision.ac_mode == "input" and float(decision.charge_w or 0.0) > 0.0:
                self._persist["prev_charge_w"] = float(decision.charge_w)
            else:
                self._persist["prev_charge_w"] = 0.0

            # -----------------------------
            # BMS SoC limit (directional block)
            # -----------------------------
            soc_limit = self._get_soc_limit()
            if soc_limit == 1 and decision.ac_mode == "input" and decision.charge_w > 0:
                decision.charge_w = 0.0
                decision.action = "idle"
                decision.reason = "soc_limit_upper"
            elif soc_limit == 2 and decision.ac_mode == "output" and decision.discharge_w > 0:
                decision.discharge_w = 0.0
                decision.action = "idle"
                decision.reason = "soc_limit_lower"

            # Enforce soc_min on discharge
            if decision.ac_mode == "output" and soc <= float(soc_min):
                decision.discharge_w = 0.0
                decision.action = "idle"
                decision.reason = "soc_min_enforced"

            # -----------------------------
            # Apply setpoints
            # -----------------------------
            ac_mode = ZENDURE_MODE_INPUT if decision.ac_mode == "input" else ZENDURE_MODE_OUTPUT
            in_w = float(decision.charge_w) if ac_mode == ZENDURE_MODE_INPUT else 0.0
            out_w = float(decision.discharge_w) if ac_mode == ZENDURE_MODE_OUTPUT else 0.0

            # Zendure requires output_limit=0 before AC input
            if ac_mode == ZENDURE_MODE_INPUT:
                if self._persist.get("last_set_output_w", 0) != 0:
                    await self._set_output_limit(0)

            await self._set_ac_mode(ac_mode)

            # set limits
            await self._set_input_limit(in_w)
            await self._set_output_limit(out_w)

            # Persist discharge memory for delta controller
            self._persist["last_set_output_w"] = out_w

            is_charging = ac_mode == ZENDURE_MODE_INPUT and in_w > 0.0
            is_discharging = ac_mode == ZENDURE_MODE_OUTPUT and out_w > 0.0

            if is_charging:
                self._persist["power_state"] = "charging"
            elif is_discharging:
                self._persist["power_state"] = "discharging"
            else:
                self._persist["power_state"] = "idle"

            # next_action_time (top-level sensor expects ISO or None)
            if is_charging or is_discharging:
                self._persist["next_action_time"] = now.isoformat()
            else:
                self._persist["next_action_time"] = None

            # -----------------------------
            # AI status + recommendation
            # -----------------------------
            ai_status = self._map_ai_status(ai_mode=ai_mode, action=decision.action, reason=decision.reason)
            recommendation = self._map_reco(decision.action)

            # -----------------------------
            # Persist + return payload
            # -----------------------------
            self._persist["debug"] = "OK"
            self._persist["last_ts"] = now.isoformat()

            await self._save()

            details = {
                "soc": soc,
                "pv_w": pv_w,
                "deficit": float(grid_import),
                "surplus": float(grid_export),
                "house_load": int(round(house_load, 0)),
                "price_now": price_now,
                "avg_charge_price": self._persist.get("trade_avg_charge_price"),
                "profit_eur": float(self._persist.get("profit_eur") or 0.0),
                "max_charge": max_charge,
                "max_discharge": max_discharge,
                "set_mode": ac_mode,
                "set_input_w": int(round(in_w, 0)),
                "set_output_w": int(round(out_w, 0)),
                "ai_mode": ai_mode,
                "manual_action": manual_action,
                "decision_reason": decision.reason,
                "adaptive_peak_active": adaptive_peak_active,
                "device_profile": self.device_profile_key,
                "profile_max_input_w": profile_max_in,
                "profile_max_output_w": profile_max_out,
                "soc_limit": soc_limit,
                "soc_limit_status": (
                    "not_configured"
                    if soc_limit is None
                    else "no_limit"
                    if soc_limit == 0
                    else "upper_limit_active"
                    if soc_limit == 1
                    else "lower_limit_active"
                ),
            }

            # --- top-level values used by sensor.py ---
            def _iso_or_none(val):
                try:
                    if not val:
                        return None
                    dt = dt_util.parse_datetime(str(val))
                    return dt_util.as_utc(dt).isoformat() if dt else None
                except Exception:
                    return None

            next_action_time_state = _iso_or_none(self._persist.get("next_action_time"))

            next_action_state = (
                "charging_active" if self._persist.get("power_state") == "charging"
                else "discharging_active" if self._persist.get("power_state") == "discharging"
                else "none"
            )

            return {
                "status": STATUS_OK,
                "ai_status": ai_status,
                "recommendation": recommendation,
                "debug": "OK",
                "details": details,
                "decision_reason": decision.reason,
                "next_action_time": next_action_time_state,
                "next_action_state": next_action_state,
                "device_profile": self.device_profile_key,
                "season_mode": (
                    "manual" if ai_mode == AI_MODE_MANUAL
                    else "summer" if ai_mode == AI_MODE_SUMMER
                    else "winter" if ai_mode == AI_MODE_WINTER
                    else self._persist.get("season_mode", "winter")
                ),
                "fault_level_status": "normal",
                "price_daily_average": daily_avg_price,
                "current_peak_threshold": current_peak_threshold,
                "engine_health": engine_health,
            }

        except Exception as err:
            raise UpdateFailed(str(err)) from err
