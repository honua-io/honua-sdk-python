# Honua Python SDK Feature Map

This repository owns the Python data-plane package and admin/control-plane package.

## Current Capabilities

- `honua-sdk` data client for service listing, FeatureServer query helpers, shared Source/Query/Result facade, apply edits, pagination, and error handling.
- Protocol clients and examples for OGC API Features, STAC, WFS, WMS, WMTS, OData, geocoding, and gRPC.
- Sync and async client surfaces with matching factory and method shapes.
- GeoPandas conversion helpers for feature results and edit payloads.
- Retry handling for transient failures, `Retry-After`, and configurable retry counts.
- `honua-admin` control-plane client for compatibility checks, capabilities, services, connections, layers, styles, metadata, and manifests, plus the `_arcpy_scanner` migration scanner that emits `ArcPyScriptInventoryArtifact` payloads.
- `honua-arcpy` proprietary drop-in shim covering 45 top-of-corpus `arcpy` functions (15 analysis + 20 management + 10 data-access); dispatches through the existing `honua-sdk` / `honua-admin` / OGC API Processes clients and writes a redacted JSONL audit per call.
- ETL demo and staging/release smoke helpers with result artifacts.

## Source Evidence

- Data client package: `packages/honua-sdk/honua_sdk/`
- Admin package: `packages/honua-admin/honua_admin/`
- ArcPy compatibility shim: `packages/honua-arcpy/honua_arcpy/`
- Examples: `examples/`
- Tests: `tests/`
- Compatibility and release scripts: `scripts/compatibility_gate.py`, `scripts/release_smoke.py`

## Boundary

The Python SDK is alpha. Keep docs explicit about current read/write smoke coverage, optional dependencies, and server compatibility gates before making stable API claims. `honua-arcpy` is proprietary and excluded from the public Apache-2.0 grant; see [docs/honua-arcpy/](../honua-arcpy/README.md).
