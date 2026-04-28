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
    result = client.query_feature_set("natural-earth", layer_id=0)
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

## Protocol Clients

```python
from honua_sdk import HonuaClient

with HonuaClient("https://your-honua-server.com") as client:
    capabilities = client.capabilities()
    if capabilities.supports("stac"):
        stac_items = client.stac().items("imagery")

    image = client.ogc_maps().collection_map("parcels", bbox=[-180, -90, 180, 90])
    tile = client.ogc_tiles().tile("WebMercatorQuad", "0", 0, 0, collection_id="parcels")
    coverage = client.ogc_coverages().coverage("elevation", response_format="tiff")
    processes = client.ogc_processes().processes()
    wfs_xml = client.wfs().get_feature(type_names="parcels")
    wms_capabilities = client.wms("basemap").capabilities()
    wmts_tile = client.wmts("basemap").tile(
        layer="parcels",
        tile_matrix_set="WebMercatorQuad",
        tile_matrix="0",
        tile_row=0,
        tile_col=0,
    )
    odata_features = client.odata().features(layer_id=0)
```

Protocol helpers return protocol-native JSON `dict`, XML `str`, raw `bytes`,
or SDK models for geocoding and gRPC. `client.capabilities()` and
`client.supports("stac")` expose advertised data-plane capabilities.

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
