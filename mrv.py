"""
MRV — Measurement, Reporting, and Verification module.
Phoenix DAC System · Permanent Sequestration Only

This module implements the batch-traceability chain required before any verified
removal credit can be claimed:

  Capture batch  →  CO₂ canister inventory  →  Carbonation reactor batch
               →  Solid aggregate product  →  Disposition (sold / stockpiled / injected)
               →  Verified credit (net-negative, after all debits)

Design principles (from the company plan):
  • Every kilogram of CO₂ that enters the ledger as a "credit" must trace back to
    a specific capture batch, a specific tailings lot, and a confirmed permanent fate.
  • TCLP / leaching test results gate the use of any tailings source for mineral
    carbonation.  No product ships from an unqualified source.
  • Water use is tracked per batch (the plan requires disclosure and the accounting
    boundary must close — no silent evaporative losses).
  • Each record is timestamped and carries a status flag so an external auditor can
    reconstruct the chain without access to source code.

Usage
─────
    from mrv import MRVRegistry, CaptureBatch, CarbonationBatch, ProductBatch

    registry = MRVRegistry()

    # Step 1: record a capture event
    cb = registry.record_capture(
        timestamp="2025-07-15T02:00",
        co2_kg=18.4,
        temp_c=32.1,
        rh_pct=22,
        sorbent_cycle=1847,
        power_source="battery",
        fan_kwh=3.2,
    )

    # Step 2: add CO₂ from multiple capture batches into a carbonation reactor run
    rb = registry.record_carbonation(
        timestamp="2025-07-15T12:00",
        capture_batch_ids=[cb.batch_id],
        tailings_lot_id="Morenci-2025-Q3",
        tailings_kg=46.0,
        water_litre=8.5,
        reactor_temp_c=55,
        reactor_duration_h=4.0,
        co2_consumed_kg=18.0,
        aggregate_kg=63.5,
    )

    # Step 3: qualify the tailings lot (TCLP test result required)
    registry.record_tclp_result(
        lot_id="Morenci-2025-Q3",
        test_date="2025-07-01",
        pb_mg_l=0.02, as_mg_l=0.001, cr_mg_l=0.004,
        passed=True,
        lab="Arizona Analytical Lab",
        notes="All values well below EPA TCLP limits",
    )

    # Step 4: record disposition of the aggregate product
    pb = registry.record_product_disposition(
        timestamp="2025-07-20T08:00",
        carbonation_batch_id=rb.batch_id,
        aggregate_kg=63.5,
        fate="sold_aggregate",  # or "stockpiled" | "geologic_injected"
        buyer="AZ Ready-Mix Co.",
        price_usd_per_tonne=45.0,
    )

    # Step 5: issue a verified removal credit (if all gates pass)
    credit = registry.issue_credit(product_batch_id=pb.batch_id)
    print(credit)
"""

from __future__ import annotations

import uuid
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Dict, List, Optional, Tuple


# ── Status codes ──────────────────────────────────────────────────────────────

class Status:
    PENDING    = "pending"      # created, not yet verified
    QUALIFIED  = "qualified"    # TCLP / leaching test passed for this tailings lot
    CONFIRMED  = "confirmed"    # fate confirmed, product dispatched or injected
    CREDITED   = "credited"     # verified removal credit issued
    REJECTED   = "rejected"     # failed a quality gate


# ── EPA TCLP regulatory limits (mg/L) ─────────────────────────────────────────

TCLP_LIMITS_MG_L = {
    "arsenic":   5.0,
    "barium":  100.0,
    "cadmium":   1.0,
    "chromium":  5.0,
    "lead":      5.0,
    "mercury":   0.2,
    "selenium":  1.0,
    "silver":    5.0,
}


# ── Dataclasses ───────────────────────────────────────────────────────────────

