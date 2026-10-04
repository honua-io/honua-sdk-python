---
type: guide
title: "Query features in five minutes"
description: "Install the SDK and run a real query against the public demo server, with no account, key or local install. The fastest proof the SDK works."
resource: "https://pypi.org/project/honua-sdk/"
tags: [quickstart, python]
---
# 5-Minute Quickstart: Query Features and Plot with GeoPandas

## What You'll Build

A Python script that queries geospatial features from a Honua server,
converts them to a GeoDataFrame, and plots them with matplotlib.

By the end you will have a map saved as `features.png` and a geocoded
point overlaid on top of it.

This quickstart is the smallest tour of the SDK surface. The maintained
script-first example remains the [Geospatial ETL demo](https://github.com/honua-io/honua-sdk-python/tree/trunk/examples/geospatial_etl),
and the notebook companion imports that same shared workflow module.

## Prerequisites

- Python 3.11+
- A Honua server to talk to. You do not need to stand one up to finish this page
  — the sections below run against the public read-only demo.

### The public demo server

`https://demo.honua.io` serves real data anonymously, with no account, key, or
local install. Every read-only example on this page runs against it as written.

| | |
|---|---|
| Base URL | `https://demo.honua.io` |
| FeatureServer service | `maui-zoning` |
| Layer id | `2` (polygon; `id`, `zone_code`, `zone_dist`, `cp_area`, `island`) |
| OGC API Features | `https://demo.honua.io/ogc/features/collections` (collection `2`) |
| Geocoding | `https://demo.honua.io` (`HonuaGeocodingClient`) |

It is a shared, read-only demo: `/api/v1/admin/*` returns `401`. The **gRPC**
step and the **editing** recipe below therefore keep a `your-honua-server.com`
placeholder and need a server of your own — see the
[Honua Server quickstart](https://github.com/honua-io/honua-server/blob/trunk/docs/get-started/quickstart.md),
whose gRPC listener is h2c on port **8081**.

## Step 1: Install (takes a minute or two on first install)

```bash
pip install "honua-sdk[geopandas]" matplotlib
```

The `geopandas` extra installs the GeoPandas and Shapely stack used later in this quickstart.

## Step 2: Query features (60 seconds)

```python
from honua_sdk import HonuaClient, Query, SourceDescriptor, SourceLocator

with HonuaClient("https://demo.honua.io") as client:
    source = client.source(
        SourceDescriptor(
            id="maui-zoning",
            protocol="geoservices-feature-service",
            locator=SourceLocator(service_id="maui-zoning", layer_id=2),
        )
    )
    result = source.query(Query(where="island = 'Maui'", out_fields=["*"]))

print(f"Found {len(result.features)} features")
for feature in result.features[:3]:
    print(feature.properties)
```

`client.source(...)` returns a source-bound facade; `source.query(...)`
returns a canonical `Result` whose `features` are normalized
`QueryFeature` entries (`id`, `properties`, `geometry`, `protocol`,
`source`, `raw`). The `raw` attribute on each feature still exposes that
feature's underlying protocol payload (for FeatureServer that is the
GeoServices JSON shape with `"attributes"` and `"geometry"` sub-keys), and
`result.raw_legacy` holds the underlying query envelope, when you need it.

> **Legacy / compact form.** `client.query_features("maui-zoning",
> layer_id=2, where="1=1", return_geometry=True, out_fields=["*"])`
> still works and returns the raw GeoServices dict; prefer it only for
> one-liners. The `Source` API above is the recommended idiom and
> returns typed `Result`/`QueryFeature` objects.

## Step 3: Convert to GeoDataFrame (10 seconds)

A `Result` from the `Source` API converts directly with one call -- no
Shapely glue code required:

```python
gdf = result.to_geodataframe()
print(gdf.head())
print(gdf.crs)
```

`Result.to_geodataframe()` reads attributes and geometry from the result's
normalized features and resolves the CRS from the query's spatial reference.

For raw FeatureServer payloads (the GeoServices dict returned directly by
`query_features`), the typed `FeatureSet` returned by `query_feature_set`, or
a list of feature dicts, use `features_to_geodataframe`, which also accepts
Esri JSON geometries and the layer's `spatialReference`:

```python
from honua_sdk.geopandas import features_to_geodataframe

with HonuaClient("https://demo.honua.io") as client:
    raw = client.query_features("maui-zoning", layer_id=2, where="island = 'Maui'")

gdf = features_to_geodataframe(raw)
```

The reverse helper, `geodataframe_to_features`, turns an edited GeoDataFrame
back into payloads ready for `apply_edits`.

If you prefer to skip the `geopandas` extra and stay on raw dicts, see the
appendix at the bottom of this file for the manual Esri JSON conversion.

## Step 4: Plot the data (60 seconds)

```python
import matplotlib.pyplot as plt

ax = gdf.plot(column="cp_area", legend=True, figsize=(12, 8))
ax.set_title("Maui zoning by community plan area")
plt.savefig("features.png", dpi=150, bbox_inches="tight")
plt.show()
```

`cp_area` is the community plan area of each zoning polygon. Against your own
data, replace it with any attribute name, or drop the `column` argument to plot
without a colour ramp:

```python
gdf.plot(figsize=(12, 8))
```

## Step 5: Add geocoding (optional, 60 seconds)

Use `HonuaGeocodingClient` to forward-geocode an address and plot it on
top of the feature map. Geocode an address inside your data's extent — a point
outside it plots off the map.

```python
import geopandas as gpd
from shapely.geometry import Point

from honua_sdk import HonuaGeocodingClient

with HonuaGeocodingClient("https://demo.honua.io") as geocoder:
    results = geocoder.forward_geocode("Kahului Airport, Maui, Hawaii")

if results:
    top = results[0]
    print(f"{top.address}  ({top.latitude}, {top.longitude})  score={top.score}")

    point = gpd.GeoDataFrame(
        [{"label": top.address, "geometry": Point(top.longitude, top.latitude)}],
        geometry="geometry",
        crs="EPSG:4326",
    ).to_crs(gdf.crs)  # geocoder returns WGS84; plot in the layer's CRS

    ax = gdf.plot(figsize=(12, 8), color="lightgrey", edgecolor="black")
    point.plot(ax=ax, color="red", markersize=80, zorder=5)
    ax.set_title("Geocoded location on feature map")
    plt.savefig("geocoded.png", dpi=150, bbox_inches="tight")
    plt.show()
```

`forward_geocode` returns a list of `GeocodeResult` dataclasses sorted by
score. Each result exposes `address`, `latitude`, `longitude`, `score`,
and `attributes`.

## Step 6: Query via gRPC (optional, 60 seconds)

> **Needs your own server.** This step uses a `your-honua-server.com:8081`
> placeholder. Point it at your server's gRPC address (the Honua Server
> quickstart serves h2c on port 8081), and replace `maui-zoning` / `2` with
> the service and layer id of one of your published layers.


