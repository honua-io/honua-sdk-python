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
- `honua-arcpy assess` now reads the
  `honua_sdk.migration.scan_arcpy_source(...).to_dict()` shape (entries
  under the top-level `calls` key) in addition to the
  `honua_admin.scan_arcpy_script` shape (`toolCalls` / `tool_calls`).
  Both scanners are documented inputs; previously the SDK shape
  silently produced an empty assessment.
- `da.SearchCursor` / `da.UpdateCursor` now preserve a zero-valued
  `OBJECTID` (or `FID`) when resolving `OID@`. The previous
  `attrs.get('OBJECTID') or ...` falsy chain collapsed `0` to `None`,
  which caused `updateRow` / `deleteRow` to raise
  `HonuaArcpyConfigurationError` against legitimate rows with OID 0.

### Fixes (review pass 4)

- `honua-arcpy assess` now canonicalizes
  `arcpy.management.CopyFeatures` to the supported `management.Copy`
  manifest entry. The shim already exposed
  `management.CopyFeatures = Copy`, but `assess` keyed straight off the
  scanner's qualified name, so SDK / admin inventories of
  `CopyFeatures` calls dropped into the out-of-scope bucket. Existing
  `Copy` scans aggregate with `CopyFeatures` scans into a single row.
- Unsupported shim calls now write an audit JSONL line. `raise_unsupported`
  wraps the rejection in `record_call(...)`, and every stub (analysis,
  management, da) plus the targeted `SelectLayerByAttribute(selection_type=SWITCH_SELECTION)`
  refusal forwards their `args` / `kwargs` so the audit row carries the
  redacted payload, `status="error"`, and `error_kind="unsupported"`.
  Operators can now correlate every shim call -- including refused
  ones -- through the JSONL stream the docs already promised.
- `SearchCursor.__next__` / `UpdateCursor.__next__` call
  `_ensure_open()` before producing a row, so direct
  `next(cursor)` invocations raise
  `HonuaArcpyConfigurationError` before context-enter and after
  context-exit instead of (a) silently yielding rows from a cached
  iterator after `__exit__`, or (b) wrapping the bare `AttributeError`
  on `_source` in an `ExecuteError` that mislabels the failure as a
  backend error.
- `eval/run_eval.py` `_classify` now honours the golden
  `audit_lines` count inside the `expected_failure` branch. Previously
  the branch returned `pass` as long as the script exited cleanly and
  printed the marker, so a regression that lost the refusal-time audit
  line would slip through. The check now matches the regular branch,
  and the new audit-wrapped stubs make every expected-failure golden's
  `audit_lines: 1` actually enforceable.

### Fixes (review pass 5)

- `honua-arcpy matrix --check` now runs the drift comparison *before*
  any `--output` write, so a caller pointing both flags at the same
  path (the `honua-arcpy-eval.yml` CI gate previously did this) cannot
  rewrite the committed file with fresh-rendered text and then compare
  it to itself, masking real drift. The CI workflow now passes only
  `--check` (no `--output`); a regression test
  (`tests/test_cli.py::test_matrix_check_runs_before_output_so_same_path_cannot_mask_drift`)
  pins the new behavior so a future caller that accidentally adds
  `--output` back will still get a non-zero exit on drift.
- `management.SelectLayerByAttribute` now wraps its pre-dispatch
  validation paths (missing layer alias, unknown `selection_type`) in
  `record_call`, so the documented "every shim call writes one JSONL
  line" contract holds for those refusals. The `SWITCH_SELECTION`
  rejection is still detected before the surrounding `record_call` so
  `raise_unsupported`'s variant-scoped audit line stays the single
  audit record for that mode (no double-audit).
- Updated the matrix CLI examples in `docs/honua-arcpy/README.md` to
  use explicit file paths (`--check docs/honua-arcpy/compatibility-matrix.md`,
  `--output docs/honua-arcpy/compatibility-matrix.md`) instead of the
  argument-free `--check` / directory-form `--output` that the parser
  never accepted.

### Fixes (review pass 6)

- `dispatch_process` now rolls back any output aliases it registered
  during input projection when `processes.execute(...)` raises.
  Previously a transport failure left the output alias (e.g.
  `roads_buffer`) in `HonuaSession._layers`, so a retry of the same
  call tripped the duplicate-output guard with
  `HonuaArcpyConfigurationError` and never reached the process client.
  The dispatcher captures each output's prior alias (None if it did
  not exist) during `_project_to_process_inputs` and restores that
  state under the session lock on exception. Tests
  (`test_failed_process_rolls_back_output_alias`,
  `test_failed_process_restores_prior_output_alias_under_overwrite`)
  pin both the absent-prior and overwrite-true-prior cases.
- `management.GetCount` now performs alias lookup, path resolution,
  and the backend call entirely inside the surrounding `record_call`,
  so pre-dispatch failures (`GetCount(None)` ->
  `HonuaArcpyResolveError`; unconfigured session ->
  `HonuaArcpyConfigurationError`) write the documented JSONL audit
  line with the real `error_kind` instead of bypassing the audit. A
  regression test (`test_get_count_resolve_failure_is_audited`) pins
  the contract.
- `.github/workflows/honua-arcpy-eval.yml` `paths:` filters now
  include `docs/honua-arcpy/**`, so a PR that only touches the
  top-level docs copy of the compatibility matrix still triggers the
  matrix drift gate and the byte-equal cross-copy test. Previously
  such a PR bypassed the workflow entirely.
- `packages/honua-arcpy/README.md` layout block drops the stale
  `_client.py` entry (session client construction lives in
  `_session.py`) and the stale `docs/scanner-handoff.md` entry (the
  scanner-handoff page lives in the workspace `docs/honua-arcpy/`
  tree, not the package docs directory). Added a short paragraph
  pointing readers to the correct locations.