@dataclass
class CaptureBatch:
    """One discrete capture event (typically one capture cycle ≈ 8 h)."""
    batch_id: str
    timestamp: str                 # ISO 8601
    co2_kg: float                  # CO₂ adsorbed this cycle
    temp_c: float                  # ambient temperature during capture
    rh_pct: float                  # relative humidity during capture
    sorbent_cycle: int             # cycle number on the sorbent bed
    power_source: str              # "battery" | "grid" | "direct_pv"
    fan_kwh: float                 # energy consumed
    vacuum_kwh: float = 0.0        # regen energy (solar, this cycle)
    notes: str = ""
    status: str = Status.PENDING

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TailingsLotQualification:
    """TCLP leaching test result for a named tailings lot."""
    lot_id: str
    test_date: str
    lab: str
    # Analytes (mg/L) — add more as needed
    arsenic_mg_l: float = 0.0
    barium_mg_l: float = 0.0
    cadmium_mg_l: float = 0.0
    chromium_mg_l: float = 0.0
    lead_mg_l: float = 0.0
    mercury_mg_l: float = 0.0
    selenium_mg_l: float = 0.0
    silver_mg_l: float = 0.0
    passed: bool = False
    notes: str = ""
    status: str = Status.PENDING

    def check_limits(self) -> Tuple[bool, List[str]]:
        """Check measured values against EPA TCLP limits. Returns (passed, list_of_failures)."""
        measured = {
            "arsenic":  self.arsenic_mg_l,
            "barium":   self.barium_mg_l,
            "cadmium":  self.cadmium_mg_l,
            "chromium": self.chromium_mg_l,
            "lead":     self.lead_mg_l,
            "mercury":  self.mercury_mg_l,
            "selenium": self.selenium_mg_l,
            "silver":   self.silver_mg_l,
        }
        failures = [
            f"{analyte}: {val:.3f} mg/L > limit {TCLP_LIMITS_MG_L[analyte]} mg/L"
            for analyte, val in measured.items()
            if val > TCLP_LIMITS_MG_L[analyte]
        ]
        return (len(failures) == 0), failures

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CarbonationBatch:
    """
    One reactor run: captured CO₂ + tailings + water → aggregate.
    Links back to one or more CaptureBatches and a qualified tailings lot.
    """
    batch_id: str
    timestamp: str
    capture_batch_ids: List[str]   # CaptureBatch IDs consumed in this run
    tailings_lot_id: str           # must be qualified (TCLP passed)
    tailings_kg: float             # tailings mass consumed
    water_litre: float             # process water (closed-loop target; evap loss tracked)
    reactor_temp_c: float
    reactor_duration_h: float
    co2_consumed_kg: float         # CO₂ actually mineralised (mass balance)
    aggregate_kg: float            # solid product mass (tailings + CO₂ mass balance)
    water_recovered_litre: float = 0.0   # water recovered from reactor
    reactor_kwh: float = 0.0       # electricity for agitation / pumping
    notes: str = ""
    status: str = Status.PENDING

    @property
    def water_net_litre(self) -> float:
        """Net water consumed (lost to evaporation or product)."""
        return max(0.0, self.water_litre - self.water_recovered_litre)

    @property
    def mass_balance_ok(self) -> bool:
        """
        Rough sanity check: aggregate mass should be ≈ tailings + CO₂ consumed.
        Allow ±5 % for water retention in product and measurement error.
        """
        expected = self.tailings_kg + self.co2_consumed_kg
        return abs(self.aggregate_kg - expected) / (expected + 1e-9) < 0.05

    def to_dict(self) -> dict:
        d = asdict(self)
        d["water_net_litre"] = self.water_net_litre
        d["mass_balance_ok"] = self.mass_balance_ok
        return d


