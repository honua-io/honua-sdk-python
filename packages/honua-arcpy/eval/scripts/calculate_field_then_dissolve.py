"""Calculate a field then dissolve on it."""

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

arcpy.management.CalculateField("parcels", "group", "!zoning_code!", expression_type="PYTHON3")
arcpy.management.Dissolve("parcels", "parcels_grouped", dissolve_field=["group"])
print("calculate_field_then_dissolve ok")
