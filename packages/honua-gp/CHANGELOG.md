# Changelog

All notable changes to `honua-gp` will be documented in this file.

## Unreleased

- **Renamed** the distribution and import namespace from `honua-arcpy` /
  `honua_arcpy` to `honua-gp` / `honua_gp` to remove an Esri trademark from a
  package and import-namespace name (honua-io/honua-sdk-python#123). "ArcPy"
  and "ArcGIS" now appear only as descriptive references to the migration
  target. Branded public symbols and env vars were renamed accordingly
  (`HonuaArcpy*Error` -> `HonuaGp*Error`, `HONUA_ARCPY_*` -> `HONUA_GP_*`),
  and the console entry point is now `honua-gp`. A deprecated `honua-arcpy`
  shim package re-exports `honua_gp` and emits a `DeprecationWarning` so the
  legacy `import honua_arcpy` keeps working.

## 0.1.0 (2026-05-22)

Initial drop. Adds the proprietary `honua_gp` shim package covering 45
top-of-corpus arcpy functions (15 analysis, 20 management, 10 data-access).
Dispatches through `honua_sdk`, `honua_admin`, and
`honua_sdk.protocols.OgcProcessesClient` -- no direct REST/gRPC plumbing.

- Dispatch core, audit JSONL logger, path resolver, env/session shim.
- Compatibility matrix generated from in-code manifest.
- `honua-gp assess` CLI consuming the `honua_admin._arcpy_scanner` output.
- 50-script eval suite + `eval/run_eval.py` harness writing JUnit + JSON.
- End-to-end Buffer / Clip / ApplyEdits example.
- CI lane `honua-gp-eval.yml` reusing the staging-integration container
  pattern.
- Legacy suffix aliases (`Buffer_analysis`, `Clip_analysis`,
  `GetCount_management`, ...) so unmodified arcpy scripts continue to
  import.

### Known limitations

- `AddField`, `DeleteField`, `Rename`, `ListFields`, and `Describe` are
  shipped as stubs that raise `HonuaGpUnsupportedError`.
  `HonuaAdminClient` does not yet expose per-layer schema mutation or
  reading; the stubs surface the gap with a replacement hint and a
  `honua-server#layer-schema-mutate` / `honua-server#layer-schema-read`
  tracking ticket so the migration scanner picks them up.
- `GetCount`, `SelectLayerByAttribute`, and `SearchCursor` are `partial`:
  they run on Honua with documented deviations, and `honua-gp assess`
  reports them separately from APIs that run unchanged.
- `SourceDescriptor` mappings emitted by `_resolve.descriptor_mapping`
  default to `geoservices-feature-service` and treat unrecognized paths as
  `service_id=<name>, layer_id=0`. Customers with non-default layer IDs
  should configure `HONUA_GP_PATH_MAP`.

### Fixes (review pass 2)

- Cursors (`da.SearchCursor`, `da.UpdateCursor`) now AND-combine the
  alias-resident `where` from `MakeFeatureLayer` / `SelectLayerByAttribute`
  with any cursor-supplied `where_clause`. Previously the alias filter was
  dropped, so a selected layer could iterate, update, or delete rows
  outside the selection.
- `SelectLayerByAttribute` honours `invert_where_clause=True` and rejects
  `selection_type="SWITCH_SELECTION"` (arcpy's OID-set toggle that cannot
  be modelled as a SQL where clause) with `HonuaGpUnsupportedError`.
  Unknown selection types now raise `HonuaGpConfigurationError`.
- `_layer_count` no longer swallows backend exceptions and silently
  returns `Selection(count=0)`. Source-facade failures from
  `SelectLayerByAttribute` and `GetCount` are wrapped in `ExecuteError`
  (with the original cause attached) and surface in the audit JSONL with
  the real `error_kind`.
- The process dispatcher honours `arcpy.env.overwriteOutput`. With it
  unset (the default), a second process call that targets the same output
  name raises `HonuaGpConfigurationError` instead of silently
  re-running over the prior output. Audit projection moved inside
  `record_call` so the overwrite error is recorded.
- `HONUA_GP_PATH_MAP` entries apply inside list-valued source
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
- `HONUA_GP_PATH_MAP` no longer rewrites non-source string arguments.
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
  `HonuaGpUnsupportedError` whose `function` reads
  `management.SelectLayerByAttribute(selection_type=SWITCH_SELECTION)`
  and whose `replacement_hint` points at `invert_where_clause=True`. The
  prior code claimed the whole `SelectLayerByAttribute` function was
  unimplemented, contradicting the compatibility matrix.
- `honua-gp assess` now reads the
  `honua_sdk.migration.scan_arcpy_source(...).to_dict()` shape (entries
  under the top-level `calls` key) in addition to the
  `honua_admin.scan_arcpy_script` shape (`toolCalls` / `tool_calls`).
  Both scanners are documented inputs; previously the SDK shape
  silently produced an empty assessment.
- `da.SearchCursor` / `da.UpdateCursor` now preserve a zero-valued
  `OBJECTID` (or `FID`) when resolving `OID@`. The previous
  `attrs.get('OBJECTID') or ...` falsy chain collapsed `0` to `None`,
  which caused `updateRow` / `deleteRow` to raise
  `HonuaGpConfigurationError` against legitimate rows with OID 0.

### Fixes (review pass 4)

- `honua-gp assess` now canonicalizes
  `arcpy.management.CopyFeatures` to the canonical `management.Copy`
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
  `HonuaGpConfigurationError` before context-enter and after
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

- `honua-gp matrix --check` now runs the drift comparison *before*
  any `--output` write, so a caller pointing both flags at the same
  path (the `honua-gp-eval.yml` CI gate previously did this) cannot
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
- Updated the matrix CLI examples in `docs/honua-gp/README.md` to
  use explicit file paths (`--check docs/honua-gp/compatibility-matrix.md`,
  `--output docs/honua-gp/compatibility-matrix.md`) instead of the
  argument-free `--check` / directory-form `--output` that the parser
  never accepted.

### Fixes (review pass 6)

- `dispatch_process` now rolls back any output aliases it registered
  during input projection when `processes.execute(...)` raises.
  Previously a transport failure left the output alias (e.g.
  `roads_buffer`) in `HonuaSession._layers`, so a retry of the same
  call tripped the duplicate-output guard with
  `HonuaGpConfigurationError` and never reached the process client.
  The dispatcher captures each output's prior alias (None if it did
  not exist) during `_project_to_process_inputs` and restores that
  state under the session lock on exception. Tests
  (`test_failed_process_rolls_back_output_alias`,
  `test_failed_process_restores_prior_output_alias_under_overwrite`)
  pin both the absent-prior and overwrite-true-prior cases.
