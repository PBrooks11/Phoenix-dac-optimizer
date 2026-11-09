"""
Phoenix, Arizona — synthetic but realistic hourly weather data.

Sources for parameter values:
  - Phoenix July mean daily high: ~42 °C (108 °F), mean nightly low: ~31 °C (88 °F)
  - Phoenix annual GHI ≈ 6.5 kWh/m²/day (NREL)
  - Phoenix relative humidity July: 20–40 %
  - Dust events roughly 2–3 haboob days/month in monsoon season (July–August)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List

HOURS_PER_DAY = 24

@dataclass
class HourlyCondition:
    hour_of_year: int      # 0-based
    day: int               # 0-based day of year
    hour_of_day: int       # 0 – 23
    temp_c: float          # ambient dry-bulb temperature (°C)
    rh_pct: float          # relative humidity (%)
    ghi_w_m2: float        # global horizontal irradiance (W/m²)
    wind_m_s: float        # wind speed (m/s)
    dust_factor: float     # 1.0 = clean, >1 means extra filter pressure drop (dimensionless)
    solar_pv_avail_kw: float   # available solar PV output (kW) for a notional 50 kW array
    elec_price_usd_kwh: float  # marginal electricity cost (shadow price of battery discharge)


def _diurnal(hour: int, peak_hour: float, amplitude: float, base: float, phase_spread: float = 6.0) -> float:
    """Smooth diurnal cosine cycle."""
    angle = math.pi * (hour - peak_hour) / phase_spread
    return base + amplitude * math.cos(angle) if abs(hour - peak_hour) <= phase_spread else base - amplitude


def generate_phoenix_year(
    seed: int = 42,
    array_kw_peak: float = 50.0,
    days: int = 365,
) -> List[HourlyCondition]:
    """
    Return a list of HourlyCondition for every hour of a synthetic Phoenix year.
    Seasonal variation is modelled; July–August monsoon humidity spikes and
    haboob dust events are included.
    """
    rng = random.Random(seed)
    conditions: List[HourlyCondition] = []

    for day in range(days):
        # ---- Seasonal parameters (day 0 = Jan 1) --------------------------------
        day_of_year = day + 1
        # Hottest around day 196 (mid-July), coolest around day 15 (mid-Jan)
        # season_angle = 0 at peak heat, π at peak cold
        season_angle = 2 * math.pi * (day_of_year - 196) / 365

        # Daily peak / trough temperatures (°C)
        # cos(0) = 1 → July peak = 38 + 8 = 46 °C  (slightly above observed ~42; diurnal trough pulls avg down)
        # cos(π) = -1 → Jan peak = 38 - 8 = 30 °C  (close to observed ~18 °C high in Phoenix Jan? No, too high)
        # Phoenix Jan mean high ~18°C, mean low ~5°C; July mean high ~42°C, mean low ~30°C
        # Use amplitude 12 to span 18–42: base=30, amp=12
        t_peak   = 30 + 12 * math.cos(season_angle)    # Jul≈42, Jan≈18
        t_trough = t_peak - 13                          # diurnal swing ≈ 13 °C

        # Monsoon: elevated humidity July 1 (day 181) – Sep 15 (day 258)
        monsoon = 181 <= day_of_year <= 258
        rh_base = 30 if monsoon else 12
        rh_swing = 18 if monsoon else 6

        # Haboob dust event: ~1 in 20 monsoon days; lasts ~3 hours
        dust_event_hour = -1
        if monsoon and rng.random() < 0.05:
            dust_event_hour = rng.randint(17, 21)   # late afternoon / early evening

        # Daylight hours: Phoenix ranges ~10 h (Dec) to ~14 h (Jun)
        # Longest days at summer solstice (day ~172), cos(season_angle) largest near July → ~14 h
        daylight_h = 12 + 2 * math.cos(season_angle)

        # ---- Hourly loop --------------------------------------------------------
        for h in range(HOURS_PER_DAY):
            # Temperature: peak ~15:00, trough ~05:00
            if 5 <= h <= 15:
                frac = (h - 5) / 10
                temp = t_trough + (t_peak - t_trough) * math.sin(math.pi * frac)
            else:
                # Cooling from peak to trough
                if h > 15:
                    cooling_h = h - 15
                else:
                    cooling_h = h + (24 - 15)
                temp = t_peak - (t_peak - t_trough) * (cooling_h / 14)
            temp += rng.gauss(0, 0.6)  # small random noise

            # Relative humidity: highest at night/dawn
            rh_phase = rh_base + rh_swing * math.cos(math.pi * (h - 6) / 9) if 0 <= h <= 15 else rh_base
            rh = max(5.0, min(80.0, rh_phase + rng.gauss(0, 3)))

            # Solar irradiance: simple clear-sky with cloud noise
            solar_start = 12 - daylight_h / 2
            solar_end   = 12 + daylight_h / 2
            if solar_start <= h < solar_end:
                solar_frac = (h - solar_start) / daylight_h
                ghi = 900 * math.sin(math.pi * solar_frac) * rng.uniform(0.85, 1.0)
                # Monsoon clouds attenuate by up to 30 %
                if monsoon:
                    ghi *= rng.uniform(0.70, 1.0)
            else:
                ghi = 0.0

            # PV output (simple linear efficiency model, degrades at high temperature)
            pv_eff = max(0.0, 1.0 - 0.004 * max(0, temp - 25))   # -0.4 %/°C above 25°C
            pv_kw = array_kw_peak * (ghi / 1000) * pv_eff

            # Dust factor
            if dust_event_hour >= 0 and abs(h - dust_event_hour) <= 1:
                dust = rng.uniform(1.8, 3.0)   # severe filter fouling
            elif monsoon:
                dust = rng.uniform(1.0, 1.25)
            else:
                dust = rng.uniform(1.0, 1.08)

            # Electricity shadow price (battery discharge cost)
            # Cheap when sun is up, expensive at night (battery wear)
            if ghi > 50:
                price = rng.uniform(0.01, 0.04)   # near-zero marginal solar cost
            else:
                price = rng.uniform(0.05, 0.14)   # battery discharge cost

            conditions.append(HourlyCondition(
                hour_of_year=day * 24 + h,
                day=day,
                hour_of_day=h,
                temp_c=round(temp, 2),
                rh_pct=round(rh, 1),
                ghi_w_m2=round(ghi, 1),
                wind_m_s=round(rng.uniform(1.5, 5.5), 1),
                dust_factor=round(dust, 3),
                solar_pv_avail_kw=round(pv_kw, 2),
                elec_price_usd_kwh=round(price, 4),
            ))

    return conditions
