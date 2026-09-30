# LTspice installation and CLI diagnostics

## Windows executable discovery

The runner checks, in order:

1. An explicit `--ltspice` argument.
2. The `LTSPICE_EXE` environment variable.
3. `LTspice.exe` or `LTspice` on `PATH`.
4. Common ADI locations under `%LOCALAPPDATA%` and `%ProgramFiles%`.

Verify a PATH installation from a newly opened PowerShell terminal:

```powershell
Get-Command LTspice.exe
LTspice.exe -Run -b .\example.cir -ascii
```

Environment changes are not inherited by terminals that were already open.
Set `LTSPICE_EXE` or pass `--ltspice` when LTspice is installed in a custom
location and changing PATH is undesirable.

## Batch outputs

For `example.cir`, batch mode normally creates `example.raw` and `example.log`
beside the netlist. `-ascii` requests a text RAW file that
`ltspice_common.read_ascii_raw()` can parse without another package.

If no RAW file is created, inspect the log first. Common causes are an invalid
model include path, an unsupported model parameter, a malformed analysis
directive, or an output directory that is not writable.

Paths containing spaces are supported when commands are launched as argument
lists, as done by `run_ltspice()`; do not construct a single shell command by
concatenating quoted strings.

## Platform boundary

The provided automation targets Windows LTspice. Native macOS LTspice does not
offer the same command-line switch workflow; use a Windows environment for
this skill's batch examples.
