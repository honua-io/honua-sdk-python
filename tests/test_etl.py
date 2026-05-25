from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from honua_sdk import (
    AsyncHonuaClient,
    HonuaClient,
    PipelineDefinition,
    PipelineExecution,
    PipelineExecutionError,
    SinkStage,
    SourceStage,
    TransformStage,
)
from honua_sdk.etl import TERMINAL_EXECUTION_STATUSES


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _definition() -> PipelineDefinition:
    return PipelineDefinition(
        name="roads-to-layer",
        description="reproject + load",
        stages=[
            SourceStage("geojson", {"path": "/data/roads.geojson"}),
            TransformStage("reproject", {"fromSrid": "4326", "toSrid": "3857"}),
            SinkStage("honua-layer", {"layer": "roads_3857"}),
        ],
    )


def _envelope(data: Any) -> dict[str, Any]:
    return {"success": True, "data": data, "message": None, "timestamp": "2026-05-25T00:00:00Z"}


def _definition_response(pipeline_id: str = "pl-1") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "id": pipeline_id,
        "name": "roads-to-layer",
        "description": "reproject + load",
        "version": 1,
        "stages": [
            {"kind": "source", "connector": {"type": "geojson", "options": {"path": "/data/roads.geojson"}}},
            {"kind": "transform", "transform": {"type": "reproject", "options": {"fromSrid": "4326", "toSrid": "3857"}}},
            {"kind": "sink", "connector": {"type": "honua-layer", "options": {"layer": "roads_3857"}}},
        ],
        "created_at": "2026-05-25T00:00:00Z",
        "updated_at": "2026-05-25T00:00:00Z",
        "advisories": ["external-postgis sink requires a native worker"],
    }


def _execution_response(status: str, execution_id: str = "ex-1", pipeline_id: str = "pl-1") -> dict[str, Any]:
    return {
        "id": execution_id,
        "pipeline_id": pipeline_id,
        "pipeline_version": 1,
        "execution_job_id": "job-xyz",
        "status": status,
        "is_dry_run": False,
        "features_read": 12,
        "features_written": 10,
        "features_quarantined": 2,
        "batch_id": "batch-1",
        "error_message": None if status != "Failed" else "sink rejected 2 features",
        "created_at": "2026-05-25T00:00:00Z",
        "completed_at": "2026-05-25T00:01:00Z" if status in TERMINAL_EXECUTION_STATUSES else None,
    }


def test_definition_to_request_models_stage_chain() -> None:
    body = _definition().to_request()
    assert body == {
        "schema_version": 1,
        "name": "roads-to-layer",
        "description": "reproject + load",
        "stages": [
            {"kind": "source", "connector": {"type": "geojson", "options": {"path": "/data/roads.geojson"}}},
            {"kind": "transform", "transform": {"type": "reproject", "options": {"fromSrid": "4326", "toSrid": "3857"}}},
            {"kind": "sink", "connector": {"type": "honua-layer", "options": {"layer": "roads_3857"}}},
        ],
    }


def test_create_pipeline_posts_definition_and_parses_envelope() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {
                "method": request.method,
                "path": request.url.raw_path.decode("ascii").split("?")[0],
                "body": json.loads(request.content) if request.content else None,
            }
        )
        return httpx.Response(201, json=_envelope(_definition_response()))

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        created = client.etl().create(_definition())

    assert seen[0]["method"] == "POST"
    assert seen[0]["path"] == "/api/v1.0/admin/geoetl/pipelines"
    assert seen[0]["body"]["name"] == "roads-to-layer"
    assert created.id == "pl-1"
    assert created.version == 1
    assert created.advisories == ("external-postgis sink requires a native worker",)
    assert [stage.kind for stage in created.stages] == ["source", "transform", "sink"]
    assert created.stages[0].connector is not None
    assert created.stages[0].connector.type == "geojson"
    assert created.stages[1].transform is not None
    assert created.stages[1].transform.type == "reproject"


def test_crud_paths() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append({"method": request.method, "path": path})
        if request.method == "DELETE":
            return httpx.Response(204)
        if path.endswith("/pipelines"):
            return httpx.Response(200, json=_envelope({"pipelines": [_definition_response()]}))
        return httpx.Response(200, json=_envelope(_definition_response()))

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        etl = client.etl()
        assert len(etl.list()) == 1
        assert etl.get("pl-1").id == "pl-1"
        assert etl.update("pl-1", _definition()).id == "pl-1"
        etl.delete("pl-1")

    assert [(e["method"], e["path"]) for e in seen] == [
        ("GET", "/api/v1.0/admin/geoetl/pipelines"),
        ("GET", "/api/v1.0/admin/geoetl/pipelines/pl-1"),
        ("PUT", "/api/v1.0/admin/geoetl/pipelines/pl-1"),
        ("DELETE", "/api/v1.0/admin/geoetl/pipelines/pl-1"),
    ]


