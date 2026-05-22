"""Expected-failure script exercising management.CreateTable."""

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

arcpy.env.workspace = "honua://services/legacy"
arcpy.env.overwriteOutput = True

try:
    arcpy.management.CreateTable('honua://services/transport', 'new_table')
except arcpy.HonuaArcpyUnsupportedError as exc:
    print(f"expected_failure_create_table caught {exc.function}")
    raise SystemExit(0) from exc
raise SystemExit("expected_failure_create_table did not raise")
