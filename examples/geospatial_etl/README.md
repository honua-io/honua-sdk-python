# Geospatial ETL Demo

This example shows the analyst-facing ETL loop for the Python SDK:

1. Extract a tabular CSV source into a `GeoDataFrame`
2. Normalize it to the target layer CRS
3. Validate required fields, duplicate `uid` values, and missing coordinates
4. Query the current Honua target slice
5. Upsert with `apply_edits`
6. Re-query the same slice and emit demo artifacts

The script is the canonical fast path. The notebook reuses the same workflow module for analyst walkthroughs.
See [../README.md](../README.md) for the shared demo-suite cloud environment contract, and [../../docs/troubleshooting.md](../../docs/troubleshooting.md) for staging base URL, auth, seeded contract, and cleanup guidance.

## Prerequisites

- A local checkout of this repo
- Python 3.11+
- A running Honua server at `http://localhost:8080`

Use the existing `honua-server` Docker Compose quick start and seeded `test_service` docs instead of re-creating that setup here:

- `honua-server` quick start: <https://github.com/honua-io/honua-server/blob/trunk/README.md#quick-start>
- Seeded `test_service` + layer `0`: <https://github.com/honua-io/honua-server/blob/trunk/docs/contributor/mcp-certification.md#how-the-seed-is-applied-in-ci>

## Install

From the repo root:

```bash
pip install -e "packages/honua-sdk[geopandas]" matplotlib jupyter
```

The core staging smoke lane does not install these extras. It exercises the
same SDK data-plane calls with only `honua-sdk` and `pytest`.

## Fast Path

Run the canonical script:

```bash
python examples/geospatial_etl/run_etl.py
```

The demo defaults to:

- base URL: `HONUA_BASE_URL` when set, otherwise `http://localhost:8080`
- service id: `test_service`
- layer id: `0`
- target filter: `uid LIKE 'demo-etl-%'`

Rerunning the sample is safe for the demo slice because it queries only `demo-etl-%` records before load and turns subsequent runs into updates instead of duplicate adds.

On the checked-in CSV, the first run validates `6` rows, rejects `3`, and plans `6` adds / `0` updates when the target demo slice starts empty.

### Optional flags

```bash
python examples/geospatial_etl/run_etl.py \
  --base-url http://localhost:8080 \
  --service-id test_service \
  --layer-id 0 \
  --input examples/geospatial_etl/data/demo_sites.csv \
  --output-dir examples/geospatial_etl/output
```

For non-anonymous environments, pass `--api-key ...` or set `HONUA_API_KEY`.
The CLI also defaults `--base-url` from `HONUA_BASE_URL` before falling back to `http://localhost:8080`.

## What The Script Demonstrates

- `pandas.read_csv(...)` loads the tabular source
- `GeoDataFrame(...)` builds source geometry from `x_3857` / `y_3857`
- `to_crs(...)` reprojects from `EPSG:3857` to the target layer CRS
- `HonuaClient.query_features(...)` reads the target slice before and after load
- `features_to_geodataframe(...)` converts the Honua query response into a `GeoDataFrame`
- `geodataframe_to_features(...)` builds the `apply_edits` payload
- Validation rejects:
  - duplicate `uid` rows
  - blank required fields
  - rows with missing coordinates / null geometry

The checked-in CSV intentionally includes a duplicate `uid`, a blank `name`, and a row with missing coordinates so the validation report is visible on the first run.

## Source And Target Contract

### Source CSV contract

The workflow expects these source columns:

- `uid`
- `name`
- `status`
- `count`
- `x_3857`
- `y_3857`

Behavior is intentionally narrow and deterministic:

- `uid`, `name`, and `status` are trimmed before validation
- `status` is normalized to lowercase
- `count` is coerced to a nullable integer
- source geometry is built from `x_3857` / `y_3857` in `EPSG:3857`
- the transformed `GeoDataFrame` is reprojected to the target layer CRS returned by the pre-load query, falling back to `EPSG:4326` when the target query does not expose a CRS

Rows are rejected when they:

- are missing `uid`, `name`, or `status`
- reuse a `uid` that already appeared earlier in the same batch
- are missing either coordinate
- produce a null or invalid geometry

### Target layer contract

The demo queries and reconciles only the `uid LIKE 'demo-etl-%'` slice. The target layer is expected to expose:

- a `uid` attribute used as the upsert key
- an `objectid` or `OBJECTID` field on existing features so matched rows can be sent as updates

The load payload stays scoped to the target schema used by the demo seed:

