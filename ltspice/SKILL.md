---
name: ltspice
description: "Run and automate Windows LTspice simulations from text netlists, parse ASCII RAW results, and characterize the repository's PTM 180/45/22nm NMOS and PMOS models. Use for LTspice CLI, batch simulation, RAW data extraction, or LTspice-based gm/ID examples; do not use for ngspice .control/wrdata syntax or Cadence Spectre PSF workflows."
---

# LTspice Simulation Skill

Use LTspice's Windows batch interface for reproducible text-netlist simulations.
Keep generated netlists, RAW files, logs, CSV files, and plots in the user's
working directory; modify this skill only when explicitly asked to extend it.

## Prerequisites

- LTspice for Windows. The runner discovers `LTspice.exe` from `PATH`,
  `LTSPICE_EXE`, and common ADI installation locations.
- Python 3 with NumPy and Matplotlib.
- For installation, PATH setup, and command-line diagnostics, read
  [`references/installation.md`](references/installation.md).

## Assets

```text
assets/
|-- ltspice_common.py          LTspice discovery, batch runner, ASCII RAW parser
|-- run_ptm_gmoverid.py        PTM 180/45/22nm NMOS/PMOS gm/ID example
|-- models/
|   |-- ptm180.lib
|   |-- ptm45hp.lib
|   `-- ptm22hp.lib
`-- netlist/
    |-- gmoverid_nmos.cir.tmpl
    `-- gmoverid_pmos.cir.tmpl
```

The model copies make the deployed skill self-contained. They match the PTM
files used by the repository's `gmoverid` skill.

## Core workflow

1. Copy the needed files from `assets/` into the user's project directory.
2. Discover LTspice with `find_ltspice()`; honor an explicit `--ltspice` path.
3. Generate a text `.cir` netlist with an ordinary `.dc`, `.ac`, or `.tran`
   directive. Do not use ngspice `.control` or `wrdata` blocks.
4. Run `LTspice.exe -Run -b <netlist> -ascii` and preserve the sibling `.raw` and
   `.log` files.
5. Treat a missing RAW file, nonzero return code, or `Fatal Error` in the log
   as a failed simulation.
6. Parse the ASCII RAW file, validate point count, finiteness, monotonic sweep
   order, and basic circuit invariants before plotting or deriving metrics.

Prefer binary RAW for large interactive simulations, but use `-ascii` for
small automated examples because it is deterministic and needs no third-party
RAW dependency.

## PTM gm/ID example

From a directory containing the deployed assets:

```powershell
python .\run_ptm_gmoverid.py --models all --polarity both --output-dir .\ltspice-results
```

To run a quick smoke test:

```powershell
python .\run_ptm_gmoverid.py --models 180nm --polarity nmos --step 0.02 --output-dir .\smoke
```

Outputs include one CSV per model/polarity, a combined CSV and plot, plus the
source netlists, LTspice RAW files, and logs under `raw/`. Each CSV also has an
identical `.csv.txt` mirror for managed Windows systems that transparently
protect files based on the `.csv` extension.

The example derives `gm` numerically from the DC current sweep and reports
positive magnitudes for NMOS and PMOS. It is a simulator-integration example;
use the `gmoverid` skill for the full sizing API, capacitance model, `fT`, and
`gm*r_o` workflow.

## Simulator boundaries

- LTspice, ngspice, and Spectre have different control languages and result
  formats. Share circuit intent and normalized CSV columns, not simulator-
  specific netlist directives.
- PTM models are educational predictive models. Do not present their results
  as sign-off data for a manufactured process.
- For proprietary PDKs, use only the model entry point and simulator supported
  by that PDK; do not copy licensed model payloads into this skill.
