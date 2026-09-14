"""UpdateCursor: delete CLOSED rows, then confirm they are gone."""

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

# The script owns its fixture row (scoped by name), so there is always a CLOSED
# row to delete -- a zero-delete run is a failure, not a vacuous pass.
with arcpy.da.InsertCursor("roads", ["STATUS", "name"]) as cursor:
    cursor.insertRow(["CLOSED", "Delete Closed Rd"])
    inserted = edited_object_ids(cursor.flush(), "add")
with arcpy.da.UpdateCursor("roads", ["OID@", "STATUS"], "name = 'Delete Closed Rd'") as cursor:
    for row in cursor:
        if row[1] == "CLOSED":
            cursor.deleteRow()
    edits = cursor.flush()
deleted = edited_object_ids(edits, "delete")
with arcpy.da.SearchCursor("roads", ["OID@", "STATUS"], "name = 'Delete Closed Rd'") as cursor:
    rows = list(cursor)
print("update_cursor_delete_closed ok")
from eval._emit import emit_response
emit_response('update_cursor_delete_closed', {**apply_edits_fingerprint(edits), 'deleted_inserted_row': bool(inserted) and deleted == inserted, 'rows_remaining': len(rows)})
