# Installing the Honua Python SDK

## Packages

| Package | Description |
|---------|-------------|
| `honua-sdk` | Data-plane client for Honua Server -- REST queries, geocoding, gRPC features |
| `honua-admin` | Control-plane / admin client for Honua Server (depends on `honua-sdk`) |

## Prerequisites

- Python 3.11 or later
- A running Honua Server instance

## Install

The canonical install path is PyPI:

```bash
# Core data client (REST/HTTP, sync + async)
pip install honua-sdk

# With extras: gRPC, GeoPandas vector interop, raster interop
pip install "honua-sdk[grpc,geopandas,raster]"

# Admin / control-plane client (installs honua-sdk alongside it)
pip install honua-admin
```

For unreleased development work, install from a clone instead:

```bash
git clone https://github.com/honua-io/honua-sdk-python.git
cd honua-sdk-python

# Core data client (REST/HTTP, sync + async)
pip install ./packages/honua-sdk

# With gRPC support
pip install "./packages/honua-sdk[grpc]"

# With GeoPandas integration (vector result interop)
pip install "./packages/honua-sdk[geopandas]"

# With raster result interop (rasterio / rioxarray / xarray)
pip install "./packages/honua-sdk[raster]"

# Admin / control-plane client (installs honua-sdk alongside it)
pip install ./packages/honua-sdk ./packages/honua-admin

# Everything
pip install "./packages/honua-sdk[grpc,geopandas,raster]" ./packages/honua-admin
```

Or straight from GitHub without cloning, pinned to a release tag
(`python-sdk-v0.1.12` is the `honua-sdk` release that Honua 2026.1 ships):

```bash
pip install "honua-sdk[geopandas] @ git+https://github.com/honua-io/honua-sdk-python.git@python-sdk-v0.1.12#subdirectory=packages/honua-sdk"
```

The repo-root `pyproject.toml` is intentionally **not** installable (it
holds shared tool config only) -- install the per-package directories,
not `.`.

## Quick Start

Check the install against the public, anonymous demo server at
`https://demo.honua.io`. Its `maui-zoning` FeatureServer publishes zoning
polygons as layer `2`. To query your own server, change the base URL, service
and layer.

```python
from honua_sdk import HonuaClient, Query, SourceDescriptor, SourceLocator

with HonuaClient(base_url="https://demo.honua.io") as client:
    # Query features through the shared Source/Query/Result API
    source = client.source(
        SourceDescriptor(
            id="maui-zoning",
            protocol="geoservices-feature-service",
            locator=SourceLocator(service_id="maui-zoning", layer_id=2),
        )
    )
    result = source.query(
        Query(where="island = 'Maui'", out_fields=["*"])
    )

    print(f"Found {len(result.features)} features")
```

The context-manager form (`with HonuaClient(...) as client:`) is the
recommended default -- it guarantees underlying `httpx` connections are
returned to the pool when the block exits, even if a request raises.

## With gRPC

