from __future__ import annotations
from dataclasses import dataclass


@dataclass
class PowerContext:
    soc: float
    soc_min: float
    soc_max: float

    max_charge_w: float
    max_discharge_w: float

    grid_import_w: float
    grid_export_w: float

    prev_discharge_w: float
    prev_charge_w: float

    profile: dict


class PowerController:

    # --------------------------------------------------
    # Delta discharge (EXAKT aus V2.0.4 übernommen)
    # --------------------------------------------------

    @staticmethod
    def delta_discharge(ctx: PowerContext) -> float:
        p = ctx.profile

        TARGET_IMPORT = float(p["TARGET_IMPORT_W"])
        DEADBAND = float(p["DEADBAND_W"])
        EXPORT_GUARD = float(p["EXPORT_GUARD_W"])

        KP_UP = float(p["KP_UP"])
        KP_DOWN = float(p["KP_DOWN"])
        MAX_STEP_UP = float(p["MAX_STEP_UP"])
        MAX_STEP_DOWN = float(p["MAX_STEP_DOWN"])

        KEEPALIVE_MIN_DEFICIT = float(p["KEEPALIVE_MIN_DEFICIT_W"])
        KEEPALIVE_MIN_OUTPUT = float(p["KEEPALIVE_MIN_OUTPUT_W"])

        if ctx.soc <= ctx.soc_min:
            return 0.0

        net = float(ctx.grid_import_w) - float(ctx.grid_export_w)
        out_w = float(ctx.prev_discharge_w or 0.0)

        if net < -EXPORT_GUARD:
            cut = (abs(net) + TARGET_IMPORT) * 1.4
            out_w = max(0.0, out_w - cut)
            return min(float(ctx.max_discharge_w), out_w)

        err = net - TARGET_IMPORT

        if err > DEADBAND:
            step = min(MAX_STEP_UP, max(40.0, KP_UP * err))
            out_w += step

        elif err < -DEADBAND:
            step = min(MAX_STEP_DOWN, max(60.0, KP_DOWN * abs(err)))
            out_w -= step

        out_w = max(0.0, min(float(ctx.max_discharge_w), out_w))

        if (
            ctx.prev_discharge_w > KEEPALIVE_MIN_OUTPUT
            and ctx.grid_import_w <= KEEPALIVE_MIN_DEFICIT
        ):
            out_w = max(out_w, KEEPALIVE_MIN_OUTPUT)

        return out_w


    # --------------------------------------------------
    # Delta charge (EXAKT aus V2.0.4 übernommen)
    # --------------------------------------------------

    @staticmethod
    def delta_charge(ctx: PowerContext) -> float:
        p = ctx.profile

        TARGET_EXPORT = float(p.get("TARGET_EXPORT_W", 10.0))
        DEADBAND = float(p["DEADBAND_W"])
        EXPORT_GUARD = float(p["EXPORT_GUARD_W"])

        KP_UP = float(p["KP_UP"])
        KP_DOWN = float(p["KP_DOWN"])

        MAX_STEP_UP = float(p["MAX_STEP_UP"]) * 0.5
        MAX_STEP_DOWN = float(p["MAX_STEP_DOWN"]) * 0.5

        if ctx.soc >= ctx.soc_max:
            return 0.0

        net = float(ctx.grid_import_w) - float(ctx.grid_export_w)
        in_w = float(ctx.prev_charge_w or 0.0)

        if net > DEADBAND:
            step = min(MAX_STEP_DOWN, max(60.0, KP_DOWN * abs(net)))
            in_w -= step
            return max(0.0, min(float(ctx.max_charge_w), in_w))

        target_net = -TARGET_EXPORT
        err = target_net - net

        if net < -(EXPORT_GUARD):
            step = min(MAX_STEP_UP * 1.5, max(40.0, KP_UP * abs(err)))
            in_w += step
            return max(0.0, min(float(ctx.max_charge_w), in_w))

        if err > DEADBAND:
            step = min(MAX_STEP_UP, max(30.0, KP_UP * err))
            in_w += step

        elif err < -DEADBAND:
            step = min(MAX_STEP_DOWN, max(40.0, KP_DOWN * abs(err)))
            in_w -= step

        in_w = max(0.0, min(float(ctx.max_charge_w), in_w))
        return in_w
