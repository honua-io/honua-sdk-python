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

### OGC API Features

```python
from honua_sdk import HonuaClient

with HonuaClient("https://your-honua-server.com") as client:
    ogc = client.ogc_features()
    collections = ogc.collections()

    parcels = ogc.collection("parcels")
    items = parcels.items(limit=100, filter="status = 'active'")
    all_items = parcels.items_all(page_size=500, max_pages=20)
    feature = parcels.item("123")
```

### Protocol clients

```python
from honua_sdk import HonuaClient, ODataQuery

with HonuaClient("https://your-honua-server.com") as client:
    capabilities = client.capabilities()
    if capabilities.supports("stac"):
        stac_items = client.stac().items("imagery")
        stac_item_list = client.stac().items_all("imagery", page_size=100, limit=500)

    map_png = client.ogc_maps().collection_map("parcels", bbox=[-180, -90, 180, 90])
    tile_png = client.ogc_tiles().tile("WebMercatorQuad", "0", 0, 0, collection_id="parcels")
    coverage = client.ogc_coverages().coverage("elevation", response_format="tiff")
    process_list = client.ogc_processes().processes()
    wfs_xml = client.wfs().get_feature(type_names="parcels")
    wms_png = client.wms("basemap").map(layers="parcels", bbox=[-180, -90, 180, 90], width=512, height=512)
    wms_response = client.wms("basemap").map_response(
        layers="parcels",
        bbox=[-180, -90, 180, 90],
        width=512,
        height=512,
    )
    wmts_tile = client.wmts("basemap").tile(
        layer="parcels",
        tile_matrix_set="WebMercatorQuad",
        tile_matrix="0",
        tile_row=0,
        tile_col=0,
    )
    odata_features = client.odata().features_all(
        layer_id=0,
        query=ODataQuery(select=["ObjectId", "Name"], count=True),
        page_size=500,
        limit=2000,
    )
```

Protocol helpers return protocol-native shapes: JSON `dict`, XML `str`, raw
`bytes`, `BinaryResponse` metadata wrappers for WMS/WMTS payloads, or SDK
models for geocoding and gRPC. Collection-style surfaces also expose paged
iterators and collect-all helpers such as `iter_items()`, `query_items()`,
`items_all()`, and `features_all()`. `client.capabilities()` and
`client.supports("stac")` expose advertised data-plane capabilities. See
[Protocol Examples](docs/protocol-examples.md) for every public wrapper and
[Protocol Parity](docs/protocol-parity.md) for the Python/JS coverage map.

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

HTTP data and protocol workflows have async counterparts with the same factory
and method names:

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
- [Core Client](docs/core-client.md) -- typed service, FeatureServer, applyEdits, pagination, and error handling helpers
- [Protocol Examples](docs/protocol-examples.md) -- OGC, STAC, WFS, WMS, WMTS, OData, geocoding, and gRPC examples with response shapes
- [Geospatial ETL demo](examples/geospatial_etl/README.md) -- canonical script-first ETL flow plus notebook companion, with `load-summary.json` / `post-load-preview.png` artifacts and the `apply_edits` contract
- [Authentication](docs/auth.md) -- refreshable bearer tokens, secure storage guidance, revocation, rotation, and failure modes
- [Compatibility](docs/compatibility.md) -- supported server matrix, public API snapshot gate, and release blocking policy
- [Troubleshooting](docs/troubleshooting.md) -- staging smoke env vars and result artifacts, auth expectations, seeded `test_service` / layer `0` assumptions, optional example dependencies, and cleanup guidance
- [Operating Cadence](docs/operating-cadence.md) -- weekly backlog review, scope gate, and done/close hygiene
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

# Run the deterministic local suite
python3 -m pytest tests/ -q

# Run the compatibility gate
python3 scripts/compatibility_gate.py

# Run the opt-in staging smoke suite
python3 -m pytest tests/integration -q --run-integration -m "integration and staging and smoke"

# Run the release smoke helper against an installed SDK build
python3 scripts/release_smoke.py
```

The staging smoke command and `scripts/release_smoke.py` both require
`HONUA_BASE_URL`. Set `HONUA_ENABLE_WRITE_SMOKE=true` when you want the
add/query/update/delete roundtrip enabled outside the default read-only local run.

The staging smoke suite writes `staging-smoke-results.json` by default.
`scripts/release_smoke.py` writes `release-smoke-results.json` unless `--results-path` overrides it.
The dedicated GitHub staging lane in `.github/workflows/staging-integration.yml`
uploads both `staging-smoke-results.json` and `staging-smoke-junit.xml`, then
renders the JSON report into the workflow step summary. Same-repo pull requests
skip that live lane until `HONUA_BASE_URL` is configured in GitHub Actions;
`trunk`, scheduled, and manual runs still fail fast when the staging base URL is missing.

## License

Apache-2.0
