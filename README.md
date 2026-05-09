# Honua Python SDK

Monorepo for the Honua Python client libraries. Two independently installable
packages live under `packages/`:

Current package capabilities are summarized in [docs/features/README.md](docs/features/README.md).

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

    # Query features through the shared Source/Query/Result API
    source = client.source(
        {
            "id": "natural-earth",
            "protocol": "geoservices-feature-service",
            "locator": {"serviceId": "natural-earth", "layerId": 0},
        }
    )
    result = source.query(where="status = 'active'", out_fields=["*"])

    features = result.features
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

### OGC API Records

```python
from honua_sdk import HonuaClient

with HonuaClient("https://your-honua-server.com") as client:
    records = client.ogc_records()
    catalogs = records.collections()

    catalog = records.collection("metadata")
    search = catalog.records(q="shoreline", bbox=[-158, 21, -157, 22], limit=25)
    all_records = catalog.records_all(page_size=100, limit=500)
    record = catalog.record("dataset-123")
```

### Shared Source/Query API

```python
from honua_sdk import FeatureQuery, HonuaClient, Query, SourceDescriptor, SourceLocator

with HonuaClient("https://your-honua-server.com") as client:
    parcels = client.source(
        SourceDescriptor(
            id="parcels",
            protocol="feature-server",
            locator=SourceLocator(service_id="parcels", layer_id=0),
        )
    )
    result = parcels.query(
        Query(
            where="status = 'active'",
            out_fields=["objectid", "name", "status"],
            pagination={"limit": 2000},
        )
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

`client.source(...)` accepts a `SourceDescriptor` and returns a source-bound
facade with `query()`, `query_all()`, `stream()`/`iter_features()`,
`apply_edits()`, and `protocol(...)`. `source.query()` returns a canonical
`Result` with normalized `QueryFeature` entries: `id`, `properties`, `geometry`,
`protocol`, `source`, and `raw`.

The older `client.query()` and `client.iter_query()` helpers remain available as
the compact FeatureServer, OGC Features, STAC, and OData path. Protocol-specific
clients are still available through `source.protocol(...)` or direct factories
for native payloads, map and tile bytes, OData metadata, WMS/WMTS
`BinaryResponse` metadata, and advanced protocol options. See
[Protocol Examples](docs/protocol-examples.md) for every wrapper and
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
renders the JSON report into the workflow step summary. When `HONUA_BASE_URL` is
configured, the lane runs against that live external target. When it is missing,
the lane starts the seeded Honua Server client-compat Docker target and runs the
same smoke suite against `test_service` / layer `0`.

## License

Apache-2.0
