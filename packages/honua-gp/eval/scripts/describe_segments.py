"""Describe a feature layer's schema."""

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
for path in (PACKAGE_ROOT, PACKAGE_ROOT.parent.parent / "packages" / "honua-sdk", PACKAGE_ROOT.parent.parent / "packages" / "honua-admin"):
    candidate = str(path)
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

from eval._emit import emit_response, schema_fingerprint
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

desc = gp.Describe("segments")
srid = desc.spatialReference.factoryCode if desc.spatialReference else None
emit_response(
    "describe_segments",
    schema_fingerprint(desc.fields, shape_type=desc.shapeType, oid_field=desc.OIDFieldName, srid=srid),
)
print(
    f"describe_segments ok shapeType={desc.shapeType} "
    f"fields={len(desc.fields)} oidField={desc.OIDFieldName} srid={srid}"
)
