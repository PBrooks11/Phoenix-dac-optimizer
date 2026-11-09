"""
Phoenix DAC Optimizer — main demo script
=========================================
Run:   python demo.py
Deps:  Python 3.9+ standard library only (no third-party packages)
"""

from __future__ import annotations

import math
from collections import defaultdict

from weather import generate_phoenix_year
from optimizer import optimize_schedule, FAN_POWER_KW, VACUUM_PUMP_KW, BATTERY_CAPACITY_KWH
from sorbent import should_replace_sorbent, SORBENT_MASS_KG
from ledger import CarbonLedger


# ── ANSI colour helpers (graceful no-op on Windows) ───────────────────────────
try:
    import sys
    _tty = sys.stdout.isatty()
except Exception:
    _tty = False

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _tty else text

GREEN  = lambda t: _c("32;1", t)
CYAN   = lambda t: _c("36;1", t)
YELLOW = lambda t: _c("33;1", t)
RED    = lambda t: _c("31;1", t)
BOLD   = lambda t: _c("1",    t)
DIM    = lambda t: _c("2",    t)


def bar(fraction: float, width: int = 30, fill: str = "█", empty: str = "░") -> str:
    filled = round(min(1.0, max(0.0, fraction)) * width)
    return fill * filled + empty * (width - filled)


def section(title: str) -> None:
    print()
    print(BOLD("═" * 66))
    print(BOLD(f"  {title}"))
    print(BOLD("═" * 66))


# ─────────────────────────────────────────────────────────────────────────────
# 1.  Generate one year of Phoenix weather
# ─────────────────────────────────────────────────────────────────────────────

section("① Generating synthetic Phoenix weather data (full year, hourly)")

conditions = generate_phoenix_year(seed=42, array_kw_peak=50.0)
print(f"  Generated {len(conditions):,} hourly records  "
      f"({len(conditions)//24} days × 24 h)")

# Quick weather stats
july_nights = [c for c in conditions if 180 <= c.day <= 210 and 21 <= c.hour_of_day <= 23]
avg_july_night_t = sum(c.temp_c for c in july_nights) / len(july_nights)
jan_nights  = [c for c in conditions if   0 <= c.day <=  30 and 21 <= c.hour_of_day <= 23]
avg_jan_night_t  = sum(c.temp_c for c in jan_nights)  / len(jan_nights)
dust_events = sum(1 for c in conditions if c.dust_factor > 1.8)
print(f"  Avg July night temp  : {avg_july_night_t:.1f} °C  "
      f"({avg_july_night_t * 9/5 + 32:.0f} °F)  ← capture penalty in effect")
print(f"  Avg Jan  night temp  : {avg_jan_night_t:.1f} °C  "
      f"({avg_jan_night_t * 9/5 + 32:.0f} °F)")
print(f"  Dust events (severe) : {dust_events} hours")
peak_pv = max(c.solar_pv_avail_kw for c in conditions)
print(f"  Peak PV output       : {peak_pv:.1f} kW  (50 kW array at ~{peak_pv/50*100:.0f}% efficiency)")


# ─────────────────────────────────────────────────────────────────────────────
# 2.  Run the optimizer (full year)
# ─────────────────────────────────────────────────────────────────────────────

section("② Running hourly fan-schedule optimizer (full year)")

decisions, ledger, final_sorbent = optimize_schedule(
    conditions=conditions,
    initial_soc=0.70,
    pathway="mineral",
    co2_price_usd_per_tonne=200.0,
    verbose=True,
)

# Mode breakdown
mode_counts: dict = defaultdict(int)
mode_co2:    dict = defaultdict(float)
for d in decisions:
    mode_counts[d.mode] += 1
    mode_co2[d.mode]    += d.co2_kg_this_hour

total_hours = len(decisions)
print(f"\n  Dispatch summary  ({total_hours:,} hours):")
for mode in ("capture", "regen", "idle", "cleaning"):
    h = mode_counts[mode]
    co2 = mode_co2[mode]
    pct = h / total_hours * 100
    print(f"    {mode:<10} {h:>5} h  ({pct:4.1f}%)   "
          f"CO₂: {co2/1000:6.2f} t")


# ─────────────────────────────────────────────────────────────────────────────
# 3.  Carbon ledger summary
# ─────────────────────────────────────────────────────────────────────────────

section("③ Net-negative carbon ledger")

s = ledger.summary()

gross_t = s["gross_co2_tonnes"]
net_t   = s["net_co2_tonnes"]
emis_t  = s["total_emissions_tonnes"]
net_frac= s["net_negative_fraction"]

