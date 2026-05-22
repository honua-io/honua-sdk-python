"""Composite Buffer -> Intersect -> Union pipeline."""

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
for path in (PACKAGE_ROOT, PACKAGE_ROOT.parent.parent / "packages" / "honua-sdk", PACKAGE_ROOT.parent.parent / "packages" / "honua-admin"):
    candidate = str(path)
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from eval._stub import install_stub, stub_active

import honua_arcpy as arcpy

if stub_active():
    install_stub()
else:
    # Live mode: pick up HONUA_BASE_URL / HONUA_API_KEY / HONUA_BEARER_TOKEN
    # so the script runs against the configured Honua deployment.
    arcpy.configure_from_env()

arcpy.env.workspace = "honua://services/transport"
arcpy.env.overwriteOutput = True

arcpy.analysis.Buffer("roads", "roads_buffer", "5 Meters", dissolve_option="ALL")
arcpy.analysis.Intersect(["roads_buffer", "parcels"], "roads_x_parcels", "ALL")
arcpy.analysis.Union(["roads_x_parcels", "right_of_way"], "row_combined", "ALL")
print("buffer_intersect_union_pipeline ok")
