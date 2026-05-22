"""End-to-end Buffer -> Clip -> ApplyEdits demo using honua_arcpy.

This is the canonical "arcpy -> honua_arcpy parity" sample. Pair it with the
matching arcpy script (commented in this file) when running against a
licensed ArcGIS Pro install for side-by-side verification.

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

import honua_arcpy as arcpy

# --------------------------------------------------------------------------
# Equivalent arcpy script (kept here for parity reviews):
#
#   import arcpy
#   arcpy.env.workspace = r"C:\\GIS\\transport.gdb"
#   arcpy.env.overwriteOutput = True
#   arcpy.analysis.Buffer("roads", "roads_buffer", "25 Meters", dissolve_option="ALL")
#   arcpy.analysis.Clip("roads_buffer", "study_area", "roads_in_study")
#   with arcpy.da.UpdateCursor("roads_in_study", ["OID@", "STATUS"]) as cursor:
#       for row in cursor:
#           if row[1] == "CLOSED":
#               cursor.deleteRow()
# --------------------------------------------------------------------------


def main() -> int:
    base_url = os.environ.get("HONUA_BASE_URL")
    if not base_url:
        print("Set HONUA_BASE_URL (and HONUA_API_KEY if required) before running this example.")
        return 0

    arcpy.configure_from_env()
    arcpy.env.workspace = os.environ.get("HONUA_ARCPY_WORKSPACE") or "honua://services/transport"
    arcpy.env.overwriteOutput = True

    arcpy.analysis.Buffer(
        in_features="roads",
        out_feature_class="roads_buffer",
        buffer_distance_or_field="25 Meters",
        dissolve_option="ALL",
    )

    arcpy.analysis.Clip(
        in_features="roads_buffer",
        clip_features="study_area",
        out_feature_class="roads_in_study",
    )

    closed_count = 0
    with arcpy.da.UpdateCursor("roads_in_study", ["OID@", "STATUS"]) as cursor:
        for row in cursor:
            if row[1] == "CLOSED":
                cursor.deleteRow()
                closed_count += 1

    audit_dir = Path(os.environ.get("HONUA_ARCPY_AUDIT_DIR") or ".honua-arcpy/audit")
    print(f"Removed {closed_count} closed segments. Audit JSONL: {audit_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
