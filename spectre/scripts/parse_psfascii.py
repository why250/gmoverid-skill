#!/usr/bin/env python3
"""Convert a simple one-dimensional Spectre PSFASCII sweep to CSV."""

from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from pathlib import Path


VALUE_RE = re.compile(
    r'^"(?P<name>[^"]+)"\s+'
    r'(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)$'
)


def parse_signal(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("signal must use COLUMN=PSF_TRACE syntax")
    column, trace = value.split("=", 1)
    column = column.strip()
    trace = trace.strip()
    if not column or not trace:
        raise argparse.ArgumentTypeError("signal column and PSF trace must be non-empty")
    return column, trace


def read_sweep(path: Path, sweep: str) -> list[dict[str, float]]:
    rows: list[dict[str, float]] = []
    current: dict[str, float] | None = None
    in_values = False

    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line == "VALUE":
                in_values = True
                continue
            if not in_values:
                continue
            if line == "END":
                break
            match = VALUE_RE.match(line)
            if not match:
                continue
            name = match.group("name")
            value = float(match.group("value"))
            if name == sweep:
                if current is not None:
                    rows.append(current)
                current = {sweep: value}
            elif current is not None:
                current[name] = value

    if current is not None:
        rows.append(current)
    if not rows:
        raise ValueError(f"no values found for sweep {sweep!r} in {path}")
    return rows


def convert(
    input_path: Path,
    output_path: Path | None,
    sweep: str,
    signals: list[tuple[str, str]],
    absolute: set[str],
    expected_points: int | None,
) -> int:
    aliases = [column for column, _trace in signals]
    traces = [trace for _column, trace in signals]
    if len(set(aliases)) != len(aliases):
        raise ValueError("signal column aliases must be unique")
    if len(set(traces)) != len(traces):
        raise ValueError("PSF trace selections must be unique")
    unknown_absolute = absolute.difference(aliases)
    if unknown_absolute:
        raise ValueError(f"--absolute names unknown columns: {sorted(unknown_absolute)}")

    raw_rows = read_sweep(input_path, sweep)
    if expected_points is not None and len(raw_rows) != expected_points:
        raise ValueError(
            f"expected {expected_points} points, found {len(raw_rows)} in {input_path}"
        )

    target = sys.stdout if output_path is None else output_path.open("w", newline="", encoding="utf-8")
    try:
        writer = csv.DictWriter(target, fieldnames=[sweep, *aliases])
        writer.writeheader()
        for index, raw in enumerate(raw_rows):
            result: dict[str, float] = {sweep: raw[sweep]}
            for column, trace in signals:
                if trace not in raw:
                    raise ValueError(f"trace {trace!r} is missing at point {index}")
                value = abs(raw[trace]) if column in absolute else raw[trace]
                if not math.isfinite(value):
                    raise ValueError(f"trace {trace!r} is non-finite at point {index}")
                result[column] = value
            writer.writerow(result)
    finally:
        if output_path is not None:
            target.close()
    return len(raw_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="input PSFASCII analysis file")
    parser.add_argument("output", help="output CSV path, or - for stdout")
    parser.add_argument("--sweep", required=True, help="PSF sweep trace name")
    parser.add_argument(
        "--signal",
        action="append",
        required=True,
        type=parse_signal,
        metavar="COLUMN=PSF_TRACE",
        help="CSV column and PSF trace; repeat for each signal",
    )
    parser.add_argument(
        "--absolute",
        action="append",
        default=[],
        metavar="COLUMN",
        help="write the magnitude of this selected column; repeat as needed",
    )
    parser.add_argument("--expected-points", type=int)
    args = parser.parse_args()

    if args.expected_points is not None and args.expected_points <= 0:
        parser.error("--expected-points must be positive")
    if not args.input.is_file():
        parser.error(f"input does not exist: {args.input}")

    output_path = None if args.output == "-" else Path(args.output)
    try:
        count = convert(
            args.input,
            output_path,
            args.sweep,
            args.signal,
            set(args.absolute),
            args.expected_points,
        )
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if output_path is not None:
        print(f"wrote {count} points to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
