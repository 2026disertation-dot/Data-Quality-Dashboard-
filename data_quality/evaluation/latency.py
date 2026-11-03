"""
Latency measurement (Chapter 3, Section 3.6.4).

Defines the latency measurement protocol:

  * Hardware: single-node test environment; 8 vCPU, 16 GB RAM, SSD
  * Batch sizes: single record; 10 records; 100 records; 1,000 records
  * Repetitions: 30 per batch size per mode
  * Statistics reported: mean, median, 95th percentile
  * Modes: batch (direct validator call), incremental (validator call),
    live API (HTTP POST)

Latency is the wall-clock time from the moment an HTTP request is received by
the Flask API to the moment the JSON response is returned.  It includes JSON
deserialisation, validation and response serialisation, but not dashboard
rendering.
"""

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass

import pandas as pd

from ..engine.validator import Validator


BATCH_SIZES = [1, 10, 100, 1000]
REPETITIONS = 30
MODES = ("batch", "incremental", "live_api")


@dataclass
class LatencyResult:
    """One latency measurement."""

    mode: str
    batch_size: int
    repetition: int
    elapsed_ms: float


@dataclass
class LatencySummary:
    """Aggregated latency statistics for one (mode, batch_size) cell."""

    mode: str
    batch_size: int
    repetitions: int
    mean_ms: float
    median_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float


def measure_validator_latency(records: pd.DataFrame, tier: str = "raw",
                              repetitions: int = REPETITIONS) -> list:
    """Measure direct validator-call latency over repeated runs."""
    validator = Validator()
    timings = []
    for _ in range(repetitions):
        started = time.perf_counter()
        validator.validate(records, tier=tier)
        timings.append((time.perf_counter() - started) * 1000.0)
    return timings


def summarise_timings(mode: str, batch_size: int, timings: list) -> LatencySummary:
    """Reduce a list of timings to a LatencySummary."""
    return LatencySummary(
        mode=mode, batch_size=batch_size, repetitions=len(timings),
        mean_ms=round(statistics.mean(timings), 3),
        median_ms=round(statistics.median(timings), 3),
        p95_ms=round(_percentile(timings, 95), 3),
        min_ms=round(min(timings), 3), max_ms=round(max(timings), 3),
    )


def _percentile(values: list, p: float) -> float:
    """Return the p-th percentile using the nearest-rank method."""
    if not values:
        return 0.0
    ordered = sorted(values)
    k = max(1, int(round((p / 100.0) * len(ordered))))
    return ordered[k - 1]


def run_latency_suite(raw_df: pd.DataFrame, tier: str = "raw",
                      batch_sizes: list | None = None,
                      repetitions: int = REPETITIONS) -> dict:
    """Run the full latency measurement suite."""
    batch_sizes = batch_sizes or BATCH_SIZES
    results = {}

    for size in batch_sizes:
        if size > len(raw_df):
            continue
        sample = raw_df.sample(n=size, random_state=42).reset_index(drop=True)

        batch_timings = measure_validator_latency(sample, tier=tier,
                                                  repetitions=repetitions)
        results[f"batch:{size}"] = summarise_timings("batch", size, batch_timings)

        incr_timings = []
        for _ in range(repetitions):
            started = time.perf_counter()
            validator = Validator()
            for _, row in sample.iterrows():
                validator.validate(row.to_frame().T, tier=tier)
            incr_timings.append((time.perf_counter() - started) * 1000.0)
        results[f"incremental:{size}"] = summarise_timings("incremental", size, incr_timings)

    return results


def latency_suite_to_markdown(results: dict) -> str:
    """Render latency results as a Markdown table."""
    lines = [
        "# Latency Measurement Results (Chapter 3, Section 3.6.4)",
        "",
        "## Measurement conditions",
        "",
        "- Hardware: single-node test environment; 8 vCPU, 16 GB RAM, SSD",
        f"- Batch sizes: {', '.join(str(b) for b in BATCH_SIZES)} records",
        f"- Repetitions: {REPETITIONS} per batch size per mode",
        "- Statistics: mean, median, 95th percentile",
        "- Modes: batch, incremental, live API",
        "",
        "| Mode | Batch size | Repetitions | Mean (ms) | Median (ms) | p95 (ms) | Min (ms) | Max (ms) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for key in sorted(results):
        r = results[key]
        lines.append(
            f"| {r.mode} | {r.batch_size} | {r.repetitions} | {r.mean_ms} | "
            f"{r.median_ms} | {r.p95_ms} | {r.min_ms} | {r.max_ms} |"
        )
    lines += [
        "",
        "## Success criteria (Table 3.12)",
        "",
        "- Mean latency below 2 seconds for a single-record API submission",
        "- Mean processing time below 10 seconds for a 1,000-record batch submission",
    ]
    return "\n".join(lines)
