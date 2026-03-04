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

    valley_factor: float = 0.85
    very_cheap_price: Optional[float] = None


@dataclass
class DecisionResult:
    action: ActionType
    ac_mode: ZendureMode
    charge_w: float
    discharge_w: float
    reason: str
    target_soc: Optional[float] = None


# ==================================================
# RULE BASE
# ==================================================

class BaseRule:
    def evaluate(self, engine: "DecisionEngine", ctx: DecisionContext) -> Optional[DecisionResult]:
        raise NotImplementedError


# ==================================================
# RULES
# ==================================================

class EmergencyRule(BaseRule):
    def evaluate(self, engine, ctx):
        if ctx.soc <= ctx.emergency_soc:
            return DecisionResult(
                action="emergency",
                ac_mode="input",
                charge_w=min(ctx.max_charge_w, ctx.emergency_charge_w),
                discharge_w=0.0,
                reason="emergency_latched_charge",
            )
        return None


class PeakRule(BaseRule):
    def evaluate(self, engine, ctx):
        if (
            ctx.soc > ctx.soc_min + 5
            and ctx.ai_mode in ("automatic", "winter")
        ):
            if engine._detect_adaptive_peak(ctx):
                discharge_w = engine._delta_discharge(ctx)
                return DecisionResult(
                    action="discharge",
                    ac_mode="output",
                    charge_w=0.0,
                    discharge_w=discharge_w,
                    reason="adaptive_peak_discharge",
                )

            if (
                ctx.price_now is not None
                and ctx.price_now >= ctx.very_expensive_threshold
            ):
                discharge_w = engine._delta_discharge(ctx)
                return DecisionResult(
                    action="discharge",
                    ac_mode="output",
                    charge_w=0.0,
                    discharge_w=discharge_w,
                    reason="very_expensive_force_discharge",
                )
        return None


class ArbitrageRule(BaseRule):
    def evaluate(self, engine, ctx):
        if (
            ctx.price_now is not None
            and ctx.avg_charge_price is not None
            and ctx.price_now >= ctx.expensive_threshold
            and ctx.price_now > ctx.avg_charge_price
            and ctx.soc > ctx.soc_min + 5
            and ctx.ai_mode in ("automatic", "winter")
        ):
            discharge_w = engine._delta_discharge(ctx)
            return DecisionResult(
                action="discharge",
                ac_mode="output",
                charge_w=0.0,
                discharge_w=discharge_w,
                reason="price_based_discharge",
            )
        return None


class PlanningRule(BaseRule):
    def evaluate(self, engine, ctx):
        return engine._evaluate_adaptive_planning(ctx)


class PvRule(BaseRule):
    def evaluate(self, engine, ctx):
        if ctx.soc < ctx.soc_max:
            charge_w = engine._delta_charge(ctx)
            if charge_w > 0:
                return DecisionResult(
                    action="charge",
                    ac_mode="input",
                    charge_w=charge_w,
                    discharge_w=0.0,
                    reason="pv_surplus_charge",
                )
        return None


class SummerRule(BaseRule):
    def evaluate(self, engine, ctx):
        if (
            ctx.ai_mode == "summer"
            or (ctx.ai_mode == "automatic" and ctx.season == "summer")
        ):
            if ctx.soc > ctx.soc_min:
                discharge_w = engine._delta_discharge(ctx)
                if discharge_w > 0:
                    return DecisionResult(
                        action="discharge",
                        ac_mode="output",
                        charge_w=0.0,
                        discharge_w=discharge_w,
                        reason="summer_cover_deficit",
                    )
        return None


class ManualRule(BaseRule):
    def evaluate(self, engine, ctx):
        if ctx.ai_mode != "manual":
            return None

        if ctx.manual_action == "charge":
            return DecisionResult(
                action="charge",
                ac_mode="input",
                charge_w=ctx.max_charge_w,
                discharge_w=0.0,
                reason="manual_charge",
            )

        if ctx.manual_action == "discharge":
            discharge_w = engine._delta_discharge(ctx)
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


# ==================================================
# ENGINE
# ==================================================

