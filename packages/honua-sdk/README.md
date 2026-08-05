# honua-sdk

Python client for [Honua Server](https://github.com/honua-io/honua-server),
the multi-protocol geospatial server behind [Honua](https://honua.io) --
query geospatial features, geocode addresses, stream data over gRPC, and
convert results to GeoDataFrames. Sync and async clients included.

> **Status: Alpha (`0.x`).** APIs may change before 1.0. Breaking changes to
> the public API are gated by a
> [compatibility snapshot](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/compatibility.md)
> and a per-capability
> [SDK coverage snapshot](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/sdk-coverage.md).

See the [monorepo README](https://github.com/honua-io/honua-sdk-python) for
the full documentation index, install matrix, and release notes.

## Highlights

- Sync and async clients (`HonuaClient`, `AsyncHonuaClient`) with shared retry,
  refreshable-auth, and error-handling behavior.
- Source-bound facade (`client.source(...)`) returns normalized features across
  GeoServices FeatureServer, OGC API Features, STAC, and OData.
- Protocol wrappers for FeatureServer/MapServer/ImageServer/GeometryServer,
  SceneServer, ElevationServer,
  OGC Features/Maps/Tiles/Coverages/Processes/Records, STAC, WFS, WMS, WMTS,
  OData, and geocoding.
- Optional `geopandas` extra converts query responses to GeoDataFrames in one
  call via `honua_sdk.geopandas`; the `raster` extra adds raster result
  interop (`rasterio` / `rioxarray` / `xarray`).
- Optional `grpc` extra unlocks streaming feature queries through
  `honua_sdk.grpc.HonuaGrpcClient` / `HonuaGrpcAsyncClient`.
- Two CLIs ship with the package: `honua` (services / layers / style apply /
  sanitized `doctor` diagnostic bundles) and `honua-migrate` (offline ArcPy
  migration tooling: scan and translate ArcPy scripts, classify `.pyt` and
  `.atbx` toolboxes and geoprocessing services -- no `arcpy` install needed).

## Install

```bash
pip install honua-sdk                   # core data-plane client
pip install "honua-sdk[geopandas]"      # + GeoDataFrame helpers
pip install "honua-sdk[grpc]"           # + streaming gRPC client
pip install "honua-sdk[raster]"         # + raster interop (rasterio/rioxarray/xarray)
pip install "honua-sdk[grpc,geopandas,raster]"  # everything
```

Requires Python 3.11+.

## Minimal Example

```python
from honua_sdk import HonuaClient, Query, SourceDescriptor, SourceLocator

with HonuaClient("https://your-honua-server.com") as client:
    source = client.source(
        SourceDescriptor(
            id="parcels",
            protocol="geoservices-feature-service",
            locator=SourceLocator(service_id="parcels", layer_id=0),
        )
    )
    result = source.query(Query(where="status = 'active'", out_fields=["*"]))
    print(f"Found {len(result.features)} features")
    for feature in result.features[:3]:
        print(feature.id, feature.properties)

    # Requires the [geopandas] extra
    gdf = result.to_geodataframe()  # GeoDataFrame with geometry column + CRS set
```

The same `SourceDescriptor` with a different `protocol` (`ogc-features`,
`stac`, `odata`, ...) returns the same normalized `Result` shape.

Always use the `with HonuaClient(...) as client:` form -- it guarantees the
underlying `httpx` connections are returned to the pool on exit, even when a
request raises.

### Async

```python
from honua_sdk import AsyncHonuaClient, Query, SourceDescriptor, SourceLocator

async with AsyncHonuaClient("https://your-honua-server.com") as client:
    source = client.source(
        SourceDescriptor(
            id="parcels",
            protocol="geoservices-feature-service",
            locator=SourceLocator(service_id="parcels", layer_id=0),
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

Rendered docs site:
[honua-io.github.io/honua-sdk-python](https://honua-io.github.io/honua-sdk-python/latest/).
Platform docs: [honua.io](https://honua.io) and
[honua.gitbook.io/honuaio](https://honua.gitbook.io/honuaio/).

- [5-Minute Quickstart](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/quickstart.md)
- [Core Client](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/core-client.md)
- [Protocol Examples](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/protocol-examples.md)
- [Authentication](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/auth.md)
- [Geospatial ETL demo](https://github.com/honua-io/honua-sdk-python/blob/trunk/examples/geospatial_etl/README.md)
- [Troubleshooting](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/troubleshooting.md)
- [Sanitized diagnostic bundles](https://github.com/honua-io/honua-sdk-python/blob/trunk/docs/diagnostic-bundles.md)
- [Monorepo README](https://github.com/honua-io/honua-sdk-python) -- install matrix, package overview, and release notes

Related: [honua-admin](https://github.com/honua-io/honua-sdk-python/tree/trunk/packages/honua-admin)
(control-plane client),
[honua-sdk-js](https://github.com/honua-io/honua-sdk-js) (JS/TS SDKs + MCP server),
[honua-sdk-dotnet](https://github.com/honua-io/honua-sdk-dotnet) (.NET SDKs).

## License

Apache-2.0
