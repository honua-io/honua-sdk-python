"""Expected-failure: CalculateField has no standalone honua-server process.

honua-server classifies ``data-management.calculate-field`` as CanServe=false;
it is only reachable inside a honua-geoprocessing analysis plan, so a one-shot
CalculateField 404s on every server version. The shim surfaces that as a
client-side ``HonuaGpUnsupportedError``.
"""

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

try:
    arcpy.management.CalculateField("honua://services/segments/0", "active", "1", where_clause="status = 'OPEN'")
except arcpy.HonuaGpUnsupportedError as exc:
    print(f"expected_failure_calculate_field_constant caught {exc.function}")
    raise SystemExit(0) from exc
raise SystemExit("expected_failure_calculate_field_constant did not raise")
