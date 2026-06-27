"""Expected-failure script exercising analysis.NearestNeighbor."""

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

arcpy.env.workspace = "honua://services/legacy"
arcpy.env.overwriteOutput = True

try:
    arcpy.analysis.NearestNeighbor('points')
except arcpy.HonuaGpUnsupportedError as exc:
    print(f"expected_failure_nearest_neighbor caught {exc.function}")
    raise SystemExit(0) from exc
raise SystemExit("expected_failure_nearest_neighbor did not raise")
