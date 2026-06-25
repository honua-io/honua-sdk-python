# honua-sdk › Models

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
via the [Source facade](source-facade.md).

```python
from honua_sdk import Query

q = Query(where="status = 'active'", out_fields=["id", "name"], limit=100)
for feature in client.source(descriptor).iter_query(q):
    print(feature.id, feature.properties)
```

**See also**: [Source facade](source-facade.md) for the entry point that consumes
these models, [Errors](errors.md) for the exception hierarchy raised on
failure, and [Pagination](../../pagination.md) for how `Result.exceeded_transfer_limit` /
`Result.total_count` map to FeatureServer, OGC Features, STAC, and OData
signals and how `Query.page_size` / `Query.max_pages` drive the pagination loop.

::: honua_sdk.Query
::: honua_sdk.Result
::: honua_sdk.QueryFeature
::: honua_sdk.SourceDescriptor
::: honua_sdk.SourceLocator
::: honua_sdk.FeatureQuery
::: honua_sdk.FeatureQueryResult
