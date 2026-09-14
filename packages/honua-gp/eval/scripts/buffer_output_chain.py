"""Buffer, read the bound output with GetCount/SearchCursor, then Dissolve (#226)."""

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

import json

from honua_gp import HonuaGpResolveError

input_count = int(arcpy.management.GetCount("roads"))
result = arcpy.analysis.Buffer("roads", "roads_buffer", "25 Meters", dissolve_option="ALL")
buffer_count = int(arcpy.management.GetCount(result[0]))
with arcpy.da.SearchCursor("roads_buffer", ["SHAPE@JSON"]) as cursor:
    geometry_types = sorted({json.loads(row[0])["type"] for row in cursor})
# The buffer output is an inline job result, not a server layer: a layer-aware
# tool cannot take it as input and must refuse instead of reading layer 0.
try:
    arcpy.management.Dissolve("roads_buffer", "roads_buffer_dissolved")
    chained = "ran"
except HonuaGpResolveError:
    chained = "refused"
dissolved = arcpy.management.Dissolve("roads", "roads_dissolved")
dissolve_count = int(arcpy.management.GetCount(dissolved[0]))
print(f"buffer_output_chain ok input={input_count} buffer={buffer_count} dissolve={dissolve_count} chained={chained}")
from eval._emit import emit_response
emit_response('buffer_output_chain', {'input_count': input_count, 'buffer_count': buffer_count, 'buffer_geometry_types': geometry_types, 'chained_dissolve': chained, 'dissolve_count': dissolve_count})
