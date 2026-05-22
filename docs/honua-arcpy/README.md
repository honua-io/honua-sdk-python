# honua-arcpy docs

`honua-arcpy` is a **proprietary** drop-in compatibility shim that lets
existing `arcpy` scripts run end-to-end against a Honua deployment. It is
distributed from this monorepo with its own `LICENSE` (see
[`packages/honua-arcpy/LICENSE`](../../packages/honua-arcpy/LICENSE)) which
**overrides** the surrounding Apache-2.0 license for that package only.

## Pointers

* [Compatibility matrix](compatibility-matrix.md) -- generated from the
  in-code manifest at `packages/honua-arcpy/honua_arcpy/_compat.py`.
* [Scanner handoff](scanner-handoff.md) -- how a `scan_arcpy_script`
  inventory becomes a per-call TODO list via `honua-arcpy assess`.
* Package README: [`packages/honua-arcpy/README.md`](../../packages/honua-arcpy/README.md).
* Example end-to-end script:
  [`packages/honua-arcpy/examples/buffer_clip_roundtrip.py`](../../packages/honua-arcpy/examples/buffer_clip_roundtrip.py).

## Quickstart

```python
import honua_arcpy as arcpy

arcpy.configure(base_url="https://honua.example.com", api_key="...")
arcpy.env.workspace = "honua://services/transport"
arcpy.env.overwriteOutput = True

arcpy.analysis.Buffer("roads", "roads_buffer", "25 Meters", dissolve_option="ALL")
arcpy.analysis.Clip("roads_buffer", "study_area", "roads_clip")
arcpy.management.Project("roads_clip", "roads_wgs84", 4326)
```

`honua_arcpy` resolves the `arcpy.env` workspace, output coordinate system,
overwrite policy, parallel processing factor, and scratch workspace onto a
module-global `HonuaSession`. Unknown env attributes are accepted and stashed
in `session.extra_client_options` so legacy scripts keep working without
silent attribute errors.

## Configuration

The session is bootstrapped in one of two ways:

* Programmatic: `honua_arcpy.configure(base_url=..., api_key=...)` or
  `honua_arcpy.configure(base_url=..., bearer_token=...)`. Pre-built
  `client=`, `admin_client=`, or `processes_client=` instances may also be
  injected for testing.
* Environment: `HONUA_BASE_URL`, `HONUA_API_KEY`, and `HONUA_BEARER_TOKEN`
  are picked up by `honua_arcpy.configure_from_env()`.

Path resolution: customers can declare an explicit alias map via
`HONUA_ARCPY_PATH_MAP='{"local_name": "honua://services/foo/bar"}'` for
unrecognized GDB / SDE / file paths. `MakeFeatureLayer` and `MakeTableView`
also register in-process aliases that subsequent calls can reference.

## Audit JSONL

Every shim call writes one JSONL line to
`${HONUA_ARCPY_AUDIT_DIR:-./.honua-arcpy/audit}/audit-YYYYMMDD.jsonl` in UTC,
rotated per day. The record shape is:

```jsonc
{
  "timestamp": "2026-05-22T17:42:11Z",
  "function": "analysis.Buffer",
  "args": ["...", "..."],         // redacted positional args
  "kwargs": {"distance": "..."},   // redacted kwargs
  "result_shape": {"type": "object", "keys": ["..."]},
  "latency_ms": 12.4,
  "status": "ok",                  // or "error"
  "error_kind": "..."              // present only when status == "error"
}
```

Redaction reuses the same heuristics as `honua_admin._arcpy_scanner` so paths,
URLs, and secret-shaped strings are stripped before the record lands on disk.
The operator owns retention and shipping; the writer is append-only with one
open handle per UTC day.

## Error model

* `honua_arcpy.ExecuteError` mirrors `arcpy.ExecuteError`; existing
  `except arcpy.ExecuteError:` clauses keep catching shim failures.
* `honua_arcpy.HonuaArcpyUnsupportedError` subclasses `ExecuteError` and is
  raised by stubbed functions. The message embeds the compatibility-matrix
  anchor URL and a recommended honua-sdk replacement call.
* `honua_arcpy.HonuaArcpyConfigurationError` is raised when the session is
  used before `configure(...)` / `HONUA_BASE_URL` is set.
* `honua_arcpy.HonuaArcpyResolveError` is raised when an arcpy path cannot be
  mapped to a Honua source descriptor.

## CLI

```bash
honua-arcpy assess path/to/inventory.json       # scanner-handoff pivot
honua-arcpy matrix --check                      # CI doc-gate: fails on drift
honua-arcpy matrix --output docs/honua-arcpy/   # regenerate matrix files
```

`assess` consumes the `ArcPyScriptInventoryArtifact` JSON emitted by
`honua_admin.scan_arcpy_script` and writes `honua-arcpy-assessment.json`
alongside the bucketed stdout summary. See
[scanner-handoff.md](scanner-handoff.md) for the migration-tool integration.

## Distribution

The package is intended for a private PyPI index (founder decision pending --
recommended target is GitHub Packages scoped to the `honua-io` org). The
public CI lane (`ci.yml`) does **not** publish this package; publishing is
gated behind a manual workflow once the index is configured. The
`packages/honua-arcpy/pyproject.toml` carries the `Private :: Do Not Upload`
classifier so an accidental `twine upload` to pypi.org fails.

When the founder decides to extract the package into a private repo (the
design's R1 recommendation), the contents of `packages/honua-arcpy/` move
verbatim. The in-code manifest, audit logger, dispatcher, CLI, eval suite,
and tests are designed to be standalone within that directory.