print(f"\n  Gross CO₂ captured     : {BOLD(f'{gross_t:>8.2f} tonnes')}")
print(f"  System emissions       : {YELLOW(f'{emis_t:>8.2f} tonnes CO₂e')}")
print(f"  ─────────────────────────────────────")
print(f"  NET removal            : {GREEN(f'{net_t:>8.2f} tonnes CO₂')}  "
      f"({net_frac*100:.1f}% net-negative ratio)")

print(f"\n  Net-negative bar:  [{bar(net_frac)}]  {net_frac*100:.1f}%")
print(f"  Target: >85% net-negative for credible permanence claims")

print(f"\n  Emission breakdown (tonnes CO₂e):")
for k, v in s["emission_breakdown_tonnes"].items():
    pct_of_emis = v / emis_t * 100 if emis_t > 0 else 0
    bar_w = round(pct_of_emis / 3)
    print(f"    {k:<24} {v:6.3f} t  ({pct_of_emis:5.1f}%)  "
          f"{'█' * bar_w}")

print(f"\n  ── Costs ──────────────────────────────────────────────────")
print(f"  Total system cost      : ${s['total_cost_usd']:>10,.2f}")
print(f"  Cost per GROSS tonne   : ${s['cost_per_gross_tonne_usd']:>10,.2f}  "
      f"{DIM('(what most DAC vendors report)')}")
print(f"  Cost per NET tonne     : ${s['cost_per_net_tonne_usd']:>10,.2f}  "
      f"{BOLD('← true climate cost')}")

if s['cost_per_net_tonne_usd'] > s['cost_per_gross_tonne_usd'] * 1.5:
    print(f"\n  {YELLOW('⚠  System emissions are inflating the net cost significantly.')}")
    print(f"     Biggest lever: {max(s['emission_breakdown_tonnes'], key=s['emission_breakdown_tonnes'].get).replace('_',' ')}")


# ─────────────────────────────────────────────────────────────────────────────
# 4.  Sorbent degradation report
# ─────────────────────────────────────────────────────────────────────────────

section("④ Sorbent degradation & replacement forecast")

cap_frac = final_sorbent.capacity_fraction
cycles   = final_sorbent.cycle_count

print(f"\n  Cycles completed       : {cycles:,}")
print(f"  Remaining capacity     : {cap_frac*100:.1f}%  [{bar(cap_frac, 20)}]")
print(f"  CO₂ captured lifetime  : {final_sorbent.cumulative_co2_kg/1000:.2f} tonnes")

replace, reason = should_replace_sorbent(final_sorbent, avg_co2_price_usd_per_tonne=200)
status = RED("⚠ REPLACE NOW") if replace else GREEN("✓ OK")
print(f"\n  Replacement verdict    : {status}")
print(f"  Reason                 : {reason}")

# Project forward: at current degradation rate, when does capacity hit 60%?
if cap_frac > 0.60:
    # capacity_fraction after N more cycles ≈ cap_frac * (1 - 0.00045)^N = 0.60
    # N = log(0.60/cap_frac) / log(1-0.00045)
    deg_rate = 0.00045
    n_more = math.log(0.60 / cap_frac) / math.log(1 - deg_rate)
    cycles_per_day = 3
    days_left = n_more / cycles_per_day
    print(f"\n  Projected life left    : ~{int(n_more):,} cycles  (~{int(days_left):,} days  "
          f"/ ~{days_left/365:.1f} years at {cycles_per_day} cycles/day)")
else:
    print(f"\n  {RED('Capacity below 60% floor — replacement overdue.')}")


# ─────────────────────────────────────────────────────────────────────────────
# 5.  Seasonal performance deep-dive (monthly averages)
# ─────────────────────────────────────────────────────────────────────────────

section("⑤ Monthly performance profile")

# Build a month lookup
MONTH_DAYS = [31,28,31,30,31,30,31,31,30,31,30,31]
MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun",
               "Jul","Aug","Sep","Oct","Nov","Dec"]

def day_to_month(day: int) -> int:
    acc = 0
    for i, d in enumerate(MONTH_DAYS):
        acc += d
        if day < acc:
            return i
    return 11

monthly_co2_kg   = defaultdict(float)
monthly_cost_usd = defaultdict(float)
monthly_emis_kg  = defaultdict(float)
monthly_cap_h    = defaultdict(int)

