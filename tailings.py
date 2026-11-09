"""
Tailings assay model for mineral carbonation pathway.

Each batch of tailings from an Arizona copper mine has a unique geochemical
profile that determines:
  - How much CO₂ it can permanently mineralise per tonne (reactivity)
  - How much energy is needed to grind it to reactive particle size
  - How far it must be transported to the DAC plant

Real Arizona copper mine data (public sources: USGS, AZDEQ, operator filings):

  Mine          | Location        | Primary silicate   | Reactive fraction
  ─────────────────────────────────────────────────────────────────────────
  Morenci        | Greenlee Co.   | Olivine / pyroxene | 18–22 %
  Bagdad         | Yavapai Co.    | Serpentinite        | 22–28 %
  Sierrita       | Pima Co.       | Wollastonite        | 8–14 %
  Ray            | Pinal Co.      | Mixed silicate      | 12–18 %
  Pinto Valley   | Gila Co.       | Chlorite / talc     | 10–16 %

Reactivity definitions
─────────────────────
  reactive_fraction : fraction of tonne that can carbonate (0–1)
  stoichiometric_ratio : t tailings needed per t CO₂ sequestered
      = 1 / (reactive_fraction × 0.786)
      where 0.786 ≈ CO₂ / (CaO+MgO) mass ratio for typical Ca/Mg silicates
  aggregate_ratio : t aggregate produced per t CO₂ (tailings + CO₂ mass)

Grinding energy
───────────────
  Finer grinding → higher reactivity, but more diesel/electric energy.
  Target particle size: 75 µm for olivine/pyroxene, 100 µm for serpentinite.
  Bond work index (kWh/t) sourced from literature per mineral type.
  If crusher is diesel → CO₂ emission; if electric (solar) → near-zero.
  We model both and let the optimizer choose.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional
import math


# ── Stoichiometry helper ───────────────────────────────────────────────────────

# Molar mass ratio: CO₂ / CaO = 44/56 = 0.786; CO₂ / MgO = 44/40 = 1.1
# Most copper tailings are a mix; we use 0.80 as a practical blended factor.
_CO2_OXIDE_MASS_RATIO = 0.80


def stoich_ratio(reactive_fraction: float) -> float:
    """Tonnes of tailings required per tonne of CO₂ mineralised."""
    if reactive_fraction <= 0:
        return float("inf")
    return 1.0 / (reactive_fraction * _CO2_OXIDE_MASS_RATIO)


def aggregate_ratio(reactive_fraction: float) -> float:
    """Tonnes of solid aggregate produced per tonne of CO₂ (tailings + CO₂ mass)."""
    s = stoich_ratio(reactive_fraction)
    return s + 1.0  # mass balance: tailings + CO₂ → aggregate


# ── Grinding energy model ──────────────────────────────────────────────────────

# Bond Work Index (kWh/t) by primary mineral type (literature median values)
BOND_WI = {
    "olivine_pyroxene":  14.0,   # kWh/t  (Morenci-type)
    "serpentinite":      10.5,   # kWh/t  (Bagdad-type — softer)
    "wollastonite":      12.0,   # kWh/t  (Sierrita-type)
    "mixed_silicate":    13.0,   # kWh/t  (Ray-type)
    "chlorite_talc":      9.5,   # kWh/t  (Pinto Valley — softest)
}

# Target P80 grind size (µm) per mineral — finer = more reactive
TARGET_P80_UM = {
    "olivine_pyroxene":  75,
    "serpentinite":     100,
    "wollastonite":      90,
    "mixed_silicate":    85,
    "chlorite_talc":    110,
}

# Feed P80 from typical ROM tailings: ~500 µm
FEED_P80_UM = 500


def grinding_kwh_per_tonne(mineral_type: str, override_p80_um: Optional[float] = None) -> float:
    """
    Estimate kWh/t to grind from feed P80 to target P80 using Bond's law.
    W = Wi × 10 × (1/√P80 - 1/√F80)  [P80, F80 in µm; W in kWh/t]
    """
    wi    = BOND_WI.get(mineral_type, 13.0)
    p80   = override_p80_um if override_p80_um else TARGET_P80_UM.get(mineral_type, 85)
    f80   = FEED_P80_UM
    w     = wi * 10 * (1 / math.sqrt(p80) - 1 / math.sqrt(f80))
    return max(0.0, w)


# ── Transport emission factor ──────────────────────────────────────────────────

# Freight truck: 0.062 kg CO₂e / (tonne · km)  — Arizona Dept. of Transportation avg
EF_TRUCK_KG_CO2E_PER_T_KM = 0.062


def transport_co2_kg_per_tonne(distance_km: float) -> float:
    return distance_km * EF_TRUCK_KG_CO2E_PER_T_KM


# ── Diesel vs electric grinding ────────────────────────────────────────────────

# Diesel generator: 0.27 kg CO₂e/kWh (Arizona grid diesel backup)
EF_DIESEL_KG_CO2E_PER_KWH = 0.27
# On-site solar grinding: lifecycle 20 g CO₂e/kWh (same as PV assumption)
EF_SOLAR_KG_CO2E_PER_KWH  = 0.020


@dataclass
class TailingsAssay:
    """
    Represents a single sourced batch of mine tailings.

    All per-tonne figures are per tonne of TAILINGS unless noted.
    """
    name: str                        # e.g. "Morenci Lot 2024-Q3"
    mine_site: str                   # e.g. "Morenci"
    mineral_type: str                # key into BOND_WI dict
    reactive_fraction: float         # 0–1 (fraction of tailings mass that carbonates)
    distance_km: float               # transport distance to DAC plant
    batch_tonnes: float              # total tailings available in this batch
    grinder_type: str = "diesel"     # "diesel" or "solar"
    override_p80_um: Optional[float] = None  # override target grind size if known
    notes: str = ""
    # Solar-crusher contract: one-time capex to convert mine crusher to solar-electric.
    # Spread over expected contract volume (total tonnes to be processed under contract).
    # Set to 0 if no conversion needed (grinder_type already "solar").
    solar_crusher_contract_usd: float = 0.0      # total contract capex (USD)
    solar_crusher_contract_tonnes: float = 1.0   # total tonnes covered by that contract

    # ── Derived properties ──────────────────────────────────────────────────────

    @property
    def t_tailings_per_t_co2(self) -> float:
        """Tonnes of this tailings needed to mineralise 1 tonne CO₂."""
        return stoich_ratio(self.reactive_fraction)

    @property
    def t_aggregate_per_t_co2(self) -> float:
        return aggregate_ratio(self.reactive_fraction)

    @property
    def grinding_kwh_per_t_tailings(self) -> float:
        return grinding_kwh_per_tonne(self.mineral_type, self.override_p80_um)

    @property
    def grinding_co2_kg_per_t_tailings(self) -> float:
        ef = EF_DIESEL_KG_CO2E_PER_KWH if self.grinder_type == "diesel" else EF_SOLAR_KG_CO2E_PER_KWH
        return self.grinding_kwh_per_t_tailings * ef

    @property
    def transport_co2_kg_per_t_tailings(self) -> float:
        return transport_co2_kg_per_tonne(self.distance_km)

    @property
    def total_process_co2_kg_per_t_tailings(self) -> float:
        """Total kg CO₂e emitted per tonne of tailings processed."""
        return self.grinding_co2_kg_per_t_tailings + self.transport_co2_kg_per_t_tailings

    @property
    def process_co2_kg_per_t_co2_sequestered(self) -> float:
        """
        Net emission cost to sequester 1 tonne CO₂ via THIS tailings batch.
        This is the key optimisation figure: lower is better.
        """
        return self.total_process_co2_kg_per_t_tailings * self.t_tailings_per_t_co2

    @property
    def max_co2_sequestrable_tonnes(self) -> float:
        """Maximum CO₂ this batch can sequester given its available mass."""
        return self.batch_tonnes / self.t_tailings_per_t_co2

    @property
    def net_negative_efficiency(self) -> float:
        """
        1 - (process_co2 / 1000 kg)  — fraction of each sequestered tonne
        that survives as a true net-negative credit.
        Higher = better batch.
        """
        return max(0.0, 1.0 - self.process_co2_kg_per_t_co2_sequestered / 1000)

    @property
    def solar_crusher_contract_usd_per_t_tailings(self) -> float:
        """Amortised contract capex per tonne of tailings processed."""
        if self.solar_crusher_contract_tonnes <= 0:
            return 0.0
        return self.solar_crusher_contract_usd / self.solar_crusher_contract_tonnes

    def cost_usd_per_t_co2(
        self,
        grinding_cost_usd_per_kwh: float = 0.08,
        transport_cost_usd_per_t_km: float = 0.15,
    ) -> float:
        """Estimated processing cost per tonne CO₂ sequestered (including contract capex)."""
        grind_cost    = (self.grinding_kwh_per_t_tailings * grinding_cost_usd_per_kwh
                         * self.t_tailings_per_t_co2)
        trans_cost    = (self.distance_km * transport_cost_usd_per_t_km
                         * self.t_tailings_per_t_co2)
        contract_cost = (self.solar_crusher_contract_usd_per_t_tailings
                         * self.t_tailings_per_t_co2)
        return grind_cost + trans_cost + contract_cost

    def summary_dict(self) -> dict:
        return {
            "name":                      self.name,
            "mine_site":                 self.mine_site,
            "mineral_type":              self.mineral_type,
            "reactive_fraction_%":       round(self.reactive_fraction * 100, 1),
            "distance_km":               self.distance_km,
            "batch_tonnes":              self.batch_tonnes,
            "grinder_type":              self.grinder_type,
            "solar_crusher_contract_usd":         self.solar_crusher_contract_usd,
            "solar_crusher_contract_tonnes":      self.solar_crusher_contract_tonnes,
            "notes":                     self.notes,
            "t_tailings/t_CO2":          round(self.t_tailings_per_t_co2, 2),
            "t_aggregate/t_CO2":         round(self.t_aggregate_per_t_co2, 2),
            "grind_kwh/t_tailings":      round(self.grinding_kwh_per_t_tailings, 2),
            "grind_CO2e_kg/t_tailings":  round(self.grinding_co2_kg_per_t_tailings, 3),
            "transport_CO2e_kg/t_tailings": round(self.transport_co2_kg_per_t_tailings, 3),
            "process_CO2e_kg/t_CO2_seq": round(self.process_co2_kg_per_t_co2_sequestered, 1),
            "net_neg_efficiency_%":      round(self.net_negative_efficiency * 100, 1),
            "max_CO2_seq_t":             round(self.max_co2_sequestrable_tonnes, 1),
        }


# ── Tailings blending ──────────────────────────────────────────────────────────

def blend_assays(
    assays: List["TailingsAssay"],
    fractions: List[float],
    blended_name: str = "Blended Lot",
) -> "TailingsAssay":
    """
    Produce a single blended TailingsAssay from multiple lots.

    fractions : weight proportions for each assay (will be normalised to sum=1).
                Length must match len(assays).

    The blended assay uses:
      - Weighted-average reactive_fraction
      - Weighted-average distance_km
      - Weighted-average grinding energy (via mineral-type lookup)
      - Batch tonnes = sum of proportional contributions
      - grinder_type = "solar" only if ALL constituent assays are solar
      - solar_crusher_contract figures summed proportionally

    This lets the optimizer use one uniform assay object while the
    underlying accounting reflects a real mixed-stockpile scenario.
    """
    if not assays:
        raise ValueError("blend_assays requires at least one assay")
    if len(assays) != len(fractions):
        raise ValueError("len(assays) must equal len(fractions)")

    total = sum(fractions)
    if total <= 0:
        raise ValueError("fractions must sum to a positive number")
    w = [f / total for f in fractions]   # normalised weights

    blended_reactive  = sum(a.reactive_fraction * wi for a, wi in zip(assays, w))
    blended_distance  = sum(a.distance_km        * wi for a, wi in zip(assays, w))
    blended_tonnes    = sum(a.batch_tonnes        * wi for a, wi in zip(assays, w))
    all_solar         = all(a.grinder_type == "solar" for a in assays)

    # Weighted contract capex (amortised per tonne)
    blended_contract_usd    = sum(
        a.solar_crusher_contract_usd * wi for a, wi in zip(assays, w)
    )
    blended_contract_tonnes = sum(
        a.solar_crusher_contract_tonnes * wi for a, wi in zip(assays, w)
    )

    # For mineral_type: pick the dominant type by weight
    type_weights: dict = {}
    for a, wi in zip(assays, w):
        type_weights[a.mineral_type] = type_weights.get(a.mineral_type, 0) + wi
    dominant_type = max(type_weights, key=type_weights.__getitem__)

    mine_sites = ", ".join(dict.fromkeys(a.mine_site for a in assays))

    return TailingsAssay(
        name=blended_name,
        mine_site=mine_sites,
        mineral_type=dominant_type,
        reactive_fraction=blended_reactive,
        distance_km=blended_distance,
        batch_tonnes=blended_tonnes,
        grinder_type="solar" if all_solar else "diesel",
        solar_crusher_contract_usd=blended_contract_usd,
        solar_crusher_contract_tonnes=blended_contract_tonnes,
        notes=f"Blended from: {mine_sites}",
    )


# ── Built-in Arizona mine database ────────────────────────────────────────────

def arizona_mine_defaults() -> List[TailingsAssay]:
    """
    Return a list of representative tailings assays from Arizona copper mines.
    Values are based on published USGS/AZDEQ data and operator environmental reports.
    Reactive fractions shown as midpoint of reported range.
    Distances are approximate road km to a DAC plant sited near Casa Grande, AZ.
    """
    return [
        TailingsAssay(
            name="Morenci Standard Lot",
            mine_site="Morenci",
            mineral_type="olivine_pyroxene",
            reactive_fraction=0.20,     # midpoint of 18–22 %
            distance_km=230,
            batch_tonnes=50_000,
            grinder_type="diesel",
            notes="Freeport-McMoRan. High olivine content, requires fine grind to 75 µm.",
        ),
        TailingsAssay(
            name="Bagdad High-Reactivity Lot",
            mine_site="Bagdad",
            mineral_type="serpentinite",
            reactive_fraction=0.25,     # midpoint of 22–28 %
            distance_km=310,
            batch_tonnes=30_000,
            grinder_type="diesel",
            notes="Freeport-McMoRan. Serpentinite is softest — lower grind energy.",
        ),
        TailingsAssay(
            name="Sierrita Low-Reactivity Lot",
            mine_site="Sierrita",
            mineral_type="wollastonite",
            reactive_fraction=0.11,     # midpoint of 8–14 %
            distance_km=90,
            batch_tonnes=80_000,
            grinder_type="diesel",
            notes="Freeport-McMoRan. Closest mine but lowest reactivity; requires more tailings per t CO₂.",
        ),
        TailingsAssay(
            name="Ray Medium Lot",
            mine_site="Ray",
            mineral_type="mixed_silicate",
            reactive_fraction=0.15,     # midpoint of 12–18 %
            distance_km=110,
            batch_tonnes=40_000,
            grinder_type="diesel",
            notes="Asarco. Mixed silicate profile; moderate reactivity and proximity.",
        ),
        TailingsAssay(
            name="Pinto Valley Solar-Ground",
            mine_site="Pinto Valley",
            mineral_type="chlorite_talc",
            reactive_fraction=0.13,     # midpoint of 10–16 %
            distance_km=150,
            batch_tonnes=25_000,
            grinder_type="solar",       # ← this mine has on-site solar grinding
            notes="BHP. Chlorite/talc — very soft, lowest grind energy. Solar crusher on-site "
                  "dramatically reduces grinding emissions.",
        ),
        TailingsAssay(
            name="Bagdad Solar-Ground Premium",
            mine_site="Bagdad",
            mineral_type="serpentinite",
            reactive_fraction=0.26,
            distance_km=310,
            batch_tonnes=15_000,
            grinder_type="solar",
            notes="Same mine as standard lot but crushed with on-site solar — "
                  "lower emission intensity despite longer haul.",
        ),
    ]


# ── Batch selector ─────────────────────────────────────────────────────────────

def rank_batches(
    assays: List[TailingsAssay],
    co2_to_sequester_t: float,
    weight_emissions: float = 0.6,
    weight_cost: float = 0.4,
) -> List[dict]:
    """
    Score and rank available tailings batches for a given CO₂ sequestration target.

    Scoring:
      score = weight_emissions × (1 - norm_emis) + weight_cost × (1 - norm_cost)

    Higher score = better batch.  Batches with insufficient capacity are flagged.
    """
    if not assays:
        return []

    emis_vals = [a.process_co2_kg_per_t_co2_sequestered for a in assays]
    cost_vals  = [a.cost_usd_per_t_co2() for a in assays]

    emis_min, emis_max = min(emis_vals), max(emis_vals)
    cost_min, cost_max = min(cost_vals),  max(cost_vals)

    results = []
    for assay, emis, cost in zip(assays, emis_vals, cost_vals):
        # Normalise 0–1 (lower raw value = higher norm score)
        norm_emis = (emis - emis_min) / (emis_max - emis_min + 1e-9)
        norm_cost = (cost - cost_min) / (cost_max - cost_min + 1e-9)
        score = weight_emissions * (1 - norm_emis) + weight_cost * (1 - norm_cost)

        sufficient = assay.max_co2_sequestrable_tonnes >= co2_to_sequester_t

        results.append({
            **assay.summary_dict(),
            "composite_score":    round(score, 4),
            "sufficient_supply":  sufficient,
            "shortfall_t":        max(0.0, co2_to_sequester_t - assay.max_co2_sequestrable_tonnes),
        })

    results.sort(key=lambda r: r["composite_score"], reverse=True)
    return results
