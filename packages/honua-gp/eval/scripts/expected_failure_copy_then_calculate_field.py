"""Expected-failure: a Copy-then-CalculateField chain raises on the first step.

Both ``data-management.copy-features`` and ``data-management.calculate-field``
are classified CanServe=false on honua-server (only reachable inside a
honua-geoprocessing analysis plan), so the leading Copy already raises a
client-side ``HonuaGpUnsupportedError`` before CalculateField is reached.
"""

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
for path in (PACKAGE_ROOT, PACKAGE_ROOT.parent.parent / "packages" / "honua-sdk", PACKAGE_ROOT.parent.parent / "packages" / "honua-admin"):
    candidate = str(path)
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from eval._stub import install_stub, stub_active

import honua_gp as gp

if stub_active():
    install_stub()
else:
    # Live mode: pick up HONUA_BASE_URL / HONUA_API_KEY / HONUA_BEARER_TOKEN
    # so the script runs against the configured Honua deployment.
    gp.configure_from_env()

gp.env.workspace = "honua://services/transport"
gp.env.overwriteOutput = True

try:
    gp.management.Copy("honua://services/stage/0", "published")
    gp.management.CalculateField("honua://services/stage/0", "reviewed", "1")
except gp.HonuaGpUnsupportedError as exc:
    print(f"expected_failure_copy_then_calculate_field caught {exc.function}")
    raise SystemExit(0) from exc
raise SystemExit("expected_failure_copy_then_calculate_field did not raise")
