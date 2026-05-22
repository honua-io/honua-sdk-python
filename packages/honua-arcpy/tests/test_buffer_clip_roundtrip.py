"""End-to-end exercise of the example script against a mock honua-server.

This proves the AC line item: "At least one end-to-end script demo in
``examples/`` showing arcpy -> honua_arcpy parity."
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

import honua_arcpy


@pytest.fixture
def mock_honua_client(monkeypatch: pytest.MonkeyPatch) -> tuple[list[httpx.Request], honua_arcpy.HonuaSession]:
    from honua_sdk import HonuaClient

    captured: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        path = request.url.path
        if path.startswith("/ogc/processes/processes/") and path.endswith("/execution"):
            process_id = path.split("/")[-2]
            return httpx.Response(
                200,
                json={
                    "processID": process_id,
                    "status": "successful",
                    "outputs": json.loads(request.content.decode("utf-8")).get("outputs", {}),
                },
            )
        return httpx.Response(404, json={"error": "not mocked"})

    client = HonuaClient("http://example.test", transport=httpx.MockTransport(_handler))
    honua_arcpy.configure(client=client)
    return captured, honua_arcpy.get_session()


def test_buffer_clip_pipeline_dispatches_two_processes(
    mock_honua_client: tuple[list[httpx.Request], honua_arcpy.HonuaSession],
) -> None:
    captured, _session = mock_honua_client

    honua_arcpy.env.workspace = "honua://services/transport"
    honua_arcpy.env.overwriteOutput = True

    honua_arcpy.analysis.Buffer(
        "roads", "roads_buffer", "25 Meters", dissolve_option="ALL"
    )
    honua_arcpy.analysis.Clip("roads_buffer", "study_area", "roads_clip")

    paths = [req.url.path for req in captured]
    assert paths == [
        "/ogc/processes/processes/geometry.buffer/execution",
        "/ogc/processes/processes/geometry.clip/execution",
    ]

    buffer_body = json.loads(captured[0].content.decode("utf-8"))
    assert buffer_body["inputs"] == {
        "input_features": "roads",
        "distance": "25 Meters",
        "dissolve_option": "ALL",
    }
    assert buffer_body["outputs"] == {"result": "roads_buffer"}
    assert buffer_body["metadata"]["honuaArcpy"]["workspace"] == "honua://services/transport"

    clip_body = json.loads(captured[1].content.decode("utf-8"))
    assert clip_body["inputs"] == {
        "input_features": "roads_buffer",
        "clip_features": "study_area",
    }
    assert clip_body["outputs"] == {"result": "roads_clip"}
