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

## Geometry, schema, and GeoDataFrame ergonomics

For ArcGIS-style geoprocessing authoring, the typed feature models carry a
first-class geometry bridge and the source facade exposes typed layer schema and
`arcpy.da`-style cursors:

* [`Feature`][honua_sdk.Feature] / [`QueryFeature`][honua_sdk.QueryFeature]
  expose `.to_shapely()`, a cached `.geometry_shape`, and the
  `__geo_interface__` protocol — Shapely geometry directly off the typed
  feature (the `arcpy` `feature.SHAPE` analogue), for both Esri-JSON and GeoJSON
  sources. Shapely stays an optional dependency.
* [`LayerSchema`][honua_sdk.LayerSchema] (with typed
  [`Field`][honua_sdk.Field] / [`Extent`][honua_sdk.Extent]) is the
  `arcpy.Describe` / `ListFields` analogue — `Source.schema()` /
  `feature_server.schema()` parse FeatureServer layer metadata into typed
  fields, normalized geometry type, resolved SRID, and a typed extent.
* `Result.to_geodataframe()` / `Source.to_geodataframe(...)` are the
  Spatially-Enabled-DataFrame equivalent: one call from a query result to a
  GeoPandas `GeoDataFrame` (requires the `geopandas` extra).
* `Source.search_cursor` / `update_cursor` / `insert_cursor` (see the
  [Source facade](source-facade.md)) provide the `arcpy.da` cursor idioms over
  streaming query + batched `apply_edits`.

::: honua_sdk.Query
::: honua_sdk.Result
::: honua_sdk.QueryFeature
::: honua_sdk.Feature
::: honua_sdk.LayerSchema
::: honua_sdk.Field
::: honua_sdk.Extent
::: honua_sdk.SourceDescriptor
::: honua_sdk.SourceLocator
::: honua_sdk.FeatureQuery
::: honua_sdk.FeatureQueryResult
