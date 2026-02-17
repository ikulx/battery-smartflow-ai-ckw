# custom_components/battery_smartflow_ai/decision_engine.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Literal, Dict, Any
from datetime import datetime, timezone


Action = Literal["idle", "charge", "discharge"]
ZendureMode = Literal["input", "output"]
AiMode = Literal["automatic", "summer", "winter", "manual"]


# ------------------------------------------------------------
# Decision
# ------------------------------------------------------------
@dataclass(frozen=True)
class Decision:
    action: Action
    mode: ZendureMode
    input_w: float
    output_w: float
    reason: str
    lock: bool = False  # reserved for future, currently always False
    meta: Optional[Dict[str, Any]] = None


# ------------------------------------------------------------
# Context (input to decision engine)
# ------------------------------------------------------------
@dataclass
class DecisionContext:
    # modes
    ai_mode: AiMode
    manual_action: Literal["standby", "charge", "discharge"]

    # time
    now: datetime

    # soc
    soc: float
    soc_min: float
    soc_max: float

    # emergency
    emergency_soc: float
    emergency_charge_w: float
    emergency_active: bool

    # prices
    price_now: Optional[float]
    expensive_threshold: float
    very_expensive_threshold: float
    profit_margin_pct: float
    avg_charge_price: Optional[float]

    # power / grid
    pv_w: float
    house_load_w: float
    net_grid_w: float              # +import / -export
    grid_import_w: float
    grid_export_w: float
    real_pv_surplus: bool

    # hardware state (current measured / last applied)
    current_mode: ZendureMode
    current_input_w: float
    current_output_w: float

    # planning (already evaluated by coordinator OR by helper)
    planning_action: Literal["none", "charge", "discharge"]
    planning_status: str
    planning_next_peak: Optional[str]      # ISO
    planning_target_soc: Optional[float]   # float
    planning_reason: Optional[str]

    # soc limit / bms overrides
    soc_limit: Optional[int]  # 0/1/2 or None

    # device profile
    profile_key: str
    profile: Dict[str, Any]


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def clamp(v: float, vmin: float, vmax: float) -> float:
    return max(vmin, min(vmax, v))


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_utc(val: Optional[str]) -> Optional[datetime]:
    if not val:
        return None
    try:
        # datetime.fromisoformat accepts offsets; ensure UTC for comparisons
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        return _as_utc(dt)
    except Exception:
        return None


# ------------------------------------------------------------
# Delta discharge controller (profile-driven)
# ------------------------------------------------------------
def delta_discharge_w(
    *,
    deficit_w: float,
    prev_out_w: float,
    max_discharge: float,
    soc: float,
    soc_min: float,
    profile: Dict[str, Any],
    allow_zero: bool = True,
) -> float:
    """
    Drives grid import close to TARGET_IMPORT_W, avoids export oscillations.
    All tuning comes from device profile.
    """

    TARGET_IMPORT_W = float(profile["TARGET_IMPORT_W"])
    DEADBAND_W = float(profile["DEADBAND_W"])
    EXPORT_GUARD_W = float(profile["EXPORT_GUARD_W"])

    KP_UP = float(profile["KP_UP"])
    KP_DOWN = float(profile["KP_DOWN"])
    MAX_STEP_UP = float(profile["MAX_STEP_UP"])
    MAX_STEP_DOWN = float(profile["MAX_STEP_DOWN"])

    KEEPALIVE_MIN_DEFICIT_W = float(profile["KEEPALIVE_MIN_DEFICIT_W"])
    KEEPALIVE_MIN_OUTPUT_W = float(profile["KEEPALIVE_MIN_OUTPUT_W"])

    # hard constraint: never discharge below soc_min
    if soc <= soc_min + 0.05:
        return 0.0

    net = float(deficit_w)  # + import / - export
    out_w = float(prev_out_w)

    # anti export guard
    if net < -EXPORT_GUARD_W:
        cut = (abs(net) + TARGET_IMPORT_W) * 1.4
        out_w = max(0.0, out_w - cut)
        return float(min(float(max_discharge), out_w))

    # import-target control
    err = net - TARGET_IMPORT_W

    if err > DEADBAND_W:
        step = min(MAX_STEP_UP, max(40.0, KP_UP * err))
        out_w += step
    elif err < -DEADBAND_W:
        step = min(MAX_STEP_DOWN, max(60.0, KP_DOWN * abs(err)))
        out_w -= step
    else:
        out_w = out_w  # hold

    out_w = clamp(out_w, 0.0, float(max_discharge))

    # keep-alive (avoid OUTPUT dropping)
    if allow_zero and deficit_w <= KEEPALIVE_MIN_DEFICIT_W:
        out_w = max(out_w, KEEPALIVE_MIN_OUTPUT_W)

    return float(out_w)