- `management.GetCount` now performs alias lookup, path resolution,
  and the backend call entirely inside the surrounding `record_call`,
  so pre-dispatch failures (`GetCount(None)` ->
  `HonuaGpResolveError`; unconfigured session ->
  `HonuaGpConfigurationError`) write the documented JSONL audit
  line with the real `error_kind` instead of bypassing the audit. A
  regression test (`test_get_count_resolve_failure_is_audited`) pins
  the contract.
- `.github/workflows/honua-gp-eval.yml` `paths:` filters now
  include `docs/honua-gp/**`, so a PR that only touches the
  top-level docs copy of the compatibility matrix still triggers the
  matrix drift gate and the byte-equal cross-copy test. Previously
  such a PR bypassed the workflow entirely.
- `packages/honua-gp/README.md` layout block drops the stale
  `_client.py` entry (session client construction lives in
  `_session.py`) and the stale `docs/scanner-handoff.md` entry (the
  scanner-handoff page lives in the workspace `docs/honua-gp/`
  tree, not the package docs directory). Added a short paragraph
  pointing readers to the correct locations.

### Fixes (review pass 8)

- **Honest manifest -- process-backed entries downgraded to stubs.**
  Audit pass 8 compared the shim's emitted payloads against
  honua-server's ``BuiltInProcessCatalog`` and found a contract
  mismatch: the manifest mapped ``in_features``/``out_feature_class``
  to ``input_features``/``result``, but honua-server's
  ``geometry.buffer``/``geometry.clip``/``geometry.intersect``/
  ``geometry.union``/``geometry.difference``/``geometry.dissolve``
  expect raw base64-WKB (``wkb`` / ``targetWkb`` / ``wkbs``) plus
  ``srid``, and ``analytics.spatial-join``/
  ``data-management.copy-features``/``data-management.delete-features``/
  ``data-management.calculate-field``/``conversion.feature-project``
  expect ``layerId``-shaped references. Eleven entries
  (``analysis.Buffer``, ``analysis.Clip``, ``analysis.Intersect``,
  ``analysis.Union``, ``analysis.Erase``, ``analysis.SpatialJoin``,
  ``management.CalculateField``, ``management.Dissolve``,
  ``management.Copy``, ``management.Delete``, ``management.Project``)
  are now ``backend="not_implemented", status="stub"`` and raise
  ``HonuaGpUnsupportedError`` with a per-function
  ``honua-server#...`` tracking ticket pointing at the projection
  adapter that needs to land before they can be re-promoted. The
  prior arcpy-style payloads would have been rejected by live OGC
  Processes validation despite passing the in-tree stub eval; the
  downgrade makes the migration tool surface the real coverage and
  unblocks future adapter work.
