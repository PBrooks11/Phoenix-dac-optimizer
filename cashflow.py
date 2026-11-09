"""
Cash Flow Model — Phoenix DAC System
=====================================
Monthly revenue and cost projections by phase (Phase 0 → Phase 4).

Design principles:
  • Model the WORST plausible month, not the best, for each revenue line.
    Investors and grant reviewers will stress-test toward the low end.
  • Every dollar of revenue must tie to the carbon ledger: only NET tonnes
    are eligible for carbon credits; only ASTM-qualified aggregate earns
    the construction premium.
  • 45Q tax credit (§45Q IRS): $180/tonne for permanent geologic storage,
    $130/tonne for utilisation (mineral carbonation to aggregate falls here
    as of IRA 2022). We model the utilisation rate — verify with tax counsel.
  • Grant income is NOT revenue — it is non-dilutive project funding.
    It reduces the cash burn rate but does not affect unit economics.
  • Phase gates are cash gates: spending only unlocks for the next phase
    when the current phase gate passes.

Revenue sources (permanent-fate only):
  1. Aggregate sales          — $/tonne sold to ready-mix / precast buyers
  2. Carbon removal credits   — voluntary market ($/tonne NET removed)
  3. 45Q tax credit           — mineral carbonation utilisation rate
  4. Grant / partnership      — non-dilutive funding by phase

Cost categories:
  1. Operating expenses (OpEx): sorbent, filters, electricity, water, labour
  2. Capital expenditure (CapEx): annualised / depreciated
  3. Tailings processing: grinding + transport per tonne CO₂
  4. Third-party MRV & verification
  5. Legal / IP / admin

All monetary values in 2025 USD. Inflation not modelled (Phase 0–1 horizon).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import math


# ══════════════════════════════════════════════════════════════════════════════
# PHASE PARAMETERS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class PhaseParams:
    """Fixed parameters for one project phase."""
    phase: int
    name: str
    duration_months: int
    # System scale
    gross_co2_t_per_month: float       # gross capture at design point
    net_negative_ratio: float          # fraction that is net-negative
    operating_hours_per_day: float     # capture hours / day average
    # Revenue
    aggregate_price_usd_per_t: float   # $/tonne aggregate sold (conservative)
    aggregate_sellable_fraction: float # fraction of aggregate that meets ASTM spec
    carbon_credit_price_usd_per_t: float  # voluntary market $/tonne net CO₂
    credit_fraction_sold: float        # fraction of credits that find a buyer
    q45_utilisation_rate_usd: float    # IRS §45Q mineral carbonation rate
    q45_eligible: bool                 # only from Phase 2 onward (after 45Q reg)
    # Costs (monthly)
    capex_monthly_usd: float           # annualised CapEx / 12
    opex_fixed_monthly_usd: float      # fixed OpEx (labour, insurance, monitoring)
    sorbent_monthly_usd: float         # amortised sorbent replacement cost
    filter_monthly_usd: float          # filter replacements
    water_monthly_usd: float           # municipal water
    tailings_usd_per_t_co2: float      # grinding + transport per tonne CO₂
    mrv_monthly_usd: float             # MRV software + audit costs
    legal_admin_monthly_usd: float     # legal, accounting, filings
    # Grants (non-dilutive)
    grant_monthly_usd: float           # expected monthly grant income


# ── Phase definitions ──────────────────────────────────────────────────────────
# All numbers are conservative mid-points; use sensitivity sliders in the dashboard.

PHASE_PARAMS: Dict[int, PhaseParams] = {
    0: PhaseParams(
        phase=0, name="Foundation & Literature",
        duration_months=6,
        # No physical system yet
        gross_co2_t_per_month=0.0,
        net_negative_ratio=0.0,
        operating_hours_per_day=0.0,
        # No revenue yet
        aggregate_price_usd_per_t=0.0,
        aggregate_sellable_fraction=0.0,
        carbon_credit_price_usd_per_t=0.0,
        credit_fraction_sold=0.0,
        q45_utilisation_rate_usd=0.0,
        q45_eligible=False,
        # Minimal costs — founder's time + literature access
        capex_monthly_usd=0.0,
        opex_fixed_monthly_usd=500.0,    # cloud compute, subscriptions
        sorbent_monthly_usd=0.0,
        filter_monthly_usd=0.0,
        water_monthly_usd=0.0,
        tailings_usd_per_t_co2=0.0,
        mrv_monthly_usd=50.0,            # this software
        legal_admin_monthly_usd=300.0,   # IP attorney consultation
        grant_monthly_usd=0.0,
    ),
    1: PhaseParams(
        phase=1, name="Bench Scale & Sorbent Qualification",
        duration_months=12,
        # Bench scale: ~0.1 t/month gross
        gross_co2_t_per_month=0.10,
        net_negative_ratio=0.85,
        operating_hours_per_day=8.0,
        # Limited sales — test batches only, no commercial ASTM yet
        aggregate_price_usd_per_t=20.0,   # test-batch price (not commercial)
        aggregate_sellable_fraction=0.0,   # no ASTM yet — no commercial sale
        carbon_credit_price_usd_per_t=0.0, # no registry yet
        credit_fraction_sold=0.0,
        q45_utilisation_rate_usd=0.0,
        q45_eligible=False,
        # Bench costs
        capex_monthly_usd=2_000.0,        # bench equipment depreciation
        opex_fixed_monthly_usd=2_000.0,   # part-time lab time, utilities
        sorbent_monthly_usd=500.0,        # test sorbent procurement
        filter_monthly_usd=100.0,
        water_monthly_usd=50.0,
        tailings_usd_per_t_co2=85.0,      # small-batch unit cost is high
        mrv_monthly_usd=100.0,
        legal_admin_monthly_usd=500.0,    # company formation, IP filings
        grant_monthly_usd=5_000.0,        # DOE SBIR Phase I (~$150k / 30 months)
    ),
    2: PhaseParams(
        phase=2, name="Pilot Plant (1 t CO₂/day)",
        duration_months=18,
        # Pilot: ~25 t/month gross (1 t/day design, ~83% uptime)
        gross_co2_t_per_month=25.0,
        net_negative_ratio=0.88,
        operating_hours_per_day=16.0,
        # Pilot revenue starts
        aggregate_price_usd_per_t=38.0,   # initial market price (conservative)
        aggregate_sellable_fraction=0.70,  # 70% meets ASTM spec initially
        carbon_credit_price_usd_per_t=250.0,  # conservative voluntary market
        credit_fraction_sold=0.40,         # 40% of credits find buyers early
        q45_utilisation_rate_usd=130.0,    # §45Q mineral carbonation / utilisation
        q45_eligible=True,
        # Pilot costs
        capex_monthly_usd=8_333.0,        # $100k pilot capex / 12 months
        opex_fixed_monthly_usd=6_000.0,   # 0.5 FTE ops + utilities
        sorbent_monthly_usd=1_500.0,      # 2000 kg, 3-yr life → $5k/yr
        filter_monthly_usd=200.0,
        water_monthly_usd=150.0,
        tailings_usd_per_t_co2=68.0,      # improved with mine partner agreement
        mrv_monthly_usd=300.0,
        legal_admin_monthly_usd=800.0,
        grant_monthly_usd=12_500.0,       # DOE SBIR Phase II (~$1.5M / 24 months, staggered)
    ),
    3: PhaseParams(
        phase=3, name="Commercial Scale (10 t CO₂/day)",
        duration_months=24,
        # Commercial: ~250 t/month gross (10 t/day, 83% uptime)
        gross_co2_t_per_month=250.0,
        net_negative_ratio=0.90,
        operating_hours_per_day=20.0,
        # Commercial revenue
        aggregate_price_usd_per_t=45.0,   # established market rate
        aggregate_sellable_fraction=0.90,
        carbon_credit_price_usd_per_t=300.0,
        credit_fraction_sold=0.70,         # offtake agreement in place
        q45_utilisation_rate_usd=130.0,
        q45_eligible=True,
        # Commercial costs (scale economies kick in)
        capex_monthly_usd=20_833.0,       # $250k commercial capex / 12
        opex_fixed_monthly_usd=18_000.0,  # 1.5 FTE + utilities + maintenance
        sorbent_monthly_usd=5_000.0,
        filter_monthly_usd=600.0,
        water_monthly_usd=500.0,
        tailings_usd_per_t_co2=52.0,      # volume discount + solar crusher contract
        mrv_monthly_usd=1_500.0,          # third-party audit costs
        legal_admin_monthly_usd=2_000.0,
        grant_monthly_usd=8_333.0,        # DOE prize / state grants
    ),
    4: PhaseParams(
        phase=4, name="Scale-Out & Replication",
        duration_months=36,
        # Scale-out: 100 t/month gross per unit, modelled as 1 unit
        gross_co2_t_per_month=100.0,      # per replicated unit (model 1 unit)
        net_negative_ratio=0.92,
        operating_hours_per_day=22.0,
        # Scale-out revenue
        aggregate_price_usd_per_t=50.0,
        aggregate_sellable_fraction=0.95,
        carbon_credit_price_usd_per_t=350.0,
        credit_fraction_sold=0.85,
        q45_utilisation_rate_usd=130.0,
        q45_eligible=True,
        # Scale-out costs (optimised)
        capex_monthly_usd=6_250.0,        # $75k per unit / 12
        opex_fixed_monthly_usd=8_000.0,
        sorbent_monthly_usd=2_500.0,
        filter_monthly_usd=300.0,
        water_monthly_usd=250.0,
        tailings_usd_per_t_co2=42.0,      # solar crusher + volume
        mrv_monthly_usd=800.0,
        legal_admin_monthly_usd=1_000.0,
        grant_monthly_usd=0.0,            # self-sustaining
    ),
}


# ══════════════════════════════════════════════════════════════════════════════
# MONTHLY CASH FLOW RECORD
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class MonthlyCashFlow:
    phase: int
    month_in_phase: int          # 1-based within the phase
    month_absolute: int          # 1-based from project start

    # Revenue lines (USD)
    rev_aggregate: float = 0.0
    rev_carbon_credits: float = 0.0
    rev_45q: float = 0.0
    rev_grant: float = 0.0

    # Cost lines (USD)
    cost_capex: float = 0.0
    cost_opex_fixed: float = 0.0
    cost_sorbent: float = 0.0
    cost_filter: float = 0.0
    cost_water: float = 0.0
    cost_tailings: float = 0.0
    cost_mrv: float = 0.0
    cost_legal: float = 0.0

    # Carbon metrics
    gross_co2_t: float = 0.0
    net_co2_t: float = 0.0
    aggregate_t: float = 0.0

    @property
    def total_revenue(self) -> float:
        return (self.rev_aggregate + self.rev_carbon_credits
                + self.rev_45q + self.rev_grant)

    @property
    def total_commercial_revenue(self) -> float:
        """Revenue excluding grants (the honest unit economics metric)."""
        return self.rev_aggregate + self.rev_carbon_credits + self.rev_45q

    @property
    def total_cost(self) -> float:
        return (self.cost_capex + self.cost_opex_fixed + self.cost_sorbent
                + self.cost_filter + self.cost_water + self.cost_tailings
                + self.cost_mrv + self.cost_legal)

    @property
    def net_cash_flow(self) -> float:
        return self.total_revenue - self.total_cost

    @property
    def operating_cash_flow(self) -> float:
        """Cash flow excluding grants (stress-test view)."""
        return self.total_commercial_revenue - self.total_cost

    @property
    def cost_per_net_tonne(self) -> Optional[float]:
        if self.net_co2_t > 0:
            return self.total_cost / self.net_co2_t
        return None

    @property
    def revenue_per_net_tonne(self) -> Optional[float]:
        if self.net_co2_t > 0:
            return self.total_commercial_revenue / self.net_co2_t
        return None

    def to_dict(self) -> dict:
        return {
            "phase":                  self.phase,
            "month_in_phase":         self.month_in_phase,
            "month_absolute":         self.month_absolute,
            "gross_co2_t":            round(self.gross_co2_t, 2),
            "net_co2_t":              round(self.net_co2_t, 2),
            "aggregate_t":            round(self.aggregate_t, 2),
            "rev_aggregate":          round(self.rev_aggregate, 0),
            "rev_carbon_credits":     round(self.rev_carbon_credits, 0),
            "rev_45q":                round(self.rev_45q, 0),
            "rev_grant":              round(self.rev_grant, 0),
            "total_revenue":          round(self.total_revenue, 0),
            "total_commercial_rev":   round(self.total_commercial_revenue, 0),
            "cost_capex":             round(self.cost_capex, 0),
            "cost_opex_fixed":        round(self.cost_opex_fixed, 0),
            "cost_sorbent":           round(self.cost_sorbent, 0),
            "cost_filter":            round(self.cost_filter, 0),
            "cost_water":             round(self.cost_water, 0),
            "cost_tailings":          round(self.cost_tailings, 0),
            "cost_mrv":               round(self.cost_mrv, 0),
            "cost_legal":             round(self.cost_legal, 0),
            "total_cost":             round(self.total_cost, 0),
            "net_cash_flow":          round(self.net_cash_flow, 0),
            "operating_cash_flow":    round(self.operating_cash_flow, 0),
            "cost_per_net_tonne":     round(self.cost_per_net_tonne, 0) if self.cost_per_net_tonne else None,
            "revenue_per_net_tonne":  round(self.revenue_per_net_tonne, 0) if self.revenue_per_net_tonne else None,
        }


# ══════════════════════════════════════════════════════════════════════════════
# CASH FLOW ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class CashFlowModel:
    """
    Generates a monthly cash flow projection across all phases.

    Parameters can be overridden via the dashboard sliders.
    By default uses the conservative PHASE_PARAMS table above.
    """

    def __init__(
        self,
        phases_to_include: Optional[List[int]] = None,
        # Override multipliers (1.0 = use defaults)
        aggregate_price_factor: float = 1.0,
        carbon_credit_price_factor: float = 1.0,
        grant_factor: float = 1.0,
        opex_factor: float = 1.0,
        # Sensitivity overrides (absolute, USD)
        carbon_credit_price_override: Optional[float] = None,
        aggregate_price_override: Optional[float] = None,
    ):
        self.phases = phases_to_include or [0, 1, 2, 3, 4]
        self.agg_factor    = aggregate_price_factor
        self.credit_factor = carbon_credit_price_factor
        self.grant_factor  = grant_factor
        self.opex_factor   = opex_factor
        self.credit_override = carbon_credit_price_override
        self.agg_override    = aggregate_price_override

    def _compute_month(
        self,
        p: PhaseParams,
        month_in_phase: int,
        month_absolute: int,
    ) -> MonthlyCashFlow:
        cf = MonthlyCashFlow(
            phase=p.phase,
            month_in_phase=month_in_phase,
            month_absolute=month_absolute,
        )

        # Carbon metrics
        cf.gross_co2_t = p.gross_co2_t_per_month
        cf.net_co2_t   = p.gross_co2_t_per_month * p.net_negative_ratio
        # Aggregate: t tailings / t CO₂ ≈ 4–5× for typical assays, so ~4× net CO₂ in aggregate
        cf.aggregate_t = cf.net_co2_t * 4.2

        # Revenue
        agg_price  = (self.agg_override or
                      p.aggregate_price_usd_per_t * self.agg_factor)
        cred_price = (self.credit_override or
                      p.carbon_credit_price_usd_per_t * self.credit_factor)

        cf.rev_aggregate = (
            cf.aggregate_t
            * p.aggregate_sellable_fraction
            * agg_price
        )
        cf.rev_carbon_credits = (
            cf.net_co2_t
            * p.credit_fraction_sold
            * cred_price
        )
        cf.rev_45q = (
            cf.net_co2_t * p.q45_utilisation_rate_usd
            if p.q45_eligible else 0.0
        )
        cf.rev_grant = p.grant_monthly_usd * self.grant_factor

        # Costs
        cf.cost_capex      = p.capex_monthly_usd
        cf.cost_opex_fixed = p.opex_fixed_monthly_usd * self.opex_factor
        cf.cost_sorbent    = p.sorbent_monthly_usd
        cf.cost_filter     = p.filter_monthly_usd
        cf.cost_water      = p.water_monthly_usd
        cf.cost_tailings   = cf.net_co2_t * p.tailings_usd_per_t_co2
        cf.cost_mrv        = p.mrv_monthly_usd
        cf.cost_legal      = p.legal_admin_monthly_usd

        return cf

    def run(self) -> List[MonthlyCashFlow]:
        """Generate the full multi-phase monthly cash flow series."""
        results: List[MonthlyCashFlow] = []
        month_abs = 1
        for ph in self.phases:
            p = PHASE_PARAMS[ph]
            for m in range(1, p.duration_months + 1):
                cf = self._compute_month(p, m, month_abs)
                results.append(cf)
                month_abs += 1
        return results

    def summary(self) -> Dict:
        """Aggregate summary across all modelled phases."""
        rows = self.run()
        total_rev      = sum(r.total_revenue for r in rows)
        total_comm_rev = sum(r.total_commercial_revenue for r in rows)
        total_cost     = sum(r.total_cost for r in rows)
        total_net_cf   = sum(r.net_cash_flow for r in rows)
        total_op_cf    = sum(r.operating_cash_flow for r in rows)
        total_net_co2  = sum(r.net_co2_t for r in rows)
        total_grants   = sum(r.rev_grant for r in rows)

        # Breakeven analysis (cumulative, with grants)
        cumulative = 0.0
        breakeven_month = None
        for r in rows:
            cumulative += r.net_cash_flow
            if cumulative >= 0 and breakeven_month is None:
                breakeven_month = r.month_absolute

        # Breakeven without grants (commercial only)
        cumulative_comm = 0.0
        breakeven_commercial = None
        for r in rows:
            cumulative_comm += r.operating_cash_flow
            if cumulative_comm >= 0 and breakeven_commercial is None:
                breakeven_commercial = r.month_absolute

        # Peak cash need (maximum cumulative deficit)
        running = 0.0
        peak_deficit = 0.0
        for r in rows:
            running += r.net_cash_flow
            if running < peak_deficit:
                peak_deficit = running

        return {
            "total_months":             len(rows),
            "total_revenue_usd":        round(total_rev, 0),
            "total_commercial_rev_usd": round(total_comm_rev, 0),
            "total_grant_usd":          round(total_grants, 0),
            "total_cost_usd":           round(total_cost, 0),
            "net_cash_flow_usd":        round(total_net_cf, 0),
            "operating_cash_flow_usd":  round(total_op_cf, 0),
            "total_net_co2_t":          round(total_net_co2, 1),
            "breakeven_month_with_grants":   breakeven_month,
            "breakeven_month_commercial":    breakeven_commercial,
            "peak_cash_need_usd":       round(peak_deficit, 0),
        }


def build_demo_cashflow(
    carbon_credit_price: float = 250.0,
    aggregate_price_factor: float = 1.0,
    opex_factor: float = 1.0,
    grant_factor: float = 1.0,
    phases: Optional[List[int]] = None,
) -> Tuple[CashFlowModel, List[MonthlyCashFlow], Dict]:
    """Return a ready-to-use demo CashFlowModel + computed rows + summary."""
    model = CashFlowModel(
        phases_to_include=phases or [0, 1, 2, 3, 4],
        carbon_credit_price_override=carbon_credit_price,
        aggregate_price_factor=aggregate_price_factor,
        opex_factor=opex_factor,
        grant_factor=grant_factor,
    )
    rows = model.run()
    summary = model.summary()
    return model, rows, summary
