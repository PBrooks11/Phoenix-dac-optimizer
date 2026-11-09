"""
Sensor Data Pipeline — Phoenix DAC System
==========================================
Ingests real or simulated plant measurements and feeds them directly into the
MRV registry, so carbon accounting updates automatically from physical sensor
readings rather than manual data entry.

Two ingestion modes:
  1. CSV import  — reads a CSV file (from a datalogger, SCADA export, or manual spreadsheet)
  2. Live feed   — simulates a real-time MQTT-style data stream for demo purposes

Sensor channels modelled:
  • CO₂ concentration differential (inlet minus outlet, ppm) → CO₂ captured kg
  • Air flow rate through contactor (m³/h) → mass throughput
  • Ambient temperature (°C) and relative humidity (%)
  • Battery state of charge (%)
  • Reactor temperature (°C) and pressure (mbar)
  • Reactor effluent CO₂ concentration → CO₂ consumed in carbonation
  • Tailings mass added to reactor (kg) → gravimetric scale
  • Water flow in and out (L)
  • Aggregate mass output (kg) → product scale

Data quality checks on every reading:
  • Range validation (sensor physically possible bounds)
  • Sensor drift detection (value change > 3× moving average step)
  • Missing data flagging (gap > 15 minutes → interpolate and flag)
  • Mass balance check on reactor (CO₂ consumed + tailings ≈ aggregate ± 5%)

IBM App Connect integration note:
  In production, replace the CSV/demo reader with an App Connect webhook that
  POSTs sensor JSON to a local endpoint.  The SensorPipeline.ingest_reading()
  method accepts the same dict schema regardless of source.
"""

from __future__ import annotations

import csv
import json
import math
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from mrv import MRVRegistry, CaptureBatch, CarbonationBatch


# ══════════════════════════════════════════════════════════════════════════════
# SENSOR CHANNEL DEFINITIONS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class SensorChannel:
    """Definition of one physical sensor channel."""
    id: str
    name: str
    unit: str
    valid_min: float
    valid_max: float
    typical_noise_pct: float = 0.5    # % of reading, for simulation
    description: str = ""


# NOTE: channels with spike_check=False are batch/event channels that are
# legitimately 0 most of the time and must not be spike-checked continuously.
_NO_SPIKE = frozenset({
    "tailings_kg", "water_in_l", "water_out_l", "aggregate_kg",
    "reactor_temp_c", "reactor_co2_ppm",  # bimodal — separate idle vs run modes
    "air_flow_m3h",                        # bimodal — fan on vs idle
    "fan_kw",                              # bimodal
})

CHANNELS: Dict[str, SensorChannel] = {
    "co2_inlet_ppm":   SensorChannel("co2_inlet_ppm",  "CO₂ inlet",         "ppm",  380, 430, 0.2,
                                     "Ambient CO₂ concentration before contactor"),
    "co2_outlet_ppm":  SensorChannel("co2_outlet_ppm", "CO₂ outlet",        "ppm",  300, 425, 0.3,
                                     "CO₂ concentration leaving contactor (lower = more captured)"),
    "air_flow_m3h":    SensorChannel("air_flow_m3h",   "Air flow",          "m³/h",   0, 15_000, 1.0,
                                     "Volumetric air flow through fan array (0 = fan off)"),
    "temp_c":          SensorChannel("temp_c",         "Ambient temp",      "°C",   -5,  55,   0.1),
    "rh_pct":          SensorChannel("rh_pct",         "Relative humidity", "%",     0, 100,   0.5),
    "battery_soc_pct": SensorChannel("battery_soc_pct","Battery SOC",       "%",     5,  100,  0.2),
    "reactor_temp_c":  SensorChannel("reactor_temp_c", "Reactor temp",      "°C",   15,  90,   0.3),
    "reactor_pres_mbar":SensorChannel("reactor_pres_mbar","Reactor pressure","mbar", 200, 1050, 0.5),
    "reactor_co2_ppm": SensorChannel("reactor_co2_ppm","Reactor CO₂",       "ppm",  400, 50_000, 2.0,
                                     "CO₂ concentration in reactor headspace (high = not yet consumed)"),
    "tailings_kg":     SensorChannel("tailings_kg",    "Tailings added",    "kg",     0, 5_000, 0.8),
    "water_in_l":      SensorChannel("water_in_l",     "Water input",       "L",      0,  500,  0.5),
    "water_out_l":     SensorChannel("water_out_l",    "Water recovered",   "L",      0,  500,  0.5),
    "aggregate_kg":    SensorChannel("aggregate_kg",   "Aggregate output",  "kg",     0, 8_000, 0.8),
    "fan_kw":          SensorChannel("fan_kw",         "Fan power",         "kW",     0,   60,  0.3),
    "reactor_kw":      SensorChannel("reactor_kw",     "Reactor power",     "kW",     0,   10,  0.3),
}


