---
name: spectre
description: "Run and troubleshoot Cadence Spectre simulations, including native netlists, foundry-PDK model sections, device operating-point saves, PSFASCII extraction, and remote licensed-server workflows. Use when a task explicitly involves Spectre, ADE/Maestro-generated model configuration, PSF results, or a foundry PDK whose supported simulator is Spectre; do not use for ordinary ngspice-only work."
---

# Cadence Spectre Simulation Skill

Use Spectre in the user's authorized environment without copying proprietary
PDK payloads into the project. Put new netlists, scripts, logs, and results in
the user's working directory; modify this skill only when explicitly asked to
improve the skill itself.

Spectre is a simulator skill, not a process-specific skill. Keep model paths,
corners, device names, voltages, and dimensions in project configuration or a
PDK-specific practice directory.

## Route the task

- For Spectre native netlist and command-line patterns, read
  [`references/netlist-and-cli.md`](references/netlist-and-cli.md).
- For an installed foundry PDK, OA/CDF discovery, corners, and remote execution,
  read [`references/foundry-pdk.md`](references/foundry-pdk.md).
- For PSFASCII parsing or tabular export, read
  [`references/psfascii.md`](references/psfascii.md) and reuse
  [`scripts/parse_psfascii.py`](scripts/parse_psfascii.py).
- For failures, warnings, licensing, or unexpected empty results, read
  [`references/troubleshooting.md`](references/troubleshooting.md).

Read only the references needed for the request.

## Core workflow

1. Confirm the Spectre executable and version in the actual run environment.
2. If a testbench exists, reuse its active model include and corner instead of
   guessing from PDK filenames.
3. Run a minimal operating-point smoke test before a large sweep.
4. Save only required nodes, currents, and device operating-point parameters.
5. Use PSF for Cadence-native viewing or `-format psfascii` for dependency-free
   automation; preserve the simulator log either way.
6. Require a zero exit code, validate point counts and finite values, and
   distinguish model warnings from simulation errors.

Useful discovery commands:

```bash
command -v spectre
spectre -W
spectre -h dc
spectre -h save
spectre -h bsim4
```

Do not assume that an operating-point field exists merely because another
simulator exposes it. Query the installed Spectre help and fall back to a
clearly documented derived quantity when needed.

## Relationship to other skills

- `gmoverid` owns gm/ID methodology, normalized table definitions, plots, and
  transistor sizing. This skill owns the Spectre execution/data path.
- `ngspice` is a separate simulator route with different control syntax and
  output formats; do not mix its `.control`, `wrdata`, or `@m[...]` conventions
  into Spectre native netlists.
- PDK-specific skills or practice folders may provide model names and corners,
  but must not vendor proprietary foundry files.
- If managed `scp`/SFTP transforms an authorized text payload, use the
  `ssh-text-deploy` skill rather than embedding transfer workarounds here.
