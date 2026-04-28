# honua-sdk

Python data-plane client for [Honua Server](https://github.com/honua-io) --
query geospatial features, geocode addresses, stream data over gRPC, and
convert results to GeoDataFrames. Sync and async clients included.

See the [monorepo README](https://github.com/honua-io/honua-sdk-python) for
full documentation.

## Install

```bash
pip install honua-sdk

# With gRPC support
pip install honua-sdk[grpc]

# With GeoPandas integration
pip install honua-sdk[geopandas]
```

Requires Python 3.11+.

## Quick Example

```python
from honua_sdk import HonuaClient

with HonuaClient("https://your-honua-server.com") as client:
    result = client.query("natural-earth", layer_id=0)
    print(f"Found {len(result.features)} features")
```

## Refreshable Auth

```python
from honua_sdk import HonuaClient, RefreshableBearerTokenProvider

auth = RefreshableBearerTokenProvider(lambda: {"access_token": "token", "expires_in": 3600})

with HonuaClient("https://your-honua-server.com", auth_provider=auth) as client:
    services = client.list_services()
```

## OGC API Features

```python
from honua_sdk import HonuaClient

with HonuaClient("https://your-honua-server.com") as client:
    parcels = client.ogc_features().collection("parcels")
    items = parcels.items(limit=100, filter="status = 'active'")
    all_items = parcels.items_all(page_size=500, max_pages=20)
    feature = parcels.item("123")
```

## Shared Feature Query

```python
from honua_sdk import FeatureQuery, HonuaClient

with HonuaClient("https://your-honua-server.com") as client:
    feature_server = client.query(
        "parcels",
        layer_id=0,
        where="status = 'active'",
        fields=["objectid", "name", "status"],
        limit=2000,
    )
    ogc_features = client.query(
        "parcels",
        protocol="ogc-features",
        filter="status = 'active'",
        bbox=[-180, -90, 180, 90],
        fields=["name", "status"],
        limit=2000,
    )
    stac_items = client.query(
        FeatureQuery(
            source="imagery",
            protocol="stac",
            filter="eo:cloud_cover < 10",
            bbox=[-180, -90, 180, 90],
            limit=500,
        )
    )
    odata_features = client.query(
        "4",
        protocol="odata",
        filter="Status eq 'active'",
        fields=["ObjectId", "Name"],
        limit=2000,
    )
```

`client.query()` returns normalized `QueryFeature` entries across FeatureServer,
OGC API Features, STAC, and OData. Use `client.iter_query()` to stream features
without collecting the full result. Protocol-specific clients remain available
for native payloads, maps, tiles, WMS/WMTS metadata, OData metadata, geocoding,
and gRPC.

## Documentation

- [5-Minute Quickstart](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/quickstart.md) - query features, convert them to a GeoDataFrame, and plot them
- [Core Client](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/core-client.md) - typed service, FeatureServer, applyEdits, pagination, and error handling helpers
- [Protocol Examples](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/protocol-examples.md) - OGC, STAC, WFS, WMS, WMTS, OData, geocoding, and gRPC examples with response shapes
- [Geospatial ETL demo](https://github.com/honua-io/honua-sdk-python/blob/trunk/examples/geospatial_etl/README.md) - canonical script-first extract/validate/write/reconcile flow with the notebook companion and `load-summary.json` / `post-load-preview.png` contract
- [Authentication](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/auth.md) - refreshable bearer tokens, secure storage guidance, revocation, rotation, and failure modes
- [Troubleshooting](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/troubleshooting.md) - base URL selection, auth, staging smoke env vars, JSON/JUnit artifacts, and cleanup guidance
- [Monorepo README](https://github.com/honua-io/honua-sdk-python) - install options and package overview

## License

Apache-2.0
