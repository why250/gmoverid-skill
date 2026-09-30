# Multi-dimensional gm/ID characterization and explorer

Use this reference when characterizing an installed ngspice-compatible foundry
PDK, building a multi-dimensional MOS lookup table, or presenting that table in
an interactive explorer. Ordinary PTM characterization and single-table sizing
do not need this reference.

## 1. Source of truth and model boundary

Keep the foundry PDK external and versioned. Record the PDK/model version and
include its library from the installed location; do not flatten, copy, or edit
foundry model cards.

Many PDK devices are subcircuit wrappers. Discover and verify the internal
compact-model instance before extracting operating-point values. Save internal
values during the sweep rather than relying on the final operating point.

The normalized table, not a rendered plot, is the source of truth. Static plots
and the interactive explorer are views over that table.

## 2. Characterization profiles

A full Cartesian product of process, temperature, geometry, and bias is often
unnecessarily expensive. The default database should use two complementary
profiles:

| Profile | Swept dimensions | Fixed dimensions | Purpose |
|---|---|---|---|
| `core` | `L × VDS × VBS × VGS` | nominal corner and temperature | Design lookup and bias/geometry exploration |
| `pvt` | `corner × temperature × VGS` | nominal L, VDS, and VBS | Process and temperature sensitivity |

Deduplicate the nominal condition shared by both profiles and label it
`core+pvt`. Generate the full
`corner × temperature × L × VDS × VBS × VGS` product only when the user needs
combined PVT/geometry queries and accepts the additional simulation cost.

Choose sweep values from the device's legal operating range and design needs.
For the Sky130 1.8 V NFET example, the validated first-pass grid is:

```text
L           = 0.15, 0.30, 0.50, 1.00 um
VDS         = 0.10, 0.30, 0.60, 0.90, 1.20, 1.80 V
VBS         = 0, -0.30, -0.60 V
corner      = tt, ff, ss, fs, sf
temperature = -40, 27, 125 C
VGS         = 0 ... 1.8 V, step 10 mV
```

These values are an example, not universal MOS limits. Parameterize them for a
different device, voltage class, or PDK.

## 3. Extracted quantities and conventions

At each VGS point, retain the independent dimensions and these device values:

```text
VGS, VTH, VOV, VDSAT,
ID, ID/W, gm, gds, gmb, gmb/gm,
gm/ID, gm/gds, fT,
Cgg, Cgs, Cgd, Cgb, Cdb
```

Derived quantities:

```text
gm/ID = gm / abs(ID)
gm/gds = gm / gds
fT = gm / (2*pi*Cgg)
ID/W = abs(ID) / W
VOV = VGS - VTH
```

Normalize current sign so NMOS and PMOS tables store positive current
magnitudes. Preserve polarity and terminal orientation in metadata.

ngspice compact models expose capacitance-matrix cross derivatives with signed
charge conventions. If the table is intended for design parasitics, store the
magnitude of `Cgs`, `Cgd`, `Cgb`, and `Cdb` and document that choice. Keep `Cgg`
positive for the fT calculation. Do not silently mix signed matrix derivatives
and positive parasitic magnitudes in one schema.

## 4. Raw and lookup tables

Prefer a long-form, delimiter-separated raw table with one row per VGS sample.
Use stable ASCII column names and carry units in the names where ambiguity is
likely.

Required condition columns:

```text
profiles, device, corner, temperature_c, width_um,
length_um, vds_v, vbs_v
```

Recommended metric columns:

```text
vgs_v, vth_v, vov_v, vdsat_v,
id_a, id_w_ua_per_um,
gm_s, gds_s, gmb_s, gmb_over_gm,
cgg_f, cgs_f, cgd_f, cgb_f, cdb_f,
gmid_per_v, gmro, ft_hz
```

Generate a smaller design lookup table at requested gm/ID targets. Add an
explicit Boolean `available` column. When a target is outside the simulated
inversion branch, set `available=false` and leave interpolated fields empty;
never extrapolate.

