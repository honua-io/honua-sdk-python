# Core Client

The SDK keeps the original protocol-native methods for callers that need exact
server JSON, and adds typed wrappers for common early-adopter workflows.

## Service Catalog

Use `list_services()` when you need the raw `/rest/services` payload:

```python
from honua_sdk import HonuaClient

with HonuaClient("https://honua.example") as client:
    payload = client.list_services()
```

Use `list_service_summaries()` when you want typed service entries:

```python
from honua_sdk import HonuaClient

with HonuaClient("https://honua.example") as client:
    services = client.list_service_summaries()
    for service in services:
        print(service.name, service.type)
```

## Capability Discovery

Use `capabilities()` when you need the advertised data-plane protocols and
feature flags before choosing an optional surface. `supports()` checks a single
protocol or feature name:

```python
from honua_sdk import HonuaClient

with HonuaClient("https://honua.example") as client:
    capabilities = client.capabilities()

    if capabilities.supports("stac"):
        items = client.stac().items("imagery")

    if client.supports("feature-server"):
        services = client.list_service_summaries()
```

Older servers that do not expose `/api/v1/capabilities` fall back to readiness
and GeoServices catalog discovery.

## FeatureServer Queries

`query_features()` returns the raw FeatureServer response. `query_feature_set()`
wraps the same response in a `FeatureSet` with typed `Feature` entries:

```python
from honua_sdk import HonuaClient

with HonuaClient("https://honua.example") as client:
    feature_set = client.query_feature_set(
        "parcels",
        0,
        where="status = 'active'",
        out_fields=["objectid", "name", "status"],
    )

    for feature in feature_set.features:
        print(feature.object_id, feature.attributes["name"])
```

The raw response is preserved on `FeatureSet.raw` and `Feature.raw` for fields
that are not lifted into typed attributes.

## Pagination

Use `query_features_all()` to collect a FeatureServer layer with `resultOffset`
and `resultRecordCount`. Use `client.feature_server(service_id).query_pages()`
or `query_items()` when you want to stream pages or individual typed features:

```python
from honua_sdk import HonuaClient

with HonuaClient("https://honua.example") as client:
    features = client.query_features_all(
        "parcels",
        0,
        where="1=1",
        page_size=500,
        limit=2000,
    )

    feature_server = client.feature_server("parcels")
    for page in feature_server.query_pages(0, page_size=500, limit=2000):
        print(len(page.features), page.exceeded_transfer_limit)

    for feature in feature_server.query_items(0, page_size=500, limit=2000):
        print(feature.object_id)
```

The helper stops when:

- the requested `limit` is reached
- a page returns fewer features than requested
- `exceededTransferLimit` is absent or false
- `max_pages` is reached

Use `max_pages` as a guardrail for broad queries. Keep `page_size` aligned with
the server layer's configured maximum record count.

The async client exposes the same methods:

```python
from honua_sdk import AsyncHonuaClient

async with AsyncHonuaClient("https://honua.example") as client:
    features = await client.query_features_all("parcels", 0, page_size=500)

    async for feature in client.feature_server("parcels").query_items(0, page_size=500):
        print(feature.object_id)
```

## Edits

`apply_edits()` returns raw JSON. `apply_edits_result()` wraps add, update, and
delete outcomes in typed operation results:

```python
result = client.apply_edits_result(
    "parcels",
    0,
    updates=[
        {
            "attributes": {"objectid": 10, "status": "retired"},
        }
    ],
)

if not result.all_succeeded:
    print(result.raw)
```

## Errors And Retries

Non-2xx HTTP responses raise `HonuaHttpError`. The exception includes:

- `status_code`
- `message`
- `body`, when the server response body can be parsed or decoded

Transport failures such as DNS, TLS, or connection errors are normalized to
`HonuaHttpError` with `status_code == 0`.

Clients retry transient responses through the shared retry transport. Retry is
limited to `429`, `502`, and `503`, with `Retry-After` support when the server
provides it. Auth failures such as `401` and `403` are not retried; refresh or
replace credentials before retrying those requests.