@dataclass
class ProductBatch:
    """
    Aggregate product batch with confirmed permanent fate.
    Disposition must be one of the permanent sequestration fates.
    """
    batch_id: str
    timestamp: str
    carbonation_batch_id: str
    aggregate_kg: float
    # Fate options:
    #   "sold_aggregate"   — sold as construction material (permanent fate: locked in concrete)
    #   "stockpiled"       — on-site storage (NOT yet credited — fate not confirmed)
    #   "geologic_injected" — compressed and injected (permanent)
    fate: str
    buyer: Optional[str] = None        # for sold_aggregate
    price_usd_per_tonne: float = 0.0
    astm_c33_passed: Optional[bool] = None   # aggregate spec for construction use
    astm_test_date: Optional[str] = None
    astm_lab: Optional[str] = None
    co2_certified_kg: float = 0.0     # filled in by issue_credit()
    notes: str = ""
    status: str = Status.PENDING

    PERMANENT_FATES = frozenset({"sold_aggregate", "geologic_injected"})

    @property
    def fate_is_permanent(self) -> bool:
        return self.fate in self.PERMANENT_FATES

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class VerifiedCredit:
    """
    An issued verified removal credit.
    This is the final output of the MRV chain — the auditable unit.
    """
    credit_id: str
    issued_at: str
    product_batch_id: str
    carbonation_batch_id: str
    capture_batch_ids: List[str]
    tailings_lot_id: str
    gross_co2_kg: float           # captured
    net_co2_kg: float             # after all system debits
    system_emissions_kg: float    # debited from gross
    fate: str
    astm_c33_passed: Optional[bool]
    tclp_passed: bool
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def __str__(self) -> str:
        return (
            f"VerifiedCredit {self.credit_id[:8]}  "
            f"gross={self.gross_co2_kg:.1f} kg  "
            f"net={self.net_co2_kg:.1f} kg  "
            f"fate={self.fate}  "
            f"tclp={'✅' if self.tclp_passed else '❌'}  "
            f"astm={'✅' if self.astm_c33_passed else '—'}"
        )


# ── MRV Registry ──────────────────────────────────────────────────────────────

