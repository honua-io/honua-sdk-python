---
type: guide
title: "Import the geoprocessing package"
description: "How to import honua-gp, and the unpublished re-export distribution that was removed."
---
# Geoprocessing import

`honua-gp` is the geoprocessing distribution. Import it as `honua_gp`:

```python
import honua_gp as arcpy

arcpy.configure(base_url="https://honua.example.com", api_key="...")
```

Point the session at a Honua base URL, then call the supported tools. The
package README
([`packages/honua-gp/README.md`](../../packages/honua-gp/README.md)) and the
compatibility matrix
([`packages/honua-gp/docs/compatibility-matrix.md`](../../packages/honua-gp/docs/compatibility-matrix.md))
are the behaviour reference.

## Previous distribution

This repository used to contain a second distribution, `honua-arcpy`, next to
`honua-gp`. Importing `honua_arcpy` re-exported `honua_gp` and emitted a
`DeprecationWarning`. That distribution was never published to a package index.
It has been removed.

Replace:

```python
import honua_arcpy as arcpy
```

with:

```python
import honua_gp as arcpy
```

Calls, configuration, and results are the `honua_gp` implementation. There is
no compatibility module left under the old name.

## Source scanner

`honua_sdk.migration.arcpy` is a different module. It reads Python source text
and describes calls for translation onto Honua processes. It does not import
`honua_gp`, and removing the unpublished distribution does not change it.
