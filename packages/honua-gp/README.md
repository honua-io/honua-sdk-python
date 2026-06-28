# honua-gp

**Proprietary** compatibility shim that lets a **supported subset** of `arcpy`
Python scripts -- feature-layer queries, search/insert/update cursors, and
`GetCount`-style workflows -- run against a Honua deployment without a rewrite.
Coverage is partial (roughly the mapped functions in the table below; see
[`docs/compatibility-matrix.md`](docs/compatibility-matrix.md) for the
authoritative matrix); unmapped functions raise a clear `ExecuteError` rather
than silently succeeding. Distributed as a closed-source package; this directory
carries its own `LICENSE` that overrides the surrounding monorepo Apache-2.0
grant.

Customers replace `import arcpy` with `import honua_gp as arcpy` and point
the shim at a Honua base URL. Every shim call dispatches through one of three
existing clients -- `honua_sdk.HonuaClient`, `honua_admin.HonuaAdminClient`, or
`honua_sdk.protocols.OgcProcessesClient` -- and emits an audit JSONL record so
the migration tool can build a fine-tuning corpus.

## Layout

```
honua-gp/
├── LICENSE                            # Proprietary, overrides monorepo
├── pyproject.toml                     # name=honua-gp
├── honua_gp/
│   ├── __init__.py                    # analysis / management / da / env / ExecuteError
│   ├── _audit.py                      # rotating per-day JSONL logger
│   ├── _compat.py                     # single-source compatibility manifest
│   ├── _dispatch.py                   # dispatch entry-point used by every shim
│   ├── _resolve.py                    # arcpy path -> SourceDescriptor / source string
│   ├── _errors.py                     # ExecuteError-shaped exceptions
│   ├── _session.py                    # arcpy.env-style module-global session
│   ├── _cli.py                        # honua-gp assess <inventory.json> + matrix
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
│   └── buffer_clip_roundtrip.py       # arcpy <-> honua_gp parity demo
├── scripts/
│   └── render_compat_matrix.py
└── tests/
```

The shim does not expose a `_client.py` shim module today -- session
client construction lives in `_session.py` (`HonuaSession._build_client`
/ `_build_admin_client` plus the lazy `processes_client()` accessor).
The migration-tool integration narrative
(`../../docs/honua-gp/scanner-handoff.md`) is owned by the workspace
docs tree, not the package docs directory.

## Quickstart

```python
import honua_gp as arcpy

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

Process-backed shims run a supported subset against honua-server's
``BuiltInProcessCatalog`` as asynchronous OGC API Processes jobs:
``analysis.Buffer`` and ``management.Copy`` / ``CopyFeatures`` / ``Project``
are **Supported**, and ``analysis.SpatialJoin`` plus
``management.CalculateField`` / ``Dissolve`` are **Partial** (documented
deviations -- see the matrix). The remaining process-shaped operations
(``analysis.Clip`` / ``Intersect`` / ``Union`` / ``Erase`` and
``management.Delete``) still raise ``HonuaGpUnsupportedError`` because
honua-server only exposes the single-WKB ``geometry.*`` family (one geometry
per call, not feature classes) and ``data-management.delete-features`` deletes
filtered features inside a layer rather than dropping the dataset arcpy.Delete
targets. The migration tool surfaces each unmapped op as a ``stub`` with a
``honua-server#...`` tracking ticket so customers know what work remains. See
[`docs/compatibility-matrix.md`](docs/compatibility-matrix.md) for the
authoritative per-function status and [`CHANGELOG.md`](CHANGELOG.md) for the
projection-adapter promotion. The end-to-end runnable example lives at
[`examples/buffer_clip_roundtrip.py`](examples/buffer_clip_roundtrip.py).

The shim writes one JSONL line per call to
`${HONUA_GP_AUDIT_DIR:-./.honua-gp/audit}/audit-YYYYMMDD.jsonl`. Run
`honua-gp assess <inventory.json>` against a `honua_admin.scan_arcpy_script`
inventory to get a per-call TODO list against the compatibility matrix.

## Status

- **Closed source:** distributed via private PyPI index; do not redistribute.
- **MVP scope:** 45 functions (15 analysis + 20 management + 10 da); see
  [`docs/compatibility-matrix.md`](docs/compatibility-matrix.md).
- **Coverage today:** 7 supported entries and 6 partial entries
  (13 supported/partial) + 32 stubs. Supported: session-backed
  ``MakeFeatureLayer`` / ``MakeTableView``, the two buffered ``da`` write
  cursors (``InsertCursor`` / ``UpdateCursor``), and process-backed
  ``analysis.Buffer`` / ``management.Copy`` / ``management.Project``. Partial:
  source-backed ``SelectLayerByAttribute`` / ``GetCount`` / ``da.SearchCursor``,
  and process-backed ``analysis.SpatialJoin`` / ``management.CalculateField`` /
  ``management.Dissolve`` (documented deviations). The layer-aware projection
  adapter (see [`CHANGELOG.md`](CHANGELOG.md)) re-promoted the six high-frequency
  process tools from stub to working. The remaining process-shaped stubs
  (``analysis.Clip`` / ``Intersect`` / ``Union`` / ``Erase`` and
  ``management.Delete``) each carry a ``honua-server#...`` tracking ticket
  because no single ``BuiltInProcessCatalog`` op maps onto them.
- **Audit:** every invocation produces a redacted JSONL record (paths and
  secrets are stripped per the `honua_admin._arcpy_scanner` heuristics).