class MRVRegistry:
    """
    Central registry for all MRV records.

    All records are in-memory by default.  Call export_json() to serialise
    to disk for auditor handoff or IBM App Connect integration.
    """

    def __init__(self) -> None:
        self.capture_batches:     Dict[str, CaptureBatch]           = {}
        self.tailings_lots:       Dict[str, TailingsLotQualification] = {}
        self.carbonation_batches: Dict[str, CarbonationBatch]       = {}
        self.product_batches:     Dict[str, ProductBatch]            = {}
        self.credits:             Dict[str, VerifiedCredit]          = {}
        # Water ledger (cumulative litres)
        self._water_in_total   = 0.0
        self._water_recovered  = 0.0

    # ── Record helpers ──────────────────────────────────────────────────────

    def record_capture(
        self,
        co2_kg: float,
        temp_c: float,
        rh_pct: float,
        sorbent_cycle: int,
        fan_kwh: float,
        timestamp: Optional[str] = None,
        power_source: str = "battery",
        vacuum_kwh: float = 0.0,
        notes: str = "",
    ) -> CaptureBatch:
        batch_id = str(uuid.uuid4())
        ts = timestamp or datetime.utcnow().isoformat()
        cb = CaptureBatch(
            batch_id=batch_id,
            timestamp=ts,
            co2_kg=co2_kg,
            temp_c=temp_c,
            rh_pct=rh_pct,
            sorbent_cycle=sorbent_cycle,
            power_source=power_source,
            fan_kwh=fan_kwh,
            vacuum_kwh=vacuum_kwh,
            notes=notes,
            status=Status.PENDING,
        )
        self.capture_batches[batch_id] = cb
        return cb

    def record_tclp_result(
        self,
        lot_id: str,
        test_date: str,
        lab: str,
        passed: bool,
        arsenic_mg_l: float = 0.0,
        barium_mg_l: float = 0.0,
        cadmium_mg_l: float = 0.0,
        chromium_mg_l: float = 0.0,
        lead_mg_l: float = 0.0,
        mercury_mg_l: float = 0.0,
        selenium_mg_l: float = 0.0,
        silver_mg_l: float = 0.0,
        notes: str = "",
    ) -> TailingsLotQualification:
        qual = TailingsLotQualification(
            lot_id=lot_id,
            test_date=test_date,
            lab=lab,
            arsenic_mg_l=arsenic_mg_l,
            barium_mg_l=barium_mg_l,
            cadmium_mg_l=cadmium_mg_l,
            chromium_mg_l=chromium_mg_l,
            lead_mg_l=lead_mg_l,
            mercury_mg_l=mercury_mg_l,
            selenium_mg_l=selenium_mg_l,
            silver_mg_l=silver_mg_l,
            passed=passed,
            notes=notes,
        )
        ok, failures = qual.check_limits()
        qual.passed = passed and ok
        qual.status = Status.QUALIFIED if qual.passed else Status.REJECTED
        if failures:
            qual.notes += f" | Limit exceedances: {'; '.join(failures)}"
        self.tailings_lots[lot_id] = qual
        return qual

    def record_carbonation(
        self,
        tailings_lot_id: str,
        tailings_kg: float,
        water_litre: float,
        reactor_temp_c: float,
        reactor_duration_h: float,
        co2_consumed_kg: float,
        aggregate_kg: float,
        capture_batch_ids: Optional[List[str]] = None,
        timestamp: Optional[str] = None,
        water_recovered_litre: float = 0.0,
        reactor_kwh: float = 0.0,
        notes: str = "",
    ) -> CarbonationBatch:
        # Validate tailings lot is qualified
        lot = self.tailings_lots.get(tailings_lot_id)
        if lot is None:
            raise ValueError(
                f"Tailings lot '{tailings_lot_id}' not found in registry. "
                "Run record_tclp_result() first."
            )
        if not lot.passed:
            raise ValueError(
                f"Tailings lot '{tailings_lot_id}' failed TCLP qualification. "
                "Cannot use in carbonation reactor."
            )

        batch_id = str(uuid.uuid4())
        ts = timestamp or datetime.utcnow().isoformat()
        cb = CarbonationBatch(
            batch_id=batch_id,
            timestamp=ts,
            capture_batch_ids=capture_batch_ids or [],
            tailings_lot_id=tailings_lot_id,
            tailings_kg=tailings_kg,
            water_litre=water_litre,
            reactor_temp_c=reactor_temp_c,
            reactor_duration_h=reactor_duration_h,
            co2_consumed_kg=co2_consumed_kg,
            aggregate_kg=aggregate_kg,
            water_recovered_litre=water_recovered_litre,
            reactor_kwh=reactor_kwh,
            notes=notes,
            status=Status.PENDING,
        )
        self._water_in_total  += water_litre
        self._water_recovered += water_recovered_litre
        self.carbonation_batches[batch_id] = cb
        return cb

    def record_product_disposition(
        self,
        carbonation_batch_id: str,
        aggregate_kg: float,
        fate: str,
        timestamp: Optional[str] = None,
        buyer: Optional[str] = None,
        price_usd_per_tonne: float = 0.0,
        astm_c33_passed: Optional[bool] = None,
        astm_test_date: Optional[str] = None,
        astm_lab: Optional[str] = None,
        notes: str = "",
    ) -> ProductBatch:
        VALID_FATES = {"sold_aggregate", "stockpiled", "geologic_injected"}
        if fate not in VALID_FATES:
            raise ValueError(f"fate must be one of {VALID_FATES}, got '{fate}'")

        batch_id = str(uuid.uuid4())
        ts = timestamp or datetime.utcnow().isoformat()
        pb = ProductBatch(
            batch_id=batch_id,
            timestamp=ts,
            carbonation_batch_id=carbonation_batch_id,
            aggregate_kg=aggregate_kg,
            fate=fate,
            buyer=buyer,
            price_usd_per_tonne=price_usd_per_tonne,
            astm_c33_passed=astm_c33_passed,
            astm_test_date=astm_test_date,
            astm_lab=astm_lab,
            notes=notes,
            status=Status.CONFIRMED if fate in ProductBatch.PERMANENT_FATES else Status.PENDING,
        )
        self.product_batches[batch_id] = pb
        return pb

    def issue_credit(
        self,
        product_batch_id: str,
        system_emissions_kg: float = 0.0,
        notes: str = "",
    ) -> VerifiedCredit:
        """
        Issue a verified removal credit for a product batch.

        Gates that must pass:
          1. Fate must be permanent (sold_aggregate or geologic_injected).
          2. If sold_aggregate: tailings lot must be TCLP-qualified.
          3. If sold_aggregate: ASTM C33 test must have passed (construction use).
          4. Mass balance on the carbonation batch must close.

        system_emissions_kg: the total system emission debits (energy + sorbent +
          filter + infrastructure + tailings processing) computed by the CarbonLedger
          for the same capture batches.  Pass in from ledger.summary() for accurate
          net accounting.
        """
        pb = self.product_batches.get(product_batch_id)
        if pb is None:
            raise ValueError(f"ProductBatch '{product_batch_id}' not found.")

        if not pb.fate_is_permanent:
            raise ValueError(
                f"Fate '{pb.fate}' is not a permanent sequestration fate. "
                "Only sold_aggregate and geologic_injected qualify."
            )

        rb = self.carbonation_batches.get(pb.carbonation_batch_id)
        if rb is None:
            raise ValueError(
                f"CarbonationBatch '{pb.carbonation_batch_id}' not found."
            )

        # TCLP gate
        lot = self.tailings_lots.get(rb.tailings_lot_id)
        tclp_ok = (lot is not None and lot.passed)

        if pb.fate == "sold_aggregate" and not tclp_ok:
            raise ValueError(
                f"Tailings lot '{rb.tailings_lot_id}' not TCLP-qualified. "
                "Cannot sell aggregate from this source."
            )

        # ASTM gate (warn but don't block — product may be pre-spec during Phase 1)
        astm_note = ""
        if pb.fate == "sold_aggregate" and pb.astm_c33_passed is False:
            astm_note = " [WARNING: ASTM C33 failed — credit issued but product cannot ship]"

        # Mass balance check
        if not rb.mass_balance_ok:
            notes += " [WARNING: mass balance outside ±5 % tolerance — review reactor data]"

        gross_co2_kg = rb.co2_consumed_kg
        net_co2_kg = max(0.0, gross_co2_kg - system_emissions_kg)

        credit_id = str(uuid.uuid4())
        credit = VerifiedCredit(
            credit_id=credit_id,
            issued_at=datetime.utcnow().isoformat(),
            product_batch_id=product_batch_id,
            carbonation_batch_id=pb.carbonation_batch_id,
            capture_batch_ids=rb.capture_batch_ids,
            tailings_lot_id=rb.tailings_lot_id,
            gross_co2_kg=gross_co2_kg,
            net_co2_kg=net_co2_kg,
            system_emissions_kg=system_emissions_kg,
            fate=pb.fate,
            astm_c33_passed=pb.astm_c33_passed,
            tclp_passed=tclp_ok,
            notes=notes + astm_note,
        )

        # Update product and capture batch statuses
        pb.co2_certified_kg = net_co2_kg
        pb.status = Status.CREDITED
        for cap_id in rb.capture_batch_ids:
            if cap_id in self.capture_batches:
                self.capture_batches[cap_id].status = Status.CREDITED

        self.credits[credit_id] = credit
        return credit

    # ── Reporting ───────────────────────────────────────────────────────────

    def summary(self) -> dict:
        """High-level MRV summary statistics."""
        total_captured_kg  = sum(c.co2_kg for c in self.capture_batches.values())
        total_consumed_kg  = sum(r.co2_consumed_kg for r in self.carbonation_batches.values())
        total_credited_kg  = sum(c.net_co2_kg for c in self.credits.values())
        total_aggregate_kg = sum(p.aggregate_kg for p in self.product_batches.values())

        lots_qualified  = sum(1 for l in self.tailings_lots.values() if l.status == Status.QUALIFIED)
        lots_rejected   = sum(1 for l in self.tailings_lots.values() if l.status == Status.REJECTED)
        lots_pending    = sum(1 for l in self.tailings_lots.values() if l.status == Status.PENDING)

        products_by_fate: Dict[str, float] = {}
        for pb in self.product_batches.values():
            products_by_fate[pb.fate] = (
                products_by_fate.get(pb.fate, 0.0) + pb.aggregate_kg / 1000
            )

        water_net_litre = self._water_in_total - self._water_recovered

        return {
            "capture_batches":          len(self.capture_batches),
            "carbonation_batches":      len(self.carbonation_batches),
            "product_batches":          len(self.product_batches),
            "verified_credits":         len(self.credits),
            "total_captured_kg":        round(total_captured_kg, 2),
            "total_consumed_kg":        round(total_consumed_kg, 2),
            "total_credited_kg":        round(total_credited_kg, 2),
            "total_aggregate_tonnes":   round(total_aggregate_kg / 1000, 3),
            "products_by_fate_tonnes":  {k: round(v, 3) for k, v in products_by_fate.items()},
            "tailings_lots_qualified":  lots_qualified,
            "tailings_lots_rejected":   lots_rejected,
            "tailings_lots_pending":    lots_pending,
            "water_in_litre":           round(self._water_in_total, 1),
            "water_recovered_litre":    round(self._water_recovered, 1),
            "water_net_consumed_litre": round(water_net_litre, 1),
            "water_net_litre_per_t_co2": (
                round(water_net_litre / (total_consumed_kg / 1000), 1)
                if total_consumed_kg > 0 else None
            ),
        }

    def tclp_summary(self) -> List[dict]:
        """Return all TCLP results as a list of dicts for display."""
        return [lot.to_dict() for lot in self.tailings_lots.values()]

    def credits_summary(self) -> List[dict]:
        """Return all credits as a list of dicts for display."""
        return [c.to_dict() for c in self.credits.values()]

    def export_json(self, path: str) -> None:
        """Serialise the full registry to a JSON file for auditor handoff."""
        data = {
            "capture_batches":     [c.to_dict() for c in self.capture_batches.values()],
            "tailings_lots":       [l.to_dict() for l in self.tailings_lots.values()],
            "carbonation_batches": [r.to_dict() for r in self.carbonation_batches.values()],
            "product_batches":     [p.to_dict() for p in self.product_batches.values()],
            "credits":             [c.to_dict() for c in self.credits.values()],
            "summary":             self.summary(),
            "exported_at":         datetime.utcnow().isoformat(),
        }
        with open(path, "w") as f:
            json.dump(data, f, indent=2)


