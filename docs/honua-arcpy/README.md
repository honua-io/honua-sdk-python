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

Calling `configure(...)` again with a different `base_url`, `api_key`,
`bearer_token`, or extra client kwarg invalidates the cached Honua /
Admin / OGC Processes clients so the next backend call rebuilds against
the new settings. Explicit `client=` / `admin_client=` /
`processes_client=` arguments passed in the same call still win.
Idempotent reconfigures (re-passing the same values) leave the cache
untouched.

Path resolution: customers can declare an explicit alias map via
`HONUA_ARCPY_PATH_MAP='{"local_name": "honua://services/foo/bar"}'` for
unrecognized GDB / SDE / file paths. `MakeFeatureLayer` and `MakeTableView`
also register in-process aliases that subsequent calls can reference.

Source-valued parameters are declared in the compatibility manifest via
`FunctionEntry.source_params`. The dispatcher applies path-map resolution to
each string element of those parameters -- including list-valued inputs such
as `analysis.Intersect(in_features=[...])` and `analysis.Union(in_features=[...])`
-- so a `HONUA_ARCPY_PATH_MAP` entry for `"roads"` rewrites `"roads"` whether
it appears as `in_features="roads"` or as one element of `["roads", "parcels"]`.
Non-source string parameters (e.g. `dissolve_option="ALL"`, an arcpy
`expression` text, a CRS literal) pass through untouched, so a path-map entry
that collides with such a literal cannot silently corrupt the process
payload.

Output protection: process backends register every output path as an alias.
With `arcpy.env.overwriteOutput = False` (the default), a second call that
targets the same output name raises `HonuaArcpyConfigurationError`. Set
`overwriteOutput = True` to let subsequent calls replace prior outputs.
If `processes.execute(...)` itself raises (e.g. a transport error from the
OGC Processes client), the dispatcher rolls back any output aliases it
registered during input projection, so a retry of the same call is not
blocked by the duplicate-output guard.

Cursor filters: `MakeFeatureLayer(where_clause=...)` and
`SelectLayerByAttribute(...)` write the effective filter onto the layer
alias. `da.SearchCursor` and `da.UpdateCursor` AND-combine that filter with
any `where_clause` supplied directly to the cursor, so cursor iteration
never reads, updates, or deletes rows outside the selection. The
`invert_where_clause=True` flag on `SelectLayerByAttribute` is applied to
the supplied where clause before composition. `selection_type="SWITCH_SELECTION"`
is reported as unsupported via a targeted
`HonuaArcpyUnsupportedError` (whose `function` reads
`management.SelectLayerByAttribute(selection_type=SWITCH_SELECTION)`); use
`invert_where_clause=True` with an explicit predicate instead.

Cursor row contract: include `"OID@"` in the cursor's `field_names` to
project the row's object id. The cursor resolves `OID@` against the
feature attributes in the order `OBJECTID`, `oid`, `FID`, using explicit
key-presence checks so a valid zero-valued OID (e.g. shapefile `FID = 0`)
is preserved instead of being collapsed to `None`. `UpdateCursor.updateRow`
and `UpdateCursor.deleteRow` require an OID-bearing row and raise
`HonuaArcpyConfigurationError` when none is present.

Selection rollback: `SelectLayerByAttribute` only writes the new
`alias.where` / `alias.selection` after the backend count succeeds. If
the source query raises, the alias is left in its prior state so
subsequent cursors do not iterate against a selection that never reached
the server.

Source descriptor projection: `HonuaClient.source(...)` requires a
`SourceDescriptor` or mapping. The shim builds one from each arcpy path via
`honua_arcpy._resolve.descriptor_mapping`. The default heuristic is
`protocol="geoservices-feature-service"`, with `serviceId`/`layerId`
parsed from `honua://services/<service>/<layer>` URIs when possible and
falling back to `service_id=<input name>, layer_id=0`. Customers with
non-default layer IDs or non-FeatureServer protocols should declare them
through `HONUA_ARCPY_PATH_MAP` so the descriptor matches their deployment.

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

Unsupported / refused shim calls write the same JSONL record so the stream
captures *every* attempt rather than only the calls that reached the backend.
Stubs (e.g. `analysis.Near`, `management.AddField`) and the targeted
`SelectLayerByAttribute(selection_type=SWITCH_SELECTION)` refusal record with
`status="error"` and `error_kind="unsupported"`; the redacted `args` /
`kwargs` round-trip the caller's payload so the migration tool can pivot on
what was attempted, not just the function name.

