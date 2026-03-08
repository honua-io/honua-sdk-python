# Installing the Honua Python SDK

## Package

| Package | Description |
|---------|-------------|
| `honua-sdk` | Python client for Honua Server — REST admin, gRPC features |

## Prerequisites

- Python 3.11 or later
- A running Honua Server instance

## Install via pip

```bash
# Core SDK (REST/HTTP client)
pip install honua-sdk

# With gRPC support
pip install honua-sdk[grpc]
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

client = HonuaGrpcClient(endpoint="grpc.your-honua-server.com:443")

# Stream features
async for feature in client.stream_features(service_id="my-service", layer_id=0):
    print(feature.id, feature.geometry)
```

## Version Policy

- **Pre-release** (`0.x.xaN`, `0.x.xbN`): Published to PyPI with alpha/beta classifiers
- **Stable** (`1.0.0+`): Published to PyPI as a stable release

All packages follow [Semantic Versioning](https://semver.org/). Major versions are coordinated across all Honua SDKs.