- adds send `uid`, `name`, `status`, `count`, and geometry
- updates send the same fields plus the matched `objectid`
- deletes are intentionally out of scope for this example

Empty edit groups are omitted from the `apply_edits` request. A pure-add run sends
`adds` only, and a pure-update run sends `updates` only.

## Runtime Contract

The happy path makes three network calls:

1. `query_features(...)` before load to discover the target slice and CRS
2. `apply_edits(...)` with `rollback_on_failure=True`
3. `query_features(...)` after load to reconcile the written slice

Exit behavior is also fixed:

- exit code `0` only when `apply_edits` reports at least one successful add/update/delete result
- exit code `1` when every source row is rejected before load
- exit code `1` on source/setup failures before the first network call
- exit code `1` when the pre-load query, `apply_edits`, or post-load query raises `HonuaHttpError`
- exit code `1` when `apply_edits` returns but none of its result entries are successful

## Data Quality Report

Run the companion report before loading when you only need source diagnostics:

```bash
python examples/data_quality_report.py
```

It uses the same GeoPandas conversion and validation functions as the ETL workflow, then writes:

- `data-quality-report.json`
- `data-quality-report.html`
- `data-quality-report.png`

The report covers duplicate `uid` values, missing required attributes, missing coordinates / null geometries, invalid geometries, and schema drift against the source CSV contract.

## Artifacts And Response Shape

Every run writes `examples/geospatial_etl/output/load-summary.json`.

- `load-summary.json`
- `post-load-preview.png` only when the workflow reaches post-load reconciliation

`load-summary.json` has `schema_version: 1` and always includes:

- `started_at` / `completed_at`
- `target`
  with `base_url`, `service_id`, `layer_id`, `where`, and `target_crs`
- `source`
  with `input_path`, `source_row_count`, `valid_row_count`, `rejected_row_count`, and `rejected_rows`
- `pre_load`
  with the matching feature count before load
- `plan`
  with add/update counts
- `artifacts`
  with the JSON path and either a PNG path or `null`
- `apply_edits`
  with a normalized status summary including `status`, `successful_edits`, and `response`

`source.rejected_rows[]` records the source line number, normalized `uid`, rejection reasons, and the original non-geometry source fields for that row.

`apply_edits.status` is one of:

- `success`
- `skipped`
- `http_error`

`apply_edits` always carries `status`, `successful_edits`, and `response`. On `success`, `response` is the raw `apply_edits` payload. This status means the HTTP request completed; it does not guarantee that any add/update/delete result entry succeeded. Use `successful_edits` or the CLI exit code to tell whether the run actually applied edits. On `skipped`, the summary records a `reason` and does not call `apply_edits`; validation-only skips use `reason: "all_rows_rejected"`. On `http_error`, the summary also records `stage`, `status_code`, `message`, and `body`.

When a pre-load or post-load `query_features(...)` call fails with `HonuaHttpError`, the workflow still writes `load-summary.json` and adds `workflow_error`. That object reuses the same error envelope shape as `apply_edits.http_error`: `stage`, `status`, `status_code`, `message`, `body`, `successful_edits`, and `response`. `stage` is `pre_load_query` or `post_load_query`, and the summary preserves the already-computed source, plan, and `apply_edits` details that were available before the failure.

Input/setup failures before the first network call also still write `load-summary.json`. In that case `workflow_error.stage` is `source_setup`, `workflow_error.status` is `input_error`, `workflow_error.error_type` records the Python exception class, `apply_edits.status` is `skipped`, and `source.source_row_count` is populated when the CSV was readable before the failure.

`post_load` is initialized once the workflow reaches post-load reconciliation after a non-error `apply_edits` response. When the re-query succeeds it records the reconciled `matching_feature_count` and `target_crs`. When that re-query fails, `post_load.matching_feature_count` stays `null`, `workflow_error.stage` is `post_load_query`, and `artifacts.post_load_preview` remains `null`. `post-load-preview.png` is the analyst-facing map for the reconciled slice whenever the post-load query succeeds, even when `successful_edits` is `0`.

## Notebook Walkthrough

After the script path works, open the companion notebook:

```bash
jupyter notebook examples/geospatial_etl/analyst_notebook.ipynb
```

The notebook imports `examples.geospatial_etl.workflow` and calls the same shared `run_workflow(...)` entrypoint, so the notebook stays on the exact same ETL implementation and artifact contract as the CLI.
CI validates that shared workflow module and the staging smoke harness rather than maintaining a second notebook-only execution path.
