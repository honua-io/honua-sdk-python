# Installing the Honua Python SDK

## Packages

| Package | Description |
|---------|-------------|
| `honua-sdk` | Data-plane client for Honua Server -- REST queries, geocoding, gRPC features |
| `honua-admin` | Control-plane / admin client for Honua Server (depends on `honua-sdk`) |

## Prerequisites

- Python 3.11 or later
- A running Honua Server instance

## Install via pip

```bash
# Core data client (REST/HTTP, sync + async)
pip install honua-sdk

# With gRPC support
pip install honua-sdk[grpc]

# With GeoPandas integration
pip install honua-sdk[geopandas]

# Admin / control-plane client
pip install honua-admin

# Everything
pip install honua-sdk[grpc,geopandas] honua-admin
```

## Quick Start

```python
from honua_sdk import HonuaClient, Query, SourceDescriptor, SourceLocator

with HonuaClient(base_url="https://your-honua-server.com") as client:
    # Query features through the shared Source/Query/Result API
    source = client.source(
        SourceDescriptor(
            id="test_service",
            protocol="geoservices-feature-service",
            locator=SourceLocator(service_id="test_service", layer_id=0),
        )
    )
    result = source.query(
        Query(where="status = 'active'", out_fields=["*"])
    )

    print(f"Found {len(result.features)} features")
```

The context-manager form (`with HonuaClient(...) as client:`) is the
recommended default -- it guarantees underlying `httpx` connections are
returned to the pool when the block exits, even if a request raises.

## With gRPC

```python
import grpc

from honua_sdk.grpc import HonuaGrpcClient, QueryFeaturesRequest

request = QueryFeaturesRequest(service_id="test_service", layer_id=0)

# Production: TLS via channel credentials
with HonuaGrpcClient(
    "grpc.your-honua-server.com:443",
    credentials=grpc.ssl_channel_credentials(),
) as client:
    # Stream features
    for page in client.query_features_stream(request):
        print(page)

# Local dev: plaintext channel (must opt in explicitly)
with HonuaGrpcClient("localhost:50051", insecure=True) as client:
    for page in client.query_features_stream(request):
        print(page)
```

The constructor takes `target` positionally; pass exactly one of
`credentials=`, `channel=`, or `insecure=True`. The same shape is used
in [docs/quickstart.md](docs/quickstart.md#step-6-query-via-grpc-optional-60-seconds).

## Admin

```python
from honua_admin import HonuaAdminClient

with HonuaAdminClient("https://your-honua-server.com", api_key="honua-api-key") as admin:
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

- server version `>= 2026.3.0`
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

with HonuaClient(base_url="https://your-honua-server.com") as client:
    source = client.source(
        SourceDescriptor(
            id="test_service",
            protocol="geoservices-feature-service",
            locator=SourceLocator(service_id="test_service", layer_id=0),
        )
    )
    result = source.query(Query(where="status = 'active'", out_fields=["*"]))
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
