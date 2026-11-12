"""
build_slides.py — Generate submission presentation for IBM AI Builders Challenge
Run: cd dac_optimizer && python3 build_slides.py
→ writes Phoenix_DAC_Submission_Slides.pptx
"""
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt

OUT = Path(__file__).resolve().parent / "Phoenix_DAC_Submission_Slides.pptx"

# ── Colours ────────────────────────────────────────────────────────────────────
NAVY   = RGBColor(0x1e, 0x3a, 0x5f)
TEAL   = RGBColor(0x0e, 0x74, 0x90)
GREEN  = RGBColor(0x16, 0x65, 0x34)
WHITE  = RGBColor(0xff, 0xff, 0xff)
LGREY  = RGBColor(0xf1, 0xf5, 0xf9)
DGREY  = RGBColor(0x33, 0x41, 0x55)
AMBER  = RGBColor(0x92, 0x40, 0x0e)

W = Inches(13.33)  # widescreen 16:9
H_SLIDE = Inches(7.5)

prs = Presentation()
prs.slide_width  = W
prs.slide_height = H_SLIDE

BLANK = prs.slide_layouts[6]  # completely blank

def slide():
    return prs.slides.add_slide(BLANK)

def bg(sl, color):
    fill = sl.background.fill
    fill.solid()
    fill.fore_color.rgb = color

def box(sl, left, top, width, height, text="", font_size=18,
        bold=False, color=WHITE, align=PP_ALIGN.LEFT,
        bg_color=None, wrap=True):
    txb = sl.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height))
    if bg_color:
        txb.fill.solid()
        txb.fill.fore_color.rgb = bg_color
    tf = txb.text_frame
    tf.word_wrap = wrap
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = Pt(font_size)
    run.font.bold = bold
    run.font.color.rgb = color
    return txb

def multiline(sl, left, top, width, height, lines,
              font_size=14, color=WHITE, bold_first=False, spacing=1.15,
              align=PP_ALIGN.LEFT):
    txb = sl.shapes.add_textbox(
        Inches(left), Inches(top), Inches(width), Inches(height))
    tf = txb.text_frame
    tf.word_wrap = True
    for i, line in enumerate(lines):
        if i == 0:
            p = tf.paragraphs[0]
        else:
            p = tf.add_paragraph()
        p.alignment = align
        p.space_after = Pt(4)
        run = p.add_run()
        run.text = line
        run.font.size = Pt(font_size)
        run.font.color.rgb = color
        run.font.bold = (bold_first and i == 0)
    return txb

def rect(sl, left, top, width, height, color):
    shape = sl.shapes.add_shape(
        1,  # MSO_SHAPE_TYPE.RECTANGLE
        Inches(left), Inches(top), Inches(width), Inches(height))
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    return shape

