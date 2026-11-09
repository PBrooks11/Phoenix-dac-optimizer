# Phoenix DAC Optimizer
### AI-Powered Carbon Removal System — IBM AI Builders Challenge 2024

**[Live Demo →](https://your-deploy-url.streamlit.app)** | Built with IBM Bob

---

## What it does

An end-to-end AI optimizer and carbon accounting platform for a desert **Direct Air Capture (DAC)** system in Phoenix, Arizona.

- Captures CO₂ at night using solar-charged batteries + hybrid sorbent-solvent contactors
- Releases CO₂ by day via solar thermal regeneration (80–100°C)
- Permanently sequesters CO₂ via **mineral carbonation into construction aggregate** from Arizona copper mine tailings — or geologic injection
- **No fossil energy anywhere in the loop**

## Key results (validated, 365-day simulation)

| Metric | Value |
|---|---|
| Gross CO₂ captured | 93.0 t/year |
| Net CO₂ removed | 82.8 t/year |
| Net-negative ratio | 89.0% |
| Cost / net tonne | $408 |
| Optimizer | 72-hour rolling MIP (scipy.milp) |
| Battery utilisation | 84% of available night hours |

## Built entirely with IBM Bob

Every line of code in this project was written with IBM Bob as the primary development tool — 11 Python modules, 1,400+ lines of Streamlit dashboard, 6 optimizer improvements, and this README.

## Run locally

```bash
git clone https://github.com/YOUR_USERNAME/phoenix-dac-optimizer
cd phoenix-dac-optimizer
pip install -r requirements.txt
streamlit run app.py
```

## Architecture

```
weather.py       → Synthetic Phoenix weather (NREL TMY3 calibrated)
sorbent.py       → Amine sorbent degradation model
tailings.py      → Per-batch assay engine (6 Arizona mines)
ledger.py        → Net-negative carbon ledger
optimizer.py     → 72-h rolling MIP scheduler (6 optimizations)
mrv.py           → MRV batch traceability chain
lca.py           → ISO 14064-2 LCA boundary model
phase_gate.py    → Phase 0→4 go/no-go engine
cashflow.py      → 96-month revenue/cost model
sensors.py       → Sensor data pipeline
monte_carlo.py   → Monte Carlo LCA sensitivity
app.py           → 11-tab Streamlit dashboard
```

## The 6 optimizer improvements

1. **72-hour rolling MIP** — binary fan on/off via `scipy.optimize.milp`, 3-day horizon
2. **Assay-aware capture threshold** — low-quality tailings batches tighten the threshold automatically
3. **Dynamic regen temperature** — 95°C fresh sorbent → 82°C aged, extends bed life ~15%
4. **Proactive cleaning scheduling** — forecasts dust fouling, cleans at solar peak before it hits capture window
5. **Battery-forecast re-solve** — LP re-solved every day-start with actual current SOC
6. **Stochastic PV scenarios** — 3 PV scenarios (×0.75/1.0/1.20) with probability weights for cloud-robust scheduling

## Why this matters

Arizona copper mines generate **200+ million tonnes of tailings per year** — an environmental liability. At full scale, DAC-to-mineral-carbonation could sequester **20 million tonnes CO₂/year** from Arizona mines alone, while producing construction-grade aggregate for one of the fastest-growing metro areas in the US.

## Carbon accounting methodology

This system uses **honest net-negative accounting** — cost per NET tonne, not gross tonne.
Every credit traces through: Capture batch → TCLP-qualified tailings lot → Carbonation reactor (mass balance ±5%) → Confirmed permanent fate → Verified credit.

- **ISO 14064-2** aligned LCA boundary
- **EPA TCLP** leaching test gates on every tailings source
- **ASTM C33** aggregate specification gate before any product ships
- **§45Q** tax credit pathway (mineral carbonation = utilisation, $130/t)

## Challenge

IBM AI Builders Challenge — Sustainability & Environment track  
Submission deadline: December 10, 2024

---
*Built with IBM Bob · Phoenix, Arizona · Pre-commercial prototype*
