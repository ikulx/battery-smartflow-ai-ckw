from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional, Literal, List, Tuple


# ----------------------------
# Types
# ----------------------------

PowerState = Literal["idle", "charging", "discharging"]
Action = Literal["none", "charge", "discharge"]
AiMode = str  # use your existing const strings
ZendureMode = str  # use your existing const strings


@dataclass(frozen=True)
class PricePoint:
    start: datetime
    end: datetime
    price_per_kwh: float


@dataclass
class PlanningResult:
    action: Action = "none"
    status: str = "not_checked"
    blocked_by: Optional[str] = None
    next_peak: Optional[str] = None  # ISO
    reason: Optional[str] = None
    latest_start: Optional[str] = None  # ISO
    target_soc: Optional[float] = None
    watts: float = 0.0


@dataclass
class Decision:
    # setpoints
    ac_mode: ZendureMode
    input_w: float
    output_w: float

    # meta / UI
    recommendation: str
    decision_reason: str
    ai_status: str

    # internal state updates
    power_state: PowerState
    discharge_target_w: float

    # planning transparency
    planning_checked: bool
    planning_status: str
    planning_blocked_by: Optional[str]
    planning_active: bool
    planning_reason: Optional[str]
    planning_target_soc: Optional[float]
    planning_next_peak: Optional[str]

    next_planned_action: str  # "charge"|"discharge"|"wait"|"emergency"|"none"
    next_planned_action_time: str  # ISO or ""

    # anti-flutter latch
    planning_latch_until: Optional[str]  # ISO or None


@dataclass
class DecisionContext:
    # time
    now: datetime

    # modes
    ai_mode: AiMode
    manual_action: str  # your existing consts

    # measurements (already cleaned floats)
    soc: float
    pv_w: float
    net_grid_w: float       # +import / -export
    grid_import_w: float    # >=0
    grid_export_w: float    # >=0
    house_load_w: float
    real_pv_surplus: bool

    # optional signals
    price_now: Optional[float]
    price_series: List[PricePoint]  # future price points (already filtered)

    # settings (user configured)
    soc_min: float
    soc_max: float
    max_charge_w: float
    max_discharge_w: float
    expensive_threshold: float
    very_expensive_threshold: float
    emergency_soc: float
    emergency_charge_w: float
    profit_margin_pct: float

    # guards (hardware/BMS)
    soc_limit: Optional[int]  # None/0/1/2
    fault_level: Optional[int]

    # state memory (persist)
    prev_power_state: PowerState
    prev_discharge_target_w: float
    last_set_input_w: float
    last_charge_reason: Optional[str]  # "pv"|"planning"|"manual"|"emergency"|None
    emergency_active_latched: bool
    price_discharge_latched: bool
    planning_latch_until: Optional[datetime]

    # economics memory
    avg_charge_price: Optional[float]  # trade_avg_charge_price

    # device profile (tuning + clamps)
    profile: dict[str, Any]


# ----------------------------
# Helpers (profile based)
# ----------------------------

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def delta_discharge_w(
    *,
    profile: dict[str, Any],
    deficit_w: float,          # net grid (+import/-export)
    prev_out_w: float,
    max_discharge_w: float,
    soc: float,
    soc_min: float,
) -> float:
    """Incremental discharge controller (profile tuned)."""

    target_import = float(profile.get("TARGET_IMPORT_W", 35.0))
    deadband = float(profile.get("DEADBAND_W", 40.0))
    export_guard = float(profile.get("EXPORT_GUARD_W", 45.0))

    kp_up = float(profile.get("KP_UP", 0.55))
    kp_down = float(profile.get("KP_DOWN", 0.95))
    max_step_up = float(profile.get("MAX_STEP_UP", 450.0))
    max_step_down = float(profile.get("MAX_STEP_DOWN", 900.0))

    keepalive_min_deficit = float(profile.get("KEEPALIVE_MIN_DEFICIT_W", 15.0))
    keepalive_min_output = float(profile.get("KEEPALIVE_MIN_OUTPUT_W", 60.0))

    # Hard constraint
    if soc <= soc_min + 0.05:
        return 0.0

    net = float(deficit_w)
    out_w = float(prev_out_w)

    # Anti-export guard: if exporting hard, cut quickly
    if net < -export_guard:
        cut = (abs(net) + target_import) * 1.4
        out_w = max(0.0, out_w - cut)
        return float(_clamp(out_w, 0.0, max_discharge_w))

    err = net - target_import

    if err > deadband:
        step = min(max_step_up, max(40.0, kp_up * err))
        out_w += step
    elif err < -deadband:
        step = min(max_step_down, max(60.0, kp_down * abs(err)))
        out_w -= step
    else:
        # hold
        out_w = out_w

    out_w = float(_clamp(out_w, 0.0, max_discharge_w))

    # Keep-alive: don’t drop to 0 too early when deficit is tiny
    if net <= keepalive_min_deficit:
        out_w = max(out_w, keepalive_min_output)

    return float(_clamp(out_w, 0.0, max_discharge_w))