for d, e in zip(decisions, ledger.entries):
    m = day_to_month(d.hour_of_year // 24)
    monthly_co2_kg[m]   += e.gross_co2_kg
    monthly_cost_usd[m] += e.total_cost_usd
    monthly_emis_kg[m]  += e.total_emissions_kg
    if d.mode == "capture":
        monthly_cap_h[m] += 1

print(f"\n  {'Month':>5}  {'Cap.h':>6}  {'Gross t':>8}  {'Emis. t':>8}  {'Net t':>8}  {'$/net t':>8}")
print(f"  {'─'*5}  {'─'*6}  {'─'*8}  {'─'*8}  {'─'*8}  {'─'*8}")
for m in range(12):
    gross = monthly_co2_kg[m]
    emis  = monthly_emis_kg[m]
    net   = gross - emis
    cost  = monthly_cost_usd[m]
    cpt   = (cost / (net / 1000)) if net > 0 else float("inf")
    net_col = GREEN(f"{net/1000:8.3f}") if net > 0 else RED(f"{net/1000:8.3f}")
    print(f"  {MONTH_NAMES[m]:>5}  {monthly_cap_h[m]:>6}  "
          f"{gross/1000:8.3f}  {emis/1000:8.3f}  {net_col}  "
          f"${cpt:7,.0f}")


# ─────────────────────────────────────────────────────────────────────────────
# 6.  Sample 48-hour dispatch window (first week of July)
# ─────────────────────────────────────────────────────────────────────────────

section("⑥ 48-hour dispatch window — first week of July")

july_start = 181 * 24   # hour 0 of July 1
sample = [(d, c) for d, c in zip(decisions, conditions)
          if july_start <= d.hour_of_year < july_start + 48]

MODE_SYM = {"capture": "●", "regen": "☀", "idle": "·", "cleaning": "⚙"}
MODE_COL  = {"capture": CYAN, "regen": YELLOW, "idle": DIM, "cleaning": RED}

print(f"\n  Hr  T°C  SOC%  Mode     CO₂ kg  Fan kWh  Flag")
print(f"  ──  ───  ────  ───────  ──────  ───────  ────")
for d, c in sample:
    sym = MODE_SYM.get(d.mode, "?")
    col = MODE_COL.get(d.mode, lambda x: x)
    flag_str = d.flag if d.flag else ""
    print(
        f"  {d.hour_of_day:02d}  {c.temp_c:4.1f}  "
        f"{d.soc_end*100:4.0f}%  "
        f"{col(f'{sym} {d.mode:<7}')}  "
        f"{d.co2_kg_this_hour:6.1f}  "
        f"{d.fan_kwh:7.1f}  "
        f"{YELLOW(flag_str) if flag_str else ''}"
    )


# ─────────────────────────────────────────────────────────────────────────────
# 7.  Next improvement priorities
# ─────────────────────────────────────────────────────────────────────────────

section("⑦ Top 3 next improvements")

print("""
  1. REPLACE THE GREEDY SCHEDULER WITH A ROLLING-HORIZON MPC
     ─────────────────────────────────────────────────────────
     The current greedy dispatcher evaluates each hour in isolation, so it
     cannot pre-charge the battery before a forecast hot spell or hold off
     regeneration until solar output peaks.  A 24–72 h model-predictive
     control (MPC) loop — trivially solvable as a linear program with
     scipy.optimize.linprog or OR-Tools — would increase net capture by an
     estimated 8–15% purely through better timing, at no additional capital
     cost.  Feed in NOAA hourly forecast data (free via api.weather.gov).

  2. ADD A REAL SORBENT KINETICS MODEL (RATE-BASED, NOT BATCH-AVERAGE)
     ─────────────────────────────────────────────────────────────────
     The current model assigns an average kg CO₂/cycle and scales it by
     temperature and humidity.  A Langmuir-kinetics or LDF (linear driving
     force) model would capture the breakthrough curve correctly: you can
     stop the fans at 80% saturation (higher rate) rather than waiting for
     full saturation, which shortens cycle time by ~25% and increases daily
     cycles.  This also lets you model partial-night captures correctly when
     the battery runs low at 03:00.

  3. CLOSE THE MINERAL CARBONATION LOOP WITH REAL TAILINGS CHEMISTRY
     ─────────────────────────────────────────────────────────────────
     The ledger currently assumes a fixed 2.2 t tailings / t CO₂ ratio and
     15 kg CO₂e / t aggregate for crushing.  In practice, Arizona copper
     tailings vary in Mg/Ca silicate content by mine and depth; some are
     25% reactive, some are 8%.  Replacing the fixed ratio with an assay-
     driven geochemical model (PHREEQC or a simple stoichiometric table
     keyed to mine site) would: (a) sharpen the net-negative accounting so
     it survives third-party verification, and (b) identify the highest-
     reactivity tailings sources to prioritise transport contracts for.
""")

section("Run complete")
print(f"  {GREEN('All numbers are net-negative accounting. No fossil inputs assumed.')}")
print(f"  To switch to geologic storage: pass  pathway='geologic'  to optimize_schedule().")
print()
