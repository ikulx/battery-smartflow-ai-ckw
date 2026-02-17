# decision_engine.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, List, Literal
from datetime import datetime, timedelta


# --------------------------------------------------
# TYPES
# --------------------------------------------------

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


@dataclass
class DecisionResult:
    action: ActionType
    ac_mode: ZendureMode
    charge_w: float
    discharge_w: float
    reason: str
    target_soc: Optional[float] = None


# --------------------------------------------------
# ENGINE
# --------------------------------------------------

class DecisionEngine:

    def evaluate(self, ctx: DecisionContext) -> DecisionResult:

        # --------------------------------------------------
        # 1️⃣ EMERGENCY (absolute highest priority)
        # --------------------------------------------------
        if ctx.soc <= ctx.emergency_soc:
            return DecisionResult(
                action="emergency",
                ac_mode="input",
                charge_w=min(ctx.max_charge_w, ctx.emergency_charge_w),
                discharge_w=0.0,
                reason="emergency_latched_charge",
            )

        # --------------------------------------------------
        # 2️⃣ VERY EXPENSIVE PEAK DISCHARGE
        # --------------------------------------------------
        if (
            ctx.price_now is not None
            and ctx.price_now >= ctx.very_expensive_threshold
            and ctx.soc > ctx.soc_min + 5
            and ctx.ai_mode in ("automatic", "winter")
        ):
            return DecisionResult(
                action="discharge",
                ac_mode="output",
                charge_w=0.0,
                discharge_w=ctx.max_discharge_w,
                reason="very_expensive_force_discharge",
            )

        # --------------------------------------------------
        # 3️⃣ PRICE ARBITRAGE DISCHARGE
        # --------------------------------------------------
        if (
            ctx.price_now is not None
            and ctx.avg_charge_price is not None
            and ctx.price_now >= ctx.expensive_threshold
            and ctx.price_now > ctx.avg_charge_price
            and ctx.soc > ctx.soc_min + 5
            and ctx.ai_mode in ("automatic", "winter")
        ):
            return DecisionResult(
                action="discharge",
                ac_mode="output",
                charge_w=0.0,
                discharge_w=ctx.max_discharge_w,
                reason="price_based_discharge",
            )

        # --------------------------------------------------
        # 4️⃣ PLANNING CHARGE
        # --------------------------------------------------
        if (
            ctx.ai_mode in ("automatic", "winter")
            and ctx.price_now is not None
            and ctx.price_points
            and ctx.soc < ctx.soc_max
        ):
            cheapest = min(p.price for p in ctx.price_points)
            margin_factor = 1.0 - (ctx.profit_margin_pct / 100.0)
            target_price = cheapest * margin_factor

            if ctx.price_now <= target_price:
                return DecisionResult(
                    action="charge",
                    ac_mode="input",
                    charge_w=ctx.max_charge_w,
                    discharge_w=0.0,
                    reason="planning_charge_now",
                )

        # --------------------------------------------------
        # 5️⃣ SUMMER / SURPLUS
        # --------------------------------------------------
        if (
            ctx.ai_mode == "summer"
            or (ctx.ai_mode == "automatic" and ctx.season == "summer")
        ):
            if ctx.grid_import_w > 80 and ctx.soc > ctx.soc_min:
                return DecisionResult(
                    action="discharge",
                    ac_mode="output",
                    charge_w=0.0,
                    discharge_w=min(ctx.max_discharge_w, ctx.grid_import_w),
                    reason="summer_cover_deficit",
                )

            if ctx.grid_export_w > 80 and ctx.soc < ctx.soc_max:
                return DecisionResult(
                    action="charge",
                    ac_mode="input",
                    charge_w=min(ctx.max_charge_w, ctx.grid_export_w),
                    discharge_w=0.0,
                    reason="pv_surplus_charge",
                )

        # --------------------------------------------------
        # 6️⃣ MANUAL
        # --------------------------------------------------
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
                return DecisionResult(
                    action="discharge",
                    ac_mode="output",
                    charge_w=0.0,
                    discharge_w=ctx.max_discharge_w,
                    reason="manual_discharge",
                )

            return DecisionResult(
                action="idle",
                ac_mode="input",
                charge_w=0.0,
                discharge_w=0.0,
                reason="manual_idle",
            )

        # --------------------------------------------------
        # 7️⃣ DEFAULT
        # --------------------------------------------------
        return DecisionResult(
            action="idle",
            ac_mode="input",
            charge_w=0.0,
            discharge_w=0.0,
            reason="idle",
        )