- **Contract test pinned the invariant.** New
  ``tests/test_compat_manifest.py::test_process_backed_entries_match_honua_server_catalog``
  walks every ``backend="process"`` entry and asserts that the
  ``param_map`` values are a subset of the matching honua-server
  process inputs. The snapshot is a hand-maintained dictionary in
  the test file (kept in lock-step with
  ``Honua.Server.Features.Geoprocessing.BuiltInProcessCatalog``). The
  invariant currently holds vacuously (no entries are
  ``backend="process"``); the moment a future change promotes one
  back to ``process``, the test enforces that the payload matches
  the server contract.
- **Coverage shifted to source/session surface.** The MVP surface is now
  4 supported entries plus 3 partial entries. 38 entries are
  stubs that the migration tool surfaces with a replacement hint and
  tracking ticket. ``docs/honua-gp/compatibility-matrix.md`` and
  ``packages/honua-gp/docs/compatibility-matrix.md`` were
  regenerated to reflect the downgrade; ``eval/_generate_scripts.py``
  moved every previously process-backed script into the
  ``expected_failure_*`` block so the 50-script eval suite remains
  at 50 and the harness validates every refusal via the audit JSONL
  contract. Local eval pass rate: **50/50 (100%)** against the stub
  transport, with all 39 expected-failure scripts producing the
  documented refusal audit line.
- **Unknown ``arcpy.env.*`` attributes no longer crash client
  construction.** Writes such as ``arcpy.env.extent``,
  ``arcpy.env.MTolerance``, or ``arcpy.env.geographicTransformations``
  previously landed in ``HonuaSession.extra_client_options``, which
  ``_build_client`` forwarded into ``honua_sdk.HonuaClient(**kwargs)``.
  ``HonuaClient`` has a closed keyword signature, so the next backend
  call raised ``TypeError: HonuaClient.__init__() got an unexpected
  keyword argument 'extent'`` before the first request. The env
  proxy now stashes unknown attrs in a separate
  ``HonuaSession.extra_env_options`` bag that is **not** forwarded to
  the SDK constructor; ``configure(..., **client_kwargs)`` remains
  the only path that populates ``extra_client_options``. Regression
  tests live in ``tests/test_env.py`` (``test_env_unknown_attribute_falls_into_extra_env_options``,
  ``test_env_unknown_attribute_does_not_break_client_construction``).

### Fixes (review pass 7)

- `HonuaSession.configure(...)` now invalidates the cached
  `_client` / `_admin` / `_processes` references whenever
  connection-relevant fields (`base_url`, `api_key`, `bearer_token`,
  or extra `**client_kwargs`) change. Previously a script that called
  `configure(base_url="a", api_key="k1")`, dispatched once, then
  called `configure(base_url="b", api_key="k2")` would keep using the
  client built against the first URL/auth, silently sending traffic
  to the wrong deployment until `reset()` was invoked. Explicit
  `client=` / `admin_client=` / `processes_client=` arguments are
  still applied *after* the invalidation, so they continue to win in
  the same call. Idempotent reconfigures (re-passing the same values)
  do not invalidate the cache. Regression tests live in the new
  `tests/test_session.py`.
