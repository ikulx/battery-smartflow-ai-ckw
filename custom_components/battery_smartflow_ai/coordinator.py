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
    SETTING_BATTERY_CAPACITY_KWH,
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
    DEFAULT_BATTERY_CAPACITY_KWH,
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

            # planning transparency (keep sensor-compat)
            "planning_checked": False,
            "planning_status": "not_checked",
            "planning_blocked_by": None,
            "planning_active": False,
            "planning_target_soc": None,
            "planning_next_peak": None,
            "planning_reason": None,
            "next_planned_action": "none",
            "next_planned_action_time": "",
            "next_action_time": None,

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

    def _parse_price_points(self, now) -> list[PricePoint]:
        """Parse export attributes.data (Tibber/EPEX style) to engine price points."""
        if not self.entities.price_export:
            return []
        export = self._attr(self.entities.price_export, "data")
        if not isinstance(export, list):
            return []

        out: list[PricePoint] = []
        for item in export:
            if not isinstance(item, dict):
                continue

            start = (
                item.get("start_time")
                or item.get("starts_at")
                or item.get("start")
                or item.get("time")
            )
            end = item.get("end_time") or item.get("ends_at")

            p = _to_float(item.get("price_per_kwh"), None)
            if not start or p is None:
                continue

            t_start = dt_util.parse_datetime(str(start))
            if not t_start:
                continue

            if end:
                t_end = dt_util.parse_datetime(str(end))
                if not t_end:
                    continue
            else:
                t_end = t_start + timedelta(minutes=15)

            if t_end <= now:
                continue

            out.append(PricePoint(start=t_start, end=t_end, price=float(p)))

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
                    "next_planned_action_time": "",
                    "next_action_state": "none",
                    "device_profile": self.device_profile_key,
                    "season_mode": self._persist.get("season_mode", "winter"),
                    "fault_level_status": "normal",
                }

            soc = float(soc)
            pv_w = float(pv)

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

            battery_capacity_kwh = self._get_setting(SETTING_BATTERY_CAPACITY_KWH, DEFAULT_BATTERY_CAPACITY_KWH)

            ai_mode = str(self.runtime_mode.get("ai_mode", AI_MODE_AUTOMATIC))
            manual_action = str(self.runtime_mode.get("manual_action", MANUAL_STANDBY))

            grid_import, grid_export = self._get_grid()
            if grid_import is None or grid_export is None:
                grid_import = 0.0
                grid_export = 0.0

            price_now = self._get_price_now()
            price_points = self._parse_price_points(now)

            # -----------------------------
            # house load estimate
            # -----------------------------
            # Eigenverbrauch = PV - Export (ohne Batteriemessung -> konservativ)
            eigenverbrauch = max(0.0, pv_w - float(grid_export))
            house_load = max(0.0, float(grid_import) + eigenverbrauch)

            # -----------------------------
            # Season detection (Option A)
            # -----------------------------
            season = self._season_detection(pv_w=pv_w, export_w=float(grid_export))

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
                battery_capacity_kwh=0.0,   # optional später über Entity
            )

            decision = self._engine.evaluate(ctx)

            adaptive_peak_active = decision.reason == "adaptive_peak_discharge"

            # Persist previous discharge for delta controller
            self._persist["prev_discharge_w"] = float(decision.discharge_w or 0.0)

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

            # -----------------------------
            # Planning sensor compatibility (minimal but stable)
            # -----------------------------
            self._persist["planning_checked"] = True
            self._persist["planning_active"] = decision.reason.startswith("planning")
            if decision.reason == "planning_charge_now":
                self._persist["planning_status"] = "planning_charge_now"

            elif decision.reason == "planning_latest_start":
                self._persist["planning_status"] = "planning_last_chance"

            elif ai_mode not in (AI_MODE_AUTOMATIC, AI_MODE_WINTER):
                self._persist["planning_status"] = "planning_inactive_mode"

            elif not price_points:
                self._persist["planning_status"] = "planning_no_price_data"

            elif price_now is None:
                self._persist["planning_status"] = "planning_no_price_now"

            else:
                self._persist["planning_status"] = "planning_no_peak_detected"

            self._persist["planning_reason"] = decision.reason if decision.reason.startswith("planning") else "standby"
            self._persist["planning_target_soc"] = decision.target_soc

            if decision.action == "charge" and decision.reason.startswith("planning"):
                self._persist["next_planned_action"] = "charge"
                self._persist["next_planned_action_time"] = now.isoformat()
            else:
                self._persist["next_planned_action"] = "none"
                self._persist["next_planned_action_time"] = ""

            # next_action_time (top-level sensor expects ISO or None)
            if is_charging or is_discharging:
                self._persist["next_action_time"] = now.isoformat()
            else:
                self._persist["next_action_time"] = self._persist.get("next_planned_action_time") or None

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
                "planning_checked": bool(self._persist.get("planning_checked")),
                "planning_status": self._persist.get("planning_status"),
                "planning_active": bool(self._persist.get("planning_active")),
                "planning_target_soc": self._persist.get("planning_target_soc"),
                "planning_next_peak": self._persist.get("planning_next_peak"),
                "planning_reason": self._persist.get("planning_reason"),
                "next_planned_action": self._persist.get("next_planned_action"),
                "next_planned_action_time": self._persist.get("next_planned_action_time"),
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
            next_planned_action_time_state = (
                self._persist.get("next_planned_action_time")
                if isinstance(self._persist.get("next_planned_action_time"), str)
                else ""
            )

            next_action_state = (
                "charging_active" if self._persist.get("power_state") == "charging"
                else "discharging_active" if self._persist.get("power_state") == "discharging"
                else "planned_charge" if self._persist.get("next_planned_action") == "charge"
                else "planned_discharge" if self._persist.get("next_planned_action") == "discharge"
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
                "next_planned_action_time": next_planned_action_time_state,
                "next_action_state": next_action_state,
                "device_profile": self.device_profile_key,
                "season_mode": (
                    "manual" if ai_mode == AI_MODE_MANUAL
                    else "summer" if ai_mode == AI_MODE_SUMMER
                    else "winter" if ai_mode == AI_MODE_WINTER
                    else self._persist.get("season_mode", "winter")
                ),
                "fault_level_status": "normal",
            }

        except Exception as err:
            raise UpdateFailed(str(err)) from err
