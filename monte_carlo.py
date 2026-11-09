"""
Monte Carlo LCA Sensitivity — Phoenix DAC System
=================================================
Runs N simulations of the LCA with uncertain emission factors sampled
from triangular or log-normal distributions, producing:

  • 5th / 50th / 95th percentile net-negative ratios
  • Probability that net-negative ratio falls below 85% threshold
  • Tornado chart data: which uncertain input drives variance most
  • Confidence interval on cost per net tonne

Key uncertain parameters (LOW / MEDIUM confidence from lca.py):
  1. Sorbent manufacturing EF  : 4–15 kg CO₂e/kg (triangular, mode=8)
  2. Infrastructure EF          : 1–4 kg CO₂e/t gross CO₂ (triangular, mode=2)
  3. Filter manufacturing EF    : 8–25 kg CO₂e/set (triangular, mode=15)
  4. Tailings grinding EF diesel: 0.22–0.32 kg CO₂e/kWh (triangular, mode=0.27)
  5. Transport EF               : 0.05–0.08 kg CO₂e/t·km (triangular, mode=0.062)

Well-characterised inputs are held fixed (solar PV, battery).

This module does NOT require scipy or numpy — it uses Python stdlib random
with a fast triangular sampler so it runs in-browser without extra deps.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ══════════════════════════════════════════════════════════════════════════════
# TRIANGULAR DISTRIBUTION SAMPLER
# ══════════════════════════════════════════════════════════════════════════════

def triangular(lo: float, mode: float, hi: float, rng: random.Random) -> float:
    """Sample from a triangular distribution using the inverse CDF method."""
    u = rng.random()
    fc = (mode - lo) / (hi - lo)
    if u < fc:
        return lo + math.sqrt(u * (hi - lo) * (mode - lo))
    else:
        return hi - math.sqrt((1 - u) * (hi - lo) * (hi - mode))


# ══════════════════════════════════════════════════════════════════════════════
# UNCERTAIN PARAMETER DEFINITIONS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class UncertainParam:
    name: str
    base: float           # central/default value used in deterministic LCA
    lo: float             # lower bound (e.g. 5th percentile)
    mode: float           # most likely value (triangular peak)
    hi: float             # upper bound (e.g. 95th percentile)
    unit: str
    source: str
    confidence: str       # "low" | "medium" | "high"


UNCERTAIN_PARAMS: Dict[str, UncertainParam] = {
    "sorbent_ef": UncertainParam(
        name="Sorbent manufacturing EF",
        base=8.0, lo=4.0, mode=8.0, hi=15.0,
        unit="kg CO₂e / kg sorbent",
        source="Fasihi et al. 2019; Wurzbacher et al. 2016 — range 4–15",
        confidence="low",
    ),
    "infrastructure_ef": UncertainParam(
        name="Infrastructure EF",
        base=2.0, lo=0.8, mode=2.0, hi=4.5,
        unit="kg CO₂e / t gross CO₂",
        source="Climeworks 2021 LCA supplementary — pilot to commercial range",
        confidence="low",
    ),
    "filter_ef": UncertainParam(
        name="Filter manufacturing EF",
        base=15.0, lo=8.0, mode=15.0, hi=28.0,
        unit="kg CO₂e / filter set",
        source="Ecoinvent 3.9 fiberglass HEPA — ±40% supplier variation",
        confidence="low",
    ),
    "diesel_grinding_ef": UncertainParam(
        name="Diesel grinding EF",
        base=0.270, lo=0.220, mode=0.270, hi=0.320,
        unit="kg CO₂e / kWh",
        source="US EIA 2023 diesel genset range across Arizona operators",
        confidence="medium",
    ),
    "transport_ef": UncertainParam(
        name="Transport EF",
        base=0.062, lo=0.050, mode=0.062, hi=0.080,
        unit="kg CO₂e / tonne·km",
        source="Arizona DOT 2022 — variation across truck types/loads",
        confidence="medium",
    ),
    "sorbent_lifetime_yr": UncertainParam(
        name="Sorbent lifetime",
        base=3.0, lo=1.5, mode=3.0, hi=5.0,
        unit="years",
        source="Bench-scale results suggest 2–5 yr at 3 cycles/day; no Phoenix field data yet",
        confidence="low",
    ),
}


# ══════════════════════════════════════════════════════════════════════════════
# SINGLE SIMULATION RUN
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class MCResult:
    """Result of one Monte Carlo run."""
    net_negative_ratio: float
    net_co2_t_per_yr: float
    total_emis_kg_per_yr: float
    cost_per_net_tonne: float
    # Sampled parameter values
    sorbent_ef: float
    infrastructure_ef: float
    filter_ef: float
    diesel_grinding_ef: float
    transport_ef: float
    sorbent_lifetime_yr: float


def _run_one(
    rng: random.Random,
    # Fixed system parameters (from the LCA boundary)
    gross_co2_t_yr: float = 114.3,
    sorbent_mass_kg: float = 2_000.0,
    filters_per_yr: float = 6.0,
    tailings_t_yr: float = 330.0,
    tailings_dist_km: float = 150.0,
    grinding_kwh_per_t: float = 12.0,
    fan_kwh_yr: float = 43_800.0,
    vacuum_kwh_yr: float = 4_380.0,
    battery_kwh_discharged: float = 35_000.0,
    pv_mfg_annualised_kg: float = 60.0,
    battery_mfg_ef: float = 0.008,
    solar_pv_ef: float = 0.020,
    water_net_litre_yr: float = 2_000.0,
    reactor_kwh_yr: float = 850.0,
    total_cost_usd_yr: float = 28_800.0,
    grinder_type: str = "diesel",
) -> MCResult:
    """Sample one set of uncertain parameters and compute LCA metrics."""

    # Sample uncertain parameters
    s_ef   = triangular(UNCERTAIN_PARAMS["sorbent_ef"].lo,
                        UNCERTAIN_PARAMS["sorbent_ef"].mode,
                        UNCERTAIN_PARAMS["sorbent_ef"].hi, rng)
    inf_ef = triangular(UNCERTAIN_PARAMS["infrastructure_ef"].lo,
                        UNCERTAIN_PARAMS["infrastructure_ef"].mode,
                        UNCERTAIN_PARAMS["infrastructure_ef"].hi, rng)
    f_ef   = triangular(UNCERTAIN_PARAMS["filter_ef"].lo,
                        UNCERTAIN_PARAMS["filter_ef"].mode,
                        UNCERTAIN_PARAMS["filter_ef"].hi, rng)
    d_ef   = triangular(UNCERTAIN_PARAMS["diesel_grinding_ef"].lo,
                        UNCERTAIN_PARAMS["diesel_grinding_ef"].mode,
                        UNCERTAIN_PARAMS["diesel_grinding_ef"].hi, rng)
    t_ef   = triangular(UNCERTAIN_PARAMS["transport_ef"].lo,
                        UNCERTAIN_PARAMS["transport_ef"].mode,
                        UNCERTAIN_PARAMS["transport_ef"].hi, rng)
    s_life = triangular(UNCERTAIN_PARAMS["sorbent_lifetime_yr"].lo,
                        UNCERTAIN_PARAMS["sorbent_lifetime_yr"].mode,
                        UNCERTAIN_PARAMS["sorbent_lifetime_yr"].hi, rng)

    # Compute emissions
    emis_pv     = pv_mfg_annualised_kg
    emis_batt   = battery_kwh_discharged * battery_mfg_ef
    emis_sorb   = (sorbent_mass_kg * s_ef) / s_life
    emis_filt   = filters_per_yr * f_ef
    grind_ef    = d_ef if grinder_type == "diesel" else 0.020
    emis_grind  = tailings_t_yr * grinding_kwh_per_t * grind_ef
    emis_trans  = tailings_t_yr * tailings_dist_km * t_ef
    emis_fan    = fan_kwh_yr * solar_pv_ef
    emis_vac    = vacuum_kwh_yr * solar_pv_ef
    emis_water  = water_net_litre_yr * 0.00035
    emis_react  = reactor_kwh_yr * solar_pv_ef
    emis_infra  = gross_co2_t_yr * inf_ef

    total_emis_kg = (emis_pv + emis_batt + emis_sorb + emis_filt
                     + emis_grind + emis_trans + emis_fan + emis_vac
                     + emis_water + emis_react + emis_infra)

    net_co2_t    = max(0.0, gross_co2_t_yr - total_emis_kg / 1000)
    net_neg_frac = net_co2_t / gross_co2_t_yr if gross_co2_t_yr > 0 else 0.0
    cost_per_net = total_cost_usd_yr / net_co2_t if net_co2_t > 0 else float("inf")

    return MCResult(
        net_negative_ratio=net_neg_frac,
        net_co2_t_per_yr=net_co2_t,
        total_emis_kg_per_yr=total_emis_kg,
        cost_per_net_tonne=cost_per_net,
        sorbent_ef=s_ef,
        infrastructure_ef=inf_ef,
        filter_ef=f_ef,
        diesel_grinding_ef=d_ef,
        transport_ef=t_ef,
        sorbent_lifetime_yr=s_life,
    )


# ══════════════════════════════════════════════════════════════════════════════
# MONTE CARLO RUNNER
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class MCStats:
    """Summary statistics from a Monte Carlo run."""
    n: int
    # Net-negative ratio
    nn_p5:  float; nn_p25: float; nn_p50: float; nn_p75: float; nn_p95: float
    nn_mean: float
    prob_below_85_pct: float      # P(net-neg ratio < 85%)
    prob_below_75_pct: float      # P(net-neg ratio < 75%)
    # Net CO₂
    net_co2_p5: float; net_co2_p50: float; net_co2_p95: float
    # Cost per net tonne
    cost_p5:  float; cost_p50: float; cost_p95: float
    # Tornado data: param name → Pearson correlation with net-neg ratio
    tornado: Dict[str, float] = field(default_factory=dict)


def run_monte_carlo(
    n: int = 500,
    seed: int = 42,
    grinder_type: str = "diesel",
    gross_co2_t_yr: float = 114.3,
    total_cost_usd_yr: float = 28_800.0,
) -> Tuple[List[MCResult], MCStats]:
    """
    Run N Monte Carlo simulations and return (raw_results, summary_stats).

    n=500 is sufficient for stable percentiles and runs in <1s in pure Python.
    """
    rng     = random.Random(seed)
    results = [
        _run_one(rng, gross_co2_t_yr=gross_co2_t_yr,
                 total_cost_usd_yr=total_cost_usd_yr,
                 grinder_type=grinder_type)
        for _ in range(n)
    ]

    nn_vals   = sorted(r.net_negative_ratio for r in results)
    net_vals  = sorted(r.net_co2_t_per_yr   for r in results)
    cost_vals = sorted(r.cost_per_net_tonne for r in results
                       if r.cost_per_net_tonne < 1e6)

    def pct(lst: List[float], p: float) -> float:
        idx = max(0, min(len(lst) - 1, int(len(lst) * p / 100)))
        return lst[idx]

    def pearson(xs: List[float], ys: List[float]) -> float:
        n_ = len(xs)
        if n_ < 2:
            return 0.0
        mx = sum(xs) / n_; my = sum(ys) / n_
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        dx  = math.sqrt(sum((x - mx) ** 2 for x in xs) + 1e-12)
        dy  = math.sqrt(sum((y - my) ** 2 for y in ys) + 1e-12)
        return num / (dx * dy)

    nn_list = [r.net_negative_ratio for r in results]
    tornado = {
        "Sorbent EF":         pearson([r.sorbent_ef         for r in results], nn_list),
        "Sorbent lifetime":   pearson([r.sorbent_lifetime_yr for r in results], nn_list),
        "Infrastructure EF":  pearson([r.infrastructure_ef  for r in results], nn_list),
        "Filter EF":          pearson([r.filter_ef           for r in results], nn_list),
        "Diesel grinding EF": pearson([r.diesel_grinding_ef  for r in results], nn_list),
        "Transport EF":       pearson([r.transport_ef        for r in results], nn_list),
    }

    stats = MCStats(
        n=n,
        nn_p5=pct(nn_vals, 5),  nn_p25=pct(nn_vals, 25),
        nn_p50=pct(nn_vals, 50), nn_p75=pct(nn_vals, 75),
        nn_p95=pct(nn_vals, 95),
        nn_mean=sum(nn_vals) / len(nn_vals),
        prob_below_85_pct=100 * sum(1 for v in nn_vals if v < 0.85) / len(nn_vals),
        prob_below_75_pct=100 * sum(1 for v in nn_vals if v < 0.75) / len(nn_vals),
        net_co2_p5=pct(net_vals, 5), net_co2_p50=pct(net_vals, 50),
        net_co2_p95=pct(net_vals, 95),
        cost_p5=pct(cost_vals, 5), cost_p50=pct(cost_vals, 50),
        cost_p95=pct(cost_vals, 95),
        tornado=tornado,
    )

    return results, stats


def histogram_data(values: List[float], bins: int = 30) -> Tuple[List[float], List[int]]:
    """Return (bin_centres, counts) for a histogram of values."""
    if not values:
        return [], []
    lo, hi = min(values), max(values)
    width   = (hi - lo) / bins if hi > lo else 1.0
    counts  = [0] * bins
    edges   = [lo + i * width for i in range(bins + 1)]
    for v in values:
        idx = min(bins - 1, int((v - lo) / width))
        counts[idx] += 1
    centres = [(edges[i] + edges[i + 1]) / 2 for i in range(bins)]
    return centres, counts