# ------------------------------------------------------------
# Candidates (priorities frozen)
# ------------------------------------------------------------
class EmergencyChargeCandidate:
    PRIORITY = 100

    @staticmethod
    def evaluate(ctx: DecisionContext) -> Optional[Decision]:
        # emergency may latch from coordinator, but we also allow direct trigger
        if not ctx.emergency_active and ctx.soc > ctx.emergency_soc:
            return None

        max_input = float(ctx.profile["MAX_INPUT_W"])
        in_w = clamp(float(ctx.emergency_charge_w), 0.0, max_input)

        if in_w <= 0.0:
            return Decision(
                action="idle",
                mode="input",
                input_w=0.0,
                output_w=0.0,
                reason="emergency_active_but_zero_power",
                lock=False,
            )

        return Decision(
            action="charge",
            mode="input",
            input_w=in_w,
            output_w=0.0,
            reason="emergency_latched_charge",
            lock=False,
        )


class SoCLimitGuardCandidate:
    PRIORITY = 95

    @staticmethod
    def evaluate(ctx: DecisionContext) -> Optional[Decision]:
        # Only blocks the direction, does NOT force opposite action.
        if ctx.soc_limit not in (1, 2):
            return None

        # 1 = upper limit active -> block charge
        if ctx.soc_limit == 1:
            return Decision(
                action="idle",
                mode="input",
                input_w=0.0,
                output_w=0.0,
                reason="soc_limit_upper_block_charge",
                lock=False,
                meta={"soc_limit": 1},
            )

        # 2 = lower limit active -> block discharge
        if ctx.soc_limit == 2:
            return Decision(
                action="idle",
                mode="input",
                input_w=0.0,
                output_w=0.0,
                reason="soc_limit_lower_block_discharge",
                lock=False,
                meta={"soc_limit": 2},
            )

        return None


class PeakDischargeCandidate:
    PRIORITY = 90

    @staticmethod
    def evaluate(ctx: DecisionContext) -> Optional[Decision]:
        # PeakDischarge applies also in manual winter-mode (ai_mode == "winter")
        if ctx.ai_mode not in ("automatic", "winter", "summer"):
            return None
        if ctx.emergency_active:
            return None

        if ctx.planning_action != "discharge":
            return None
        if ctx.planning_status != "planning_discharge_planned":
            return None

        peak_dt = parse_iso_utc(ctx.planning_next_peak)
        if not peak_dt:
            return None

        # discharge only close to peak (next 30 min) or after peak started
        secs_to_peak = (peak_dt - _as_utc(ctx.now)).total_seconds()
        if not (secs_to_peak <= 1800):
            return None

        if ctx.soc <= ctx.soc_min:
            return None

        max_out = float(ctx.profile["MAX_OUTPUT_W"])
        out_w = delta_discharge_w(
            deficit_w=ctx.net_grid_w,
            prev_out_w=ctx.current_output_w,
            max_discharge=max_out,
            soc=ctx.soc,
            soc_min=ctx.soc_min,
            profile=ctx.profile,
        )

        if out_w <= 30.0:
            return None

        return Decision(
            action="discharge",
            mode="output",
            input_w=0.0,
            output_w=out_w,
            reason="peak_discharge",
            lock=False,
            meta={"peak": ctx.planning_next_peak},
        )


class PlanningChargeCandidate:
    PRIORITY = 85

    @staticmethod
    def evaluate(ctx: DecisionContext) -> Optional[Decision]:
        # PlanningCharge should also apply in manual winter-mode
        if ctx.ai_mode not in ("automatic", "winter"):
            return None
        if ctx.emergency_active:
            return None

        if ctx.planning_action != "charge":
            return None
        if ctx.planning_status != "planning_charge_now":
            return None

        target_soc = float(ctx.planning_target_soc or ctx.soc_max)
        if ctx.soc >= min(target_soc, ctx.soc_max) - 0.1:
            return None

        max_in = float(ctx.profile["MAX_INPUT_W"])
        in_w = clamp(float(ctx.profile.get("PLANNING_CHARGE_W", max_in)), 0.0, max_in)
        # Default: full device capability unless you add PLANNING_CHARGE_W into profile later.

        if in_w <= 0.0:
            return None

        return Decision(
            action="charge",
            mode="input",
            input_w=in_w,
            output_w=0.0,
            reason=ctx.planning_reason or "planning_charge_now",
            lock=False,
            meta={"target_soc": target_soc, "peak": ctx.planning_next_peak},
        )


