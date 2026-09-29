"""Generate gm/ID characterization curves from the real Sky130A PDK.

The script characterizes sky130_fd_pr__nfet_01v8 directly through ngspice.
Unlike the PTM exercise, gm, gds, Cgg, and Vth are read from the internal
BSIM device inside the Sky130A subcircuit.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parents[1]
LOG_DIR = BASE_DIR / "logs"
PLOT_DIR = BASE_DIR / "plots"
DATA_DIR = BASE_DIR / "data"
PDK_VERSION = "c6d73a35f524070e85faff4a6a9eef49553ebc2b"
DEVICE = "sky130_fd_pr__nfet_01v8"
INTERNAL_DEVICE = "m.xn1.msky130_fd_pr__nfet_01v8"
DEFAULT_CORNERS = ("tt", "ff", "ss", "fs", "sf")


def spice_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def find_sky130a(value: str) -> Path:
    root = Path(value).expanduser().resolve()
    candidates = (root, root / "sky130A")
    for candidate in candidates:
        lib = candidate / "libs.tech" / "combined" / "continuous" / "sky130.lib.spice"
        if lib.is_file():
            return candidate
    raise FileNotFoundError(f"Cannot find a Sky130A continuous model below {root}")


def find_ngspice(value: str | None) -> Path:
    if value:
        candidate = Path(value).expanduser().resolve()
        if candidate.is_file():
            return candidate
        raise FileNotFoundError(f"ngspice executable does not exist: {candidate}")

    local = PROJECT_ROOT / ".claude" / "tools" / "Spice64" / "bin" / "ngspice_con.exe"
    if local.is_file():
        return local
    for name in ("ngspice_con", "ngspice"):
        resolved = shutil.which(name)
        if resolved:
            return Path(resolved)
    raise FileNotFoundError("ngspice_con/ngspice was not found")


def make_deck(
    *, model_lib: Path, corner: str, data_path: Path, width_um: float,
    length_um: float, vds: float, vgs_step: float, temperature_c: float,
) -> str:
    dev = INTERNAL_DEVICE
    return f"""* Sky130A gm/ID characterization: {DEVICE}, corner={corner}
.lib \"{spice_path(model_lib)}\" {corner}
.temp {temperature_c:g}
.options reltol=1e-5 abstol=1e-14 vntol=1e-8

VDS d 0 {vds:g}
VGS g 0 0
XN1 d g 0 0 {DEVICE} l={length_um:g} w={width_um:g} nf=1

