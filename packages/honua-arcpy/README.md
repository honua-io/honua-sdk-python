# honua-arcpy (deprecated)

> **Deprecated.** This package has been renamed to
> [`honua-gp`](../honua-gp/README.md) (import namespace `honua_gp`). The old
> `honua-arcpy` / `honua_arcpy` name used an Esri trademark in a
> distribution and import-namespace name and has been retired.

This directory now ships a thin backward-compatibility shim only. Importing
`honua_arcpy` re-exports the public API of `honua_gp` and emits a
`DeprecationWarning`. Update your imports:

```python
# Before
import honua_arcpy as arcpy

# After
import honua_gp as arcpy
```

`honua_gp` is a drop-in-style geoprocessing compatibility layer for teams
migrating scripts from ArcGIS `arcpy` to Honua services. "ArcPy" and "ArcGIS"
are trademarks of Esri and are used here only to describe compatibility.
