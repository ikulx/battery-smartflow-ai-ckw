from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Literal, Optional

from .power_controller import PowerController, PowerContext


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

    profile: dict
    prev_discharge_w: float
    prev_charge_w: float

    battery_capacity_kwh: float

    peak_factor: float = 1.35


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
    # --------------------------------------------------
    # Delta controllers (delegated to PowerController)
    # --------------------------------------------------

    def _to_power_ctx(self, ctx: DecisionContext) -> PowerContext:
        # Keep this as a single mapping place → reduces error risk.
        return PowerContext(
            soc=float(ctx.soc),
            soc_min=float(ctx.soc_min),
            soc_max=float(ctx.soc_max),
            max_charge_w=float(ctx.max_charge_w),
            max_discharge_w=float(ctx.max_discharge_w),
            grid_import_w=float(ctx.grid_import_w),
            grid_export_w=float(ctx.grid_export_w),
            prev_discharge_w=float(ctx.prev_discharge_w or 0.0),
            prev_charge_w=float(ctx.prev_charge_w or 0.0),
            profile=dict(ctx.profile or {}),
        )

    def _delta_discharge(self, ctx: DecisionContext) -> float:
        return PowerController.delta_discharge(self._to_power_ctx(ctx))

    def _delta_charge(self, ctx: DecisionContext) -> float:
        return PowerController.delta_charge(self._to_power_ctx(ctx))

    # --------------------------------------------------
    # Adaptive peak detection
    # --------------------------------------------------

    def _detect_adaptive_peak(self, ctx: DecisionContext) -> bool:
        """
        Detects a real-time adaptive price peak.
        No minimum duration. Immediate reaction.
        """
        if not ctx.price_points or ctx.price_now is None:
            return False

        prices = [p.price for p in ctx.price_points if p is not None]
        if not prices:
            return False

        avg_price = sum(prices) / len(prices)

        peak_factor = float(ctx.peak_factor or 1.35)
        MIN_PEAK_MARGIN_CT = 0.03  # at least +3ct above average

        threshold = max(
            avg_price * peak_factor,
            avg_price + MIN_PEAK_MARGIN_CT,
        )

        return float(ctx.price_now) >= threshold

    # --------------------------------------------------
    # Adaptive planning (physically correct)
    # --------------------------------------------------

    def _evaluate_adaptive_planning(self, ctx: DecisionContext) -> Optional[DecisionResult]:
        """
        Adaptive planning with real capacity-based latest-start calculation.
        """
        if (
            ctx.ai_mode not in ("automatic", "winter")
            or not ctx.price_points
            or ctx.price_now is None
            or ctx.soc >= ctx.soc_max
            or ctx.battery_capacity_kwh <= 0
            or ctx.max_charge_w <= 0
        ):
            return None

        prices = [p.price for p in ctx.price_points]
        if not prices:
            return None

        avg_price = sum(prices) / len(prices)

        # -----------------------------
        # 1️⃣ Detect peak
        # -----------------------------
        peak_factor = float(ctx.peak_factor or 1.35)
        MIN_PEAK_MARGIN_CT = 0.03

        peak_threshold = max(
            avg_price * peak_factor,
            avg_price + MIN_PEAK_MARGIN_CT,
        )

        peak_slots = [p for p in ctx.price_points if p.price >= peak_threshold]
        if not peak_slots:
            return None

        future_peaks = [p for p in peak_slots if p.start > ctx.now]
        if not future_peaks:
            return None

        next_peak = min(p.start for p in future_peaks)

        # -----------------------------
        # 2️⃣ Real capacity calculation
        # -----------------------------
        soc_gap_pct = max(0.0, float(ctx.soc_max) - float(ctx.soc))
        required_kwh = float(ctx.battery_capacity_kwh) * (soc_gap_pct / 100.0)

        charge_power_kw = float(ctx.max_charge_w) / 1000.0
        if charge_power_kw <= 0:
            return None

        hours_needed = required_kwh / charge_power_kw

        # 10% Sicherheitsaufschlag
        hours_needed *= 1.10
        hours_needed = max(hours_needed, 0.25)  # mindestens 15 Minuten

        latest_start = next_peak - timedelta(hours=hours_needed)

        # -----------------------------
        # 3️⃣ Valley detection
        # -----------------------------
        pre_peak_slots = [p for p in ctx.price_points if p.end <= next_peak]
        if not pre_peak_slots:
            return None

        min_price = min(p.price for p in pre_peak_slots)
        valley_threshold = min_price * 1.04  # 4% above lowest

        valley_slots = [p for p in pre_peak_slots if p.price <= valley_threshold]

        in_valley = any(slot.start <= ctx.now < slot.end for slot in valley_slots)

        # -----------------------------
        # 4️⃣ Decision
        # -----------------------------
        if in_valley:
            return DecisionResult(
                action="charge",
                ac_mode="input",
                charge_w=float(ctx.max_charge_w),
                discharge_w=0.0,
                reason="planning_charge_now",
                target_soc=float(ctx.soc_max),
            )

        if ctx.now >= latest_start:
            return DecisionResult(
                action="charge",
                ac_mode="input",
                charge_w=float(ctx.max_charge_w),
                discharge_w=0.0,
                reason="planning_latest_start",
                target_soc=float(ctx.soc_max),
            )

        return None

    # --------------------------------------------------
    # MAIN EVALUATION (verhaltensneutral zu deiner letzten Version)
    # --------------------------------------------------

    def evaluate(self, ctx: DecisionContext) -> DecisionResult:
        # 1️⃣ Emergency
        if ctx.soc <= ctx.emergency_soc:
            return DecisionResult(
                action="emergency",
                ac_mode="input",
                charge_w=min(float(ctx.max_charge_w), float(ctx.emergency_charge_w)),
                discharge_w=0.0,
                reason="emergency_latched_charge",
            )

        # 2️⃣ Peak / very expensive discharge (always dynamic)
        if (
            ctx.soc > ctx.soc_min + 5
            and ctx.ai_mode in ("automatic", "winter")
        ):
            adaptive_peak = self._detect_adaptive_peak(ctx)

            if adaptive_peak:
                discharge_w = self._delta_discharge(ctx)
                return DecisionResult(
                    action="discharge",
                    ac_mode="output",
                    charge_w=0.0,
                    discharge_w=discharge_w,
                    reason="adaptive_peak_discharge",
                )

            if ctx.price_now is not None and ctx.price_now >= ctx.very_expensive_threshold:
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

        # 4️⃣ Adaptive planning
        planning_result = self._evaluate_adaptive_planning(ctx)
        if planning_result:
            return planning_result

        # 4.5️⃣ PV surplus charging (all modes)
        if ctx.soc < ctx.soc_max:
            charge_w = self._delta_charge(ctx)
            if charge_w > 0:
                return DecisionResult(
                    action="charge",
                    ac_mode="input",
                    charge_w=charge_w,
                    discharge_w=0.0,
                    reason="pv_surplus_charge",
                )

        # 5️⃣ Summer logic (fully delta-controlled)
        if (
            ctx.ai_mode == "summer"
            or (ctx.ai_mode == "automatic" and ctx.season == "summer")
        ):
            if ctx.soc > ctx.soc_min:
                discharge_w = self._delta_discharge(ctx)
                if discharge_w > 0:
                    return DecisionResult(
                        action="discharge",
                        ac_mode="output",
                        charge_w=0.0,
                        discharge_w=discharge_w,
                        reason="summer_cover_deficit",
                    )

        # 6️⃣ Manual
        if ctx.ai_mode == "manual":
            if ctx.manual_action == "charge":
                return DecisionResult(
                    action="charge",
                    ac_mode="input",
                    charge_w=float(ctx.max_charge_w),
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

        # 7️⃣ Default idle
        return DecisionResult(
            action="idle",
            ac_mode="input",
            charge_w=0.0,
            discharge_w=0.0,
            reason="idle",
        )
