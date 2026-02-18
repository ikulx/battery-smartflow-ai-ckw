# decision_engine.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List, Literal
from datetime import datetime


AiMode = Literal["automatic", "summer", "winter", "manual"]
ZendureMode = Literal["input", "output"]
ActionType = Literal["idle", "charge", "discharge", "emergency"]


@dataclass
class PricePoint:
    start: datetime
    end: datetime
    price: float


@dataclass
class DecisionContext:
    now: datetime

    soc: float
    soc_min: float
    soc_max: float

    emergency_soc: float
    emergency_charge_w: float

    max_charge_w: float
    max_discharge_w: float

    grid_import_w: float
    grid_export_w: float
    pv_w: float
    house_load_w: float

    price_now: Optional[float]
    avg_charge_price: Optional[float]
    expensive_threshold: float
    very_expensive_threshold: float
    profit_margin_pct: float
    price_points: List[PricePoint]

    ai_mode: AiMode
    manual_action: Optional[str]
    season: Literal["winter", "summer"]

    profile: dict
    prev_discharge_w: float


@dataclass
class DecisionResult:
    action: ActionType
    ac_mode: ZendureMode
    charge_w: float
    discharge_w: float
    reason: str
    target_soc: Optional[float] = None


class DecisionEngine:

    # --------------------------------------------------
    # Delta discharge controller (profile based)
    # --------------------------------------------------

    def _delta_discharge(self, ctx: DecisionContext) -> float:

        p = ctx.profile

        TARGET_IMPORT = p["TARGET_IMPORT_W"]
        DEADBAND = p["DEADBAND_W"]
        EXPORT_GUARD = p["EXPORT_GUARD_W"]

        KP_UP = p["KP_UP"]
        KP_DOWN = p["KP_DOWN"]
        MAX_STEP_UP = p["MAX_STEP_UP"]
        MAX_STEP_DOWN = p["MAX_STEP_DOWN"]

        KEEPALIVE_MIN_DEFICIT = p["KEEPALIVE_MIN_DEFICIT_W"]
        KEEPALIVE_MIN_OUTPUT = p["KEEPALIVE_MIN_OUTPUT_W"]

        if ctx.soc <= ctx.soc_min:
            return 0.0

        net = ctx.grid_import_w - ctx.grid_export_w
        out_w = float(ctx.prev_discharge_w or 0.0)

        # Anti-export guard
        if net < -EXPORT_GUARD:
            cut = (abs(net) + TARGET_IMPORT) * 1.4
            out_w = max(0.0, out_w - cut)
            return min(ctx.max_discharge_w, out_w)

        err = net - TARGET_IMPORT

        if err > DEADBAND:
            step = min(MAX_STEP_UP, max(40.0, KP_UP * err))
            out_w += step

        elif err < -DEADBAND:
            step = min(MAX_STEP_DOWN, max(60.0, KP_DOWN * abs(err)))
            out_w -= step

        out_w = max(0.0, min(ctx.max_discharge_w, out_w))

        if ctx.grid_import_w <= KEEPALIVE_MIN_DEFICIT:
            out_w = max(out_w, KEEPALIVE_MIN_OUTPUT)

        return out_w

    # --------------------------------------------------
    # Main evaluate
    # --------------------------------------------------

    def evaluate(self, ctx: DecisionContext) -> DecisionResult:

        # 1️⃣ Emergency
        if ctx.soc <= ctx.emergency_soc:
            return DecisionResult(
                action="emergency",
                ac_mode="input",
                charge_w=min(ctx.max_charge_w, ctx.emergency_charge_w),
                discharge_w=0.0,
                reason="emergency_latched_charge",
            )

        # 2️⃣ Very expensive discharge
        if (
            ctx.price_now is not None
            and ctx.price_now >= ctx.very_expensive_threshold
            and ctx.soc > ctx.soc_min + 5
            and ctx.ai_mode in ("automatic", "winter")
        ):
            discharge_w = self._delta_discharge(ctx)
            return DecisionResult(
                action="discharge",
                ac_mode="output",
                charge_w=0.0,
                discharge_w=discharge_w,
                reason="very_expensive_force_discharge",
            )

        # 3️⃣ Arbitrage discharge
        if (
            ctx.price_now is not None
            and ctx.avg_charge_price is not None
            and ctx.price_now >= ctx.expensive_threshold
            and ctx.price_now > ctx.avg_charge_price
            and ctx.soc > ctx.soc_min + 5
            and ctx.ai_mode in ("automatic", "winter")
        ):
            discharge_w = self._delta_discharge(ctx)
            return DecisionResult(
                action="discharge",
                ac_mode="output",
                charge_w=0.0,
                discharge_w=discharge_w,
                reason="price_based_discharge",
            )

        # 4️⃣ Summer logic
        if (
            ctx.ai_mode == "summer"
            or (ctx.ai_mode == "automatic" and ctx.season == "summer")
        ):
            if ctx.grid_import_w > 80 and ctx.soc > ctx.soc_min:
                discharge_w = self._delta_discharge(ctx)
                return DecisionResult(
                    action="discharge",
                    ac_mode="output",
                    charge_w=0.0,
                    discharge_w=discharge_w,
                    reason="summer_cover_deficit",
                )

            if ctx.grid_export_w > 80 and ctx.soc < ctx.soc_max:
                charge_w = min(ctx.max_charge_w, ctx.grid_export_w)
                return DecisionResult(
                    action="charge",
                    ac_mode="input",
                    charge_w=charge_w,
                    discharge_w=0.0,
                    reason="pv_surplus_charge",
                )

        # 5️⃣ Manual
        if ctx.ai_mode == "manual":
            if ctx.manual_action == "charge":
                return DecisionResult(
                    action="charge",
                    ac_mode="input",
                    charge_w=ctx.max_charge_w,
                    discharge_w=0.0,
                    reason="manual_charge",
                )

            if ctx.manual_action == "discharge":
                discharge_w = self._delta_discharge(ctx)
                return DecisionResult(
                    action="discharge",
                    ac_mode="output",
                    charge_w=0.0,
                    discharge_w=discharge_w,
                    reason="manual_discharge",
                )

            return DecisionResult(
                action="idle",
                ac_mode="input",
                charge_w=0.0,
                discharge_w=0.0,
                reason="manual_idle",
            )

        # 6️⃣ Default idle
        return DecisionResult(
            action="idle",
            ac_mode="input",
            charge_w=0.0,
            discharge_w=0.0,
            reason="idle",
        )
