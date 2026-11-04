---
type: index
title: "honua-gp documentation"
description: "Documentation for the separately licensed Honua geoprocessing package."
resource: "https://github.com/honua-io/honua-sdk-python/tree/trunk/packages/honua-gp"
tags: [honua-gp, geoprocessing]
---
# honua-gp documentation

`honua-gp` is a separately licensed package for running supported
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

The package is proprietary and is not published by the public CI workflow.
Its license and package metadata describe the distribution restrictions.