def grid_follow_charge_w(
    *,
    profile: dict[str, Any],
    net_grid_w: float,     # +import / -export
    prev_in_w: float,
    max_charge_w: float,
) -> float:
    """
    Grid-following charge controller: regulate against near-zero export.
    Profile keys (optional):
      - CHARGE_TARGET_EXPORT_W (default -10W)
      - CHARGE_KP (default 0.6)
      - CHARGE_MAX_STEP_W (default 250W)
    """

    target_export_w = float(profile.get("CHARGE_TARGET_EXPORT_W", -10.0))
    kp = float(profile.get("CHARGE_KP", 0.6))
    max_step = float(profile.get("CHARGE_MAX_STEP_W", 250.0))

    # error relative to target export
    # if net_grid_w is very negative (export), we need MORE charging (increase in_w)
    err = net_grid_w - target_export_w

    # proportional step (note sign)
    step = _clamp(kp * (-err), -max_step, max_step)
    in_w = prev_in_w + step

    return float(_clamp(in_w, 0.0, max_charge_w))


# ----------------------------
# Planning (peak + valley)
# ----------------------------

def evaluate_price_planning(ctx: DecisionContext, *, planning_enabled: bool) -> PlanningResult:
    r = PlanningResult()

    if not planning_enabled:
        r.status = "planning_inactive_mode"
        r.blocked_by = "mode"
        return r

    if ctx.soc >= ctx.soc_max - 0.1:
        r.status = "planning_blocked_soc_full"
        r.blocked_by = "soc"
        return r

    if ctx.price_now is None:
        r.status = "planning_no_price_now"
        r.blocked_by = "price_now"
        return r

    if not ctx.price_series or len(ctx.price_series) < 8:
        r.status = "planning_no_price_data"
        r.blocked_by = "price_data"
        return r

    # Peak = highest price point
    peak = max(ctx.price_series, key=lambda p: p.price_per_kwh)
    peak_price = float(peak.price_per_kwh)

    if peak_price < float(ctx.expensive_threshold) and peak_price < float(ctx.very_expensive_threshold):
        r.status = "planning_no_peak_detected"
        return r

    # ---- Very-expensive peak discharge planning (no lock, only close to peak) ----
    # NOTE: does NOT limit charging, only adds an optional discharge action near the peak.
    reserve_soc_for_peak_discharge = float(ctx.soc_min) + float(ctx.profile.get("PEAK_DISCHARGE_RESERVE_SOC", 20.0))

    if peak_price >= float(ctx.very_expensive_threshold):
        # plan discharge only within X hours before peak (default 1h)
        window_h = float(ctx.profile.get("PEAK_DISCHARGE_WINDOW_H", 1.0))
        if ctx.now >= peak.start - timedelta(hours=window_h):
            if ctx.soc >= reserve_soc_for_peak_discharge:
                r.action = "discharge"
                r.status = "planning_discharge_planned"
                r.next_peak = peak.start.isoformat()
                r.reason = "discharge_during_price_peak"
                r.target_soc = ctx.soc_min
                return r

    # ---- Charge planning based on peak and margin ----
    margin = max(float(ctx.profit_margin_pct or 0.0), 0.0) / 100.0
    target_price = peak_price * (1.0 - margin)

    pre_peak = [p for p in ctx.price_series if p.end <= peak.start]
    if len(pre_peak) < 4:
        r.status = "planning_peak_detected_insufficient_window"
        r.blocked_by = "price_data"
        return r

    min_price = min(p.price_per_kwh for p in pre_peak)
    tolerance = max(0.01, float(min_price) * 0.03)

    # If we are at (or very near) daily low before the peak -> charge now
    if ctx.now < peak.start and float(ctx.price_now) <= float(min_price) + tolerance:
        target_soc = min(float(ctx.soc_max), float(ctx.soc) + float(ctx.profile.get("PLANNING_CHARGE_SOC_STEP", 30.0)))
        r.action = "charge"
        r.watts = float(max(ctx.max_charge_w, 0.0))
        r.status = "planning_charge_now"
        r.next_peak = peak.start.isoformat()
        r.reason = "charge_at_daily_low"
        r.target_soc = target_soc
        return r

    cheap = [p for p in pre_peak if p.price_per_kwh <= target_price]
    if not cheap:
        r.status = "planning_waiting_for_cheap_window"
        r.blocked_by = "price_data"
        r.next_peak = peak.start.isoformat()
        r.reason = "waiting_for_cheap_price"
        return r

    # valley selection: near minimum of cheap window
    min_p = min(p.price_per_kwh for p in cheap)
    valley_tol = max(0.01, float(min_p) * 0.04)

    valley = [p for p in cheap if p.price_per_kwh <= float(min_p) + valley_tol] or cheap
    valley.sort(key=lambda p: p.start)

    in_valley_now = any(p.start <= ctx.now < p.end for p in valley)
    target_soc = min(float(ctx.soc_max), float(ctx.soc) + float(ctx.profile.get("PLANNING_CHARGE_SOC_STEP", 30.0)))

    if in_valley_now:
        r.action = "charge"
        r.watts = float(max(ctx.max_charge_w, 0.0))
        r.status = "planning_charge_now"
        r.next_peak = peak.start.isoformat()
        r.reason = "charge_in_best_price_valley"
        r.latest_start = ctx.now.isoformat()
        r.target_soc = target_soc
        return r

    # next valley slot
    nxt = next((p for p in valley if p.end > ctx.now), None)
    if not nxt:
        last_cheap = max(cheap, key=lambda p: p.start)
        r.status = "planning_waiting_for_cheap_window"
        r.next_peak = peak.start.isoformat()
        r.reason = "waiting_for_last_chance_window"
        r.latest_start = last_cheap.start.isoformat()
        r.target_soc = target_soc
        return r

    r.status = "planning_waiting_for_cheap_window"
    r.next_peak = peak.start.isoformat()
    r.reason = "waiting_for_best_price_valley"
    r.latest_start = nxt.start.isoformat()
    r.target_soc = target_soc
    return r


