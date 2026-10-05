#!/usr/bin/env bash
# Regenerate the FeatureService binding and its complete import closure.
# Canonical protocol: honua-io/geospatial-grpc v1.0.0 (the candidate server's pin).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDK_DIR="$(dirname "$SCRIPT_DIR")"
OUT_DIR="$SDK_DIR/packages/honua-sdk/honua_sdk/grpc/_generated"
PROTO_REVISION="0f701ecc6b0c41a5ea43e2dff3c46ce654312576"
PYTHON="${PYTHON:-python3}"

# Keep generated runtime requirements within honua-sdk[grpc]'s declared floor.
# Install into a development venv: pip install grpcio-tools==1.70.0
"$PYTHON" - <<'PY'
from importlib.metadata import version

if version("grpcio-tools") != "1.70.0":
    raise SystemExit("Generation requires grpcio-tools==1.70.0")
PY

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT
PROTO_ROOT="$WORK_DIR/source"
mkdir -p "$PROTO_ROOT"

# Optional local canonical checkout for offline generation. Always archive the
# pinned commit, never its working tree or a floating branch/sibling proto path.
if [[ $# -eq 1 ]]; then
  git -C "$1" archive "$PROTO_REVISION" geospatial | tar -x -C "$PROTO_ROOT"
elif [[ $# -eq 0 ]]; then
  git -C "$PROTO_ROOT" init -q
  git -C "$PROTO_ROOT" remote add origin https://github.com/honua-io/geospatial-grpc.git
  fetched=false
  for delay in 0 10 30 60 120; do
    sleep "$delay"
    if timeout 15s git -C "$PROTO_ROOT" fetch --depth=1 origin "$PROTO_REVISION"; then
      fetched=true
      break
    fi
  done
  "$fetched" || exit 1
  git -C "$PROTO_ROOT" checkout -q --detach FETCH_HEAD
else
  echo "Usage: $0 [geospatial-grpc-checkout]" >&2
  exit 2
fi

# Generate all FeatureService dependencies as well: shared types no longer live
# in feature_service.proto. Stage output before replacing the committed binding.
"$PYTHON" - "$PROTO_ROOT" "$WORK_DIR/generated" <<'PY'
import re
import sys
from pathlib import Path

from grpc_tools import protoc

root, output = map(Path, sys.argv[1:])
output.mkdir()
pending = ["geospatial/v1/feature_service.proto"]
protos = set()
while pending:
    proto = pending.pop()
    if proto in protos:
        continue
    protos.add(proto)
    pending.extend(re.findall(r'^import "([^"]+)";', (root / proto).read_text(), re.MULTILINE))

result = protoc.main([
    "grpc_tools.protoc", f"--proto_path={root}", f"--python_out={output}",
    f"--grpc_python_out={output}", f"--pyi_out={output}", *sorted(protos),
])
if result:
    raise SystemExit(result)
for path in output.rglob("*.py*"):
    text = path.read_text().replace(
        "from geospatial.v1 import", "from honua_sdk.grpc._generated.geospatial.v1 import",
    ).replace("'geospatial.v1.", "'honua_sdk.grpc._generated.geospatial.v1.")
    path.write_text(text)
for directory in (output / "geospatial", output / "geospatial/v1"):
    (directory / "__init__.py").touch()
PY

mkdir -p "$OUT_DIR"
rm -rf "$OUT_DIR/honua" "$OUT_DIR/geospatial"
cp -R "$WORK_DIR/generated/geospatial" "$OUT_DIR/"
echo "Generated geospatial.v1 FeatureService from $PROTO_REVISION (v1.0.0) in $OUT_DIR"
