"""InsertCursor: append three rows, then read the persisted rows back."""

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
for path in (PACKAGE_ROOT, PACKAGE_ROOT.parent.parent / "packages" / "honua-sdk", PACKAGE_ROOT.parent.parent / "packages" / "honua-admin"):
    candidate = str(path)
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from eval._stub import install_stub, stub_active

import honua_gp as arcpy

if stub_active():
    install_stub()
else:
    # Live mode: pick up HONUA_BASE_URL / HONUA_API_KEY / HONUA_BEARER_TOKEN
    # so the script runs against the configured Honua deployment.
    arcpy.configure_from_env()

arcpy.env.workspace = "honua://services/transport"
arcpy.env.overwriteOutput = True

from eval._emit import apply_edits_fingerprint, edited_object_ids

with arcpy.da.InsertCursor("roads", ["STATUS", "name"]) as cursor:
    cursor.insertRow(["OPEN", "Main St"])
    cursor.insertRow(["OPEN", "Elm Ave"])
    cursor.insertRow(["CLOSED", "Side Rd"])
    edits = cursor.flush()
added = edited_object_ids(edits, "add")
with arcpy.da.SearchCursor("roads", ["OID@", "STATUS", "name"]) as cursor:
    persisted_rows = sorted([row[1], row[2]] for row in cursor if str(row[0]) in added)
print("insert_cursor_append_rows ok")
from eval._emit import emit_response
emit_response('insert_cursor_append_rows', {**apply_edits_fingerprint(edits), 'persisted_rows': persisted_rows})
