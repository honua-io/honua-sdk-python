"""Installed-package proof for #205.

Builds non-editable installs of honua-sdk, honua-admin and honua-gp into a
throwaway directory, then runs a consumer script in a separate interpreter,
outside the repository, configured ONLY through the documented environment
variables. The consumer calls ``GetCount`` first thing after import, with the
full FeatureServer layer URL and with the relative ``rest/services`` path, against
a real HTTP server that answers only that layer's query endpoint.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PACKAGES = ("honua-sdk", "honua-admin", "honua-gp")
_API_KEY = "installed-consumer-key"
# honua-server's default Limits:Query:MaxRecordCount.
_MAX_RECORD_COUNT = 10000
_LAYER_OIDS = list(range(1, 10))
# Nine features, the count real ArcPy returned for the licensed probe layer.
_EXPECTED_COUNT = 9

_CONSUMER = """
import json
import os
import sys

import honua_gp as arcpy

base = os.environ["HONUA_BASE_URL"]
full = base + "/rest/services/test/FeatureServer/0"
relative = "rest/services/test/FeatureServer/0"
full_count = arcpy.management.GetCount(full)
relative_count = arcpy.management.GetCount(relative)

from honua_gp._resolve import resolve

print(json.dumps({
    "modules": {name: sys.modules[name].__file__ for name in ("honua_gp", "honua_sdk", "honua_admin")},
    "full": {"count": int(full_count), "resolved": resolve(full).to_dict()},
    "relative": {"count": int(relative_count), "resolved": resolve(relative).to_dict()},
}))
"""


@pytest.fixture(scope="module")
def installed_site(tmp_path_factory: pytest.TempPathFactory) -> Path:
    target = tmp_path_factory.mktemp("installed-site")
    command = [sys.executable, "-m", "pip", "install", "--quiet", "--no-deps", "--target", str(target)]
    if importlib.util.find_spec("hatchling") is not None:
        # Build offline with the interpreter's own backend when it has one.
        command += ["--no-build-isolation", "--no-index"]
    command += [str(_REPO_ROOT / "packages" / name) for name in _PACKAGES]
    proc = subprocess.run(command, capture_output=True, text=True, timeout=600, check=False)
    if proc.returncode != 0:
        pytest.fail(f"pip install of the built packages failed:\n{proc.stdout}\n{proc.stderr}")
    return target


class _LayerServer(ThreadingHTTPServer):
    prefix: str
    requests: list[tuple[str, str | None]]


class _LayerHandler(BaseHTTPRequestHandler):
    server: _LayerServer

    def do_GET(self) -> None:
        split = urlsplit(self.path)
        self.server.requests.append((split.path, self.headers.get("X-API-Key")))
        if self.headers.get("X-API-Key") != _API_KEY:
            self._send(401, {"error": {"code": 401, "message": "missing api key"}})
            return
        if split.path != f"{self.server.prefix}/rest/services/test/FeatureServer/0/query":
            self._send(404, {"error": {"code": 404, "message": "not found"}})
            return
        params = {key: values[0] for key, values in parse_qs(split.query).items()}
        offset = int(params.get("resultOffset", "0"))
        requested = int(params.get("resultRecordCount", str(_MAX_RECORD_COUNT)))
        page = _LAYER_OIDS[offset : offset + min(requested, _MAX_RECORD_COUNT)]
        self._send(
            200,
            {
                "objectIdFieldName": "OBJECTID",
                "features": [{"attributes": {"OBJECTID": oid}, "geometry": {"x": 1.0, "y": 2.0}} for oid in page],
                "exceededTransferLimit": offset + len(page) < len(_LAYER_OIDS),
            },
        )

    def _send(self, status: int, body: dict[str, object]) -> None:
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002 -- BaseHTTPRequestHandler signature
        return


@pytest.fixture(params=["", "/gis"], ids=["root", "path-prefix"])
def layer_server(request: pytest.FixtureRequest) -> Iterator[_LayerServer]:
    server = _LayerServer(("127.0.0.1", 0), _LayerHandler)
    server.prefix = request.param
    server.requests = []
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()


def test_installed_get_count_uses_environment_and_feature_server_urls(
    installed_site: Path, layer_server: _LayerServer, tmp_path: Path
) -> None:
    host, port = layer_server.server_address[:2]
    base_url = f"http://{host}:{port}{layer_server.prefix}"
    env = {key: value for key, value in os.environ.items() if not key.startswith("HONUA_")}
    env.pop("PYTHONHOME", None)
    env.update(
        {
            "PYTHONPATH": str(installed_site),
            "HONUA_BASE_URL": base_url,
            "HONUA_API_KEY": _API_KEY,
            "HONUA_GP_AUDIT_DIR": str(tmp_path / "audit"),
            "NO_PROXY": "*",
        }
    )

    proc = subprocess.run(
        [sys.executable, "-c", _CONSUMER],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert proc.returncode == 0, f"consumer failed:\n{proc.stdout}\n{proc.stderr}"
    report = json.loads(proc.stdout.strip().splitlines()[-1])
    for name, module_file in report["modules"].items():
        assert Path(module_file).resolve().is_relative_to(installed_site.resolve()), (name, module_file)
    assert report["full"]["count"] == _EXPECTED_COUNT
    assert report["relative"]["count"] == _EXPECTED_COUNT
    assert report["full"]["resolved"]["source"] == "honua://services/test/0"
    assert report["full"]["resolved"]["kind"] == "honua-uri"
    assert report["full"]["resolved"]["server_url"] == base_url
    assert report["relative"]["resolved"]["source"] == "honua://services/test/0"
    assert report["relative"]["resolved"]["server_url"] is None
    query_path = f"{layer_server.prefix}/rest/services/test/FeatureServer/0/query"
    # One page per GetCount, each on the layer endpoint with the key from HONUA_API_KEY.
    assert layer_server.requests == [(query_path, _API_KEY)] * 2
