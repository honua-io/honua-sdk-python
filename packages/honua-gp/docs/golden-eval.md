# honua-gp golden eval

The golden eval suite (`eval/run_eval.py`, `eval/scripts/*.py`,
`eval/golden/*.json`) is the correctness-verification story for the `honua_gp`
drop-in shim. `honua_gp` delegates every geoprocessing operation to a Honua
server instead of reimplementing geometry/raster logic locally, so "is the
shim correct?" reduces to two questions the harness answers directly:

1. **Does the shim project each `arcpy` call onto the right Honua request?**
   (dispatch / parameter translation)
2. **Does the shim parse the real server's response back correctly?**
   (response handling / round-trip)

## What is (and is not) verified

The harness grades each script across three independent layers, weakest to
strongest:

| Layer | Checks | Graded in |
| --- | --- | --- |
| **Plumbing** | exit code, audit JSONL line count, required `stdout` marker | every mode |
| **Request fingerprint** | projected `process_id` + typed `inputs` the shim POSTs (from the `process_inputs` audit field) diffed against golden `request` | every mode |
| **Response fingerprint** | geometry type / feature count / row count the shim parsed back from a REAL server, diffed against golden `response` | live mode only |

* **Stub mode** (`HONUA_GP_EVAL_USE_STUB=1`, the default) grades plumbing +
  request. The request fingerprint is transport-independent -- the projection
  runs identically against the stub and a live server -- so a
  parameter-mapping / dispatch regression (an `arcpy` argument mapped to the
  wrong process input) is caught here even though the stub never validates the
  payload it receives. Stub mode does **not** exercise a real server, so it
  cannot verify response round-trip.

* **Live mode** (`HONUA_GP_EVAL_USE_STUB=0` + `HONUA_BASE_URL`) additionally
  grades the response fingerprint against a real, seeded honua-server. This is
  the genuine correctness upgrade over the stub: it proves the shim's
  dispatch -> real HTTP -> response-parse loop round-trips correctly, which a
  canned-response stub can never check.

* **ArcGIS Pro parity is NOT verified anywhere.** No licensed arcpy runtime
  exists in this environment, so the golden values are not diffed against a
  real ArcGIS Pro baseline. The response oracles are pinned to what
  honua-server computes for the client-compat seed, not to what ArcGIS Pro
  would return. arcpy-level output equivalence remains license-gated and is
  tracked separately.

## Golden schema (v2)

```json
{
  "schema_version": 2,
  "expected_failure": false,
  "plumbing": { "audit_lines": 1, "stdout_contains": "buffer_roads ok" },
  "request": [
    {
      "function": "analysis.Buffer",
      "process_id": "analytics.buffer-aggregate",
      "inputs": { "layerId": 0, "distance": 25.0, "unit": "meters", "dissolve": true }
    }
  ],
  "response": { "output_keys": ["outputFeatureLayer"], "geometry_type": "Polygon", "feature_count": 1 }
}
```

* `request` is a list (one entry per process-backed call, in call order) so
  multi-op scripts fingerprint every step.
* `request` is absent for source/session-backed scripts (`GetCount`, cursors)
  that make no process dispatch; `response` is absent for `expected_failure`
  scripts and side-effecting scripts with no meaningful return.

## Re-capturing (blessing) the oracles

Golden values are captured-then-frozen. After an intentional change, re-bless
and review the diff before committing:

```bash
# Request fingerprints (stub is sufficient -- projection is transport-independent)
python eval/run_eval.py --update-golden

# Response fingerprints (requires a live, seeded honua-server)
HONUA_GP_EVAL_USE_STUB=0 HONUA_BASE_URL=http://localhost:5000 HONUA_API_KEY=... \
  python eval/run_eval.py --update-golden
```

Request fingerprints are written in any mode; response fingerprints only in
live mode (the stub's canned `href` carries no real values and must never be
frozen as an oracle).

## Determinism note (live mode)

The response oracles for count/row scripts record exact values pinned to the
client-compat seed. Several eval scripts mutate the seeded layer
(`da.InsertCursor` / `da.UpdateCursor` -> FeatureServer `applyEdits`), and
those edits persist, so **each live run must start from a fresh seed** for the
counts to reproduce. The CI `ephemeral-server-smoke` job stands up a fresh
Docker compose (fresh Postgres) per run, so counts are deterministic there.
Running live mode twice against the same persistent database will drift the
count/row oracles -- reset the seed (or re-bless) between runs.

## Standing up a live target locally

The live lane reuses honua-server's `docker/client-compat/compose.yml` seed
(`test_service` / layer 0) plus the in-repo second layer
(`eval/seed/spatial-join-second-layer.sql`, needed because
`analytics.spatial-join` rejects a self-join). Point the eval at it with:

```bash
export HONUA_GP_EVAL_USE_STUB=0
export HONUA_BASE_URL=http://localhost:5000
export HONUA_API_KEY=...
# Redirect the legacy demo names baked into the generator to the seeded layer:
export HONUA_GP_PATH_MAP='{"roads":"honua://services/test_service/0","segments_attrs":"honua://services/test_service/0"}'
python eval/run_eval.py --require-supported-pass-rate 1.0
```

The server must have Redis-backed durable job storage available (the OGC
Processes job store honua-server's async GP operations run on); the
client-compat compose wires Redis for exactly this.
