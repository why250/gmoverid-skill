#!/usr/bin/env python3
"""Characterize bundled PTM 180/45/22nm models with LTspice."""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from ltspice_common import find_ltspice, read_ascii_raw, run_ltspice


BASE_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class ModelSpec:
    key: str
    file: str
    nmos: str
    pmos: str
    vdd: float
    length_um: float


MODELS = {
    "180nm": ModelSpec("180nm", "ptm180.lib", "NMOS", "PMOS", 1.8, 0.18),
    "45nm": ModelSpec("45nm", "ptm45hp.lib", "nmos", "pmos", 1.0, 0.045),
    "22nm": ModelSpec("22nm", "ptm22hp.lib", "nmos", "pmos", 0.8, 0.022),
}
CSV_FIELDS = (
    "model", "polarity", "vgs_v", "vds_v", "id_a", "gm_s",
    "gm_over_id_per_v", "id_per_w_a_per_m", "vth_v",
)


def render_netlist(spec, polarity, width_um, step, raw_dir):
    template = (BASE_DIR / "netlist" / f"gmoverid_{polarity}.cir.tmpl").read_text(encoding="ascii")
    model_path = (BASE_DIR / "models" / spec.file).resolve()
    if not model_path.is_file():
        raise FileNotFoundError(model_path)
    values = {
        "model_key": spec.key,
        "model_path": str(model_path).replace("\\", "/"),
        "model_name": spec.nmos if polarity == "nmos" else spec.pmos,
        "w_um": f"{width_um:.12g}",
        "l_um": f"{spec.length_um:.12g}",
        "vdd_v": f"{spec.vdd:.12g}",
        "vds_v": f"{spec.vdd / 2:.12g}",
        "vd_v": f"{spec.vdd / 2:.12g}",
        "vgs_stop": f"{spec.vdd:.12g}",
        "vgs_step": f"{step:.12g}",
    }
    path = raw_dir / f"ptm_{spec.key}_{polarity}.cir"
    path.write_text(template.format(**values), encoding="ascii")
    return path


def extract_dataset(spec, polarity, raw_path, width_um):
    raw = read_ascii_raw(raw_path)
    if polarity == "nmos":
        vgs = raw.trace("V(vgs)")
        source_current = raw.trace("I(Vds)")
    else:
        vgs = spec.vdd - raw.trace("V(gate)")
        source_current = raw.trace("I(Vdrain)")
    order = np.argsort(vgs)
    vgs = np.asarray(vgs[order], dtype=float)
    drain_current = np.abs(np.asarray(source_current[order], dtype=float))
    gm = np.maximum(np.gradient(drain_current, vgs), 0.0)
    gmid = np.divide(gm, drain_current, out=np.full_like(gm, np.nan), where=drain_current > 1e-13)
    normalized = drain_current / (width_um / spec.length_um)
    vth = float(np.interp(1e-7, normalized, vgs)) if normalized.max() >= 1e-7 else float("nan")
    return {
        "model": spec.key, "polarity": polarity, "vgs": vgs,
        "vds": spec.vdd / 2, "id": drain_current, "gm": gm,
        "gmid": gmid, "id_per_w": drain_current / (width_um * 1e-6),
        "vth": vth,
    }


def validate_dataset(dataset, expected_points):
    vgs = np.asarray(dataset["vgs"])
    drain_current = np.asarray(dataset["id"])
    gmid = np.asarray(dataset["gmid"])
    label = f"{dataset['model']} {dataset['polarity']}"
    if len(vgs) < expected_points - 1:
        raise ValueError(f"{label}: expected about {expected_points} points, got {len(vgs)}")
    if not np.all(np.diff(vgs) > 0):
        raise ValueError(f"{label}: VGS sweep is not strictly increasing")
    if not np.all(np.isfinite(drain_current)) or np.any(drain_current < 0):
        raise ValueError(f"{label}: invalid drain current")
    if drain_current[-1] <= max(drain_current[0] * 100, 1e-8):
        raise ValueError(f"{label}: transistor did not turn on across the sweep")
    finite = gmid[np.isfinite(gmid)]
    if finite.size < 10 or finite.max() <= 1:
        raise ValueError(f"{label}: gm/ID extraction produced too few useful values")


