# Python SDK Troubleshooting

## Base URL Selection

Use the Honua server root URL as `base_url`:

- `https://staging.example.honua.io`
- `http://localhost:8080`

Do not pass a full service path such as `/rest/services/test_service/FeatureServer/0`.
The SDK builds those paths for you.

## Auth And Environment Variables

Set these environment variables for the staging smoke lane and release smoke runner:

- `HONUA_BASE_URL` required
- `HONUA_SERVICE_ID` defaults to `test_service`
- `HONUA_LAYER_ID` defaults to `0`
- `HONUA_API_KEY` optional, for staging environments that do not allow anonymous access
- `HONUA_ENABLE_WRITE_SMOKE` defaults to `false` locally and should be `true` in the staging CI environment
- `HONUA_SMOKE_UID_PREFIX` defaults to `sdk-python-smoke`

The opted-in staging suite and `scripts/release_smoke.py` both fail fast when `HONUA_BASE_URL` is unset so CI cannot silently pass without exercising a real deployment.

Run the opt-in staging suite locally with:

```bash
python -m pytest tests/integration \
  -q \
  --run-integration \
  -m "integration and staging and smoke"
```

Run the release smoke helper against an already-installed SDK artifact with:

```bash
python scripts/release_smoke.py
```

## Seeded Staging Contract

The smoke probes assume the same seeded data-plane contract used by the server test seed:

- service id: `test_service`
- layer id: `0`
- expected query field surface: `objectid`, `name`, `status`, `count`, `uid`

The read smoke checks `readiness()`, `list_services()`, and `query_features(...)`.
The write smoke uses the same service/layer for a minimal add -> query -> update -> query -> delete cycle.

If staging no longer exposes that contract, treat it as a bounded `honua-server` follow-on instead of changing the SDK smoke target inside this repo.

## Optional Example Dependencies

The core SDK smoke lane stays dependency-light:

- `honua-sdk`
- `pytest`

The canonical ETL example and notebook need additional local tools:

```bash
pip install -e "packages/honua-sdk[geopandas]" matplotlib jupyter
```

The notebook is a companion walkthrough, not a second implementation. CI and smoke coverage validate the shared `examples/geospatial_etl/workflow.py` path instead of executing notebook cells separately.

## Cleaning Up Staging Smoke Data

The smoke harness writes records under `HONUA_SMOKE_UID_PREFIX` and always attempts cleanup in a `finally` block. If a run is interrupted mid-flight, query and delete the leftover records with the same prefix.

Example cleanup snippet:

```python
import os

from honua_sdk import HonuaClient

prefix = os.environ.get("HONUA_SMOKE_UID_PREFIX", "sdk-python-smoke")
where = f"uid LIKE '{prefix.replace(\"'\", \"''\")}%'"  # simple SQL-style filter

with HonuaClient(os.environ["HONUA_BASE_URL"], api_key=os.environ.get("HONUA_API_KEY")) as client:
    response = client.query_features("test_service", 0, where=where, out_fields=["objectid", "uid"])
    objectids = [
        feature["attributes"]["objectid"]
        for feature in response.get("features", [])
        if feature.get("attributes", {}).get("objectid") is not None
    ]
    if objectids:
        client.apply_edits("test_service", 0, deletes=objectids)
```

## Failure Interpretation

- `HonuaHttpError` with a non-zero `status_code` means the request reached Honua and the server rejected it. Inspect `message` and `body` first.
- `HonuaHttpError` with `status_code == 0` means the failure happened before an HTTP response was received. Typical causes are DNS, TLS, timeout, or connectivity failures.
- A missing service, missing seeded fields, or an empty seeded layer usually means the staging contract drifted from the server seed expected by this repo.