- `eval/run_eval.py::_run_script` now unconditionally rebuilds the
  subprocess `PYTHONPATH` from `_build_pythonpath(...)` instead of
  using `env.setdefault`. The prior `setdefault` left a host-provided
  `PYTHONPATH` untouched, so eval scripts on CI / shell hosts where
  `PYTHONPATH` was already set could fail to import `honua_gp` /
  `honua_sdk` / `honua_admin` unless those packages happened to be
  pre-installed. `_build_pythonpath` already preserves existing
  entries and de-duplicates against the appended extras, so behavior
  on hosts without `PYTHONPATH` is unchanged. Two regression tests
  (`test_run_script_always_rebuilds_pythonpath_when_host_sets_it`,
  `test_run_script_builds_pythonpath_when_host_has_none`) cover both
  cases in `tests/test_eval_harness.py`.

### Fixes (review pass 9)

- **Live smoke gating no longer hides supported-surface regressions.**
  `eval/run_eval.py` gained `--require-supported-pass-rate <N>`, an
  independent gate that tracks the pass rate of non-`expected_failure`
  scripts and exits non-zero if it falls below the supplied threshold.
  `.github/workflows/honua-gp-eval.yml` passes `1.0` in the live
  smoke step, so a regression on any of the 11 supported scripts now
  fails the run even though the 39 expected-failure scripts alone
  would keep the headline `--pass-threshold 0.70` satisfied (the
  previous setup produced a ~78% pass rate even when every supported
  script failed). The new flag defaults to `0.0` so the stub-mode CI
  lane is unchanged. Tests: `tests/test_eval_harness.py::
  {test_main_fails_when_supported_pass_rate_below_required,
  test_main_passes_when_supported_pass_rate_meets_required}`.
- **Live smoke redirects legacy script names to seeded data.** The
  supported eval scripts reference `roads` / `segments_attrs` (legacy
  demo names baked into the generator). The seeded client-compat
  compose target exposes `test_service` / layer 0 instead, so the
  live smoke step now sets `HONUA_GP_PATH_MAP` to redirect both
  names to `honua://services/test_service/0` via the shim's existing
  alias map. Operators may override the redirect via the
  `HONUA_GP_PATH_MAP` repo variable when their `HONUA_BASE_URL`
  deployment exposes `transport` natively.
- **Ephemeral smoke health probe waits on the right endpoint.** The
  local-stack readiness loop now polls `/healthz/ready` (the
  endpoint the compose healthcheck uses) instead of the unregistered
  `/health`, and exits non-zero with a `::error::` annotation plus a
  tail of the honua-server logs when the loop exhausts its 60-attempt
  / 120-second budget. The prior loop fell through silently on
  exhaustion and ran the smoke against an unproven-ready server.
- **Stub replacement hints no longer recommend stubbed siblings.**
  Four stubs whose `replacement_hint` pointed at sibling shims that
  were themselves stubbed after pass 8 (`analysis.MultipleRingBuffer`
  -> `analysis.Buffer`; `analysis.SymmetricalDifference` -> "Compose
  Union minus Intersect; both processes are supported";
  `analysis.Identity` -> `analysis.Intersect`;
  `management.SelectLayerByLocation` -> `analysis.Buffer +
  analysis.Intersect`) were rewritten to either acknowledge the
  shared projection-adapter blocker explicitly or point at the
  underlying `honua_sdk.protocols.OgcProcessesClient.execute(...)`
  call directly. Both compatibility-matrix copies were regenerated;
  the package-local and workspace copies remain byte-equal. A new
  contract test
  (`tests/test_compat_manifest.py::test_stub_hints_do_not_recommend_stubbed_sibling_shims`)
  pins the invariant by asserting no stub's `replacement_hint`
  contains `honua_gp.<family>.<func>` for any `<func>` that is
  itself a stub.
