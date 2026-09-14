"""Make a filtered table view, then read the server rows through it."""

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

arcpy.management.MakeTableView("segments_attrs", "segments_view", "status = 'active'")
# MakeTableView itself only registers a session alias; the observable result is
# what the server returns when the view (and its where clause) is read.
view_count = int(arcpy.management.GetCount("segments_view"))
with arcpy.da.SearchCursor("segments_view", ["name", "status"]) as cursor:
    view_rows = sorted([row[0], row[1]] for row in cursor)
print(f"make_table_view ok count={view_count}")
from eval._emit import emit_response
emit_response('make_table_view', {'view_count': view_count, 'view_rows': view_rows})