If your Honua server exposes a gRPC endpoint, you can use `HonuaGrpcClient`
for high-throughput streaming queries. Install the gRPC extras first:

```bash
pip install "honua-sdk[grpc]"
```

> **Dev-only**: pass `credentials=` (TLS) in production. `insecure=True` disables transport security and should never reach production deployments.

<!-- doc-run: blocked https://github.com/honua-io/honua-sdk-python/issues/259 -->
```python
from honua_sdk.grpc import HonuaGrpcClient, QueryFeaturesRequest

with HonuaGrpcClient("your-honua-server.com:8081", insecure=True) as grpc_client:
    # Unary query
    request = QueryFeaturesRequest(
        service_id="maui-zoning",
        layer_id=2,
        return_geometry=True,
    )
    response = grpc_client.query_features(request)
    print(f"Received {len(response.features)} features via gRPC")

    # Streaming query (pages arrive incrementally)
    for page in grpc_client.query_features_stream(request):
        print(f"Page with {len(page.features)} features")
```

For async usage, swap in `HonuaGrpcAsyncClient`:

> **Dev-only**: pass `credentials=` (TLS) in production. `insecure=True` disables transport security and should never reach production deployments.

<!-- doc-run: blocked https://github.com/honua-io/honua-sdk-python/issues/259 -->
```python
from honua_sdk.grpc import HonuaGrpcAsyncClient, QueryFeaturesRequest

async with HonuaGrpcAsyncClient("your-honua-server.com:8081", insecure=True) as grpc_client:
    request = QueryFeaturesRequest(service_id="maui-zoning", layer_id=2)
    response = await grpc_client.query_features(request)

    async for page in grpc_client.query_features_stream(request):
        print(f"Streamed {len(page.features)} features")
```