def test_run_and_dry_run_post_to_expected_paths() -> None:
    seen: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append({"method": request.method, "path": path})
        return httpx.Response(202, json=_envelope(_execution_response("Pending")))

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        etl = client.etl()
        run = etl.run("pl-1")
        dry = etl.dry_run("pl-1")

    assert run.status == "Pending"
    assert run.execution_job_id == "job-xyz"
    assert dry.pipeline_id == "pl-1"
    assert [(e["method"], e["path"]) for e in seen] == [
        ("POST", "/api/v1.0/admin/geoetl/pipelines/pl-1/run"),
        ("POST", "/api/v1.0/admin/geoetl/pipelines/pl-1/dry-run"),
    ]


def test_run_to_completion_polls_to_terminal_status() -> None:
    state = {"polls": 0}
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append(path)
        if path.endswith("/run"):
            return httpx.Response(202, json=_envelope(_execution_response("Pending")))
        # execution status polls
        state["polls"] += 1
        status = "Running" if state["polls"] == 1 else "Succeeded"
        return httpx.Response(200, json=_envelope(_execution_response(status)))

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        terminal = client.etl().run_to_completion("pl-1", poll_interval=0.0)

    assert terminal.status == "Succeeded"
    assert terminal.succeeded
    assert terminal.features_written == 10
    assert seen == [
        "/api/v1.0/admin/geoetl/pipelines/pl-1/run",
        "/api/v1.0/admin/geoetl/pipelines/pl-1/executions/ex-1",
        "/api/v1.0/admin/geoetl/pipelines/pl-1/executions/ex-1",
    ]


def test_run_to_completion_raises_on_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode("ascii").split("?")[0]
        if path.endswith("/run"):
            return httpx.Response(202, json=_envelope(_execution_response("Pending")))
        return httpx.Response(200, json=_envelope(_execution_response("Failed")))

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PipelineExecutionError) as exc_info:
            client.etl().run_to_completion("pl-1", poll_interval=0.0)

    assert exc_info.value.execution.status == "Failed"
    assert "sink rejected" in str(exc_info.value)


def test_executions_list_and_get() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append(path)
        if path.endswith("/executions"):
            return httpx.Response(200, json=_envelope({"executions": [_execution_response("Succeeded")]}))
        return httpx.Response(200, json=_envelope(_execution_response("Succeeded")))

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        etl = client.etl()
        executions = etl.executions("pl-1")
        single = etl.execution("pl-1", "ex-1")

    assert len(executions) == 1
    assert isinstance(executions[0], PipelineExecution)
    assert single.id == "ex-1"
    assert seen == [
        "/api/v1.0/admin/geoetl/pipelines/pl-1/executions",
        "/api/v1.0/admin/geoetl/pipelines/pl-1/executions/ex-1",
    ]


def test_wait_times_out_when_execution_never_terminal() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_envelope(_execution_response("Running")))

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(TimeoutError):
            client.etl().wait("pl-1", "ex-1", poll_interval=0.0, timeout=0.05)


pytestmark = pytest.mark.anyio


async def test_async_create_and_run_to_completion() -> None:
    state = {"polls": 0}
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.raw_path.decode("ascii").split("?")[0]
        seen.append(path)
        if request.method == "POST" and path.endswith("/pipelines"):
            return httpx.Response(201, json=_envelope(_definition_response()))
        if path.endswith("/run"):
            return httpx.Response(202, json=_envelope(_execution_response("Pending")))
        state["polls"] += 1
        status = "Running" if state["polls"] == 1 else "Succeeded"
        return httpx.Response(200, json=_envelope(_execution_response(status)))

    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        etl = client.etl()
        created = await etl.create(_definition())
        terminal = await etl.run_to_completion(created.id, poll_interval=0.0)

    assert created.id == "pl-1"
    assert terminal.succeeded
    assert seen[0] == "/api/v1.0/admin/geoetl/pipelines"
    assert seen[1] == "/api/v1.0/admin/geoetl/pipelines/pl-1/run"
