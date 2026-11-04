---
type: guide
title: "Import the geoprocessing package"
description: "Install and import the Honua geoprocessing package."
---
# Geoprocessing package import

`honua-gp` is a separately licensed geoprocessing package. Use its
`honua_gp` namespace:

```python
import honua_gp

honua_gp.configure(base_url="https://honua.example.com", api_key="...")
```

Point the session at a Honua base URL, then call the supported tools. The
behavior reference is `packages/honua-gp/README.md` and
`packages/honua-gp/docs/compatibility-matrix.md`.
