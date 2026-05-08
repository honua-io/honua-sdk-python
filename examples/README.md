# Python Analyst Demo Suite

This directory contains runnable examples for Python-first Honua workflows. The demos are script-first so notebooks and services can reuse shared modules instead of carrying duplicate business logic.

## Cloud Environment Contract

All demos that call Honua use the same environment variables:

- `HONUA_BASE_URL`: Honua deployment URL. Defaults to `http://localhost:8080` for local demos.
- `HONUA_API_KEY`: optional API key for deployments that require API-key auth.
- `HONUA_SERVICE_ID`: FeatureServer service id. Defaults to `test_service`.
- `HONUA_LAYER_ID`: FeatureServer layer id. Defaults to `0`.
- `HONUA_COLLECTION_ID`: OGC API Features collection id for protocol demos. Defaults to the service id.
- `HONUA_STAC_COLLECTION_ID`: optional STAC collection id for imagery demos.

The checked-in examples target the seeded `test_service` layer used by local Honua server development. Cloud runs should point the variables at an equivalent writable or readable fixture.

## Demos

| Demo | Target user | Extras | Entry point | Artifacts |
| --- | --- | --- | --- | --- |
| GeoPandas ETL | Analyst loading cleaned point data into Honua | `honua-sdk[geopandas]`, `matplotlib` | `python examples/geospatial_etl/run_etl.py` | `load-summary.json`, `post-load-preview.png` |
| Data quality report | Analyst reviewing source defects before load | `honua-sdk[geopandas]` | `python examples/data_quality_report.py` | `data-quality-report.json`, `data-quality-report.html`, `data-quality-report.png` |
| Spatial query cookbook | Developer or analyst comparing protocol query patterns | core SDK, optional `honua-sdk[geopandas]` for conversions | `python examples/spatial_query_cookbook.py` | printed response-shape summary, including GeoDataFrame conversion when available |
| FastAPI spatial service | App developer exposing async Honua-backed API routes | `fastapi`, `uvicorn` | `uvicorn examples.fastapi_spatial_service:create_app --factory --reload` | local `/features` and `/summary` routes |
| Protocol clients | SDK developer checking protocol wrappers | core SDK, optional `honua-sdk[grpc]` and `honua-sdk[geopandas]` | `python examples/protocol_clients.py` | printed protocol response examples |

## Demo Contracts

- GeoPandas ETL: requires `HONUA_BASE_URL`, optional `HONUA_API_KEY`, and writable `HONUA_SERVICE_ID` / `HONUA_LAYER_ID` values. Expect `load-summary.json` on every run and `post-load-preview.png` after post-load reconciliation. Validate with `pytest tests/test_geospatial_etl_example.py`, then run the script against a fixture layer and confirm the summary's add/update counts.
- Data quality report: reads the local CSV and does not call Honua, but uses the same source contract as the ETL demo. Expect JSON, HTML, and PNG report artifacts in the output directory. Validate with `pytest tests/test_python_analyst_demos.py -k data_quality`.
- Spatial query cookbook: requires `HONUA_BASE_URL`, optional `HONUA_API_KEY`, and readable service, layer, collection, and map ids. Set `HONUA_STAC_COLLECTION_ID` only when a STAC fixture exists. Expect printed response-shape rows for FeatureServer bbox/filter, GeoDataFrame conversion, OGC API Features, WFS, WMS, WMTS, OData, and optional STAC. Validate with `pytest tests/test_python_analyst_demos.py -k spatial_query`.
- FastAPI spatial service: requires `HONUA_BASE_URL`, optional `HONUA_API_KEY`, and readable `HONUA_SERVICE_ID` / `HONUA_LAYER_ID` values. Expect `/healthz`, `/features`, and `/summary` routes backed by `AsyncHonuaClient`. Validate with `pytest tests/test_python_analyst_demos.py -k fastapi`, then start the app locally and query `/summary?limit=5`.
- Imagery and STAC: STAC item search is gated by `HONUA_STAC_COLLECTION_ID`. A runnable imagery scoring pipeline also needs a fixture collection id, stable scene metadata, asset keys, a cloud-cover field, and an expected item count; until those fixtures exist, imagery scoring remains explicitly gated.

## Validation

Run the focused example tests from the repo root:

```bash
pytest tests/test_geospatial_etl_example.py tests/test_python_analyst_demos.py
```

For cloud validation, set the environment variables above and run the scripts manually against a fixture service before attaching artifacts to issue or PR notes.
