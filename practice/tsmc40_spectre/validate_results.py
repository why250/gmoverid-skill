#!/usr/bin/env python3
"""Validate a profile result directory produced by run_tsmc40.py."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import re
import sys
from typing import Iterable


NUMERIC_FIELDS = (
    "vgs_v",
    "vds_v",
    "id_a",
    "gm_s",
    "gds_s",
    "cgg_f",
    "cgd_f",
    "cgs_f",
    "vth_v",
    "vdsat_v",
    "gm_id_per_v",
    "gm_ro",
    "ft_hz",
    "id_w_a_per_m",
)


def close_enough(actual: float, expected: float, scale: float = 1.0) -> bool:
    return math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12 * scale)


def read_numeric_csv(path: Path) -> list[dict[str, float]]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = set(NUMERIC_FIELDS).difference(reader.fieldnames or ())
        if missing:
            raise ValueError(f"{path}: missing columns: {', '.join(sorted(missing))}")
        rows = [{field: float(row[field]) for field in NUMERIC_FIELDS} for row in reader]
    if not rows:
        raise ValueError(f"{path}: no data rows")
    return rows


def count_csv_rows(path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as handle:
        return sum(1 for _ in csv.DictReader(handle))


def nondecreasing(values: Iterable[float], rel_tol: float = 1e-10) -> bool:
    sequence = list(values)
    return all(current >= previous * (1.0 - rel_tol) for previous, current in zip(sequence, sequence[1:]))


def nonincreasing(values: Iterable[float], rel_tol: float = 1e-6) -> bool:
    sequence = list(values)
    return all(current <= previous * (1.0 + rel_tol) for previous, current in zip(sequence, sequence[1:]))


def validate_curve(
    path: Path,
    expected_points: int,
    sweep: dict[str, float],
    configured_vds: tuple[float, ...],
    gmid_min: float,
    gmid_max: float,
) -> str:
    rows = read_numeric_csv(path)
    if len(rows) != expected_points:
        raise ValueError(f"{path}: expected {expected_points} rows, found {len(rows)}")
    if not all(math.isfinite(value) for row in rows for value in row.values()):
        raise ValueError(f"{path}: contains a non-finite value")

    vgs = [row["vgs_v"] for row in rows]
    if not close_enough(vgs[0], sweep["start"]):
        raise ValueError(f"{path}: unexpected VGS start {vgs[0]}")
    if not close_enough(vgs[-1], sweep["stop"]):
        raise ValueError(f"{path}: unexpected VGS stop {vgs[-1]}")
    if any(
        not close_enough(current - previous, sweep["step"], scale=sweep["step"])
        for previous, current in zip(vgs, vgs[1:])
    ):
        raise ValueError(f"{path}: VGS spacing does not match summary.json")

    curve_vds = rows[0]["vds_v"]
    if not any(close_enough(curve_vds, value) for value in configured_vds):
        raise ValueError(f"{path}: VDS {curve_vds} is absent from summary.json")
    if any(not close_enough(row["vds_v"], curve_vds) for row in rows):
        raise ValueError(f"{path}: VDS is not constant")
    if not nondecreasing(row["id_a"] for row in rows):
        raise ValueError(f"{path}: ID is not monotonic with VGS")

    peak_index = max(range(len(rows)), key=lambda index: rows[index]["gm_id_per_v"])
    useful = [
        row["gm_id_per_v"]
        for row in rows[peak_index:]
        if gmid_min <= row["gm_id_per_v"] <= gmid_max
    ]
    if len(useful) < 5:
        raise ValueError(f"{path}: fewer than five points in the gm/ID validation window")
    if not nonincreasing(useful):
        raise ValueError(f"{path}: gm/ID falling branch is not monotonic")

    return (
        f"{path.name}: rows={len(rows)}, VDS={curve_vds:g} V, "
        f"gm/ID=[{min(useful):.2f}, {max(useful):.2f}]"
    )


def validate_result_dir(result_dir: Path, gmid_min: float, gmid_max: float) -> list[str]:
    summary_path = result_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    required = ("profile", "models", "vds_v", "vgs_sweep_v", "points_per_curve")
    missing = [key for key in required if key not in summary]
    if missing:
        raise ValueError(f"{summary_path}: missing keys: {', '.join(missing)}")

    models = tuple(str(value) for value in summary["models"])
    vds_values = tuple(float(value) for value in summary["vds_v"])
    expected_curves = len(models) * len(vds_values)
    expected_points = int(summary["points_per_curve"])
    csv_dir = result_dir / "csv"
    curve_files = sorted(csv_dir.glob("tsmc40_*_vds_*.csv"))
    if len(curve_files) != expected_curves:
        raise ValueError(
            f"{csv_dir}: expected {expected_curves} curve files, found {len(curve_files)}"
        )

    messages = [
        validate_curve(
            path,
            expected_points,
            summary["vgs_sweep_v"],
            vds_values,
            gmid_min,
            gmid_max,
        )
        for path in curve_files
    ]

    combined = csv_dir / "tsmc40_gmid_all.csv"
    combined_rows = count_csv_rows(combined)
    expected_rows = expected_curves * expected_points
    if combined_rows != expected_rows:
        raise ValueError(f"{combined}: expected {expected_rows} rows, found {combined_rows}")

    log_path = result_dir / "raw" / "spectre.log"
    log = log_path.read_text(encoding="utf-8", errors="replace")
    completion = re.search(r"spectre completes with (\d+) errors?", log)
    if completion is None or int(completion.group(1)) != 0:
        raise ValueError(f"{log_path}: zero-error Spectre completion was not found")

    for model in models:
        svg = result_dir / "plots" / f"tsmc40_{model}_gmid.svg"
        if not svg.is_file() or svg.stat().st_size == 0:
            raise ValueError(f"{svg}: missing or empty plot")

    messages.append(f"combined rows={combined_rows}")
    messages.append(f"Spectre errors=0; profile={summary['profile']}")
    return messages


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result_dir", type=Path, help="results/<profile> directory")
    parser.add_argument("--gmid-min", type=float, default=2.0)
    parser.add_argument("--gmid-max", type=float, default=25.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.gmid_min <= 0.0 or args.gmid_max <= args.gmid_min:
        raise ValueError("gm/ID limits must satisfy 0 < min < max")
    result_dir = args.result_dir.resolve()
    for message in validate_result_dir(result_dir, args.gmid_min, args.gmid_max):
        print(f"PASS {message}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
