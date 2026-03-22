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
from honua_sdk import HonuaClient

client = HonuaClient(base_url="https://your-honua-server.com")

# Query features
features = client.query_features(
    service_id="my-service",
    layer_id=0,
    where="status = 'active'",
    return_geometry=True,
)

print(f"Found {len(features)} features")
```

## With gRPC

```python
from honua_sdk.grpc import HonuaGrpcClient

client = HonuaGrpcClient(target="grpc.your-honua-server.com:443")

# Stream features
for page in client.query_features_stream(request):
    print(page)
```

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
