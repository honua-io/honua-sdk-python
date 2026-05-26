# honua-sdk Reference

## Clients

Two top-level clients share the same surface area and configuration model.
Use [`HonuaClient`][honua_sdk.HonuaClient] for synchronous scripts, notebooks,
and tools backed by ``httpx`` — and reach for
[`AsyncHonuaClient`][honua_sdk.AsyncHonuaClient] in async services
(FastAPI, ``asyncio`` workers) where you need concurrent I/O. Both clients
expose the same canonical ``query``/``iter_query`` dispatcher and the same
protocol-specific escape hatches; see
[Core client model](../core-client.md) for the conceptual map of options,
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

**See also**: [Source facade](#source-facade) for the canonical query path,
[Core client model](../core-client.md) for `with_options(...)` semantics,
and [Retries and timeouts](../retries-and-timeouts.md) for the retry policy,
`Retry-After` handling, and per-call / `with_options(...)` timeout behaviour.

::: honua_sdk.HonuaClient
::: honua_sdk.AsyncHonuaClient
::: honua_sdk.HonuaGeocodingClient
::: honua_sdk.AsyncHonuaGeocodingClient

## Source facade

The canonical entry point for portable code is the ``Source`` facade —
``client.source(SourceDescriptor(...)).query(Query(...))`` returns a
[`Result[QueryFeature]`][honua_sdk.Result] regardless of whether the
underlying source is a GeoServices FeatureServer, an OGC Features collection,
a STAC catalog, or an OData entity set. Prefer this path when you want
behaviour that is consistent across protocols; reach for the
protocol-specific clients (``feature_server(...)``, ``ogc_features()``,
``stac()``, ``odata()``) when you need protocol-native operations not
covered by the canonical surface.

See [Protocol examples](../protocol-examples.md) for side-by-side recipes
that show the same query running against each supported protocol via the
facade.

```python
from honua_sdk import Query, SourceDescriptor, SourceLocator

descriptor = SourceDescriptor(id="svc", protocol="geoservices-feature-service",
                              locator=SourceLocator(service_id="svc", layer_id=0))
result = client.source(descriptor).query(Query(where="1=1"))
```

**See also**: [Models](#models) for the `Query` / `Result` shapes, and
[Core client model](../core-client.md) for how the facade composes over the
underlying clients.

::: honua_sdk.source.Source
::: honua_sdk.source.AsyncSource

## Models

These dataclasses make up the canonical request/response shape.
[`Query`][honua_sdk.Query] is the **input** type — it captures filter,
projection, and pagination intent in a protocol-agnostic way.
[`Result[QueryFeature]`][honua_sdk.Result] is the **canonical output**:
each feature exposes GeoJSON-shaped ``.geometry`` and ``.properties`` plus
the resolved ``protocol`` and ``source`` tags.

[`FeatureQuery`][honua_sdk.FeatureQuery] and
[`FeatureQueryResult`][honua_sdk.FeatureQueryResult] are the legacy
GeoServices-flavoured shape, where each feature has ``.attributes``
(raw GeoServices field bag) rather than ``.properties`` — they remain
on the public API for the existing ``HonuaClient.query`` /
``iter_query`` dispatcher and to keep typed access to FeatureServer
responses. New code should prefer ``Query`` / ``Result[QueryFeature]``
via the [Source facade](#source-facade).

```python
from honua_sdk import Query

q = Query(where="status = 'active'", out_fields=["id", "name"], limit=100)
for feature in client.source(descriptor).iter_query(q):
    print(feature.id, feature.properties)
```

**See also**: [Source facade](#source-facade) for the entry point that consumes
these models, [Errors](#errors) for the exception hierarchy raised on
failure, and [Pagination](../pagination.md) for how `Result.exceeded_transfer_limit` /
`Result.total_count` map to FeatureServer, OGC Features, STAC, and OData
signals and how `Query.page_size` / `Query.max_pages` drive the pagination loop.

::: honua_sdk.Query
::: honua_sdk.Result
::: honua_sdk.QueryFeature
::: honua_sdk.SourceDescriptor
::: honua_sdk.SourceLocator
::: honua_sdk.FeatureQuery
::: honua_sdk.FeatureQueryResult

## Errors

The SDK raises a focused hierarchy rooted at
[`HonuaError`][honua_sdk.errors.HonuaError]. HTTP-shaped failures derive
from [`HonuaHttpError`][honua_sdk.errors.HonuaHttpError], with
[`HonuaAuthError`][honua_sdk.errors.HonuaAuthError] (401/403) and
[`HonuaRateLimitError`][honua_sdk.errors.HonuaRateLimitError] (429) as
the two specialized HTTP subclasses worth catching individually.
Transport-level failures derive from
[`HonuaTransportError`][honua_sdk.errors.HonuaTransportError], with
[`HonuaTimeoutError`][honua_sdk.errors.HonuaTimeoutError] for explicit
deadline misses.

Catch ``HonuaError`` to handle any SDK failure; catch the narrower
subclasses when you want retry or surfacing logic tuned to a specific
failure mode. See
[Quickstart › Common errors](../quickstart.md#common-errors) for
worked examples.

```python
from honua_sdk import HonuaRateLimitError, HonuaTimeoutError

try:
    result = client.query_features("svc", 0)
except HonuaRateLimitError as exc:
    retry_after = exc.retry_after
```

**See also**: [Quickstart › Common errors](../quickstart.md#common-errors)
for retry recipes, and [Clients](#clients) for how `timeout=` and
`with_options(timeout=...)` interact with `HonuaTimeoutError`.

::: honua_sdk.errors.HonuaError
::: honua_sdk.errors.HonuaHttpError
::: honua_sdk.errors.HonuaAuthError
::: honua_sdk.errors.HonuaRateLimitError
::: honua_sdk.errors.HonuaTransportError
::: honua_sdk.errors.HonuaTimeoutError
