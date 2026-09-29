#!/usr/bin/env python3
"""Run a TSMC40 Spectre gm/ID sweep and generate CSV/SVG/PNG artifacts.

This script intentionally uses only the Python standard library.  The remote
IC server has Spectre and gnuplot, but it does not need numpy or matplotlib.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
NETLIST = BASE_DIR / "netlist" / "characterize.scs"
DEFAULT_SPECTRE = Path("/opt/eda/cadence/SPECTRE251/bin/spectre")
DEFAULT_GNUPLOT = Path("/opt/eda/cadence/DDI251/GENUS251/bin/gnuplot")
PDK_MODEL = Path("/PDKS/TSMC40nm/models/spectre/toplevel.scs")
CORNER = "top_tt"
WIDTH_M = 1e-6
LENGTH_M = 40e-9
EXPECTED_POINTS = 221

DEVICES = (
    ("MN005", "nch", "nmos", 0.05),
    ("MN055", "nch", "nmos", 0.55),
    ("MN110", "nch", "nmos", 1.10),
    ("MP005", "pch", "pmos", 0.05),
    ("MP055", "pch", "pmos", 0.55),
    ("MP110", "pch", "pmos", 1.10),
)

RAW_FIELDS = ("ids", "gm", "gds", "cgg", "cgd", "cgs", "vth", "vdsat")
CSV_FIELDS = (
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


def run_checked(command: list[str], cwd: Path, stdout_path: Path | None = None) -> None:
    stdout_handle = stdout_path.open("w", encoding="utf-8") if stdout_path else None
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            stdout=stdout_handle or subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    finally:
        if stdout_handle:
            stdout_handle.close()
    if completed.returncode != 0:
        captured = "" if stdout_handle else (completed.stdout or "")
        raise RuntimeError(
            f"command failed with exit code {completed.returncode}: {' '.join(command)}\n{captured[-4000:]}"
        )


def parse_psfascii(path: Path) -> list[dict[str, float]]:
    value_pattern = re.compile(
        r'^"(?P<name>[^"]+)"\s+(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)$'
    )
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
            match = value_pattern.match(line)
            if not match:
                continue
            name = match.group("name")
            value = float(match.group("value"))
            if name == "VSWEEP":
                if current is not None:
                    rows.append(current)
                current = {"VSWEEP": value}
            elif current is not None:
                current[name] = value

    if current is not None:
        rows.append(current)
    if len(rows) != EXPECTED_POINTS:
        raise RuntimeError(f"expected {EXPECTED_POINTS} sweep points, found {len(rows)} in {path}")
    return rows


def derive_device_rows(
    raw_rows: list[dict[str, float]], instance: str, vds_v: float
) -> list[dict[str, float]]:
    output: list[dict[str, float]] = []
    for raw in raw_rows:
        values = {field: abs(raw[f"{instance}:{field}"]) for field in RAW_FIELDS}
        ids = values["ids"]
        gm = values["gm"]
        gds = values["gds"]
        cgg = values["cgg"]
        derived = {
            "vgs_v": raw["VSWEEP"],
            "vds_v": vds_v,
            "id_a": ids,
            "gm_s": gm,
            "gds_s": gds,
            "cgg_f": cgg,
            "cgd_f": values["cgd"],
            "cgs_f": values["cgs"],
            "vth_v": values["vth"],
            "vdsat_v": values["vdsat"],
            "gm_id_per_v": gm / ids if ids > 0.0 else math.nan,
            "gm_ro": gm / gds if gds > 0.0 else math.nan,
            "ft_hz": gm / (2.0 * math.pi * cgg) if cgg > 0.0 else math.nan,
            "id_w_a_per_m": ids / WIDTH_M,
        }
        if not all(math.isfinite(value) for value in derived.values()):
            raise RuntimeError(f"non-finite result for {instance} at VGS={raw['VSWEEP']}")
        output.append(derived)
    return output


def csv_name(model: str, vds_v: float) -> str:
    bias = f"{vds_v:.2f}".replace(".", "p")
    return f"tsmc40_{model}_vds_{bias}.csv"


def write_device_csv(path: Path, rows: list[dict[str, float]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_combined_csv(
    path: Path, datasets: dict[tuple[str, float], list[dict[str, float]]]
) -> None:
    fields = ("model", "polarity", "corner", "l_m", "w_m") + CSV_FIELDS
    polarities = {"nch": "nmos", "pch": "pmos"}
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for (model, _vds), rows in datasets.items():
            for row in rows:
                writer.writerow(
                    {
                        "model": model,
                        "polarity": polarities[model],
                        "corner": CORNER,
                        "l_m": LENGTH_M,
                        "w_m": WIDTH_M,
                        **row,
                    }
                )


def gnuplot_quote(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def create_plot_script(
    path: Path,
    output_svg: Path,
    model: str,
    polarity: str,
    csv_paths: list[tuple[float, Path]],
) -> None:
    colors = ("#0072B2", "#D55E00", "#009E73")

    def plot_clause(x_expr: str, y_expr: str) -> str:
        clauses = []
        for index, ((vds, csv_path), color) in enumerate(zip(csv_paths, colors), start=1):
            clauses.append(
                f"'{gnuplot_quote(csv_path)}' using {x_expr}:{y_expr} with lines "
                f"lw 2 lc rgb '{color}' title 'VDS={vds:.2f} V'"
            )
        return ", \\\n+    ".join(clauses)

    device_label = "NMOS nch" if polarity == "nmos" else "PMOS pch"
    script = f"""set datafile separator ','