## Coverage summary

The 0.1.0 manifest covers 45 arcpy entry points. 18 are mapped end-to-end
(`Supported` or `Partial`); 27 are stubbed and raise
`HonuaArcpyUnsupportedError` with a replacement hint and tracking ticket.

Notable status changes versus the initial design draft:

* `management.AddField`, `management.DeleteField`, `management.Rename`,
  `management.ListFields`, and `management.Describe` are **stubs**.
  `HonuaAdminClient` exposes `apply_manifest` and `discover_tables` today,
  but neither covers per-layer schema mutation or per-layer field reads;
  the stubs surface that gap so the migration scanner can flag the calls.
* `management.GetCount` is **partial**. It now goes through
  `HonuaClient.source(...)` with a `SourceDescriptor` mapping built from
  the resolved path, returns `Result.total_count` when the server provides
  it, and otherwise falls back to `len(result.features)`. Use bounded
  `where` clauses on large layers until a count-only helper lands.

## Error model

* `honua_arcpy.ExecuteError` mirrors `arcpy.ExecuteError`; existing
  `except arcpy.ExecuteError:` clauses keep catching shim failures.
  Cursor backend failures (`Source.iter_features` /
  `Source.apply_edits` raising during iteration or flush) are wrapped in
  `ExecuteError` with `function`, `error_kind`, `compat_anchor`, and
  `cause` attached, so the cursor surface matches the process- and
  source-dispatcher surface.
* Cursor close-time failures (a flush that raises during `__exit__`
  after the user block exited cleanly) route the close-time exception
  into the audit record, so the JSONL line correctly reports
  `status="error"` with the real `error_kind`.
* `honua_arcpy.HonuaArcpyUnsupportedError` subclasses `ExecuteError` and is
  raised by stubbed functions. The message embeds the compatibility-matrix
  anchor URL and a recommended honua-sdk replacement call.
* `honua_arcpy.HonuaArcpyConfigurationError` is raised when the session is
  used before `configure(...)` / `HONUA_BASE_URL` is set. Cursor open
  failures route the same configuration error into the JSONL audit's
  `error_kind`, so a missing config does not show up as `GeneratorExit`.
  Direct `next(cursor)` calls outside the cursor's `with` block (before
  `__enter__` or after `__exit__`) raise the same configuration error
  rather than silently yielding from a cached iterator or surfacing the
  missing `_source` `AttributeError` as a backend `ExecuteError`.
* `honua_arcpy.HonuaArcpyResolveError` is raised when an arcpy path cannot be
  mapped to a Honua source descriptor.

## CLI

```bash
honua-arcpy assess path/to/inventory.json                                            # scanner-handoff pivot
honua-arcpy matrix --check docs/honua-arcpy/compatibility-matrix.md                  # CI doc-gate: fails on drift
honua-arcpy matrix --output docs/honua-arcpy/compatibility-matrix.md                 # regenerate the matrix file
```

The CI workflow passes only `--check` (no `--output`) so the gate cannot
overwrite the committed file before comparing against it. Run the
`--output` form locally after manifest edits, then commit the regenerated
file (run once for each copy --
`docs/honua-arcpy/compatibility-matrix.md` and
`packages/honua-arcpy/docs/compatibility-matrix.md`).

`assess` consumes both documented scanner shapes -- the
`ArcPyScriptInventoryArtifact` JSON emitted by
`honua_admin.scan_arcpy_script` (entries under `toolCalls` / legacy
`tool_calls`) and the `ArcPyScanReport` emitted by
`honua_sdk.migration.scan_arcpy_source(...).to_dict()` /
`scan_arcpy_file(...)` (entries under `calls`). Honest synonyms that resolve
through a single shim entry (today: `arcpy.management.CopyFeatures` maps to
the supported `management.Copy` row -- the shim itself exports
`management.CopyFeatures = Copy`) are canonicalized before the manifest
lookup, so `CopyFeatures` scans report as `supported` instead of dropping
into the out-of-scope bucket and aggregate with any `Copy` scans into a
single row. It writes `honua-arcpy-assessment.json` alongside the bucketed
stdout summary. See
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
