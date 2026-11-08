---
type: index
title: "honua-gp documentation"
description: "Documentation for the Apache-2.0 Honua geoprocessing package."
resource: "https://github.com/honua-io/honua-sdk-python/tree/trunk/packages/honua-gp"
tags: [honua-gp, geoprocessing]
---
# honua-gp documentation

`honua-gp` is an Apache-2.0 package for running supported
geoprocessing operations against a Honua deployment.

## Pointers

- [Compatibility matrix](compatibility-matrix.md)
- [Package README](../../packages/honua-gp/README.md)
- [Import guide](../migration/gp-import.md)
- [Example workflow](../../packages/honua-gp/examples/buffer_clip_roundtrip.py)

## Local commands

```bash
honua-gp matrix --check docs/honua-gp/compatibility-matrix.md
honua-gp matrix --output docs/honua-gp/compatibility-matrix.md
```

Run the output command after updating the package operation manifest, then
commit both generated compatibility matrices.

## Distribution

Releases use trusted publishing, reproducible builds, provenance attestations,
and a wheel SBOM. Install from PyPI:

```bash
pip install honua-gp
```

The package uses Apache-2.0, matching `honua-sdk` and `honua-admin`.
