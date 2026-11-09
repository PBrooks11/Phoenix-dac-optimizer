"""
Net-negative carbon ledger for the Phoenix DAC system.

Accounting methodology
──────────────────────
Only PERMANENT sequestration counts as removal:
  • Mineral carbonation into construction aggregate (Arizona copper mine tailings)
  • Direct geologic injection

All system emissions are debited:
  1. Fan electricity (night-time, battery + any grid)
  2. Vacuum pump electricity (daytime, solar)
  3. Sorbent manufacturing (amortised over expected cycle lifetime)
  4. Filter manufacturing and replacement
  5. Tailings grinding and transport (for mineral carbonation pathway)
  6. Infrastructure build (annualised, steel/concrete)

Emission factors
  • Battery round-trip efficiency: 90 % (LFP)
  • Solar PV lifecycle: 20 g CO₂e/kWh (IPCC AR6 median)
  • Tailings grinding: 15 kg CO₂e/tonne aggregate (diesel crusher — NOTE: this is
    the one residual fossil input; must be tracked carefully)
  • Transport (mine to plant, 150 km): 0.062 kg CO₂e/tonne·km → 9.3 kg CO₂e/tonne
  • Infrastructure annualised: 2.0 kg CO₂e per tonne gross CO₂ captured
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from tailings import TailingsAssay


# ── Emission factors ───────────────────────────────────────────────────────────

EF_SOLAR_PV_KG_CO2E_PER_KWH        = 0.020   # kg CO₂e/kWh (lifecycle, IPCC AR6)
EF_BATTERY_DISCHARGE_OVERHEAD       = 1 / 0.90 - 1  # ~11.1 % charge overhead per kWh out
# Battery manufacturing: 60 kg CO₂e/kWh capacity, amortised over 3000 cycles × depth
EF_BATTERY_MFG_KG_CO2E_PER_KWH_OUT = 0.008   # kg CO₂e per kWh discharged (amortised)

EF_TAILINGS_GRINDING_KG_CO2E_PER_T_AGG = 15.0  # kg CO₂e / tonne aggregate (diesel)
EF_TRANSPORT_KG_CO2E_PER_T_AGG         = 9.3   # kg CO₂e / tonne (150 km, 0.062 kg/t·km)
EF_INFRASTRUCTURE_KG_CO2E_PER_T_GROSS  = 2.0   # kg CO₂e / tonne CO₂ captured (annualised)

# Mineral carbonation stoichiometry:
# Ca/Mg silicates in tailings + CO₂ → carbonates
# Approx 1 tonne CO₂ reacts with ~2.2 t tailings to form ~3.2 t aggregate
CO2_TO_TAILINGS_RATIO = 2.2   # t tailings / t CO₂
CO2_TO_AGGREGATE_RATIO = 3.2  # t aggregate / t CO₂

# Geologic storage pipeline/injection energy: 0.04 kWh/kg CO₂ (IEA estimate)
EF_GEO_STORAGE_KWH_PER_KG_CO2 = 0.040


@dataclass
class LedgerEntry:
    hour: int
    gross_co2_kg: float          # CO₂ adsorbed this hour (kg)
    sequestered_co2_kg: float    # CO₂ confirmed to permanent fate (kg)

    # Emissions debits (kg CO₂e)
    emis_fan_elec: float = 0.0
    emis_vacuum_elec: float = 0.0
    emis_sorbent_mfg: float = 0.0
    emis_filter_mfg: float = 0.0
    emis_tailings: float = 0.0
    emis_infrastructure: float = 0.0
    emis_battery_mfg: float = 0.0

    # Cost debits (USD)
    cost_elec_usd: float = 0.0
    cost_sorbent_amort_usd: float = 0.0
    cost_filter_amort_usd: float = 0.0
    cost_tailings_usd: float = 0.0

    @property
    def total_emissions_kg(self) -> float:
        return (
            self.emis_fan_elec + self.emis_vacuum_elec + self.emis_sorbent_mfg
            + self.emis_filter_mfg + self.emis_tailings + self.emis_infrastructure
            + self.emis_battery_mfg
        )

    @property
    def net_co2_kg(self) -> float:
        """Net removal: positive = net-negative."""
        return self.sequestered_co2_kg - self.total_emissions_kg

    @property
    def total_cost_usd(self) -> float:
        return (
            self.cost_elec_usd + self.cost_sorbent_amort_usd
            + self.cost_filter_amort_usd + self.cost_tailings_usd
        )


@dataclass
class CarbonLedger:
    """Accumulates entries over the simulation horizon."""
    entries: list = field(default_factory=list)

    # Sorbent amortisation parameters
    sorbent_replacement_cost_usd: float = 180_000
    sorbent_expected_lifetime_cycles: float = 10_000
    sorbent_embodied_co2_kg: float = 16_000  # 2000 kg × 8 kg CO₂e/kg

    # Filter amortisation
    filter_replacement_cost_usd: float = 400
    filter_expected_lifetime_h: float = 2_000  # hours between replacements
    filter_embodied_co2_kg: float = 15.0

    def record(
        self,
        hour: int,
        gross_co2_kg: float,
        fan_kwh: float,
        vacuum_kwh: float,
        battery_kwh_discharged: float,
        elec_price_usd_kwh: float,
        pathway: str = "mineral",    # "mineral" or "geologic"
        cycles_this_hour: float = 0.0,
        filter_hours_used: float = 1.0,
        tailings_assay: "Optional[TailingsAssay]" = None,
    ) -> LedgerEntry:
        """
        Record one hour of operation and return the ledger entry.

        Pass a TailingsAssay object to use per-batch geochemistry instead of
        the fixed module-level defaults.  Falls back to defaults if None.

        All electricity is solar (either direct PV or battery discharge).
        Solar lifecycle emissions are charged at EF_SOLAR_PV_KG_CO2E_PER_KWH.
        Battery discharge adds manufacturing overhead.
        """
        # Electricity emissions (solar lifecycle)
        emis_fan   = fan_kwh    * EF_SOLAR_PV_KG_CO2E_PER_KWH
        emis_vac   = vacuum_kwh * EF_SOLAR_PV_KG_CO2E_PER_KWH
        # Battery discharge overhead
        emis_batt  = battery_kwh_discharged * EF_BATTERY_MFG_KG_CO2E_PER_KWH_OUT

        # Sorbent amortisation
        co2_per_cycle = (self.sorbent_embodied_co2_kg
                         / self.sorbent_expected_lifetime_cycles)
        emis_sorb  = co2_per_cycle * cycles_this_hour
        cost_sorb  = (self.sorbent_replacement_cost_usd
                      / self.sorbent_expected_lifetime_cycles) * cycles_this_hour

        # Filter amortisation
        emis_filt  = (self.filter_embodied_co2_kg
                      / self.filter_expected_lifetime_h) * filter_hours_used
        cost_filt  = (self.filter_replacement_cost_usd
                      / self.filter_expected_lifetime_h) * filter_hours_used

        # Infrastructure
        emis_infra = EF_INFRASTRUCTURE_KG_CO2E_PER_T_GROSS * (gross_co2_kg / 1000)

        # Pathway-specific emissions
        if pathway == "mineral":
            if tailings_assay is not None:
                # ── Per-batch assay path ──────────────────────────────────────
                t_co2_seq = gross_co2_kg / 1000  # tonnes CO₂
                t_tailings = t_co2_seq * tailings_assay.t_tailings_per_t_co2
                t_agg      = t_co2_seq * tailings_assay.t_aggregate_per_t_co2
                # Grinding emissions (diesel or solar, per assay)
                emis_grind = (t_tailings
                              * tailings_assay.grinding_co2_kg_per_t_tailings)
                # Transport emissions
                emis_trans = (t_tailings
                              * tailings_assay.transport_co2_kg_per_t_tailings)
                emis_tail  = emis_grind + emis_trans
                # Cost: grinding kWh × $0.08 + transport t·km × $0.15
                cost_tail  = t_co2_seq * tailings_assay.cost_usd_per_t_co2()
            else:
                # ── Legacy fixed-ratio fallback ───────────────────────────────
                t_agg      = (gross_co2_kg / 1000) * CO2_TO_AGGREGATE_RATIO
                emis_tail  = t_agg * (EF_TAILINGS_GRINDING_KG_CO2E_PER_T_AGG
                                      + EF_TRANSPORT_KG_CO2E_PER_T_AGG)
                cost_tail  = t_agg * 8.50
            geo_kwh = 0.0
        else:  # geologic
            emis_tail  = 0.0
            cost_tail  = 0.0
            geo_kwh    = gross_co2_kg * EF_GEO_STORAGE_KWH_PER_KG_CO2
            emis_vac  += geo_kwh * EF_SOLAR_PV_KG_CO2E_PER_KWH

        sequestered = gross_co2_kg  # 100 % permanent for both pathways

        cost_elec = (fan_kwh + vacuum_kwh + geo_kwh) * elec_price_usd_kwh

        entry = LedgerEntry(
            hour=hour,
            gross_co2_kg=gross_co2_kg,
            sequestered_co2_kg=sequestered,
            emis_fan_elec=emis_fan,
            emis_vacuum_elec=emis_vac,
            emis_sorbent_mfg=emis_sorb,
            emis_filter_mfg=emis_filt,
            emis_tailings=emis_tail,
            emis_infrastructure=emis_infra,
            emis_battery_mfg=emis_batt,
            cost_elec_usd=cost_elec,
            cost_sorbent_amort_usd=cost_sorb,
            cost_filter_amort_usd=cost_filt,
            cost_tailings_usd=cost_tail,
        )
        self.entries.append(entry)
        return entry

    # ── Reporting ──────────────────────────────────────────────────────────────

    def summary(self) -> Dict:
        if not self.entries:
            return {}

        gross    = sum(e.gross_co2_kg       for e in self.entries)
        net      = sum(e.net_co2_kg         for e in self.entries)
        total_em = sum(e.total_emissions_kg for e in self.entries)
        total_co = sum(e.total_cost_usd     for e in self.entries)

        cost_per_net_tonne = (
            (total_co / (net / 1000)) if net > 0 else float("inf")
        )
        cost_per_gross_tonne = total_co / (gross / 1000) if gross > 0 else float("inf")

        breakdown = {
            "fan_electricity":   sum(e.emis_fan_elec       for e in self.entries),
            "vacuum_electricity":sum(e.emis_vacuum_elec     for e in self.entries),
            "sorbent_mfg":       sum(e.emis_sorbent_mfg    for e in self.entries),
            "filter_mfg":        sum(e.emis_filter_mfg     for e in self.entries),
            "tailings_process":  sum(e.emis_tailings        for e in self.entries),
            "infrastructure":    sum(e.emis_infrastructure  for e in self.entries),
            "battery_mfg":       sum(e.emis_battery_mfg    for e in self.entries),
        }

        return {
            "gross_co2_tonnes":          round(gross   / 1000, 2),
            "total_emissions_tonnes":    round(total_em / 1000, 2),
            "net_co2_tonnes":            round(net     / 1000, 2),
            "net_negative_fraction":     round(net / gross, 3) if gross > 0 else 0,
            "total_cost_usd":            round(total_co, 2),
            "cost_per_gross_tonne_usd":  round(cost_per_gross_tonne, 2),
            "cost_per_net_tonne_usd":    round(cost_per_net_tonne, 2),
            "emission_breakdown_tonnes": {k: round(v / 1000, 4)
                                          for k, v in breakdown.items()},
        }
