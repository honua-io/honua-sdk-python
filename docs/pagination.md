# Pagination

This deep-dive explains how the Source facade represents pagination, how
each underlying protocol's pagination signals are normalized, and how to
choose between collected and streaming query patterns.

The behaviour described here is implemented in `honua_sdk.source` and the
protocol pagination wrappers it delegates to.

## Canonical signals on `Result`

`source.query(...)` returns a [`Result[QueryFeature]`][honua_sdk.Result]
whose `exceeded_transfer_limit` and `total_count` fields are sourced
from **real server signals** — never fabricated from `len(features)`.
See `_result_from_legacy` in `honua_sdk/source.py`:

> Pagination fidelity: `exceeded_transfer_limit` and `total_count` are
> sourced from the underlying `FeatureQueryResult` (which captures
> protocol-specific signals such as FeatureServer's
> `exceededTransferLimit`, OGC/STAC's `numberMatched` and next-link,
> and OData's `@odata.count` / `@odata.nextLink`) rather than being
> silently fabricated from `len(features)`.

When the server does not advertise a total count, `total_count` falls
back to `len(features)` so callers can always read an integer.

## Per-protocol pagination signals

| Protocol | "More data" signal | "Total" signal | Next-page mechanic |
|----------|--------------------|----------------|--------------------|
| GeoServices FeatureServer | `exceededTransferLimit: true` | `count` query | `resultOffset` / `resultRecordCount` |
| OGC API Features | `next` link relation | `numberMatched` | `next` link URL (server-rendered) |
| STAC | `next` link relation | `numberMatched` | `next` link URL |
| OData | `@odata.nextLink` | `@odata.count` | `@odata.nextLink` URL |

The Source facade normalizes these onto `Result.exceeded_transfer_limit`
and `Result.total_count`; the protocol-specific raw response remains
available via `result.raw_legacy` (and `result.features[i].raw` per
feature) for callers who need the underlying mechanics.

## Iterator vs collected patterns

Three patterns are supported on every `Source`:

| Call | Returns | Use when |
|------|---------|----------|
| `source.query(q)` | `Result[QueryFeature]` (collected) | Page count is small and you want signals (`exceeded_transfer_limit`, `total_count`). |
| `source.query_all(q)` | `tuple[QueryFeature, ...]` | You want every page collected into memory, no signals needed. |
| `source.stream(q)` / `source.iter_features(q)` | `Iterator[QueryFeature]` | You want to drain a large result set without buffering all pages. |

The async counterpart (`AsyncSource`) exposes the same three: `await
source.query(...)`, `await source.query_all(...)`, and `async for
feature in source.stream(...)`.

## `Query.page_size` and `Query.max_pages`

Two `Query` knobs control the underlying pagination loop:

- **`page_size`** — maximum features requested per HTTP round-trip.
  Forwarded to FeatureServer's `resultRecordCount`, OGC/STAC's `limit`,
  and OData's `$top` (subject to server-side caps).
- **`max_pages`** — upper bound on the number of pages the iterator
  will fetch. The `client.query` / `client.iter_query` facades default
  this cap to **100**; pass **`max_pages=None`** for an *unbounded* walk
  that drains until the server stops advertising more pages. When a
  bounded `client.query` walk stops at the cap while the server still
  reports more features (`exceededTransferLimit`), a `ResourceWarning`
  is emitted so a large iterate never silently truncates — raise
  `max_pages`, set it to `None`, or pass a `limit` to acknowledge it.

```python
from honua_sdk import Query

q = Query(where="1=1", page_size=500, max_pages=20)
for feature in source.iter_features(q):
    process(feature)

# Unbounded drain (no hidden 100-page cap):
for feature in client.iter_query("parcels", page_size=1000, max_pages=None):
    process(feature)
```

## Server-side spatial filters and statistics (FeatureServer)

`client.query` / `Source.query` accept an arbitrary-geometry spatial
filter and server-side statistics on the GeoServices FeatureServer path,
mirroring Esri's `query(geometry=..., spatial_relationship=...)` and
arcpy summary-statistics queries.

```python
# "Select by location": features WITHIN a polygon (Esri JSON, GeoJSON, or
# any shapely/`__geo_interface__` geometry are accepted).
result = client.query(
    "parcels",
    spatial_filter={
        "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [0, 0]]]},
        "relationship": "within",     # intersects / within / contains / crosses / touches / overlaps / within-distance
        "in_sr": 4326,
    },
)

# Within-distance ("buffer" select):
client.query(
    "stations",
    spatial_filter={"geometry": {"x": -73.0, "y": 40.7}, "relationship": "within-distance",
                    "distance": 500, "units": "meters"},
)

# Server-side statistics + group-by:
summary = client.query(
    "parcels",
    out_statistics=[{"statistic_type": "sum", "on_statistic_field": "area", "out_statistic_field_name": "total_area"}],
    group_by="zone",
)

# Distinct values / count-only:
client.query("parcels", return_distinct_values=True, out_fields="zone")
client.query("parcels", where="area > 1000", return_count_only=True)
```

On the `Source` facade these route through `Query.spatial_filter` and the
`Query.aggregation` mapping (`out_statistics` / `group_by` /
`return_distinct_values` / `return_count_only`). Both are GeoServices-only
request shapes; supplying them for a non-FeatureServer source raises
`ValueError` rather than silently dropping the predicate.

## Worked recipes

### Stream all features into geopandas

```python
from honua_sdk import HonuaClient, Query, SourceDescriptor, SourceLocator
from honua_sdk.geopandas import features_to_geodataframe

with HonuaClient("https://example.com") as client:
    parcels = client.source(
        SourceDescriptor(
            id="parcels",
            protocol="geoservices-feature-service",
            locator=SourceLocator(service_id="parcels", layer_id=0),
        )
    )
    result = parcels.query(Query(where="status='active'", page_size=2000))
    gdf = features_to_geodataframe(result.raw_legacy)
    print(gdf.crs, len(gdf))
```

For very large datasets, prefer `stream()` plus a row-wise builder so
you don't materialize every page at once:

```python
features = list(parcels.iter_features(Query(where="1=1", page_size=2000)))
```

### Cap pagination for a preview UI

```python
preview = parcels.query(Query(where="1=1", page_size=50, max_pages=1))
# `preview.exceeded_transfer_limit` tells you whether to render a
# "load more" affordance. `preview.total_count` is the server's count
# (numberMatched / @odata.count / FeatureServer count) when advertised.
```

### Resume from a known offset

The canonical `Query` model also exposes `offset` (mapped per-protocol
in `_extra_params_for_query`: `resultOffset` for FeatureServer, `$skip`
for OData, `offset` otherwise). Use it to resume a paginated drain:

```python
checkpoint = 4_000
result = parcels.query(Query(where="1=1", page_size=1000, offset=checkpoint))
```

OGC Features and STAC servers that advertise `next` links typically
prefer link-following over explicit offsets — the protocol clients
honour the server's `next` link automatically when you call
`source.stream(...)`.

## See also

- [Retries and timeouts](retries-and-timeouts.md) — what happens when a
  pagination round-trip fails partway through.
- [`Query`][honua_sdk.Query] / [`Result`][honua_sdk.Result] — the
  canonical request/response shapes.
- [Protocol examples](protocol-examples.md) — side-by-side recipes for
  each supported protocol.
