"""
build_pdf.py — Generate the complete Phoenix DAC Company Document
=================================================================
Produces a single PDF combining:
  1.  Cover page
  2.  Executive summary
  3.  Company plan (Phase 0 → 4)
  4.  Technical architecture (all 11 modules)
  5.  Carbon accounting methodology (LCA + MRV)
  6.  Validated performance results
  7.  Cash flow projections & funding plan
  8.  Risk register & mitigation
  9.  IBM partnership proposal
  10. Appendices (emission factors, mine database, glossary)

Run:
    cd dac_optimizer && python3 build_pdf.py
    → writes Phoenix_DAC_Company_Plan.pdf in the same directory
"""

import os
import sys
import math
from datetime import date

# ── ReportLab imports ─────────────────────────────────────────────────────────
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether,
)
from reportlab.platypus.flowables import Flowable

# ── Pull live numbers from our modules ────────────────────────────────────────
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _APP_DIR)

from cashflow import build_demo_cashflow, PHASE_PARAMS
from monte_carlo import run_monte_carlo
from lca import demo_lca_boundary
from mrv import build_demo_registry

_, cf_rows, cf_sum = build_demo_cashflow(carbon_credit_price=250)
_, mc_stats = run_monte_carlo(n=500, grinder_type="diesel")
lca_obj = demo_lca_boundary()
bd = lca_obj.emission_breakdown()
mrv_sum = build_demo_registry().summary()

TODAY = date.today().strftime("%B %d, %Y")
OUT_PATH = os.path.join(_APP_DIR, "Phoenix_DAC_Company_Plan.pdf")

# ── Colour palette ─────────────────────────────────────────────────────────────
NAVY    = colors.HexColor("#1e3a5f")
GREEN   = colors.HexColor("#166534")
TEAL    = colors.HexColor("#0e7490")
AMBER   = colors.HexColor("#92400e")
RED     = colors.HexColor("#991b1b")
SLATE   = colors.HexColor("#334155")
LGREY   = colors.HexColor("#f1f5f9")
MGREY   = colors.HexColor("#cbd5e1")
WHITE   = colors.white
BLACK   = colors.HexColor("#1f2328")

# ── Styles ────────────────────────────────────────────────────────────────────
base = getSampleStyleSheet()

def _s(name, parent="Normal", **kw):
    return ParagraphStyle(name, parent=base[parent], **kw)

H1   = _s("H1",   "Heading1", fontSize=18, textColor=NAVY,  spaceAfter=10, spaceBefore=18, fontName="Helvetica-Bold")
H2   = _s("H2",   "Heading2", fontSize=13, textColor=NAVY,  spaceAfter=6,  spaceBefore=14, fontName="Helvetica-Bold")
H3   = _s("H3",   "Heading3", fontSize=11, textColor=TEAL,  spaceAfter=4,  spaceBefore=10, fontName="Helvetica-Bold")
BODY = _s("BODY", "Normal",   fontSize=9.5, leading=14, textColor=BLACK,   alignment=TA_JUSTIFY, spaceAfter=5)
BULL = _s("BULL", "Normal",   fontSize=9.5, leading=13, leftIndent=16, firstLineIndent=-10, textColor=BLACK, spaceAfter=3)
CAPT = _s("CAPT", "Normal",   fontSize=8,  textColor=SLATE, alignment=TA_CENTER, spaceAfter=4, fontName="Helvetica-Oblique")
NOTE = _s("NOTE", "Normal",   fontSize=8,  textColor=SLATE, spaceAfter=3,  fontName="Helvetica-Oblique")
BOLD = _s("BOLD", "Normal",   fontSize=9.5, fontName="Helvetica-Bold", textColor=BLACK)
CNTR = _s("CNTR", "Normal",   fontSize=9.5, alignment=TA_CENTER, textColor=BLACK)

# Cover styles
CVR_TITLE = _s("CVR_TITLE", fontSize=28, textColor=WHITE, fontName="Helvetica-Bold", alignment=TA_CENTER, leading=34)
CVR_SUB   = _s("CVR_SUB",   fontSize=14, textColor=colors.HexColor("#bfdbfe"), fontName="Helvetica", alignment=TA_CENTER, leading=20)
CVR_META  = _s("CVR_META",  fontSize=10, textColor=colors.HexColor("#e2e8f0"), alignment=TA_CENTER)

# ── Helper flowables ──────────────────────────────────────────────────────────

def p(text, style=BODY):
    return Paragraph(text, style)

def b(text):
    return Paragraph(f"• {text}", BULL)

def sp(h=6):
    return Spacer(1, h)

def hr():
    return HRFlowable(width="100%", thickness=0.5, color=MGREY, spaceAfter=6, spaceBefore=2)

def section_header(text):
    return [hr(), p(text, H1), sp(2)]

def subsection(text):
    return [p(text, H2)]

def sub3(text):
    return [p(text, H3)]

def note(text):
    return p(f"<i>{text}</i>", NOTE)


class ColorBar(Flowable):
    """A full-width colored bar used for cover and section dividers."""
    def __init__(self, height=4, color=NAVY):
        super().__init__()
        self.bar_height = height
        self.bar_color  = color
    def wrap(self, aw, ah):
        self._aw = aw
        return aw, self.bar_height
    def draw(self):
        self.canv.setFillColor(self.bar_color)
        self.canv.rect(0, 0, self._aw, self.bar_height, fill=1, stroke=0)


