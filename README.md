# Honua Python SDK

[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/honua-io/honua-sdk-python/badge)](https://scorecard.dev/viewer/?uri=github.com/honua-io/honua-sdk-python)

[![Docs](https://img.shields.io/badge/docs-mkdocs--material-blue)](https://honua-io.github.io/honua-sdk-python/)

Monorepo for the Honua Python client libraries. Two independently installable
packages live under `packages/`:

| Package | PyPI name | Description |
|---------|-----------|-------------|
| [`packages/honua-sdk`](packages/honua-sdk/) | `honua-sdk` | Data-plane client -- feature queries, geocoding, gRPC streaming, GeoPandas integration |
| [`packages/honua-admin`](packages/honua-admin/) | `honua-admin` | Control-plane client -- services, connections, layers, styles, metadata, manifests |

## I want to...

| Goal                            | Start here                                                      |
|---------------------------------|-----------------------------------------------------------------|
| Query features in 5 minutes     | [docs/quickstart.md](docs/quickstart.md)                        |
| Stream features over gRPC       | [INSTALL.md#with-grpc](INSTALL.md#with-grpc)                    |
| Build an ETL pipeline           | [examples/geospatial_etl/](examples/geospatial_etl/)            |
| Wire a FastAPI service          | [examples/fastapi_spatial_service.py](examples/fastapi_spatial_service.py) |
| Manage services & connections   | [packages/honua-admin/](packages/honua-admin/)                  |
| Understand the protocol matrix  | [docs/protocol-parity.md](docs/protocol-parity.md)              |
| Diagnose an error               | [docs/quickstart.md#common-errors](docs/quickstart.md#common-errors) |

## Who is this for?

| You are a... | Start with |
|--------------|------------|
| **Data analyst** running spatial queries from Jupyter / pandas | [docs/quickstart.md](docs/quickstart.md) + [examples/data_quality_report.py](examples/data_quality_report.py) |
| **App developer** wiring a FastAPI / async service | [examples/fastapi_spatial_service.py](examples/fastapi_spatial_service.py) |
| **SDK / platform developer** managing services & connections | [packages/honua-admin/](packages/honua-admin/) |

## Install

```bash
# Data / protocol client
pip install honua-sdk

# Install both packages at once:
pip install honua-sdk honua-admin

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
from honua_sdk import HonuaClient, Query, SourceDescriptor, SourceLocator

with HonuaClient("https://your-honua-server.com") as client:
    # List available services
    services = client.list_services()

    # Query features through the shared Source/Query/Result API
    source = client.source(
        SourceDescriptor(
            id="test_service",
            protocol="geoservices-feature-service",
            locator=SourceLocator(service_id="test_service", layer_id=0),
        )
    )
    result = source.query(Query(where="status = 'active'", out_fields=["*"]))

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

### Shared Source/Query API

```python
from honua_sdk import FeatureQuery, HonuaClient, Query, SourceDescriptor, SourceLocator

with HonuaClient("https://your-honua-server.com") as client:
    parcels = client.source(
        SourceDescriptor(
            id="parcels",
            protocol="geoservices-feature-service",
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

> **Protocol IDs.** All docs and examples in this repo use the canonical
> cross-SDK protocol ids (for example, `geoservices-feature-service`,
> `ogc-features`, `stac`, `odata`). Common aliases such as `feature-server`,
> `featureserver`, `feature-service`, and `ogc-api-features` are accepted at
> runtime and normalized by `honua_sdk.normalize_protocol(...)`. The full alias
> table lives in `honua_sdk.PROTOCOL_ALIASES`.

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
from honua_sdk import AsyncHonuaClient, Query, SourceDescriptor, SourceLocator

async with AsyncHonuaClient("https://your-honua-server.com") as client:
    source = client.source(
        SourceDescriptor(
            id="test_service",
            protocol="geoservices-feature-service",
            locator=SourceLocator(service_id="test_service", layer_id=0),
        )
    )
    result = await source.query(Query(where="1=1"))
    features = result.features
```

Works with FastAPI, asyncio pipelines, Jupyter async, and any other async framework.

> **Legacy / compact form.**
> `await client.query_features(service_id="test_service", layer_id=0)`
> returns the raw GeoServices dict. Equivalent to
> `client.source(...).query(...)`; preferred for one-liners. The `Source`
> API returns typed `Result`/`QueryFeature` objects.

## GeoPandas

Convert query results to GeoDataFrames in one call:

```python
from honua_sdk import HonuaClient, Query, SourceDescriptor, SourceLocator
from honua_sdk.geopandas import geodataframe_to_features

with HonuaClient("https://your-honua-server.com") as client:
    source = client.source(
        SourceDescriptor(
            id="test_service",
            protocol="geoservices-feature-service",
            locator=SourceLocator(service_id="test_service", layer_id=0),
        )
    )
    result = source.query(Query(where="1=1"))
    gdf = result.to_geodataframe()

    # gdf is a GeoDataFrame with geometry column + CRS set
    print(gdf.head())
    print(gdf.crs)

    # Convert back for edits
    features = geodataframe_to_features(gdf)
```

Requires `pip install honua-sdk[geopandas]`.

> **Legacy / compact form.**
> `client.query_features(service_id="test_service", layer_id=0)` returns
> the raw GeoServices dict that `features_to_geodataframe` also accepts.
> Equivalent to `client.source(...).query(...)`; preferred for
> one-liners. The `Source` API returns typed `Result`/`QueryFeature`
> objects.

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
with HonuaClient("https://your-server.com") as client:
    services = client.list_services()

# Disable retry
with HonuaClient("https://your-server.com", max_retries=0) as client:
    services = client.list_services()
```

## Documentation

### Get started

- [5-Minute Quickstart](docs/quickstart.md) -- query, GeoDataFrame, and plot
- [Geospatial ETL demo](examples/geospatial_etl/README.md) -- canonical script-first ETL flow plus notebook companion, with `load-summary.json` / `post-load-preview.png` artifacts and the `apply_edits` contract
- [INSTALL.md](INSTALL.md) -- installation options and version policy

### Reference

- [Core Client](docs/core-client.md) -- typed service, FeatureServer, applyEdits, pagination, and error handling helpers
- [Protocol Examples](docs/protocol-examples.md) -- OGC, STAC, WFS, WMS, WMTS, OData, geocoding, and gRPC examples with response shapes
- [Authentication](docs/auth.md) -- refreshable bearer tokens, secure storage guidance, revocation, rotation, and failure modes
- See `honua_sdk.grpc.HonuaGrpcClient` for gRPC usage -- streaming feature queries
- [Admin client](packages/honua-admin/honua_admin/) -- server administration

### Project process

- [Compatibility](docs/compatibility.md) -- supported server matrix, public API snapshot gate, and release blocking policy
- [Troubleshooting](docs/troubleshooting.md) -- staging smoke env vars and result artifacts, auth expectations, seeded `test_service` / layer `0` assumptions, optional example dependencies, and cleanup guidance
- [Operating Cadence](docs/operating-cadence.md) -- weekly backlog review, scope gate, and done/close hygiene

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