class PriceBasedDischargeCandidate:
    PRIORITY = 70

    @staticmethod
    def evaluate(ctx: DecisionContext) -> Optional[Decision]:
        # applies in automatic/summer/winter
        if ctx.ai_mode not in ("automatic", "summer", "winter"):
            return None
        if ctx.emergency_active:
            return None

        if ctx.price_now is None:
            return None
        if ctx.avg_charge_price is None:
            return None

        if float(ctx.price_now) < float(ctx.expensive_threshold):
            return None
        if float(ctx.price_now) <= float(ctx.avg_charge_price):
            return None

        reserve_soc = float(ctx.soc_min) + 5.0
        if ctx.soc <= reserve_soc:
            return None

        max_out = float(ctx.profile["MAX_OUTPUT_W"])
        out_w = delta_discharge_w(
            deficit_w=ctx.net_grid_w,
            prev_out_w=ctx.current_output_w,
            max_discharge=max_out,
            soc=ctx.soc,
            soc_min=ctx.soc_min,
            profile=ctx.profile,
        )

        if out_w <= 30.0:
            return None

        return Decision(
            action="discharge",
            mode="output",
            input_w=0.0,
            output_w=out_w,
            reason="price_based_discharge",
            lock=False,
            meta={"price_now": ctx.price_now, "avg_charge_price": ctx.avg_charge_price},
        )


class DeficitDischargeCandidate:
    PRIORITY = 60

    @staticmethod
    def evaluate(ctx: DecisionContext) -> Optional[Decision]:
        # normal "autarky" discharge
        if ctx.ai_mode not in ("automatic", "summer", "winter"):
            return None
        if ctx.emergency_active:
            return None

        if ctx.soc <= ctx.soc_min:
            return None

        # Only discharge if importing meaningfully and house has load
        if ctx.grid_import_w <= 80.0:
            return None
        if ctx.house_load_w <= 150.0:
            return None

        max_out = float(ctx.profile["MAX_OUTPUT_W"])

        out_w = delta_discharge_w(
            deficit_w=ctx.net_grid_w,
            prev_out_w=ctx.current_output_w,
            max_discharge=max_out,
            soc=ctx.soc,
            soc_min=ctx.soc_min,
            profile=ctx.profile,
        )

        if out_w <= 30.0:
            return None

        return Decision(
            action="discharge",
            mode="output",
            input_w=0.0,
            output_w=out_w,
            reason="cover_deficit",
            lock=False,
        )


class PVChargeCandidate:
    PRIORITY = 50

    @staticmethod
    def evaluate(ctx: DecisionContext) -> Optional[Decision]:
        # PV charge mainly for automatic/summer (winter may still allow PV charge if you want)
        if ctx.ai_mode not in ("automatic", "summer", "winter"):
            return None
        if ctx.emergency_active:
            return None

        if ctx.soc >= ctx.soc_max - 0.1:
            return None

        # Only charge on real PV surplus (provided by coordinator)
        if not ctx.real_pv_surplus:
            return None

        # Simple PV surplus charge: aim to absorb export, but clamp to profile
        max_in = float(ctx.profile["MAX_INPUT_W"])

        # Try to counter export toward ~0: load export if available, else fallback
        # If you feed ctx.grid_export_w, we can charge roughly that amount (+small buffer).
        desired = max(0.0, float(ctx.grid_export_w) + 50.0)
        in_w = clamp(desired, 0.0, max_in)

        if in_w <= 0.0:
            return None

        return Decision(
            action="charge",
            mode="input",
            input_w=in_w,
            output_w=0.0,
            reason="pv_surplus_charge",
            lock=False,
            meta={"grid_export_w": ctx.grid_export_w},
        )


