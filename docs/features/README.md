# Honua Python SDK Feature Map

This repository owns the Python data-plane package and admin/control-plane package.

## Current Capabilities

- `honua-sdk` data client for service listing, FeatureServer query helpers, shared Source/Query/Result facade, apply edits, pagination, and error handling.
- Protocol clients and examples for OGC API Features, STAC, WFS, WMS, WMTS, OData, geocoding, and gRPC.
- Sync and async client surfaces with matching factory and method shapes.
- GeoPandas conversion helpers for feature results and edit payloads.
- Retry handling for transient failures, `Retry-After`, and configurable retry counts.
- `honua-admin` control-plane client for compatibility checks, capabilities, services, connections, layers, styles, metadata, and manifests.
- ETL demo and staging/release smoke helpers with result artifacts.

## Source Evidence

- Data client package: `packages/honua-sdk/honua_sdk/`
- Admin package: `packages/honua-admin/honua_admin/`
- Examples: `examples/`
- Tests: `tests/`
- Compatibility and release scripts: `scripts/compatibility_gate.py`, `scripts/release_smoke.py`

## Boundary

The Python SDK is alpha. Keep docs explicit about current read/write smoke coverage, optional dependencies, and server compatibility gates before making stable API claims.
