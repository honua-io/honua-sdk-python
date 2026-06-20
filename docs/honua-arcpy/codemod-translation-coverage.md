# ArcPy migration codemod: translation coverage

This documents the **offline codemod** in `honua_sdk.migration` (the
`honua-migrate` CLI) -- distinct from the runtime `honua-arcpy` shim and its
[compatibility matrix](compatibility-matrix.md). The codemod statically reads
ArcPy inventory from four input shapes and classifies every geoprocessing call
against a registry of Honua [OGC API - Processes](https://ogcapi.ogc.org/processes/)
targets, emitting a parity-evidence report. It never imports `arcpy` or runs
licensed Esri software.

## Inputs

| Input | Reader | CLI | Output |
| --- | --- | --- | --- |
| `.py` ArcPy script | `scan_arcpy_source` / `translate_arcpy_source` | `honua-migrate scan` / `translate` | `ArcPyScanReport` / `ArcPyMigrationPlan` |
| `.pyt` Python toolbox | `parse_pyt_file` | `honua-migrate pyt` | `PytToolbox` (per-tool `execute` body classified) |
| `.atbx` ModelBuilder toolbox | `parse_atbx_toolbox` | `honua-migrate atbx` | `ModelBuilderToolbox` (models + script-tool names) |
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
  clear redirect. Export `.tbx` to `.atbx` or `.pyt` first.
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

* Binary `.tbx` parsing (proprietary, not clean-room readable).
* Resolving an `.atbx` script tool's referenced `.py` body automatically
  (today its name is surfaced; point the `.py` scanner at it).
* Compiled .NET / ArcObjects custom tools (separate track).
