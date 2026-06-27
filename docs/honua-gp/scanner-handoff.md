# honua-gp scanner handoff

This doc shows how an ArcPy script inventory produced by the migration scanner
(see `honua_admin.scan_arcpy_script` / `honua_sdk.migration.scan_arcpy_file`)
flows into the `honua-gp` shim, and how a customer running the shim can
get a per-call translation TODO list against the compatibility matrix.

## Inputs

`assess` accepts both documented scanner shapes:

* `honua_admin.scan_arcpy_script(...)` (and the `honua-gp-scan` console
  command) emit an `ArcPyScriptInventoryArtifact` with the per-call list
  under `toolCalls` (legacy `tool_calls` is also accepted). Each entry
  should include either a fully-qualified `call` such as
  `arcpy.analysis.Buffer`, or a `(toolbox, tool)` pair.
* `honua_sdk.migration.scan_arcpy_source(...).to_dict()` (or
  `scan_arcpy_file(...)`) emits an `ArcPyScanReport` with the per-call
  list under `calls`. Each entry carries `qualifiedName`, `family`, and
  `tool` keys, which `assess` matches against the compatibility manifest.

Entries without classifiable names are skipped. Honest synonyms are
canonicalized before the manifest lookup so the same operation reports
under a single row regardless of which name the scanner emitted. Today the
only entry is `arcpy.management.CopyFeatures` -> `management.Copy` (the
shim exports `management.CopyFeatures = Copy`); a scan that mixes
`Copy` and `CopyFeatures` calls aggregates into one `management.Copy`
row instead of one stub-bucket row and one `out-of-scope` row. The row's
status follows the manifest entry: after audit pass 8, `management.Copy`
is a stub (tracking `honua-server#arcpy-copy-features-adapter`), so the
canonicalized `CopyFeatures` calls report under **Stubs**, not under
**Supported**, until the projection adapter lands.

Example inventory excerpts:

```jsonc
// honua_admin.scan_arcpy_script shape
{
  "toolCalls": [
    { "call": "arcpy.management.MakeFeatureLayer", "tool": "MakeFeatureLayer", "toolbox": "management" },
    { "call": "arcpy.management.GetCount", "tool": "GetCount", "toolbox": "management" },
    { "call": "arcpy.analysis.Buffer", "tool": "Buffer", "toolbox": "analysis" },
    { "call": "arcpy.sa.Slope", "tool": "Slope", "toolbox": "sa" }
  ]
}
```

```jsonc
// honua_sdk.migration.scan_arcpy_source(...).to_dict() shape
{
  "calls": [
    { "qualifiedName": "arcpy.management.MakeFeatureLayer", "family": "management", "tool": "MakeFeatureLayer" },
    { "qualifiedName": "arcpy.analysis.Buffer", "family": "analysis", "tool": "Buffer" }
  ]
}
```

## CLI

```bash
honua-gp assess path/to/inventory.json
```

The CLI:

1. Pivots `toolCalls` against the compatibility manifest (`honua_gp._compat.COMPAT`).
2. Prints a per-call bucketed list to stdout:
   * **Supported** -- function runs unchanged on Honua.
   * **Partial** -- function runs on Honua with documented deviations.
   * **Stub** -- function will raise `HonuaGpUnsupportedError` with a
     replacement hint and a honua-server tracking ticket.
   * **Out-of-scope** -- sa / na / ddd / mp toolboxes outside the MVP.
3. Writes a machine-readable `honua-gp-assessment.json` next to the
   inventory (override with `--output-dir`).

Example output:

```
honua-gp assessment
======================

Supported: 1  Partial: 1  Stubs: 1  Out-of-scope: 1

Supported (run unchanged)
-------------------------
  [  1x] management.MakeFeatureLayer  --  Creates an in-process layer alias; deviation: alias is bound to a Honua source descriptor.

Partial (runs with documented deviations)
-----------------------------------------
  [  1x] management.GetCount  --  Returns a row count via Source.query; currently materializes the full result set because Source has no count-only helper yet.

Stubs (will raise -- replacement hint shown)
--------------------------------------------
  [  1x] analysis.Buffer  --  honua-server's geometry.buffer takes a single base64-WKB geometry plus srid+distance, not a feature class. The arcpy feature-class semantic requires a per-feature WKB serialization adapter that does not yet exist.
       hint: Iterate features client-side via honua_sdk.Source.iter_features(...), buffer each geometry through the geoprocessing client, and write the result back via Source.apply_edits.
       tracking: honua-server#feature-class-geometry-ops

Out of MVP scope
----------------
  [  1x] sa.Slope  --  Not in honua-gp MVP scope (sa/na/ddd/mp).
       hint: Open a backlog ticket; see docs/honua-gp/scanner-handoff.md.
```

Audit pass 8 downgraded the 11 process-backed analysis/management
entries (`Buffer`, `Clip`, `Intersect`, `Union`, `Erase`,
`SpatialJoin`, `CalculateField`, `Dissolve`, `Copy`, `Delete`,
`Project`) to stubs because their payloads did not match honua-server's
`BuiltInProcessCatalog` inputs; each one will surface here under
**Stubs** with the per-function `honua-server#...` tracking ticket
shown above until the projection adapter lands.

## Programmatic API

```python
from pathlib import Path
import json

from honua_gp._cli import assess_inventory, render_assessment

inventory = json.loads(Path("inventory.json").read_text())
rows = assess_inventory(inventory)
print(render_assessment(rows))
```

The `rows` list is a sequence of `AssessmentRow` dataclasses; each row knows
its `status`, the dispatcher `backend`, and the recommended replacement.

## Migration tool integration

The migration tool (closed) feeds `honua-gp assess` against every scanned
script and groups the resulting `assessment.json` outputs by repository:

```text
script.py
  -> honua_admin.scan_arcpy_script -> inventory.json
  -> honua-gp assess -> honua-gp-assessment.json
  -> migration tool aggregates {repo, script, supported, stubs, out-of-scope}
```

The aggregated view tells customers exactly how many calls will *run
unchanged*, how many will *raise with a clear hint*, and how many need a
separate migration path (the sa / na / ddd / mp epics tracked elsewhere).
The aggregator never re-implements compatibility classification; the
`assessment.json` payload is the single source of truth.

## Status / scope notes

The matrix is generated from `honua_gp._compat.COMPAT`. Adding a new
function therefore requires one source edit; the CI lane
`.github/workflows/honua-gp-eval.yml` runs `honua-gp matrix --check`
against the committed file and fails on drift.

For sa / na / ddd / mp coverage, file separate epics; the migration product
deliberately punts those to the raster / network-analyst / 3D / mapping work
streams.
