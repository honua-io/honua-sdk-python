"""SpatialJoin with explicit search radius."""

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

arcpy.env.workspace = "honua://services/planning"
arcpy.env.overwriteOutput = True

arcpy.analysis.SpatialJoin(
    "facilities",
    "parcels",
    "facilities_with_parcel",
    join_operation="JOIN_ONE_TO_ONE",
    match_option="WITHIN_A_DISTANCE",
    search_radius="100 Meters",
)
print("spatial_join_with_radius ok")
