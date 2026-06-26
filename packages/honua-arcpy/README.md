# honua-arcpy

**Proprietary** drop-in compatibility shim that lets existing `arcpy` Python
scripts run end-to-end against a Honua deployment without a rewrite. Distributed
as a closed-source package; this directory carries its own `LICENSE` that
overrides the surrounding monorepo Apache-2.0 grant.

Customers replace `import arcpy` with `import honua_arcpy as arcpy` and point
the shim at a Honua base URL. Every shim call dispatches through one of three
existing clients -- `honua_sdk.HonuaClient`, `honua_admin.HonuaAdminClient`, or
`honua_sdk.protocols.OgcProcessesClient` -- and emits an audit JSONL record so
the migration tool can build a fine-tuning corpus.

## Layout

```
honua-arcpy/
├── LICENSE                            # Proprietary, overrides monorepo
├── pyproject.toml                     # name=honua-arcpy
├── honua_arcpy/
│   ├── __init__.py                    # analysis / management / da / env / ExecuteError
│   ├── _audit.py                      # rotating per-day JSONL logger
│   ├── _compat.py                     # single-source compatibility manifest
│   ├── _dispatch.py                   # dispatch entry-point used by every shim
│   ├── _resolve.py                    # arcpy path -> SourceDescriptor / source string
│   ├── _errors.py                     # ExecuteError-shaped exceptions
│   ├── _session.py                    # arcpy.env-style module-global session
│   ├── _cli.py                        # honua-arcpy assess <inventory.json> + matrix
│   ├── env.py                         # arcpy.env shim
│   ├── analysis/                      # 15 functions (2 process-backed, 13 stubbed)
│   ├── management/                    # 20 functions (4 mapped + 4 process-backed, 12 stubbed)
│   └── da/                            # 10 functions (3 mapped, 7 stubbed)
├── docs/
│   └── compatibility-matrix.md        # generated -- do not hand edit
├── eval/
│   ├── scripts/                       # 50 representative arcpy scripts
│   ├── golden/                        # checked-in reference outputs
│   └── run_eval.py                    # pass-rate harness, writes JUnit + JSON
├── examples/
│   └── buffer_clip_roundtrip.py       # arcpy <-> honua_arcpy parity demo
├── scripts/
│   └── render_compat_matrix.py
└── tests/
```

```
honua-arcpy/
├── ...
│   ├── _process_jobs.py                 # OGC API Processes submit-and-poll loop
│   ├── _process_tools.py                # arcpy GP tool -> honua-server process projection
```

The shim does not expose a `_client.py` shim module today -- session
client construction lives in `_session.py` (`HonuaSession._build_client`
/ `_build_admin_client` plus the lazy `processes_client()` accessor).
The migration-tool integration narrative
(`../../docs/honua-arcpy/scanner-handoff.md`) is owned by the workspace
docs tree, not the package docs directory.

## Quickstart

```python
import honua_arcpy as arcpy

arcpy.configure(base_url="https://honua.example.com", api_key="...")
arcpy.env.workspace = "honua://services/transport"
arcpy.env.overwriteOutput = True

# Session/source-backed shims run end-to-end against honua-server today.
arcpy.management.MakeFeatureLayer("roads", "roads_lyr", where_clause="STATUS = 'OPEN'")
open_count = int(arcpy.management.GetCount("roads_lyr"))
with arcpy.da.UpdateCursor("roads_lyr", ["OID@", "STATUS"]) as cursor:
    for row in cursor:
        if row[1] == "CLOSED":
            cursor.deleteRow()
```

Six high-frequency GP tools now run end-to-end against honua-server's
layer-aware geoprocessing processes via the projection adapter in
``honua_arcpy._process_tools``: ``analysis.Buffer`` ->
``analytics.buffer-aggregate``, ``analysis.SpatialJoin`` ->
``analytics.spatial-join``, ``management.Dissolve`` ->
``generalization.dissolve``, ``management.CalculateField`` ->
``data-management.calculate-field``, ``management.Copy`` /
``CopyFeatures`` -> ``data-management.copy-features``, and
``management.Project`` -> ``conversion.feature-project``. Each accepts the
arcpy-style parameters, projects the input feature class / layer alias to a
numeric ``layerId``, submits an **async OGC API Processes job**, polls it to
completion, and returns an arcpy-style ``Result``.

The four overlay tools arcpy expresses over feature classes -- ``Clip`` /
``Intersect`` / ``Union`` / ``Erase`` -- remain ``HonuaArcpyUnsupportedError``
stubs: honua-server only exposes the single-geometry ``geometry.*`` family
(one base64-WKB geometry at a time), with no layer-aware counterpart, so a
client-side per-feature WKB serialization loop would be required.
``management.Delete`` also stays a stub because arcpy deletes a whole dataset
while ``data-management.delete-features`` only deletes filtered features inside
a layer. The migration tool surfaces every remaining stub with a
``honua-server#...`` tracking ticket. The end-to-end runnable example lives at
[`examples/buffer_clip_roundtrip.py`](examples/buffer_clip_roundtrip.py).

The shim writes one JSONL line per call to
`${HONUA_ARCPY_AUDIT_DIR:-./.honua-arcpy/audit}/audit-YYYYMMDD.jsonl`. Run
`honua-arcpy assess <inventory.json>` against a `honua_admin.scan_arcpy_script`
inventory to get a per-call TODO list against the compatibility matrix.

## Status

- **Closed source:** distributed via private PyPI index; do not redistribute.
- **MVP scope:** 45 functions (15 analysis + 20 management + 10 da); see
  [`docs/compatibility-matrix.md`](docs/compatibility-matrix.md).
- **Coverage today:** **7 supported + 6 partial + 32 stubs** of 45
  functions. Supported: session-backed ``MakeFeatureLayer`` /
  ``MakeTableView``; the ``da.UpdateCursor`` / ``da.InsertCursor`` cursors;
  and the process-backed ``analysis.Buffer`` / ``management.Copy`` /
  ``management.Project``. Partial (run with documented deviations):
  source-backed ``SelectLayerByAttribute`` / ``GetCount`` / ``da.SearchCursor``;
  and the process-backed ``analysis.SpatialJoin`` /
  ``management.CalculateField`` / ``management.Dissolve``. Six entries are
  process-backed via the layer-aware projection adapter (audit pass 8's
  ``BuiltInProcessCatalog`` mismatch is resolved by projecting each arcpy
  signature onto the matching ``layerId``-shaped honua-server process and
  running it as an async job). The remaining 32 stubs -- including the
  overlay tools (``Clip`` / ``Intersect`` / ``Union`` / ``Erase``, which only
  have single-WKB ``geometry.*`` ops) and ``Delete`` (different semantics from
  ``delete-features``) -- each carry a ``honua-server#...`` tracking ticket.
- **Audit:** every invocation produces a redacted JSONL record (paths and
  secrets are stripped per the `honua_admin._arcpy_scanner` heuristics).