def kpi_card(sl, left, top, label, value, unit, w=2.2, h=1.4):
    rect(sl, left, top, w, h, NAVY)
    box(sl, left+0.1, top+0.08, w-0.2, 0.45,
        value, font_size=28, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    box(sl, left+0.1, top+0.55, w-0.2, 0.45,
        label, font_size=11, color=RGBColor(0xbf,0xdb,0xfe), align=PP_ALIGN.CENTER)
    box(sl, left+0.1, top+0.95, w-0.2, 0.35,
        unit, font_size=10, color=TEAL, align=PP_ALIGN.CENTER)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 1 — COVER
# ══════════════════════════════════════════════════════════════════════════════
sl = slide()
bg(sl, NAVY)
rect(sl, 0, 0, 13.33, 0.08, TEAL)   # top accent bar
rect(sl, 0, 7.42, 13.33, 0.08, TEAL)  # bottom bar

box(sl, 0.6, 1.4, 12, 1.0,
    "🌵 Phoenix Direct Air Capture — AI Optimizer",
    font_size=36, bold=True, color=WHITE, align=PP_ALIGN.CENTER)

box(sl, 0.6, 2.5, 12, 0.6,
    "Solar-powered CO₂ removal · Mineral carbonation into Arizona copper mine tailings",
    font_size=18, color=RGBColor(0xbf,0xdb,0xfe), align=PP_ALIGN.CENTER)

box(sl, 0.6, 3.2, 12, 0.5,
    "Net-negative verified · IBM AI Builders Challenge 2024 · Sustainability & Environment",
    font_size=14, color=RGBColor(0x94,0xa3,0xb8), align=PP_ALIGN.CENTER)

rect(sl, 3.5, 4.1, 6.33, 0.06, TEAL)

box(sl, 0.6, 4.4, 12, 0.45,
    "Built entirely with IBM Bob  ·  11 Python modules  ·  Running live today",
    font_size=13, color=RGBColor(0x60,0xa5,0xfa), align=PP_ALIGN.CENTER)

box(sl, 0.6, 5.1, 12, 0.4,
    "Submission deadline: December 10, 2024",
    font_size=12, color=RGBColor(0x94,0xa3,0xb8), align=PP_ALIGN.CENTER)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 2 — PROBLEM
# ══════════════════════════════════════════════════════════════════════════════
sl = slide()
bg(sl, RGBColor(0xf7,0xf8,0xfa))
rect(sl, 0, 0, 13.33, 0.55, NAVY)
box(sl, 0.4, 0.1, 12, 0.4, "The Problem", font_size=22, bold=True,
    color=WHITE, align=PP_ALIGN.LEFT)

# Left: problem statement
multiline(sl, 0.5, 0.85, 6.0, 5.5, [
    "❶  Carbon accounting is broken",
    "   Most DAC operators report cost per GROSS tonne —",
    "   before subtracting the emissions from running the plant.",
    "   This overstates removal by 15–30%.",
    "",
    "❷  Static fan schedules waste battery",
    "   Phoenix summers: nights still reach 35°C / 95°F.",
    "   Running fans at the wrong hour burns battery",
    "   when capture efficiency is already low.",
    "",
    "❸  Tailings chemistry is ignored",
    "   Arizona mines have 8–28% reactive mineral fraction.",
    "   Ignoring this means the carbonation reactor is",
    "   undersupplied or oversupplied — wasting CO₂.",
    "",
    "❹  No permanent-fate verification",
    "   Without a traceability chain from capture → product",
    "   → confirmed permanent fate, no credit can be verified.",
], font_size=13, color=DGREY)

# Right: impact box
rect(sl, 7.1, 0.85, 5.7, 6.0, NAVY)
multiline(sl, 7.3, 1.0, 5.3, 5.5, [
    "Scale of opportunity",
    "",
    "Arizona mines generate",
    "200M+ tonnes tailings/year",
    "",
    "At full DAC scale →",
    "20M t CO₂/year sequestered",
    "",
    "Phoenix metro is #1",
    "fastest-growing US city —",
    "sustained aggregate demand",
    "",
    "Solar irradiance: 299",
    "sunny days/year in Phoenix",
    "— entire energy loop",
    "closes on solar",
], font_size=14, color=WHITE, bold_first=True)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 3 — SOLUTION + IBM BOB
# ══════════════════════════════════════════════════════════════════════════════
sl = slide()
bg(sl, RGBColor(0xf7,0xf8,0xfa))
rect(sl, 0, 0, 13.33, 0.55, NAVY)
box(sl, 0.4, 0.1, 12, 0.4, "The Solution & How IBM Bob Built It",
    font_size=22, bold=True, color=WHITE)

# Solution description
multiline(sl, 0.5, 0.75, 7.5, 2.2, [
    "Phoenix DAC Optimizer — end-to-end AI platform",
    "  • 72-hour rolling Mixed Integer Program (scipy.milp) maximises net CO₂/$ over 3 days",
    "  • Sorbent degradation model with real replacement economics",
    "  • Per-batch tailings assay engine (Bond's Law grinding, TCLP gate)",
    "  • Net-negative ledger: gross CO₂ minus ALL lifecycle emissions",
    "  • ISO 14064-2 LCA + Monte Carlo uncertainty (500 simulations, pure Python)",
    "  • Full MRV batch traceability: capture → carbonation → verified credit",
    "  • 96-month cash flow model + §45Q tax credit pathway",
    "  • Sensor data pipeline: CSV/MQTT → auto-commits to MRV registry",
], font_size=12, color=DGREY, bold_first=True)

# IBM Bob callout
rect(sl, 0.5, 3.1, 7.5, 1.8, TEAL)
multiline(sl, 0.7, 3.2, 7.1, 1.6, [
    "🤖  How IBM Bob built this",
    "Every module was described to Bob in plain English — Bob wrote the code,",
    "I validated the physics. 11 modules, 1,400+ lines of dashboard, 6 optimizer",
    "improvements, ISO 14064-2 LCA, PPTX generator — all in one conversation.",
    "Bob caught a fundamental error (phantom daytime captures) that improved",
    "physical accuracy. This is the honest prototype, not the polished one.",
], font_size=12, color=WHITE, bold_first=True)

# Module grid (right side)
rect(sl, 8.3, 0.75, 4.6, 6.3, NAVY)
box(sl, 8.5, 0.85, 4.2, 0.4, "11 Python modules", font_size=13,
    bold=True, color=WHITE)
mods = [
    "weather.py    → Phoenix TMY3 weather",
    "sorbent.py    → Degradation + economics",
    "tailings.py   → Per-batch assay engine",
    "ledger.py     → Net-negative ledger",
    "optimizer.py  → 72h MIP scheduler",
    "mrv.py        → MRV traceability chain",
    "lca.py        → ISO 14064-2 LCA",
    "phase_gate.py → Go/No-Go engine",
    "cashflow.py   → 96-month model",
    "sensors.py    → Sensor pipeline",
    "monte_carlo.py→ MC uncertainty",
]
multiline(sl, 8.5, 1.35, 4.2, 5.5, mods,
          font_size=10.5, color=RGBColor(0xbf,0xdb,0xfe))

# Phase gate flow
multiline(sl, 0.5, 5.1, 7.5, 2.0, [
    "Phase gate discipline  (0 → 4)",
    "  Phase 0: Literature + FTO check (current)   →  Phase 1: Bench prototype",
    "  Phase 2: Pilot plant, ASTM C33, 45Q          →  Phase 3: Commercial scale",
    "  Each phase only unlocks when ALL automated gates pass in the dashboard",
], font_size=11.5, color=DGREY, bold_first=True)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 4 — DEMO SCREENSHOTS (KPIs + architecture)
# ══════════════════════════════════════════════════════════════════════════════
sl = slide()
bg(sl, RGBColor(0xf7,0xf8,0xfa))
rect(sl, 0, 0, 13.33, 0.55, NAVY)
box(sl, 0.4, 0.1, 12, 0.4, "Live Demo — 11-Tab Dashboard",
    font_size=22, bold=True, color=WHITE)

# KPI cards row
kpi_card(sl, 0.4, 0.75, "Gross CO₂/yr", "93.0 t",   "50 kW pilot system")
kpi_card(sl, 2.75, 0.75, "Net CO₂/yr",  "82.8 t",   "after all debits")
kpi_card(sl, 5.1, 0.75, "Net-negative", "89.0%",    "Phase 2 gate ≥85% ✅")
kpi_card(sl, 7.45, 0.75, "Cost/net t",  "$408",     "honest metric")
kpi_card(sl, 9.8, 0.75, "Sorbent rep.", "~24 mo",   "auto-triggered")

# Tab list
rect(sl, 0.4, 2.35, 5.8, 4.8, NAVY)
box(sl, 0.6, 2.45, 5.4, 0.4, "11 Dashboard Tabs",
    font_size=13, bold=True, color=WHITE)
multiline(sl, 0.6, 2.95, 5.4, 4.0, [
    "📊 Dashboard      — KPIs, gauge, emission donut",
    "⛏  Tailings       — 6 mine comparison, TCLP",
    "⏱  Hourly dispatch— 7-day timeline, SOC, CO₂",
    "🧪  Sorbent health — Degradation + replacement",
    "🔗  MRV Registry  — Batch traceability chain",
    "♻️  LCA Boundary  — ISO 14064-2, water use",
    "🚦  Phase Gates   — Go/No-Go live dashboard",
    "💰  Cash Flow     — 96-month projections",
    "📡  Sensor pipe   — CSV ingest → auto MRV",
    "🎲  Monte Carlo   — LCA uncertainty analysis",
    "📥  Export        — CSV + MRV JSON download",
], font_size=12, color=WHITE)

# Optimizer detail
rect(sl, 6.6, 2.35, 6.3, 4.8, RGBColor(0x0e,0x74,0x90))
box(sl, 6.8, 2.45, 5.9, 0.4, "Optimizer: 72-h Rolling MIP",
    font_size=13, bold=True, color=WHITE)
multiline(sl, 6.8, 2.95, 5.9, 4.0, [
    "Variables: x[h] ∈ {0,1} fan binary",
    "           s_k[h] battery SOC per scenario",
    "",
    "Objective: max net CO₂ × assay_eff",
    "           − battery wear − electricity cost",
    "",
    "3 PV scenarios (×0.75 / 1.0 / 1.20)",
    "weighted (0.25 / 0.50 / 0.25) for",
    "cloud-robust scheduling",
    "",
    "Hard constraints:",
    "• No capture 07:00–18:00 (solar reserved)",
    "• SOC ≥ 28% at 03:00–06:00 (dawn reserve)",
    "• Re-solved every day-start with actual SOC",
], font_size=11.5, color=WHITE)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 5 — IMPACT + CARBON ACCOUNTING
# ══════════════════════════════════════════════════════════════════════════════
sl = slide()
bg(sl, RGBColor(0xf7,0xf8,0xfa))
rect(sl, 0, 0, 13.33, 0.55, NAVY)
box(sl, 0.4, 0.1, 12, 0.4, "Impact & Carbon Accounting Methodology",
    font_size=22, bold=True, color=WHITE)

# Left: emission breakdown
rect(sl, 0.4, 0.75, 5.8, 6.3, NAVY)
box(sl, 0.6, 0.85, 5.4, 0.4, "Where emissions come from",
    font_size=13, bold=True, color=WHITE)
multiline(sl, 0.6, 1.35, 5.4, 5.2, [
    "Tailings processing   15.8 t  78.3%  ← biggest lever",
    "Sorbent mfg            1.6 t   7.8%",
    "Fan electricity        1.8 t   8.8%",
    "Battery mfg            0.5 t   2.2%",
    "Vacuum electricity     0.2 t   1.2%",
    "Infrastructure         0.3 t   1.5%",
    "Filter mfg             0.07t   0.3%",
    "",
    "Total system:  20.2 t CO₂e/yr",
    "Gross captured: 93.0 t CO₂/yr",
    "Net removed:    82.8 t CO₂/yr",
    "Net-negative:   89.0%",
    "",
    "→ Solar crusher contract at mine",
    "  converts 15.8t → ~2.4t (-85%)",
    "  Net-negative would reach 92%+",
], font_size=12, color=WHITE, bold_first=True)

# Right: MRV chain
rect(sl, 6.6, 0.75, 6.3, 3.1, TEAL)
box(sl, 6.8, 0.85, 5.9, 0.4, "MRV Traceability Chain",
    font_size=13, bold=True, color=WHITE)
multiline(sl, 6.8, 1.35, 5.9, 2.4, [
    "① Capture batch   power=solar/battery only",
    "② TCLP test       all 8 EPA analytes < limit",
    "③ Carbonation     mass balance ±5%",
    "④ Product batch   fate = permanent only",
    "⑤ Verified credit TCLP ✅ ASTM C33 ✅",
    "",
    "No credit issued until all 5 gates pass.",
], font_size=12, color=WHITE)

# Phase gates
rect(sl, 6.6, 4.05, 6.3, 3.0, NAVY)
box(sl, 6.8, 4.15, 5.9, 0.4, "Phase Gate Results (live from ledger)",
    font_size=13, bold=True, color=WHITE)
multiline(sl, 6.8, 4.65, 5.9, 2.2, [
    "Phase 0  🟡  2/5 gates   Literature ✅  FTO ❌ pending",
    "Phase 1  🔴  0/5 gates   Bench not started",
    "Phase 2  🔴  2/7 gates   Net-neg ✅  Cost ✅",
    "",
    "This is Phase 0. Honest about where we are.",
    "The software is AHEAD of the hardware.",
], font_size=12, color=WHITE, bold_first=True)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 6 — NEXT STEPS + FUNDING
# ══════════════════════════════════════════════════════════════════════════════
sl = slide()
bg(sl, RGBColor(0xf7,0xf8,0xfa))
rect(sl, 0, 0, 13.33, 0.55, NAVY)
box(sl, 0.4, 0.1, 12, 0.4, "Next Steps, Funding Plan & IBM Partnership",
    font_size=22, bold=True, color=WHITE)

# Next steps
rect(sl, 0.4, 0.75, 5.8, 3.5, TEAL)
box(sl, 0.6, 0.85, 5.4, 0.4, "Next steps (Phase 0 → 1)",
    font_size=13, bold=True, color=WHITE)
multiline(sl, 0.6, 1.35, 5.4, 2.8, [
    "① Freedom-to-operate patent search",
    "   (sorbent-solvent polymer contactor IP)",
    "② University lab partner for bench testing",
    "③ TCLP test plan — Morenci + Ray mine contacts",
    "④ DOE SBIR Phase I application (~$150k)",
    "⑤ LCA v1 external review (ISO 14064-2)",
    "⑥ Company entity formation (LLC)",
], font_size=12, color=WHITE)

# Funding
rect(sl, 0.4, 4.45, 5.8, 2.7, NAVY)
box(sl, 0.6, 4.55, 5.4, 0.4, "Funding roadmap (capital-light)",
    font_size=13, bold=True, color=WHITE)
multiline(sl, 0.6, 5.05, 5.4, 2.0, [
    "Phase 0: $0 (sweat equity + this software)",
    "Phase 1: DOE SBIR I   ~$150k  (non-dilutive)",
    "Phase 2: DOE SBIR II  ~$1.5M  (non-dilutive)",
    "Phase 3: DOE Carbon Negative Shot + offtake",
    "Phase 4: Series A only if replication requires it",
], font_size=12, color=WHITE)

# IBM
rect(sl, 6.6, 0.75, 6.3, 6.4, NAVY)
box(sl, 6.8, 0.85, 5.9, 0.4, "IBM Partnership Opportunity",
    font_size=13, bold=True, color=WHITE)
multiline(sl, 6.8, 1.35, 5.9, 5.6, [
    "What IBM gets:",
    "  • Verified, permanent CO₂ removal credits",
    "    for IBM's own net-zero portfolio",
    "  • Referenceable watsonx sustainability demo",
    "    (Granite-TTM forecast → MIP optimizer → credit)",
    "  • IBM App Connect: sensors → MRV live",
    "  • AutoAI: tune LP weights on operational data",
    "  • Granite-3: XRF lab PDF → TailingsAssay JSON",
    "",
    "What we need from IBM:",
    "  • 4-week Client Engineering engagement",
    "    (IKS deploy, Instana, PostgreSQL)",
    "  • watsonx.ai Granite-TTM trial access",
    "  • Carbon market advisory resources",
    "",
    "Commercial path:",
    "  • 93 t/yr pilot → 10 t/day commercial",
    "  • Arizona mine tailings: 200M t/yr supply",
    "  • Potential scale: 20M t CO₂/yr sequestered",
    "  • §45Q: $130/t mineral carbonation credit",
], font_size=11.5, color=WHITE, bold_first=True)


# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 7 — CLOSING / CALL TO ACTION
# ══════════════════════════════════════════════════════════════════════════════
sl = slide()
bg(sl, NAVY)
rect(sl, 0, 0, 13.33, 0.08, TEAL)
rect(sl, 0, 7.42, 13.33, 0.08, TEAL)

box(sl, 0.6, 1.6, 12, 0.9,
    "Capture the air. Turn it into rock. Build with it.",
    font_size=34, bold=True, color=WHITE, align=PP_ALIGN.CENTER)

box(sl, 0.6, 2.65, 12, 0.5,
    "Phoenix Direct Air Capture — AI Optimizer",
    font_size=18, color=RGBColor(0xbf,0xdb,0xfe), align=PP_ALIGN.CENTER)

rect(sl, 3.5, 3.35, 6.33, 0.06, TEAL)

multiline(sl, 1.5, 3.6, 10.33, 1.4, [
    "89.0% net-negative verified  ·  $408/net tonne  ·  93 t CO₂/yr  ·  0 daytime captures (physically correct)",
    "11 modules  ·  1,400+ lines  ·  72-h rolling MIP  ·  ISO 14064-2 LCA  ·  Full MRV chain  ·  Monte Carlo uncertainty",
    "Phase 0 prototype — honest about where we are, ambitious about where we're going",
], font_size=13, color=RGBColor(0x94,0xa3,0xb8), align=PP_ALIGN.CENTER)

box(sl, 0.6, 5.3, 12, 0.5,
    "Built entirely with IBM Bob  ·  IBM AI Builders Challenge 2024  ·  Sustainability & Environment",
    font_size=14, bold=True, color=RGBColor(0x60,0xa5,0xfa), align=PP_ALIGN.CENTER)

box(sl, 0.6, 6.0, 12, 0.45,
    "github.com/PBrooks11/Phoenix-dac-optimizer  ·  Live demo: phoenix-dac-optimizer-5zjneygcrutyu5ywn2ivo5.streamlit.app",
    font_size=12, color=RGBColor(0x94,0xa3,0xb8), align=PP_ALIGN.CENTER)


# ── Save ───────────────────────────────────────────────────────────────────────
prs.save(OUT)
print(f"✅  Slides written: {OUT}")
print(f"    {len(prs.slides)} slides  ·  {OUT.stat().st_size // 1024} kB")
