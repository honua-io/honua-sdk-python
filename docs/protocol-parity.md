# Protocol Parity

This tracks the Python SDK protocol surface against the JS SDK and Honua Server
protocol adapters.

| Surface | Python SDK | JS SDK parity | Notes |
| --- | --- | --- | --- |
| GeoServices FeatureServer | `client.feature_server(id)`, `query_features`, `apply_edits` | Partial | Read/query/edit and metadata wrappers are available. |
| GeoServices MapServer | `client.map_server(id)`, `export_map` | Partial | Metadata, export, identify, and tile helpers are available. |
| GeoServices ImageServer | `client.image_server(id)` | New in Python | Metadata, exportImage, identify, query, tile, and legend helpers are available. |
| GeoServices GeocodeServer | `HonuaGeocodingClient` | Python-specific | Forward, reverse, and suggest helpers are available. |
| GeoServices GeometryServer | `client.geometry_server()` | New in Python | Discovery plus project, buffer, simplify, and generic operation helpers are available. |
| OGC API Features | `client.ogc_features()` | Matches core JS shape | Landing, conformance, collections, queryables, items, paging, and item CRUD are available. |
| OGC API Maps | `client.ogc_maps()` | New in Python | Landing, conformance, OpenAPI, map, styled map, and map tileset helpers are available. |
| OGC API Tiles | `client.ogc_tiles()` | New in Python | Landing, conformance, collections, tile matrix sets, tilesets, and tile helpers are available. |
| OGC API Coverages | `client.ogc_coverages()` | New in Python | Thin wrapper is present for the advertised endpoint family; server support may vary by deployment. |
| OGC API Processes | `client.ogc_processes()` | New in Python | Included because Honua Server exposes the surface; useful for integration test coverage. |
| STAC | `client.stac()` | New in Python | Catalog, collections, items, item, and search helpers are available. |
| WFS 2.0 | `client.wfs()` | New in Python | Capabilities, describeFeatureType, getFeature, and transaction helpers are available. |
| WMS | `client.wms(service_id)` | New in Python | Service-scoped capabilities, map, and feature-info helpers are available. |
| WMTS | `client.wmts(service_id)` | New in Python | Service-scoped capabilities and tile helpers are available. |
| OData v4 | `client.odata()` | New in Python | Service document, metadata, layers, layer features, and feature helpers are available. |

The Python clients intentionally return protocol-native JSON, XML text, or bytes
instead of introducing heavy local models. That keeps parity focused on endpoint
coverage, auth, retries, timeouts, and normalized errors while preserving standard
payloads for GeoPandas, PySTAC, GDAL/OGR, and analyst workflows.

The staging smoke lane backs this parity table with SDK-owned live probes for the
public protocol clients. The smoke report records the SDK package version, server
commit/image metadata, seed profile, protocol surface, SDK method, request path,
and bounded HTTP error body summaries for each probe. Optional surfaces are
reported as skipped when a deployment does not advertise or enable them.