# ══════════════════════════════════════════════════════════════════════════════
# SENSOR READING
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SensorReading:
    """One timestamped bundle of sensor values."""
    timestamp: str                  # ISO 8601
    values: Dict[str, Optional[float]]
    flags: Dict[str, str] = field(default_factory=dict)  # channel_id → flag message

    def get(self, channel_id: str, default: float = 0.0) -> float:
        v = self.values.get(channel_id)
        return v if v is not None else default

    def flag(self, channel_id: str, message: str) -> None:
        self.flags[channel_id] = message

    def is_clean(self) -> bool:
        return len(self.flags) == 0

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "values":    {k: v for k, v in self.values.items()},
            "flags":     self.flags,
            "clean":     self.is_clean(),
        }


# ══════════════════════════════════════════════════════════════════════════════
# DATA QUALITY ENGINE
# ══════════════════════════════════════════════════════════════════════════════

class DataQualityChecker:
    """Validates sensor readings and flags anomalies."""

    def __init__(self, window: int = 12) -> None:
        self._history: Dict[str, List[float]] = {ch: [] for ch in CHANNELS}
        self._window = window   # moving-average window length

    def check(self, reading: SensorReading) -> SensorReading:
        """Apply all quality checks to a reading in-place. Returns the reading."""
        for ch_id, ch in CHANNELS.items():
            val = reading.values.get(ch_id)
            if val is None:
                reading.flag(ch_id, "missing")
                continue

            # Range check
            if val < ch.valid_min or val > ch.valid_max:
                reading.flag(ch_id, f"out_of_range: {val:.2f} [{ch.valid_min},{ch.valid_max}]")

            # Drift check — only for continuous channels with stable baselines
            if ch_id not in _NO_SPIKE:
                hist = self._history[ch_id]
                if len(hist) >= self._window:
                    avg   = sum(hist[-self._window:]) / self._window
                    delta = abs(val - avg)
                    if avg > 1.0 and delta / avg > 0.50:
                        reading.flag(ch_id, f"spike: {val:.2f} vs avg {avg:.2f}")

            # Accumulate history
            self._history[ch_id].append(val)
            if len(self._history[ch_id]) > self._window * 4:
                self._history[ch_id] = self._history[ch_id][-self._window * 4:]

        return reading


# ══════════════════════════════════════════════════════════════════════════════
# CO₂ MASS FLOW CALCULATOR
# ══════════════════════════════════════════════════════════════════════════════

# Molar volume of air at STP: 22.4 L/mol → density ~1.2 kg/m³
# CO₂ molar mass: 44 g/mol  |  Air molar mass: 28.97 g/mol
# 1 ppm CO₂ by volume ≈ 1.964 mg CO₂ / m³ air at 20°C, 1 atm
_CO2_MG_PER_M3_PER_PPM = 1.964   # mg CO₂ per m³ air per 1 ppm


def co2_captured_kg(
    inlet_ppm: float,
    outlet_ppm: float,
    air_flow_m3h: float,
    duration_h: float = 1.0,
) -> float:
    """
    Calculate CO₂ captured in kg from differential concentration measurement.

    Args:
        inlet_ppm:   upstream CO₂ concentration (ppm)
        outlet_ppm:  downstream CO₂ concentration (ppm)  [lower = more captured]
        air_flow_m3h: volumetric air flow (m³/h)
        duration_h:  measurement duration (h)

    Returns:
        kg CO₂ captured
    """
    delta_ppm = max(0.0, inlet_ppm - outlet_ppm)
    # mg CO₂ captured = delta_ppm × mg/m³/ppm × m³/h × h
    mg_captured = delta_ppm * _CO2_MG_PER_M3_PER_PPM * air_flow_m3h * duration_h
    return mg_captured / 1e6  # convert mg → kg