gRPC needs a server of your own, for example one started with the Honua
Server quickstart. Install the `grpc` extra (`pip install "honua-sdk[grpc]"`). The
[Honua Server quickstart](https://github.com/honua-io/honua-server/blob/trunk/docs/get-started/quickstart.md)
serves plaintext gRPC (h2c) on port **8081**. Replace
`your-honua-server.com:8081` with that address, and `maui-zoning` / `2` with
the service and layer id of one of your published layers:

<!-- doc-run: blocked https://github.com/honua-io/honua-sdk-python/issues/259 -->
```python
from honua_sdk.grpc import HonuaGrpcClient, QueryFeaturesRequest

request = QueryFeaturesRequest(service_id="maui-zoning", layer_id=2)

# Local dev: plaintext channel (must opt in explicitly)
with HonuaGrpcClient("your-honua-server.com:8081", insecure=True) as client:
    # Stream features
    for page in client.query_features_stream(request):
        print(f"Page with {len(page.features)} features")
```

In production, terminate TLS in front of the gRPC listener and pass channel
credentials instead of `insecure=True`. Replace `grpc.your-honua-server.com:443`
with the `host:port` of that TLS endpoint:

<!-- doc-run: blocked https://github.com/honua-io/honua-release/issues/423 -->
```python
import grpc

from honua_sdk.grpc import HonuaGrpcClient, QueryFeaturesRequest

request = QueryFeaturesRequest(service_id="maui-zoning", layer_id=2)

with HonuaGrpcClient(
    "grpc.your-honua-server.com:443",
    credentials=grpc.ssl_channel_credentials(),
) as client:
    for page in client.query_features_stream(request):
        print(f"Page with {len(page.features)} features")
```

The constructor takes `target` positionally; pass exactly one of
`credentials=`, `channel=`, or `insecure=True`. The same shape is used
in [docs/quickstart.md](docs/quickstart.md#step-6-query-via-grpc-optional-60-seconds).

## Admin

Admin needs a server of your own: the public demo returns `401` for
`/api/v1/admin/*`. Set `HONUA_API_KEY` to an admin API key for your server (the
[honua-server quickstart](https://github.com/honua-io/honua-server/blob/trunk/docs/get-started/quickstart.md)
shows how to mint one with `HONUA_ADMIN_PASSWORD`).

```python
import os

from honua_admin import HonuaAdminClient

with HonuaAdminClient("https://your-honua-server.com", api_key=os.environ["HONUA_API_KEY"]) as admin:
    compatibility = admin.check_compatibility()
    if not compatibility.supported:
        raise RuntimeError("; ".join(compatibility.reasons))

    features = admin.get_capability_flags()
    if features.metadata_resources:
        print("Metadata resources are supported on this server.")
```

## Version Policy

- **Pre-release** (`0.x.xaN`, `0.x.xbN`): Published to PyPI with alpha/beta classifiers
- **Stable** (`1.0.0+`): Published to PyPI as a stable release

All packages follow [Semantic Versioning](https://semver.org/). Major versions are coordinated across all Honua SDKs.

## Admin Compatibility Checks

The admin SDK uses `GET /api/v1/admin/capabilities` as the runtime compatibility
source of truth. It currently expects:

- server version `>= 1.0.0`, including the year-led release line (`2026.1.1`)
- control-plane API major `v1`
- release channel `preview` or newer

The coarse feature flags exposed today are:

- `metadata_resources`
- `manifest_export`
- `manifest_apply`
- `manifest_dry_run`
- `manifest_prune`

## Canonical vs legacy API

New code should prefer the canonical `Source` / `Query` / `Result`
surface:

```python
from honua_sdk import HonuaClient, Query, SourceDescriptor, SourceLocator

with HonuaClient(base_url="https://demo.honua.io") as client:
    source = client.source(
        SourceDescriptor(
            id="maui-zoning",
            protocol="geoservices-feature-service",
            locator=SourceLocator(service_id="maui-zoning", layer_id=2),
        )
    )
    result = source.query(Query(where="island = 'Maui'", out_fields=["*"]))
    for feature in result.features:
        # Typed ``QueryFeature`` -- attributes live under ``.properties``.
        print(feature.id, feature.properties)
```

`client.query_features(service_id, layer_id, where=...)` and the rest
of the raw-dict FeatureServer helpers remain available as the **legacy
/ compact form**. They return raw JSON dicts (FeatureServer
`attributes`-shaped payloads) and are useful for one-liners, scripting,
and protocol-debugging. New library code should reach for the canonical
form so it gets:

- typed `Result[QueryFeature]` with `.properties` / `.geometry` /
  `.protocol`
- protocol-aware filter routing (CQL2-text vs SQL `WHERE`) -- including
  the `where_as_cql=True` opt-in for callers who *want* a SQL-style
  string forwarded as CQL on OGC Features or STAC
- consistent pagination signals across FeatureServer, OGC Features,
  STAC, and OData

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md) for the full
guide. The most common install-time failures:

- **gRPC wheel build fails on macOS Apple Silicon** -- upgrade pip
  (`python -m pip install --upgrade pip`) so it picks the prebuilt
  `grpcio` arm64 wheel instead of falling back to source.
- **GeoPandas / Shapely fails on Windows** -- install the
  `honua-sdk[geopandas]` extra inside a `conda` env (or under WSL); the
  pip path on Windows requires a working GEOS / GDAL toolchain.
- **Python 3.10 install fails with a version-pin error** -- the SDK
  requires Python 3.11+. Upgrade your interpreter or pin a 3.11+ venv.
- **"Microsoft Visual C++ 14.0 is required" / "command 'gcc' failed"**
  -- a transitive dep is building from source because no wheel matched
  your platform. Install your platform's C compiler (Build Tools for
  Visual Studio on Windows, `xcode-select --install` on macOS,
  `build-essential` on Debian/Ubuntu) and re-run pip.
