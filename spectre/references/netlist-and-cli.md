# Spectre Native Netlists and CLI

Use the installed simulator's `spectre -h <topic>` output as the authority for
the deployed version. The patterns below cover the stable core used by this
skill.

## Batch execution

```bash
spectre -64 +log spectre.log -format psfascii testbench.scs
```

- `+log <file>` preserves the main simulator log.
- `-format psfascii` makes results text-readable. Omit it when Cadence PSF and
  ViVA/OCEAN are the intended post-processing path.
- Run from a dedicated result directory so generated `*.raw/` data does not
  mix with source netlists.

Treat environment setup and licenses as part of the run environment. Do not
silently replace Spectre with another simulator for a foundry-qualified deck.

## Minimal native netlist

```spectre
simulator lang=spectre
include "/authorized/pdk/models/spectre/toplevel.scs" section=top_tt

parameters VGS=0.7 VDS=0.55
Vg (g 0) vsource dc=VGS
Vd (d 0) vsource dc=VDS
M0 (d g 0 0) nch w=1u l=40n

save M0:ids M0:gm M0:gds M0:cgg M0:vth M0:vdsat
dcOp dc oppoint=rawfile
```

The include, section, model name, terminal order, dimensions, and voltage must
come from the target PDK/testbench, not from this example.

## Parameter sweep

```spectre
parameters VSWEEP=0 VDS=0.55
Vg (g 0) vsource dc=VSWEEP
Vd (d 0) vsource dc=VDS
M0 (d g 0 0) nch w=1u l=40n
save M0:ids M0:gm M0:gds M0:cgg
dc1 dc param=VSWEEP start=0 stop=1.1 step=0.005
```

To reduce PDK parsing time, multiple devices may share `VSWEEP` while using
different fixed drain sources. This produces several bias curves in one DC
analysis.

## Other analyses

Verify exact parameters with local help before authoring a new deck:

```bash
spectre -h ac
spectre -h tran
spectre -h noise
```

Common shapes are:

```spectre
ac1 ac start=1 stop=1G dec=100
tran1 tran stop=1u maxstep=1n
```

Noise and specialized analyses require probe/source choices specific to the
circuit. Do not paste ngspice `.control` blocks into a Spectre netlist.

## Save semantics

Spectre accepts device operating-point selections such as:

```spectre
save M0:oppoint
save M0:ids M0:gm M0:gds M0:cgg
save VDD:p out
```

Use `spectre -h save` and `spectre -h <device>` to confirm valid field names.
For BSIM4, common fields include `ids`, `gm`, `gds`, `cgg`, `cgd`, `cgs`,
`vth`, `vdsat`, `gmoverid`, `self_gain`, and sometimes `ft`/`fug`. A field
listed by help may still be absent from a particular analysis result; verify
the raw output rather than assuming it was written.
