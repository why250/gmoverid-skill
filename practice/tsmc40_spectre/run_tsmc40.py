#!/usr/bin/env python3
"""Run configurable TSMC40 Spectre gm/ID sweeps and generate artifacts.

The runner uses only the Python standard library. Device families, dimensions,
biases, model paths, and corners come from profiles.json and can be overridden
from the command line without editing Python or Spectre source files.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, replace
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_PROFILES = BASE_DIR / "profiles.json"
DEFAULT_SPECTRE = Path("/opt/eda/cadence/SPECTRE251/bin/spectre")
DEFAULT_GNUPLOT = Path("/opt/eda/cadence/DDI251/GENUS251/bin/gnuplot")
IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PROFILE_RE = re.compile(r"^[A-Za-z0-9_]+$")

RAW_FIELDS = ("ids", "gm", "gds", "cgg", "cgd", "cgs", "vth", "vdsat")
SAVE_FIELDS = RAW_FIELDS + ("gmoverid", "self_gain")
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


@dataclass(frozen=True)
class CharacterizationConfig:
    profile: str
    description: str
    pdk_model: str
    corner: str
    nmos_model: str
    pmos_model: str
    width_m: float
    length_m: float
    vgs_start_v: float
    vgs_stop_v: float
    vgs_step_v: float
    vds_v: tuple[float, ...]
    plot_gmid_max: float

    @property
    def expected_points(self) -> int:
        intervals = (self.vgs_stop_v - self.vgs_start_v) / self.vgs_step_v
        rounded = round(intervals)
        if not math.isclose(intervals, rounded, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError(
                "VGS range must contain an integer number of steps: "
                f"({self.vgs_stop_v} - {self.vgs_start_v}) / {self.vgs_step_v}"
            )
        return rounded + 1


@dataclass(frozen=True)
class DeviceSpec:
    instance: str
    model: str
    polarity: str
    vds_v: float


def validate_config(config: CharacterizationConfig) -> None:
    if not PROFILE_RE.fullmatch(config.profile):
        raise ValueError(f"invalid profile: {config.profile!r}")
    for label, value in (
        ("corner", config.corner),
        ("nmos_model", config.nmos_model),
        ("pmos_model", config.pmos_model),
    ):
        if not IDENTIFIER_RE.fullmatch(value):
            raise ValueError(f"invalid {label}: {value!r}")
    if (
        not re.fullmatch(r"/[A-Za-z0-9_./-]+", config.pdk_model)
        or "//" in config.pdk_model
        or any(part in (".", "..") for part in config.pdk_model.split("/"))
    ):
        raise ValueError(f"pdk_model must be absolute: {config.pdk_model}")
    if config.width_m <= 0.0 or config.length_m <= 0.0:
        raise ValueError("width_m and length_m must be positive")
    if config.vgs_start_v < 0.0 or config.vgs_stop_v <= config.vgs_start_v:
        raise ValueError("VGS stop must be greater than a non-negative start")
    if config.vgs_step_v <= 0.0:
        raise ValueError("vgs_step_v must be positive")
    if not config.vds_v or len(set(config.vds_v)) != len(config.vds_v):
        raise ValueError("vds_v must contain at least one unique bias")
    if any(value <= 0.0 or value > config.vgs_stop_v for value in config.vds_v):
        raise ValueError("each VDS bias must be positive and no greater than VGS stop")
    if config.plot_gmid_max <= 2.0:
        raise ValueError("plot_gmid_max must be greater than 2")
    config.expected_points


def load_profiles(path: Path) -> dict[str, CharacterizationConfig]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_profiles = payload.get("profiles")
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise ValueError(f"profiles object is missing or empty in {path}")

    profiles: dict[str, CharacterizationConfig] = {}
    for name, raw in raw_profiles.items():
        if not isinstance(raw, dict):
            raise ValueError(f"profile {name!r} must be an object")
        try:
            config = CharacterizationConfig(
                profile=name,
                description=str(raw["description"]),
                pdk_model=str(raw["pdk_model"]),
                corner=str(raw["corner"]),
                nmos_model=str(raw["nmos_model"]),
                pmos_model=str(raw["pmos_model"]),
                width_m=float(raw["width_m"]),
                length_m=float(raw["length_m"]),
                vgs_start_v=float(raw["vgs_start_v"]),
                vgs_stop_v=float(raw["vgs_stop_v"]),
                vgs_step_v=float(raw["vgs_step_v"]),
                vds_v=tuple(float(value) for value in raw["vds_v"]),
                plot_gmid_max=float(raw["plot_gmid_max"]),
            )
        except KeyError as exc:
            raise ValueError(f"profile {name!r} is missing {exc.args[0]!r}") from exc
        validate_config(config)
        profiles[name] = config
    return profiles


def parse_vds(value: str) -> tuple[float, ...]:
    try:
        parsed = tuple(float(item.strip()) for item in value.split(",") if item.strip())
    except ValueError as exc:
        raise argparse.ArgumentTypeError("VDS must be comma-separated numbers") from exc
    if not parsed:
        raise argparse.ArgumentTypeError("VDS must contain at least one number")
    return parsed


def apply_overrides(
    config: CharacterizationConfig, args: argparse.Namespace
) -> CharacterizationConfig:
    updates: dict[str, Any] = {}
    for name in (
        "corner",
        "nmos_model",
        "pmos_model",
        "vgs_start_v",
        "vgs_stop_v",
        "vgs_step_v",
        "plot_gmid_max",
    ):
        value = getattr(args, name)
        if value is not None:
            updates[name] = value
    if args.pdk_model is not None:
        updates["pdk_model"] = args.pdk_model
    if args.width_um is not None:
        updates["width_m"] = args.width_um * 1e-6
    if args.length_um is not None:
        updates["length_m"] = args.length_um * 1e-6
    if args.vds is not None:
        updates["vds_v"] = args.vds
    result = replace(config, **updates)
    validate_config(result)
    return result


def build_devices(config: CharacterizationConfig) -> tuple[DeviceSpec, ...]:
    devices = []
    for polarity, prefix, model in (
        ("nmos", "MN", config.nmos_model),
        ("pmos", "MP", config.pmos_model),
    ):
        for index, vds_v in enumerate(config.vds_v):
            devices.append(DeviceSpec(f"{prefix}{index:03d}", model, polarity, vds_v))
    return tuple(devices)


def spectre_number(value: float) -> str:
    return format(value, ".12g")


def write_netlist(
    path: Path, config: CharacterizationConfig, devices: tuple[DeviceSpec, ...]
) -> None:
    lines = [
        "simulator lang=spectre",
        "",
        f"// Generated by run_tsmc40.py profile={config.profile}.",
        f'include "{config.pdk_model}" section={config.corner}',
        "",
        f"parameters VSWEEP={spectre_number(config.vgs_start_v)}",
        "",
        "VGN (gn 0) vsource dc=VSWEEP",
        "VGP (gp 0) vsource dc=-VSWEEP",
        "",
    ]
    for device in devices:
        node = f"d{device.instance.lower()}"
        sign = "" if device.polarity == "nmos" else "-"
        lines.append(
            f"VD{device.instance} ({node} 0) vsource dc={sign}{spectre_number(device.vds_v)}"
        )
    lines.append("")
    for device in devices:
        node = f"d{device.instance.lower()}"
        gate = "gn" if device.polarity == "nmos" else "gp"
        lines.append(
            f"{device.instance} ({node} {gate} 0 0) {device.model} "
            f"w={spectre_number(config.width_m)} l={spectre_number(config.length_m)}"
        )
    lines.append("")
    fields = " ".join(f"{{instance}}:{field}" for field in SAVE_FIELDS)
    for device in devices:
        lines.append(f"save {fields.format(instance=device.instance)}")
    lines.extend(
        (
            "",
            "dc1 dc param=VSWEEP "
            f"start={spectre_number(config.vgs_start_v)} "
            f"stop={spectre_number(config.vgs_stop_v)} "
            f"step={spectre_number(config.vgs_step_v)}",
            "",
        )
    )
    path.write_text("\n".join(lines), encoding="utf-8")


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
            f"command failed with exit code {completed.returncode}: {' '.join(command)}\n"
            f"{captured[-4000:]}"
        )


def parse_psfascii(path: Path, expected_points: int) -> list[dict[str, float]]:
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
    if len(rows) != expected_points:
        raise RuntimeError(
            f"expected {expected_points} sweep points, found {len(rows)} in {path}"
        )
    return rows


def derive_device_rows(
    raw_rows: list[dict[str, float]], device: DeviceSpec, width_m: float
) -> list[dict[str, float]]:
    output: list[dict[str, float]] = []
    for raw in raw_rows:
        try:
            values = {field: abs(raw[f"{device.instance}:{field}"]) for field in RAW_FIELDS}
        except KeyError as exc:
            raise RuntimeError(
                f"missing operating-point field {exc.args[0]!r} for {device.model}"
            ) from exc
        ids = values["ids"]
        gm = values["gm"]
        gds = values["gds"]
        cgg = values["cgg"]
        derived = {
            "vgs_v": raw["VSWEEP"],
            "vds_v": device.vds_v,
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
            "id_w_a_per_m": ids / width_m,
        }
        if not all(math.isfinite(value) for value in derived.values()):
            raise RuntimeError(
                f"non-finite result for {device.instance} at VGS={raw['VSWEEP']}"
            )
        output.append(derived)
    return output


def csv_name(model: str, vds_v: float) -> str:
    bias = f"{vds_v:.4g}".replace(".", "p")
    return f"tsmc40_{model}_vds_{bias}.csv"


def write_device_csv(path: Path, rows: list[dict[str, float]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_combined_csv(
    path: Path,
    config: CharacterizationConfig,
    datasets: dict[tuple[str, float], list[dict[str, float]]],
) -> None:
    fields = ("profile", "model", "polarity", "corner", "l_m", "w_m") + CSV_FIELDS
    polarities = {config.nmos_model: "nmos", config.pmos_model: "pmos"}
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for (model, _vds), rows in datasets.items():
            for row in rows:
                writer.writerow(
                    {
                        "profile": config.profile,
                        "model": model,
                        "polarity": polarities[model],
                        "corner": config.corner,
                        "l_m": config.length_m,
                        "w_m": config.width_m,
                        **row,
                    }
                )


def gnuplot_quote(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace("'", "''")


def format_length(value_m: float) -> str:
    if value_m < 1e-6:
        return f"{value_m * 1e9:g}nm"
    return f"{value_m * 1e6:g}um"


def create_plot_script(
    path: Path,
    output_svg: Path,
    config: CharacterizationConfig,
    model: str,
    polarity: str,
    csv_paths: list[tuple[float, Path]],
) -> None:
    colors = ("#0072B2", "#D55E00", "#009E73", "#CC79A7", "#000000")

    def plot_clause(x_expr: str, y_expr: str) -> str:
        clauses = []
        for index, (vds, csv_path) in enumerate(csv_paths):
            color = colors[index % len(colors)]
            clauses.append(
                f"'{gnuplot_quote(csv_path)}' using {x_expr}:{y_expr} with lines "
                f"lw 2 lc rgb '{color}' title 'VDS={vds:g} V'"
            )
        return ", \\\n    ".join(clauses)

    device_label = f"NMOS {model}" if polarity == "nmos" else f"PMOS {model}"
    geometry = f"W/L={format_length(config.width_m)}/{format_length(config.length_m)}"
    script = f"""set datafile separator ','
