"""UpdateCursor: flip CLOSED rows to ARCHIVED, then read the rows back."""

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

# The script owns its fixture row (scoped by name), so the oracle does not
# depend on which other scripts ran first or on a previous run's leftovers.
with arcpy.da.InsertCursor("roads", ["STATUS", "name"]) as cursor:
    cursor.insertRow(["CLOSED", "Close Status Rd"])
with arcpy.da.UpdateCursor("roads", ["OID@", "STATUS"], "name = 'Close Status Rd'") as cursor:
    for row in cursor:
        if row[1] == "CLOSED":
            row[1] = "ARCHIVED"
            cursor.updateRow(row)
    edits = cursor.flush()
updated = edited_object_ids(edits, "update")
with arcpy.da.SearchCursor("roads", ["OID@", "STATUS", "name"], "name = 'Close Status Rd'") as cursor:
    rows = list(cursor)
updated_rows = sorted([row[1], row[2]] for row in rows if str(row[0]) in updated)
closed_remaining = sum(1 for row in rows if row[1] == "CLOSED")
print("update_cursor_close_status ok")
from eval._emit import emit_response
emit_response('update_cursor_close_status', {**apply_edits_fingerprint(edits), 'updated_rows': updated_rows, 'closed_remaining': closed_remaining})
