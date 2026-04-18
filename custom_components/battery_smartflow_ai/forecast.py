from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import (
    FORECAST_STATUS_AVAILABLE,
    FORECAST_STATUS_NOT_CONFIGURED,
    FORECAST_STATUS_UNAVAILABLE,
    PV_OUTLOOK_GOOD,
    PV_OUTLOOK_MIXED,
    PV_OUTLOOK_POOR,
    PV_OUTLOOK_UNKNOWN,
)


@dataclass
class ForecastPoint:
    start: datetime
    end: datetime
    power_w: float
    energy_kwh: float


@dataclass
class ForecastSummary:
    status: str = FORECAST_STATUS_NOT_CONFIGURED
    source_name: str | None = None

    remaining_today_kwh: float = 0.0
    tomorrow_kwh: float = 0.0

    next_3h_kwh: float = 0.0
    next_6h_kwh: float = 0.0

    peak_today_w: float = 0.0
    peak_tomorrow_w: float = 0.0

    pv_outlook: str = PV_OUTLOOK_UNKNOWN


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


def _normalize_dt(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = dt_util.parse_datetime(str(value))
        except Exception:
            return None

    if dt is None:
        return None

    tz = dt_util.get_default_time_zone()

    if dt.tzinfo is None:
        return dt_util.as_local(dt_util.replace(dt, tzinfo=tz))

    return dt_util.as_local(dt)


def _safe_duration_hours(start: datetime, end: datetime) -> float:
    seconds = max(0.0, (end - start).total_seconds())
    if seconds <= 0:
        return 0.0
    return seconds / 3600.0


def _extract_forecast_list(attrs: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Defensive extractor for forecast point lists.

    Solcast variants and similar sensors may expose arrays under different names.
    We intentionally support several likely patterns.
    """
    candidates = [
        attrs.get("detailedForecast"),
        attrs.get("detailed_forecast"),
        attrs.get("forecast"),
        attrs.get("forecasts"),
        attrs.get("data"),
        attrs.get("entries"),
        attrs.get("timeslots"),
    ]

    for candidate in candidates:
        if isinstance(candidate, list):
            return [item for item in candidate if isinstance(item, dict)]

    # nested structures
    for key in ("forecast", "data", "result"):
        nested = attrs.get(key)
        if isinstance(nested, dict):
            for subkey in (
                "detailedForecast",
                "detailed_forecast",
                "forecast",
                "forecasts",
                "data",
                "entries",
                "timeslots",
            ):
                candidate = nested.get(subkey)
                if isinstance(candidate, list):
                    return [item for item in candidate if isinstance(item, dict)]

    return []


def _build_point(item: dict[str, Any]) -> ForecastPoint | None:
    start = _normalize_dt(
        item.get("period_start")
        or item.get("start")
        or item.get("start_time")
        or item.get("datetime")
        or item.get("time")
    )

    end = _normalize_dt(
        item.get("period_end")
        or item.get("end")
        or item.get("end_time")
    )

    if start is None:
        return None

    if end is None:
        # Solcast detailed forecast is often 30-minute granularity
        end = start + timedelta(minutes=30)

    if end <= start:
        return None

    duration_h = _safe_duration_hours(start, end)
    if duration_h <= 0:
        return None

    # Try energy first (kWh-ish values)
    energy_kwh = _to_float(
        item.get("energy_kwh")
        or item.get("estimate_kwh")
        or item.get("pv_estimate_kwh")
        or item.get("forecast_kwh"),
        None,
    )

    # Solcast often exposes pv_estimate; depending on source/adapter this may
    # represent the period estimate. We treat it as kWh if no explicit energy exists.
    if energy_kwh is None:
        energy_kwh = _to_float(
            item.get("pv_estimate")
            or item.get("estimate")
            or item.get("forecast"),
            None,
        )

    # Try direct power fields (W or kW)
    power_w = _to_float(
        item.get("power_w")
        or item.get("pv_estimate_power_w")
        or item.get("estimate_power_w"),
        None,
    )

    if power_w is None:
        power_kw = _to_float(
            item.get("power_kw")
            or item.get("pv_estimate_power_kw")
            or item.get("estimate_power_kw"),
            None,
        )
        if power_kw is not None:
            power_w = float(power_kw) * 1000.0

    # If we only have energy, derive average power over the slot
    if power_w is None and energy_kwh is not None and duration_h > 0:
        power_w = (float(energy_kwh) / duration_h) * 1000.0

    # If we only have power, derive slot energy
    if energy_kwh is None and power_w is not None and duration_h > 0:
        energy_kwh = (float(power_w) / 1000.0) * duration_h

    if energy_kwh is None and power_w is None:
        return None

    return ForecastPoint(
        start=start,
        end=end,
        power_w=max(0.0, float(power_w or 0.0)),
        energy_kwh=max(0.0, float(energy_kwh or 0.0)),
    )


def _classify_pv_outlook(
    remaining_today_kwh: float,
    next_6h_kwh: float,
    tomorrow_kwh: float,
    installed_pv_wp: float,
) -> str:
    """
    Relative, soft classification.

    Forecast is optional and should not be overly strict in V4.0.0.
    This is intentionally conservative and only used for transparency / later planning.
    """
    installed_wp = max(0.0, float(installed_pv_wp or 0.0))

    if installed_wp <= 0:
        if next_6h_kwh <= 0.05 and remaining_today_kwh <= 0.10 and tomorrow_kwh <= 0.10:
            return PV_OUTLOOK_POOR
        if next_6h_kwh >= 2.5 or remaining_today_kwh >= 4.0 or tomorrow_kwh >= 5.0:
            return PV_OUTLOOK_GOOD
        if next_6h_kwh > 0.10 or remaining_today_kwh > 0.20 or tomorrow_kwh > 0.20:
            return PV_OUTLOOK_MIXED
        return PV_OUTLOOK_UNKNOWN

    # rough reference energy from installed peak:
    # not a physical exact model, just a relative first classification for V4.0.0
    reference_day_kwh = installed_wp / 1000.0 * 3.0
    reference_6h_kwh = installed_wp / 1000.0 * 1.5

    good_now = (
        next_6h_kwh >= reference_6h_kwh * 0.55
        or remaining_today_kwh >= reference_day_kwh * 0.55
        or tomorrow_kwh >= reference_day_kwh * 0.70
    )

    poor_now = (
        next_6h_kwh <= max(0.15, reference_6h_kwh * 0.08)
        and remaining_today_kwh <= max(0.20, reference_day_kwh * 0.10)
        and tomorrow_kwh <= max(0.30, reference_day_kwh * 0.12)
    )

    if good_now:
        return PV_OUTLOOK_GOOD
    if poor_now:
        return PV_OUTLOOK_POOR

    return PV_OUTLOOK_MIXED


def build_forecast_summary(
    hass: HomeAssistant,
    entity_id: str | None,
    now: datetime,
    installed_pv_wp: float = 0.0,
) -> ForecastSummary:
    """
    Build a normalized optional forecast summary.

    Rules:
    - No configured entity -> not_configured
    - Configured but no state / no usable points -> unavailable
    - Usable points -> available

    Forecast must never break the integration.
    """
    if not entity_id:
        return ForecastSummary(
            status=FORECAST_STATUS_NOT_CONFIGURED,
            source_name=None,
            pv_outlook=PV_OUTLOOK_UNKNOWN,
        )

    st = hass.states.get(entity_id)
    if st is None:
        return ForecastSummary(
            status=FORECAST_STATUS_UNAVAILABLE,
            source_name="Solcast",
            pv_outlook=PV_OUTLOOK_UNKNOWN,
        )

    attrs = st.attributes or {}
    raw_points = _extract_forecast_list(attrs)

    points: list[ForecastPoint] = []
    for item in raw_points:
        point = _build_point(item)
        if point is not None and point.end > now:
            points.append(point)

    if not points:
        return ForecastSummary(
            status=FORECAST_STATUS_UNAVAILABLE,
            source_name="Solcast",
            pv_outlook=PV_OUTLOOK_UNKNOWN,
        )

    local_now = dt_util.as_local(now)
    today = local_now.date()
    tomorrow = (local_now + timedelta(days=1)).date()
    next_3h_end = local_now + timedelta(hours=3)
    next_6h_end = local_now + timedelta(hours=6)

    remaining_today_kwh = 0.0
    tomorrow_kwh = 0.0
    next_3h_kwh = 0.0
    next_6h_kwh = 0.0
    peak_today_w = 0.0
    peak_tomorrow_w = 0.0

    for point in points:
        start = dt_util.as_local(point.start)

        if start.date() == today:
            remaining_today_kwh += point.energy_kwh
            peak_today_w = max(peak_today_w, point.power_w)

        if start.date() == tomorrow:
            tomorrow_kwh += point.energy_kwh
            peak_tomorrow_w = max(peak_tomorrow_w, point.power_w)

        if start < next_3h_end:
            next_3h_kwh += point.energy_kwh

        if start < next_6h_end:
            next_6h_kwh += point.energy_kwh

    pv_outlook = _classify_pv_outlook(
        remaining_today_kwh=float(remaining_today_kwh),
        next_6h_kwh=float(next_6h_kwh),
        tomorrow_kwh=float(tomorrow_kwh),
        installed_pv_wp=float(installed_pv_wp or 0.0),
    )

    return ForecastSummary(
        status=FORECAST_STATUS_AVAILABLE,
        source_name="Solcast",
        remaining_today_kwh=round(float(remaining_today_kwh), 3),
        tomorrow_kwh=round(float(tomorrow_kwh), 3),
        next_3h_kwh=round(float(next_3h_kwh), 3),
        next_6h_kwh=round(float(next_6h_kwh), 3),
        peak_today_w=round(float(peak_today_w), 1),
        peak_tomorrow_w=round(float(peak_tomorrow_w), 1),
        pv_outlook=pv_outlook,
    )