def write_csv(path, datasets):
    def write_one(target):
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for data in datasets:
                arrays = {name: np.asarray(data[name]) for name in ("vgs", "id", "gm", "gmid", "id_per_w")}
                for i in range(len(arrays["vgs"])):
                    writer.writerow({
                        "model": data["model"], "polarity": data["polarity"],
                        "vgs_v": arrays["vgs"][i], "vds_v": data["vds"],
                        "id_a": arrays["id"][i], "gm_s": arrays["gm"][i],
                        "gm_over_id_per_v": arrays["gmid"][i],
                        "id_per_w_a_per_m": arrays["id_per_w"][i], "vth_v": data["vth"],
                    })

    write_one(path)
    # Some managed Windows environments transparently protect .csv files.
    # Keep an identical plain-text mirror with a non-CSV extension so results
    # remain readable by ordinary tools on those systems.
    mirror = path.with_suffix(path.suffix + ".txt")
    write_one(mirror)
    return mirror


def plot_results(path, datasets):
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    for data in datasets:
        label = f"{data['model']} {str(data['polarity']).upper()}"
        vgs, id_w, gmid = (np.asarray(data[name]) for name in ("vgs", "id_per_w", "gmid"))
        axes[0].semilogy(vgs, np.maximum(id_w, 1e-12), label=label)
        mask = np.isfinite(gmid) & (gmid > 0) & (gmid < 50)
        axes[1].plot(vgs[mask], gmid[mask], label=label)
    axes[0].set(xlabel="$V_{GS}$ or $|V_{SG}|$ (V)", ylabel="$I_D/W$ (A/m)", title="PTM drain-current density")
    axes[1].set(xlabel="$V_{GS}$ or $|V_{SG}|$ (V)", ylabel="$g_m/I_D$ (1/V)", title="LTspice gm/ID")
    for axis in axes:
        axis.grid(True, which="both", alpha=0.3)
        axis.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def parse_models(value):
    if value.casefold() == "all":
        return list(MODELS.values())
    keys = [item.strip().casefold() for item in value.split(",") if item.strip()]
    invalid = [key for key in keys if key not in MODELS]
    if invalid or not keys:
        raise ValueError(f"unknown or empty model selection: {value}")
    return [MODELS[key] for key in keys]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", default="all", help="all or comma-separated: 180nm,45nm,22nm")
    parser.add_argument("--polarity", choices=("nmos", "pmos", "both"), default="both")
    parser.add_argument("--width-um", type=float, default=10.0)
    parser.add_argument("--step", type=float, default=0.005, help="gate sweep step in volts")
    parser.add_argument("--ltspice", type=Path, help="explicit path to LTspice.exe")
    parser.add_argument("--output-dir", type=Path, default=Path.cwd() / "ltspice-results")
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    if args.width_um <= 0 or args.step <= 0:
        parser.error("--width-um and --step must be positive")
    try:
        selected = parse_models(args.models)
    except ValueError as exc:
        parser.error(str(exc))

    executable = find_ltspice(args.ltspice)
    output = args.output_dir.resolve()
    raw_dir, csv_dir, plot_dir = (output / name for name in ("raw", "csv", "plots"))
    for directory in (raw_dir, csv_dir, plot_dir):
        directory.mkdir(parents=True, exist_ok=True)
    polarities = ("nmos", "pmos") if args.polarity == "both" else (args.polarity,)

    print(f"LTspice: {executable}")
    datasets = []
    for spec in selected:
        for polarity in polarities:
            print(f"[{spec.key} {polarity.upper()}] simulating ...", end="", flush=True)
            netlist = render_netlist(spec, polarity, args.width_um, args.step, raw_dir)
            result = run_ltspice(netlist, executable, args.timeout)
            data = extract_dataset(spec, polarity, result.raw, args.width_um)
            validate_dataset(data, int(round(spec.vdd / args.step)) + 1)
            datasets.append(data)
            write_csv(csv_dir / f"ptm_{spec.key}_{polarity}_gmid.csv", [data])
            print(f" ok ({len(data['vgs'])} points, Vth={data['vth']:.3f} V)")

    combined = csv_dir / "ptm_ltspice_gmid_all.csv"
    figure = plot_dir / "ptm_ltspice_gmid.png"
    text_mirror = write_csv(combined, datasets)
    plot_results(figure, datasets)
    manifest = {
        "ltspice": str(executable), "models": [spec.key for spec in selected],
        "polarities": list(polarities), "width_um": args.width_um,
        "step_v": args.step, "datasets": len(datasets),
        "combined_csv": str(combined), "combined_csv_text_mirror": str(text_mirror),
    }
    metadata = output / "manifest.json"
    metadata.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"CSV:  {combined}\nText: {text_mirror}\nPlot: {figure}\nMeta: {metadata}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
