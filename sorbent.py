"""
Sorbent degradation model for amine-functionalised polymer contactors.

Key phenomena captured:
  - Thermal / oxidative degradation: each regeneration cycle at 80-100 °C causes
    cumulative capacity loss.  Literature reports ~0.03–0.06 % capacity loss per
    cycle for supported amine sorbents (Wurzbacher et al., Fasihi et al.).
  - Humidity influence: co-adsorbed water accelerates amine leaching slightly.
  - Dust fouling: reduces effective mass-transfer area (reversible with cleaning,
    but cleaning has an energy cost).
  - Replacement trigger: economic crossover when the amortised cost of a new
    sorbent bed is cheaper than the lost revenue from degraded capture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple


# ── Physical constants / literature values ────────────────────────────────────

INITIAL_CAPACITY_KG_CO2_PER_KG  = 0.12   # kg CO₂ / kg sorbent at 25 °C, 400 ppm
CAPACITY_AT_35C_FRACTION         = 0.72   # fraction retained at 35 °C vs 25 °C
CAPACITY_AT_25C_FRACTION         = 1.00
# Linear interpolation between these two reference temperatures is used.

DEGRADATION_PER_CYCLE_BASE       = 0.00045  # fractional capacity loss per cycle (0.045 %)
DEGRADATION_HUMIDITY_FACTOR      = 0.15     # extra fractional degradation if RH > 40 %
DEGRADATION_TEMP_FACTOR          = 0.10     # extra if regeneration T > 95 °C

SORBENT_MASS_KG                  = 2_000    # kg of sorbent in the contactor bed
SORBENT_REPLACEMENT_COST_USD     = 180_000  # USD for full bed replacement (material + labour)

# Embodied CO₂ for manufacturing new sorbent
SORBENT_EMBODIED_KG_CO2_PER_KG   = 8.0     # kg CO₂e / kg sorbent (amine synthesis energy)

# Dust fouling: filter replacement cost and CO₂ footprint
FILTER_REPLACEMENT_COST_USD      = 400
FILTER_EMBODIED_KG_CO2           = 15.0    # kg CO₂e per filter set


@dataclass
class SorbentState:
    """Mutable state tracked across cycles."""
    cycle_count: int = 0
    capacity_fraction: float = 1.0        # 1.0 = fresh, declines over cycles
    cumulative_co2_kg: float = 0.0        # total CO₂ captured lifetime
    dust_fouling_factor: float = 1.0      # 1.0 = clean, > 1 = fouled (ΔP multiplier)
    hours_since_cleaning: int = 0
    total_embodied_co2_kg: float = field(default_factory=lambda: (
        SORBENT_MASS_KG * SORBENT_EMBODIED_KG_CO2_PER_KG
    ))  # starts with manufacturing footprint


def capture_capacity_kg_per_cycle(
    state: SorbentState,
    temp_c: float,
    rh_pct: float,
    cycle_duration_h: float = 8.0,
) -> float:
    """
    Return expected kg of CO₂ captured in one adsorption cycle.

    The capacity scales linearly with temperature between 25 °C and 35 °C
    (above 35 °C no meaningful night-time capture occurs in Phoenix).
    Below 25 °C gives a small bonus, capped at 1.05× nominal.
    """
    # Temperature penalty
    if temp_c <= 25.0:
        temp_frac = min(1.05, 1.0 + 0.005 * (25.0 - temp_c))
    elif temp_c >= 35.0:
        temp_frac = CAPACITY_AT_35C_FRACTION
    else:
        temp_frac = 1.0 - (1.0 - CAPACITY_AT_35C_FRACTION) * (temp_c - 25.0) / 10.0

    # Humidity bonus: co-adsorbed water helps CO₂ chemisorption on amines,
    # but only up to a point (excess water competes for sites).
    if rh_pct < 15:
        humidity_frac = 0.88  # very dry air — significant penalty
    elif rh_pct < 30:
        humidity_frac = 0.88 + 0.012 * (rh_pct - 15)  # gradual improvement
    elif rh_pct < 55:
        humidity_frac = 1.06  # sweet spot
    else:
        humidity_frac = 1.0   # high humidity, slight competition from water

    # Dust fouling reduces effective contactor area
    fouling_penalty = min(1.0, 1.0 / state.dust_fouling_factor)

    base_kg = (
        INITIAL_CAPACITY_KG_CO2_PER_KG
        * SORBENT_MASS_KG
        * state.capacity_fraction
        * temp_frac
        * humidity_frac
        * fouling_penalty
    )
    # Cycle duration scales sub-linearly (breakthrough after ~80 % of bed saturates)
    return base_kg * min(1.0, (cycle_duration_h / 8.0) ** 0.85)


def apply_cycle_degradation(
    state: SorbentState,
    regen_temp_c: float,
    rh_pct: float,
) -> SorbentState:
    """Return an updated SorbentState after one regeneration cycle."""
    deg = DEGRADATION_PER_CYCLE_BASE
    if rh_pct > 40:
        deg *= (1 + DEGRADATION_HUMIDITY_FACTOR)
    if regen_temp_c > 95:
        deg *= (1 + DEGRADATION_TEMP_FACTOR)

    new_capacity = max(0.30, state.capacity_fraction * (1 - deg))
    return SorbentState(
        cycle_count=state.cycle_count + 1,
        capacity_fraction=new_capacity,
        cumulative_co2_kg=state.cumulative_co2_kg,
        dust_fouling_factor=state.dust_fouling_factor,
        hours_since_cleaning=state.hours_since_cleaning + 1,
        total_embodied_co2_kg=state.total_embodied_co2_kg,
    )


def update_dust_fouling(state: SorbentState, dust_factor: float) -> SorbentState:
    """Accumulate dust fouling; cleaning resets it."""
    new_fouling = min(4.0, state.dust_fouling_factor + (dust_factor - 1.0) * 0.05)
    return SorbentState(
        cycle_count=state.cycle_count,
        capacity_fraction=state.capacity_fraction,
        cumulative_co2_kg=state.cumulative_co2_kg,
        dust_fouling_factor=new_fouling,
        hours_since_cleaning=state.hours_since_cleaning + 1,
        total_embodied_co2_kg=state.total_embodied_co2_kg,
    )


def should_replace_sorbent(state: SorbentState, avg_co2_price_usd_per_tonne: float = 200) -> Tuple[bool, str]:
    """
    Economic replacement trigger.

    Compare the annualised cost of keeping the degraded sorbent vs. buying new.
    Returns (should_replace: bool, reason: str).
    """
    # Revenue lost per year due to degradation (assuming ~3 cycles/day)
    cycles_per_year = 3 * 365
    full_capacity_kg = INITIAL_CAPACITY_KG_CO2_PER_KG * SORBENT_MASS_KG
    degraded_capacity_kg = full_capacity_kg * state.capacity_fraction
    annual_lost_kg = (full_capacity_kg - degraded_capacity_kg) * cycles_per_year
    annual_lost_usd = (annual_lost_kg / 1000) * avg_co2_price_usd_per_tonne

    # Annualised replacement cost (amortise over 3-year sorbent life at full capacity)
    annualised_replacement = SORBENT_REPLACEMENT_COST_USD / 3.0

    if state.capacity_fraction < 0.60:
        return True, (
            f"Capacity at {state.capacity_fraction:.1%} — below 60 % floor. "
            f"Annual lost value ${annual_lost_usd:,.0f} vs replacement ${annualised_replacement:,.0f}/yr."
        )
    if annual_lost_usd > annualised_replacement:
        return True, (
            f"Lost value ${annual_lost_usd:,.0f}/yr exceeds replacement cost "
            f"${annualised_replacement:,.0f}/yr at {state.capacity_fraction:.1%} capacity."
        )
    return False, f"Sorbent at {state.capacity_fraction:.1%} — replacement not yet economic."
