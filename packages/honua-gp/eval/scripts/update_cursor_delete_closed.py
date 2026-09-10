"""UpdateCursor: delete CLOSED rows."""

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
for path in (PACKAGE_ROOT, PACKAGE_ROOT.parent.parent / "packages" / "honua-sdk", PACKAGE_ROOT.parent.parent / "packages" / "honua-admin"):
    candidate = str(path)
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from eval._emit import apply_edits_fingerprint, emit_response
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

with arcpy.da.UpdateCursor("roads", ["OID@", "STATUS"]) as cursor:
    for row in cursor:
        if row[1] == "CLOSED":
            cursor.deleteRow()
    # Flush explicitly (rather than relying on the implicit __exit__ flush) so
    # the applyEdits result is available here to fingerprint. update_cursor_
    # close_status runs alphabetically first and archives every CLOSED row on
    # the same seeded layer, so this deterministically finds zero rows to
    # delete -- that is itself the stable oracle, not an absent one.
    result = cursor.flush()

emit_response("update_cursor_delete_closed", apply_edits_fingerprint(result))
print("update_cursor_delete_closed ok")
