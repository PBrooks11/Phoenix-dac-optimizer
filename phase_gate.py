"""
Phase Gate — Go/No-Go Decision Engine.
Phoenix DAC System · Company Plan Phase 0 → Phase 4

Implements the phase-gate discipline from the company plan:
  Each phase only advances if its defined gates all pass.
  Gates pull live data from the CarbonLedger, MRVRegistry, and LCABoundary.

Phase structure (from the company plan):
  Phase 0  (months 0-6):   Literature review, patent freedom-to-operate, LCA draft,
                            university partner conversations. No company formed yet.
  Phase 1  (months 6-18):  Bench-scale prototype, sorbent qualification, first TCLP,
                            LCA v1. Gate: sorbent capacity ≥ design spec after 500 cycles.
  Phase 2  (months 18-36): Pilot plant (1 t/day), ASTM C33 qualification, verified
                            net-negative ledger. Gate: net-negative ratio ≥ 85 %,
                            ASTM C33 passed, one TCLP-qualified tailings source.
  Phase 3  (months 36-60): Commercial scale (10 t/day), 45Q credit pathway,
                            voluntary market offtake. Gate: cost/net tonne < $400,
                            verified third-party MRV, 45Q registration.
  Phase 4  (60+ months):   Scale-out and replication. Gate: positive unit economics,
                            ≥ 2 qualified tailings sources, water-stress disclosure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any


# ── Gate status ────────────────────────────────────────────────────────────────

class GateStatus:
    PASS    = "pass"
    FAIL    = "fail"
    PENDING = "pending"   # not enough data to evaluate
    WARN    = "warn"      # passes but with caution


@dataclass
class GateResult:
    name: str
    status: str           # GateStatus value
    value: Any            # measured value (number, bool, str)
    threshold: Any        # required threshold
    notes: str = ""

    @property
    def icon(self) -> str:
        return {"pass": "✅", "fail": "❌", "pending": "⏳", "warn": "⚠️"}.get(
            self.status, "?"
        )

    def to_dict(self) -> dict:
        return {
            "gate":      self.name,
            "status":    self.status,
            "icon":      self.icon,
            "value":     self.value,
            "threshold": self.threshold,
            "notes":     self.notes,
        }


@dataclass
class PhaseResult:
    phase: int
    name: str
    gates: List[GateResult] = field(default_factory=list)

    @property
    def go(self) -> bool:
        """Phase is GO only if all gates PASS (warnings allowed)."""
        return all(g.status in (GateStatus.PASS, GateStatus.WARN)
                   for g in self.gates)

    @property
    def failed_gates(self) -> List[GateResult]:
        return [g for g in self.gates if g.status == GateStatus.FAIL]

    @property
    def pending_gates(self) -> List[GateResult]:
        return [g for g in self.gates if g.status == GateStatus.PENDING]

    @property
    def icon(self) -> str:
        if self.go:
            return "🟢"
        if any(g.status == GateStatus.PENDING for g in self.gates):
            return "🟡"
        return "🔴"

    def summary(self) -> str:
        total  = len(self.gates)
        passed = sum(1 for g in self.gates if g.status in (GateStatus.PASS, GateStatus.WARN))
        return (
            f"Phase {self.phase} — {self.name}  "
            f"{self.icon}  "
            f"{passed}/{total} gates passed  "
            f"{'GO' if self.go else 'NO-GO'}"
        )

    def to_dict(self) -> dict:
        return {
            "phase":       self.phase,
            "name":        self.name,
            "go":          self.go,
            "icon":        self.icon,
            "gates":       [g.to_dict() for g in self.gates],
        }


# ══════════════════════════════════════════════════════════════════════════════
# GATE EVALUATORS
# Each evaluator takes relevant data from the live modules and returns GateResult.
# ══════════════════════════════════════════════════════════════════════════════

def _gate(name: str, value: Any, threshold: Any, pass_if, notes: str = "") -> GateResult:
    """Helper: evaluate a gate given a comparison function."""
    try:
        if value is None:
            status = GateStatus.PENDING
        elif pass_if(value, threshold):
            status = GateStatus.PASS
        else:
            status = GateStatus.FAIL
    except Exception as e:
        status = GateStatus.PENDING
        notes = f"Evaluation error: {e}"
    return GateResult(name=name, status=status, value=value, threshold=threshold, notes=notes)


def _warn_gate(name: str, value: Any, threshold: Any, pass_if, warn_if, notes: str = "") -> GateResult:
    """Gate with an intermediate warning band."""
    try:
        if value is None:
            status = GateStatus.PENDING
        elif pass_if(value, threshold):
            status = GateStatus.PASS
        elif warn_if(value, threshold):
            status = GateStatus.WARN
        else:
            status = GateStatus.FAIL
    except Exception as e:
        status = GateStatus.PENDING
        notes = f"Evaluation error: {e}"
    return GateResult(name=name, status=status, value=value, threshold=threshold, notes=notes)


# ══════════════════════════════════════════════════════════════════════════════
# PHASE GATE ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class PhaseGateEngine:
    """
    Evaluates all phase gates against live data.

    Usage:
        engine = PhaseGateEngine()
        engine.set_ledger_summary(ledger.summary())
        engine.set_mrv_summary(registry.summary())
        engine.set_lca_boundary(lca)
        engine.set_sorbent_state(final_sorbent)
        results = engine.evaluate_all()
    """

    def __init__(self) -> None:
        self._ledger_summary: Optional[Dict]  = None
        self._mrv_summary:    Optional[Dict]  = None
        self._lca_boundary:   Any             = None   # LCABoundary instance
        self._sorbent_state:  Any             = None   # SorbentState instance
        # Manual checklist items (set by the user in the dashboard)
        self.manual_checks: Dict[str, bool]   = {}

    def set_ledger_summary(self, summary: Dict) -> None:
        self._ledger_summary = summary

    def set_mrv_summary(self, summary: Dict) -> None:
        self._mrv_summary = summary

    def set_lca_boundary(self, lca) -> None:
        self._lca_boundary = lca

    def set_sorbent_state(self, state) -> None:
        self._sorbent_state = state

    def set_manual_check(self, key: str, value: bool) -> None:
        """Set a gate that can only be confirmed by a human (e.g. patent search done)."""
        self.manual_checks[key] = value

    def _manual(self, key: str, name: str, description: str) -> GateResult:
        val = self.manual_checks.get(key)
        if val is None:
            return GateResult(name=name, status=GateStatus.PENDING,
                              value="not checked", threshold="confirmed",
                              notes=description)
        return GateResult(name=name,
                          status=GateStatus.PASS if val else GateStatus.FAIL,
                          value="confirmed" if val else "not confirmed",
                          threshold="confirmed",
                          notes=description)

    # ── Phase 0: Foundation ─────────────────────────────────────────────────

    def evaluate_phase_0(self) -> PhaseResult:
        """
        Phase 0 gates: literature, patents, LCA draft, partner conversations.
        These are all manual checks — no automated data to pull yet.
        """
        gates = [
            self._manual(
                "p0_literature_review",
                "Literature review complete",
                "Systematic review of DAC sorbent literature (2015–present). "
                "Target: ≥50 papers, identify 3 candidate sorbent formulations.",
            ),
            self._manual(
                "p0_fto_check",
                "Freedom-to-operate (FTO) check",
                "Patent landscape search for hybrid sorbent-solvent polymer contactors. "
                "Must confirm no blocking IP before Phase 1 IP development. "
                "Engage patent attorney if any conflicts found.",
            ),
            self._manual(
                "p0_lca_draft",
                "LCA draft v0 complete",
                "Draft LCA boundary defined (this module). "
                "Key uncertainties documented. "
                "At least one external reviewer (university or consultant).",
            ),
            self._manual(
                "p0_university_partner",
                "University / lab partner identified",
                "At least one academic group willing to collaborate on sorbent testing. "
                "Informal MOU or letter of support.",
            ),
            self._manual(
                "p0_tclp_plan",
                "TCLP test plan drafted",
                "Identified at least 2 candidate Arizona tailings sources. "
                "Contacted mine operators. "
                "Test plan approved by accredited laboratory.",
            ),
        ]
        return PhaseResult(phase=0, name="Foundation & Literature", gates=gates)

    # ── Phase 1: Bench Scale ────────────────────────────────────────────────

    def evaluate_phase_1(self) -> PhaseResult:
        """
        Phase 1 gates: bench prototype, sorbent qualification, first TCLP, LCA v1.
        """
        sorbent = self._sorbent_state

        # Sorbent capacity after 500 cycles
        if sorbent is not None and sorbent.cycle_count >= 500:
            cap_frac = sorbent.capacity_fraction
        else:
            cap_frac = None

        gates = [
            _gate(
                "Sorbent capacity ≥ 85 % after 500 cycles",
                value=round(cap_frac * 100, 1) if cap_frac is not None else None,
                threshold=85.0,
                pass_if=lambda v, t: v >= t,
                notes="Key sorbent life gate. Below 85 % at 500 cycles indicates "
                      "unacceptable degradation — must reformulate before Phase 2.",
            ),
            self._manual(
                "p1_tclp_one_source",
                "≥ 1 TCLP-qualified tailings source",
                "At least one Arizona mine tailings lot has passed TCLP leaching test "
                "at an accredited lab.  No product leaves the site from an unqualified source.",
            ),
            self._manual(
                "p1_lca_v1",
                "LCA v1 complete (ISO 14064-2)",
                "Full LCA with ISO 14064-2 boundary, reviewed by external verifier. "
                "All low-confidence EFs identified and improvement plan noted.",
            ),
            self._manual(
                "p1_carbonation_confirmed",
                "Carbonation reaction confirmed at bench scale",
                "XRD or TGA analysis confirms carbonate mineral formation. "
                "Mass balance within ±5 % for ≥ 5 consecutive batches.",
            ),
            self._manual(
                "p1_company_formed",
                "Company entity formed (if proceeding)",
                "LLC or C-corp formed. IP assigned to entity. "
                "Required before any grant applications or investor conversations.",
            ),
        ]
        return PhaseResult(phase=1, name="Bench Scale & Sorbent Qualification", gates=gates)

    # ── Phase 2: Pilot Plant ────────────────────────────────────────────────

    def evaluate_phase_2(self) -> PhaseResult:
        """
        Phase 2 gates: pilot plant, net-negative verified, ASTM C33, 45Q eligibility.
        """
        ls = self._ledger_summary
        mv = self._mrv_summary

        net_neg_frac  = ls.get("net_negative_fraction", None) if ls else None
        cost_net      = ls.get("cost_per_net_tonne_usd", None) if ls else None
        credits_count = mv.get("verified_credits", None) if mv else None
        lots_qual     = mv.get("tailings_lots_qualified", None) if mv else None

        gates = [
            _warn_gate(
                "Net-negative ratio ≥ 85 %",
                value=round(net_neg_frac * 100, 1) if net_neg_frac is not None else None,
                threshold=85.0,
                pass_if=lambda v, t: v >= t,
                warn_if=lambda v, t: v >= 80.0,
                notes="Core credibility gate. Must be maintained continuously, not just "
                      "at peak — verify on rolling 30-day average, not single-day best.",
            ),
            _gate(
                "Cost/net tonne ≤ $600",
                value=round(cost_net, 0) if cost_net is not None else None,
                threshold=600,
                pass_if=lambda v, t: v <= t,
                notes="Phase 2 cost ceiling. The path to $300 is Phase 3 scale. "
                      "At $600 the system is not commercially viable.",
            ),
            _gate(
                "≥ 1 TCLP-qualified tailings source",
                value=lots_qual,
                threshold=1,
                pass_if=lambda v, t: v >= t,
                notes="Required before any product leaves the site.",
            ),
            _gate(
                "≥ 1 verified removal credit issued",
                value=credits_count,
                threshold=1,
                pass_if=lambda v, t: v >= t,
                notes="Demonstrates the full MRV chain works end-to-end.",
            ),
            self._manual(
                "p2_astm_c33",
                "ASTM C33 aggregate spec passed",
                "Aggregate product meets ASTM C33 gradation and cleanliness requirements "
                "for use as construction material.  Tested by accredited lab.",
            ),
            self._manual(
                "p2_45q_eligible",
                "45Q tax credit pathway confirmed",
                "IRS Form 8933 eligibility confirmed with tax counsel. "
                "EOR exclusion confirmed (no EOR use in this project).",
            ),
            self._manual(
                "p2_water_disclosure",
                "Water-stress disclosure published",
                "Annual water consumption and recovery rate published in public MRV report. "
                "Phoenix is 'Extremely High' stress per WRI Aqueduct — disclosure required.",
            ),
        ]
        return PhaseResult(phase=2, name="Pilot Plant & Verified Credits", gates=gates)

    # ── Phase 3: Commercial Scale ───────────────────────────────────────────

    def evaluate_phase_3(self) -> PhaseResult:
        """Phase 3 gates: commercial scale, third-party MRV, voluntary market."""
        ls = self._ledger_summary
        mv = self._mrv_summary

        cost_net  = ls.get("cost_per_net_tonne_usd", None) if ls else None
        lots_qual = mv.get("tailings_lots_qualified", None) if mv else None

        gates = [
            _gate(
                "Cost/net tonne ≤ $400",
                value=round(cost_net, 0) if cost_net is not None else None,
                threshold=400,
                pass_if=lambda v, t: v <= t,
                notes="Commercial viability threshold at current voluntary market prices ($250–400/t).",
            ),
            _gate(
                "≥ 2 TCLP-qualified tailings sources",
                value=lots_qual,
                threshold=2,
                pass_if=lambda v, t: v >= t,
                notes="Supply chain resilience — not dependent on a single mine.",
            ),
            self._manual(
                "p3_third_party_mrv",
                "Third-party MRV verification completed",
                "Independent auditor (e.g. DNV, SCS Global) has reviewed and signed off "
                "on the MRV registry for ≥ one full year of operation.",
            ),
            self._manual(
                "p3_offtake",
                "Offtake agreement signed",
                "At least one multi-year aggregate offtake agreement with a construction "
                "materials buyer.  Revenue covers ≥ 50 % of operating costs.",
            ),
            self._manual(
                "p3_solar_crusher",
                "Solar crusher contract at ≥ 1 mine",
                "Signed contract to convert at least one mine's crusher to solar-electric. "
                "This reduces the largest single emission source (tailings grinding).",
            ),
        ]
        return PhaseResult(phase=3, name="Commercial Scale & Third-Party Verification", gates=gates)

    # ── Phase 4: Scale-Out ──────────────────────────────────────────────────

    def evaluate_phase_4(self) -> PhaseResult:
        """Phase 4 gates: positive unit economics, scale-out readiness."""
        ls  = self._ledger_summary
        mv  = self._mrv_summary
        lca = self._lca_boundary

        cost_net  = ls.get("cost_per_net_tonne_usd", None) if ls else None
        lots_qual = mv.get("tailings_lots_qualified", None) if mv else None
        net_neg   = ls.get("net_negative_fraction", None) if ls else None

        grinder = "solar" if (lca and lca.grinder_type == "solar") else "diesel"

        gates = [
            _gate(
                "Cost/net tonne ≤ $300",
                value=round(cost_net, 0) if cost_net is not None else None,
                threshold=300,
                pass_if=lambda v, t: v <= t,
                notes="Long-run commercial target for scale-out economics.",
            ),
            _gate(
                "≥ 2 TCLP-qualified tailings sources",
                value=lots_qual,
                threshold=2,
                pass_if=lambda v, t: v >= t,
            ),
            _warn_gate(
                "Net-negative ratio ≥ 88 %",
                value=round(net_neg * 100, 1) if net_neg is not None else None,
                threshold=88.0,
                pass_if=lambda v, t: v >= t,
                warn_if=lambda v, t: v >= 85.0,
                notes="Higher bar for scale-out — improved accounting as we reduce grinding emissions.",
            ),
            _gate(
                "≥ 1 solar crusher contract active",
                value=grinder,
                threshold="solar",
                pass_if=lambda v, t: v == t,
                notes="Solar grinding at mine site is the single biggest lever to improve net-negative ratio.",
            ),
            self._manual(
                "p4_replication_design",
                "Replication-ready plant design complete",
                "Modular plant design documented. "
                "BOM and construction costs validated against Phase 3 actuals.",
            ),
            self._manual(
                "p4_ibm_integration",
                "Automated MRV integration live",
                "IBM App Connect / watsonx.ai integration live for real-time sensor data "
                "→ ledger updates → credit issuance without manual data entry.",
            ),
        ]
        return PhaseResult(phase=4, name="Scale-Out & Automation", gates=gates)

    # ── Evaluate all phases ─────────────────────────────────────────────────

    def evaluate_all(self) -> List[PhaseResult]:
        return [
            self.evaluate_phase_0(),
            self.evaluate_phase_1(),
            self.evaluate_phase_2(),
            self.evaluate_phase_3(),
            self.evaluate_phase_4(),
        ]

    def current_phase(self) -> int:
        """
        Return the highest phase that is GO (all gates pass).
        This is the current phase the project is IN — the next phase is what to unlock.
        """
        results = self.evaluate_all()
        for result in reversed(results):
            if result.go:
                return result.phase
        return 0

    def next_actions(self) -> List[str]:
        """
        Return a prioritised list of the most important things to do right now,
        based on which gates are failing or pending.
        """
        results = self.evaluate_all()
        actions = []
        for phase_result in results:
            for gate in phase_result.gates:
                if gate.status in (GateStatus.FAIL, GateStatus.PENDING):
                    actions.append(
                        f"[Phase {phase_result.phase}] {gate.icon} {gate.name}  "
                        f"({gate.notes[:80]}{'…' if len(gate.notes) > 80 else ''})"
                    )
        return actions


# ── Demo factory ───────────────────────────────────────────────────────────────

def build_demo_engine(ledger_summary: dict, mrv_summary: dict, lca, sorbent_state) -> PhaseGateEngine:
    """
    Build a PhaseGateEngine pre-loaded with demo data.
    Reflects Phase 0 reality: most manual checks are incomplete.
    """
    engine = PhaseGateEngine()
    engine.set_ledger_summary(ledger_summary)
    engine.set_mrv_summary(mrv_summary)
    engine.set_lca_boundary(lca)
    engine.set_sorbent_state(sorbent_state)

    # Phase 0: partially done (literature started, no FTO yet, LCA draft in progress)
    engine.set_manual_check("p0_literature_review", True)
    engine.set_manual_check("p0_fto_check", False)         # not done yet
    engine.set_manual_check("p0_lca_draft", True)          # this codebase IS the draft LCA
    engine.set_manual_check("p0_university_partner", False)
    engine.set_manual_check("p0_tclp_plan", False)

    # Phase 1: not started yet (demo only)
    # (all defaults to pending / False)

    return engine
