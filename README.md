# Honua Python SDK

[![CI](https://github.com/honua-io/honua-sdk-python/actions/workflows/ci.yml/badge.svg?branch=trunk)](https://github.com/honua-io/honua-sdk-python/actions/workflows/ci.yml)
[![Conformance](https://github.com/honua-io/honua-sdk-python/actions/workflows/conformance.yml/badge.svg?branch=trunk)](https://github.com/honua-io/honua-sdk-python/actions/workflows/conformance.yml)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/honua-io/honua-sdk-python/badge)](https://scorecard.dev/viewer/?uri=github.com/honua-io/honua-sdk-python)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

Python client libraries for [Honua](https://honua.io), the cloud-native
geospatial platform built around
[honua-server](https://github.com/honua-io/honua-server). One typed client
covers feature queries, geocoding, map/image export, editing, and server
administration across the server's protocol adapters — GeoServices REST
(FeatureServer/MapServer/ImageServer/GeocodeServer/GeometryServer), OGC API
Features, STAC, OData, WFS/WMS/WMTS, and gRPC streaming — with one-call
GeoDataFrame interop for the pandas/GeoPandas stack.

## Packages

Two independently installable, Apache-2.0 packages live under `packages/`:

| Package | Import | Description |
|---------|--------|-------------|
| [`packages/honua-sdk`](packages/honua-sdk/) | `honua_sdk` | Data-plane client — feature queries, geocoding, protocol clients, gRPC streaming, GeoPandas/raster interop, `honua` CLI |
| [`packages/honua-admin`](packages/honua-admin/) | `honua_admin` | Control-plane client — services, connections, layers, styles, metadata, manifests, compatibility checks (depends on `honua-sdk`) |

Also in this repo: [`packages/honua-gp`](packages/honua-gp/), a proprietary
geoprocessing compatibility layer for teams migrating scripts from ArcGIS
`arcpy` (separate license, not published), and
[`packages/honua-arcpy`](packages/honua-arcpy/), a deprecated shim that
re-exports it.

## Status

Alpha (`0.x`): `honua-sdk` 0.1.9, `honua-admin` 0.1.6. APIs may change before
1.0; breaking changes to the public API are gated by a
[compatibility snapshot](docs/compatibility.md).

**Not yet published to PyPI** — install from source (below). Release
automation is in place (release-please + a tag-triggered publish workflow
using PyPI Trusted Publishing), so `pip install honua-sdk` becomes the install
path once the first publish lands.

## Install

Requires Python 3.11+ (CI tests 3.11, 3.12, 3.13). Until the packages are on
PyPI, install from a clone:

```bash
git clone https://github.com/honua-io/honua-sdk-python.git
cd honua-sdk-python

# Data-plane client
pip install ./packages/honua-sdk

# With optional extras: gRPC streaming, GeoPandas vector interop,
# raster interop (rasterio / rioxarray / xarray)
pip install "./packages/honua-sdk[grpc,geopandas,raster]"

# Control-plane (admin) client — installs honua-sdk alongside it
pip install ./packages/honua-sdk ./packages/honua-admin
```

Or straight from GitHub without cloning:

```bash
pip install "honua-sdk[geopandas] @ git+https://github.com/honua-io/honua-sdk-python.git@python-sdk-v0.1.9#subdirectory=packages/honua-sdk"
```

The repo-root `pyproject.toml` is intentionally **not** installable (it holds
shared tool config only) — install the per-package directories, not `.`.
[INSTALL.md](INSTALL.md) has extras details and install-time troubleshooting;
its `pip install honua-sdk` commands apply once the packages are published.

## I want to...

| Goal                            | Start here                                                      |
|---------------------------------|-----------------------------------------------------------------|
| Query features in 5 minutes     | [docs/quickstart.md](docs/quickstart.md)                        |
| Stream features over gRPC       | [INSTALL.md#with-grpc](INSTALL.md#with-grpc)                    |
| Build an ETL pipeline           | [examples/geospatial_etl/](examples/geospatial_etl/)            |
| Wire a FastAPI service          | [examples/fastapi_spatial_service.py](examples/fastapi_spatial_service.py) |
| Run spatial queries from Jupyter / pandas | [docs/quickstart.md](docs/quickstart.md) + [examples/data_quality_report.py](examples/data_quality_report.py) |
| Manage services & connections   | [packages/honua-admin/](packages/honua-admin/)                  |
| Understand the protocol matrix  | [docs/protocol-parity.md](docs/protocol-parity.md)              |
| Diagnose an error               | [docs/quickstart.md#common-errors](docs/quickstart.md#common-errors) |

## Quick start

Query features through the canonical `Source` / `Query` / `Result` API and
convert to a GeoDataFrame in one call:

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

    # Requires: pip install "./packages/honua-sdk[geopandas]"
    gdf = result.to_geodataframe()  # GeoDataFrame with geometry column + CRS set
    print(gdf.head(), gdf.crs)
```

`client.source(...)` returns a source-bound facade with `query()`,
`query_all()`, `stream()`/`iter_features()`, `apply_edits()`, and
`protocol(...)`. `source.query()` returns a canonical `Result` of normalized
`QueryFeature` entries (`id`, `properties`, `geometry`, `protocol`, `source`,
`raw`) — the same shape across FeatureServer, OGC API Features, STAC, and
OData. The reverse helper `honua_sdk.geopandas.geodataframe_to_features` turns
an edited GeoDataFrame back into `apply_edits` payloads.

### OGC API Features

```python
from honua_sdk import HonuaClient

with HonuaClient("https://your-honua-server.com") as client:
    ogc = client.ogc_features()
    collections = ogc.collections()

    parcels = ogc.collection("parcels")
    items = parcels.items(limit=100, filter="status = 'active'")
    feature = parcels.item("123")
```

### Geocoding

```python
from honua_sdk import HonuaGeocodingClient

with HonuaGeocodingClient("https://your-honua-server.com") as geocoder:
    results = geocoder.forward_geocode("1600 Pennsylvania Ave NW, Washington, DC")
    for r in results:
        print(f"{r.address}  ({r.latitude}, {r.longitude})  score={r.score}")
```

### Async

Every HTTP workflow has an async counterpart with the same factory and method
names — works with FastAPI, asyncio pipelines, and Jupyter:

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
    result = await source.query(Query(where="1=1"))
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

> **Protocol IDs.** Docs and examples use the canonical cross-SDK protocol ids
> (`geoservices-feature-service`, `ogc-features`, `stac`, `odata`, ...).
> Common aliases (`feature-server`, `ogc-api-features`, ...) are accepted at
> runtime and normalized by `honua_sdk.normalize_protocol(...)`; the full
> table lives in `honua_sdk.PROTOCOL_ALIASES`. Compact helpers
> (`client.query(...)`, `client.query_features(...)`) remain for one-liners —
> see [Protocol Examples](docs/protocol-examples.md) for every wrapper and
> [Protocol Parity](docs/protocol-parity.md) for the Python/JS coverage map.

## Key features

| | |
|---|---|
| Typed, canonical query surface | `Source` / `Query` / `Result` with normalized `QueryFeature` across FeatureServer, OGC Features, STAC, OData |
| Protocol clients | GeoServices (Feature/Map/Image/Geocode/Geometry servers), OGC API Features, STAC, OData, WFS, WMS, WMTS — see [protocol parity](docs/protocol-parity.md) |
| GIS interop | `Result.to_geodataframe()`, `features_to_geodataframe` (Esri JSON aware), raster results via `rasterio`/`rioxarray` (`[raster]` extra) |
| gRPC streaming | `honua_sdk.grpc.HonuaGrpcClient` / `HonuaGrpcAsyncClient` for unary + streaming feature queries (`[grpc]` extra) |
| Sync + async | `HonuaClient` / `AsyncHonuaClient` in lockstep (sync clients generated from the async source of truth) |
| Automatic retry | 429/502/503 with exponential backoff and `Retry-After` support; configurable via `max_retries`, `retry_methods` |
| Typed errors | `HonuaAuthError`, `HonuaRateLimitError`, `HonuaHttpError`, `HonuaTimeoutError`, `HonuaTransportError` — see [common errors](docs/quickstart.md#common-errors) |
| CLI | `honua` (services / layers / style apply / sanitized `doctor` diagnostics) and `honua-migrate` (offline ArcPy script scan / translate / `.pyt` classify) |
| Quality gates | mypy `strict` workspace-wide, 94% coverage gate, public-API [compatibility snapshot](docs/compatibility.md), live-server [conformance lane](.github/workflows/conformance.yml) against shared [geospatial-grpc](https://github.com/honua-io/geospatial-grpc) fixtures |

## Documentation

Repo docs live under [docs/](docs/README.md) (MkDocs sources; browsable on
GitHub). Platform-level docs are at
[honua.gitbook.io/honuaio](https://honua.gitbook.io/honuaio/).

- [5-Minute Quickstart](docs/quickstart.md) — query, GeoDataFrame, plot, common errors
- [Core Client](docs/core-client.md) — typed service, FeatureServer, applyEdits, pagination, error handling
- [Protocol Examples](docs/protocol-examples.md) — OGC, STAC, WFS, WMS, WMTS, OData, geocoding, gRPC with response shapes
- [Authentication](docs/auth.md) — refreshable bearer tokens, storage, rotation, failure modes
- [Geospatial ETL demo](examples/geospatial_etl/README.md) — script-first ETL flow with notebook companion
- [Compatibility](docs/compatibility.md) — supported server matrix and public-API snapshot gate
- [Troubleshooting](docs/troubleshooting.md) — base URL, auth, staging smoke env vars, cleanup

## Related Honua repos

| Repo | What it is |
|------|------------|
| [honua-server](https://github.com/honua-io/honua-server) | Flagship multi-protocol geospatial server this SDK talks to |
| [honua-sdk-js](https://github.com/honua-io/honua-sdk-js) | JavaScript/TypeScript SDKs + MCP server |
| [honua-sdk-dotnet](https://github.com/honua-io/honua-sdk-dotnet) | .NET SDKs |
| [honua-console](https://github.com/honua-io/honua-console) | Unified web console (Studio, Catalog, Operate, Share) |
| [honua-qgis-plugin](https://github.com/honua-io/honua-qgis-plugin) | QGIS plugin |
| [geospatial-grpc](https://github.com/honua-io/geospatial-grpc) | Vendor-neutral gRPC protocol standard; source of this repo's conformance fixtures |

## Development

```bash
# Editable install of both packages with extras
pip install -e "packages/honua-sdk[grpc,geopandas]"
pip install -e "packages/honua-admin"
pip install pytest pytest-cov ruff mypy

# Lint + type-check (mypy runs in strict mode)
ruff check .
python -m mypy packages/honua-sdk/honua_sdk packages/honua-admin/honua_admin

# Deterministic local test suite
python3 -m pytest tests/ -q

# Public-API compatibility gate
python3 scripts/compatibility_gate.py
```

Sync clients (`client.py`, `_client.py`) are generated from their async
counterparts — edit the async module and run `python scripts/gen_sync.py`;
never hand-edit the generated files.

Opt-in integration lanes (staging smoke, live-server conformance, release
smoke) need `HONUA_BASE_URL` and the `--run-integration` flag; see
[docs/troubleshooting.md](docs/troubleshooting.md) and
[docs/compatibility.md](docs/compatibility.md) for env vars, markers, and
result artifacts.

Bugs and feature requests: [GitHub issues](https://github.com/honua-io/honua-sdk-python/issues).
Pull requests are welcome — CI enforces lint, strict typing, the coverage
gate, and the compatibility snapshot.

## Security

Report vulnerabilities to <security@honua.io> — see the
[org security policy](https://github.com/honua-io/.github/blob/main/SECURITY.md).
Do not open public issues for security reports.

## License

`honua-sdk` and `honua-admin` are licensed under
[Apache-2.0](LICENSE). `packages/honua-gp` and `packages/honua-arcpy` are
proprietary (see their respective `LICENSE` files) and are not published.
