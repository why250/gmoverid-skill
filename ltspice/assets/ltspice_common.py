#!/usr/bin/env python3
"""Shared Windows LTspice batch runner and ASCII RAW reader."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class LtspiceResult:
    netlist: Path
    raw: Path
    log: Path
    returncode: int
    console: str


@dataclass(frozen=True)
class RawData:
    properties: dict[str, str]
    names: tuple[str, ...]
    kinds: tuple[str, ...]
    values: np.ndarray

    def trace(self, name: str) -> np.ndarray:
        wanted = name.casefold()
        for index, candidate in enumerate(self.names):
            if candidate.casefold() == wanted:
                return self.values[:, index]
        available = ", ".join(self.names)
        raise KeyError(f"RAW trace {name!r} not found; available: {available}")


def find_ltspice(explicit: str | Path | None = None) -> Path:
    """Locate LTspice.exe, preferring caller and environment configuration."""
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    if os.environ.get("LTSPICE_EXE"):
        candidates.append(Path(os.environ["LTSPICE_EXE"]).expanduser())

    for command in ("LTspice.exe", "LTspice"):
        resolved = shutil.which(command)
        if resolved:
            candidates.append(Path(resolved))

    for root_name in ("LOCALAPPDATA", "ProgramFiles", "ProgramW6432"):
        root = os.environ.get(root_name)
        if root:
            candidates.append(Path(root) / "Programs" / "ADI" / "LTspice" / "LTspice.exe")
            candidates.append(Path(root) / "ADI" / "LTspice" / "LTspice.exe")

    checked: list[str] = []
    for candidate in candidates:
        candidate = candidate.resolve(strict=False)
        label = str(candidate).casefold()
        if label in checked:
            continue
        checked.append(label)
        if candidate.is_file():
            return candidate

    raise FileNotFoundError(
        "LTspice.exe was not found. Put its directory on PATH, set "
        "LTSPICE_EXE, or pass --ltspice <path>."
    )


def run_ltspice(
    netlist: str | Path,
    executable: str | Path | None = None,
    timeout: float = 120.0,
) -> LtspiceResult:
    """Run a text netlist in LTspice batch mode and require RAW output."""
    netlist_path = Path(netlist).resolve()
    if not netlist_path.is_file():
        raise FileNotFoundError(netlist_path)
    exe = find_ltspice(executable)
    raw_path = netlist_path.with_suffix(".raw")
    log_path = netlist_path.with_suffix(".log")
    for stale in (raw_path, log_path):
        if stale.exists():
            stale.unlink()

    kwargs: dict[str, object] = {
        # Current Windows LTspice requires -Run as well as -b. Without -Run it
        # opens the netlist in the GUI and the process does not finish in batch.
        "args": [str(exe), "-Run", "-b", str(netlist_path), "-ascii"],
        "cwd": str(netlist_path.parent),
        "capture_output": True,
        "text": True,
        "errors": "replace",
        "timeout": timeout,
        "stdin": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    completed = subprocess.run(**kwargs)
    console = (completed.stdout + completed.stderr).strip()
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""

    failures: list[str] = []
    if completed.returncode != 0:
        failures.append(f"exit code {completed.returncode}")
    if re.search(r"\bfatal error\b", log_text, re.IGNORECASE):
        failures.append("Fatal Error in LTspice log")
    if not raw_path.is_file() or raw_path.stat().st_size == 0:
        failures.append("RAW output was not created")
    if failures:
        detail = "\n".join((console + "\n" + log_text).splitlines()[:60])
        raise RuntimeError(f"LTspice failed ({', '.join(failures)}):\n{detail}")

    return LtspiceResult(netlist_path, raw_path, log_path, completed.returncode, console)


_FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?"
_POINT_RE = re.compile(rf"^\s*(\d+)\s+({_FLOAT})(?:\s+.*)?$")
_VALUE_RE = re.compile(_FLOAT)


def _decode_raw(path: Path) -> str:
    payload = path.read_bytes()
    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        return payload.decode("utf-16", errors="replace")
    if b"\x00" in payload[:256]:
        return payload.decode("utf-16-le", errors="replace")
    return payload.decode("utf-8", errors="replace")


def read_ascii_raw(path: str | Path) -> RawData:
    """Parse a real-valued LTspice ASCII RAW file into a dense NumPy matrix."""
    raw_path = Path(path)
    lines = _decode_raw(raw_path).splitlines()
    variables_index = next(
        (i for i, line in enumerate(lines) if line.strip().casefold() == "variables:"),
        None,
    )
    values_index = next(
        (i for i, line in enumerate(lines) if line.strip().casefold() == "values:"),
        None,
    )
    binary_index = next(
        (i for i, line in enumerate(lines) if line.strip().casefold() == "binary:"),
        None,
    )
    if binary_index is not None and values_index is None:
        raise ValueError(f"{raw_path} is binary; rerun LTspice with -ascii")
    if variables_index is None or values_index is None or variables_index >= values_index:
        raise ValueError(f"{raw_path} is not a recognized LTspice ASCII RAW file")

    properties: dict[str, str] = {}
    for line in lines[:variables_index]:
        if ":" in line:
            key, value = line.split(":", 1)
            properties[key.strip()] = value.strip()

    variables: list[tuple[int, str, str]] = []
    for line in lines[variables_index + 1 : values_index]:
        match = re.match(r"^\s*(\d+)\s+(\S+)\s+(\S+)", line)
        if match:
            variables.append((int(match.group(1)), match.group(2), match.group(3)))
    variables.sort(key=lambda item: item[0])
    if not variables:
        raise ValueError(f"{raw_path} contains no variable definitions")

    count = len(variables)
    records: list[list[float]] = []
    current: list[float] = []
    for line in lines[values_index + 1 :]:
        if not line.strip():
            continue
        point_match = _POINT_RE.match(line)
        if point_match:
            if current:
                if len(current) != count:
                    raise ValueError(
                        f"point {len(records)} has {len(current)} values; expected {count}"
                    )
                records.append(current)
            current = [float(point_match.group(2))]
            continue
        numeric = _VALUE_RE.findall(line)
        if numeric:
            current.extend(float(token) for token in numeric)
    if current:
        if len(current) != count:
            raise ValueError(f"point {len(records)} has {len(current)} values; expected {count}")
        records.append(current)

    if not records:
        raise ValueError(f"{raw_path} contains no data points")
    values = np.asarray(records, dtype=float)
    expected_points = properties.get("No. Points")
    if expected_points and values.shape[0] != int(expected_points):
        raise ValueError(
            f"RAW header declares {expected_points} points but parsed {values.shape[0]}"
        )
    if not np.all(np.isfinite(values)):
        raise ValueError(f"{raw_path} contains non-finite values")
    return RawData(
        properties,
        tuple(item[1] for item in variables),
        tuple(item[2] for item in variables),
        values,
    )
