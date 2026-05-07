# Protocol Parity

This tracks the Python SDK protocol surface against the JS SDK and Honua Server
protocol adapters.

| Surface | Python SDK | JS SDK parity | Notes |
| --- | --- | --- | --- |
| Shared Source/Query/Result | `client.source(...)`, `SourceDescriptor`, `Query`, `Result` | Aligned by fixture | Canonical source-bound facade with Pythonic snake_case names and protocol escape hatch. |
| Shared feature query | `client.query(...)`, `client.iter_query(...)` | Legacy compact helper | Normalized `QueryFeature` output spans FeatureServer, OGC API Features, STAC, and OData. |
| gRPC FeatureService | `honua_sdk.grpc.HonuaGrpcClient`, `HonuaGrpcAsyncClient` | Canonical shared protocol id | Generated FeatureService client with unary and streaming query helpers; `grpc` is included in the shared semantic fixture/default capability registry. |
| GeoServices FeatureServer | `client.feature_server(id)`, `query_features`, `apply_edits` | Partial | Read/query/edit, metadata, typed query pages, and item iterators are available. |
| GeoServices MapServer | `client.map_server(id)`, `export_map` | Partial | Metadata, export, identify, and tile helpers are available. |
| GeoServices ImageServer | `client.image_server(id)` | New in Python | Metadata, exportImage, identify, query, tile, and legend helpers are available. |
| GeoServices GeocodeServer | `client.geocoder()`, `HonuaGeocodingClient` | Python-specific | Forward, reverse, and suggest helpers are available. |
| GeoServices GeometryServer | `client.geometry_server()` | New in Python | Discovery plus project, buffer, simplify, and generic operation helpers are available. |
| OGC API Features | `client.ogc_features()` | Matches core JS shape | Landing, conformance, collections, queryables, item pages, item iterators, collect-all paging, and item CRUD are available. |
| OGC API Maps | `client.ogc_maps()` | New in Python | Landing, conformance, OpenAPI, map, styled map, and map tileset helpers are available. |
| OGC API Tiles | `client.ogc_tiles()` | New in Python | Landing, conformance, collections, tile matrix sets, tilesets, and tile helpers are available. |
| OGC API Coverages | `client.ogc_coverages()` | New in Python | Thin wrapper is present for the advertised endpoint family; server support may vary by deployment. |
| OGC API Processes | `client.ogc_processes()` | New in Python | Included because Honua Server exposes the surface; useful for integration test coverage. |
| STAC | `client.stac()` | New in Python | Catalog, collections, items, item, search, item pages, and search item iterators are available. |
| WFS 2.0 | `client.wfs()` | New in Python | Capabilities, describeFeatureType, getFeature, and transaction helpers are available. |
| WMS | `client.wms(service_id)` | New in Python | Service-scoped capabilities, map, feature-info, and binary metadata helpers are available. |
| WMTS | `client.wmts(service_id)` | New in Python | Service-scoped capabilities, tile, and binary metadata helpers are available. |
| OData v4 | `client.odata()` | New in Python | Service document, metadata, query helpers, layers, layer features, paged iterators, and feature helpers are available. |

The Python SDK offers a source-bound shared query API for application code that
wants one feature shape across queryable data protocols. `SourceDescriptor`,
`Query`, and `Result` follow the cross-SDK fixture while keeping Python naming
conventions such as `out_fields`, `return_geometry`, and `query_all()`. The
lower-level protocol clients intentionally keep protocol-native JSON, XML text,
and bytes as their default return shapes. Additive helpers provide typed
FeatureServer pages, `ODataQuery` parameter grouping, and `BinaryResponse`
metadata for WMS/WMTS payloads without forcing heavy local models. That keeps
parity focused on endpoint coverage, auth, retries, timeouts, and normalized
errors while preserving standard payloads for GeoPandas, PySTAC, GDAL/OGR, and
analyst workflows.

Sync and async HTTP clients expose the same protocol factory names. The
compatibility gate snapshots those factories and fails on unallowlisted drift.

See [Protocol Examples](./protocol-examples.md) for concise examples of each
public protocol wrapper and its response shape.

The staging smoke lane backs this parity table with SDK-owned live probes for the
public protocol clients. The smoke report records the SDK package version, server
commit/image metadata, seed profile, protocol surface, SDK method, request path,
and bounded HTTP error body summaries for each probe. Optional surfaces are
reported as skipped when a deployment does not advertise or enable them.