- **`honua-gp assess` docs no longer claim `CopyFeatures` reports
  as supported.** `docs/honua-gp/README.md` and
  `docs/honua-gp/scanner-handoff.md` previously said that
  canonicalized `CopyFeatures` calls land in the `supported` bucket
  via `management.Copy`. Audit pass 8 downgraded `management.Copy`
  to a stub; the docs now explain that canonicalization preserves
  the aggregation invariant but the row's status follows the
  manifest, so `CopyFeatures` calls report under **Stubs** (tracking
  `honua-server#arcpy-copy-features-adapter`) until the projection
  adapter lands.

### Fixes (review pass 10)

- **`InsertCursor.reset()` no longer silently drops buffered inserts.**
  `BaseCursor.reset()` calls `_reset()`, and `InsertCursor._reset`
  cleared `_inserts` / `_inserted`. Because `_close` only flushes
  when the buffer is non-empty, an `insertRow(...); reset(); <context
  exit>` sequence committed nothing to the backend, raised nothing,
  and emitted an `audit JSONL line with `status="ok"`. Real
  `arcpy.da.InsertCursor` does not expose `reset()`. The shim now
  overrides `InsertCursor.reset` to call `_ensure_open()` (so a
  pre-context use surfaces the standard configuration error first)
  then raises `HonuaGpConfigurationError` with a message
  pointing callers at `flush()` or `__exit__`. The audit JSONL
  carries the refusal with `status="error"` and
  `error_kind="configuration"`. Regression tests:
  `tests/test_da_cursors.py::{test_insert_cursor_reset_refuses_to_drop_buffered_inserts,
  test_insert_cursor_reset_does_not_clear_buffer_before_raising,
  test_insert_cursor_reset_outside_context_raises_configuration_error}`.
- **Cursor row-length mismatches surface as `ExecuteError`.**
  `_payload_for_row` used `zip(row, fields, strict=True)`, so a
  short or long row argument to `UpdateCursor.updateRow` /
  `InsertCursor.insertRow` raised a bare `ValueError` that the
  documented `except arcpy.ExecuteError:` idiom did not catch.
  `_payload_for_row` now compares `len(row)` against `len(fields)`
  before the zip and raises `HonuaGpConfigurationError` (an
  `ExecuteError` subclass) with the expected / got counts in the
  message. The audit JSONL records the failure with the real
  `error_kind`. Same regression-test family in
  `tests/test_da_cursors.py::{test_update_cursor_update_row_length_mismatch_raises_configuration_error,
  test_update_cursor_update_row_short_row_raises_configuration_error,
  test_insert_cursor_insert_row_length_mismatch_raises_configuration_error,
  test_row_length_mismatch_caught_by_execute_error}`.
- **`HonuaGpUnsupportedError.compat_anchor` URLs resolve.**
  `_compat.COMPAT_REPO_DOC` was `"docs/compatibility-matrix.md"`, a
  path that does not exist in this repo (the committed copies are
  `docs/honua-gp/compatibility-matrix.md` and
  `packages/honua-gp/docs/compatibility-matrix.md`). Every
  unsupported-error message embedded the bad path, so a user who
  pasted the URL into the repo browser got a 404. The constant
  now points at `docs/honua-gp/compatibility-matrix.md` (the
  public-facing copy) and carries a comment explaining why the
  byte-equal package-local copy was not chosen. Regression test:
  `tests/test_compat_manifest.py::test_compat_repo_doc_points_at_a_committed_matrix_copy`
  asserts the path resolves from the repo root and that
  `anchor_for(...)` builds URLs against the same path.
- **Admin client honours `configure(..., **client_kwargs)`.**
  `HonuaSession._build_admin_client` started with an empty `kwargs`
  dict, so options the docs promised would forward into the admin
  client (`timeout`, `transport`, `auth_provider`,
  `follow_redirects`, `max_retries`) were silently dropped --
  `_build_client` already mirrored them into the data client. The
  admin builder now starts from `dict(self.extra_client_options)`
  and layers the session-level credentials via `setdefault`, so a
  test-only `transport=` or a tuned `timeout=` reaches both
  clients. Regression test:
  `tests/test_session.py::test_configure_forwards_extra_client_options_to_admin_client`.
