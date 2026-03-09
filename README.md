# Honua Python SDK

Python client library for [Honua Server](https://github.com/honua-io) --
query geospatial features, geocode addresses, manage services, and stream
data over gRPC.

## Features

- **HonuaClient** -- query and edit features, export maps, check server health
- **HonuaGeocodingClient** -- forward/reverse geocoding and typeahead suggestions
- **HonuaAdminClient** -- manage services, connections, layers, styles, and metadata
- **HonuaGrpcClient** -- synchronous and async streaming feature queries via gRPC
- Auth support for API-key (`X-API-Key`) and Bearer token
- Typed error hierarchy: `HonuaHttpError`, `HonuaGrpcError`

## Install

```bash
# Core SDK (REST/HTTP)
pip install honua-sdk

# With gRPC support
pip install honua-sdk[grpc]
```

Requires Python 3.11+. See [INSTALL.md](INSTALL.md) for full details.

## Quick Example

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

## Geocoding

```python
from honua_sdk import HonuaGeocodingClient

with HonuaGeocodingClient("https://your-honua-server.com") as geocoder:
    results = geocoder.forward_geocode("1600 Pennsylvania Ave NW, Washington, DC")
    for r in results:
        print(f"{r.address}  ({r.latitude}, {r.longitude})  score={r.score}")
```

## Admin Compatibility Handshake

```python
from honua_sdk.admin import HonuaAdminClient, MINIMUM_SUPPORTED_SERVER_VERSION

with HonuaAdminClient("https://your-honua-server.com", api_key="honua-api-key") as admin:
    compatibility = admin.check_compatibility()
    if not compatibility.supported:
        raise RuntimeError(
            f"Unsupported server. Minimum supported version is "
            f"{MINIMUM_SUPPORTED_SERVER_VERSION}. "
            + "; ".join(compatibility.reasons)
        )

    features = admin.get_capability_flags()
    if features.manifest_apply:
        manifest = admin.get_manifest()
        print(f"Manifest resources: {len(manifest.resources)}")
```

The admin SDK currently expects:
- server version `>= 2026.3.0`
- control-plane API major `v1`
- server release channel `preview` or newer

## Documentation

- [5-Minute Quickstart](docs/quickstart.md) -- query, GeoDataFrame, and plot
- [INSTALL.md](INSTALL.md) -- installation options and version policy
- [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) -- release automation and publishing checklist
- [gRPC usage](honua_sdk/grpc/) -- streaming feature queries
- [Admin client](honua_sdk/admin/) -- server administration

## Status

This package is in **alpha** (`0.x`).
Release automation is configured for PyPI publishing from `python-sdk-v<version>` tags.
APIs may change before the 1.0 stable release.

## Development

```bash
python3 -m pytest tests -q
```

## License

Apache-2.0
