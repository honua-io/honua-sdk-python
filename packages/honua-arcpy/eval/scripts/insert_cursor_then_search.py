"""InsertCursor then SearchCursor to confirm."""

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
for path in (PACKAGE_ROOT, PACKAGE_ROOT.parent.parent / "packages" / "honua-sdk", PACKAGE_ROOT.parent.parent / "packages" / "honua-admin"):
    candidate = str(path)
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from eval._stub import install_stub, stub_active

if stub_active():
    install_stub()

import honua_arcpy as arcpy

arcpy.env.workspace = "honua://services/transport"
arcpy.env.overwriteOutput = True

with arcpy.da.InsertCursor("roads", ["STATUS", "name"]) as cursor:
    cursor.insertRow(["OPEN", "Loop Rd"])
with arcpy.da.SearchCursor("roads", ["OID@", "name"]) as cursor:
    rows = list(cursor)
print(f"insert_cursor_then_search ok rows={len(rows)}")
