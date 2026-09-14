"""GetCount over FeatureServer layer URLs with environment-only configuration (#205).

The licensed ArcPy parity probe set ``HONUA_BASE_URL``, imported the shim and
called ``GetCount`` on a live FeatureServer layer URL. The shim raised a
configuration error, and once configured it classified the URL as a
workspace-relative name and queried a nonexistent endpoint. These tests drive
the same sequence through the real ``honua_sdk.HonuaClient`` over an
``httpx.MockTransport`` that serves only the layer's query endpoint.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

import honua_gp

_API_KEY = "parity-key"
# honua-server's default Limits:Query:MaxRecordCount; pages are bounded by the
# SDK's requested resultRecordCount (1000), so the count spans two full pages.
_MAX_RECORD_COUNT = 10000
_LAYER_OIDS = list(range(101, 1335))
_EXPECTED_COUNT = 1234


class _FeatureServerLayer:
    def __init__(self, prefix: str) -> None:
        self.query_path = f"{prefix}/rest/services/test/FeatureServer/0/query"
        self.requests: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request.url.raw_path.decode().split("?", 1)[0])
        if request.headers.get("x-api-key") != _API_KEY:
            return httpx.Response(401, json={"error": {"code": 401, "message": "missing api key"}})
        if request.url.path != self.query_path:
            return httpx.Response(404, json={"error": {"code": 404, "message": "not found"}})
        params = {key: values[0] for key, values in parse_qs(request.url.query.decode()).items()}
        offset = int(params.get("resultOffset", "0"))
        requested = int(params.get("resultRecordCount", str(_MAX_RECORD_COUNT)))
        page = _LAYER_OIDS[offset : offset + min(requested, _MAX_RECORD_COUNT)]
        return httpx.Response(
            200,
            json={
                "objectIdFieldName": "OBJECTID",
                "features": [
                    {"attributes": {"OBJECTID": oid}, "geometry": {"x": -122.0, "y": 37.0}} for oid in page
                ],
                "exceededTransferLimit": offset + len(page) < len(_LAYER_OIDS),
            },
        )


@pytest.mark.parametrize("prefix", ["", "/gis"])
@pytest.mark.parametrize("form", ["full", "relative"])
def test_get_count_resolves_feature_server_url_from_environment(
    monkeypatch: pytest.MonkeyPatch, prefix: str, form: str
) -> None:
    base_url = f"https://localhost:28446{prefix}"
    layer = _FeatureServerLayer(prefix)
    monkeypatch.setenv("HONUA_BASE_URL", base_url)
    monkeypatch.setenv("HONUA_API_KEY", _API_KEY)
    # Only a transport is injected; base URL and credentials come from the env.
    honua_gp.configure(transport=httpx.MockTransport(layer))
    path = (
        f"{base_url}/rest/services/test/FeatureServer/0"
        if form == "full"
        else "rest/services/test/FeatureServer/0"
    )

    count = honua_gp.management.GetCount(path)

    assert count == _EXPECTED_COUNT
    assert layer.requests == [layer.query_path, layer.query_path]


def test_get_count_for_url_on_another_server_sends_no_request(monkeypatch: pytest.MonkeyPatch) -> None:
    layer = _FeatureServerLayer("")
    monkeypatch.setenv("HONUA_BASE_URL", "https://localhost:28446")
    monkeypatch.setenv("HONUA_API_KEY", _API_KEY)
    honua_gp.configure(transport=httpx.MockTransport(layer))

    with pytest.raises(honua_gp.HonuaGpResolveError, match="names the server"):
        honua_gp.management.GetCount("https://gis.example.com/rest/services/test/FeatureServer/0")

    assert layer.requests == []


def test_get_count_env_bootstrap_writes_one_audit_line(
    monkeypatch: pytest.MonkeyPatch, _isolated_audit_dir: Any
) -> None:
    layer = _FeatureServerLayer("")
    monkeypatch.setenv("HONUA_BASE_URL", "https://localhost:28446")
    monkeypatch.setenv("HONUA_API_KEY", _API_KEY)
    honua_gp.configure(transport=httpx.MockTransport(layer))

    assert honua_gp.management.GetCount("rest/services/test/FeatureServer/0") == _EXPECTED_COUNT

    lines = [line for path in _isolated_audit_dir.glob("*.jsonl") for line in path.read_text().splitlines()]
    assert len(lines) == 1