set terminal svg size 1400,1000 enhanced font 'Arial,16'
set output '{gnuplot_quote(output_svg)}'
set multiplot layout 2,2 rowsfirst title 'TSMC40 {device_label}, {config.corner}, {geometry}' font ',20'
set grid back lc rgb '#d9d9d9'
set border lw 1.2
set key top right
set tics out

set xlabel '|VGS| (V)'
set ylabel 'gm/ID (1/V)'
set xrange [{config.vgs_start_v}:{config.vgs_stop_v}]
set yrange [0:{config.plot_gmid_max}]
plot {plot_clause('1', '11')}

set xlabel 'gm/ID (1/V)'
set ylabel 'fT = gm/(2*pi*Cgg) (GHz)'
set xrange [2:{config.plot_gmid_max}]
set yrange [0:*]
plot {plot_clause('11', '($13/1e9)')}

set xlabel 'gm/ID (1/V)'
set ylabel 'Intrinsic gain gm/gds'
set xrange [2:{config.plot_gmid_max}]
set yrange [0:*]
plot {plot_clause('11', '12')}

set xlabel 'gm/ID (1/V)'
set ylabel 'ID/W (uA/um)'
set xrange [2:{config.plot_gmid_max}]
set logscale y
set yrange [1e-4:*]
plot {plot_clause('11', '14')}
unset logscale y
unset multiplot
"""
    path.write_text(script, encoding="utf-8")


def ensure_white_svg_background(path: Path) -> None:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profiles-file", type=Path, default=DEFAULT_PROFILES)
    parser.add_argument("--profile", default="1v1")
    parser.add_argument("--list-profiles", action="store_true")
    parser.add_argument("--spectre", type=Path, default=DEFAULT_SPECTRE)
    parser.add_argument("--gnuplot", type=Path, default=DEFAULT_GNUPLOT)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--skip-simulation", action="store_true")
    parser.add_argument("--pdk-model")
    parser.add_argument("--corner")
    parser.add_argument("--nmos-model")
    parser.add_argument("--pmos-model")
    parser.add_argument("--width-um", type=float)
    parser.add_argument("--length-um", type=float)
    parser.add_argument("--vgs-start-v", type=float)
    parser.add_argument("--vgs-stop-v", type=float)
    parser.add_argument("--vgs-step-v", type=float)
    parser.add_argument("--vds", type=parse_vds, help="comma-separated positive VDS magnitudes")
    parser.add_argument("--plot-gmid-max", type=float)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    profiles = load_profiles(args.profiles_file.resolve())
    if args.list_profiles:
        for name, profile in profiles.items():
            print(
                f"{name}: {profile.description}; {profile.nmos_model}/{profile.pmos_model}; "
                f"L={format_length(profile.length_m)}; VGS<={profile.vgs_stop_v:g} V"
            )
        return 0
    if args.profile not in profiles:
        raise ValueError(
            f"unknown profile {args.profile!r}; available: {', '.join(sorted(profiles))}"
        )
    config = apply_overrides(profiles[args.profile], args)
    devices = build_devices(config)

    for required in (Path(config.pdk_model), args.spectre, args.gnuplot):
        if not required.exists():
            raise FileNotFoundError(required)

    output_dir = (
        args.output.resolve()
        if args.output is not None
        else (BASE_DIR / "results" / config.profile).resolve()
    )
    raw_dir = output_dir / "raw"
    csv_dir = output_dir / "csv"
    plot_dir = output_dir / "plots"
    for directory in (raw_dir, csv_dir, plot_dir):
        directory.mkdir(parents=True, exist_ok=True)

    netlist_path = raw_dir / "characterize.scs"
    write_netlist(netlist_path, config, devices)
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
                str(netlist_path),
            ],
            cwd=raw_dir,
            stdout_path=console_path,
        )

    psf_path = raw_dir / "characterize.raw" / "dc1.dc"
    if not psf_path.exists():
        raise FileNotFoundError(psf_path)
    raw_rows = parse_psfascii(psf_path, config.expected_points)

    datasets: dict[tuple[str, float], list[dict[str, float]]] = {}
    instance_to_csv: dict[str, Path] = {}
    for device in devices:
        rows = derive_device_rows(raw_rows, device, config.width_m)
        datasets[(device.model, device.vds_v)] = rows
        output_csv = csv_dir / csv_name(device.model, device.vds_v)
        write_device_csv(output_csv, rows)
        instance_to_csv[device.instance] = output_csv

    combined_csv = csv_dir / "tsmc40_gmid_all.csv"
    write_combined_csv(combined_csv, config, datasets)

    plot_outputs: list[Path] = []
    for model, polarity in (
        (config.nmos_model, "nmos"),
        (config.pmos_model, "pmos"),
    ):
        csv_paths = [
            (device.vds_v, instance_to_csv[device.instance])
            for device in devices
            if device.model == model and device.polarity == polarity
        ]
        svg_path = plot_dir / f"tsmc40_{model}_gmid.svg"
        gp_path = plot_dir / f"tsmc40_{model}_gmid.gnuplot"
        create_plot_script(gp_path, svg_path, config, model, polarity, csv_paths)
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
    middle_vds = config.vds_v[len(config.vds_v) // 2]
    for model in (config.nmos_model, config.pmos_model):
        rows = datasets[(model, middle_vds)]
        representative[model] = {
            str(target): nearest_row(rows, target) for target in (5.0, 10.0, 15.0, 20.0)
        }

    summary = {
        "profile": config.profile,
        "description": config.description,
        "pdk_model": str(config.pdk_model),
        "corner": config.corner,
        "models": [config.nmos_model, config.pmos_model],
        "drawn_length_m": config.length_m,
        "width_m": config.width_m,
        "vds_v": list(config.vds_v),
        "vgs_sweep_v": {
            "start": config.vgs_start_v,
            "stop": config.vgs_stop_v,
            "step": config.vgs_step_v,
        },
        "points_per_curve": config.expected_points,
        "generated_netlist": str(netlist_path),
        "combined_csv": str(combined_csv),
        "plots": [str(path) for path in plot_outputs],
        f"representative_at_vds_{middle_vds:g}": representative,
    }
    summary_path = output_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"TSMC40 gm/ID characterization completed: profile={config.profile}")
    print(f"  models:     {config.nmos_model} / {config.pmos_model}")
    print(f"  geometry:   W={format_length(config.width_m)}, L={format_length(config.length_m)}")
    print(f"  raw points: {len(raw_rows)}")
    print(f"  curves:     {len(datasets)}")
    print(f"  CSV:        {combined_csv}")
    for plot in plot_outputs:
        print(f"  plot:       {plot}")
    print(f"  summary:    {summary_path}")
    for model in (config.nmos_model, config.pmos_model):
        row = representative[model]["10.0"]
        print(
            f"  {model} @ VDS={middle_vds:g} V, gm/ID~10: "
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
