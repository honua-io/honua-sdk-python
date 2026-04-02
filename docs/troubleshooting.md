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
- `HONUA_ENABLE_WRITE_SMOKE` defaults to `false` locally; set it to `true` when you want the add/query/update/delete roundtrip enabled in local or release smoke runs, and keep it `true` in the staging CI environment
- `HONUA_SMOKE_UID_PREFIX` defaults to `sdk-python-smoke` and is recorded as a human-readable write-smoke tag in the feature `description`
- `HONUA_SMOKE_RESULTS_PATH` defaults to `staging-smoke-results.json` for the pytest-driven staging lane

The GitHub Actions live smoke lane only requires `HONUA_BASE_URL`. Set it in the repo or the
`staging` environment before enabling the workflow as a required PR check. `HONUA_SERVICE_ID`
and `HONUA_LAYER_ID` stay optional and fall back to `test_service` / `0`; set `HONUA_API_KEY`
as a secret when the target deployment requires auth.

Same-repo pull requests skip the live smoke lane until `HONUA_BASE_URL` is configured so the
branch does not fail purely on missing GitHub Actions setup. `trunk`, scheduled, and manual
runs still fail fast when that required base URL is absent.

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

The release smoke helper writes `release-smoke-results.json` by default and accepts `--results-path` when you need a different artifact path.

## Smoke Result Artifacts

The shared smoke harness writes a machine-readable JSON report with `schema_version: 1`.

- The staging pytest lane writes to `HONUA_SMOKE_RESULTS_PATH` or `staging-smoke-results.json`.
- `scripts/release_smoke.py` writes to `release-smoke-results.json` unless `--results-path` overrides it.
- Top-level fields include `started_at`, `completed_at`, `overall_status`, `target`, `probe_counts`, and `probes`.
- `target` records `base_url`, `service_id`, `layer_id`, `write_smoke_enabled`, and `uid_prefix` (the configured write-smoke description tag).
- Each `probes[]` entry records `name`, `status`, `required`, `started_at`, `completed_at`, `details`, and an optional `error`.
- When present, `error` records `type`, `message`, `context`, and, for `HonuaHttpError`, `status_code` plus `body`.
- `overall_status` becomes `failed` only when a required probe fails. With `HONUA_ENABLE_WRITE_SMOKE=false`, the write roundtrip probe is recorded as `skipped` and does not fail the run.
- `.github/workflows/staging-integration.yml` also uploads `staging-smoke-junit.xml` and writes a short step summary rendered from the JSON report.

## Seeded Staging Contract

The smoke probes assume the same seeded data-plane contract used by the server test seed:

- service id: `test_service`
- layer id: `0`
- minimum read-smoke field subset asserted by `query_seeded_layer`: `objectid`, `name`, `status`, `count`, `ratio`

The read smoke checks `readiness()`, `list_services()`, and `query_features(...)`.
The same seeded layer also exposes `description` and `uid`. The write smoke uses that same service/layer for a minimal add -> query -> update -> query -> delete cycle, records a human-readable tag in `description`, and validates the `uid` UUID field on the smoke-created record instead of assuming seeded rows already populate it.

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

The smoke harness stores a real UUID in `uid`, tags each write-smoke record `description` as `<HONUA_SMOKE_UID_PREFIX>:<uuid>`, and always attempts cleanup in a `finally` block. If a run is interrupted mid-flight, query and delete leftover records by the description prefix.

Example cleanup snippet:

```python
import os

from honua_sdk import HonuaClient

prefix = os.environ.get("HONUA_SMOKE_UID_PREFIX", "sdk-python-smoke")
escaped_prefix = prefix.replace("'", "''")
where = f"description LIKE '{escaped_prefix}:%'"  # simple SQL-style filter

with HonuaClient(os.environ["HONUA_BASE_URL"], api_key=os.environ.get("HONUA_API_KEY")) as client:
    response = client.query_features(
        "test_service",
        0,
        where=where,
        out_fields=["objectid", "uid", "description"],
    )
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
