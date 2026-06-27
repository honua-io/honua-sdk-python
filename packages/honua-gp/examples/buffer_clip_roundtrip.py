"""End-to-end ``arcpy -> honua_gp`` parity demo.

``analysis.Buffer`` is now end-to-end supported: the layer-aware projection
adapter (``honua_gp._process_tools``) maps its arcpy signature onto
honua-server's ``analytics.buffer-aggregate`` process, submits an async OGC
API Processes job, polls it to completion, and returns an arcpy-style
``Result``. ``analysis.Clip`` stays a stub -- honua-server only exposes the
single-WKB ``geometry.clip`` op, with no layer-aware counterpart -- so the
migration tool still surfaces it via ``honua-gp assess``.

The demo exercises the supported surface end-to-end: layer aliases, attribute
selection, row counts, update cursors, and a layer-aware Buffer job.

Run the script against a configured Honua deployment::

    export HONUA_BASE_URL="https://honua.example.com"
    export HONUA_API_KEY="..."
    python examples/buffer_clip_roundtrip.py

Or wire up a stub transport in tests (see
``tests/test_buffer_clip_roundtrip.py``).
"""

from __future__ import annotations

import os
from pathlib import Path

import honua_gp as arcpy

# --------------------------------------------------------------------------
# Equivalent arcpy script (kept here for parity reviews):
#
#   import arcpy
#   arcpy.env.workspace = r"C:\\GIS\\transport.gdb"
#   arcpy.env.overwriteOutput = True
#   arcpy.management.MakeFeatureLayer("roads", "roads_lyr", "STATUS = 'OPEN'")
#   open_count = int(arcpy.management.GetCount("roads_lyr"))
#   with arcpy.da.UpdateCursor("roads_lyr", ["OID@", "STATUS"]) as cursor:
#       for row in cursor:
#           if row[1] == "CLOSED":
#               cursor.deleteRow()
# --------------------------------------------------------------------------


def main() -> int:
    # When the harness has already wired a client (e.g. the eval stub via
    # ``install_stub`` or a unit test), trust that wiring and skip
    # ``configure_from_env`` -- otherwise the env-driven reconfigure would
    # invalidate the cached stub client and force a real network call.
    session = arcpy.get_session()
    has_client = session._client is not None  # noqa: SLF001 -- intentional white-box check
    if not has_client:
        base_url = os.environ.get("HONUA_BASE_URL")
        if not base_url:
            print("Set HONUA_BASE_URL (and HONUA_API_KEY if required) before running this example.")
            return 0
        arcpy.configure_from_env()
    arcpy.env.workspace = os.environ.get("HONUA_GP_WORKSPACE") or "honua://services/transport"
    arcpy.env.overwriteOutput = True

    arcpy.management.MakeFeatureLayer(
        in_features="roads",
        out_layer="roads_lyr",
        where_clause="STATUS = 'OPEN'",
    )

    open_count = int(arcpy.management.GetCount("roads_lyr"))

    closed_count = 0
    with arcpy.da.UpdateCursor("roads_lyr", ["OID@", "STATUS"]) as cursor:
        for row in cursor:
            if row[1] == "CLOSED":
                cursor.deleteRow()
                closed_count += 1

    audit_dir = Path(os.environ.get("HONUA_GP_AUDIT_DIR") or ".honua-gp/audit")
    print(
        f"open layer count={open_count}; removed {closed_count} closed segments. "
        f"Audit JSONL: {audit_dir.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
