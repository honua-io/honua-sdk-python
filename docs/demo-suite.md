# Python Analyst Demo Suite

The Python SDK demo suite is designed around workflows where Python is the best fit: GeoPandas ETL, data quality reporting, spatial query exploration, and async API services.

## Environment

Use the shared demo contract from [../examples/README.md](../examples/README.md):

- `HONUA_BASE_URL`
- `HONUA_API_KEY`
- `HONUA_SERVICE_ID`
- `HONUA_LAYER_ID`
- `HONUA_COLLECTION_ID`
- `HONUA_STAC_COLLECTION_ID`

Cloud demos should use fixture services with stable schemas and stable record counts. Demos that write data must filter their own slice, such as the ETL demo's `uid LIKE 'demo-etl-%'` target filter.

## Current Coverage

- GeoPandas ETL: clean, validate, query, upsert, re-query, and write deterministic artifacts.
- Data quality report: validate the same source contract and emit JSON and HTML findings before load.
- Spatial query cookbook: exercise FeatureServer bbox/filter queries, OGC API Features, STAC item search, WFS, WMS, WMTS, and OData response shapes.
- FastAPI service: expose async `/features` and `/summary` routes backed by `AsyncHonuaClient`.

## Optional STAC And Imagery

STAC calls are included in the cookbook when `HONUA_STAC_COLLECTION_ID` points at a fixture collection. Imagery scoring is intentionally gated until the server fixture includes stable scene metadata and imagery assets. A runnable imagery pipeline should state the required collection id, asset keys, cloud cover field, and expected item count before adding scoring logic.
