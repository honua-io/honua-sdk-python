"""Tests for the Workflow authoring + publication clients.

Transport is mocked with :class:`httpx.MockTransport` (no live server/Docker),
mirroring the existing client tests. The wire shapes mirror the reconciled
honua-server ``/api/v1/console`` workflow contract: every successful
body is an ``ApiResponse<T>`` envelope (``{"success", "data", ...}``) and the
client unwraps the inner ``data`` payload.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from honua_sdk import AsyncHonuaClient, HonuaClient
from honua_sdk.workflow import (
    PUBLICATION_TARGET_PROCESS_ENDPOINT,
    PUBLICATION_TARGET_SCHEDULE,
    WORKFLOW_SCHEMA_VERSION,
    AsyncHonuaWorkflow,
    HonuaWorkflow,
)

# Fixtures

ROOT = "/api/v1/console"

GRAPH = {
    "schemaVersion": WORKFLOW_SCHEMA_VERSION,
    "nodes": [
        {"nodeId": "n1", "nodeTypeId": "geometry.buffer", "parameters": {"distance": "100"}},
    ],
    "edges": [],
}

PACKAGE = {
    "packageId": "pkg-1",
    "name": "Buffer flow",
    "graph": GRAPH,
    "latestVersion": 1,
    "createdAt": "2026-05-25T00:00:00Z",
    "updatedAt": "2026-05-25T00:00:00Z",
}

NODE_REGISTRY = {
    "registryVersion": "reg-7",
    "nodes": [{"nodeTypeId": "geometry.buffer", "runtimeKind": "Geoprocessing"}],
}


def _envelope(data: Any) -> dict[str, Any]:
    return {"success": True, "data": data, "message": None, "timestamp": "2026-05-25T00:00:00Z"}


# Node registry


def test_node_registry_and_node() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == f"{ROOT}/workflow-node-registry":
            return httpx.Response(200, json=_envelope(NODE_REGISTRY))
        if request.url.path == f"{ROOT}/workflow-node-registry/geometry.buffer":
            return httpx.Response(200, json=_envelope({"nodeTypeId": "geometry.buffer"}))
        raise AssertionError(f"unexpected {request.url.path}")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        wf = client.workflow()
        assert isinstance(wf, HonuaWorkflow)
        registry = wf.node_registry()
        node = wf.node("geometry.buffer")

    assert registry["registryVersion"] == "reg-7"
    assert node["nodeTypeId"] == "geometry.buffer"
    assert ("GET", f"{ROOT}/workflow-node-registry") in seen
    assert ("GET", f"{ROOT}/workflow-node-registry/geometry.buffer") in seen


# Draft CRUD


def test_list_and_get_draft() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == f"{ROOT}/workflow-packages":
            return httpx.Response(200, json=_envelope({"items": [PACKAGE]}))
        if request.url.path == f"{ROOT}/workflow-packages/pkg-1":
            return httpx.Response(200, json=_envelope(PACKAGE))
        raise AssertionError(f"unexpected {request.url.path}")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        wf = client.workflow()
        listing = wf.drafts()
        package = wf.draft("pkg-1")

    assert listing["items"][0]["packageId"] == "pkg-1"
    assert package["name"] == "Buffer flow"


def test_save_draft_posts_graph_body() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == f"{ROOT}/workflow-packages"
        captured.update(json.loads(request.content))
        return httpx.Response(201, json=_envelope(PACKAGE))

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        package = client.workflow().save_draft(
            "Buffer flow",
            GRAPH,
            namespace="analysis",
            metadata={"owner": "soleil"},
        )

    assert package["packageId"] == "pkg-1"
    assert captured["name"] == "Buffer flow"
    assert captured["graph"] == GRAPH
    assert captured["namespace"] == "analysis"
    assert captured["metadata"] == {"owner": "soleil"}
    # packageId omitted on create (no key) -> server assigns one.
    assert "packageId" not in captured


def test_update_draft_uses_put_and_route_id() -> None:
    captured: dict[str, Any] = {}
    seen_method = {"m": ""}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_method["m"] = request.method
        assert request.url.path == f"{ROOT}/workflow-packages/pkg-1"
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=_envelope(PACKAGE))

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        client.workflow().update_draft("pkg-1", "Buffer flow", GRAPH, description="updated")

    assert seen_method["m"] == "PUT"
    assert captured["packageId"] == "pkg-1"
    assert captured["description"] == "updated"


# Versions + lifecycle


def test_versions_list_create_get() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.method == "GET" and request.url.path == f"{ROOT}/workflow-packages/pkg-1/versions":
            return httpx.Response(200, json=_envelope({"items": [{"version": 1}]}))
        if request.method == "POST" and request.url.path == f"{ROOT}/workflow-packages/pkg-1/versions":
            return httpx.Response(201, json=_envelope({"version": 2, "packageId": "pkg-1"}))
        if request.url.path == f"{ROOT}/workflow-packages/pkg-1/versions/2":
            return httpx.Response(200, json=_envelope({"version": 2, "packageHash": "abc"}))
        raise AssertionError(f"unexpected {request.method} {request.url.path}")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        wf = client.workflow()
        versions = wf.versions("pkg-1")
        created = wf.create_version("pkg-1")
        version = wf.version("pkg-1", 2)

    assert versions["items"][0]["version"] == 1
    assert created["version"] == 2
    assert version["packageHash"] == "abc"
    assert ("POST", f"{ROOT}/workflow-packages/pkg-1/versions") in seen


def test_validate_and_dry_run_version() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"{ROOT}/workflow-packages/pkg-1/versions/1/validate":
            return httpx.Response(200, json=_envelope({"isValid": True, "issues": []}))
        if path == f"{ROOT}/workflow-packages/pkg-1/versions/1/dry-run":
            return httpx.Response(200, json=_envelope({"artifacts": [{"artifactId": "a1"}]}))
        raise AssertionError(f"unexpected {path}")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        wf = client.workflow()
        validation = wf.validate_version("pkg-1", 1)
        dry_run = wf.dry_run_version("pkg-1", 1)

    assert validation["isValid"] is True
    assert dry_run["artifacts"][0]["artifactId"] == "a1"


def test_publish_version_process_endpoint() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == f"{ROOT}/workflow-packages/pkg-1/versions/1/publish"
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=_envelope({"publicationId": "pub-1", "target": "ProcessEndpoint"}))

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        publication = client.workflow().publish_version(
            "pkg-1",
            1,
            target=PUBLICATION_TARGET_PROCESS_ENDPOINT,
            process_id="analysis.buffer-flow",
        )

    assert publication["publicationId"] == "pub-1"
    assert captured["target"] == "ProcessEndpoint"
    assert captured["processId"] == "analysis.buffer-flow"
    assert captured["enabled"] is True


def test_publish_version_schedule_carries_cron() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200, json=_envelope({"publicationId": "pub-2"}))

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        client.workflow().publish_version(
            "pkg-1",
            1,
            target=PUBLICATION_TARGET_SCHEDULE,
            schedule={"cronExpression": "0 * * * *", "timeZone": "UTC"},
            enabled=False,
        )

    assert captured["target"] == "Schedule"
    assert captured["schedule"]["cronExpression"] == "0 * * * *"
    assert captured["enabled"] is False


# Publications + runs


def test_publications_and_run() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path == f"{ROOT}/workflow-publications":
            return httpx.Response(200, json=_envelope({"items": [{"publicationId": "pub-1"}]}))
        if request.method == "POST" and path == f"{ROOT}/workflow-publications/pub-1/runs":
            captured.update(json.loads(request.content))
            return httpx.Response(
                201,
                json=_envelope({"publicationId": "pub-1", "jobId": "job-42", "workflowRunId": None}),
            )
        raise AssertionError(f"unexpected {request.method} {path}")

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        wf = client.workflow()
        publications = wf.publications()
        result = wf.run("pub-1", idempotency_key="idem-1", parameters={"region": "west"})

    assert publications["items"][0]["publicationId"] == "pub-1"
    assert result["jobId"] == "job-42"
    assert captured["idempotencyKey"] == "idem-1"
    assert captured["parameters"] == {"region": "west"}


def test_run_with_no_body_args_sends_empty_body() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content) if request.content else {"__empty__": True})
        return httpx.Response(201, json=_envelope({"publicationId": "pub-1", "workflowRunId": "run-9"}))

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        result = client.workflow().run("pub-1")

    assert result["workflowRunId"] == "run-9"
    # No idempotency key / parameters -> empty JSON body object.
    assert captured == {}


# Envelope unwrapping edge cases


def test_unwrap_passthrough_when_no_envelope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Server returned a bare payload (no ``data`` key) -> returned as-is.
        return httpx.Response(200, json={"registryVersion": "reg-bare"})

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        registry = client.workflow().node_registry()

    assert registry == {"registryVersion": "reg-bare"}


def test_unwrap_scalar_data_wrapped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_envelope("just-a-string"))

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        result = client.workflow().node("x")

    assert result == {"data": "just-a-string"}


# Async parity


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_async_authoring_roundtrip() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        path = request.url.path
        if path == f"{ROOT}/workflow-node-registry":
            return httpx.Response(200, json=_envelope(NODE_REGISTRY))
        if request.method == "POST" and path == f"{ROOT}/workflow-packages":
            return httpx.Response(201, json=_envelope(PACKAGE))
        if request.method == "POST" and path == f"{ROOT}/workflow-packages/pkg-1/versions":
            return httpx.Response(201, json=_envelope({"version": 1}))
        if path == f"{ROOT}/workflow-packages/pkg-1/versions/1/publish":
            return httpx.Response(200, json=_envelope({"publicationId": "pub-1"}))
        if path == f"{ROOT}/workflow-publications/pub-1/runs":
            return httpx.Response(201, json=_envelope({"jobId": "job-1"}))
        raise AssertionError(f"unexpected {request.method} {path}")

    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        wf = client.workflow()
        assert isinstance(wf, AsyncHonuaWorkflow)
        registry = await wf.node_registry()
        package = await wf.save_draft("Buffer flow", GRAPH)
        version = await wf.create_version("pkg-1")
        publication = await wf.publish_version(
            "pkg-1", 1, target=PUBLICATION_TARGET_PROCESS_ENDPOINT, process_id="analysis.buffer-flow"
        )
        run = await wf.run("pub-1")

    assert registry["registryVersion"] == "reg-7"
    assert package["packageId"] == "pkg-1"
    assert version["version"] == 1
    assert publication["publicationId"] == "pub-1"
    assert run["jobId"] == "job-1"


@pytest.mark.anyio
async def test_async_drafts_versions_validation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == f"{ROOT}/workflow-packages":
            return httpx.Response(200, json=_envelope({"items": [PACKAGE]}))
        if path == f"{ROOT}/workflow-packages/pkg-1":
            return httpx.Response(200, json=_envelope(PACKAGE))
        if path == f"{ROOT}/workflow-packages/pkg-1/versions":
            return httpx.Response(200, json=_envelope({"items": [{"version": 1}]}))
        if path == f"{ROOT}/workflow-packages/pkg-1/versions/1":
            return httpx.Response(200, json=_envelope({"version": 1}))
        if path == f"{ROOT}/workflow-packages/pkg-1/versions/1/validate":
            return httpx.Response(200, json=_envelope({"isValid": False}))
        if path == f"{ROOT}/workflow-packages/pkg-1/versions/1/dry-run":
            return httpx.Response(200, json=_envelope({"artifacts": []}))
        if path == f"{ROOT}/workflow-publications":
            return httpx.Response(200, json=_envelope({"items": []}))
        if path == f"{ROOT}/workflow-node-registry/geometry.buffer":
            return httpx.Response(200, json=_envelope({"nodeTypeId": "geometry.buffer"}))
        if path == f"{ROOT}/workflow-packages/pkg-1" and request.method == "PUT":
            return httpx.Response(200, json=_envelope(PACKAGE))
        raise AssertionError(f"unexpected {request.method} {path}")

    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        wf = client.workflow()
        assert (await wf.drafts())["items"][0]["packageId"] == "pkg-1"
        assert (await wf.draft("pkg-1"))["name"] == "Buffer flow"
        assert (await wf.node("geometry.buffer"))["nodeTypeId"] == "geometry.buffer"
        assert (await wf.versions("pkg-1"))["items"][0]["version"] == 1
        assert (await wf.version("pkg-1", 1))["version"] == 1
        assert (await wf.validate_version("pkg-1", 1))["isValid"] is False
        assert (await wf.dry_run_version("pkg-1", 1))["artifacts"] == []
        assert (await wf.publications())["items"] == []
        assert (await wf.update_draft("pkg-1", "Buffer flow", GRAPH))["packageId"] == "pkg-1"


# Deprecated aliases


def _draft_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path.endswith("/versions"):
        return httpx.Response(200, json=_envelope({"items": [{"version": 1}]}))
    if request.url.path.startswith(f"{ROOT}/workflow-packages"):
        return httpx.Response(200, json=_envelope(PACKAGE))
    raise AssertionError(f"unexpected {request.url.path}")


def test_deprecated_draft_aliases_warn_and_delegate() -> None:
    with HonuaClient("http://example.test", transport=httpx.MockTransport(_draft_handler)) as client:
        wf = client.workflow()
        with pytest.deprecated_call(match=r"packages\(\) is deprecated; use drafts\(\)"):
            assert wf.packages()["packageId"] == "pkg-1"
        with pytest.deprecated_call(match=r"package\(\) is deprecated; use draft\(\)"):
            assert wf.package("pkg-1")["name"] == "Buffer flow"
        with pytest.deprecated_call(match=r"save_package\(\)"):
            assert wf.save_package("Buffer flow", GRAPH, package_id="pkg-1")["packageId"] == "pkg-1"
        with pytest.deprecated_call(match=r"update_package\(\)"):
            assert wf.update_package("pkg-1", "Buffer flow", GRAPH)["packageId"] == "pkg-1"
        with pytest.deprecated_call(match=r"package_id= is deprecated; use workflow_id="):
            assert wf.versions(package_id="pkg-1")["items"] == [{"version": 1}]


@pytest.mark.anyio
async def test_async_deprecated_draft_aliases_warn_and_delegate() -> None:
    async with AsyncHonuaClient("http://example.test", transport=httpx.MockTransport(_draft_handler)) as client:
        wf = client.workflow()
        with pytest.deprecated_call(match=r"packages\(\)"):
            assert (await wf.packages())["packageId"] == "pkg-1"
        with pytest.deprecated_call(match=r"package\(\)"):
            assert (await wf.package("pkg-1"))["name"] == "Buffer flow"
        with pytest.deprecated_call(match=r"save_package\(\)"):
            assert (await wf.save_package("Buffer flow", GRAPH))["packageId"] == "pkg-1"
        with pytest.deprecated_call(match=r"update_package\(\)"):
            assert (await wf.update_package("pkg-1", "Buffer flow", GRAPH))["packageId"] == "pkg-1"
        with pytest.deprecated_call(match=r"package_id="):
            assert (await wf.versions(package_id="pkg-1"))["items"] == [{"version": 1}]


def test_deprecated_schema_version_constant_warns() -> None:
    import honua_sdk.workflow as workflow_module

    with pytest.deprecated_call(match="WORKFLOW_PACKAGE_SCHEMA_VERSION is deprecated"):
        assert workflow_module.WORKFLOW_PACKAGE_SCHEMA_VERSION == WORKFLOW_SCHEMA_VERSION
    with pytest.raises(AttributeError):
        _ = workflow_module.NOT_A_CONSTANT


def test_async_versions_stays_a_coroutine_function() -> None:
    import inspect

    assert inspect.iscoroutinefunction(AsyncHonuaWorkflow.versions)
    assert inspect.iscoroutinefunction(AsyncHonuaWorkflow.publish_version)


def test_package_id_and_workflow_id_together_are_rejected() -> None:
    with HonuaClient("http://example.test", transport=httpx.MockTransport(_draft_handler)) as client:
        with pytest.raises(TypeError, match="not both"):
            client.workflow().versions(package_id="a", workflow_id="b")  # type: ignore[call-arg]
