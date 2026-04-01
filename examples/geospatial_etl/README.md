# Geospatial ETL Demo

This example shows the buyer-facing ETL loop for the Python SDK:

1. Extract a tabular CSV source into a `GeoDataFrame`
2. Normalize it to the target layer CRS
3. Validate required fields, duplicate `uid` values, and missing coordinates
4. Query the current Honua target slice
5. Upsert with `apply_edits`
6. Re-query the same slice and emit demo artifacts

The script is the canonical fast path. The notebook reuses the same workflow module for analyst walkthroughs.

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

## Fast Path

Run the canonical script:

```bash
python examples/geospatial_etl/run_etl.py
```

The demo defaults to:

- base URL: `http://localhost:8080`
- service id: `test_service`
- layer id: `0`
- target filter: `uid LIKE 'demo_etl_%'`

Rerunning the sample is safe for the demo slice because it queries only `demo_etl_%` records before load and turns subsequent runs into updates instead of duplicate adds.

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

## Artifacts

Successful runs write these files to `examples/geospatial_etl/output/`:

- `load-summary.json`
- `post-load-preview.png`

`load-summary.json` captures source counts, rejected-row details, pre/post query counts, add/update counts, and the raw `apply_edits` response. The PNG is a simple analyst-facing map of the demo-owned features after load.

## Notebook Walkthrough

After the script path works, open the companion notebook:

```bash
jupyter notebook examples/geospatial_etl/analyst_notebook.ipynb
```

The notebook imports `examples.geospatial_etl.workflow` so it stays on the same ETL implementation as the CLI.
