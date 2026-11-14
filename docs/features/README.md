---
type: index
title: "What this repository owns"
description: "The split between the Python data-plane package and the admin control-plane package, and the surfaces each one covers."
resource: "https://github.com/honua-io/honua-sdk-python"
tags: [sdk, python, surfaces]
---
# Honua Python SDK Feature Map

> **Native application path:** [gRPC for live data and edits; PMTiles, GeoParquet and COG through the CDN](../native-data-paths.md). Start there for browser gRPC-Web setup, signed private URLs and regeneration after changes. OGC API and GeoServices REST examples below are compatibility workflows.

This repository owns the Python data-plane package and admin/control-plane package.

## Current Capabilities

- `honua-sdk` data client for service listing, FeatureServer query helpers, shared Source/Query/Result facade, apply edits, pagination, and error handling.
- Protocol clients and examples for OGC API Features, STAC, WFS, WMS, WMTS, OData, geocoding, and gRPC.
- Sync and async client surfaces with matching factory and method shapes.
- GeoPandas conversion helpers for feature results and edit payloads.
- Retry handling for transient failures, `Retry-After`, and configurable retry counts.
- `honua-gp` Apache-2.0 drop-in shim covering 45 top-of-corpus `desktop GIS API` functions (15 analysis + 20 management + 10 data-access); dispatches through the existing `honua-sdk` / `honua-admin` / OGC API Processes clients and writes a redacted JSONL audit per call.
- ETL demo and staging/release smoke helpers with result artifacts.

## Source Evidence

- Data client package: `packages/honua-sdk/honua_sdk/`
- Admin package: `packages/honua-admin/honua_admin/`
- Geoprocessing integration package: `packages/honua-gp/honua_gp/`
- Examples: `examples/`
- Tests: `tests/`
- Compatibility and release scripts: `scripts/compatibility_gate.py`, `scripts/release_smoke.py`

## Boundary

The Python SDK is alpha. Keep docs explicit about current read/write smoke coverage, optional dependencies, and server compatibility gates before making stable API claims. `honua-gp` is available under Apache-2.0; see [docs/honua-gp/](../honua-gp/README.md).
