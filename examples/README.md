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
| Data quality report | Analyst reviewing source defects before load | `honua-sdk[geopandas]` | `python examples/data_quality_report.py` | `data-quality-report.json`, `data-quality-report.html` |
| Spatial query cookbook | Developer or analyst comparing protocol query patterns | core SDK, optional `honua-sdk[geopandas]` for conversions | `python examples/spatial_query_cookbook.py` | printed response-shape summary |
| Spatial analysis walkthrough | Analyst running buffer / spatial-join / dissolve on queried features | `honua-sdk[geopandas]`, optional `matplotlib` for the map | open `examples/notebooks/spatial_analysis_walkthrough.ipynb` (or run the paired `examples/notebooks/spatial_analysis_walkthrough.py`) | per-district summary table, optional map; runs offline on a bundled fixture |
| FastAPI spatial service | App developer exposing async Honua-backed API routes | `fastapi`, `uvicorn` | `uvicorn examples.fastapi_spatial_service:create_app --factory --reload` | local `/features` and `/summary` routes |
| Async feature service | App developer fronting Honua with a pooled async client | `fastapi`, `uvicorn` | `uvicorn examples.async_feature_service.service:create_app --factory --reload` | local `/services` and `/features` routes |
| Protocol clients | SDK developer checking protocol wrappers | core SDK, optional `honua-sdk[grpc]` and `honua-sdk[geopandas]` | `python examples/protocol_clients.py` | printed protocol response examples |

## Validation

Run the focused example tests from the repo root:

```bash
pytest tests/test_geospatial_etl_example.py tests/test_python_analyst_demos.py tests/test_spatial_analysis_example.py
```

The spatial-analysis walkthrough is notebook-first. Its logic lives in the
importable `examples/spatial_analysis/analysis.py`, and the committed `.ipynb`
is paired with a diff-friendly `py:percent` mirror
(`examples/notebooks/spatial_analysis_walkthrough.py`). `tests/test_spatial_analysis_example.py`
exercises the pure-Python helpers and verifies the notebook ships with cleared
outputs. Notebook outputs are intentionally cleared; install `jupytext` if you
want to keep the `.ipynb`/`.py` pair in sync automatically.

For cloud validation, set the environment variables above and run the scripts manually against a fixture service before attaching artifacts to issue or PR notes.
