# Changelog

All notable changes to `honua-arcpy` will be documented in this file.

## 0.1.0 (2026-05-22)

Initial drop. Adds the proprietary `honua_arcpy` shim package covering 45
top-of-corpus arcpy functions (15 analysis, 20 management, 10 data-access).
Dispatches through `honua_sdk`, `honua_admin`, and
`honua_sdk.protocols.OgcProcessesClient` -- no direct REST/gRPC plumbing.

- Dispatch core, audit JSONL logger, path resolver, env/session shim.
- Compatibility matrix generated from in-code manifest.
- `honua-arcpy assess` CLI consuming the `honua_admin._arcpy_scanner` output.
- 50-script eval suite + `eval/run_eval.py` harness writing JUnit + JSON.
- End-to-end Buffer / Clip / ApplyEdits example.
- CI lane `honua-arcpy-eval.yml` reusing the staging-integration container
  pattern.
- Legacy suffix aliases (`Buffer_analysis`, `Clip_analysis`,
  `GetCount_management`, ...) so unmodified arcpy scripts continue to
  import.

### Known limitations

- `AddField`, `DeleteField`, `Rename`, `ListFields`, and `Describe` are
  shipped as stubs that raise `HonuaArcpyUnsupportedError`.
  `HonuaAdminClient` does not yet expose per-layer schema mutation or
  reading; the stubs surface the gap with a replacement hint and a
  `honua-server#layer-schema-mutate` / `honua-server#layer-schema-read`
  tracking ticket so the migration scanner picks them up.
- `GetCount` is `partial`: it materializes the full result set because the
  `Source` facade does not expose a count-only helper yet. Use bounded
  `where` clauses for large layers.
- `SourceDescriptor` mappings emitted by `_resolve.descriptor_mapping`
  default to `geoservices-feature-service` and treat unrecognized paths as
  `service_id=<name>, layer_id=0`. Customers with non-default layer IDs
  should configure `HONUA_ARCPY_PATH_MAP`.

### Fixes (review pass 2)

- Cursors (`da.SearchCursor`, `da.UpdateCursor`) now AND-combine the
  alias-resident `where` from `MakeFeatureLayer` / `SelectLayerByAttribute`
  with any cursor-supplied `where_clause`. Previously the alias filter was
  dropped, so a selected layer could iterate, update, or delete rows
  outside the selection.
- `SelectLayerByAttribute` honours `invert_where_clause=True` and rejects
  `selection_type="SWITCH_SELECTION"` (arcpy's OID-set toggle that cannot
  be modelled as a SQL where clause) with `HonuaArcpyUnsupportedError`.
  Unknown selection types now raise `HonuaArcpyConfigurationError`.
- `_layer_count` no longer swallows backend exceptions and silently
  returns `Selection(count=0)`. Source-facade failures from
  `SelectLayerByAttribute` and `GetCount` are wrapped in `ExecuteError`
  (with the original cause attached) and surface in the audit JSONL with
  the real `error_kind`.
- The process dispatcher honours `arcpy.env.overwriteOutput`. With it
  unset (the default), a second process call that targets the same output
  name raises `HonuaArcpyConfigurationError` instead of silently
  re-running over the prior output. Audit projection moved inside
  `record_call` so the overwrite error is recorded.
- `HONUA_ARCPY_PATH_MAP` entries apply inside list-valued source
  parameters (e.g. `analysis.Intersect`, `analysis.Union`,
  `analysis.SpatialJoin` `target_features` / `join_features`).
  Source-valued parameters are now declared via
  `FunctionEntry.source_params` in the manifest.

### Fixes (review pass 3)

- Cursor backend failures (`Source.iter_features`, `Source.apply_edits`)
  now surface as `ExecuteError` with `function`, `error_kind`,
  `compat_anchor`, and `cause` attached. Previously a `RuntimeError`
  raised from `iter_features` leaked past the cursor and the
  `except arcpy.ExecuteError:` idiom missed it.
- Cursor close-time failures (a flush raised during `__exit__` after the
  user block exited cleanly) now route the close-time exception into the
  audit context, so the JSONL record reflects `status="error"` /
  `error_kind="<RealException>"` instead of recording `status="ok"`
  while the caller saw an exception.
- `HONUA_ARCPY_PATH_MAP` no longer rewrites non-source string arguments.
  The dispatcher only resolves parameters declared in
  `FunctionEntry.source_params` / `output_params`. Other strings
  (`dissolve_option`, `expression`, CRS strings, distances, etc.) pass
  through unchanged so a path-map entry that happens to collide with an
  arcpy literal like `"ALL"` cannot silently corrupt the process payload.
- `SelectLayerByAttribute` now commits `alias.where` / `alias.selection`
  only after the backend count succeeds. A failed selection leaves the
  alias in its prior state, so subsequent cursors do not iterate against
  a selection that never reached the server.
- `selection_type="SWITCH_SELECTION"` raises a targeted
  `HonuaArcpyUnsupportedError` whose `function` reads
  `management.SelectLayerByAttribute(selection_type=SWITCH_SELECTION)`
  and whose `replacement_hint` points at `invert_where_clause=True`. The
  prior code claimed the whole `SelectLayerByAttribute` function was
  unimplemented, contradicting the compatibility matrix.
