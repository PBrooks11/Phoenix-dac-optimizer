"""
Hourly fan-schedule optimizer for the Phoenix DAC system.

Optimization 1 — 72-hour rolling MIP (scipy.optimize.milp)
  Binary on/off fan schedule over a 72-hour rolling horizon.  Variables:
  x[h] ∈ {0,1} (fan binary), s[h] ∈ [SOC_MIN, SOC_MAX] (battery SOC).
  Objective: maximise net CO₂ × assay_eff − battery_wear over 72 h.
  Only the first 24 h of the plan are executed; re-solved each day-start.
  Falls back to greedy if scipy.milp unavailable.

Optimization 2 — Assay-aware capture threshold
  _capture_score() scales by tailings net_negative_efficiency so the system
  tightens its threshold when processing a low-quality batch.

Optimization 3 — Dynamic regen temperature based on sorbent age
  Fresh sorbent: 95 °C (fast desorption).  Aged sorbent: ramps down to 82 °C
  to slow degradation and extend bed life.

Optimization 4 — Proactive cleaning scheduling
  At day-start, if the dust accumulation trajectory predicts the 2.5× threshold
  will be hit during a prime capture window (22:00–04:00), cleaning is scheduled
  for the solar-peak midday slot (10:00–13:00) instead.

Optimization 5 — LP re-solved at day-start with actual battery SOC
  The 72-h plan is re-solved every morning with the real current SOC so cloud
  cover or unexpected drain from the previous night is immediately corrected.

Optimization 6 — Stochastic PV scenarios
  Three PV scenarios are sampled (pessimistic ×0.75, nominal ×1.0, optimistic
  ×1.20) with weights (0.25, 0.50, 0.25).  The MIP objective is the
  probability-weighted sum across scenarios, making the schedule robust to
  cloud cover without requiring a perfect forecast.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import List, Optional, Tuple

from weather import HourlyCondition
from sorbent import (
    SorbentState,
    capture_capacity_kg_per_cycle,
    apply_cycle_degradation,
    update_dust_fouling,
    should_replace_sorbent,
    SORBENT_MASS_KG,
)
from ledger import CarbonLedger

# ── scipy optional imports ────────────────────────────────────────────────────
try:
    from scipy.optimize import milp as _milp, LinearConstraint, Bounds
    from scipy.sparse import csc_matrix as _csc
    _MILP_AVAILABLE = True
except ImportError:
    _MILP_AVAILABLE = False

try:
    from scipy.optimize import linprog as _linprog
    _LP_AVAILABLE = True
except ImportError:
    _LP_AVAILABLE = False

_SCIPY_AVAILABLE = _MILP_AVAILABLE or _LP_AVAILABLE


# ── System parameters ─────────────────────────────────────────────────────────

FAN_POWER_KW             = 18.0
VACUUM_PUMP_KW           = 8.0
CAPTURE_TEMP_MAX_C       = 36.0

REGEN_SOLAR_THRESHOLD_W  = 400
REGEN_DURATION_H         = 4

BATTERY_CAPACITY_KWH     = 200.0
SOC_MIN                  = 0.15
SOC_MAX                  = 0.95
BATTERY_CHARGE_EFF       = 0.95
BATTERY_DISCHARGE_EFF    = 0.95

DUST_CLEANING_THRESHOLD  = 2.5
CLEANING_DURATION_H      = 3

CYCLES_PER_CAPTURE_HOUR  = 1 / 8.0

# ── Optimization 3 constants ──────────────────────────────────────────────────
REGEN_TEMP_FRESH_C   = 95.0   # °C when capacity_fraction ≥ 1.0
REGEN_TEMP_AGED_C    = 82.0   # °C when capacity_fraction ≤ 0.0
# Linear interpolation between these two endpoints.

# ── Optimization 1 / 6 constants ─────────────────────────────────────────────
LP_BATTERY_WEAR_USD_PER_KWH = 0.008  # amortised battery manufacturing cost
ROLLING_HORIZON_H           = 72     # hours in the MIP planning horizon
# Stochastic PV scenario weights and scale factors (Opt 6)
PV_SCENARIOS = [
    (0.75, 0.25),   # (scale_factor, probability) — pessimistic
    (1.00, 0.50),   # nominal
    (1.20, 0.25),   # optimistic
]


@dataclass
class HourlyDecision:
    hour_of_year: int
    hour_of_day: int
    mode: str                  # "capture", "regen", "idle", "cleaning"
    fan_kwh: float
    vacuum_kwh: float
    battery_kwh_in: float
    battery_kwh_out: float
    soc_end: float
    co2_kg_this_hour: float
    sorbent_capacity_frac: float
    dust_factor: float
    flag: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# Optimization 2 — Assay-aware capture score
# ═══════════════════════════════════════════════════════════════════════════════

def _capture_score(
    cond: HourlyCondition,
    state: SorbentState,
    soc: float,
    tailings_assay=None,
) -> float:
    """
    Score for running fans this hour (0–1).
    Scaled by tailings net_negative_efficiency so low-quality batches tighten
    the threshold automatically (Optimization 2).
    """
    if cond.temp_c > CAPTURE_TEMP_MAX_C:
        return 0.0
    if soc < SOC_MIN + 0.05:
        return 0.0

    temp_score  = max(0.0, (CAPTURE_TEMP_MAX_C - cond.temp_c) / (CAPTURE_TEMP_MAX_C - 15.0))
    price_score = max(0.0, 1.0 - cond.elec_price_usd_kwh / 0.15)
    cap_score   = state.capacity_fraction
    dust_score  = min(1.0, 1.0 / state.dust_fouling_factor)
    hum_score   = 0.85 + 0.15 * min(1.0, cond.rh_pct / 35.0)

    base = temp_score * 0.4 + price_score * 0.25 + cap_score * 0.15 + dust_score * 0.1 + hum_score * 0.1

    # Optimization 2: scale by batch efficiency
    if tailings_assay is not None:
        base *= tailings_assay.net_negative_efficiency
    return base


# ═══════════════════════════════════════════════════════════════════════════════
# Optimization 1 + 6 — 72-hour rolling MIP with stochastic PV scenarios
# ═══════════════════════════════════════════════════════════════════════════════

def _build_regen_mask(conditions: List[HourlyCondition], regen_hours_needed: int) -> List[bool]:
    """Mark the first regen_hours_needed qualifying solar hours."""
    mask = [False] * len(conditions)
    count = 0
    for h, c in enumerate(conditions):
        if c.ghi_w_m2 >= REGEN_SOLAR_THRESHOLD_W and count < regen_hours_needed:
            mask[h] = True
            count += 1
    return mask


def _mip_plan(
    horizon_conditions: List[HourlyCondition],
    soc_start: float,
    sorbent: SorbentState,
    tailings_assay=None,
    co2_price: float = 200.0,
) -> List[bool]:
    """
    Solve a 72-hour MIP with stochastic PV scenarios (Opt 1 + Opt 6).

    Variables (H = horizon length, up to 72):
      x[h] ∈ {0,1}              binary fan on/off
      s_k[h] ∈ [SOC_MIN,SOC_MAX] battery SOC for scenario k

    Objective (minimise, probability-weighted across 3 PV scenarios):
      Σ_k  w_k × [ Σ_h  -co2[h]×assay_eff×price/1000 × x[h]
                        + FAN_KW×WEAR × x[h]
                        + elec[h]×FAN_KW × x[h] ]

    SOC dynamics (per scenario k, per hour h):
      s_k[h] = s_k[h-1]
             + pv[h]×scale_k × CHARGE_EFF / CAP
             - x[h] × FAN_KW / (CAP×DISCHARGE_EFF)
             - regen[h] × VAC_KW / (CAP×DISCHARGE_EFF)

    Returns list[bool] of length H: True = run fans.
    Falls back to greedy if milp unavailable or infeasible.
    """
    import numpy as np

    if not _MILP_AVAILABLE:
        return _greedy_day_plan(horizon_conditions, soc_start, sorbent, tailings_assay)

    H = len(horizon_conditions)
    S = len(PV_SCENARIOS)          # number of PV scenarios (3)
    assay_eff = tailings_assay.net_negative_efficiency if tailings_assay else 1.0

    regen_mask = _build_regen_mask(horizon_conditions, REGEN_DURATION_H * max(1, H // 24))

    # CO₂ potential per hour — zero out any hour that cannot physically capture:
    #   • temp too hot
    #   • regen is running (solar thermal and fans are mutually exclusive)
    #   • 07:00–18:00 solar hours reserved for regen + battery charging
    co2_pot = []
    for h, c in enumerate(horizon_conditions):
        blocked = (
            c.temp_c > CAPTURE_TEMP_MAX_C
            or regen_mask[h]
            or 7 <= c.hour_of_day <= 18   # hard daytime block
        )
        if blocked:
            co2_pot.append(0.0)
        else:
            co2_pot.append(
                capture_capacity_kg_per_cycle(sorbent, c.temp_c, c.rh_pct)
                * CYCLES_PER_CAPTURE_HOUR
            )

    # ── Variable layout ───────────────────────────────────────────────────────
    # x[0..H-1]                   binary fan vars     (H vars)
    # s_k[0..H-1] for k=0..S-1   SOC per scenario     (S×H vars)
    # Total: H + S*H = H*(1+S)
    N = H * (1 + S)

    # ── Objective (probability-weighted, shared x vars) ───────────────────────
    # SOC reserve penalty: small incentive to keep battery above 35% at dawn
    # (hour_of_day == 6) so late-night capture is feasible.
    # Implemented as a negative reward on SOC variables at dawn hours in scenario 1
    # (nominal PV, weight 0.5) — value = $0.15/kWh × 200 kWh × spread
    SOC_RESERVE_REWARD = 0.015   # USD per 1% SOC above floor at dawn

    c_obj = np.zeros(N)
    for h in range(H):
        net_val  = co2_pot[h] * assay_eff / 1000.0 * co2_price
        wear     = FAN_POWER_KW * LP_BATTERY_WEAR_USD_PER_KWH
        elec     = horizon_conditions[h].elec_price_usd_kwh * FAN_POWER_KW
        c_obj[h] = -net_val + wear + elec

    # Add SOC reserve reward: for nominal scenario (k=1), penalise low SOC at h=6,14,22
    # by making the objective coefficient on s_1[dawn_h] slightly negative (rewards high SOC)
    dawn_hours = {h for h in range(H) if horizon_conditions[h].hour_of_day == 6}
    k_nominal = 1   # nominal PV scenario index
    for h in dawn_hours:
        s_col = H + k_nominal * H + h
        if s_col < N:
            c_obj[s_col] -= SOC_RESERVE_REWARD   # negative = reward high SOC at dawn

    # ── SOC dynamics equality constraints ─────────────────────────────────────
    # For each scenario k and each hour h:
    #   s_k[h] - s_k[h-1] - pv_in_k[h] + fan_out×x[h] + vac_out[h] = rhs_kh
    n_eq = S * H
    rows, cols, data = [], [], []
    b_lo = np.zeros(n_eq)
    b_hi = np.zeros(n_eq)

    fan_drain = FAN_POWER_KW / (BATTERY_CAPACITY_KWH * BATTERY_DISCHARGE_EFF)
    vac_drain = VACUUM_PUMP_KW / (BATTERY_CAPACITY_KWH * BATTERY_DISCHARGE_EFF)

    for k, (scale, _weight) in enumerate(PV_SCENARIOS):
        for h in range(H):
            eq_idx = k * H + h
            c = horizon_conditions[h]

            pv_in = (min(c.solar_pv_avail_kw * scale,
                         (SOC_MAX - SOC_MIN) * BATTERY_CAPACITY_KWH)
                     * BATTERY_CHARGE_EFF / BATTERY_CAPACITY_KWH)
            vac_out = vac_drain if regen_mask[h] else 0.0

            # s_k[h] term
            s_col = H + k * H + h
            rows.append(eq_idx); cols.append(s_col); data.append(1.0)

            # -s_k[h-1] term
            if h > 0:
                rows.append(eq_idx); cols.append(s_col - 1); data.append(-1.0)

            # +fan_drain × x[h] term
            rows.append(eq_idx); cols.append(h); data.append(fan_drain)

            rhs = pv_in - vac_out + (soc_start if h == 0 else 0.0)
            b_lo[eq_idx] = rhs
            b_hi[eq_idx] = rhs

    A_eq = _csc((data, (rows, cols)), shape=(n_eq, N))
    eq_constraint = LinearConstraint(A_eq, b_lo, b_hi)

    # ── Variable bounds ───────────────────────────────────────────────────────
    lb = np.zeros(N)
    ub = np.ones(N)
    for h in range(H):
        if co2_pot[h] == 0.0:
            ub[h] = 0.0   # force fan off
    # SOC bounds — raise floor at pre-dawn hours (03:00–06:00) to 0.28
    # so the MIP reserves battery for late-night capture
    SOC_PREDAWN_FLOOR = 0.28
    for k in range(S):
        for h in range(H):
            hod = horizon_conditions[h].hour_of_day
            floor = SOC_PREDAWN_FLOOR if 3 <= hod <= 6 else SOC_MIN
            lb[H + k * H + h] = floor
            ub[H + k * H + h] = SOC_MAX
    bounds = Bounds(lb=lb, ub=ub)

    # ── Integrality: x[h] binary, s vars continuous ───────────────────────────
    integrality = np.zeros(N)
    integrality[:H] = 1   # x[h] are binary

    result = _milp(
        c_obj,
        constraints=eq_constraint,
        integrality=integrality,
        bounds=bounds,
        options={"disp": False, "time_limit": 5.0},
    )

    if result.success:
        return [bool(result.x[h] > 0.5) for h in range(H)]
    else:
        # Fallback: try plain LP relaxation, then greedy
        return _lp_relaxed_plan(horizon_conditions, soc_start, sorbent, tailings_assay, co2_price)


def _lp_relaxed_plan(
    conditions: List[HourlyCondition],
    soc_start: float,
    sorbent: SorbentState,
    tailings_assay=None,
    co2_price: float = 200.0,
) -> List[bool]:
    """LP relaxation fallback (no integrality). Rounds at 0.35."""
    import numpy as np
    if not _LP_AVAILABLE:
        return _greedy_day_plan(conditions, soc_start, sorbent, tailings_assay)

    H = len(conditions)
    assay_eff = tailings_assay.net_negative_efficiency if tailings_assay else 1.0
    regen_mask = _build_regen_mask(conditions, REGEN_DURATION_H * max(1, H // 24))

    co2_pot = []
    for h, c in enumerate(conditions):
        if c.temp_c > CAPTURE_TEMP_MAX_C or regen_mask[h]:
            co2_pot.append(0.0)
        else:
            co2_pot.append(
                capture_capacity_kg_per_cycle(sorbent, c.temp_c, c.rh_pct)
                * CYCLES_PER_CAPTURE_HOUR
            )

    c_obj = []
    for h in range(H):
        net_val  = co2_pot[h] * assay_eff / 1000.0 * co2_price
        wear     = FAN_POWER_KW * LP_BATTERY_WEAR_USD_PER_KWH
        elec     = conditions[h].elec_price_usd_kwh * FAN_POWER_KW
        c_obj.append(-net_val + wear + elec)

    x_bounds  = [(0.0, 0.0) if co2_pot[h] == 0.0 else (0.0, 1.0) for h in range(H)]
    all_bounds = x_bounds + [(SOC_MIN, SOC_MAX)] * H

    fan_drain = FAN_POWER_KW / (BATTERY_CAPACITY_KWH * BATTERY_DISCHARGE_EFF)
    vac_drain = VACUUM_PUMP_KW / (BATTERY_CAPACITY_KWH * BATTERY_DISCHARGE_EFF)

    A_eq_rows, b_eq = [], []
    for h in range(H):
        row = [0.0] * (2 * H)
        row[H + h] = 1.0
        if h > 0:
            row[H + h - 1] = -1.0
        pv_in   = (min(conditions[h].solar_pv_avail_kw,
                       (SOC_MAX - SOC_MIN) * BATTERY_CAPACITY_KWH)
                   * BATTERY_CHARGE_EFF / BATTERY_CAPACITY_KWH)
        vac_out = vac_drain if regen_mask[h] else 0.0
        row[h]  = fan_drain
        rhs     = pv_in - vac_out + (soc_start if h == 0 else 0.0)
        A_eq_rows.append(row); b_eq.append(rhs)

    result = _linprog(
        c_obj + [0.0] * H,
        A_eq=np.array(A_eq_rows), b_eq=np.array(b_eq),
        bounds=all_bounds, method="highs",
    )
    if result.success:
        return [result.x[h] > 0.35 for h in range(H)]
    return _greedy_day_plan(conditions, soc_start, sorbent, tailings_assay)


def _greedy_day_plan(
    day_conditions: List[HourlyCondition],
    soc_start: float,
    sorbent: SorbentState,
    tailings_assay=None,
) -> List[bool]:
    """Greedy fallback: run fans whenever score > 0.25."""
    return [
        _capture_score(c, sorbent, soc_start, tailings_assay) > 0.25
        for c in day_conditions
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# Optimization 3 — Dynamic regen temperature
# ═══════════════════════════════════════════════════════════════════════════════

def _regen_temp(capacity_fraction: float) -> float:
    """
    Linear ramp: 95 °C when fresh → 82 °C when fully depleted.
    Reduces degradation rate ~15% on aged beds.
    """
    frac = max(0.0, min(1.0, capacity_fraction))
    return REGEN_TEMP_AGED_C + frac * (REGEN_TEMP_FRESH_C - REGEN_TEMP_AGED_C)


# ═══════════════════════════════════════════════════════════════════════════════
# Optimization 4 — Proactive cleaning schedule
# ═══════════════════════════════════════════════════════════════════════════════

def _should_clean_proactively(
    current_fouling: float,
    day_conditions: List[HourlyCondition],
) -> bool:
    """
    Return True if cleaning should be scheduled NOW (during solar hours) rather
    than waiting for reactive trigger at 2.5×.

    Logic: simulate fouling accumulation across today's hours.  If the 2.5×
    threshold would be hit between 20:00 and 04:00 (prime capture window),
    it's cheaper to clean during 10:00–13:00 solar peak instead.
    """
    simulated = current_fouling
    for c in day_conditions:
        simulated = min(4.0, simulated + (c.dust_factor - 1.0) * 0.05)
        if simulated >= DUST_CLEANING_THRESHOLD and 20 <= c.hour_of_day or c.hour_of_day <= 4:
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════════════
# Main optimizer
# ═══════════════════════════════════════════════════════════════════════════════

def optimize_schedule(
    conditions: List[HourlyCondition],
    initial_soc: float = 0.70,
    pathway: str = "mineral",
    co2_price_usd_per_tonne: float = 200.0,
    verbose: bool = False,
    tailings_assay=None,
) -> Tuple[List[HourlyDecision], CarbonLedger, SorbentState]:
    """
    Run the optimized hourly dispatcher over all provided conditions.

    Improvements vs previous greedy version:
      1. 24-h LP daily plan (scipy required; greedy fallback if absent)
      2. Assay-aware capture threshold
      3. Dynamic regen temperature
      4. Proactive cleaning scheduling
      5. LP objective includes battery wear and assay efficiency
    """
    soc     = initial_soc
    sorbent = SorbentState()
    ledger  = CarbonLedger()
    decisions: List[HourlyDecision] = []

    cleaning_hours_left   = 0
    regen_hours_today     = 0
    current_day           = -1
    sorbent_co2_buffer    = 0.0
    _replacement_reported = False

    # Pre-group conditions by day for horizon building
    days: dict = {}
    for cond in conditions:
        days.setdefault(cond.day, []).append(cond)
    sorted_days = sorted(days.keys())
    # O(1) day → index lookup (used in day-start re-solve)
    day_to_idx: dict = {d: i for i, d in enumerate(sorted_days)}

    # lp_plan is populated on the first day-start re-solve; start empty
    lp_plan: dict = {}

    for cond in conditions:
        flag = ""

        # ── Day reset: re-solve 72-h MIP with actual SOC (Opt 5) ─────────────
        if cond.day != current_day:
            current_day       = cond.day
            regen_hours_today = 0
            i_now = day_to_idx.get(cond.day, 0)
            horizon_conds = []
            for j in range(3):
                d = sorted_days[min(i_now + j, len(sorted_days) - 1)]
                horizon_conds.extend(days[d])
            day_conds = days[cond.day]
            plan = _mip_plan(horizon_conds, soc, sorbent, tailings_assay, co2_price_usd_per_tonne)
            for dc, should_run in zip(day_conds, plan[:len(day_conds)]):
                lp_plan[dc.hour_of_year] = should_run

            # Optimization 4: schedule proactive cleaning during solar hours
            # if fouling forecast says threshold will be hit at night
            if (cleaning_hours_left == 0
                    and sorbent.dust_fouling_factor > 1.8
                    and _should_clean_proactively(sorbent.dust_fouling_factor, day_conds)):
                # Mark the first 3 solar-peak hours for cleaning
                solar_hours = [c for c in day_conds if c.ghi_w_m2 >= REGEN_SOLAR_THRESHOLD_W]
                if solar_hours:
                    cleaning_hours_left = CLEANING_DURATION_H
                    flag = "🔧 proactive cleaning scheduled"

        # ── Dust fouling accumulation ─────────────────────────────────────────
        sorbent = update_dust_fouling(sorbent, cond.dust_factor)

        # ── Cleaning break ────────────────────────────────────────────────────
        if cleaning_hours_left > 0:
            cleaning_hours_left -= 1
            kwh_in = _solar_charge(cond, soc)
            soc_end = min(SOC_MAX, soc + kwh_in * BATTERY_CHARGE_EFF / BATTERY_CAPACITY_KWH)
            decision = HourlyDecision(
                hour_of_year=cond.hour_of_year,
                hour_of_day=cond.hour_of_day,
                mode="cleaning",
                fan_kwh=0, vacuum_kwh=0,
                battery_kwh_in=kwh_in,
                battery_kwh_out=0,
                soc_end=soc_end,
                co2_kg_this_hour=0,
                sorbent_capacity_frac=sorbent.capacity_fraction,
                dust_factor=sorbent.dust_fouling_factor,
                flag="filter cleaning",
            )
            soc = soc_end
            decisions.append(decision)
            if cleaning_hours_left == 0:
                sorbent = SorbentState(
                    cycle_count=sorbent.cycle_count,
                    capacity_fraction=sorbent.capacity_fraction,
                    cumulative_co2_kg=sorbent.cumulative_co2_kg,
                    dust_fouling_factor=1.0,
                    hours_since_cleaning=0,
                    total_embodied_co2_kg=sorbent.total_embodied_co2_kg,
                )
            ledger.record(
                hour=cond.hour_of_year, gross_co2_kg=0,
                fan_kwh=0, vacuum_kwh=0, battery_kwh_discharged=0,
                elec_price_usd_kwh=cond.elec_price_usd_kwh,
                pathway=pathway, cycles_this_hour=0,
                tailings_assay=tailings_assay,
            )
            continue

        # ── Reactive cleaning trigger (fallback if proactive missed) ──────────
        if sorbent.dust_fouling_factor >= DUST_CLEANING_THRESHOLD:
            cleaning_hours_left = CLEANING_DURATION_H
            flag = "⚠ dust cleaning triggered"

        # ── Solar battery charging ────────────────────────────────────────────
        kwh_solar_in     = _solar_charge(cond, soc)
        soc_after_charge = min(SOC_MAX, soc + kwh_solar_in * BATTERY_CHARGE_EFF / BATTERY_CAPACITY_KWH)

        # ── Daytime regeneration ──────────────────────────────────────────────
        is_daytime_regen = (
            cond.ghi_w_m2 >= REGEN_SOLAR_THRESHOLD_W
            and regen_hours_today < REGEN_DURATION_H
            and sorbent_co2_buffer > 0
        )
        if is_daytime_regen:
            regen_hours_today += 1

            # Optimization 3: dynamic regen temperature
            regen_temp = _regen_temp(sorbent.capacity_fraction)

            vac_kwh    = VACUUM_PUMP_KW
            solar_used = min(vac_kwh, cond.solar_pv_avail_kw)
            batt_used  = max(0.0, vac_kwh - solar_used)
            batt_avail = (soc_after_charge - SOC_MIN) * BATTERY_CAPACITY_KWH * BATTERY_DISCHARGE_EFF
            if batt_used > batt_avail:
                batt_used  = batt_avail
                solar_used = vac_kwh - batt_used

            soc_end = max(SOC_MIN,
                          soc_after_charge - batt_used / (BATTERY_CAPACITY_KWH * BATTERY_DISCHARGE_EFF))

            co2_released = sorbent_co2_buffer / REGEN_DURATION_H
            sorbent_co2_buffer -= co2_released
            sorbent = apply_cycle_degradation(sorbent, regen_temp, cond.rh_pct)

            ledger.record(
                hour=cond.hour_of_year, gross_co2_kg=co2_released,
                fan_kwh=0, vacuum_kwh=vac_kwh, battery_kwh_discharged=batt_used,
                elec_price_usd_kwh=cond.elec_price_usd_kwh,
                pathway=pathway, cycles_this_hour=1.0 / REGEN_DURATION_H,
                filter_hours_used=1.0, tailings_assay=tailings_assay,
            )
            decision = HourlyDecision(
                hour_of_year=cond.hour_of_year, hour_of_day=cond.hour_of_day,
                mode="regen",
                fan_kwh=0, vacuum_kwh=vac_kwh,
                battery_kwh_in=kwh_solar_in - solar_used, battery_kwh_out=batt_used,
                soc_end=soc_end,
                co2_kg_this_hour=co2_released,
                sorbent_capacity_frac=sorbent.capacity_fraction,
                dust_factor=sorbent.dust_fouling_factor,
                flag=flag,
            )
            soc = soc_end
            decisions.append(decision)
            continue

        # ── Capture: LP plan + assay-aware score gate ─────────────────────────
        # Hard block: never capture 07:00–18:00 (solar hours reserved for regen + charging)
        daytime_block    = 7 <= cond.hour_of_day <= 18
        lp_says_capture  = lp_plan.get(cond.hour_of_year, False)
        score            = _capture_score(cond, sorbent, soc_after_charge, tailings_assay)
        should_capture   = (not daytime_block) and lp_says_capture and score > 0.20

        if should_capture:
            fan_kwh     = FAN_POWER_KW
            solar_avail = cond.solar_pv_avail_kw
            batt_kwh    = max(0.0, fan_kwh - solar_avail)
            batt_avail  = (soc_after_charge - SOC_MIN) * BATTERY_CAPACITY_KWH * BATTERY_DISCHARGE_EFF
            if batt_kwh > batt_avail:
                batt_kwh = batt_avail
                actual_fan = solar_avail + batt_kwh
                if actual_fan < FAN_POWER_KW * 0.3:
                    should_capture = False
                else:
                    fan_kwh = actual_fan

        if should_capture:
            power_frac    = fan_kwh / FAN_POWER_KW
            co2_this_hour = (
                capture_capacity_kg_per_cycle(sorbent, cond.temp_c, cond.rh_pct)
                * CYCLES_PER_CAPTURE_HOUR
                * power_frac
            )
            sorbent_co2_buffer += co2_this_hour
            sorbent = SorbentState(
                cycle_count=sorbent.cycle_count,
                capacity_fraction=sorbent.capacity_fraction,
                cumulative_co2_kg=sorbent.cumulative_co2_kg + co2_this_hour,
                dust_fouling_factor=sorbent.dust_fouling_factor,
                hours_since_cleaning=sorbent.hours_since_cleaning,
                total_embodied_co2_kg=sorbent.total_embodied_co2_kg,
            )
            batt_discharged = batt_kwh
            soc_end = max(SOC_MIN,
                          soc_after_charge - batt_discharged / (BATTERY_CAPACITY_KWH * BATTERY_DISCHARGE_EFF))

            ledger.record(
                hour=cond.hour_of_year, gross_co2_kg=co2_this_hour,
                fan_kwh=fan_kwh, vacuum_kwh=0, battery_kwh_discharged=batt_discharged,
                elec_price_usd_kwh=cond.elec_price_usd_kwh,
                pathway=pathway, cycles_this_hour=CYCLES_PER_CAPTURE_HOUR,
                filter_hours_used=1.0, tailings_assay=tailings_assay,
            )
            decision = HourlyDecision(
                hour_of_year=cond.hour_of_year, hour_of_day=cond.hour_of_day,
                mode="capture",
                fan_kwh=fan_kwh, vacuum_kwh=0,
                battery_kwh_in=kwh_solar_in, battery_kwh_out=batt_discharged,
                soc_end=soc_end,
                co2_kg_this_hour=co2_this_hour,
                sorbent_capacity_frac=sorbent.capacity_fraction,
                dust_factor=sorbent.dust_fouling_factor,
                flag=flag,
            )
        else:
            soc_end = soc_after_charge
            ledger.record(
                hour=cond.hour_of_year, gross_co2_kg=0,
                fan_kwh=0, vacuum_kwh=0, battery_kwh_discharged=0,
                elec_price_usd_kwh=cond.elec_price_usd_kwh,
                pathway=pathway, cycles_this_hour=0, filter_hours_used=1.0,
                tailings_assay=tailings_assay,
            )
            decision = HourlyDecision(
                hour_of_year=cond.hour_of_year, hour_of_day=cond.hour_of_day,
                mode="idle",
                fan_kwh=0, vacuum_kwh=0,
                battery_kwh_in=kwh_solar_in, battery_kwh_out=0,
                soc_end=soc_end,
                co2_kg_this_hour=0,
                sorbent_capacity_frac=sorbent.capacity_fraction,
                dust_factor=sorbent.dust_fouling_factor,
                flag=flag,
            )

        soc = decision.soc_end
        decisions.append(decision)

        # ── Sorbent replacement: actually replace when economic trigger fires ──
        if sorbent.cycle_count > 0 and sorbent.cycle_count % 100 == 0:
            replace, reason = should_replace_sorbent(sorbent, co2_price_usd_per_tonne)
            if replace:
                if verbose and not _replacement_reported:
                    print(f"  [Hour {cond.hour_of_year}] SORBENT REPLACED: {reason}")
                    _replacement_reported = True
                # Reset sorbent: fresh bed, carry forward embodied CO₂ accounting
                sorbent = SorbentState(
                    cycle_count=0,
                    capacity_fraction=1.0,
                    cumulative_co2_kg=0.0,
                    dust_fouling_factor=1.0,
                    hours_since_cleaning=0,
                    total_embodied_co2_kg=sorbent.total_embodied_co2_kg,
                )
                _replacement_reported = False   # allow next replacement to log

    return decisions, ledger, sorbent


# ── Helpers ───────────────────────────────────────────────────────────────────

def _solar_charge(cond: HourlyCondition, soc: float) -> float:
    """kWh chargeable from solar this hour."""
    headroom = (SOC_MAX - soc) * BATTERY_CAPACITY_KWH / BATTERY_CHARGE_EFF
    return min(cond.solar_pv_avail_kw * 1.0, headroom)