.control
set wr_singlescale
set wr_vecnames
save v(g) i(VDS) @{dev}[gm] @{dev}[gds] @{dev}[cgg] @{dev}[vth]
dc VGS 0 1.8 {vgs_step:g}
wrdata {spice_path(data_path)} v(g) i(VDS) @{dev}[gm] @{dev}[gds] @{dev}[cgg] @{dev}[vth]
quit
.endc
.end
"""


def simulate_corner(
    *, ngspice: Path, model_lib: Path, corner: str, width_um: float,
    length_um: float, vds: float, vgs_step: float, temperature_c: float,
    timeout: int,
) -> dict[str, np.ndarray]:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cir_path = LOG_DIR / f"sky130_gmid_{corner}.spice"
    log_path = LOG_DIR / f"sky130_gmid_{corner}.log"
    raw_path = LOG_DIR / f"sky130_gmid_{corner}.dat"
    table_path = DATA_DIR / f"sky130_gmid_{corner}.tsv"
    raw_path.unlink(missing_ok=True)

    cir_path.write_text(
        make_deck(
            model_lib=model_lib,
            corner=corner,
            data_path=raw_path,
            width_um=width_um,
            length_um=length_um,
            vds=vds,
            vgs_step=vgs_step,
            temperature_c=temperature_c,
        ),
        encoding="ascii",
    )
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
        raise RuntimeError(
            f"Sky130A simulation failed for corner={corner}; see {log_path}"
        )

    # wr_singlescale emits: sweep, Vgs, I(VDS), gm, gds, Cgg, Vth.
    raw = np.loadtxt(raw_path, skiprows=1)
    if raw.ndim != 2 or raw.shape[1] != 7:
        raise RuntimeError(f"Unexpected wrdata shape {raw.shape} for {corner}")

    vgs = raw[:, 1]
    drain_current = np.maximum(-raw[:, 2], 1e-30)
    gm = np.maximum(raw[:, 3], 0.0)
    gds = np.maximum(raw[:, 4], 1e-30)
    cgg = np.maximum(raw[:, 5], 1e-30)
    vth = raw[:, 6]
    gmid = gm / drain_current
    id_w = drain_current / width_um * 1e6  # uA/um
    ft = gm / (2.0 * math.pi * cgg)
    gmro = gm / gds
    vov = vgs - vth

    data = {
        "vgs_v": vgs,
        "vth_v": vth,
        "vov_v": vov,
        "id_a": drain_current,
        "id_w_ua_per_um": id_w,
        "gm_s": gm,
        "gds_s": gds,
        "cgg_f": cgg,
        "gmid_per_v": gmid,
        "ft_hz": ft,
        "gmro": gmro,
    }
    with table_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(data.keys())
        writer.writerows(zip(*data.values()))
    return data


def inversion_branch(data: dict[str, np.ndarray]) -> np.ndarray:
    gmid = data["gmid_per_v"]
    current = data["id_a"]
    finite = np.isfinite(gmid) & (current > 1e-12)
    indexes = np.flatnonzero(finite)
    if not len(indexes):
        raise RuntimeError("No valid inversion points were generated")
    peak = indexes[np.argmax(gmid[indexes])]
    return (np.arange(len(gmid)) >= peak) & finite & (gmid >= 4.0) & (gmid <= 24.0)


def plot_results(results: dict[str, dict[str, np.ndarray]], output: Path) -> None:
    colors = ["#1565C0", "#E65100", "#2E7D32", "#C62828", "#7B1FA2"]
    styles = ["-", "--", "-.", ":", (0, (5, 2, 1, 2))]
    fig, axes = plt.subplots(2, 2, figsize=(13.2, 9.4))

    for index, (corner, data) in enumerate(results.items()):
        color = colors[index % len(colors)]
        style = styles[index % len(styles)]
        branch = inversion_branch(data)
        gmid = data["gmid_per_v"]
        label = corner.upper()
        valid = np.isfinite(gmid) & (data["id_a"] > 1e-12)

        axes[0, 0].plot(data["vov_v"][valid], gmid[valid], color=color, linestyle=style, label=label)
        axes[0, 1].semilogy(gmid[branch], data["id_w_ua_per_um"][branch], color=color, linestyle=style, label=label)
        axes[1, 0].plot(gmid[branch], data["ft_hz"][branch] / 1e9, color=color, linestyle=style, label=label)
        axes[1, 1].plot(gmid[branch], data["gmro"][branch], color=color, linestyle=style, label=label)

    axes[0, 0].set_title(r"$g_m/I_D$ vs $V_{OV}$")
    axes[0, 0].set_xlabel(r"$V_{OV}=V_{GS}-V_{TH}$ [V]")
    axes[0, 0].set_ylabel(r"$g_m/I_D$ [$V^{-1}$]")
    axes[0, 0].set_ylim(bottom=0)

    axes[0, 1].set_title(r"$I_D/W$ vs $g_m/I_D$")
    axes[0, 1].set_xlabel(r"$g_m/I_D$ [$V^{-1}$]")
    axes[0, 1].set_ylabel(r"$I_D/W$ [$\mu A/\mu m$]")

    axes[1, 0].set_title(r"$f_T$ vs $g_m/I_D$")
    axes[1, 0].set_xlabel(r"$g_m/I_D$ [$V^{-1}$]")
    axes[1, 0].set_ylabel(r"$f_T$ [GHz]")
    axes[1, 0].set_ylim(bottom=0)

    axes[1, 1].set_title(r"Intrinsic Gain vs $g_m/I_D$")
    axes[1, 1].set_xlabel(r"$g_m/I_D$ [$V^{-1}$]")
    axes[1, 1].set_ylabel(r"$g_m r_o$")
    axes[1, 1].set_ylim(bottom=0)

    for axis in axes.flat:
        axis.grid(True, which="both", alpha=0.35)
        axis.legend()
    for axis in (axes[0, 1], axes[1, 0], axes[1, 1]):
        axis.set_xlim(4, 24)
        axis.set_xticks(np.arange(4, 25, 2))

    fig.suptitle(
        "Sky130A nfet_01v8 gm/ID Characterization — W=1.0um, L=0.15um, VDS=0.9V",
        fontsize=15,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.965))
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdk-root", required=True, help="Direct sky130A path or its parent")
    parser.add_argument("--ngspice", help="Path to ngspice_con/ngspice")
    parser.add_argument("--corners", nargs="+", default=list(DEFAULT_CORNERS))
    parser.add_argument("--width", type=float, default=1.0, help="Device width [um]")
    parser.add_argument("--length", type=float, default=0.15, help="Device length [um]")
    parser.add_argument("--vds", type=float, default=0.9, help="Drain voltage [V]")
    parser.add_argument("--vgs-step", type=float, default=0.005, help="Gate sweep step [V]")
    parser.add_argument("--temperature", type=float, default=27.0, help="Temperature [C]")
    parser.add_argument("--timeout", type=int, default=60, help="Per-corner timeout [s]")
    args = parser.parse_args()

    sky130a = find_sky130a(args.pdk_root)
    ngspice = find_ngspice(args.ngspice)
    model_lib = sky130a / "libs.tech" / "combined" / "continuous" / "sky130.lib.spice"

    results: dict[str, dict[str, np.ndarray]] = {}
    for corner in args.corners:
        print(f"Simulating Sky130A corner {corner} ...", flush=True)
        results[corner] = simulate_corner(
            ngspice=ngspice,
            model_lib=model_lib,
            corner=corner,
            width_um=args.width,
            length_um=args.length,
            vds=args.vds,
            vgs_step=args.vgs_step,
            temperature_c=args.temperature,
            timeout=args.timeout,
        )

    output = PLOT_DIR / "gmoverid_sky130_nfet_01v8_L150nm.png"
    plot_results(results, output)

    summary: dict[str, object] = {
        "pdk": "Sky130A",
        "open_pdks_commit": PDK_VERSION,
        "model_library": str(model_lib),
        "device": DEVICE,
        "width_um": args.width,
        "length_um": args.length,
        "vds_v": args.vds,
        "temperature_c": args.temperature,
        "corners": {},
        "plot": str(output),
    }
    corner_summary: dict[str, object] = {}
    for corner, data in results.items():
        branch = inversion_branch(data)
        corner_summary[corner] = {
            "points": int(len(data["vgs_v"])),
            "gmid_peak_per_v": float(np.nanmax(data["gmid_per_v"])),
            "ft_peak_ghz": float(np.nanmax(data["ft_hz"][branch]) / 1e9),
            "gmro_peak": float(np.nanmax(data["gmro"][branch])),
            "id_at_vgs_0p9_ua": float(np.interp(0.9, data["vgs_v"], data["id_a"]) * 1e6),
        }
    summary["corners"] = corner_summary
    summary_path = DATA_DIR / "sky130_gmid_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Plot: {output}")
    print(f"Summary: {summary_path}")
    for corner, item in corner_summary.items():
        print(
            f"{corner.upper():>2}: gm/ID_peak={item['gmid_peak_per_v']:.2f}  "
            f"fT_peak={item['ft_peak_ghz']:.2f}GHz  "
            f"gmro_peak={item['gmro_peak']:.2f}  "
            f"Id@0.9V={item['id_at_vgs_0p9_ua']:.2f}uA"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