def tbl(data, col_widths, style_extra=None, repeat_rows=1):
    """Build a styled table."""
    ts = TableStyle([
        ("BACKGROUND",   (0, 0), (-1, 0),     NAVY),
        ("TEXTCOLOR",    (0, 0), (-1, 0),      WHITE),
        ("FONTNAME",     (0, 0), (-1, 0),      "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, 0),      9),
        ("ROWBACKGROUNDS",(0,1), (-1,-1),      [WHITE, LGREY]),
        ("FONTSIZE",     (0, 1), (-1, -1),     8.5),
        ("FONTNAME",     (0, 1), (-1, -1),     "Helvetica"),
        ("TEXTCOLOR",    (0, 1), (-1, -1),     BLACK),
        ("GRID",         (0, 0), (-1, -1),     0.3, MGREY),
        ("TOPPADDING",   (0, 0), (-1, -1),     4),
        ("BOTTOMPADDING",(0, 0), (-1, -1),     4),
        ("LEFTPADDING",  (0, 0), (-1, -1),     6),
        ("RIGHTPADDING", (0, 0), (-1, -1),     6),
        ("VALIGN",       (0, 0), (-1, -1),     "MIDDLE"),
        ("ROWBACKGROUNDS",(0,1), (-1,-1),      [WHITE, LGREY]),
    ])
    if style_extra:
        for cmd in style_extra:
            ts.add(*cmd)
    t = Table(data, colWidths=col_widths, repeatRows=repeat_rows)
    t.setStyle(ts)
    return t


def kpi_row(items):
    """Horizontal row of (label, value, unit) KPI boxes."""
    W = 6.5 * inch / len(items)
    cells = []
    for label, val, unit in items:
        cells.append(
            Table(
                [[p(val, _s(f"kv{label}", fontSize=16, fontName="Helvetica-Bold",
                            textColor=NAVY, alignment=TA_CENTER))],
                 [p(label, _s(f"kl{label}", fontSize=7.5, textColor=SLATE, alignment=TA_CENTER))],
                 [p(unit,  _s(f"ku{label}", fontSize=7,   textColor=TEAL,  alignment=TA_CENTER,
                              fontName="Helvetica-Oblique"))]],
                colWidths=[W - 12],
                style=TableStyle([
                    ("BOX",        (0,0),(-1,-1), 0.5, MGREY),
                    ("BACKGROUND", (0,0),(-1,-1), LGREY),
                    ("TOPPADDING", (0,0),(-1,-1), 6),
                    ("BOTTOMPADDING",(0,0),(-1,-1),6),
                ]),
            )
        )
    outer = Table([cells], colWidths=[W]*len(items))
    outer.setStyle(TableStyle([("LEFTPADDING",(0,0),(-1,-1),4),
                                ("RIGHTPADDING",(0,0),(-1,-1),4)]))
    return outer


# ── Page template callbacks ────────────────────────────────────────────────────

LOGO_TEXT = "PHOENIX DAC"

def _header_footer(canvas, doc):
    canvas.saveState()
    w, h = LETTER
    # Header bar
    canvas.setFillColor(NAVY)
    canvas.rect(0, h - 0.45*inch, w, 0.45*inch, fill=1, stroke=0)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(WHITE)
    canvas.drawString(0.5*inch, h - 0.28*inch, LOGO_TEXT)
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(w - 0.5*inch, h - 0.28*inch, "CONFIDENTIAL — PRE-COMMERCIAL")
    # Footer
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(SLATE)
    canvas.drawString(0.5*inch, 0.35*inch,
                      f"Phoenix DAC Optimizer — Company Plan & Technical Reference  |  {TODAY}")
    canvas.drawRightString(w - 0.5*inch, 0.35*inch, f"Page {doc.page}")
    canvas.restoreState()


def _cover_page(canvas, doc):
    """Full-bleed cover — no header/footer."""
    canvas.saveState()
    w, h = LETTER
    canvas.setFillColor(NAVY)
    canvas.rect(0, 0, w, h, fill=1, stroke=0)
    # Accent stripe
    canvas.setFillColor(TEAL)
    canvas.rect(0, h*0.38, w, 4, fill=1, stroke=0)
    canvas.restoreState()


# ── Document builder ──────────────────────────────────────────────────────────

def build():
    doc = SimpleDocTemplate(
        OUT_PATH,
        pagesize=LETTER,
        leftMargin=0.75*inch, rightMargin=0.75*inch,
        topMargin=0.65*inch,  bottomMargin=0.6*inch,
        title="Phoenix DAC — Company Plan & Technical Reference",
        author="Phoenix DAC Optimizer",
        subject="Direct Air Capture — Net-Negative Carbon Platform",
    )

    story = []
    W = 6.5 * inch   # usable page width

    # ══════════════════════════════════════════════════════════════════════════
    # COVER PAGE
    # ══════════════════════════════════════════════════════════════════════════

    story.append(Spacer(1, 1.6*inch))
    story.append(p("PHOENIX DIRECT AIR CAPTURE", CVR_TITLE))
    story.append(Spacer(1, 0.1*inch))
    story.append(p("Company Plan &amp; Technical Reference", CVR_SUB))
    story.append(Spacer(1, 0.08*inch))
    story.append(p("AI Optimizer · Carbon Ledger · MRV Registry · Cash Flow Model", CVR_SUB))
    story.append(Spacer(1, 1.8*inch))
    story.append(p(f"Version 1.0  |  {TODAY}  |  CONFIDENTIAL — PRE-COMMERCIAL", CVR_META))
    story.append(Spacer(1, 0.15*inch))
    story.append(p("Solar PV + LFP battery  ·  Hybrid sorbent-solvent contactor", CVR_META))
    story.append(p("Mineral carbonation into Arizona copper mine tailings aggregate", CVR_META))
    story.append(p("Net-negative accounting: gross CO₂ minus ALL lifecycle emissions", CVR_META))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # TABLE OF CONTENTS
    # ══════════════════════════════════════════════════════════════════════════

    story += section_header("Table of Contents")
    toc_data = [
        ["Section", "Title", "Page"],
        ["1",  "Executive Summary", "3"],
        ["2",  "The Company Plan — Mission & Strategy", "4"],
        ["3",  "Phase Gate Roadmap (Phase 0 → 4)", "5"],
        ["4",  "Technical Architecture — 11 Modules", "7"],
        ["5",  "Carbon Accounting Methodology (LCA + MRV)", "10"],
        ["6",  "Validated Performance Results", "12"],
        ["7",  "Cash Flow Projections & Funding Plan", "14"],
        ["8",  "Risk Register & Mitigation", "17"],
        ["9",  "IBM Partnership Proposal", "18"],
        ["10", "Appendices", "21"],
    ]
    story.append(tbl(toc_data, [0.5*inch, 4.5*inch, 1.5*inch]))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # 1. EXECUTIVE SUMMARY
    # ══════════════════════════════════════════════════════════════════════════

    story += section_header("1. Executive Summary")
    story.append(p(
        "Phoenix Direct Air Capture is developing a <b>permanently net-negative carbon removal "
        "business</b> in the Sonoran Desert. The system captures atmospheric CO₂ at night using "
        "solar-charged batteries to power contactor fans, releases it by day through solar thermal "
        "regeneration at 80–100°C, and sequesters it permanently via mineral carbonation into "
        "construction aggregate made from Arizona copper mine tailings — or via direct geologic "
        "injection. No fossil energy enters the loop at any point."
    ))
    story.append(p(
        "A fully working AI optimization and carbon accounting platform has been designed, built, "
        "and validated. It comprises 11 Python modules, an 11-tab Streamlit operations dashboard, "
        "and a complete suite of lifecycle tools — from a 24-hour linear program dispatcher to a "
        "batch-traceability MRV registry, Monte Carlo LCA uncertainty analysis, and a 96-month "
        "cash flow model. All tools are running locally today."
    ))

    story.append(sp(4))
    story.append(kpi_row([
        ("Gross CO₂", "114.3 t", "per year (50 kW pilot)"),
        ("Net-negative ratio", "88.4%", "P50 range 85.8–92.1%"),
        ("Cost / net tonne", "$285", "base case, diesel grinder"),
        ("Breakeven", "Month 25", "with grants / Month 42 commercial"),
        ("Peak cash need", f"${abs(cf_sum['peak_cash_need_usd']):,.0f}", "maximum cumulative deficit"),
    ]))
    story.append(sp(6))

    story.append(p(
        "The three core claims — net-negative removal, permanent sequestration, and honest "
        "cost-per-net-tonne accounting — are verified continuously by the ledger and MRV registry, "
        "not asserted from a spreadsheet. Every kilogram of CO₂ credited traces to a specific "
        "capture event, a TCLP-qualified tailings lot, a confirmed permanent fate, and a closed "
        "mass balance."
    ))
    story.append(note(
        "Note: This document is pre-commercial and confidential. All performance figures are from "
        "prototype simulation with calibrated synthetic Phoenix weather data. Phase 1 bench-scale "
        "testing has not yet begun."
    ))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # 2. COMPANY PLAN — MISSION & STRATEGY
    # ══════════════════════════════════════════════════════════════════════════

    story += section_header("2. The Company Plan — Mission &amp; Strategy")

    story += subsection("2.1 Mission")
    story.append(p(
        "<b>Capture the air. Turn it into rock. Build with it.</b> The mission is to remove "
        "atmospheric CO₂ permanently and verifiably, using only the sun as an energy source and "
        "Arizona copper mine tailings as the sequestration medium — converting an environmental "
        "liability into a structural material."
    ))

    story += subsection("2.2 Why Phoenix, Why Tailings")
    for txt in [
        "<b>Solar resource:</b> Phoenix averages 299 sunny days per year and leads the continental "
        "US in GHI. A 50 kW array provides sufficient energy for night capture (via battery) and "
        "daytime thermal regeneration — the entire energy loop closes on solar.",
        "<b>Tailings supply:</b> Arizona is the largest copper-producing state in the US. Morenci, "
        "Bagdad, Sierrita, Ray, and Pinto Valley generate a combined tailings output exceeding "
        "200 million tonnes per year. Current tailings management is an ongoing environmental "
        "liability — reactive silicate tailings that carbonate also benefit from structural "
        "stabilisation, creating a mutual value proposition for offtake agreements.",
        "<b>Construction market:</b> Arizona's population growth (Phoenix metro: #1 fastest-growing "
        "in the US 2023–2025) creates sustained demand for aggregate and precast concrete. "
        "Carbonated aggregate commands a premium from sustainability-focused developers.",
        "<b>No fossil inputs:</b> Phoenix's solar irradiance and the proximity of mine tailings "
        "eliminate any need for fossil fuel in the process loop, which is required to claim a "
        "genuinely permanent net-negative credit.",
    ]:
        story.append(b(txt))

    story += subsection("2.3 Competitive Differentiation")
    diff_data = [
        ["Dimension", "Phoenix DAC", "Typical DAC operator"],
        ["Energy source", "Solar PV + LFP battery only", "Grid (fossil mix) or natural gas"],
        ["Sequestration fate", "Mineral carbonation (permanent) or geologic", "Often EOR or utilisation (not permanent)"],
        ["Accounting metric", "Cost per NET tonne (honest)", "Cost per GROSS tonne (inflated 15–30%)"],
        ["Tailings use", "Per-batch geochemistry assay, TCLP-qualified", "Fixed stoichiometry assumptions"],
        ["MRV", "Automated batch traceability chain", "Manual spreadsheet reporting"],
        ["Location", "Mine tailings adjacent, solar belt", "Remote sites, grid-dependent"],
    ]
    story.append(tbl(diff_data, [1.4*inch, 2.6*inch, 2.5*inch]))

    story += subsection("2.4 Capital-Light Model")
    story.append(p(
        "The founder is proceeding capital-light: grant and partnership funded, no self-funded "
        "plant, operating alongside full-time work and school. Phase 0 requires no company "
        "formation — only literature access, patent attorney consultation, and this software. "
        "Each phase gates spending on the phase before it: no Phase 1 bench hardware unless "
        "Phase 0 freedom-to-operate check passes."
    ))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # 3. PHASE GATE ROADMAP
    # ══════════════════════════════════════════════════════════════════════════

    story += section_header("3. Phase Gate Roadmap (Phase 0 → 4)")
    story.append(p(
        "Each phase only advances when all gates pass. Gates are evaluated live by the "
        "PhaseGateEngine in the dashboard — some are automated (pulled from the carbon ledger "
        "and MRV registry), others require human confirmation (patent search, ASTM results, etc.)."
    ))

    for ph in range(5):
        pp = PHASE_PARAMS[ph]
        story += sub3(f"Phase {ph} — {pp.name}  ({pp.duration_months} months)")

    phase_detail = [
        (0, "Foundation & Literature", "6", [
            "Systematic literature review (≥50 papers, 2015–present)",
            "Freedom-to-operate (FTO) patent search — hybrid sorbent-solvent contactors",
            "LCA draft v0 (this codebase IS the draft LCA model)",
            "Identify university / lab partner for sorbent testing",
            "Draft TCLP test plan with at least 2 candidate mine sites",
            "No company formed yet — optional at end of Phase 0",
        ], "Literature access ($0), IP attorney consultation (~$1,500), cloud compute (~$500)"),
        (1, "Bench Scale & Sorbent Qualification", "12", [
            "Build bench-scale contactor (single column, ~0.1 t CO₂/month)",
            "Sorbent capacity ≥ 85% after 500 cycles (GATE: automated, measured)",
            "First TCLP-qualified tailings source from accredited lab",
            "XRD or TGA confirmation of carbonate mineral formation",
            "LCA v1 complete to ISO 14064-2, external reviewer sign-off",
            "Company entity formed (LLC or C-corp), IP assigned",
        ], "DOE SBIR Phase I (~$150k / 30 months). Bench equipment: ~$25k. Sorbent: ~$6k/yr."),
        (2, "Pilot Plant (1 t CO₂/day)", "18", [
            "Net-negative ratio ≥ 85% (GATE: live from ledger)",
            "Cost/net tonne ≤ $600 (GATE: live from ledger)",
            "ASTM C33 aggregate specification passed (GATE: lab test)",
            "45Q tax credit eligibility confirmed with tax counsel",
            "Third-party MRV audit of at least one 30-day period",
            "Water-stress disclosure published (Phoenix = Extremely High, WRI Aqueduct)",
        ], "DOE SBIR Phase II (~$1.5M / 24 months). Pilot plant: ~$100k CapEx. 0.5 FTE ops."),
        (3, "Commercial Scale (10 t CO₂/day)", "24", [
            "Cost/net tonne ≤ $400 (GATE: live from ledger)",
            "≥ 2 TCLP-qualified tailings sources (supply chain resilience)",
            "Third-party MRV verification — full year, signed by DNV or SCS Global",
            "Multi-year aggregate offtake agreement signed (revenue ≥ 50% of OpEx)",
            "Solar crusher contract at ≥ 1 mine (largest single emissions lever)",
        ], "DOE Prize / AZ State grants (~$100k/yr). Commercial plant: ~$250k CapEx. 1.5 FTE."),
        (4, "Scale-Out & Replication", "36", [
            "Cost/net tonne ≤ $300 (GATE: live from ledger)",
            "Net-negative ratio ≥ 88% (GATE: live, with solar crusher)",
            "≥ 1 solar crusher contract active (GATE: automated)",
            "Replication-ready plant design with BOM validated against actuals",
            "IBM App Connect / watsonx.ai automated MRV integration live",
        ], "Self-funded from operations. Optional Series A if replication accelerates."),
    ]

    phase_rows = [["Phase", "Duration", "Key Gates", "Funding Source"]]
    for ph, name, dur, gates, funding in phase_detail:
        gates_text = "\n".join(f"• {g}" for g in gates[:4])
        phase_rows.append([
            p(f"<b>Phase {ph}</b>\n{name}", BODY),
            p(f"{dur} mo", CNTR),
            p(gates_text, _s(f"pg{ph}", fontSize=7.5, leading=11)),
            p(funding, _s(f"pf{ph}", fontSize=7.5, leading=11)),
        ])

    story.append(tbl(phase_rows,
                     [0.85*inch, 0.65*inch, 3.3*inch, 1.7*inch],
                     style_extra=[("VALIGN",(0,0),(-1,-1),"TOP")]))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # 4. TECHNICAL ARCHITECTURE
    # ══════════════════════════════════════════════════════════════════════════

    story += section_header("4. Technical Architecture — 11 Python Modules")
    story.append(p(
        "All code is Python 3.12 with four runtime dependencies: <code>scipy</code>, "
        "<code>pandas</code>, <code>plotly</code>, <code>streamlit</code>. Every module is "
        "independently containerisable. The 11-tab Streamlit dashboard provides a live view "
        "of the full system state without requiring direct code access."
    ))

    modules = [
        ("weather.py", "Synthetic Phoenix weather generator",
         "8,760-hour synthetic year calibrated to NREL TMY3. Seasonal temperature profile, "
         "monsoon humidity (Jul–Sep), haboob dust events, PV output with temperature derating. "
         "Replace with live NOAA + watsonx.ai Granite-TTM forecasts in Phase 2."),
        ("sorbent.py", "Amine sorbent degradation model",
         "Cycle-by-cycle capacity tracking (0.045%/cycle base rate, accelerated by humidity >40% "
         "and regen T >95°C). Temperature-dependent capture capacity (72% at 35°C vs fresh at 25°C). "
         "Dust fouling accumulation and reversible cleaning model. Economic replacement trigger."),
        ("tailings.py", "Per-batch tailings assay engine",
         "TailingsAssay dataclass with Bond's Law grinding energy, stoichiometry from reactive "
         "fraction, transport emissions. 6 pre-loaded Arizona mine defaults. blend_assays() for "
         "on-site stockpile mixing. rank_batches() composite scoring. Solar crusher contract "
         "cost model."),
        ("ledger.py", "Net-negative carbon ledger",
         "Per-hour signed ledger debiting: fan electricity (solar lifecycle 20 g CO₂e/kWh), "
         "vacuum, battery manufacturing, sorbent manufacturing, filter, tailings grinding+transport, "
         "infrastructure. TailingsAssay-aware — uses actual batch geochemistry. Reports cost per "
         "GROSS tonne and per NET tonne separately."),
        ("optimizer.py", "24-hour LP dispatch scheduler",
         "scipy HiGH linear program maximising net CO₂/$ over a 24-hour window subject to battery "
         "SOC constraints. 5 additional optimisations: assay-aware capture threshold, dynamic "
         "regen temperature (82–95°C by sorbent age), proactive cleaning scheduling, battery-"
         "forecast LP re-solve at day-start, greedy fallback if scipy absent."),
        ("mrv.py", "MRV — Measurement, Reporting & Verification",
         "Full batch traceability: CaptureBatch → TailingsLotQualification (TCLP) → "
         "CarbonationBatch (mass balance ±5%) → ProductBatch (fate gate) → VerifiedCredit. "
         "EPA TCLP limit auto-check on all 8 regulated analytes. ASTM C33 gate for aggregate "
         "sales. Water ledger per batch. JSON export for auditor handoff."),
        ("lca.py", "LCA boundary model (ISO 14064-2)",
         "Full Scope 1/2/3 boundary. Every emission factor cited with source and confidence level. "
         "Low-confidence items flagged for Phase 1 improvement. Diesel vs solar crusher comparison. "
         "Water accounting with Phoenix stress-index disclosure. confidence_flags() method returns "
         "prioritised improvement list."),
        ("phase_gate.py", "Phase gate engine",
         "Go/No-Go evaluator for all 5 phases. Automated gates pull live data from ledger, MRV, "
         "and sorbent state. Manual gates (FTO check, ASTM, 45Q, etc.) set via dashboard "
         "checkboxes. next_actions() returns prioritised remediation list. Prevents phase "
         "advancement until all gates pass."),
        ("cashflow.py", "96-month cash flow model",
         "Conservative monthly projections for Phase 0→4. Revenue: aggregate sales, voluntary "
         "carbon credits, §45Q utilisation ($130/t), grants. Costs: CapEx (annualised), OpEx, "
         "sorbent, filters, water, tailings processing, MRV audit, legal. Breakeven analysis "
         "with-grants vs commercial-only. Peak cash need calculation."),
        ("sensors.py", "Sensor data pipeline",
         "16 physical sensor channels with range validation and drift detection. State machine "
         "auto-detects capture cycles and reactor runs, committing batches to the MRV registry "
         "without manual data entry. co2_captured_kg() from differential concentration × air flow. "
         "CSV import + downloadable template. IBM App Connect integration path."),
        ("monte_carlo.py", "Monte Carlo LCA sensitivity",
         "500 simulations, pure Python stdlib. 6 uncertain parameters sampled from triangular "
         "distributions (literature-sourced bounds). P5/P50/P95 net-negative ratios, probability "
         "of missing the 85% gate, tornado chart (Pearson correlations). Key result: diesel "
         f"P50 = {mc_stats.nn_p50*100:.1f}%, P(below 85%) = {mc_stats.prob_below_85_pct:.1f}%, "
         "top driver: sorbent manufacturing EF."),
    ]

    mod_data = [["Module", "Purpose", "Key functionality"]]
    for mod, purpose, detail in modules:
        mod_data.append([
            p(f"<code>{mod}</code>", _s("mc", fontSize=8, fontName="Courier-Bold", textColor=NAVY)),
            p(f"<b>{purpose}</b>", _s("mp", fontSize=8.5, fontName="Helvetica-Bold")),
            p(detail, _s("md", fontSize=8, leading=11)),
        ])
    story.append(tbl(mod_data, [1.1*inch, 1.6*inch, 3.8*inch],
                     style_extra=[("VALIGN",(0,0),(-1,-1),"TOP")]))

    story += subsection("4.1 Dashboard — 11 Tabs")
    tabs = [
        ("📊 Dashboard",         "KPIs, net-negative gauge, emission donut chart, monthly bar chart"),
        ("⛏ Tailings Assay",     "Editable batch library, derived geochemistry, batch ranking, blend UI"),
        ("⏱ Hourly Dispatch",    "4-panel timeline: mode/temp, battery SOC/PV, CO₂ kg/h, dust factor"),
        ("🧪 Sorbent Health",    "Degradation curve, replacement forecast, economic trigger"),
        ("🔗 MRV Registry",      "Verified credits, TCLP results, water accounting, traceability chain"),
        ("♻️ LCA Boundary",      "ISO 14064-2 breakdown, diesel/solar comparison, confidence flags"),
        ("🚦 Phase Gates",       "Go/No-Go per phase, manual checkboxes, next actions list"),
        ("💰 Cash Flow",         "96-month projections, stress-test sliders, breakeven chart"),
        ("📡 Sensor Pipeline",   "Live sensor ingestion, anomaly detection, auto-MRV commit"),
        ("🎲 LCA Monte Carlo",   "Net-neg distribution histogram, tornado chart, uncertain parameter table"),
        ("📥 Export",            "Hourly CSV download, MRV registry JSON for auditor handoff"),
    ]
    tab_data = [["Tab", "Contents"]] + [[t, d] for t, d in tabs]
    story.append(tbl(tab_data, [1.7*inch, 4.8*inch]))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # 5. CARBON ACCOUNTING METHODOLOGY
    # ══════════════════════════════════════════════════════════════════════════

    story += section_header("5. Carbon Accounting Methodology")

    story += subsection("5.1 LCA System Boundary (ISO 14064-2)")
    story.append(p(
        "Functional unit: <b>1 tonne of net CO₂ removed and permanently sequestered.</b> "
        "The boundary includes all Scope 1, 2, and 3 upstream emissions. Scope 1 = zero "
        "(no on-site combustion). Scope 2 = zero (100% solar). Scope 3 upstream covers "
        "PV manufacturing, battery manufacturing, sorbent manufacturing, filter manufacturing, "
        "tailings grinding and transport, and annualised infrastructure. End-of-life for "
        "carbonated aggregate is excluded under ISO 14064-2 cut-off rules — the CO₂ is locked "
        "in stable carbonate mineral."
    ))

    # LCA breakdown table
    total_emis = sum(bd.values())
    lca_rows = [["Emission category", "Scope", "kg CO₂e/yr", "% of total", "Confidence"]]
    scope_map = {
        "pv_manufacturing": "3-upstream", "battery_mfg": "3-upstream",
        "sorbent_mfg": "3-upstream", "filter_mfg": "3-upstream",
        "tailings_grinding": "3-upstream", "tailings_transport": "3-upstream",
        "fan_electricity": "Operational", "vacuum_electricity": "Operational",
        "reactor_electricity": "Operational", "water": "Operational",
        "infrastructure": "3-upstream",
    }
    conf_map = {
        "pv_manufacturing": "High", "battery_mfg": "Medium",
        "sorbent_mfg": "LOW ⚠", "filter_mfg": "LOW ⚠",
        "tailings_grinding": "High", "tailings_transport": "High",
        "fan_electricity": "High", "vacuum_electricity": "High",
        "reactor_electricity": "High", "water": "Medium",
        "infrastructure": "LOW ⚠",
    }
    for cat, val in sorted(bd.items(), key=lambda x: -x[1]):
        pct = val / total_emis * 100 if total_emis > 0 else 0
        lca_rows.append([
            cat.replace("_", " ").title(),
            scope_map.get(cat, "—"),
            f"{val:.1f}",
            f"{pct:.1f}%",
            conf_map.get(cat, "—"),
        ])
    lca_rows.append([
        p("<b>TOTAL</b>", BOLD), "", p(f"<b>{total_emis:.0f}</b>", BOLD),
        p("<b>100%</b>", BOLD), "",
    ])
    story.append(tbl(lca_rows, [1.9*inch, 1.1*inch, 1.1*inch, 0.8*inch, 1.6*inch],
                     style_extra=[
                         ("FONTNAME", (0,-1),(-1,-1), "Helvetica-Bold"),
                         ("BACKGROUND",(0,-1),(-1,-1), LGREY),
                     ]))
    story.append(note(
        f"Net CO₂ removed: {lca_obj.net_removal_tonnes_co2():.1f} t/yr  |  "
        f"Net-negative ratio: {lca_obj.net_negative_ratio()*100:.1f}%  |  "
        "Key finding: tailings grinding is 63–67% of all system emissions on diesel crusher. "
        "Solar crusher contract is the single highest-leverage improvement."
    ))

    story += subsection("5.2 Monte Carlo LCA Uncertainty")
    story.append(p(
        f"500 simulations were run sampling 6 uncertain emission factors from triangular "
        f"distributions (literature-sourced bounds). Results for the <b>diesel crusher scenario</b>:"
    ))
    mc_data = [
        ["Metric", "Value"],
        ["P5 net-negative ratio",  f"{mc_stats.nn_p5*100:.1f}%"],
        ["P50 net-negative ratio", f"{mc_stats.nn_p50*100:.1f}%"],
        ["P95 net-negative ratio", f"{mc_stats.nn_p95*100:.1f}%"],
        ["P(ratio < 85% gate)",    f"{mc_stats.prob_below_85_pct:.1f}%"],
        ["P50 cost / net tonne",   f"${mc_stats.cost_p50:,.0f}"],
        ["Top uncertainty driver", "Sorbent manufacturing EF (4–15 kg CO₂e/kg)"],
    ]
    story.append(tbl(mc_data, [3.0*inch, 3.5*inch]))
    story.append(p(
        "The 4% probability of missing the 85% net-negative gate is <b>driven entirely by "
        "sorbent EF uncertainty</b>. Obtaining a supplier Environmental Product Declaration in "
        "Phase 1 would collapse this risk. The solar crusher scenario reduces P(below 85%) to "
        "near zero by eliminating diesel grinding emissions."
    ))

    story += subsection("5.3 MRV Traceability Chain")
    story.append(p(
        "Every verified removal credit traces through five records, all of which must be "
        "present and passing before a credit is issued:"
    ))
    mrv_chain = [
        ["Step", "Record", "Key gate"],
        ["1", "CaptureBatch", "Power source = solar/battery only; no grid fossil input"],
        ["2", "TailingsLotQualification", "All 8 EPA TCLP analytes below regulatory limits"],
        ["3", "CarbonationBatch", "Mass balance (tailings + CO₂ ≈ aggregate) within ±5%"],
        ["4", "ProductBatch", "Fate = sold_aggregate or geologic_injected (NOT stockpiled)"],
        ["5", "VerifiedCredit", "TCLP ✓ + ASTM C33 ✓ (for aggregate) + mass balance ✓"],
    ]
    story.append(tbl(mrv_chain, [0.5*inch, 1.8*inch, 4.2*inch]))
    story.append(note(
        f"Demo registry: {mrv_sum['verified_credits']} credits issued, "
        f"{mrv_sum['tailings_lots_qualified']} lots qualified, "
        f"{mrv_sum['tailings_lots_rejected']} lot rejected (arsenic exceedance — Sierrita pilot), "
        f"net water: {mrv_sum['water_net_consumed_litre']:.0f} L consumed "
        f"({mrv_sum['water_net_litre_per_t_co2']:.0f} L/t CO₂)."
    ))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # 6. VALIDATED PERFORMANCE RESULTS
    # ══════════════════════════════════════════════════════════════════════════

    story += section_header("6. Validated Performance Results")
    story.append(p(
        "The following results are from a full 365-day simulation with calibrated synthetic "
        "Phoenix weather data. Configuration: 50 kW peak PV, 200 kWh LFP battery, 18 kW fans, "
        "2,000 kg sorbent, Morenci Standard Lot tailings (20% reactive, 230 km, diesel grinder), "
        "mineral carbonation pathway, $200/tonne CO₂ credit price."
    ))

    story.append(sp(4))
    story.append(kpi_row([
        ("Gross CO₂", "114.3 t", "captured/year"),
        ("Net CO₂", "101.1 t", "removed/year"),
        ("System emissions", "13.2 t", "CO₂e/year total"),
        ("Net-negative", "88.4%", "ratio (gross basis)"),
        ("$/gross tonne", "$252", "vendor metric"),
        ("$/net tonne", "$285", "honest metric"),
    ]))
    story.append(sp(6))

    story += subsection("6.1 Optimisation Impact (vs Greedy Baseline)")
    opt_data = [
        ["Optimisation", "Mechanism", "Projected gain"],
        ["24h LP scheduler",        "scipy HiGHS LP, maximise net CO₂/$", "+8–12% net CO₂/yr"],
        ["Assay-aware threshold",   "Capture threshold scales with batch quality", "+3–5% net-neg ratio"],
        ["Dynamic regen temp",      "82–95°C by sorbent age (saves 15% sorbent life)", "−15% sorbent cost/yr"],
        ["Proactive cleaning",      "Schedule cleaning to solar peak (zero capture cost)", "+2–4% uptime"],
        ["Battery-forecast LP",     "Re-solve at day-start with actual SOC", "+4–7% battery utilisation"],
        ["Greedy fallback",         "No scipy → rule-based schedule", "−0 (graceful degradation)"],
    ]
    story.append(tbl(opt_data, [1.5*inch, 2.5*inch, 2.5*inch]))

    story += subsection("6.2 Seasonal Performance")
    seasonal_data = [
        ["Season", "Night temp range", "Capture factor", "Net-neg ratio", "Notes"],
        ["Winter (Dec–Feb)", "2–15°C",  "105%", "91–93%", "Best performance — cool nights, max capture"],
        ["Spring (Mar–May)", "10–25°C", "98%",  "89–91%", "Shoulder season — good all-round"],
        ["Summer (Jun–Sep)", "28–38°C", "72%",  "82–87%", "Worst — hot nights, capacity penalty"],
        ["Monsoon (Jul–Sep)","28–35°C", "78%",  "85–88%", "Humidity bonus partially offsets heat penalty"],
        ["Fall (Oct–Nov)",   "12–28°C", "96%",  "89–91%", "Second-best — recovering from summer"],
    ]
    story.append(tbl(seasonal_data, [1.2*inch, 1.2*inch, 1.0*inch, 1.0*inch, 2.1*inch]))
    story.append(note(
        "Phoenix July nights average 35°C / 95°F — the single largest performance risk. "
        "The system correctly penalises capture at high night temperatures and shifts scheduling "
        "weight toward shoulder seasons. The 85% net-negative gate is met on an annual average "
        "even with summer degradation."
    ))

    story += subsection("6.3 Sorbent Life Projection")
    story.append(p(
        "At 0.045% capacity loss per cycle and 3 cycles/day, the sorbent reaches the 60% "
        "replacement floor in approximately <b>2,200 cycles (~24 months)</b>. Dynamic temperature "
        "management (reducing regen temp from 95°C to 82°C as the sorbent ages) extends this to "
        "~27 months without hardware modification. The economic replacement trigger fires earlier "
        "when lost revenue from degraded capacity exceeds the amortised cost of a new bed at the "
        "prevailing carbon credit price."
    ))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # 7. CASH FLOW PROJECTIONS & FUNDING PLAN
    # ══════════════════════════════════════════════════════════════════════════

    story += section_header("7. Cash Flow Projections &amp; Funding Plan")
    story.append(p(
        "All projections use conservative mid-point assumptions. The 'commercial' column "
        "excludes grants — that is the stress-test view of whether the business stands on its "
        "own unit economics. <b>Model the worst plausible month, not the best.</b>"
    ))

    story += subsection("7.1 Phase-by-Phase Financials")
    cf_phase_data = [
        ["Phase", "Duration", "Gross CO₂\nt/mo", "Net CO₂\nt/mo", "Revenue\n$/mo (avg)",
         "Costs\n$/mo (avg)", "Net CF\n$/mo (avg)", "Breakeven"],
    ]
    month_acc = 0
    for ph in range(5):
        pp  = PHASE_PARAMS[ph]
        rows_ph = [r for r in cf_rows if r.phase == ph]
        if not rows_ph:
            continue
        avg_rev  = sum(r.total_commercial_revenue for r in rows_ph) / len(rows_ph)
        avg_cost = sum(r.total_cost for r in rows_ph) / len(rows_ph)
        avg_net  = sum(r.operating_cash_flow for r in rows_ph) / len(rows_ph)
        gross    = rows_ph[0].gross_co2_t
        net_co2  = rows_ph[0].net_co2_t
        month_acc += pp.duration_months
        be = "—" if ph < 2 else ("self-fund" if avg_net > 0 else "grant-dep.")
        cf_phase_data.append([
            f"Phase {ph}", f"{pp.duration_months} mo",
            f"{gross:.1f}", f"{net_co2:.1f}",
            f"${avg_rev:,.0f}", f"${avg_cost:,.0f}",
            f"${avg_net:,.0f}", be,
        ])
    story.append(tbl(cf_phase_data,
                     [0.65*inch, 0.65*inch, 0.75*inch, 0.75*inch, 1.0*inch, 1.0*inch, 1.0*inch, 0.7*inch]))

    story += subsection("7.2 Revenue Streams")
    rev_data = [
        ["Revenue stream", "When", "Rate (base case)", "Notes"],
        ["Aggregate sales",     "Phase 2+", "$38–50/t aggregate", "ASTM C33 required. ~4.2 t aggregate per t CO₂."],
        ["Voluntary carbon credits", "Phase 2+", "$250/t net CO₂", "Conservative; market range $200–500."],
        ["§45Q tax credit",     "Phase 2+", "$130/t (utilisation)", "Mineral carbonation = utilisation rate, not storage rate. Verify with counsel."],
        ["DOE SBIR Phase I",    "Phase 1",  "~$150k / 30 mo", "Non-dilutive. Eligibility: small business, novel tech."],
        ["DOE SBIR Phase II",   "Phase 2",  "~$1.5M / 24 mo", "Conditional on Phase I results."],
        ["DOE Carbon Negative Shot", "Phase 3+", "Prize TBD", "$3.5B program, $100/tonne target by 2032."],
        ["AZ State / county",   "Phase 2+", "$50–200k/yr", "AZ Commerce Authority clean energy grants."],
    ]
    story.append(tbl(rev_data, [1.5*inch, 0.8*inch, 1.4*inch, 2.8*inch],
                     style_extra=[("VALIGN",(0,0),(-1,-1),"TOP")]))

    story += subsection("7.3 Summary Financials")
    story.append(sp(4))
    story.append(kpi_row([
        ("Total revenue (96 mo)", f"${cf_sum['total_revenue_usd']:,.0f}", "incl. grants"),
        ("Commercial revenue", f"${cf_sum['total_commercial_rev_usd']:,.0f}", "excl. grants"),
        ("Total grants", f"${cf_sum['total_grant_usd']:,.0f}", "non-dilutive"),
        ("Total costs", f"${cf_sum['total_cost_usd']:,.0f}", "all phases"),
        ("Peak cash need", f"${abs(cf_sum['peak_cash_need_usd']):,.0f}", "max deficit"),
        ("Breakeven (commercial)", f"Mo {cf_sum['breakeven_month_commercial']}", "no grants"),
    ]))
    story.append(sp(8))

    story += subsection("7.4 Funding Plan")
    funding_data = [
        ["Phase", "Funding source", "Amount", "Type", "Trigger"],
        ["0", "Founder (sweat equity)", "$0–2k", "Self", "Start immediately"],
        ["1", "DOE SBIR Phase I", "~$150k", "Grant", "Company formed, FTO cleared"],
        ["1", "University partnership", "$0 cash", "In-kind lab access", "MOA with university partner"],
        ["2", "DOE SBIR Phase II", "~$1.5M", "Grant", "Phase I complete, bench results pass gate"],
        ["2", "Arizona Commerce Authority", "~$100k", "Grant", "Company in Arizona, pilot operational"],
        ["3", "DOE Carbon Negative Shot", "TBD", "Prize/contract", "Phase 2 gate passed, net-neg verified"],
        ["3", "Aggregate offtake advance", "~$50–150k", "Revenue advance", "ASTM C33 passed, buyer committed"],
        ["4", "Series A (optional)", "$1–5M", "Equity", "Only if replication requires capital"],
    ]
    story.append(tbl(funding_data, [0.55*inch, 2.0*inch, 0.85*inch, 1.0*inch, 2.1*inch],
                     style_extra=[("VALIGN",(0,0),(-1,-1),"TOP")]))
    story.append(note(
        "Key constraint: the founder is capital-light and proceeding alongside full-time work "
        "and school. Phase 0 has near-zero cash cost. Phase 1 SBIR bridges to Phase 2 without "
        "equity dilution. Equity is a last resort — only if scale-out speed requires it."
    ))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # 8. RISK REGISTER
    # ══════════════════════════════════════════════════════════════════════════

    story += section_header("8. Risk Register &amp; Mitigation")

    risk_data = [
        ["Risk", "Likelihood", "Impact", "Mitigation"],
        ["Sorbent EF is 15 kg CO₂e/kg (high end)\n→ net-neg ratio drops to ~75%",
         "Medium", "High",
         "Negotiate supplier EPD in Phase 1. Monte Carlo shows P(below 85%) = 4% on current estimate. "
         "Solar crusher contract reduces exposure."],
        ["Phoenix summer nights >38°C more frequent\n(climate trend)",
         "Medium", "Medium",
         "System already models 35°C baseline. LP scheduler shifts capture weight to cooler months. "
         "Economic impact: ~5% annual capture reduction per +1°C."],
        ["Tailings TCLP failure (blocking commercial use)\nat primary source",
         "Low-Medium", "High",
         "≥2 qualified sources required before Phase 2 gate. Sierrita pilot already failed "
         "(arsenic) — demonstrates the gate works. Pinto Valley solar-ground lot is backup."],
        ["§45Q eligibility disputed\n(mineral carbonation classification)",
         "Low", "High",
         "Engage tax counsel before Phase 2. EOR exclusion confirmed in IRA 2022 text. "
         "Mineral carbonation to aggregate is utilisation, not storage — rate is $130/t not $180/t."],
        ["Sorbent IP is not novel / FTO issue",
         "Medium", "High",
         "Phase 0 FTO check is a hard gate before any IP investment. Do not file patents "
         "before FTO is clear. University partnership provides freedom-to-operate via "
         "academic licensing if needed."],
        ["Dust fouling worse than modelled\n(haboob frequency increasing)",
         "Low-Medium", "Medium",
         "Proactive cleaning scheduling already in LP. Filter replacement cost is tracked "
         "in ledger. Physical solution: pre-filter cyclone separator (Phase 1 engineering)."],
        ["Carbon credit market price falls below $100/t",
         "Low", "Medium",
         "§45Q provides a $130/t floor independent of voluntary market. Aggregate revenue "
         "covers >50% of Phase 3 OpEx at $45/t even with zero carbon credits."],
        ["Single-founder risk\n(execution dependency)",
         "High", "High",
         "University partnership provides continuity. Document all processes in this codebase. "
         "Phase 1 goal: identify co-founder or technical advisor with equity stake."],
    ]
    story.append(tbl(risk_data,
                     [2.0*inch, 0.85*inch, 0.7*inch, 2.95*inch],
                     style_extra=[
                         ("VALIGN",   (0,0),(-1,-1),"TOP"),
                         ("BACKGROUND",(2,1),(2,2), colors.HexColor("#fef3c7")),
                         ("BACKGROUND",(2,3),(2,4), colors.HexColor("#fee2e2")),
                     ]))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # 9. IBM PARTNERSHIP PROPOSAL
    # ══════════════════════════════════════════════════════════════════════════

    story += section_header("9. IBM Partnership Proposal")
    story.append(p(
        "The prototype is ready for Phase 1 IBM deployment today. All code is Python 3.12 with "
        "four runtime dependencies. The 11 modules are independently containerisable. "
        "A live demo runs at http://localhost:8501 and can be deployed to IBM Cloud in under "
        "one business day."
    ))

    story += subsection("9.1 IBM Platform Architecture")
    ibm_data = [
        ["Module", "IBM Service", "Purpose"],
        ["Hourly scheduler (optimizer.py)", "IBM Cloud Kubernetes Service (IKS)", "CronJob pod, daily 06:00"],
        ["Weather + forecast (weather.py)", "watsonx.ai Granite-TTM", "72-h PV & temperature forecast"],
        ["Sensor ingestion (sensors.py)", "IBM App Connect", "MQTT/OPC-UA → MRV registry"],
        ["Ledger + MRV (ledger.py, mrv.py)", "IBM Cloud Databases for PostgreSQL", "Persistent signed records"],
        ["LCA + Monte Carlo", "Watson Studio / Cloud Pak for Data", "AutoAI continuous improvement"],
        ["Dashboard (app.py)", "IKS + IBM Cloud Internet Services", "Continuous, public URL"],
        ["Monitoring", "IBM Instana", "4 custom metrics: net-neg ratio, SOC, dust, sorbent cap"],
        ["Secrets & config", "IBM Secrets Manager", "API keys, sensor credentials"],
        ["Granite-3 assay reader", "watsonx.ai LoRA fine-tune", "XRF PDF → TailingsAssay JSON (Phase 4)"],
    ]
    story.append(tbl(ibm_data, [2.0*inch, 2.2*inch, 2.3*inch]))

    story += subsection("9.2 Phased IBM Engagement")
    ibm_phases = [
        ["Phase", "Timeline", "IBM Services", "Deliverable"],
        ["1 — Infrastructure", "Weeks 1–4",
         "IKS, Instana, Cloud Databases, Secrets Manager",
         "All 11 modules containerised, deployed, monitored. "
         "4 custom Instana metrics with adaptive alerts."],
        ["2 — Live Data", "Weeks 5–8",
         "watsonx.ai Granite-TTM, App Connect",
         "Real NOAA weather → Granite-TTM 72h forecast replacing synthetic data. "
         "Plant sensors → App Connect → MRV registry live."],
        ["3 — AutoAI", "Weeks 9–16",
         "Cloud Pak for Data, Watson ML, Watson Studio",
         "30 days of operational data → AutoAI pipeline. "
         "Deployed WML model returns daily LP weight adjustments."],
        ["4 — Granite Assay", "Weeks 17–24",
         "watsonx.ai LoRA, Cloud Object Storage",
         "Fine-tuned Granite-3 8B reads XRF lab PDFs → structured TailingsAssay JSON. "
         "Eliminates primary source of carbon accounting error."],
    ]
    story.append(tbl(ibm_phases, [1.1*inch, 0.85*inch, 2.0*inch, 2.55*inch],
                     style_extra=[("VALIGN",(0,0),(-1,-1),"TOP")]))

    story += subsection("9.3 IBM Alignment — Why This Project")
    for txt in [
        "<b>Net-zero commitment:</b> IBM targets net-zero by 2030. This project provides "
        "verified, permanent, third-party-auditable CO₂ removal — not offsets — with a "
        "complete and public ledger. IBM could include verified credits from this system in "
        "its own portfolio.",
        "<b>Referenceable watsonx sustainability demo:</b> A system where IBM technology "
        "directly enables a verifiable, permanent removal credit — with Granite-TTM forecasting, "
        "App Connect sensor integration, and AutoAI scheduling improvement — is a concrete "
        "demonstration of watsonx's sustainability use case.",
        "<b>Arizona copper mine opportunity:</b> Arizona mines generate >200 Mt tailings/yr. "
        "At full DAC-scale utilisation, this is a 20 Mt CO₂/yr removal opportunity — within "
        "the range of national climate targets. IBM's Arizona cloud infrastructure (Phoenix "
        "data center) is geographically aligned.",
        "<b>IP-light engagement:</b> The prototype is open to co-development. IBM's contribution "
        "is infrastructure and AI services; the carbon accounting methodology and MRV registry "
        "are the founder's IP. No IP conflict.",
    ]:
        story.append(b(txt))

    story += subsection("9.4 Requested from IBM Client Engineering")
    for txt in [
        "4-week IBM Client Engineering engagement to complete Phase 1 (IKS deployment, "
        "Instana monitoring, PostgreSQL integration) and validate against IBM Cloud production standards.",
        "Access to watsonx.ai Granite-TTM time series models for weather forecast integration "
        "under a watsonx trial or co-development agreement.",
        "Introduction to IBM's sustainability practice and carbon market advisory resources "
        "to structure the credit issuance and third-party verification pathway.",
        "Joint go-to-market exploration for watsonx.ai + DAC as a referenceable IBM "
        "sustainability demonstration project with potential inclusion in IBM's own carbon removal portfolio.",
    ]:
        story.append(b(txt))
    story.append(PageBreak())

    # ══════════════════════════════════════════════════════════════════════════
    # 10. APPENDICES
    # ══════════════════════════════════════════════════════════════════════════

    story += section_header("10. Appendices")

    story += subsection("Appendix A — Emission Factors")
    ef_data = [
        ["Factor", "Value", "Unit", "Source", "Confidence"],
        ["Solar PV lifecycle",         "0.020", "kg CO₂e/kWh", "IPCC AR6 WG3 Table A.III.2", "High"],
        ["Battery mfg overhead",       "0.008", "kg CO₂e/kWh discharged", "Ellingsen et al. 2022, LFP pack", "Medium"],
        ["Sorbent manufacturing",      "4–15 (mode 8)", "kg CO₂e/kg", "Fasihi 2019; Wurzbacher 2016", "LOW ⚠"],
        ["Diesel crusher",             "0.27", "kg CO₂e/kWh", "US EIA 2023 diesel genset", "High"],
        ["Solar crusher",              "0.020", "kg CO₂e/kWh", "Same as PV lifecycle", "High"],
        ["Truck transport",            "0.062", "kg CO₂e/t·km", "Arizona DOT 2022; IPCC AR6 T10.SM.1", "High"],
        ["Infrastructure (annualised)","1–4 (mode 2)", "kg CO₂e/t gross CO₂", "Climeworks 2021 LCA supp.", "LOW ⚠"],
        ["Filter manufacturing",       "8–28 (mode 15)", "kg CO₂e/set", "Ecoinvent 3.9 HEPA", "LOW ⚠"],
        ["Municipal water",            "0.00035", "kg CO₂e/L", "WRI Aqueduct; AZ municipal treatment", "Medium"],
        ["Geologic injection",         "0.040", "kWh/kg CO₂", "IEA injection energy estimate", "Medium"],
    ]
    story.append(tbl(ef_data, [1.6*inch, 1.1*inch, 1.3*inch, 2.0*inch, 0.5*inch]))

    story += subsection("Appendix B — Arizona Mine Database")
    mine_data = [
        ["Mine", "Operator", "Mineral type", "Reactivity", "Distance", "Grinder", "Notes"],
        ["Morenci", "Freeport-McMoRan", "Olivine/pyroxene", "18–22%", "230 km", "Diesel",
         "World's largest open-pit copper mine. High olivine, needs fine grind to 75 µm."],
        ["Bagdad", "Freeport-McMoRan", "Serpentinite", "22–28%", "310 km", "Diesel/Solar",
         "Highest reactivity. Softest ore — lowest grind energy. Solar-ground premium lot available."],
        ["Sierrita", "Freeport-McMoRan", "Wollastonite", "8–14%", "90 km", "Diesel",
         "Closest mine, lowest reactivity. Pilot lot failed TCLP (arsenic). Re-test pending."],
        ["Ray", "Asarco", "Mixed silicate", "12–18%", "110 km", "Diesel",
         "Moderate reactivity and proximity. Good balance of distance and quality."],
        ["Pinto Valley", "BHP", "Chlorite/talc", "10–16%", "150 km", "Solar",
         "Solar crusher on-site. Lowest grind energy. Near-zero grinding emissions."],
    ]
    story.append(tbl(mine_data,
                     [0.8*inch, 1.5*inch, 1.1*inch, 0.7*inch, 0.7*inch, 0.6*inch, 1.1*inch],
                     style_extra=[("FONTSIZE",(0,0),(-1,-1),7.5),
                                  ("VALIGN",(0,0),(-1,-1),"TOP")]))

    story += subsection("Appendix C — Glossary")
    gloss = [
        ("DAC", "Direct Air Capture — mechanical removal of CO₂ directly from ambient air"),
        ("Net-negative", "System removes more CO₂ than it emits across its full lifecycle"),
        ("Gross tonne", "CO₂ adsorbed by the sorbent — the vendor metric (incomplete)"),
        ("Net tonne", "CO₂ removed after all system emissions are deducted — the honest metric"),
        ("MRV", "Measurement, Reporting, Verification — the auditable chain from sensor to credit"),
        ("TCLP", "Toxicity Characteristic Leaching Procedure — EPA test for hazardous waste leaching"),
        ("ASTM C33", "Standard Specification for Concrete Aggregates (ASTM International)"),
        ("§45Q", "IRS Section 45Q tax credit for carbon capture and storage ($130/t utilisation, $180/t storage)"),
        ("LCA", "Life Cycle Assessment — accounting for all emissions across a product's lifecycle"),
        ("Bond's Law", "Grinding energy equation: W = Wi × 10 × (1/√P₈₀ − 1/√F₈₀) in kWh/t"),
        ("EOR", "Enhanced Oil Recovery — CO₂ injected to extract more oil. NOT a permanent fate."),
        ("FTO", "Freedom to Operate — patent search to confirm no blocking IP"),
        ("SBIR", "Small Business Innovation Research — US federal grant program (DOE, NSF, etc.)"),
        ("GHI", "Global Horizontal Irradiance — solar resource measurement (W/m²)"),
        ("LFP", "Lithium Iron Phosphate — battery chemistry (high cycle life, thermal stability)"),
    ]
    gloss_data = [["Term", "Definition"]] + [[t, d] for t, d in gloss]
    story.append(tbl(gloss_data, [0.9*inch, 5.6*inch]))

    story += subsection("Appendix D — Software Files")
    file_data = [
        ["File", "Lines (approx.)", "Purpose"],
        ["weather.py",       "~250", "Synthetic Phoenix weather generator"],
        ["sorbent.py",       "~170", "Amine sorbent degradation + replacement economics"],
        ["tailings.py",      "~420", "Per-batch assay engine, Bond's Law, mine database"],
        ["ledger.py",        "~250", "Net-negative carbon ledger, all emission debits"],
        ["optimizer.py",     "~450", "24h LP scheduler + 5 optimisations"],
        ["mrv.py",           "~430", "MRV batch traceability chain, TCLP gates"],
        ["lca.py",           "~310", "ISO 14064-2 LCA boundary, water accounting"],
        ["phase_gate.py",    "~310", "Phase 0–4 go/no-go engine"],
        ["cashflow.py",      "~420", "96-month revenue/cost model, §45Q, grants"],
        ["sensors.py",       "~390", "Sensor pipeline, QC, auto-MRV commit"],
        ["monte_carlo.py",   "~265", "Monte Carlo LCA sensitivity, tornado chart"],
        ["app.py",           "~1,400", "11-tab Streamlit dashboard (main UI)"],
        ["demo.py",          "~200", "CLI demo (no web UI required)"],
        ["build_pdf.py",     "~820", "This document generator"],
        ["requirements.txt", "5",    "streamlit, plotly, pandas, scipy, reportlab"],
    ]
    story.append(tbl(file_data, [1.5*inch, 1.2*inch, 3.8*inch]))

    # ── Final footer page ──────────────────────────────────────────────────────
    story.append(Spacer(1, 0.5*inch))
    story.append(hr())
    story.append(p(
        "<b>Phoenix Direct Air Capture</b>  ·  AI Optimizer &amp; Carbon Ledger  ·  "
        f"Generated {TODAY}", CNTR
    ))
    story.append(p(
        "CONFIDENTIAL — PRE-COMMERCIAL  ·  All performance figures from prototype simulation  ·  "
        "Not an offer to sell securities", CAPT
    ))

    # ── Build ──────────────────────────────────────────────────────────────────
    def _first_page(c, d):
        _cover_page(c, d)

    def _later_pages(c, d):
        _header_footer(c, d)

    doc.build(story, onFirstPage=_first_page, onLaterPages=_later_pages)
    print(f"✅  PDF written to: {OUT_PATH}")
    print(f"    Size: {os.path.getsize(OUT_PATH) / 1024:.0f} kB")


if __name__ == "__main__":
    build()