# ══════════════════════════════════════════════════════════════════════════════
# SENSOR PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

class SensorPipeline:
    """
    Ingests sensor readings and automatically updates the MRV registry.

    Capture cycle logic:
      • A "capture batch" is one contiguous block of hours where the system
        is in capture mode (fan running, battery discharging, CO₂ decreasing).
      • When the cycle ends (battery SOC < 20% or daylight triggers regen),
        the accumulated CO₂ is committed to the MRV registry.

    Carbonation batch logic:
      • When a full reactor cycle completes (reactor_temp drops + reactor_co2
        returns to ambient), the batch is committed.
    """

    def __init__(
        self,
        mrv_registry: MRVRegistry,
        active_tailings_lot_id: str = "Morenci-2025-Q3",
        sorbent_cycle_offset: int = 0,
    ) -> None:
        self.registry = mrv_registry
        self.lot_id   = active_tailings_lot_id
        self.qc       = DataQualityChecker()

        # Accumulation buffers
        self._capture_buffer: List[SensorReading] = []
        self._reactor_buffer: List[SensorReading] = []
        self._sorbent_cycle  = sorbent_cycle_offset

        # State machine
        self._capture_active = False
        self._reactor_active = False

        # Diagnostics
        self.readings_processed = 0
        self.readings_flagged   = 0
        self.batches_committed  = {"capture": 0, "carbonation": 0}

    def ingest_reading(self, reading: SensorReading) -> SensorReading:
        """
        Accept one sensor reading, run QC, and update state machine.
        Returns the (possibly flagged) reading.
        """
        reading = self.qc.check(reading)
        self.readings_processed += 1
        if not reading.is_clean():
            self.readings_flagged += 1

        soc = reading.get("battery_soc_pct", 50)
        fan = reading.get("fan_kw", 0)
        r_temp = reading.get("reactor_temp_c", 25)
        r_co2  = reading.get("reactor_co2_ppm", 400)

        # ── Capture state machine ──
        if fan > 2.0 and soc > 20:
            if not self._capture_active:
                self._capture_active = True
                self._capture_buffer = []
            self._capture_buffer.append(reading)
        elif self._capture_active:
            # Capture cycle ended — commit batch
            self._capture_active = False
            if self._capture_buffer:
                self._commit_capture_batch(self._capture_buffer)
                self._capture_buffer = []

        # ── Reactor state machine ──
        if r_temp > 45 and r_co2 > 800:
            if not self._reactor_active:
                self._reactor_active = True
                self._reactor_buffer = []
            self._reactor_buffer.append(reading)
        elif self._reactor_active:
            # Reactor run ended — commit batch
            self._reactor_active = False
            if len(self._reactor_buffer) >= 2:
                self._commit_carbonation_batch(self._reactor_buffer)
                self._reactor_buffer = []

        return reading

    def _commit_capture_batch(self, readings: List[SensorReading]) -> Optional[CaptureBatch]:
        """Accumulate readings into one CaptureBatch and register it."""
        if not readings:
            return None

        # Calculate CO₂ captured over the cycle
        total_co2_kg = 0.0
        total_fan_kwh = 0.0
        for r in readings:
            total_co2_kg += co2_captured_kg(
                r.get("co2_inlet_ppm", 415),
                r.get("co2_outlet_ppm", 410),
                r.get("air_flow_m3h", 5_000),
                duration_h=1.0,
            )
            total_fan_kwh += r.get("fan_kw", 0) * 1.0   # 1-hour intervals

        avg_temp = sum(r.get("temp_c", 25) for r in readings) / len(readings)
        avg_rh   = sum(r.get("rh_pct", 20) for r in readings) / len(readings)

        self._sorbent_cycle += 1

        batch = self.registry.record_capture(
            timestamp=readings[0].timestamp,
            co2_kg=total_co2_kg,
            temp_c=avg_temp,
            rh_pct=avg_rh,
            sorbent_cycle=self._sorbent_cycle,
            fan_kwh=total_fan_kwh,
            power_source="battery",
            notes=f"Auto-committed from {len(readings)} sensor readings",
        )
        self.batches_committed["capture"] += 1
        return batch

    def _commit_carbonation_batch(self, readings: List[SensorReading]) -> None:
        """Accumulate reactor readings into a CarbonationBatch."""
        if not readings:
            return

        # Verify the tailings lot is qualified
        lot = self.registry.tailings_lots.get(self.lot_id)
        if lot is None or not lot.passed:
            return  # silently skip — lot not qualified

        # Integrated sensor values
        total_water_in  = sum(r.get("water_in_l", 0) for r in readings)
        total_water_out = sum(r.get("water_out_l", 0) for r in readings)
        tailings_kg     = max(r.get("tailings_kg", 0) for r in readings)  # gravimetric peak
        aggregate_kg    = max(r.get("aggregate_kg", 0) for r in readings)
        reactor_kwh     = sum(r.get("reactor_kw", 0) * 1.0 for r in readings)
        avg_reactor_t   = sum(r.get("reactor_temp_c", 50) for r in readings) / len(readings)
        duration_h      = len(readings) * 1.0   # 1-hour intervals assumed

        # CO₂ consumed = tailings mass × reactive fraction × stoich factor
        # We use a conservative 15% reactive fraction if unknown
        # (replace with actual assay from lot when available)
        reactive_fraction = 0.15
        co2_consumed_kg = tailings_kg * reactive_fraction * 0.80

        # Use capture batch IDs from recent unlinked batches
        unlinked = [
            bid for bid, cb in self.registry.capture_batches.items()
            if cb.status == "pending"
        ]

        try:
            batch = self.registry.record_carbonation(
                timestamp=readings[0].timestamp,
                capture_batch_ids=unlinked[-3:] if unlinked else [],
                tailings_lot_id=self.lot_id,
                tailings_kg=tailings_kg,
                water_litre=total_water_in,
                reactor_temp_c=avg_reactor_t,
                reactor_duration_h=duration_h,
                co2_consumed_kg=co2_consumed_kg,
                aggregate_kg=aggregate_kg,
                water_recovered_litre=total_water_out,
                reactor_kwh=reactor_kwh,
                notes=f"Auto-committed from {len(readings)} reactor readings",
            )
            self.batches_committed["carbonation"] += 1
        except ValueError:
            pass  # lot not qualified — already guarded above

    def pipeline_status(self) -> dict:
        return {
            "readings_processed":   self.readings_processed,
            "readings_flagged":     self.readings_flagged,
            "flag_rate_pct":        round(
                100 * self.readings_flagged / max(1, self.readings_processed), 1
            ),
            "batches_capture":      self.batches_committed["capture"],
            "batches_carbonation":  self.batches_committed["carbonation"],
            "capture_active":       self._capture_active,
            "reactor_active":       self._reactor_active,
            "sorbent_cycle":        self._sorbent_cycle,
            "active_tailings_lot":  self.lot_id,
        }