## Full script

Here is the complete example in one copy-pasteable block:

```python
"""quickstart.py -- Honua SDK 5-minute demo."""

import matplotlib.pyplot as plt

from honua_sdk import (
    HonuaClient,
    Query,
    SourceDescriptor,
    SourceLocator,
)

SERVER = "https://demo.honua.io"

# --- Query features --------------------------------------------------------
with HonuaClient(SERVER) as client:
    source = client.source(
        SourceDescriptor(
            id="maui-zoning",
            protocol="geoservices-feature-service",
            locator=SourceLocator(service_id="maui-zoning", layer_id=2),
        )
    )
    result = source.query(Query(where="island = 'Maui'", out_fields=["*"]))

print(f"Found {len(result.features)} features")

# --- Build GeoDataFrame ----------------------------------------------------
gdf = result.to_geodataframe()

# --- Plot ------------------------------------------------------------------
ax = gdf.plot(column="cp_area", legend=True, figsize=(12, 8))
ax.set_title("Maui zoning by community plan area")

plt.savefig("features.png", dpi=150, bbox_inches="tight")
plt.show()
```

## What's Next

- [Geospatial ETL demo](https://github.com/honua-io/honua-sdk-python/tree/trunk/examples/geospatial_etl) -- canonical script-first ETL flow plus notebook companion, including the `load-summary.json` and `post-load-preview.png` output contract
- [Troubleshooting](./troubleshooting.md) -- base URL selection, auth, staging smoke env vars, optional ETL dependencies, and cleanup guidance
- [INSTALL.md](https://github.com/honua-io/honua-sdk-python/blob/trunk/INSTALL.md) -- installation options including gRPC extras
- [gRPC client](../packages/honua-sdk/honua_sdk/grpc/) -- streaming feature queries via `HonuaGrpcClient`
- [Admin client](../packages/honua-admin/honua_admin/) -- server administration with `HonuaAdminClient`

## Appendix: Manual Esri JSON conversion (without the `geopandas` extra)

If you cannot install the `geopandas` extra and need to handle the FeatureServer
response yourself, the JSON shape is straightforward. Each feature has
`"attributes"` and `"geometry"` keys; the geometry uses Esri JSON
(`rings`, `paths`, or `x`/`y`) rather than GeoJSON. Use the legacy
`query_features` call, which returns that raw GeoServices dict directly:

```python
import geopandas as gpd
from shapely.geometry import shape

from honua_sdk import HonuaClient

with HonuaClient("https://demo.honua.io") as client:
    raw = client.query_features("maui-zoning", layer_id=2, where="island = 'Maui'")
features = raw.get("features", [])

rows = []
for f in features:
    attrs = dict(f.get("attributes", {}))
    geom = f.get("geometry")

    # Esri JSON rings/paths -> GeoJSON-style dict for shapely
    if geom and "rings" in geom:
        geom = {"type": "Polygon", "coordinates": geom["rings"]}
    elif geom and "paths" in geom:
        geom = {"type": "LineString", "coordinates": geom["paths"][0]}
    elif geom and "x" in geom:
        geom = {"type": "Point", "coordinates": [geom["x"], geom["y"]]}

    attrs["geometry"] = shape(geom) if geom else None
    rows.append(attrs)

gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")
```

Prefer `features_to_geodataframe` in real code -- it also handles polylines,
multipoints, M/Z dimensions, and the layer's actual `spatialReference` so the
GeoDataFrame's CRS is correct without guessing `EPSG:4326`.

## Common errors

The SDK raises a small hierarchy of typed errors. Catch broadly with
`HonuaError`, or narrowly with the specific subclass.

| Exception | When it fires | What to do |
|-----------|--------------|------------|
| `HonuaAuthError` (401/403) | Missing/invalid API key or bearer token | Confirm `api_key=` or `bearer_token=` is set on the client |
| `HonuaRateLimitError` (429) | Server rate limit hit | Honor `error.retry_after` (seconds); the SDK already retries idempotent methods |
| `HonuaHttpError` (any 4xx/5xx) | Other server-side errors | Inspect `error.status_code` and `error.body` |
| `HonuaTimeoutError` | Request exceeded the configured timeout | Pass `timeout=` to the client or use `client.with_options(timeout=...)` for a one-off |
| `HonuaTransportError` | DNS/connect/read failure | Network issue; the SDK already retries safe methods |

Example:

```python
from honua_sdk import (
    HonuaAuthError,
    HonuaClient,
    HonuaRateLimitError,
    Query,
    SourceDescriptor,
    SourceLocator,
)

SERVER = "https://demo.honua.io"
ZONING = SourceDescriptor(
    id="maui-zoning",
    protocol="geoservices-feature-service",
    locator=SourceLocator(service_id="maui-zoning", layer_id=2),
)

with HonuaClient(SERVER) as client:
    try:
        result = client.source(ZONING).query(Query(where="island = 'Maui'"))
    except HonuaAuthError:
        raise SystemExit("Auth failed -- check the client's api_key or bearer_token")
    except HonuaRateLimitError as exc:
        print(f"Rate limited; retry after {exc.retry_after}s")
```

### Recipe: rate-limit retry on mutating calls

The SDK already retries idempotent methods (`GET`, `HEAD`, `PUT`, `DELETE`,
`OPTIONS`) on 429 automatically, honouring the `Retry-After` header. `POST` is
not retried unless you opt in by adding it to `retry_methods` on the retry
transport (see [Retries and timeouts](retries-and-timeouts.md)), so by default a
mutating call such as `apply_edits` raises `HonuaRateLimitError` on the first
429. To retry it at the application level --
for example, to log backoff explicitly or to bound the number of attempts --
catch `HonuaRateLimitError`, sleep for `exc.retry_after`, and send the same
`idempotency_key` on every attempt so the server can de-duplicate the edit.

This recipe writes to a layer, so run it against a server of your own. Set
`HONUA_API_KEY` to an API key that may edit, and `HONUA_EDIT_SERVICE` to a
FeatureServer service whose first layer accepts updates (the service declares
the `Update` capability). The recipe re-saves the first feature of that layer
unchanged, so it leaves your data as it was:

<!-- doc-run: blocked https://github.com/honua-io/honua-release/issues/423 -->
```python
import os
import time
import uuid

from honua_sdk import HonuaClient, HonuaRateLimitError

service_id = os.environ["HONUA_EDIT_SERVICE"]

with HonuaClient("https://your-honua-server.com", api_key=os.environ["HONUA_API_KEY"]) as client:
    layer_id = client.feature_server(service_id).metadata()["layers"][0]["id"]
    first = client.query_features(service_id, layer_id, return_geometry=False)["features"][0]
    edit_key = uuid.uuid4().hex  # one key for every attempt of this edit
    for attempt in range(5):
        try:
            result = client.apply_edits_result(
                service_id,
                layer_id,
                updates=[{"attributes": first["attributes"]}],
                idempotency_key=edit_key,
            )
            if not result.all_succeeded:
                # Row-level failures come back as HTTP 200 with success=false.
                errors = [r.error for r in result.update_results if not r.success]
                raise SystemExit(f"Edit rejected: {errors}")
            break
        except HonuaRateLimitError as exc:
            wait_s = exc.retry_after or 2 ** attempt
            print(f"429; sleeping {wait_s}s before retry {attempt + 1}")
            time.sleep(wait_s)
    else:
        raise SystemExit("Gave up after 5 retries")
```

### Recipe: retry a timeout with a larger budget

`HonuaTimeoutError` fires when a single request exceeds the client's configured
timeout. For occasional slow queries, retry the same call with a one-shot
`client.with_options(timeout=...)` override -- this returns a lightweight clone
that shares the underlying transport, so it does not reconnect. `SERVER` and
`ZONING` are the ones defined in the example above:

```python
from honua_sdk import HonuaClient, HonuaTimeoutError, Query

query = Query(where="island = 'Maui'")

with HonuaClient(SERVER, timeout=5.0) as client:
    try:
        result = client.source(ZONING).query(query)
    except HonuaTimeoutError:
        # One-shot bigger budget; original client keeps its 5s default.
        result = client.with_options(timeout=60.0).source(ZONING).query(query)
```

See [troubleshooting.md](troubleshooting.md) for more.