class DecisionEngine:

    def __init__(self):
        self._rules = [
            EmergencyRule(),
            PeakRule(),
            ArbitrageRule(),
            PlanningRule(),
            PvRule(),
            SummerRule(),
            ManualRule(),
        ]

    # -----------------------------
    # Delta delegation
    # -----------------------------

    def _to_power_ctx(self, ctx: DecisionContext) -> PowerContext:
        return PowerContext(
            soc=ctx.soc,
            soc_min=ctx.soc_min,
            soc_max=ctx.soc_max,
            max_charge_w=ctx.max_charge_w,
            max_discharge_w=ctx.max_discharge_w,
            grid_import_w=ctx.grid_import_w,
            grid_export_w=ctx.grid_export_w,
            prev_discharge_w=ctx.prev_discharge_w,
            prev_charge_w=ctx.prev_charge_w,
            profile=ctx.profile,
        )

    def _delta_discharge(self, ctx: DecisionContext) -> float:
        return PowerController.delta_discharge(self._to_power_ctx(ctx))

    def _delta_charge(self, ctx: DecisionContext) -> float:
        return PowerController.delta_charge(self._to_power_ctx(ctx))

    # -----------------------------
    # Peak detection (unchanged)
    # -----------------------------

    def _detect_adaptive_peak(self, ctx: DecisionContext) -> bool:
        if not ctx.price_points or ctx.price_now is None:
            return False

        prices = [p.price for p in ctx.price_points]
        if not prices:
            return False

        avg_price = sum(prices) / len(prices)

        # -----------------------------------------
        # Optional absolute cheap price filter
        # -----------------------------------------

        if ctx.very_cheap_price is not None:
            if ctx.price_now > ctx.very_cheap_price:
                return None

        threshold = max(
            avg_price * ctx.peak_factor,
            avg_price + 0.03,
        )

        return ctx.price_now >= threshold

    # -----------------------------
    # Planning (unchanged)
    # -----------------------------

    def _evaluate_adaptive_planning(self, ctx: DecisionContext) -> Optional[DecisionResult]:
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

        peak_threshold = max(
            avg_price * ctx.peak_factor,
            avg_price + 0.03,
        )

        peak_slots = [p for p in ctx.price_points if p.price >= peak_threshold]
        future_peaks = [p for p in peak_slots if p.start > ctx.now]
        if not future_peaks:
            return None

        next_peak = min(p.start for p in future_peaks)

        soc_gap_pct = max(0.0, ctx.soc_max - ctx.soc)
        required_kwh = ctx.battery_capacity_kwh * (soc_gap_pct / 100.0)

        charge_power_kw = ctx.max_charge_w / 1000.0
        if charge_power_kw <= 0:
            return None

        hours_needed = required_kwh / charge_power_kw
        hours_needed = max(hours_needed * 1.10, 0.25)

        latest_start = next_peak - timedelta(hours=hours_needed)

        # ------------------------------------------------
        # Peak energy sufficiency check (V3 strategic fix)
        # ------------------------------------------------

        # 1️⃣ Dauer des kommenden Peaks berechnen
        # Wir betrachten alle zusammenhängenden Peak-Slots
        peak_slots_sorted = sorted(peak_slots, key=lambda p: p.start)

        contiguous_peak_duration_h = 0.0
        current_block_start = None
        current_block_end = None

        for slot in peak_slots_sorted:
            if slot.start <= next_peak:
                if current_block_start is None:
                    current_block_start = slot.start
                    current_block_end = slot.end
                elif slot.start <= current_block_end:
                    current_block_end = max(current_block_end, slot.end)
                else:
                    break

        if current_block_start and current_block_end:
            contiguous_peak_duration_h = (
                (current_block_end - current_block_start).total_seconds() / 3600.0
            )

        # 2️⃣ Maximal mögliche Entladeenergie während Peak
        max_discharge_kw = ctx.max_discharge_w / 1000.0
        required_peak_kwh = contiguous_peak_duration_h * max_discharge_kw

        # Sicherheitsaufschlag 15 %
        required_peak_kwh *= 1.15

        # 3️⃣ Verfügbare Energie oberhalb soc_min
        usable_pct = max(0.0, ctx.soc - ctx.soc_min)
        available_kwh = ctx.battery_capacity_kwh * (usable_pct / 100.0)

        # 4️⃣ Wenn Akku Peak bereits vollständig bedienen kann → NICHT laden
        if available_kwh >= required_peak_kwh:
            return None

        # ------------------------------------------------
        # Regulärer Latest-Start-Trigger
        # ------------------------------------------------

        if ctx.now >= latest_start:
            return DecisionResult(
                action="charge",
                ac_mode="input",
                charge_w=ctx.max_charge_w,
                discharge_w=0.0,
                reason="planning_latest_start",
                target_soc=ctx.soc_max,
            )

        return None

    # -----------------------------
    # MAIN EVALUATION
    # -----------------------------

    def evaluate(self, ctx: DecisionContext) -> DecisionResult:
        for rule in self._rules:
            result = rule.evaluate(self, ctx)
            if result:
                return result

        return DecisionResult(
            action="idle",
            ac_mode="input",
            charge_w=0.0,
            discharge_w=0.0,
            reason="idle",
        )
