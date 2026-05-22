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
│   ├── _client.py                     # shared sync clients (Honua, Admin, OGC Processes)
│   ├── _audit.py                      # rotating per-day JSONL logger
│   ├── _compat.py                     # single-source compatibility manifest
│   ├── _dispatch.py                   # dispatch entry-point used by every shim
│   ├── _resolve.py                    # arcpy path -> SourceDescriptor / source string
│   ├── _errors.py                     # ExecuteError-shaped exceptions
│   ├── _session.py                    # arcpy.env-style module-global session
│   ├── _cli.py                        # honua-arcpy assess <inventory.json>
│   ├── env.py                         # arcpy.env shim
│   ├── analysis/                      # 15 functions (6 mapped, 9 stubbed)
│   ├── management/                    # 20 functions (10 mapped, 10 stubbed)
│   └── da/                            # 10 cursor / data-access entries
├── docs/
│   ├── compatibility-matrix.md        # generated -- do not hand edit
│   └── scanner-handoff.md
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

## Quickstart

```python
import honua_arcpy as arcpy

arcpy.configure(base_url="https://honua.example.com", api_key="...")
arcpy.env.workspace = "honua://services/transport"
arcpy.env.overwriteOutput = True

arcpy.analysis.Buffer("roads", "roads_buffer", "25 Meters", dissolve_option="ALL")
arcpy.analysis.Clip("roads_buffer", "study_area", "roads_clip")
arcpy.management.Project("roads_clip", "roads_wgs84", 4326)
```

The shim writes one JSONL line per call to
`${HONUA_ARCPY_AUDIT_DIR:-./.honua-arcpy/audit}/audit-YYYYMMDD.jsonl`. Run
`honua-arcpy assess <inventory.json>` against a `honua_admin.scan_arcpy_script`
inventory to get a per-call TODO list against the compatibility matrix.

## Status

- **Closed source:** distributed via private PyPI index; do not redistribute.
- **MVP scope:** 45 functions (15 analysis + 20 management + 10 da); see
  [`docs/compatibility-matrix.md`](docs/compatibility-matrix.md).
- **Audit:** every invocation produces a redacted JSONL record (paths and
  secrets are stripped per the `honua_admin._arcpy_scanner` heuristics).
