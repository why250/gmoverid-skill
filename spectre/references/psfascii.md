# PSFASCII Extraction

Use PSFASCII when results must be processed without Cadence Python bindings,
OCEAN, numpy, or matplotlib. Keep native PSF when ViVA/OCEAN is the intended
consumer.

## File structure

A simple DC sweep normally contains:

```text
HEADER
TYPE
SWEEP
TRACE
VALUE
"VSWEEP" 0.000000000000000e+00
"M0:ids"  1.234000000000000e-10
...
"VSWEEP" 5.000000000000000e-03
...
END
```

The sweep key begins each row. `TYPE` and `TRACE` define metadata; numeric data
needed for simple tables appears after `VALUE`.

## Included parser

`scripts/parse_psfascii.py` converts a one-dimensional numeric sweep to CSV:

```bash
python scripts/parse_psfascii.py results.raw/dc1.dc results.csv \
  --sweep VSWEEP \
  --signal id_a=M0:ids \
  --signal gm_s=M0:gm \
  --signal gds_s=M0:gds \
  --signal cgg_f=M0:cgg \
  --absolute id_a --absolute gm_s --absolute gds_s --absolute cgg_f \
  --expected-points 221
```

The parser validates duplicate aliases, missing traces, finite numeric values,
and optional point count. It intentionally handles a simple one-dimensional
sweep only. Nested sweeps, complex AC data, families, and transient structures
should use an analysis-specific parser or OCEAN.

## Normalization guidance

- Preserve raw names and units in metadata or code comments.
- State whether current signs are simulator-native or converted to magnitudes.
- Do not silently replace a missing field with a derived value. Name and
  document derived columns, for example `ft_hz = gm/(2*pi*cgg)`.
- Keep the original PSF/PSFASCII and simulator log next to processed data for
  reproducibility.
