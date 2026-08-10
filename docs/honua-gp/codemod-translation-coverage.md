# ArcPy migration codemod: translation coverage

This documents the **offline codemod** in `honua_sdk.migration` (the
`honua-migrate` CLI) -- distinct from the runtime `honua-gp` shim and its
[compatibility matrix](compatibility-matrix.md). The codemod statically reads
ArcPy inventory from four input shapes and classifies every geoprocessing call
against a registry of Honua [OGC API - Processes](https://ogcapi.ogc.org/processes/)
targets, emitting a parity-evidence report. It never imports `arcpy` or runs
licensed Esri software.

## Inputs

| Input | Reader | CLI | Output |
| --- | --- | --- | --- |
| `.py` ArcPy script | `scan_arcpy_source` / `translate_arcpy_source` | `honua-migrate scan` / `translate` | `ArcPyScanReport` / `ArcPyMigrationPlan` |
| `.pyt` Python toolbox | `parse_pyt_file` | `honua-migrate pyt` / `translate` | `PytToolbox` (per-tool `execute` body classified) |
| `.atbx` ModelBuilder toolbox | `parse_atbx_toolbox` | `honua-migrate atbx` / `translate` | `ModelBuilderToolbox` (models + script-tool names) |
| ArcGIS REST GPServer task defs | `parse_gp_service_definition` / `parse_gp_task_definition` | `honua-migrate gpservice` | `GpService` / `GpTask` |

All four share the same registry-driven classification, so a `Buffer` maps to
`geometry.buffer` whether it is a `.py` call, a `.pyt` tool body, a ModelBuilder
step, or a GPServer task.

### Format / compliance notes

* **`.atbx`** is the published, open ArcGIS Pro zip-of-JSON toolbox container.
  `parse_atbx_toolbox` reads it **clean-room**: it unzips the archive and
  JSON-decodes the per-tool definitions (`*.tool/*.content` / `.rc` / `.json`).
  Models (a process/step list) are translated; script tools (which reference an
  external `.py`) are surfaced by name for the caller to scan via the `.py`
  path. The proprietary binary **`.tbx`** format is **not** parsed (it is not
  clean-room readable) -- `parse_binary_toolbox`/`parse_atbx_toolbox` raise a
  clear redirect carrying the concrete ArcGIS Pro export steps
  (`BINARY_TOOLBOX_EXPORT_GUIDANCE`). This is a standing policy decision, not an
  unimplemented stub: Honua never reverse-engineers a proprietary Esri
  container, and the migration path is always export-to-open-format -- the same
  rule that governs `.loc`/`.lox` locator files. Export `.tbx` to `.atbx` or
  `.pyt` first.
* **GP-service** definitions are public ArcGIS REST API JSON
  (`.../GPServer?f=json` and per-task `.../GPServer/<task>?f=json`).

## Classification statuses

Each call resolves to one of:

* **translatable** -- mapped to a Honua process the reconciled server can
  *job-execute* today (`EXECUTABLE_PROCESS_IDS`). Emits a runnable OGC payload.
* **manual-review** -- mapped to a known Honua process whose target is not yet
  job-executable, or whose ArcGIS semantics differ enough to need a human (with
  a reason). Emits an OGC payload + a reason; never claims a runnable migration.
* **unsupported** -- no Honua mapping registered; flagged with a reason.

Coverage percentage in the parity-evidence report is gated on
*job-executability*, not on how many tools the codemod can parse -- so growing
the registry never inflates the runnable-coverage number.

## Server-attested verdicts

The statuses above are the SDK's **own** view of the Honua process catalog, and
that view can drift from the server that would actually run the job. For a
toolbox, `honua-migrate` can have the server settle it instead:

```bash
honua-migrate translate roads.pyt --server https://honua.example --api-key "$HONUA_ADMIN_API_KEY"
honua-migrate pyt   roads.pyt  --server https://honua.example --attestation attest.json
honua-migrate atbx  models.atbx --server https://honua.example --require-attested
```

Each command builds a translation manifest and posts it to
`POST /api/v1/admin/import/toolbox/translation/validate` (honua-server#2145),
which validates every proposed mapping against the canonical process catalog and
returns a per-tool `translated` / `partially-translated` / `unsupported`
classification with the specific reasons a tool cannot be fully translated.

The emitted report carries an `attestation` block whose `verdictSource` is
either `server-attested` or `local-only`:

* **The server wins.** Where the server contradicts the SDK, its verdict is the
  effective one; the local verdict is kept beside it and the disagreement is
  listed under `disagreements`. A disagreement means the SDK's registry has
  drifted from the catalog.
* **A local verdict is never labelled attested.** Running without `--server`, an
  unreachable server, refused credentials, or a malformed response all produce a
  complete `local-only` report with an explicit `fallbackReason`. There is no
  partial attestation -- one failed batch un-attests the whole toolbox. Pass
  `--require-attested` to make a local-only verdict a non-zero exit instead.
* **A response only counts as attestation if it is unambiguously one.** The
  report must carry the expected `artifactKind` and a readable `artifactVersion`
  (never defaulted in client-side), and every tool's `classification` must be one
  of the three declared values. A 200 that misses either bar -- an error
  envelope, a proxy page, a newer server's vocabulary -- degrades to
  `local-only`, because an accepted-but-unrecognized classification would show as
  a tool's effective verdict while no summary counter tallied it.
* **Every discovered toolbox tool is submitted**, including the ones the reader
  could only learn the *name* of:
  * `.atbx` script tools -- their logic lives in an external `.py` the reader
    does not follow (`script_tool_names`);
  * `.atbx` models whose definition yielded no recognizable step
    (`unresolved_tool_names`);
  * `.pyt` tools listed in `self.tools` whose class is imported rather than
    defined in the file (`declared_tool_names` minus the materialised tools).

  Those go in with no proposed target -- nothing was read, so nothing is claimed
  -- and come back `unsupported`. An attestation can therefore never cover a
  strict subset of the toolbox while claiming to cover all of it. Scan the
  referenced script/module with the arcpy `.py` path to classify them properly.

Attestation is toolbox-scoped, because the endpoint's manifest declares a
toolbox `sourceFormat` (`pyt` / `atbx` / `tbx`). `translate` on a bare arcpy
`.py` script therefore refuses `--server` rather than inventing a format.

Auth reuses the existing admin credential path (`--api-key`, or
`$HONUA_ADMIN_API_KEY`), since the endpoint is in the admin import group.
Attestation needs the `honua-admin` package installed; without it, the toolbox
still translates and the report is simply marked `local-only`.

Library entry points: `honua_sdk.migration.build_pyt_translation_manifest` /
`build_atbx_translation_manifest` build the manifest, and
`attest_translation(manifest, validator=...)` merges a server verdict over it.
The validator is injected, so the merge logic itself stays offline and pure.

## Registered tools

Job-executable (`translatable`) targets, gated by `EXECUTABLE_PROCESS_IDS`:

| ArcPy tool | Honua process | Job process |
| --- | --- | --- |
| `analysis.Buffer`, `analysis.GraphicBuffer`, `analysis.PairwiseBuffer` | `buffer` | `geometry.buffer` |
| `analysis.Clip`, `analysis.PairwiseClip` | `clip` | `geometry.clip` |
| `analysis.Intersect`, `analysis.PairwiseIntersect` | `intersect` | `geometry.intersect` |
| `analysis.Union` | `union` | `geometry.union` |
| `analysis.SpatialJoin` (one-to-one form) | `spatial-join` | `analytics.spatial-join-managed` |
| `management.Dissolve`, `analysis.PairwiseDissolve` | `dissolve` | `geometry.dissolve` |
| `management.Project` | `project` | `geometry.project` |
| `management.RepairGeometry` | `make-valid` | `geometry.make-valid` |
| `cartography.SimplifyPolygon`, `cartography.SimplifyLine` | `simplify` | `geometry.simplify` |

Supported but `manual-review` (mapped, not yet job-executable / semantics
differ -- emit payload + reason):

`analysis.Erase`, `analysis.PairwiseErase`, `analysis.SymDiff`,
`analysis.Update`, `analysis.Near`, `management.CopyFeatures`,
`management.MakeFeatureLayer`, `management.SelectLayerByAttribute`,
`management.SelectLayerByLocation`, `management.Merge`, `management.Append`,
`management.MinimumBoundingGeometry`, `management.FeatureToPoint`,
`management.MultipartToSinglepart`, `management.FeatureToLine`,
`management.FeatureToPolygon`, `management.PolygonToLine`,
`cartography.SmoothPolygon`, `cartography.SmoothLine`, `editing.Densify`.

Anything else classifies as `unsupported` with a reimplement/federate reason.
The registry (`_SUPPORTED_TOOL_SPECS` in `honua_sdk/migration/arcpy.py`) is the
single source of truth; this table is a human-readable projection of it.

## Deferred

* Binary `.tbx` parsing -- **will not be implemented** (proprietary container;
  export-to-open-format is the migration path).
* Resolving an `.atbx` script tool's referenced `.py` body automatically
  (today its name is surfaced; point the `.py` scanner at it).
* Compiled .NET / ArcObjects custom tools (separate track).
