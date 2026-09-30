# LTspice PTM gm/ID practice

This practice entry runs the independent `ltspice` skill's bundled PTM example
without copying its implementation. It characterizes 180nm, 45nm HP, and 22nm
HP NMOS/PMOS devices and writes LTspice RAW/log files, normalized CSV data, and
a comparison plot to `practice/ltspice/results/`.

From the repository root in a newly opened PowerShell terminal:

```powershell
pwsh .\practice\ltspice\run_ltspice_practice.ps1
```

For a quick one-device smoke test:

```powershell
pwsh .\practice\ltspice\run_ltspice_practice.ps1 -Models 180nm -Polarity nmos -Step 0.02
```

Use `-LtspiceExe` if LTspice is not on PATH. The Python runner also checks
`LTSPICE_EXE` and common ADI installation directories.

