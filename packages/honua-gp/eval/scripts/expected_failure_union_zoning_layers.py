"""Expected-failure script exercising analysis.Union."""

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

gp.env.workspace = "honua://services/legacy"
gp.env.overwriteOutput = True

try:
    gp.analysis.Union(['zoning_2020', 'zoning_2024'], 'zoning_union', 'ALL')
except gp.HonuaGpUnsupportedError as exc:
    print(f"expected_failure_union_zoning_layers caught {exc.function}")
    raise SystemExit(0) from exc
raise SystemExit("expected_failure_union_zoning_layers did not raise")