# ----------------------------
# Decision Engine
# ----------------------------

class DecisionEngine:
    """
    V2 decision engine: single source of truth for priorities.
    Coordinator supplies Context + persist values, gets Decision back.
    """

    def evaluate(self, ctx: DecisionContext) -> Decision:
        # ---- clamps from profile (safety) ----
        max_in_profile = float(ctx.profile.get("MAX_INPUT_W", ctx.max_charge_w))
        max_out_profile = float(ctx.profile.get("MAX_OUTPUT_W", ctx.max_discharge_w))
        max_charge = min(float(ctx.max_charge_w), max_in_profile)
        max_discharge = min(float(ctx.max_discharge_w), max_out_profile)

        # ---- mode gates ----
        # Winter-manual mode should behave like auto regarding planning + peak discharge.
        planning_enabled = ctx.ai_mode in ("automatic", "winter")  # map to your const values in coordinator
        peak_discharge_enabled = ctx.ai_mode in ("automatic", "winter")

        # ---- emergency latch (handled in coordinator persist usually, but we respect it) ----
        emergency_active = bool(ctx.emergency_active_latched or (ctx.soc <= ctx.emergency_soc))

        # ---- planning evaluation ----
        planning = evaluate_price_planning(ctx, planning_enabled=planning_enabled)

        # planning charge should happen if:
        planning_charge_now = (
            planning_enabled
            and planning.action == "charge"
            and planning.status == "planning_charge_now"
            and (ctx.soc < float(planning.target_soc or ctx.soc_max))
            and not emergency_active
        )

        # peak discharge should be executed only close to peak (planning returns that only close to peak)
        planning_discharge_now = (
            peak_discharge_enabled
            and planning.action == "discharge"
            and planning.status == "planning_discharge_planned"
            and not emergency_active
            and (ctx.soc > ctx.soc_min)
        )

        # ---- price based discharge (economic) ----
        # Only in automatic/winter logic scope (same rationale as V1)
        price_based_discharge_active = (
            planning_enabled
            and ctx.price_now is not None
            and ctx.avg_charge_price is not None
            and float(ctx.price_now) >= float(ctx.expensive_threshold)
            and float(ctx.price_now) > float(ctx.avg_charge_price)
            and ctx.soc > (ctx.soc_min + float(ctx.profile.get("PRICE_DISCHARGE_RESERVE_SOC", 5.0)))
        )

        # ---- planning latch (anti-flutter for charging only) ----
        latch_until_iso: Optional[str] = None
        latch_hold = False
        if ctx.planning_latch_until and ctx.now < ctx.planning_latch_until:
            # hold only if we are already charging due to planning
            if ctx.prev_power_state == "charging" and ctx.last_charge_reason == "planning":
                latch_hold = True
                latch_until_iso = ctx.planning_latch_until.isoformat()

        # Defaults (idle)
        ac_mode: ZendureMode = "INPUT"
        in_w = 0.0
        out_w = 0.0
        recommendation = "standby"
        decision_reason = "standby"
        power_state: PowerState = "idle"
        discharge_target = float(ctx.prev_discharge_target_w or 0.0)

        next_planned_action = "none"
        next_planned_time = ""

        # ---- planning transparency (next action) ----
        if planning.action == "discharge" and planning.next_peak:
            next_planned_action = "discharge"
            next_planned_time = planning.next_peak
        elif planning.status == "planning_waiting_for_cheap_window" and planning.latest_start:
            next_planned_action = "charge"
            next_planned_time = planning.latest_start
        elif planning.status == "planning_charge_now":
            next_planned_action = "charge"
            next_planned_time = ctx.now.isoformat()

        # ---- PRIORITY 1: Emergency ----
        if emergency_active:
            ac_mode = "INPUT"
            in_w = float(_clamp(ctx.emergency_charge_w, 0.0, max_charge))
            out_w = 0.0
            recommendation = "emergency"
            decision_reason = "emergency_latched_charge"
            power_state = "charging"
            discharge_target = 0.0
            latch_until_iso = None  # no latch in emergency

        # ---- PRIORITY 2: Planning charge (Auto + Winter-manual) OR latch-hold ----
        elif latch_hold:
            ac_mode = "INPUT"
            in_w = float(max_charge)
            out_w = 0.0
            recommendation = "charge"
            decision_reason = "planning_latch_hold"
            power_state = "charging"
            discharge_target = 0.0

        elif planning_charge_now:
            ac_mode = "INPUT"
            in_w = float(max_charge)
            out_w = 0.0
            recommendation = "charge"
            decision_reason = planning.reason or "planning_charge_now"
            power_state = "charging"
            discharge_target = 0.0
            # set latch for 10 min (coordinator persists datetime)
            latch_until_iso = (ctx.now + timedelta(minutes=float(ctx.profile.get("PLANNING_LATCH_MIN", 10.0)))).isoformat()

        # ---- PRIORITY 3: Price-based discharge (Auto + Winter-manual) ----
        elif price_based_discharge_active:
            ac_mode = "OUTPUT"
            recommendation = "discharge"
            decision_reason = "price_based_discharge"
            out_w = delta_discharge_w(
                profile=ctx.profile,
                deficit_w=ctx.net_grid_w,
                prev_out_w=float(ctx.prev_discharge_target_w or 0.0),
                max_discharge_w=max_discharge,
                soc=ctx.soc,
                soc_min=ctx.soc_min,
            )
            in_w = 0.0
            power_state = "discharging" if out_w > 0 else "idle"
            discharge_target = float(out_w)
            latch_until_iso = None

        # ---- PRIORITY 4: Peak discharge (Auto + Winter-manual, close to peak) ----
        elif planning_discharge_now:
            ac_mode = "OUTPUT"
            recommendation = "discharge"
            decision_reason = "planning_discharge_peak"
            out_w = delta_discharge_w(
                profile=ctx.profile,
                deficit_w=ctx.net_grid_w,
                prev_out_w=float(ctx.prev_discharge_target_w or 0.0),
                max_discharge_w=max_discharge,
                soc=ctx.soc,
                soc_min=ctx.soc_min,
            )
            in_w = 0.0
            power_state = "discharging" if out_w > 0 else "idle"
            discharge_target = float(out_w)
            latch_until_iso = None

        # ---- PRIORITY 5: Manual mode (true manual) ----
        elif ctx.ai_mode == "manual":
            latch_until_iso = None
            if ctx.manual_action == "standby":
                ac_mode = "INPUT"
                in_w = 0.0
                out_w = 0.0
                recommendation = "standby"
                decision_reason = "manual_standby"
                power_state = "idle"
                discharge_target = 0.0
            elif ctx.manual_action == "charge":
                ac_mode = "INPUT"
                in_w = float(max_charge)
                out_w = 0.0
                recommendation = "charge"
                decision_reason = "manual_charge"
                power_state = "charging"
                discharge_target = 0.0
            elif ctx.manual_action == "discharge":
                ac_mode = "OUTPUT"
                in_w = 0.0
                out_w = delta_discharge_w(
                    profile=ctx.profile,
                    deficit_w=ctx.net_grid_w,
                    prev_out_w=float(ctx.prev_discharge_target_w or 0.0),
                    max_discharge_w=max_discharge,
                    soc=ctx.soc,
                    soc_min=ctx.soc_min,
                )
                recommendation = "discharge"
                decision_reason = "manual_discharge"
                power_state = "discharging" if out_w > 0 else "idle"
                discharge_target = float(out_w)

        # ---- PRIORITY 6: Normal operation (PV / load based) ----
        else:
            # Enter/continue discharging if deficit + load and soc > soc_min
            if ctx.house_load_w > float(ctx.profile.get("HOUSE_LOAD_MIN_W", 150.0)) and ctx.net_grid_w > float(ctx.profile.get("DEFICIT_MIN_W", 80.0)) and ctx.soc > ctx.soc_min:
                ac_mode = "OUTPUT"
                recommendation = "discharge"
                decision_reason = "state_discharging"
                out_w = delta_discharge_w(
                    profile=ctx.profile,
                    deficit_w=ctx.net_grid_w,
                    prev_out_w=float(ctx.prev_discharge_target_w or 0.0),
                    max_discharge_w=max_discharge,
                    soc=ctx.soc,
                    soc_min=ctx.soc_min,
                )
                in_w = 0.0
                power_state = "discharging" if out_w > 0 else "idle"
                discharge_target = float(out_w)

            # Charge from PV surplus
            elif ctx.real_pv_surplus and ctx.soc < ctx.soc_max:
                ac_mode = "INPUT"
                recommendation = "charge"
                # NEW: grid-follow to reduce export (user report: 1kW export in auto)
                in_w = grid_follow_charge_w(
                    profile=ctx.profile,
                    net_grid_w=ctx.net_grid_w,
                    prev_in_w=float(ctx.last_set_input_w or 0.0),
                    max_charge_w=max_charge,
                )
                out_w = 0.0
                decision_reason = "state_charging_grid_follow"
                power_state = "charging"
                discharge_target = 0.0

            else:
                ac_mode = "INPUT"
                in_w = 0.0
                out_w = 0.0
                recommendation = "standby"
                decision_reason = "state_idle"
                power_state = "idle"
                discharge_target = 0.0

        # ---- SOC limit guard (directional) ----
        if ctx.soc_limit == 1 and ac_mode == "INPUT" and in_w > 0:
            in_w = 0.0
            recommendation = "standby"
            decision_reason = "soc_limit_upper"
            power_state = "idle"

        if ctx.soc_limit == 2 and ac_mode == "OUTPUT" and out_w > 0:
            out_w = 0.0
            discharge_target = 0.0
            recommendation = "standby"
            decision_reason = "soc_limit_lower"
            power_state = "idle"

        # ---- enforce SoC-min on discharge ----
        if ac_mode == "OUTPUT" and ctx.soc <= ctx.soc_min:
            ac_mode = "INPUT"
            out_w = 0.0
            discharge_target = 0.0
            if recommendation == "discharge":
                recommendation = "standby"
            decision_reason = "soc_min_enforced"
            power_state = "idle"

        # ---- never set both ----
        if ac_mode == "OUTPUT":
            in_w = 0.0
        if ac_mode == "INPUT":
            out_w = 0.0
            discharge_target = 0.0

        # ---- AI status mapping (string keys should match your sensor state mapping) ----
        if ctx.ai_mode == "manual":
            ai_status = "manual"
        elif emergency_active:
            ai_status = "emergency_charge"
        elif power_state == "charging":
            ai_status = "charge_surplus"
        elif power_state == "discharging":
            if decision_reason in ("price_based_discharge", "expensive_discharge"):
                ai_status = "expensive_discharge"
            elif decision_reason.startswith("very_expensive"):
                ai_status = "very_expensive_force"
            else:
                ai_status = "cover_deficit"
        else:
            ai_status = "standby"

        # ---- planning flags (single source of truth) ----
        planning_active = planning.action in ("charge", "discharge") and planning_enabled

        return Decision(
            ac_mode=ac_mode,
            input_w=float(in_w),
            output_w=float(out_w),
            recommendation=recommendation,
            decision_reason=decision_reason,
            ai_status=ai_status,
            power_state=power_state,
            discharge_target_w=float(discharge_target),

            planning_checked=True,
            planning_status=planning.status,
            planning_blocked_by=planning.blocked_by,
            planning_active=bool(planning_active),
            planning_reason=planning.reason,
            planning_target_soc=planning.target_soc,
            planning_next_peak=planning.next_peak,

            next_planned_action=str(next_planned_action),
            next_planned_action_time=str(next_planned_time or ""),

            planning_latch_until=latch_until_iso,
        )
