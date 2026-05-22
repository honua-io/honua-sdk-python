# honua-arcpy scanner handoff

This doc shows how an ArcPy script inventory produced by the migration scanner
(see `honua_admin.scan_arcpy_script` / `honua_sdk.migration.scan_arcpy_file`)
flows into the `honua-arcpy` shim, and how a customer running the shim can
get a per-call translation TODO list against the compatibility matrix.

## Inputs

`assess` accepts both documented scanner shapes:

* `honua_admin.scan_arcpy_script(...)` (and the `honua-arcpy-scan` console
  command) emit an `ArcPyScriptInventoryArtifact` with the per-call list
  under `toolCalls` (legacy `tool_calls` is also accepted). Each entry
  should include either a fully-qualified `call` such as
  `arcpy.analysis.Buffer`, or a `(toolbox, tool)` pair.
* `honua_sdk.migration.scan_arcpy_source(...).to_dict()` (or
  `scan_arcpy_file(...)`) emits an `ArcPyScanReport` with the per-call
  list under `calls`. Each entry carries `qualifiedName`, `family`, and
  `tool` keys, which `assess` matches against the compatibility manifest.

Entries without classifiable names are skipped.

Example inventory excerpts:

```jsonc
// honua_admin.scan_arcpy_script shape
{
  "toolCalls": [
    { "call": "arcpy.analysis.Buffer", "tool": "Buffer", "toolbox": "analysis" },
    { "call": "arcpy.management.SelectLayerByLocation", "tool": "SelectLayerByLocation", "toolbox": "management" },
    { "call": "arcpy.sa.Slope", "tool": "Slope", "toolbox": "sa" }
  ]
}
```

```jsonc
// honua_sdk.migration.scan_arcpy_source(...).to_dict() shape
{
  "calls": [
    { "qualifiedName": "arcpy.analysis.Buffer", "family": "analysis", "tool": "Buffer" },
    { "qualifiedName": "arcpy.management.SelectLayerByLocation", "family": "management", "tool": "SelectLayerByLocation" }
  ]
}
```

## CLI

```bash
honua-arcpy assess path/to/inventory.json
```

The CLI:

1. Pivots `toolCalls` against the compatibility manifest (`honua_arcpy._compat.COMPAT`).
2. Prints a per-call bucketed list to stdout:
   * **Supported** -- function runs unchanged on Honua.
   * **Stub** -- function will raise `HonuaArcpyUnsupportedError` with a
     replacement hint and a honua-server tracking ticket.
   * **Out-of-scope** -- sa / na / ddd / mp toolboxes outside the MVP.
3. Writes a machine-readable `honua-arcpy-assessment.json` next to the
   inventory (override with `--output-dir`).

Example output:

```
honua-arcpy assessment
======================

Supported: 1  Stubs: 1  Out-of-scope: 1

Supported (run unchanged)
-------------------------
  [  1x] analysis.Buffer  --  Vector buffer; dispatches to honua-server geometry.buffer.

Stubs (will raise -- replacement hint shown)
--------------------------------------------
  [  1x] management.SelectLayerByLocation  --  Spatial selection composed of buffer + intersect when no native process exists.
       hint: Use honua_arcpy.analysis.Buffer + analysis.Intersect, then SelectLayerByAttribute.
       tracking: honua-server#spatial-filter

Out of MVP scope
----------------
  [  1x] sa.Slope  --  Not in honua-arcpy MVP scope (sa/na/ddd/mp).
       hint: Open a backlog ticket; see docs/honua-arcpy/scanner-handoff.md.
```

## Programmatic API

```python
from pathlib import Path
import json

from honua_arcpy._cli import assess_inventory, render_assessment

inventory = json.loads(Path("inventory.json").read_text())
rows = assess_inventory(inventory)
print(render_assessment(rows))
```

The `rows` list is a sequence of `AssessmentRow` dataclasses; each row knows
its `status`, the dispatcher `backend`, and the recommended replacement.

## Migration tool integration

The migration tool (closed) feeds `honua-arcpy assess` against every scanned
script and groups the resulting `assessment.json` outputs by repository:

```text
script.py
  -> honua_admin.scan_arcpy_script -> inventory.json
  -> honua-arcpy assess -> honua-arcpy-assessment.json
  -> migration tool aggregates {repo, script, supported, stubs, out-of-scope}
```

The aggregated view tells customers exactly how many calls will *run
unchanged*, how many will *raise with a clear hint*, and how many need a
separate migration path (the sa / na / ddd / mp epics tracked elsewhere).
The aggregator never re-implements compatibility classification; the
`assessment.json` payload is the single source of truth.

## Status / scope notes

The matrix is generated from `honua_arcpy._compat.COMPAT`. Adding a new
function therefore requires one source edit; the CI lane
`.github/workflows/honua-arcpy-eval.yml` runs `honua-arcpy matrix --check`
against the committed file and fails on drift.

For sa / na / ddd / mp coverage, file separate epics; the migration product
deliberately punts those to the raster / network-analyst / 3D / mapping work
streams.
