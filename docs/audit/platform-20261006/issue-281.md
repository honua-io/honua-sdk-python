# Issue 281 — cursor and pagination correctness

| Finding id | Outcome | Evidence |
|---|---|---|
| SDKPY-001 | fixed | `test_sdkpy_001_update_cursor_snapshots_rows_before_flushing` demonstrates that every matching row is captured from the original predicate before a batch update can change the offset-paged result set. The synchronous and asynchronous update cursors now take a geometry-free object-id snapshot first, then fetch full rows lazily one `batch_size` chunk of `objectIds` at a time (`test_update_cursor_fetches_rows_lazily_per_batch`, `test_async_update_cursor_fetches_rows_lazily_per_batch`), so memory stays bounded. |
| SDKPY-002 | fixed | `test_sdkpy_002_items_pages_preserves_reverse_proxy_base_path` covers a relative continuation from a reverse-proxy sub-path. OGC Features continuation hrefs are now resolved against the current page URL and passed as absolute same-origin request URLs. |
| SDKPY-004 | fixed | `test_sdkpy_004_search_cursor_serializes_geometry_filter` asserts JSON geometry, inferred `geometryType`, and `spatialRel`. Both cursor variants now use the canonical `spatial_filter` query path. |
| SDKPY-005 | fixed | `test_sdkpy_005_odata_stops_after_final_continuation_page` proves that a full final continuation page is not followed by a stale-offset request. OData, STAC item/search, and OGC Records sync/async walkers now stop when a continuation sequence ends. |
| SDKPY-006 | fixed | `test_sdkpy_006_insert_cursor_raises_for_row_failure` proves that an HTTP-success response containing a failed row raises `HonuaError`. Every insert/update cursor flush now records and validates `ApplyEditsResult.all_succeeded`, including async cursors. |