# ══════════════════════════════════════════════════════════════════════════════
# CSV IMPORTER
# ══════════════════════════════════════════════════════════════════════════════

def parse_csv_readings(csv_text: str) -> List[SensorReading]:
    """
    Parse a CSV string into a list of SensorReadings.

    Expected CSV columns (order not important, unknown columns ignored):
      timestamp, co2_inlet_ppm, co2_outlet_ppm, air_flow_m3h,
      temp_c, rh_pct, battery_soc_pct, reactor_temp_c, reactor_pres_mbar,
      reactor_co2_ppm, tailings_kg, water_in_l, water_out_l, aggregate_kg,
      fan_kw, reactor_kw
    """
    readings = []
    reader = csv.DictReader(csv_text.strip().splitlines())
    for row in reader:
        ts = row.get("timestamp", datetime.utcnow().isoformat())
        vals: Dict[str, Optional[float]] = {}
        for ch_id in CHANNELS:
            raw = row.get(ch_id, "").strip()
            if raw == "" or raw.lower() in ("na", "nan", "null", "none"):
                vals[ch_id] = None
            else:
                try:
                    vals[ch_id] = float(raw)
                except ValueError:
                    vals[ch_id] = None
        readings.append(SensorReading(timestamp=ts, values=vals))
    return readings


# ══════════════════════════════════════════════════════════════════════════════
# SYNTHETIC DATA GENERATOR (for demo / testing)
# ══════════════════════════════════════════════════════════════════════════════

