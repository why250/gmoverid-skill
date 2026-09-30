"""Build a reusable multi-dimensional gm/ID table for Sky130A NFETs.

The generated database deliberately separates two useful sweeps:

* ``core``: L x VDS x VBS at TT/27 C, for design lookup.
* ``pvt``: process corner x temperature at nominal geometry and bias.

This keeps the first characterization compact while exposing every major
independent variable.  Use ``--full-cross`` only when the full Cartesian PVT
database is really needed.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from gmoverid_sky130 import (
    DEFAULT_CORNERS,
    DEVICE,
    INTERNAL_DEVICE,
    PDK_VERSION,
    find_ngspice,
    find_sky130a,
    spice_path,
)


BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs" / "mos_characterization"
PLOT_DIR = BASE_DIR / "plots"
DATA_DIR = BASE_DIR / "data"

DEFAULT_LENGTHS_UM = (0.15, 0.30, 0.50, 1.00)
DEFAULT_VDS_V = (0.10, 0.30, 0.60, 0.90, 1.20, 1.80)
DEFAULT_VBS_V = (0.0, -0.30, -0.60)
DEFAULT_TEMPERATURES_C = (-40.0, 27.0, 125.0)
DEFAULT_GMID_TARGETS = (6.0, 10.0, 15.0, 20.0)


@dataclass(frozen=True, order=True)
class Condition:
    corner: str
    temperature_c: float
    length_um: float
    vds_v: float
    vbs_v: float

    def stem(self) -> str:
        def token(value: float) -> str:
            return f"{value:g}".replace("-", "m").replace(".", "p")

        return (
            f"{self.corner}_T{token(self.temperature_c)}_"
            f"L{token(self.length_um)}_VDS{token(self.vds_v)}_"
            f"VBS{token(self.vbs_v)}"
        )


def make_deck(
    *, model_lib: Path, condition: Condition, data_path: Path,
    width_um: float, vgs_step: float,
) -> str:
    dev = INTERNAL_DEVICE
    return f"""* Sky130A MOS characterization: {DEVICE}
* corner={condition.corner}, temp={condition.temperature_c:g}C,
* L={condition.length_um:g}um, VDS={condition.vds_v:g}V, VBS={condition.vbs_v:g}V
.lib \"{spice_path(model_lib)}\" {condition.corner}
.temp {condition.temperature_c:g}
.options reltol=1e-5 abstol=1e-14 vntol=1e-8

VDS d 0 {condition.vds_v:g}
VGS g 0 0
VBS b 0 {condition.vbs_v:g}
XN1 d g 0 b {DEVICE} l={condition.length_um:g} w={width_um:g} nf=1

.control
set wr_singlescale
set wr_vecnames
save v(g) v(d) v(b) i(VDS) \
  @{dev}[gm] @{dev}[gds] @{dev}[gmbs] \
  @{dev}[cgg] @{dev}[cgs] @{dev}[cgd] @{dev}[cgb] @{dev}[cdb] \
  @{dev}[vth] @{dev}[vdsat]
dc VGS 0 1.8 {vgs_step:g}
wrdata {spice_path(data_path)} v(g) v(d) v(b) i(VDS) \
  @{dev}[gm] @{dev}[gds] @{dev}[gmbs] \
  @{dev}[cgg] @{dev}[cgs] @{dev}[cgd] @{dev}[cgb] @{dev}[cdb] \
  @{dev}[vth] @{dev}[vdsat]
