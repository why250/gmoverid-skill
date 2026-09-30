"""Characterize GF180MCU vertical BJTs with the official ngspice model."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
MODEL_COMMIT = "9f992d5a9186d1f7820c58f039c484ad35b2edea"
MODEL_URL = (
    "https://raw.githubusercontent.com/google/"
    "globalfoundries-pdk-libs-gf180mcu_fd_pr/"
    f"{MODEL_COMMIT}/models/ngspice/sm141064.ngspice"
)
MODEL_NAME = "sm141064.ngspice"
DEVICES = {
    "vnpn_0p54x2": 0.54 * 2,
    "vnpn_0p54x4": 0.54 * 4,
    "vnpn_0p54x8": 0.54 * 8,
    "vnpn_0p54x16": 0.54 * 16,
    "vnpn_5x5": 25.0,
    "vnpn_10x10": 100.0,
}
DEFAULT_DEVICES = ("vnpn_0p54x2", "vnpn_0p54x4", "vnpn_0p54x8")
MODEL_CORNERS = ("bjt_typical", "bjt_ff", "bjt_ss")
FIELDS = (
    "vbe_v", "ic_a", "ib_a", "jc_ua_um2", "gm_s", "go_s", "cpi_f",
    "cmu_f", "cap_density_ff_um2", "gm_over_ic_vinv", "beta", "gmro",
)


def spice_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def find_ngspice(value: str | None) -> Path:
    if value:
        path = Path(value).expanduser().resolve()
        if path.is_file():
            return path
        raise FileNotFoundError(f"ngspice not found: {path}")
    local = ROOT / ".claude" / "tools" / "Spice64" / "bin" / "ngspice_con.exe"
    if local.is_file():
        return local
    for name in ("ngspice_con", "ngspice"):
        found = shutil.which(name)
        if found:
            return Path(found)
    raise FileNotFoundError("ngspice_con/ngspice not found; use --ngspice")


def find_model(value: str | None) -> Path:
    if value:
        path = Path(value).expanduser().resolve()
        if path.is_dir():
            path = path / "libs.tech" / "ngspice" / MODEL_NAME
        if not path.is_file():
            raise FileNotFoundError(f"GF180MCU model not found: {path}")
        return path
    path = HERE / "models" / MODEL_NAME
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Downloading official GF180MCU model ({MODEL_COMMIT[:12]}) ...", flush=True)
        with urllib.request.urlopen(MODEL_URL, timeout=60) as response:
            payload = response.read()
        if len(payload) < 100_000 or b".LIB bjt_typical" not in payload:
            raise RuntimeError("Downloaded file is not the expected GF180MCU model")
        path.write_bytes(payload)
    return path


def deck(model: Path, corner: str, device: str, data: Path,
         vce: float, vbe_stop: float, vbe_step: float, temp: float) -> str:
    q = "@q.xq1.q0"
    vectors = f"v(b) i(VCE) i(VBE) {q}[gm] {q}[go] {q}[cpi] {q}[cmu]"
    return f"""* GF180MCU BJT characterization: {device}, {corner}