TSV is a good default for a local workflow: it remains human-readable, imports
cleanly into spreadsheet tools, and avoids comma/locale ambiguity. Emit a JSON
metadata sidecar containing the PDK version, model path, device, sweep grid,
reference width, profile definition, output paths, and generation settings.

## 5. Inversion branch and interpolation

gm/ID versus VGS can be double-valued near very low current. Apply one branch
rule consistently in table generation, static plots, and the web explorer:

1. Reject non-finite points and points below a meaningful current floor.
2. Find the gm/ID peak among the remaining samples.
3. Retain samples from that peak toward increasing VGS.
4. Restrict the supported gm/ID interval to the characterized design range.
5. Sort the retained samples by gm/ID before interpolation.
6. Interpolate within the retained range only.

For the validated Sky130 workflow, the current floor is `ID > 1e-12 A` and the
stored branch is limited to `3 <= gm/ID <= 30 V^-1`; user-facing charts focus on
`4 ... 24 V^-1`.

High temperature increases thermal voltage and lowers the weak-inversion
gm/ID ceiling. A target such as `20 V^-1` may therefore be unavailable at some
125 C corners. Treat this as a physical boundary when the raw sweep and branch
rule agree, not as a simulation failure.

## 6. Interactive explorer contract

Keep the explorer a view over the raw table. A local static implementation is
usually sufficient: HTML, CSS, and JavaScript can fetch the TSV through a small
local HTTP server without a database or build tool.

Provide two modes:

- **Explore** selects one condition. Each filter must expose only values that
  form a condition actually present in the sparse `core+pvt` database.
- **Compare** varies exactly one dimension while holding the other dimensions
  at a documented valid cross-section. Let users hide individual series.

Use linked charts for at least `ID/W`, `gm/gds`, `fT`, and `VGS` versus gm/ID.
A shared gm/ID cursor must update every chart and the operating-point table.
Show the selected condition, units, the interpolated values, and a visible
unavailable state. Useful local actions are copying the current operating point
and exporting the selected curve slice.

Keep interaction accessible:

- native labeled selects, checkboxes, range, and number inputs;
- semantic tabs with `aria-selected` and associated tab panels;
- keyboard-operable cursor and series controls;
- an `aria-live` status for loading, copying, and availability changes;
- responsive single-column layout at narrow widths;
- color plus text labels for every compared series.

Serve the page over localhost rather than opening `index.html` directly,
because browsers commonly block `fetch()` of sibling data files under
`file://`.

## 7. Validation and acceptance

Validate the generated database before trusting the UI:

- every condition has the expected VGS sample count;
- all requested condition tuples are present and the shared nominal point is
  deduplicated;
- simulation logs contain no parse, convergence, or fatal errors;
- lookup rows are finite when `available=true` and empty when unavailable;
- at fixed gm/ID, increasing L generally raises intrinsic gain and lowers fT;
- reverse body bias raises the VGS required for the same gm/ID;
- ID/W decreases from strong toward weak inversion on the retained branch;
- a few representative points agree between raw-table interpolation, the
  compact lookup table, static plots, and the explorer.

Browser acceptance checks:

1. The displayed condition and point counts match the generated metadata.
2. Changing a filter updates all four charts and the operating-point table.
3. Dragging or typing the gm/ID cursor updates every linked view.
4. Compare dimension changes produce the expected fixed cross-section and
   series labels; hiding a series removes its values everywhere.
5. An intentionally unavailable high-temperature point shows no stale values.
6. The page has no console errors at desktop width and a narrow mobile width.
7. Keyboard navigation reaches tabs, filters, cursor, series toggles, and
   export actions in logical order.

## 8. Porting to another device

For another NMOS, PMOS, or voltage class, rediscover the wrapper's internal
device path and supported operating-point names. Adjust voltage polarity,
current sign, body-bias direction, legal voltage range, geometry grid, and
corners. Keep the table schema and branch/availability contract stable so the
same sizing and explorer logic can consume the new dataset.
