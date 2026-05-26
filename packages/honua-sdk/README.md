# honua-sdk

Python data-plane client for [Honua Server](https://github.com/honua-io) --
query geospatial features, geocode addresses, stream data over gRPC, and
convert results to GeoDataFrames. Sync and async clients included.

See the [monorepo README](https://github.com/honua-io/honua-sdk-python) for
the full documentation index, install matrix, and release notes.

## Highlights

- Sync and async clients (`HonuaClient`, `AsyncHonuaClient`) with shared retry,
  refreshable-auth, and error-handling behavior.
- Source-bound facade (`client.source(...)`) returns normalized features across
  GeoServices FeatureServer, OGC API Features, STAC, and OData.
- Protocol wrappers for FeatureServer/MapServer/ImageServer/GeometryServer,
  OGC Features/Maps/Tiles/Coverages/Processes, STAC, WFS, WMS, WMTS, OData,
  and geocoding.
- Optional `geopandas` extra converts query responses to GeoDataFrames in one
  call via `honua_sdk.geopandas`.
- Optional `grpc` extra unlocks streaming feature queries through
  `honua_sdk.grpc.HonuaGrpcClient` / `HonuaGrpcAsyncClient`.

## Install

```bash
pip install honua-sdk                 # core data-plane client
pip install honua-sdk[geopandas]      # + GeoDataFrame helpers
pip install honua-sdk[grpc]           # + streaming gRPC client
```

Requires Python 3.11+.

## Minimal Example

```python
from honua_sdk import HonuaClient, Query, SourceDescriptor, SourceLocator

with HonuaClient("https://your-honua-server.com") as client:
    source = client.source(
        SourceDescriptor(
            id="test_service",
            protocol="geoservices-feature-service",
            locator=SourceLocator(service_id="test_service", layer_id=0),
        )
    )
    result = source.query(Query(where="status = 'active'", out_fields=["*"]))
    for feature in result.features:
        print(feature.properties, feature.geometry)
```

Always use the `with HonuaClient(...) as client:` form -- it guarantees the
underlying `httpx` connections are returned to the pool on exit, even when a
request raises.

### Async

```python
from honua_sdk import AsyncHonuaClient, Query, SourceDescriptor, SourceLocator

async with AsyncHonuaClient("https://your-honua-server.com") as client:
    source = client.source(
        SourceDescriptor(
            id="test_service",
            protocol="geoservices-feature-service",
            locator=SourceLocator(service_id="test_service", layer_id=0),
        )
    )
    result = await source.query(Query(where="status = 'active'", out_fields=["*"]))
    async for feature in source.stream(Query(where="status = 'active'")):
        print(feature.properties, feature.geometry)
```

Works with FastAPI, asyncio pipelines, Jupyter async, and any other async
framework. Sync and async clients share identical method names, retry, and
error-handling behavior.

Protocol IDs follow the canonical cross-SDK names
(`geoservices-feature-service`, `ogc-features`, `stac`, `odata`, ...). Common
aliases (`feature-server`, `featureserver`, `ogc-api-features`, ...) are
accepted and normalized through `honua_sdk.normalize_protocol(...)`.

## Documentation

- [5-Minute Quickstart](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/quickstart.md)
- [Core Client](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/core-client.md)
- [Protocol Examples](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/protocol-examples.md)
- [Authentication](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/auth.md)
- [Geospatial ETL demo](https://github.com/honua-io/honua-sdk-python/blob/trunk/examples/geospatial_etl/README.md)
- [Troubleshooting](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/troubleshooting.md)
- [Monorepo README](https://github.com/honua-io/honua-sdk-python) -- install matrix, package overview, and release notes

## License

Apache-2.0
