# Honua Python SDK

Monorepo for the Honua Python client libraries. Two independently installable
packages live under `packages/`:

| Package | PyPI name | Description |
|---------|-----------|-------------|
| [`packages/honua-sdk`](packages/honua-sdk/) | `honua-sdk` | Data-plane client -- feature queries, geocoding, gRPC streaming, GeoPandas integration |
| [`packages/honua-admin`](packages/honua-admin/) | `honua-admin` | Control-plane client -- services, connections, layers, styles, metadata, manifests |

## Install

```bash
# Data / protocol client
pip install honua-sdk

# With gRPC support
pip install honua-sdk[grpc]

# With GeoPandas integration
pip install honua-sdk[geopandas]

# Admin / control-plane client (depends on honua-sdk)
pip install honua-admin

# Everything
pip install honua-sdk[grpc,geopandas] honua-admin
```

Requires Python 3.11+. See [INSTALL.md](INSTALL.md) for full details.

## Quick Example

### Data client

```python
from honua_sdk import HonuaClient

with HonuaClient("https://your-honua-server.com") as client:
    # List available services
    services = client.list_services()

    # Query features from a layer
    result = client.query_features(
        service_id="natural-earth",
        layer_id=0,
        where="status = 'active'",
        return_geometry=True,
        out_fields=["*"],
    )

    features = result.get("features", [])
    print(f"Found {len(features)} features")
```

### Admin client

```python
from honua_admin import HonuaAdminClient

with HonuaAdminClient("https://your-honua-server.com", api_key="honua-api-key") as admin:
    compatibility = admin.check_compatibility()
    if not compatibility.supported:
        raise RuntimeError("; ".join(compatibility.reasons))

    features = admin.get_capability_flags()
    if features.manifest_apply:
        manifest = admin.get_manifest()
        print(f"Manifest resources: {len(manifest.resources)}")
```

## Async

Every client has an async counterpart with the same API:

```python
from honua_sdk import AsyncHonuaClient

async with AsyncHonuaClient("https://your-honua-server.com") as client:
    result = await client.query_features("natural-earth", layer_id=0)
    features = result.get("features", [])
```

Works with FastAPI, asyncio pipelines, Jupyter async, and any other async framework.

## GeoPandas

Convert query results to GeoDataFrames in one call:

```python
from honua_sdk import HonuaClient
from honua_sdk.geopandas import features_to_geodataframe, geodataframe_to_features

with HonuaClient("https://your-honua-server.com") as client:
    result = client.query_features("natural-earth", layer_id=0)
    gdf = features_to_geodataframe(result)

    # gdf is a GeoDataFrame with geometry column + CRS set
    print(gdf.head())
    print(gdf.crs)

    # Convert back for edits
    features = geodataframe_to_features(gdf)
```

Requires `pip install honua-sdk[geopandas]`.

## Geocoding

```python
from honua_sdk import HonuaGeocodingClient

with HonuaGeocodingClient("https://your-honua-server.com") as geocoder:
    results = geocoder.forward_geocode("1600 Pennsylvania Ave NW, Washington, DC")
    for r in results:
        print(f"{r.address}  ({r.latitude}, {r.longitude})  score={r.score}")
```

## Retry

All clients retry automatically on transient failures (429, 502, 503) with
exponential backoff and `Retry-After` header support. Configurable:

```python
# Default: 3 retries with exponential backoff
client = HonuaClient("https://your-server.com")

# Disable retry
client = HonuaClient("https://your-server.com", max_retries=0)
```

## Documentation

- [5-Minute Quickstart](docs/quickstart.md) -- query, GeoDataFrame, and plot
- [INSTALL.md](INSTALL.md) -- installation options and version policy
- See `honua_sdk.grpc.HonuaGrpcClient` for gRPC usage -- streaming feature queries
- [Admin client](packages/honua-admin/honua_admin/) -- server administration

## Status

These packages are in **alpha** (`0.x`).
Release automation is configured for PyPI publishing from `python-sdk-v<version>`
and `python-admin-v<version>` tags.
APIs may change before the 1.0 stable release.

## Development

```bash
# Install both packages in editable mode
pip install -e "packages/honua-sdk[grpc,geopandas]"
pip install -e "packages/honua-admin"

# Run all tests
python3 -m pytest tests/ -q
```

## License

Apache-2.0
