"""Buffer then clip roads against a study area."""

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

arcpy.analysis.Buffer("roads", "roads_buffer", "25 Meters", dissolve_option="ALL")
arcpy.analysis.Clip("roads_buffer", "study_area", "roads_clip")
print("buffer_clip_roads_in_study ok")
