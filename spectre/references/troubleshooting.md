# Spectre Troubleshooting

Start with the simulator exit code and the final summary line. Preserve the
full log; do not diagnose only from console excerpts.

| Symptom | Likely cause | Check or fix |
|---|---|---|
| `spectre: command not found` | Cadence environment not initialized | Locate the qualified installation and use its absolute binary or approved setup script |
| License checkout failure | License server/feature unavailable | Report the requested feature and license path; do not loop retries indefinitely |
| Unknown model or master | Wrong include, section, or primitive name | Reuse ADE/Maestro model configuration and inspect PDK CDF read-only |
| Invalid instance parameter | PDK primitive does not accept the assumed field | Compare CDF `instParameters` and `spectre -h <device>` |
| No outputs were found | Save selection did not match or analysis relaxed to `allpub` | Inspect `TRACE`/`VALUE`; verify instance case and field name |
| Saved `ft` is absent | Model/analysis did not emit that OP field | If appropriate, derive and label `gm/(2*pi*Cgg)` |
| Raw result is binary | Native PSF selected | Re-run with `-format psfascii` or use OCEAN/ViVA |
| Python sees non-UTF-8 bytes and file starts `%TSD-Header-###%` | Managed transfer policy wrapped an uploaded script | If authorized and policy permits shell-created text, use the `ssh-text-deploy` skill; otherwise ask the administrator |
| Executable script reports `Exec format error` | Windows CRLF corrupted the Linux shebang | Normalize `\r` and verify the first line |

## Warnings

Do not suppress all warnings. Classify them:

- PDK include/option redefinition warnings may be expected when the top-level
  deck intentionally includes several voltage domains, but the last effective
  value must be understood.
- Geometry or operating-region warnings can invalidate characterization data.
- Convergence warnings require checking actual points and may need a smaller
  step, better initial conditions, or the PDK-recommended settings.

Report the warning class and count alongside a successful run. A zero exit code
alone does not prove that every requested signal or sweep point is valid.