class ManualOverrideCandidate:
    PRIORITY = 40

    @staticmethod
    def evaluate(ctx: DecisionContext) -> Optional[Decision]:
        # Manual mode: explicit user intent
        if ctx.ai_mode != "manual":
            return None

        max_in = float(ctx.profile["MAX_INPUT_W"])
        max_out = float(ctx.profile["MAX_OUTPUT_W"])

        if ctx.manual_action == "charge":
            return Decision(
                action="charge",
                mode="input",
                input_w=max_in,
                output_w=0.0,
                reason="manual_charge",
                lock=False,
            )

        if ctx.manual_action == "discharge":
            out_w = delta_discharge_w(
                deficit_w=ctx.net_grid_w,
                prev_out_w=ctx.current_output_w,
                max_discharge=max_out,
                soc=ctx.soc,
                soc_min=ctx.soc_min,
                profile=ctx.profile,
            )
            if out_w <= 30.0:
                return Decision(
                    action="idle",
                    mode="input",
                    input_w=0.0,
                    output_w=0.0,
                    reason="manual_discharge_but_low_power",
                    lock=False,
                )
            return Decision(
                action="discharge",
                mode="output",
                input_w=0.0,
                output_w=out_w,
                reason="manual_discharge",
                lock=False,
            )

        return Decision(
            action="idle",
            mode="input",
            input_w=0.0,
            output_w=0.0,
            reason="manual_standby",
            lock=False,
        )


class IdleCandidate:
    PRIORITY = 0

    @staticmethod
    def evaluate(ctx: DecisionContext) -> Decision:
        return Decision(
            action="idle",
            mode="input",
            input_w=0.0,
            output_w=0.0,
            reason="idle",
            lock=False,
        )


# ------------------------------------------------------------
# Decision Engine
# ------------------------------------------------------------
class DecisionEngine:
    """
    Final V2 decision engine.
    Order is priority-driven and frozen.
    """

    CANDIDATES = [
        EmergencyChargeCandidate,
        SoCLimitGuardCandidate,
        PeakDischargeCandidate,
        PlanningChargeCandidate,
        PriceBasedDischargeCandidate,
        DeficitDischargeCandidate,
        PVChargeCandidate,
        ManualOverrideCandidate,  # note: manual still can exist, but higher prios may act in winter-mode
    ]

    @classmethod
    def decide(cls, ctx: DecisionContext) -> Decision:
        # normalize now
        if ctx.now.tzinfo is None:
            ctx.now = ctx.now.replace(tzinfo=timezone.utc)

        # Hard SoC constraints first (safety)
        if ctx.soc >= ctx.soc_max - 0.01:
            # never charge when full
            if ctx.current_mode == "input":
                pass

        # Apply candidates by PRIORITY order (highest first)
        ordered = sorted(cls.CANDIDATES, key=lambda c: int(getattr(c, "PRIORITY", 0)), reverse=True)

        # Special: SoCLimitGuardCandidate blocks direction only.
        # If it returns idle for "block charge", we still allow discharge candidates below if they apply.
        # Implemented by: if soc_limit == 1 and candidate suggests charge -> blocked.
        # Here: we just let SoCLimit return idle, but we DO NOT stop evaluation unless it is emergency.
        blocked_charge = (ctx.soc_limit == 1)
        blocked_discharge = (ctx.soc_limit == 2)

        for cand in ordered:
            d = cand.evaluate(ctx)
            if d is None:
                continue

            # If emergency candidate fired, return immediately
            if cand is EmergencyChargeCandidate:
                return _apply_profile_clamps(ctx, d)

            # Blocked directions
            if d.action == "charge" and blocked_charge:
                # skip this decision and continue searching (e.g. discharge may still be valid)
                continue
            if d.action == "discharge" and blocked_discharge:
                continue

            return _apply_profile_clamps(ctx, d)

        return _apply_profile_clamps(ctx, IdleCandidate.evaluate(ctx))


def _apply_profile_clamps(ctx: DecisionContext, d: Decision) -> Decision:
    """
    Enforce device profile hardware limits and mode coherence.
    """
    max_in = float(ctx.profile["MAX_INPUT_W"])
    max_out = float(ctx.profile["MAX_OUTPUT_W"])

    in_w = float(d.input_w)
    out_w = float(d.output_w)

    # mode coherence
    if d.mode == "input":
        out_w = 0.0
    elif d.mode == "output":
        in_w = 0.0

    in_w = clamp(in_w, 0.0, max_in)
    out_w = clamp(out_w, 0.0, max_out)

    # Zendure quirk: tiny output counts as off -> normalize
    if d.mode == "output" and out_w < 30.0:
        out_w = 0.0

    # if both zero -> idle
    action: Action = d.action
    mode: ZendureMode = d.mode

    if in_w <= 0.0 and out_w <= 0.0:
        action = "idle"
        mode = "input"

    return Decision(
        action=action,
        mode=mode,
        input_w=in_w,
        output_w=out_w,
        reason=d.reason,
        lock=bool(d.lock),
        meta=d.meta,
    )
