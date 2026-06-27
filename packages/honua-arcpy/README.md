# honua-arcpy

**Proprietary** compatibility shim that lets a **supported subset** of `arcpy`
Python scripts -- feature-layer queries, search/insert/update cursors, and
`GetCount`-style workflows -- run against a Honua deployment without a rewrite.
Coverage is partial (roughly the mapped functions in the table below; see
[`docs/compatibility-matrix.md`](docs/compatibility-matrix.md) for the
authoritative matrix); unmapped functions raise a clear `ExecuteError` rather
than silently succeeding. Distributed as a closed-source package; this directory
carries its own `LICENSE` that overrides the surrounding monorepo Apache-2.0
grant.

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
│   ├── analysis/                      # 15 functions (0 mapped, 15 stubbed)
│   ├── management/                    # 20 functions (4 mapped, 16 stubbed)
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

Process-backed shims (``analysis.Buffer`` / ``Clip`` / ``Intersect`` /
``Union`` / ``Erase`` / ``SpatialJoin`` and ``management.CalculateField``
/ ``Dissolve`` / ``Copy`` / ``Delete`` / ``Project``) currently raise
``HonuaArcpyUnsupportedError`` -- audit pass 8 downgraded them because
their payloads did not match honua-server's ``BuiltInProcessCatalog``
inputs (see [`CHANGELOG.md`](CHANGELOG.md) and the Status section
below). The migration tool surfaces each one as a ``stub`` with a
``honua-server#...`` tracking ticket so customers know what work
remains. The end-to-end runnable example lives at
[`examples/buffer_clip_roundtrip.py`](examples/buffer_clip_roundtrip.py).

The shim writes one JSONL line per call to
`${HONUA_ARCPY_AUDIT_DIR:-./.honua-arcpy/audit}/audit-YYYYMMDD.jsonl`. Run
`honua-arcpy assess <inventory.json>` against a `honua_admin.scan_arcpy_script`
inventory to get a per-call TODO list against the compatibility matrix.

## Status

- **Closed source:** distributed via private PyPI index; do not redistribute.
- **MVP scope:** 45 functions (15 analysis + 20 management + 10 da); see
  [`docs/compatibility-matrix.md`](docs/compatibility-matrix.md).
- **Coverage today:** 4 supported entries and 3 partial entries
  (session-backed ``MakeFeatureLayer`` / ``MakeTableView``, source-backed
  ``SelectLayerByAttribute`` / ``GetCount``, and the three ``da`` cursors)
  + 38 stubs. The 11 previously process-backed entries (``Buffer``,
  ``Clip``, ``Intersect``, ``Union``, ``Erase``, ``SpatialJoin``,
  ``CalculateField``, ``Dissolve``, ``Copy``, ``Delete``, ``Project``)
  were downgraded in audit pass 8 because their payloads did not match
  honua-server's ``BuiltInProcessCatalog`` contract. Each carries a
  ``honua-server#...`` tracking ticket pointing at the projection
  adapter that needs to land before they can be re-promoted.
- **Audit:** every invocation produces a redacted JSONL record (paths and
  secrets are stripped per the `honua_admin._arcpy_scanner` heuristics).
