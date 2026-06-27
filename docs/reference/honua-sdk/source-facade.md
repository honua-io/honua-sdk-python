# honua-sdk › Source facade

The canonical entry point for portable code is the ``Source`` facade —
``client.source(SourceDescriptor(...)).query(Query(...))`` returns a
[`Result[QueryFeature]`][honua_sdk.Result] regardless of whether the
underlying source is a GeoServices FeatureServer, an OGC Features collection,
a STAC catalog, or an OData entity set. Prefer this path when you want
behaviour that is consistent across protocols; reach for the
protocol-specific clients (``feature_server(...)``, ``ogc_features()``,
``stac()``, ``odata()``) when you need protocol-native operations not
covered by the canonical surface.

See [Protocol examples](../../protocol-examples.md) for side-by-side recipes
that show the same query running against each supported protocol via the
facade.

```python
from honua_sdk import Query, SourceDescriptor, SourceLocator

descriptor = SourceDescriptor(id="svc", protocol="geoservices-feature-service",
                              locator=SourceLocator(service_id="svc", layer_id=0))
result = client.source(descriptor).query(Query(where="1=1"))
```

## arcpy.da-style cursors

For geoprocessing authoring the facade exposes the `arcpy.da` cursor idioms over
the streaming query and batched `apply_edits`:

```python
source = client.source(descriptor)

# SearchCursor: lazily iterate (attrs, geometry) rows; "SHAPE@" selects geometry.
for name, shape in source.search_cursor(["NAME", "SHAPE@"], where="POP > 1000"):
    ...

# UpdateCursor: iterate rows, edit, write back in batches.
with source.update_cursor(where="STATUS = 'stale'") as cursor:
    for row in cursor:
        cursor.update_row(row, attributes={"STATUS": "reviewed"})

# InsertCursor: batched feature inserts.
with source.insert_cursor() as cursor:
    cursor.insert_row({"NAME": "New"}, {"x": -100.0, "y": 40.0})
```

`Source.schema()` returns a typed [`LayerSchema`][honua_sdk.LayerSchema]
(`arcpy.Describe` analogue) and `Source.to_geodataframe(...)` returns a GeoPandas
`GeoDataFrame` in one call (the Spatially-Enabled-DataFrame equivalent; requires
the `geopandas` extra).

**See also**: [Models](models.md) for the `Query` / `Result` shapes, and
[Core client model](../../core-client.md) for how the facade composes over the
underlying clients.

::: honua_sdk.source.Source
::: honua_sdk.source.AsyncSource
::: honua_sdk.cursors.SearchCursor
::: honua_sdk.cursors.UpdateCursor
::: honua_sdk.cursors.InsertCursor
::: honua_sdk.cursors.Row
