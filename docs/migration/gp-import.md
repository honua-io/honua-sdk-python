---
type: guide
title: "Import the geoprocessing package"
description: "Install and import the Honua geoprocessing package."
---
# Geoprocessing package import

> **Native application path:** [gRPC for live data and edits; PMTiles, GeoParquet and COG through the CDN](../native-data-paths.md). Start there for browser gRPC-Web setup, signed private URLs and regeneration after changes. OGC API and GeoServices REST examples below are compatibility workflows.

`honua-gp` is an Apache-2.0 geoprocessing package. Install it with
`pip install honua-gp`, then use its
`honua_gp` namespace:

```python
import honua_gp

honua_gp.configure(base_url="https://honua.example.com", api_key="...")
```

Point the session at a Honua base URL, then call the supported tools. The
behavior reference is `packages/honua-gp/README.md` and
`packages/honua-gp/docs/compatibility-matrix.md`.
