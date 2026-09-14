"""GetCount on a FeatureServer layer URL with environment-only configuration (#205)."""

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
# Live mode: deliberately NO configure call -- the first tool invocation must
# pick up HONUA_BASE_URL / HONUA_API_KEY from the environment by itself.

arcpy.env.workspace = "honua://services/transport"
arcpy.env.overwriteOutput = True

import os

from honua_gp._resolve import descriptor_mapping, resolve

base_url = os.environ.get("HONUA_BASE_URL") or "https://honua.example.com"
full_url = base_url.rstrip("/") + "/rest/services/test_service/FeatureServer/0"
relative_path = "rest/services/test_service/FeatureServer/0"
full_count = arcpy.management.GetCount(full_url)
relative_count = arcpy.management.GetCount(relative_path)
locator = descriptor_mapping(resolve(full_url))["locator"]
print(f"get_count_feature_server_url ok full={full_count} relative={relative_count} locator={locator}")
from eval._emit import emit_response
emit_response('get_count_feature_server_url', {'full_url_count': int(full_count), 'relative_path_count': int(relative_count), 'locator': locator})
