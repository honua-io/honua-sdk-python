"""Union two zoning layers preserving all attributes."""

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

arcpy.analysis.Union(["zoning_2020", "zoning_2024"], "zoning_union", "ALL")
print("union_zoning_layers ok")
