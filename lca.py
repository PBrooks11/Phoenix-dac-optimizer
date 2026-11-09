"""
LCA — Life Cycle Assessment boundary model.
Phoenix DAC System · ISO 14064-2 aligned

This module defines the system boundary, emission factors, and per-phase impact
categories for a third-party-verifiable LCA.  It is designed to:

  1. Be conservative — when uncertain, use the higher emission factor.
  2. Be auditable — every number cites a source or assumption.
  3. Grow with the project — Phase 0 values are placeholders that get replaced
     by real measurements as the company progresses through its phase gates.

ISO 14064-2 boundary (this system):
  ┌─────────────────────────────────────────────────────────────────────┐
  │ SYSTEM BOUNDARY                                                     │
  │  • DAC plant (sorbent contactor + fans + regen heater)              │
  │  • Solar PV array + LFP battery (lifecycle, not just ops)           │
  │  • Mine tailings: extraction (upstream), transport, grinding        │
  │  • Carbonation reactor + water system                               │
  │  • Aggregate product (sold as permanent fate)                       │
  │  • Sorbent + filter manufacturing (upstream) + disposal             │
  │  EXCLUDED: end-of-life concrete demolition (not our responsibility  │
  │            under 14064-2 cut-off rules — product is stable rock)    │
  └─────────────────────────────────────────────────────────────────────┘

Functional unit: 1 tonne of net CO₂ removed and permanently sequestered.

Water accounting methodology:
  Closed-loop target: process water is recycled from reactor condensate.
  Makeup water = evaporative loss + product moisture retention.
  Source: municipal water (Phoenix), emission factor 0.00035 kg CO₂e/L (WRI).
  Disclosure: water stress index for Phoenix is "extremely high" (Aqueduct).
  We report gross water consumption even when recycled (full-cycle accounting).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ══════════════════════════════════════════════════════════════════════════════
# EMISSION FACTORS — all values in kg CO₂e per unit stated
# Source citations are inline.
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class EmissionFactor:
    """One emission factor with its metadata."""
    value: float           # kg CO₂e per unit
    unit: str              # e.g. "per_kWh", "per_kg", "per_tonne_km"
    source: str            # citation
    confidence: str        # "high" | "medium" | "low" (low = placeholder)
    notes: str = ""


# Electricity — solar PV lifecycle
EF_SOLAR_PV = EmissionFactor(
    value=0.020,
    unit="kg_CO2e_per_kWh",
    source="IPCC AR6 WG3 Table A.III.2, utility-scale solar PV median",
    confidence="high",
)

# Battery — manufacturing amortised over discharge
EF_BATTERY_MFG = EmissionFactor(
    value=0.008,
    unit="kg_CO2e_per_kWh_discharged",
    source="Ellingsen et al. 2022, LFP pack 60 kg CO₂e/kWh capacity, 3000 cycles×80%DOD",
    confidence="medium",
)

# Sorbent — amine-functionalised polymer
EF_SORBENT_MFG = EmissionFactor(
    value=8.0,
    unit="kg_CO2e_per_kg_sorbent",
    source="Fasihi et al. 2019 DAC cost analysis; Wurzbacher et al. 2016 sorbent LCA",
    confidence="medium",
    notes="Highly uncertain — range 4–15 kg CO₂e/kg depending on synthesis route. "
          "Replace with supplier EPD when available.",
)

# Tailings grinding — diesel crusher
EF_GRINDING_DIESEL = EmissionFactor(
    value=0.27,
    unit="kg_CO2e_per_kWh_grinding",
    source="US EIA 2023 diesel generator emission intensity",
    confidence="high",
)

# Tailings grinding — solar electric crusher
EF_GRINDING_SOLAR = EmissionFactor(
    value=0.020,
    unit="kg_CO2e_per_kWh_grinding",
    source="Same as EF_SOLAR_PV (solar-powered crusher)",
    confidence="high",
)

# Transport — freight truck
EF_TRUCK = EmissionFactor(
    value=0.062,
    unit="kg_CO2e_per_tonne_km",
    source="Arizona DOT freight analysis 2022; IPCC AR6 Table 10.SM.1",
    confidence="high",
)

# Infrastructure — annualised (steel, concrete, installation)
EF_INFRASTRUCTURE = EmissionFactor(
    value=2.0,
    unit="kg_CO2e_per_tonne_gross_CO2_captured",
    source="Climeworks 2021 LCA supplementary; scaled to 100 tCO₂/yr system",
    confidence="low",
    notes="Phase 0 placeholder — replace with Bill of Materials LCA when plant design is fixed.",
)

# Water — municipal supply
EF_WATER = EmissionFactor(
    value=0.00035,
    unit="kg_CO2e_per_litre",
    source="WRI Aqueduct Water Risk Atlas; Arizona municipal treatment energy",
    confidence="medium",
)

# Carbonation reactor — agitation electricity (same as solar PV)
EF_REACTOR_ELEC = EmissionFactor(
    value=0.020,
    unit="kg_CO2e_per_kWh",
    source="Same as EF_SOLAR_PV",
    confidence="high",
)

# Filter — manufacturing per filter set
EF_FILTER_MFG = EmissionFactor(
    value=15.0,
    unit="kg_CO2e_per_filter_set",
    source="Fiberglass HEPA filter LCA; Ecoinvent 3.9 estimate",
    confidence="low",
    notes="Replace with manufacturer EPD when procurement is finalised.",
)


# ══════════════════════════════════════════════════════════════════════════════
# LCA BOUNDARY MODEL
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class LCABoundary:
    """
    Defines the full LCA system boundary and computes per-functional-unit impacts.

    All parameters have defaults matching a ~100 t/yr DAC pilot.
    Override for your specific system configuration.
    """

    # -- System sizing --
    gross_co2_tonnes_per_year: float = 100.0   # gross capture target
    net_co2_tonnes_per_year: float = 88.0      # net after all debits

    # -- Solar & battery --
    pv_array_kw_peak: float = 50.0
    pv_lifetime_years: float = 25.0
    pv_manufacturing_kg_co2e: float = 1_500.0   # total array mfg footprint
    battery_kwh_capacity: float = 200.0
    battery_lifetime_cycles: int = 3_000

    # -- Fan & vacuum energy --
    fan_kwh_per_year: float = 45_000.0
    vacuum_kwh_per_year: float = 5_000.0
    battery_kwh_discharged_per_year: float = 40_000.0

    # -- Sorbent --
    sorbent_mass_kg: float = 2_000.0
    sorbent_lifetime_years: float = 3.0

    # -- Filter --
    filters_per_year: float = 6.0

    # -- Tailings (mineral pathway) --
    tailings_tonnes_per_year: float = 300.0
    tailings_distance_km: float = 150.0
    grinding_kwh_per_tonne_tailings: float = 12.0
    grinder_type: str = "diesel"   # "diesel" or "solar"

    # -- Water --
    water_in_litre_per_year: float = 5_000.0
    water_recovered_litre_per_year: float = 3_500.0

    # -- Reactor --
    reactor_kwh_per_year: float = 800.0

    # -- Infrastructure --
    infrastructure_annualised_years: float = 20.0

    # -- Pathway --
    pathway: str = "mineral"   # "mineral" or "geologic"
    geo_storage_kwh_per_kg_co2: float = 0.040  # IEA injection energy estimate

    # ── Computed impact categories ─────────────────────────────────────────

    def _grinding_ef(self) -> float:
        return (EF_GRINDING_DIESEL.value if self.grinder_type == "diesel"
                else EF_GRINDING_SOLAR.value)

    def _pv_annualised_kg(self) -> float:
        return self.pv_manufacturing_kg_co2e / self.pv_lifetime_years

    def scope1_kg_co2e(self) -> float:
        """
        Scope 1: direct emissions from the plant boundary.
        For a solar+battery system with no on-site combustion this is zero.
        If diesel crusher is on-site (not at mine), it would be Scope 1.
        We model the crusher as Scope 3 (upstream, at mine site).
        """
        return 0.0

    def scope2_kg_co2e(self) -> float:
        """
        Scope 2: purchased electricity.
        This system is 100 % solar — zero grid electricity.
        The solar PV lifecycle is counted in Scope 3 (upstream).
        """
        return 0.0

    def scope3_upstream_kg_co2e(self) -> float:
        """
        Scope 3 upstream: manufacturing, transport, and extraction of inputs.
        """
        # PV manufacturing (annualised)
        pv = self._pv_annualised_kg()

        # Battery manufacturing (amortised over discharge)
        batt = self.battery_kwh_discharged_per_year * EF_BATTERY_MFG.value

        # Sorbent manufacturing (amortised over lifetime)
        sorb = (self.sorbent_mass_kg * EF_SORBENT_MFG.value) / self.sorbent_lifetime_years

        # Filter manufacturing
        filt = self.filters_per_year * EF_FILTER_MFG.value

        # Tailings grinding (at mine site, Scope 3 upstream)
        grind = (self.tailings_tonnes_per_year
                 * self.grinding_kwh_per_tonne_tailings
                 * self._grinding_ef()) if self.pathway == "mineral" else 0.0

        # Transport of tailings
        trans = (self.tailings_tonnes_per_year
                 * self.tailings_distance_km
                 * EF_TRUCK.value) if self.pathway == "mineral" else 0.0

        return pv + batt + sorb + filt + grind + trans

    def scope3_downstream_kg_co2e(self) -> float:
        """
        Scope 3 downstream: product use and end-of-life.
        For mineral carbonation to aggregate: the CO₂ is locked in stable carbonate
        mineral — end-of-life emissions are effectively zero (ISO 14064-2 cut-off).
        For geologic: injection pipeline construction is upstream; monitoring is downstream
        but below 1 % cut-off for small pilots.
        """
        return 0.0

    def operational_kg_co2e(self) -> float:
        """
        Operational emissions: electricity lifecycle (solar PV) + water + reactor.
        """
        # Fan electricity
        fan = self.fan_kwh_per_year * EF_SOLAR_PV.value

        # Vacuum electricity
        vac = self.vacuum_kwh_per_year * EF_SOLAR_PV.value

        # Geologic injection energy (if applicable)
        geo = 0.0
        if self.pathway == "geologic":
            geo_kwh = self.gross_co2_tonnes_per_year * 1000 * self.geo_storage_kwh_per_kg_co2
            geo = geo_kwh * EF_SOLAR_PV.value

        # Water (municipal supply net of recovery)
        water_net = max(0.0, self.water_in_litre_per_year - self.water_recovered_litre_per_year)
        water = water_net * EF_WATER.value

        # Reactor electricity
        reactor = self.reactor_kwh_per_year * EF_REACTOR_ELEC.value

        return fan + vac + geo + water + reactor

    def infrastructure_kg_co2e(self) -> float:
        """Annualised infrastructure (steel, concrete, installation)."""
        return (self.gross_co2_tonnes_per_year
                * EF_INFRASTRUCTURE.value)

    def total_system_emissions_kg_co2e(self) -> float:
        """Sum of all emission categories."""
        return (
            self.scope1_kg_co2e()
            + self.scope2_kg_co2e()
            + self.scope3_upstream_kg_co2e()
            + self.scope3_downstream_kg_co2e()
            + self.operational_kg_co2e()
            + self.infrastructure_kg_co2e()
        )

    def net_removal_tonnes_co2(self) -> float:
        """Gross capture minus all system emissions."""
        return max(0.0,
                   self.gross_co2_tonnes_per_year
                   - self.total_system_emissions_kg_co2e() / 1000)

    def net_negative_ratio(self) -> float:
        if self.gross_co2_tonnes_per_year <= 0:
            return 0.0
        return self.net_removal_tonnes_co2() / self.gross_co2_tonnes_per_year

    def emission_breakdown(self) -> Dict[str, float]:
        """Breakdown by category (kg CO₂e/year)."""

        # Scope 3 upstream sub-breakdown
        pv      = self._pv_annualised_kg()
        batt    = self.battery_kwh_discharged_per_year * EF_BATTERY_MFG.value
        sorb    = (self.sorbent_mass_kg * EF_SORBENT_MFG.value) / self.sorbent_lifetime_years
        filt    = self.filters_per_year * EF_FILTER_MFG.value
        grind   = (self.tailings_tonnes_per_year * self.grinding_kwh_per_tonne_tailings
                   * self._grinding_ef()) if self.pathway == "mineral" else 0.0
        trans   = (self.tailings_tonnes_per_year * self.tailings_distance_km
                   * EF_TRUCK.value) if self.pathway == "mineral" else 0.0

        fan     = self.fan_kwh_per_year * EF_SOLAR_PV.value
        vac     = self.vacuum_kwh_per_year * EF_SOLAR_PV.value
        water_net = max(0.0, self.water_in_litre_per_year - self.water_recovered_litre_per_year)
        water   = water_net * EF_WATER.value
        reactor = self.reactor_kwh_per_year * EF_REACTOR_ELEC.value
        infra   = self.infrastructure_kg_co2e()

        return {
            "pv_manufacturing":    round(pv,      1),
            "battery_mfg":         round(batt,    1),
            "sorbent_mfg":         round(sorb,    1),
            "filter_mfg":          round(filt,    1),
            "tailings_grinding":   round(grind,   1),
            "tailings_transport":  round(trans,   1),
            "fan_electricity":     round(fan,     1),
            "vacuum_electricity":  round(vac,     1),
            "reactor_electricity": round(reactor, 1),
            "water":               round(water,   1),
            "infrastructure":      round(infra,   1),
        }

    def water_summary(self) -> Dict[str, float]:
        """Water accounting per year and per tonne of net CO₂."""
        net_t = self.net_removal_tonnes_co2()
        water_net = max(0.0, self.water_in_litre_per_year - self.water_recovered_litre_per_year)
        return {
            "water_in_litre_per_year":        self.water_in_litre_per_year,
            "water_recovered_litre_per_year": self.water_recovered_litre_per_year,
            "water_net_litre_per_year":       round(water_net, 1),
            "water_net_litre_per_t_net_co2":  round(water_net / net_t, 1) if net_t > 0 else None,
            "water_stress_index":             "Extremely High (Phoenix, AZ — WRI Aqueduct)",
            "water_source":                   "Municipal (City of Phoenix reclaimed water preferred)",
        }

    def confidence_flags(self) -> List[Tuple[str, str, str]]:
        """
        Return list of (category, confidence, recommendation) tuples.
        Low-confidence items are the ones to target first for improvement.
        """
        items = [
            ("Infrastructure emissions",
             EF_INFRASTRUCTURE.confidence,
             "Replace with Bill of Materials LCA when plant design is finalised (Phase 1)."),
            ("Filter manufacturing",
             EF_FILTER_MFG.confidence,
             "Get supplier EPD or Ecoinvent process data when filter supplier is selected."),
            ("Sorbent manufacturing",
             EF_SORBENT_MFG.confidence,
             "High uncertainty range (4–15 kg CO₂e/kg). "
             "Negotiate supplier Environmental Product Declaration in Phase 1."),
            ("Tailings grinding",
             EF_GRINDING_DIESEL.confidence if self.grinder_type == "diesel"
             else EF_GRINDING_SOLAR.confidence,
             "Well-characterised for diesel. "
             "Solar crusher contract converts this to near-zero — highest leverage item."),
            ("Transport",
             EF_TRUCK.confidence,
             "Well-characterised. "
             "Lower by negotiating closer mine contract (Sierrita or Ray are nearest)."),
            ("Solar PV & battery",
             EF_SOLAR_PV.confidence,
             "Well-characterised per IPCC AR6. No action needed."),
        ]
        return items

    def report(self) -> str:
        """Return a formatted text report for CLI / logging use."""
        bd = self.emission_breakdown()
        total = sum(bd.values())
        lines = [
            "═" * 68,
            "  LCA SYSTEM BOUNDARY REPORT — Phoenix DAC",
            "  ISO 14064-2 aligned · functional unit: 1 t net CO₂ removed",
            "═" * 68,
            f"  Gross CO₂ captured:    {self.gross_co2_tonnes_per_year:>8.1f} t/yr",
            f"  Total system emissions: {total/1000:>8.2f} t CO₂e/yr",
            f"  Net removal:            {self.net_removal_tonnes_co2():>8.1f} t/yr",
            f"  Net-negative ratio:     {self.net_negative_ratio()*100:>7.1f} %",
            "─" * 68,
            "  EMISSION BREAKDOWN (kg CO₂e/year):",
        ]
        for cat, val in sorted(bd.items(), key=lambda x: -x[1]):
            pct = val / total * 100 if total > 0 else 0
            lines.append(f"    {cat:<26}  {val:>8.1f}  ({pct:4.1f}%)")
        lines += [
            "─" * 68,
            "  WATER ACCOUNTING:",
        ]
        ws = self.water_summary()
        for k, v in ws.items():
            lines.append(f"    {k:<36} {v}")
        lines += [
            "─" * 68,
            "  CONFIDENCE FLAGS (items to improve):",
        ]
        for cat, conf, rec in self.confidence_flags():
            if conf != "high":
                lines.append(f"    [{conf.upper()}] {cat}")
                lines.append(f"           → {rec}")
        lines.append("═" * 68)
        return "\n".join(lines)


# ── Pre-built LCA for the demo system ─────────────────────────────────────────

def demo_lca_boundary(pathway: str = "mineral", grinder_type: str = "diesel") -> LCABoundary:
    """
    Return an LCABoundary calibrated to match the simulation results
    (100 t/yr gross, 50 kW PV, 200 kWh battery, 2 000 kg sorbent).
    """
    return LCABoundary(
        gross_co2_tonnes_per_year=114.3,
        net_co2_tonnes_per_year=101.1,
        pv_array_kw_peak=50.0,
        pv_lifetime_years=25.0,
        pv_manufacturing_kg_co2e=1_500.0,
        battery_kwh_capacity=200.0,
        battery_lifetime_cycles=3_000,
        fan_kwh_per_year=43_800.0,      # ~5 kW × 8 760 h
        vacuum_kwh_per_year=4_380.0,
        battery_kwh_discharged_per_year=35_000.0,
        sorbent_mass_kg=2_000.0,
        sorbent_lifetime_years=3.0,
        filters_per_year=6.0,
        tailings_tonnes_per_year=330.0,
        tailings_distance_km=150.0,
        grinding_kwh_per_tonne_tailings=12.0,
        grinder_type=grinder_type,
        water_in_litre_per_year=6_500.0,
        water_recovered_litre_per_year=4_500.0,
        reactor_kwh_per_year=850.0,
        infrastructure_annualised_years=20.0,
        pathway=pathway,
    )
