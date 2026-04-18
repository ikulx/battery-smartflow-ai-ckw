from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.core import HomeAssistant

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


def _read_sensor_kwh(
    hass: HomeAssistant,
    entity_id: str | None,
) -> tuple[float | None, bool]:
    """
    Returns:
        (value_kwh, configured_and_found)

    - value_kwh is None if the sensor is missing or invalid
    - configured_and_found tells us whether the entity was actually configured and found
    """
    if not entity_id:
        return None, False

    st = hass.states.get(entity_id)
    if st is None:
        return None, False

    return _to_float(st.state, None), True


def build_forecast_summary(
    hass: HomeAssistant,
    today_entity_id: str | None,
    tomorrow_entity_id: str | None,
    installed_pv_wp: float = 0.0,
) -> ForecastSummary:
    """
    Build a normalized optional forecast summary from two daily forecast sensors.

    Rules:
    - no configured sensors -> not_configured
    - configured, but no readable values -> unavailable
    - at least one readable value -> available

    Notes:
    - This V4.0.0 first step intentionally prefers robustness over depth.
    - next_3h / next_6h and daily peak values are not derivable from simple
      today/tomorrow total sensors, so they remain 0.0 for now.
    """
    if not today_entity_id and not tomorrow_entity_id:
        return ForecastSummary(
            status=FORECAST_STATUS_NOT_CONFIGURED,
            source_name=None,
            pv_outlook=PV_OUTLOOK_UNKNOWN,
        )

    today_kwh, today_found = _read_sensor_kwh(hass, today_entity_id)
    tomorrow_kwh, tomorrow_found = _read_sensor_kwh(hass, tomorrow_entity_id)

    any_configured = bool(today_entity_id or tomorrow_entity_id)
    any_found = bool(today_found or tomorrow_found)
    any_valid = today_kwh is not None or tomorrow_kwh is not None

    if any_configured and (not any_found or not any_valid):
        return ForecastSummary(
            status=FORECAST_STATUS_UNAVAILABLE,
            source_name="Solcast",
            pv_outlook=PV_OUTLOOK_UNKNOWN,
        )

    remaining_today_kwh = max(0.0, float(today_kwh or 0.0))
    tomorrow_kwh_val = max(0.0, float(tomorrow_kwh or 0.0))

    # In the 2-sensor start version we do not have sub-day granularity.
    next_3h_kwh = 0.0
    next_6h_kwh = 0.0
    peak_today_w = 0.0
    peak_tomorrow_w = 0.0

    pv_outlook = _classify_pv_outlook(
        remaining_today_kwh=remaining_today_kwh,
        next_6h_kwh=next_6h_kwh,
        tomorrow_kwh=tomorrow_kwh_val,
        installed_pv_wp=float(installed_pv_wp or 0.0),
    )

    return ForecastSummary(
        status=FORECAST_STATUS_AVAILABLE,
        source_name="Solcast",
        remaining_today_kwh=round(remaining_today_kwh, 3),
        tomorrow_kwh=round(tomorrow_kwh_val, 3),
        next_3h_kwh=round(next_3h_kwh, 3),
        next_6h_kwh=round(next_6h_kwh, 3),
        peak_today_w=round(peak_today_w, 1),
        peak_tomorrow_w=round(peak_tomorrow_w, 1),
        pv_outlook=pv_outlook,
    )
