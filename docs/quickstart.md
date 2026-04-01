# 5-Minute Quickstart: Query Features and Plot with GeoPandas

## What You'll Build

A Python script that queries geospatial features from a Honua server,
converts them to a GeoDataFrame, and plots them with matplotlib.

By the end you will have a map saved as `features.png` and a geocoded
point overlaid on top of it.

## Prerequisites

- Python 3.11+
- A running Honua server (or use the demo endpoint)

## Step 1: Install (30 seconds)

```bash
pip install honua-sdk geopandas matplotlib shapely
```

## Step 2: Query features (60 seconds)

```python
from honua_sdk import HonuaClient

with HonuaClient("https://your-honua-server.com") as client:
    result = client.query_features(
        service_id="natural-earth",
        layer_id=0,
        where="1=1",
        return_geometry=True,
        out_fields=["*"],
    )

features = result.get("features", [])
print(f"Found {len(features)} features")
```

`query_features` returns a dict that mirrors the GeoServices JSON response.
The `"features"` key contains a list of feature dicts, each with
`"attributes"` and `"geometry"` sub-keys.

## Step 3: Convert to GeoDataFrame (60 seconds)

Honua returns geometries in Esri JSON format. Use `shapely` to convert
each geometry into a proper geometry object, then wrap everything in a
GeoDataFrame.

```python
import geopandas as gpd
from shapely.geometry import shape

rows = []
for f in features:
    attrs = f.get("attributes", {})
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
print(gdf.head())
```

## Step 4: Plot the data (60 seconds)

```python
import matplotlib.pyplot as plt

ax = gdf.plot(column="status", legend=True, figsize=(12, 8))
ax.set_title("Features from Honua Server")
plt.savefig("features.png", dpi=150, bbox_inches="tight")
plt.show()
```

If your layer does not have a `"status"` column, drop the `column`
argument or replace it with any attribute name from your dataset:

```python
gdf.plot(figsize=(12, 8))
```

## Step 5: Add geocoding (60 seconds)

Use `HonuaGeocodingClient` to forward-geocode an address and plot it on
top of the feature map.

```python
from honua_sdk import HonuaGeocodingClient
from shapely.geometry import Point

with HonuaGeocodingClient("https://your-honua-server.com") as geocoder:
    results = geocoder.forward_geocode("1600 Pennsylvania Ave NW, Washington, DC")

if results:
    top = results[0]
    print(f"{top.address}  ({top.latitude}, {top.longitude})  score={top.score}")

    point = gpd.GeoDataFrame(
        [{"label": top.address, "geometry": Point(top.longitude, top.latitude)}],
        geometry="geometry",
        crs="EPSG:4326",
    )

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

If your Honua server exposes a gRPC endpoint, you can use `HonuaGrpcClient`
for high-throughput streaming queries. Install the gRPC extras first:

```bash
pip install honua-sdk[grpc]
```

```python
from honua_sdk.grpc import HonuaGrpcClient, QueryFeaturesRequest

with HonuaGrpcClient("your-honua-server.com:50051", insecure=True) as grpc_client:
    # Unary query
    request = QueryFeaturesRequest(
        service_id="natural-earth",
        layer_id=0,
        return_geometry=True,
    )
    response = grpc_client.query_features(request)
    print(f"Received {len(response.features)} features via gRPC")

    # Streaming query (pages arrive incrementally)
    for page in grpc_client.query_features_stream(request):
        print(f"Page with {len(page.features)} features")
```

For async usage, swap in `HonuaGrpcAsyncClient`:

```python
from honua_sdk.grpc import HonuaGrpcAsyncClient, QueryFeaturesRequest

async with HonuaGrpcAsyncClient("your-honua-server.com:50051", insecure=True) as grpc_client:
    request = QueryFeaturesRequest(service_id="natural-earth", layer_id=0)
    response = await grpc_client.query_features(request)

    async for page in grpc_client.query_features_stream(request):
        print(f"Streamed {len(page.features)} features")
```

## Full script

Here is the complete example in one copy-pasteable block:

```python
"""quickstart.py -- Honua SDK 5-minute demo."""

import geopandas as gpd
import matplotlib.pyplot as plt
from shapely.geometry import Point, shape

from honua_sdk import HonuaClient, HonuaGeocodingClient

SERVER = "https://your-honua-server.com"

# --- Query features --------------------------------------------------------
with HonuaClient(SERVER) as client:
    result = client.query_features(
        service_id="natural-earth",
        layer_id=0,
        where="1=1",
        return_geometry=True,
        out_fields=["*"],
    )

features = result.get("features", [])
print(f"Found {len(features)} features")

# --- Build GeoDataFrame ----------------------------------------------------
rows = []
for f in features:
    attrs = f.get("attributes", {})
    geom = f.get("geometry")
    if geom and "rings" in geom:
        geom = {"type": "Polygon", "coordinates": geom["rings"]}
    elif geom and "paths" in geom:
        geom = {"type": "LineString", "coordinates": geom["paths"][0]}
    elif geom and "x" in geom:
        geom = {"type": "Point", "coordinates": [geom["x"], geom["y"]]}
    attrs["geometry"] = shape(geom) if geom else None
    rows.append(attrs)

gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326")

# --- Plot ------------------------------------------------------------------
ax = gdf.plot(figsize=(12, 8), color="lightgrey", edgecolor="black")
ax.set_title("Features from Honua Server")

# --- Geocode and overlay ---------------------------------------------------
with HonuaGeocodingClient(SERVER) as geocoder:
    hits = geocoder.forward_geocode("1600 Pennsylvania Ave NW, Washington, DC")

if hits:
    top = hits[0]
    point = gpd.GeoDataFrame(
        [{"label": top.address, "geometry": Point(top.longitude, top.latitude)}],
        geometry="geometry",
        crs="EPSG:4326",
    )
    point.plot(ax=ax, color="red", markersize=80, zorder=5)

plt.savefig("features.png", dpi=150, bbox_inches="tight")
plt.show()
```

## What's Next

- [Geospatial ETL demo](../examples/geospatial_etl/README.md) -- read, validate, write, and reconcile a demo-owned layer slice
- [INSTALL.md](../INSTALL.md) -- installation options including gRPC extras
- [gRPC client](../honua_sdk/grpc/) -- streaming feature queries via `HonuaGrpcClient`
- [Admin client](../honua_sdk/admin/) -- server administration with `HonuaAdminClient`
