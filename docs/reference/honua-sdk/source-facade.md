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

**See also**: [Models](models.md) for the `Query` / `Result` shapes, and
[Core client model](../../core-client.md) for how the facade composes over the
underlying clients.

::: honua_sdk.source.Source
::: honua_sdk.source.AsyncSource