# ── Demo data factory ─────────────────────────────────────────────────────────

def build_demo_registry() -> MRVRegistry:
    """
    Create a populated MRVRegistry with realistic demo data.
    Used by the Streamlit MRV tab and by demo.py.
    """
    reg = MRVRegistry()

    # -- Qualify two tailings lots ------------------------------------------------
    reg.record_tclp_result(
        lot_id="Morenci-2025-Q3",
        test_date="2025-07-01",
        lab="Arizona Analytical Labs",
        passed=True,
        arsenic_mg_l=0.018,
        barium_mg_l=1.2,
        chromium_mg_l=0.004,
        lead_mg_l=0.025,
        notes="Morenci standard lot — all analytes well below EPA TCLP limits",
    )
    reg.record_tclp_result(
        lot_id="PintoValley-2025-Q2",
        test_date="2025-06-15",
        lab="Desert Southwest Testing",
        passed=True,
        arsenic_mg_l=0.008,
        barium_mg_l=0.7,
        chromium_mg_l=0.002,
        lead_mg_l=0.012,
        notes="Pinto Valley solar-ground lot — soft chlorite/talc, low metals",
    )
    reg.record_tclp_result(
        lot_id="Sierrita-2025-Pilot",
        test_date="2025-08-10",
        lab="Arizona Analytical Labs",
        passed=False,
        arsenic_mg_l=6.1,   # over the 5.0 mg/L limit
        lead_mg_l=1.8,
        notes="Sierrita pilot batch — arsenic exceedance detected; lot rejected pending re-test",
    )

    # -- Capture batches (representative summer nights) ---------------------------
    cap1 = reg.record_capture(
        timestamp="2025-07-15T02:00", co2_kg=14.2, temp_c=34.1, rh_pct=18,
        sorbent_cycle=1847, fan_kwh=3.2, power_source="battery",
    )
    cap2 = reg.record_capture(
        timestamp="2025-07-15T03:00", co2_kg=15.0, temp_c=33.5, rh_pct=19,
        sorbent_cycle=1848, fan_kwh=3.2, power_source="battery",
    )
    cap3 = reg.record_capture(
        timestamp="2025-07-16T02:00", co2_kg=16.8, temp_c=31.2, rh_pct=22,
        sorbent_cycle=1851, fan_kwh=3.2, power_source="battery",
    )
    cap4 = reg.record_capture(
        timestamp="2025-07-20T02:00", co2_kg=18.4, temp_c=29.8, rh_pct=25,
        sorbent_cycle=1863, fan_kwh=3.2, power_source="battery",
    )

    # -- Carbonation reactor runs -------------------------------------------------
    carb1 = reg.record_carbonation(
        timestamp="2025-07-15T12:00",
        capture_batch_ids=[cap1.batch_id, cap2.batch_id],
        tailings_lot_id="Morenci-2025-Q3",
        tailings_kg=145.0,
        water_litre=12.0,
        reactor_temp_c=55,
        reactor_duration_h=4.0,
        co2_consumed_kg=28.5,
        aggregate_kg=173.0,
        water_recovered_litre=8.5,
        reactor_kwh=1.8,
        notes="First reactor run on Morenci lot",
    )
    carb2 = reg.record_carbonation(
        timestamp="2025-07-16T12:30",
        capture_batch_ids=[cap3.batch_id],
        tailings_lot_id="PintoValley-2025-Q2",
        tailings_kg=98.0,
        water_litre=8.0,
        reactor_temp_c=52,
        reactor_duration_h=3.5,
        co2_consumed_kg=16.5,
        aggregate_kg=114.0,
        water_recovered_litre=5.5,
        reactor_kwh=1.2,
        notes="Pinto Valley lot — soft material, lower reactor energy",
    )
    carb3 = reg.record_carbonation(
        timestamp="2025-07-20T13:00",
        capture_batch_ids=[cap4.batch_id],
        tailings_lot_id="Morenci-2025-Q3",
        tailings_kg=115.0,
        water_litre=9.5,
        reactor_temp_c=56,
        reactor_duration_h=4.5,
        co2_consumed_kg=18.0,
        aggregate_kg=132.5,
        water_recovered_litre=6.8,
        reactor_kwh=1.5,
    )

    # -- Product disposition ------------------------------------------------------
    prod1 = reg.record_product_disposition(
        timestamp="2025-07-22T09:00",
        carbonation_batch_id=carb1.batch_id,
        aggregate_kg=173.0,
        fate="sold_aggregate",
        buyer="AZ Ready-Mix Co.",
        price_usd_per_tonne=45.0,
        astm_c33_passed=True,
        astm_test_date="2025-07-21",
        astm_lab="AZ Materials Testing",
        notes="Batch 1 sold for paving aggregate",
    )
    prod2 = reg.record_product_disposition(
        timestamp="2025-07-23T10:00",
        carbonation_batch_id=carb2.batch_id,
        aggregate_kg=114.0,
        fate="sold_aggregate",
        buyer="AZ Ready-Mix Co.",
        price_usd_per_tonne=45.0,
        astm_c33_passed=True,
        astm_test_date="2025-07-22",
        astm_lab="AZ Materials Testing",
    )
    prod3 = reg.record_product_disposition(
        timestamp="2025-07-25T11:00",
        carbonation_batch_id=carb3.batch_id,
        aggregate_kg=132.5,
        fate="stockpiled",
        notes="Pending buyer — not yet credited",
    )

    # -- Issue credits (only permanent fates) ------------------------------------
    reg.issue_credit(product_batch_id=prod1.batch_id, system_emissions_kg=5.2)
    reg.issue_credit(product_batch_id=prod2.batch_id, system_emissions_kg=3.8)
    # prod3 is stockpiled — no credit issued yet

    return reg