set terminal svg size 1400,1000 enhanced font 'Arial,16'
set output '{gnuplot_quote(output_svg)}'
set multiplot layout 2,2 rowsfirst title 'TSMC40 {device_label}, TT, W/L=1um/40nm' font ',20'
set grid back lc rgb '#d9d9d9'
set border lw 1.2
set key top right
set tics out

set xlabel '|VGS| (V)'
set ylabel 'gm/ID (1/V)'
set xrange [0:1.1]
set yrange [0:26]
plot {plot_clause('1', '11')}

set xlabel 'gm/ID (1/V)'
set ylabel 'fT = gm/(2*pi*Cgg) (GHz)'
set xrange [2:25]
set yrange [0:*]
plot {plot_clause('11', '($13/1e9)')}

set xlabel 'gm/ID (1/V)'
set ylabel 'Intrinsic gain gm/gds'
set xrange [2:25]
set yrange [0:*]
plot {plot_clause('11', '12')}

set xlabel 'gm/ID (1/V)'
set ylabel 'ID/W (uA/um)'
set xrange [2:25]
set logscale y
set yrange [1e-4:*]
plot {plot_clause('11', '14')}
unset logscale y
unset multiplot
"""
    path.write_text(script, encoding="utf-8")


def ensure_white_svg_background(path: Path) -> None:
    """Insert an explicit white background for dark-theme SVG/PNG viewers."""
    svg = path.read_text(encoding="utf-8")
    if 'id="plot-background"' in svg:
        return
    opening_tag = re.search(r"<svg\b.*?>", svg, flags=re.DOTALL)
    if opening_tag is None:
        raise RuntimeError(f"SVG root element was not found: {path}")
    background = '\n<rect id="plot-background" width="100%" height="100%" fill="white"/>\n'
    svg = svg[: opening_tag.end()] + background + svg[opening_tag.end() :]
    path.write_text(svg, encoding="utf-8")


def nearest_row(rows: list[dict[str, float]], target_gmid: float) -> dict[str, float]:
    return min(rows, key=lambda row: abs(row["gm_id_per_v"] - target_gmid))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spectre", type=Path, default=DEFAULT_SPECTRE)
    parser.add_argument("--gnuplot", type=Path, default=DEFAULT_GNUPLOT)
    parser.add_argument("--output", type=Path, default=BASE_DIR / "results")
    parser.add_argument("--skip-simulation", action="store_true")
    args = parser.parse_args()

    for required in (NETLIST, PDK_MODEL, args.spectre, args.gnuplot):
        if not required.exists():
            raise FileNotFoundError(required)

    output_dir = args.output.resolve()
    raw_dir = output_dir / "raw"
    csv_dir = output_dir / "csv"
    plot_dir = output_dir / "plots"
    for directory in (raw_dir, csv_dir, plot_dir):
        directory.mkdir(parents=True, exist_ok=True)

    log_path = raw_dir / "spectre.log"
    console_path = raw_dir / "spectre.console.log"
    if not args.skip_simulation:
        run_checked(
            [
                str(args.spectre),
                "-64",
                "+log",
                str(log_path),
                "-format",
                "psfascii",
                str(NETLIST),
            ],
            cwd=raw_dir,
            stdout_path=console_path,
        )

    psf_path = raw_dir / "characterize.raw" / "dc1.dc"
    if not psf_path.exists():
        raise FileNotFoundError(psf_path)
    raw_rows = parse_psfascii(psf_path)

    datasets: dict[tuple[str, float], list[dict[str, float]]] = {}
    instance_to_csv: dict[str, Path] = {}
    for instance, model, _polarity, vds_v in DEVICES:
        rows = derive_device_rows(raw_rows, instance, vds_v)
        datasets[(model, vds_v)] = rows
        output_csv = csv_dir / csv_name(model, vds_v)
        write_device_csv(output_csv, rows)
        instance_to_csv[instance] = output_csv

    combined_csv = csv_dir / "tsmc40_gmid_all.csv"
    write_combined_csv(combined_csv, datasets)

    plot_outputs: list[Path] = []
    for model, polarity in (("nch", "nmos"), ("pch", "pmos")):
        csv_paths = [
            (vds, instance_to_csv[instance])
            for instance, device_model, device_polarity, vds in DEVICES
            if device_model == model and device_polarity == polarity
        ]
        svg_path = plot_dir / f"tsmc40_{model}_gmid.svg"
        gp_path = plot_dir / f"tsmc40_{model}_gmid.gnuplot"
        create_plot_script(gp_path, svg_path, model, polarity, csv_paths)
        run_checked([str(args.gnuplot), str(gp_path)], cwd=plot_dir)
        ensure_white_svg_background(svg_path)
        plot_outputs.append(svg_path)
        converter = shutil.which("rsvg-convert")
        if converter:
            png_path = svg_path.with_suffix(".png")
            run_checked(
                [converter, "--background-color", "white", "-o", str(png_path), str(svg_path)],
                cwd=plot_dir,
            )
            plot_outputs.append(png_path)

    representative: dict[str, dict[str, dict[str, float]]] = {}
    for model in ("nch", "pch"):
        rows = datasets[(model, 0.55)]
        representative[model] = {
            str(target): nearest_row(rows, target) for target in (5.0, 10.0, 15.0, 20.0)
        }

    summary = {
        "pdk_model": str(PDK_MODEL),
        "corner": CORNER,
        "models": ["nch", "pch"],
        "drawn_length_m": LENGTH_M,
        "width_m": WIDTH_M,
        "vds_v": [0.05, 0.55, 1.10],
        "vgs_sweep_v": {"start": 0.0, "stop": 1.1, "step": 0.005},
        "points_per_curve": EXPECTED_POINTS,
        "combined_csv": str(combined_csv),
        "plots": [str(path) for path in plot_outputs],
        "representative_at_vds_0p55": representative,
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print("TSMC40 gm/ID characterization completed")
    print(f"  raw points: {len(raw_rows)}")
    print(f"  curves:     {len(datasets)}")
    print(f"  CSV:        {combined_csv}")
    for plot in plot_outputs:
        print(f"  plot:       {plot}")
    print(f"  summary:    {summary_path}")
    for model in ("nch", "pch"):
        row = representative[model]["10.0"]
        print(
            f"  {model} @ VDS=0.55 V, gm/ID~10: "
            f"VGS={row['vgs_v']:.3f} V, ID/W={row['id_w_a_per_m']:.3f} uA/um, "
            f"fT={row['ft_hz']/1e9:.2f} GHz, gm/gds={row['gm_ro']:.2f}"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
