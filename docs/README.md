# Honua SDK Documentation

This directory holds the long-form docs for the Honua Python SDKs
(`honua-sdk` data-plane, `honua-admin` control-plane). The monorepo
[README](../README.md) covers installation and the high-level package map;
the pages below are organized by audience.

## The canonical shape

```python
from honua_sdk import HonuaClient, Query, SourceDescriptor, SourceLocator

with HonuaClient("https://your-honua-server.com") as client:
    source = client.source(
        SourceDescriptor(
            id="test_service",
            protocol="geoservices-feature-service",
            locator=SourceLocator(service_id="test_service", layer_id=0),
        )
    )
    result = source.query(Query(where="status = 'active'", out_fields=["*"]))
    for feature in result.features[:3]:
        print(feature.id, feature.properties)
```

## I want to...

| Goal                            | Start here                                                      |
|---------------------------------|-----------------------------------------------------------------|
| Query features in 5 minutes     | [quickstart.md](quickstart.md)                                  |
| Stream features over gRPC       | [../INSTALL.md#with-grpc](../INSTALL.md#with-grpc)              |
| Build an ETL pipeline           | [../examples/geospatial_etl/](../examples/geospatial_etl/)      |
| Wire a FastAPI service          | [../examples/fastapi_spatial_service.py](../examples/fastapi_spatial_service.py) |
| Manage services & connections   | [../packages/honua-admin/](../packages/honua-admin/)            |
| Understand the protocol matrix  | [protocol-parity.md](protocol-parity.md)                        |
| Diagnose an error               | [quickstart.md#common-errors](quickstart.md#common-errors)      |

## Get Started

- [quickstart.md](quickstart.md) -- 5-minute setup, install, and first query
  against a running Honua server.
- [examples.md](examples.md) -- runnable demo catalog (geospatial ETL,
  spatial-query cookbook, FastAPI scaffold, data-quality report).

## Reference

- [core-client.md](core-client.md) -- `Source` / `Query` / `Result` facade,
  protocol routing, and capability checks.
- [protocol-examples.md](protocol-examples.md) -- per-protocol recipes for
  FeatureServer, OGC API Features, STAC, OData, WFS/WMS/WMTS, and geocoding.
- [protocol-parity.md](protocol-parity.md) -- supported protocol matrix and
  capability coverage by client surface.
- [auth.md](auth.md) -- bearer tokens, API keys, and refreshable auth
  providers (sync and async).
- [compatibility.md](compatibility.md) -- server compatibility baseline and
  the release gate policy enforced by `check_compatibility()`.
- [troubleshooting.md](troubleshooting.md) -- common errors, HTTP envelopes,
  and how to read `HonuaHttpError` payloads.

## Project process

- [operating-cadence.md](operating-cadence.md) -- release, review, and audit
  cadence followed by the SDK maintainers.
