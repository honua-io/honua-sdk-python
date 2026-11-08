---
type: reference
title: "honua-sdk clients"
description: "Generated API reference for the data-plane client classes and their methods."
resource: "https://pypi.org/project/honua-sdk/"
tags: [api-reference, honua-sdk]
---
# honua-sdk › Clients

Two top-level clients share the same surface area and configuration model.
Use [`HonuaClient`][honua_sdk.HonuaClient] for synchronous scripts, notebooks,
and tools backed by ``httpx`` — and reach for
[`AsyncHonuaClient`][honua_sdk.AsyncHonuaClient] in async services
(FastAPI, ``asyncio`` workers) where you need concurrent I/O. Both clients
expose the same canonical ``query``/``iter_query`` dispatcher and the same
protocol-specific escape hatches; see
[Core client model](../../core-client.md) for the conceptual map of options,
retries, and ``with_options(...)`` semantics that apply to both.

The geocoding clients ([`HonuaGeocodingClient`][honua_sdk.HonuaGeocodingClient]
and [`AsyncHonuaGeocodingClient`][honua_sdk.AsyncHonuaGeocodingClient]) are
dedicated thin wrappers for the geocoding endpoint and keep the same
configuration knobs.

```python
from honua_sdk import HonuaClient

with HonuaClient("https://your-honua-server.com", timeout=30.0) as client:
    services = client.list_services()
```

## Folder discovery and returned Service links

`list_services(folder_name="Survey")` and
`list_service_summaries(folder_name="Survey")` read one Folder. Omitting
`folder_name` keeps Root discovery. Folder names are encoded as one segment.

Use `ServiceAddress` for an advertised service-level FeatureServer, MapServer
or ImageServer URL. Both absolute and root-relative links preserve the
advertised path, including a deployment prefix. Absolute links must stay on
the client's configured origin. Credentials, query strings and fragments do
not belong in a Service address.

```python
from honua_sdk import HonuaClient, ServiceAddress

with HonuaClient("https://your-honua-server.com") as client:
    address = ServiceAddress("/rest/services/Survey/Parcels/FeatureServer")
    features = client.query_features(address, 0)
    metadata = client.feature_server(address).metadata()
```

Use the matching protocol URL for `export_map` or an ImageServer wrapper.
Existing string Service identifiers remain encoded as one segment:
`"Survey/Parcels"` as a plain string still means a single identifier containing
a slash. A Folder path requires an explicit `ServiceAddress`.

**See also**: [Source facade](source-facade.md) for the canonical query path,
[Core client model](../../core-client.md) for `with_options(...)` semantics,
and [Retries and timeouts](../../retries-and-timeouts.md) for the retry policy,
`Retry-After` handling, and per-call / `with_options(...)` timeout behaviour.

::: honua_sdk.HonuaClient
::: honua_sdk.AsyncHonuaClient
::: honua_sdk.HonuaGeocodingClient
::: honua_sdk.AsyncHonuaGeocodingClient

## OGC API Processes

The process clients operate process definitions already registered on Honua.
They do not provide a custom-code upload, packaging, or local execution API.

::: honua_sdk.geoprocessing.HonuaGeoprocessing
::: honua_sdk.geoprocessing.AsyncHonuaGeoprocessing
