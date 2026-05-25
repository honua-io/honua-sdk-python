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

    if client.supports("geoservices-feature-service"):
        services = client.list_service_summaries()
```

Older servers that do not expose `/api/v1/capabilities` fall back to readiness
and GeoServices catalog discovery.

## Shared Source Queries

For application code that wants the same shape across data protocols, prefer
the shared Source/Query/Result API. `client.source(...)` binds a
`SourceDescriptor` to a reusable facade; `source.query()` collects normalized
`QueryFeature` entries, and `source.stream()`/`source.iter_features()` streams
the same normalized features:

```python
from honua_sdk import HonuaClient, Query, SourceDescriptor, SourceLocator

with HonuaClient("https://honua.example") as client:
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

    for feature in result.features:
        print(feature.id, feature.properties, feature.geometry)

    native = parcels.protocol()
    metadata = native.layer_metadata(0)
```

The source facade uses canonical cross-SDK protocol ids such as
`geoservices-feature-service`, `ogc-features`, `stac`, and `odata`; common
aliases such as `feature-server`, `featureserver`, `feature-service`, and
`ogc_api_features` are accepted. The full alias table is exposed as
`honua_sdk.PROTOCOL_ALIASES` and normalized through
`honua_sdk.normalize_protocol(...)`. Python uses snake_case for query fields
(`out_fields`, `return_geometry`, `query_all()`), while TypeScript and .NET use
their idiomatic casing.
`SourceDescriptor.supports(...)` reflects protocol-advertised capabilities;
`source.supports(...)` reflects the normalized operations this Python facade can
execute directly. Use `source.protocol(...)` for native protocol operations that
are advertised but not normalized by the shared facade.

The compact client-level helpers remain available for existing callers and for
one-off queries. `client.query()` returns a `FeatureQueryResult`; `iter_query()`
streams normalized features from FeatureServer, OGC API Features, STAC, or
OData:

```python
from honua_sdk import FeatureQuery, HonuaClient

with HonuaClient("https://honua.example") as client:
    ogc_features = client.query(
        "parcels",
        protocol="ogc-features",
        filter="status = 'active'",
        bbox=[-180, -90, 180, 90],
        fields=["name", "status"],
        limit=2000,
    )

    odata_features = client.query(
        "4",
        protocol="odata",
        filter="Status eq 'active'",
        fields=["ObjectId", "Name"],
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
```

Use the protocol-specific clients below when you need exact native payloads,
server-specific query options, or endpoint metadata.

`query_features()` returns the raw FeatureServer response. `query_feature_set()`
wraps the same response in a `FeatureSet` with typed `Feature` entries:

> **Legacy typed shape.** `Feature.attributes` is the raw GeoServices key-value
> shape. The canonical `Source.query()` shown above returns `QueryFeature` with
> GeoJSON-style `feature.properties`. Use `query_feature_set()` when you want
> the FeatureServer-shaped wrapper; prefer the `Source` facade in new code.

```python
from honua_sdk import HonuaClient

with HonuaClient("https://honua.example") as client:
    feature_set = client.query_feature_set(
        service_id="parcels",
        layer_id=0,
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
        service_id="parcels",
        layer_id=0,
        where="1=1",
        page_size=500,
        limit=2000,
    )

    feature_server = client.feature_server("parcels")
    for page in feature_server.query_pages(layer_id=0, page_size=500, limit=2000):
        print(len(page.features), page.exceeded_transfer_limit)

    for feature in feature_server.query_items(layer_id=0, page_size=500, limit=2000):
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
    features = await client.query_features_all(
        service_id="parcels",
        layer_id=0,
        page_size=500,
    )

    async for feature in client.feature_server("parcels").query_items(layer_id=0, page_size=500):
        print(feature.object_id)
```

## Edits

`apply_edits()` returns raw JSON. `apply_edits_result()` wraps add, update, and
delete outcomes in typed operation results:

```python
result = client.apply_edits_result(
    service_id="parcels",
    layer_id=0,
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