quit
.endc
.end
"""


def simulate_condition(
    *, ngspice: Path, model_lib: Path, condition: Condition,
    width_um: float, vgs_step: float, timeout: int, force_resim: bool,
) -> tuple[Condition, dict[str, np.ndarray]]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stem = condition.stem()
    cir_path = LOG_DIR / f"{stem}.spice"
    log_path = LOG_DIR / f"{stem}.log"
    raw_path = LOG_DIR / f"{stem}.dat"
    deck = make_deck(
        model_lib=model_lib,
        condition=condition,
        data_path=raw_path,
        width_um=width_um,
        vgs_step=vgs_step,
    )
    cache_matches = (
        not force_resim
        and raw_path.is_file()
        and cir_path.is_file()
        and cir_path.read_text(encoding="ascii") == deck
    )
    if not cache_matches:
        raw_path.unlink(missing_ok=True)
        cir_path.write_text(deck, encoding="ascii")
        result = subprocess.run(
            [str(ngspice), "-b", str(cir_path)],
            cwd=LOG_DIR,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        log_path.write_text(result.stdout, encoding="utf-8")
        if result.returncode != 0 or not raw_path.is_file():
            raise RuntimeError(f"Simulation failed for {stem}; see {log_path}")

    # wr_singlescale emits the sweep scale followed by the 14 requested vectors.
    raw = np.loadtxt(raw_path, skiprows=1)
    if raw.ndim != 2 or raw.shape[1] != 15:
        raise RuntimeError(
            f"Unexpected wrdata shape {raw.shape} for {stem}; see {log_path}"
        )

    vgs = raw[:, 1]
    drain_current = np.maximum(-raw[:, 4], 1e-30)
    gm = np.maximum(raw[:, 5], 0.0)
    gds = np.maximum(raw[:, 6], 1e-30)
    gmb = np.abs(raw[:, 7])
    cgg = np.maximum(np.abs(raw[:, 8]), 1e-30)
    # ngspice exposes the compact-model capacitance-matrix cross derivatives
    # with a signed convention.  Store magnitudes here because these columns
    # are intended as design-table parasitic-capacitance values.
    cgs = np.abs(raw[:, 9])
    cgd = np.abs(raw[:, 10])
    cgb = np.abs(raw[:, 11])
    cdb = np.abs(raw[:, 12])
    vth = raw[:, 13]
    vdsat = raw[:, 14]

    return condition, {
        "vgs_v": vgs,
        "vth_v": vth,
        "vov_v": vgs - vth,
        "vdsat_v": vdsat,
        "id_a": drain_current,
        "id_w_ua_per_um": drain_current / width_um * 1e6,
        "gm_s": gm,
        "gds_s": gds,
        "gmb_s": gmb,
        "gmb_over_gm": np.divide(gmb, gm, out=np.zeros_like(gmb), where=gm > 0),
        "cgg_f": cgg,
        "cgs_f": cgs,
        "cgd_f": cgd,
        "cgb_f": cgb,
        "cdb_f": cdb,
        "gmid_per_v": gm / drain_current,
        "gmro": gm / gds,
        "ft_hz": gm / (2.0 * math.pi * cgg),
    }


def inversion_arrays(data: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    gmid = data["gmid_per_v"]
    valid = np.isfinite(gmid) & (data["id_a"] > 1e-12)
    indexes = np.flatnonzero(valid)
    if not len(indexes):
        raise RuntimeError("No valid inversion points were generated")
    peak = indexes[np.argmax(gmid[indexes])]
    mask = (
        (np.arange(len(gmid)) >= peak)
        & valid
        & (gmid >= 3.0)
        & (gmid <= 30.0)
    )
    selected = np.flatnonzero(mask)
    order = np.argsort(gmid[selected])
    return selected[order], gmid[selected][order]


def lookup(data: dict[str, np.ndarray], quantity: str, gmid_target: float) -> float:
    indexes, x = inversion_arrays(data)
    if not len(x) or gmid_target < x[0] or gmid_target > x[-1]:
        return float("nan")
    unique_x, unique_indexes = np.unique(x, return_index=True)
    y = data[quantity][indexes][unique_indexes]
    return float(np.interp(gmid_target, unique_x, y))


def build_plan(args: argparse.Namespace) -> dict[Condition, set[str]]:
    plan: dict[Condition, set[str]] = {}

    def add(condition: Condition, profile: str) -> None:
        plan.setdefault(condition, set()).add(profile)

    if args.full_cross:
        for corner in args.corners:
            for temperature in args.temperatures:
                for length in args.lengths:
                    for vds in args.vds_values:
                        for vbs in args.vbs_values:
                            add(Condition(corner, temperature, length, vds, vbs), "full")
        return plan

    for length in args.lengths:
        for vds in args.vds_values:
            for vbs in args.vbs_values:
                add(Condition("tt", 27.0, length, vds, vbs), "core")

    for corner in args.corners:
        for temperature in args.temperatures:
            add(
                Condition(
                    corner,
                    temperature,
                    args.nominal_length,
                    args.nominal_vds,
                    0.0,
                ),
                "pvt",
            )
    return plan


def write_raw_table(
    results: dict[Condition, dict[str, np.ndarray]],
    profiles: dict[Condition, set[str]],
    width_um: float,
    output: Path,
) -> None:
    metric_names = list(next(iter(results.values())).keys())
    header = [
        "profiles", "device", "corner", "temperature_c", "width_um",
        "length_um", "vds_v", "vbs_v", *metric_names,
    ]
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(header)
        for condition in sorted(results):
            data = results[condition]
            prefix = [
                "+".join(sorted(profiles[condition])), DEVICE, condition.corner,
                condition.temperature_c, width_um, condition.length_um,
                condition.vds_v, condition.vbs_v,
            ]
            for row in zip(*(data[name] for name in metric_names)):
                writer.writerow([*prefix, *(f"{float(value):.12g}" for value in row)])


def write_lookup_table(
    results: dict[Condition, dict[str, np.ndarray]],
    profiles: dict[Condition, set[str]],
    width_um: float,
    targets: list[float],
    output: Path,
) -> None:
    quantities = (
        "vgs_v", "vth_v", "vov_v", "vdsat_v", "id_w_ua_per_um",
        "gm_s", "gds_s", "gmb_s", "gmb_over_gm", "gmro", "ft_hz",
        "cgg_f", "cgs_f", "cgd_f", "cgb_f", "cdb_f",
    )
    header = [
        "profiles", "device", "corner", "temperature_c", "width_um",
        "length_um", "vds_v", "vbs_v", "gmid_per_v", "available", *quantities,
    ]
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(header)
        for condition in sorted(results):
            data = results[condition]
            prefix = [
                "+".join(sorted(profiles[condition])), DEVICE, condition.corner,
                condition.temperature_c, width_um, condition.length_um,
                condition.vds_v, condition.vbs_v,
            ]
            for target in targets:
                values = [lookup(data, quantity, target) for quantity in quantities]
                available = all(math.isfinite(value) for value in values)
                writer.writerow(
                    [
                        *prefix,
                        target,
                        str(available).lower(),
                        *(f"{value:.12g}" if math.isfinite(value) else "" for value in values),
                    ]
                )


def _plot_curve(axis: plt.Axes, data: dict[str, np.ndarray], quantity: str, **kwargs: object) -> None:
    indexes, gmid = inversion_arrays(data)
    axis.plot(gmid, data[quantity][indexes], **kwargs)


def plot_length_atlas(
    results: dict[Condition, dict[str, np.ndarray]], args: argparse.Namespace,
    output: Path,
) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(13.2, 9.4), layout="constrained")
    colors = plt.cm.viridis(np.linspace(0.08, 0.92, len(args.lengths)))
    for color, length in zip(colors, args.lengths):
        condition = Condition("tt", 27.0, length, args.nominal_vds, 0.0)
        data = results[condition]
        label = f"L={length:g} um"
        indexes, gmid = inversion_arrays(data)
        axes[0, 0].semilogy(
            gmid, data["id_w_ua_per_um"][indexes], color=color, label=label,
        )
        axes[0, 1].plot(gmid, data["gmro"][indexes], color=color, label=label)
        axes[1, 0].plot(
            gmid, data["ft_hz"][indexes] / 1e9, color=color, label=label,
        )
        axes[1, 1].plot(gmid, data["vgs_v"][indexes], color=color, label=label)

    titles = (
        (r"$I_D/W$ vs $g_m/I_D$", r"$I_D/W$ [$\mu$A/$\mu$m]"),
        (r"Intrinsic Gain vs $g_m/I_D$", r"$g_m/g_{ds}$"),
        (r"Transit Frequency vs $g_m/I_D$", r"$f_T$ [GHz]"),
        (r"Gate Bias vs $g_m/I_D$", r"$V_{GS}$ [V]"),
    )
    for axis, (title, ylabel) in zip(axes.flat, titles):
        axis.set_title(title)
        axis.set_xlabel(r"$g_m/I_D$ [$V^{-1}$]")
        axis.set_ylabel(ylabel)
        axis.set_xlim(4, 24)
        axis.set_xticks(np.arange(4, 25, 2))
        axis.grid(True, which="both", alpha=0.35)
        axis.legend()
    fig.suptitle(
        f"Sky130A {DEVICE} Length Atlas — TT, 27 C, "
        f"VDS={args.nominal_vds:g} V, VBS=0 V",
        fontsize=14,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)


def plot_bias_pvt(
    results: dict[Condition, dict[str, np.ndarray]], args: argparse.Namespace,
    output: Path,
) -> None:
    fig, axes = plt.subplots(2, 2, figsize=(14.5, 9.8), layout="constrained")
    colors = plt.cm.plasma(np.linspace(0.08, 0.92, len(args.vds_values)))
    for color, vds in zip(colors, args.vds_values):
        condition = Condition("tt", 27.0, args.nominal_length, vds, 0.0)
        data = results[condition]
        indexes, gmid = inversion_arrays(data)
        label = f"VDS={vds:g} V"
        axes[0, 0].semilogy(
            gmid, data["id_w_ua_per_um"][indexes], color=color, label=label,
        )
        axes[0, 1].plot(gmid, data["gmro"][indexes], color=color, label=label)

    colors = plt.cm.cividis(np.linspace(0.08, 0.92, len(args.vbs_values)))
    for color, vbs in zip(colors, args.vbs_values):
        condition = Condition("tt", 27.0, args.nominal_length, args.nominal_vds, vbs)
        data = results[condition]
        _plot_curve(
            axes[1, 0], data, "vgs_v", color=color, label=f"VBS={vbs:g} V",
        )

    for corner in args.corners:
        values = []
        for temperature in args.temperatures:
            condition = Condition(
                corner, temperature, args.nominal_length, args.nominal_vds, 0.0,
            )
            values.append(lookup(results[condition], "id_w_ua_per_um", 15.0))
        axes[1, 1].plot(args.temperatures, values, marker="o", label=corner.upper())

    axes[0, 0].set_title(r"Drain-Bias Effect on $I_D/W$")
    axes[0, 0].set_ylabel(r"$I_D/W$ [$\mu$A/$\mu$m]")
    axes[0, 1].set_title(r"Drain-Bias Effect on Intrinsic Gain")
    axes[0, 1].set_ylabel(r"$g_m/g_{ds}$")
    axes[1, 0].set_title(r"Body-Bias Effect on Required $V_{GS}$")
    axes[1, 0].set_ylabel(r"$V_{GS}$ [V]")
    for axis in (axes[0, 0], axes[0, 1], axes[1, 0]):
        axis.set_xlabel(r"$g_m/I_D$ [$V^{-1}$]")
        axis.set_xlim(4, 24)
        axis.set_xticks(np.arange(4, 25, 2))
        axis.grid(True, which="both", alpha=0.35)
        axis.legend()

    axes[1, 1].set_title(r"PVT Current Density at $g_m/I_D=15\ V^{-1}$")
    axes[1, 1].set_xlabel("Temperature [C]")
    axes[1, 1].set_ylabel(r"$I_D/W$ [$\mu$A/$\mu$m]")
    axes[1, 1].grid(True, alpha=0.35)
    axes[1, 1].legend()

    fig.suptitle(
        f"Sky130A {DEVICE} Bias and PVT Atlas — "
        f"L={args.nominal_length:g} um, nominal VDS={args.nominal_vds:g} V",
        fontsize=14,
    )
    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)


def write_report(
    results: dict[Condition, dict[str, np.ndarray]], args: argparse.Namespace,
    raw_path: Path, lookup_path: Path, output: Path,
) -> None:
    condition = Condition("tt", 27.0, args.nominal_length, args.nominal_vds, 0.0)
    data = results[condition]
    lines = [
        "# Sky130A NFET gm/ID characterization", "",
        f"Device: `{DEVICE}`", "",
        f"Nominal point: TT, 27 C, W={args.width:g} um, "
        f"L={args.nominal_length:g} um, VDS={args.nominal_vds:g} V, VBS=0 V.",
        "",
        "| gm/ID [1/V] | VGS [V] | ID/W [uA/um] | gm/gds | fT [GHz] | gmb/gm |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for target in args.gmid_targets:
        lines.append(
            f"| {target:g} | {lookup(data, 'vgs_v', target):.4g} | "
            f"{lookup(data, 'id_w_ua_per_um', target):.4g} | "
            f"{lookup(data, 'gmro', target):.4g} | "
            f"{lookup(data, 'ft_hz', target) / 1e9:.4g} | "
            f"{lookup(data, 'gmb_over_gm', target):.4g} |"
        )
    lines.extend([
        "", "Generated files:", "",
        f"- Raw VGS-sweep database: `{raw_path.name}`",
        f"- Interpolated design lookup table: `{lookup_path.name}`",
        "- The `profiles` column identifies `core`, `pvt`, or both.",
        "",
        "The core profile spans L, VDS, and VBS at TT/27 C. The PVT profile "
        "spans corners and temperatures at the nominal geometry and bias. "
        "These profiles are not a full Cartesian cross unless `--full-cross` is used.",
    ])
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdk-root", required=True, help="Direct sky130A path or its parent")
    parser.add_argument("--ngspice", help="Path to ngspice_con/ngspice")
    parser.add_argument("--width", type=float, default=1.0, help="Reference width [um]")
    parser.add_argument("--lengths", type=float, nargs="+", default=list(DEFAULT_LENGTHS_UM))
    parser.add_argument("--vds-values", type=float, nargs="+", default=list(DEFAULT_VDS_V))
    parser.add_argument("--vbs-values", type=float, nargs="+", default=list(DEFAULT_VBS_V))
    parser.add_argument("--corners", nargs="+", default=list(DEFAULT_CORNERS))
    parser.add_argument(
        "--temperatures", type=float, nargs="+", default=list(DEFAULT_TEMPERATURES_C),
    )
    parser.add_argument(
        "--gmid-targets", type=float, nargs="+", default=list(DEFAULT_GMID_TARGETS),
    )
    parser.add_argument("--nominal-length", type=float, default=0.15)
    parser.add_argument("--nominal-vds", type=float, default=0.9)
    parser.add_argument("--vgs-step", type=float, default=0.01)
    parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument("--timeout", type=int, default=90, help="Per-sweep timeout [s]")
    parser.add_argument(
        "--force-resim", action="store_true",
        help="Ignore matching cached raw sweeps and run ngspice again",
    )
    parser.add_argument(
        "--full-cross", action="store_true",
        help="Sweep corners x temperatures x L x VDS x VBS (much slower)",
    )
    args = parser.parse_args()

    if args.nominal_length not in args.lengths:
        parser.error("--nominal-length must also appear in --lengths")
    if args.nominal_vds not in args.vds_values:
        parser.error("--nominal-vds must also appear in --vds-values")
    if 0.0 not in args.vbs_values:
        parser.error("--vbs-values must include 0")
    if args.jobs < 1:
        parser.error("--jobs must be >= 1")

    sky130a = find_sky130a(args.pdk_root)
    ngspice = find_ngspice(args.ngspice)
    model_lib = sky130a / "libs.tech" / "combined" / "continuous" / "sky130.lib.spice"
    profiles = build_plan(args)
    print(f"Running {len(profiles)} unique VGS sweeps with {args.jobs} worker(s) ...", flush=True)

    results: dict[Condition, dict[str, np.ndarray]] = {}
    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = {
            executor.submit(
                simulate_condition,
                ngspice=ngspice,
                model_lib=model_lib,
                condition=condition,
                width_um=args.width,
                vgs_step=args.vgs_step,
                timeout=args.timeout,
                force_resim=args.force_resim,
            ): condition
            for condition in profiles
        }
        done = 0
        for future in as_completed(futures):
            condition, data = future.result()
            results[condition] = data
            done += 1
            if done == 1 or done % 10 == 0 or done == len(futures):
                print(f"  completed {done}/{len(futures)}", flush=True)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    raw_path = DATA_DIR / "sky130_nfet_01v8_characterization.tsv"
    lookup_path = DATA_DIR / "sky130_nfet_01v8_lookup.tsv"
    metadata_path = DATA_DIR / "sky130_nfet_01v8_characterization.json"
    report_path = DATA_DIR / "sky130_nfet_01v8_characterization.md"
    length_plot = PLOT_DIR / "sky130_nfet_01v8_length_atlas.png"
    bias_pvt_plot = PLOT_DIR / "sky130_nfet_01v8_bias_pvt_atlas.png"

    write_raw_table(results, profiles, args.width, raw_path)
    write_lookup_table(results, profiles, args.width, args.gmid_targets, lookup_path)
    if not args.full_cross:
        plot_length_atlas(results, args, length_plot)
        plot_bias_pvt(results, args, bias_pvt_plot)
    write_report(results, args, raw_path, lookup_path, report_path)

    metadata = {
        "pdk": "Sky130A",
        "open_pdks_commit": PDK_VERSION,
        "device": DEVICE,
        "model_library": str(model_lib),
        "reference_width_um": args.width,
        "profiles": "full-cross" if args.full_cross else ["core", "pvt"],
        "conditions": len(results),
        "vgs_step_v": args.vgs_step,
        "lengths_um": args.lengths,
        "vds_values_v": args.vds_values,
        "vbs_values_v": args.vbs_values,
        "corners": args.corners,
        "temperatures_c": args.temperatures,
        "gmid_targets_per_v": args.gmid_targets,
        "raw_table": str(raw_path),
        "lookup_table": str(lookup_path),
        "report": str(report_path),
        "plots": [str(length_plot), str(bias_pvt_plot)] if not args.full_cross else [],
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(f"Raw table:    {raw_path}")
    print(f"Lookup table: {lookup_path}")
    print(f"Report:       {report_path}")
    if not args.full_cross:
        print(f"Plots:        {length_plot}")
        print(f"              {bias_pvt_plot}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
