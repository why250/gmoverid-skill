# Foundry PDK Workflow

Use this workflow when the user provides an installed PDK and its supported
Spectre environment. It does not convert, redistribute, or copy proprietary
models.

## Authorized boundary

- Use only the host and PDK/test-library paths supplied by the user.
- Discover the PDK read-only. Create outputs in a new, clearly named directory
  under the authorized test area; do not change existing OA cells by default.
- Keep PDK contents and derived characterization data on the authorized host
  unless the user explicitly requests transfer and policy permits it.

## Reuse the active model selection

Inspect the existing ADE/Maestro state before choosing a file or corner.
Prefer the exact top-level include and section active in the test library.
Record:

- Spectre executable and version;
- model include and section/corner;
- primitive model names and terminal order;
- nominal supply and device flavor;
- CDF default drawn `L`, `W`, and finger count.

For OpenAccess PDKs, CDF data may be stored in a cell's `data.dm`. A read-only
`strings` inspection can expose descriptions and defaults. Do not infer minimum
drawn length solely from the process marketing node, and do not parse binary OA
views by rewriting them.

## Smoke test before characterization

Instantiate one standard device at a nominal bias and save `ids`, `gm`, `gds`,
and `cgg`. Confirm model loading, license checkout, convergence, units, and raw
output before expanding the sweep.

For device characterization:

- combine several fixed drain biases into one gate sweep when practical;
- use source/body at zero with negative gate/drain voltages for a normalized
  PMOS testbench, then report magnitude conventions explicitly;
- preserve the PDK's drawn dimensions and state whether layout-dependent
  parameters are absent;
- label primitive-only results as pre-layout.

Diffusion geometry, fingers, stress, WPE/LOD, mismatch, and extracted
parasitics require PDK-specific instance parameters or extracted views. Do not
imply that a bare `w/l` primitive captures them.

## Managed-server transfer policy

Some managed IC servers wrap Python files received through `scp`; the remote
file begins with `%TSD-Header-###%` and Python reports a non-UTF-8 syntax error.
Do not decrypt files or modify security tooling.

When the user authorizes the exact destination and server policy permits
shell-created text files, use the `ssh-text-deploy` skill for atomic stdin
deployment, LF normalization, SHA-256 verification, and TSD-header detection.
If policy blocks that route too, stop and request the administrator-approved
mechanism.