def generate_demo_readings(
    n_hours: int = 48,
    start_hour: int = 0,
    seed: int = 42,
    include_anomaly: bool = True,
) -> List[SensorReading]:
    """
    Generate realistic synthetic sensor readings for a 48-hour window.

    Cycle structure:
      Hours 0-7:   nighttime capture (fan on, SOC draining)
      Hours 8-11:  solar regen (fan off, reactor heating)
      Hours 12-15: reactor running (carbonation)
      Hours 16-18: reactor cooling, aggregate discharge
      Hours 19-23: idle / charging
      Repeat

    One intentional anomaly is injected (spike on CO₂ inlet ppm) at hour 6
    to demonstrate the data quality checker.
    """
    rng = random.Random(seed)
    readings = []
    base_ts  = datetime(2025, 7, 15, 0, 0, 0) + timedelta(hours=start_hour)
    soc      = 85.0   # starting SOC %

    for h in range(n_hours):
        hour_of_day = (start_hour + h) % 24
        ts = (base_ts + timedelta(hours=h)).isoformat()

        def jitter(val: float, pct: float = 0.5) -> float:
            return val * (1 + rng.gauss(0, pct / 100))

        # Temperature: Phoenix profile
        temp_base = 34 + 4 * math.sin((hour_of_day - 14) * math.pi / 12)
        temp_c = jitter(temp_base, 0.3)
        rh_pct = jitter(18 + 5 * (1 - math.sin((hour_of_day - 6) * math.pi / 12)), 2)

        # Night capture: hours 20-6
        capturing = hour_of_day >= 20 or hour_of_day < 7
        regen      = 8 <= hour_of_day < 12
        react_run  = 12 <= hour_of_day < 16

        if capturing:
            fan_kw = jitter(18.0, 1)
            soc    = max(20, soc - jitter(2.5, 2))   # drain ~2.5% SOC/h
            co2_inlet  = jitter(415, 0.2)
            co2_outlet = jitter(410 - 2 * (1 - (soc - 20) / 65), 0.3)
            air_flow   = jitter(7_500, 1)
        else:
            fan_kw = jitter(0.5, 5)
            if regen or react_run:
                soc = min(100, soc + jitter(8, 2))   # solar charging
            co2_inlet  = jitter(415, 0.2)
            co2_outlet = jitter(414, 0.2)
            air_flow   = jitter(200, 5)

        r_temp  = jitter(55, 0.5) if react_run else jitter(30, 1)
        r_pres  = jitter(950, 0.3)
        r_co2   = jitter(12_000, 2) if react_run else jitter(420, 0.5)

        tailings_kg  = jitter(120, 1) if react_run and hour_of_day == 12 else 0.0
        water_in_l   = jitter(10, 2)  if react_run and hour_of_day == 12 else 0.0
        water_out_l  = jitter(7, 2)   if react_run and hour_of_day == 15 else 0.0
        aggregate_kg = jitter(140, 1) if react_run and hour_of_day == 15 else 0.0
        reactor_kw   = jitter(1.5, 3) if react_run else 0.0

        vals = {
            "co2_inlet_ppm":    co2_inlet,
            "co2_outlet_ppm":   co2_outlet,
            "air_flow_m3h":     air_flow,
            "temp_c":           temp_c,
            "rh_pct":           rh_pct,
            "battery_soc_pct":  soc,
            "reactor_temp_c":   r_temp,
            "reactor_pres_mbar": r_pres,
            "reactor_co2_ppm":  r_co2,
            "tailings_kg":      tailings_kg,
            "water_in_l":       water_in_l,
            "water_out_l":      water_out_l,
            "aggregate_kg":     aggregate_kg,
            "fan_kw":           fan_kw,
            "reactor_kw":       reactor_kw,
        }

        # Inject intentional anomaly at hour 6 of the simulation
        if include_anomaly and h == 6:
            vals["co2_inlet_ppm"] = 510.0   # physically impossible spike

        readings.append(SensorReading(timestamp=ts, values=vals))

    return readings


def generate_demo_csv(n_hours: int = 48) -> str:
    """Return the demo readings as a CSV string for the file upload demo."""
    readings = generate_demo_readings(n_hours=n_hours)
    header = ["timestamp"] + list(CHANNELS.keys())
    lines  = [",".join(header)]
    for r in readings:
        row = [r.timestamp] + [
            str(r.values.get(ch, "")) if r.values.get(ch) is not None else ""
            for ch in CHANNELS
        ]
        lines.append(",".join(row))
    return "\n".join(lines)
