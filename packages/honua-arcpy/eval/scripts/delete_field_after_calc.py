"""Calculate field, then delete it."""

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

arcpy.management.AddField("segments", "tmp", field_type="LONG")
arcpy.management.CalculateField("segments", "tmp", "1", expression_type="PYTHON3")
arcpy.management.DeleteField("segments", "tmp")
print("delete_field_after_calc ok")
