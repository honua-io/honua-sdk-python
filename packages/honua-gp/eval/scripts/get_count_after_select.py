"""GetCount on a selection layer."""

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
for path in (PACKAGE_ROOT, PACKAGE_ROOT.parent.parent / "packages" / "honua-sdk", PACKAGE_ROOT.parent.parent / "packages" / "honua-admin"):
    candidate = str(path)
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from eval._stub import install_stub, stub_active

import honua_gp as gp

if stub_active():
    install_stub()
else:
    # Live mode: pick up HONUA_BASE_URL / HONUA_API_KEY / HONUA_BEARER_TOKEN
    # so the script runs against the configured Honua deployment.
    gp.configure_from_env()

gp.env.workspace = "honua://services/transport"
gp.env.overwriteOutput = True

gp.management.MakeFeatureLayer("roads", "roads_lyr")
gp.management.SelectLayerByAttribute("roads_lyr", "NEW_SELECTION", "STATUS = 'OPEN'")
count = gp.management.GetCount("roads_lyr")
print(f"get_count_after_select ok count={count}")
from eval._emit import emit_response
emit_response('get_count_after_select', {'count': int(count)})