.lib \"{spice_path(model)}\" {corner}
.param sw_stat_global=0 sw_stat_mismatch=0
.temp {temp:g}
.options reltol=1e-5 abstol=1e-15 vntol=1e-9
VCE c 0 {vce:g}
VBE b 0 0
XQ1 c b 0 0 {device}
.control
set wr_singlescale
set wr_vecnames
save {vectors}
dc VBE 0 {vbe_stop:g} {vbe_step:g}
wrdata {spice_path(data)} {vectors}
quit
.endc
.end
"""


def simulate(ngspice: Path, model: Path, corner: str, device: str,
             vce: float, vbe_stop: float, vbe_step: float, temp: float,
             timeout: int) -> dict[str, np.ndarray]:
    log_dir = HERE / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{device}_{corner}_{temp:g}C".replace("-", "m").replace(".", "p")
    circuit = log_dir / f"{stem}.cir"
    output = log_dir / f"{stem}.dat"
    log = log_dir / f"{stem}.log"
    output.unlink(missing_ok=True)
    circuit.write_text(deck(model, corner, device, output, vce,
                            vbe_stop, vbe_step, temp), encoding="ascii")
    result = subprocess.run(
        [str(ngspice), "-b", str(circuit)], cwd=model.parent,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8",
        errors="replace", timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    log.write_text(result.stdout, encoding="utf-8")
    if result.returncode or not output.is_file():
        raise RuntimeError(f"ngspice failed for {device}/{corner}; see {log}")
    raw = np.loadtxt(output, skiprows=1, ndmin=2)
    if raw.shape[1] != 8:
        raise RuntimeError(f"Expected 8 columns, got {raw.shape[1]}; see {log}")
    vbe = raw[:, 1]
    ic = -raw[:, 2]
    ib = -raw[:, 3]
    gm, go, cpi, cmu = raw[:, 4], raw[:, 5], raw[:, 6], raw[:, 7]
    area = DEVICES[device]
    valid = (
        np.isfinite(raw).all(axis=1) & (ic > 0) & (ib > 0) &
        (gm > 0) & (go > 0) & (cpi + cmu > 0)
    )
    if valid.sum() < 10:
        raise RuntimeError(f"Too few valid operating points for {device}/{corner}; see {log}")
    data = {
        "vbe_v": vbe[valid], "ic_a": ic[valid], "ib_a": ib[valid],
        "jc_ua_um2": ic[valid] * 1e6 / area,
        "gm_s": gm[valid], "go_s": go[valid],
        "cpi_f": cpi[valid], "cmu_f": cmu[valid],
        "cap_density_ff_um2": (cpi[valid] + cmu[valid]) * 1e15 / area,
        "gm_over_ic_vinv": gm[valid] / ic[valid],
        "beta": ic[valid] / ib[valid],
        "gmro": gm[valid] / go[valid],
    }
    out_dir = HERE / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / f"{stem}.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(FIELDS)
        writer.writerows(zip(*(data[field] for field in FIELDS)))
    return data


def plot(results: dict[str, dict[str, np.ndarray]], corner: str,
         temp: float, vce: float, min_j: float, max_j: float) -> Path:
    fig, axes = plt.subplots(2, 2, figsize=(12, 8.8))
    specs = (
        ("gm_over_ic_vinv", r"$g_m/I_C$ [$V^{-1}$]"),
        ("beta", r"DC gain $\beta=I_C/I_B$"),
        ("gmro", r"Intrinsic gain $g_m/g_o$"),
        ("cap_density_ff_um2", r"$(C_{\pi}+C_{\mu})/A_E$ [fF/$\mu m^2$]"),
    )
    for device, data in results.items():
        j = data["jc_ua_um2"]
        mask = (j >= min_j) & (j <= max_j)
        if not mask.any():
            raise RuntimeError(f"No {device} points in requested Jc range")
        label = f"{device.removeprefix('vnpn_')} ({DEVICES[device]:g} um2)"
        for ax, (field, ylabel) in zip(axes.flat, specs):
            y = data[field][mask]
            ax.semilogx(j[mask], y, label=label)
            ax.set_ylabel(ylabel)
    for ax in axes.flat:
        ax.set_xlabel(r"$J_C=I_C/A_E$ [$\mu A/\mu m^2$]")
        ax.set_xlim(min_j, max_j)
        ax.grid(True, which="both", alpha=0.3)
        ax.legend(fontsize=8)
    fig.suptitle(f"GF180MCU vertical NPN | {corner} | {temp:g} C | VCE={vce:g} V")
    fig.tight_layout()
    out_dir = HERE / "plots"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"bjt_characterization_{corner}_{temp:g}C.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-lib", help="Official sm141064.ngspice file or GF180 PDK root; downloaded if omitted")
    parser.add_argument("--ngspice", help="Path to ngspice executable")
    parser.add_argument("--devices", nargs="+", choices=tuple(DEVICES), default=list(DEFAULT_DEVICES))
    parser.add_argument("--corner", choices=MODEL_CORNERS, default="bjt_typical")
    parser.add_argument("--temperature", type=float, default=27.0)
    parser.add_argument("--vce", type=float, default=2.0)
    parser.add_argument("--vbe-stop", type=float, default=1.1)
    parser.add_argument("--vbe-step", type=float, default=0.002)
    parser.add_argument("--min-j", type=float, default=0.01, help="Minimum plotted Jc [uA/um2]")
    parser.add_argument("--max-j", type=float, default=100.0, help="Maximum plotted Jc [uA/um2]")
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()
    if args.vce <= 0 or args.vbe_stop <= 0 or args.vbe_step <= 0 or args.min_j <= 0 or args.max_j <= args.min_j:
        parser.error("VCE, VBE and Jc bounds must be positive, with max-j > min-j")
    model = find_model(args.model_lib)
    ngspice = find_ngspice(args.ngspice)
    results = {}
    for device in args.devices:
        print(f"Simulating {device} ({args.corner}) ...", flush=True)
        results[device] = simulate(ngspice, model, args.corner, device,
                                   args.vce, args.vbe_stop, args.vbe_step,
                                   args.temperature, args.timeout)
    image = plot(results, args.corner, args.temperature, args.vce,
                 args.min_j, args.max_j)
    summary = {
        "model": str(model), "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
        "model_commit_if_downloaded": MODEL_COMMIT if not args.model_lib else None,
        "corner": args.corner, "temperature_c": args.temperature,
        "vce_v": args.vce, "devices": list(results), "plot": str(image),
        "ft_note": "No fT is reported: the selected public NPN model cards do not specify forward transit time TF, so their high-frequency prediction is not reliable.",
    }
    summary_path = HERE / "data" / "bjt_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Plot: {image}\nSummary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
