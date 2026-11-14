"""Native edits exercise the versioned RPC over a real local gRPC channel."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import grpc
import pytest

from honua_sdk import CallableAuthProvider, HonuaGrpcError
from honua_sdk.grpc import ApplyEditsRequest, Feature, HonuaGrpcAsyncClient, HonuaGrpcClient
from honua_sdk.grpc._generated.geospatial.v1 import feature_service_pb2 as pb2
from honua_sdk.grpc._generated.geospatial.v1 import feature_service_pb2_grpc as service


@pytest.fixture
def native_server():
    requests = []
    response = pb2.ApplyEditsResponse()

    class Edits(service.FeatureServiceServicer):
        def ApplyEdits(self, request, context):
            requests.append((request, dict(context.invocation_metadata())))
            if request.service_id in {"UNIMPLEMENTED", "UNAUTHENTICATED", "CANCELLED", "DEADLINE_EXCEEDED"}:
                context.set_trailing_metadata((("x-correlation-id", "edit-request"),))
                context.abort(grpc.StatusCode[request.service_id], "edits unavailable")
            return response

    server = grpc.server(ThreadPoolExecutor(max_workers=2))
    service.add_FeatureServiceServicer_to_server(Edits(), server)
    port = server.add_insecure_port("127.0.0.1:0")
    server.start()
    try:
        yield f"127.0.0.1:{port}", requests, response
    finally:
        server.stop(0).wait()


def edit_request():
    return ApplyEditsRequest(
        service_id="parks", layer_id=3,
        adds=[Feature(attributes={"name": "park", "n": 2**40, "yes": True, "nil": None, "area": 1.5},
                      geometry={"x": 1.0, "y": 2.0})],
        updates=[Feature(id=42, attributes={"name": "updated"})], deletes=[43],
        rollback_on_failure=True, force_write=True, idempotency_key="stable-key",
    )


@pytest.mark.parametrize("asynchronous", [False, True])
def test_native_edits_preserve_wire_and_results(native_server, asynchronous):
    target, requests, response = native_server
    response.add_results.add(object_id=41, success=True)
    failed = response.update_results.add(object_id=42, success=False)
    failed.error.code = 409
    failed.error.message = "conflict"
    failed.error.details["field"] = "name"
    failed.error.remedy = "refresh"
    response.delete_results.add(object_id=43, success=True)
    response.error.code = 409
    response.error.message = "rolled back"
    tokens = iter(["first", "renewed"])
    provider = CallableAuthProvider(lambda: {"authorization": next(tokens)})

    async def run_async():
        async with HonuaGrpcAsyncClient(target, insecure=True, auth_provider=provider) as client:
            result = await client.apply_edits(edit_request())
            await client.apply_edits(edit_request())
            return result

    with patch("httpx.Client.request", side_effect=AssertionError("REST fallback")), patch(
        "httpx.AsyncClient.request", side_effect=AssertionError("REST fallback")
    ):
        if asynchronous:
            result = asyncio.run(run_async())
        else:
            with HonuaGrpcClient(target, insecure=True, auth_provider=provider) as client:
                result = client.apply_edits(edit_request())
                client.apply_edits(edit_request())
    request, metadata = requests[0]
    assert request.service_id == "parks" and request.layer_id == 3
    assert request.adds[0].attributes["n"].int64_value == 2**40
    assert request.adds[0].attributes["yes"].bool_value
    assert request.adds[0].attributes["nil"].WhichOneof("value") == "null_value"
    assert request.adds[0].geometry.point.x == 1.0
    assert request.updates[0].id == 42 and list(request.deletes) == [43]
    assert request.rollback_on_failure and request.force_write
    assert request.idempotency_key == "stable-key"
    assert metadata["authorization"] == "first"
    assert requests[1][1]["authorization"] == "renewed"
    assert result.add_results[0].success and result.delete_results[0].object_id == 43
    assert not result.update_results[0].success
    assert result.update_results[0].error.code == 409
    assert result.update_results[0].error.details == {"field": "name"}
    assert result.update_results[0].error.remedy == "refresh"
    assert result.error.message == "rolled back"


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("status", ["UNIMPLEMENTED", "UNAUTHENTICATED", "CANCELLED", "DEADLINE_EXCEEDED"])
def test_rpc_errors_fail_explicitly(native_server, asynchronous, status):
    target, _, _ = native_server
    request = ApplyEditsRequest(service_id=status)

    async def run_async():
        async with HonuaGrpcAsyncClient(target, insecure=True) as client:
            await client.apply_edits(request)

    with pytest.raises(HonuaGrpcError) as error:
        if asynchronous:
            asyncio.run(run_async())
        else:
            with HonuaGrpcClient(target, insecure=True) as client:
                client.apply_edits(request)
    assert error.value.code == grpc.StatusCode[status]
    assert error.value.correlation_id == "edit-request"


@pytest.mark.parametrize("cancel_task", [True, False])
def test_async_cancellation_reaches_native_rpc(cancel_task):
    async def run():
        started = asyncio.Event()
        cancelled = asyncio.Event()

        class PendingEdits(service.FeatureServiceServicer):
            async def ApplyEdits(self, request, context):
                started.set()
                try:
                    await asyncio.Future()
                finally:
                    cancelled.set()

        server = grpc.aio.server()
        service.add_FeatureServiceServicer_to_server(PendingEdits(), server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        try:
            async with HonuaGrpcAsyncClient(
                f"127.0.0.1:{port}", insecure=True, timeout=5 if cancel_task else 0.1,
            ) as client:
                task = asyncio.create_task(client.apply_edits(edit_request()))
                await asyncio.wait_for(started.wait(), timeout=3)
                if cancel_task:
                    task.cancel()
                    with pytest.raises(asyncio.CancelledError):
                        await task
                else:
                    with pytest.raises(HonuaGrpcError) as error:
                        await task
                    assert error.value.code == grpc.StatusCode.DEADLINE_EXCEEDED
                await asyncio.wait_for(cancelled.wait(), timeout=3)
        finally:
            await server.stop(0)

    asyncio.run(run())


def test_partial_results_and_attribute_validation(native_server):
    target, requests, response = native_server
    response.add_results.add(object_id=41, success=True)
    response.delete_results.add(object_id=43, success=False).error.message = "missing"
    with HonuaGrpcClient(target, insecure=True) as client:
        request = ApplyEditsRequest(
            service_id="parks", adds=[Feature(attributes={"bytes": b"abc"})],
            deletes=[43], rollback_on_failure=False,
        )
        result = client.apply_edits(request)
        assert result.error is None
        assert result.add_results[0].error is None
        assert result.delete_results[0].error.message == "missing"
        assert not requests[0][0].rollback_on_failure
        assert requests[0][0].adds[0].attributes["bytes"].bytes_value == b"abc"
        request.adds[0].attributes["invalid"] = [1, 2]
        with pytest.raises(TypeError, match="Unsupported native edit attribute type"):
            client.apply_edits(request)
        assert len(requests) == 1


@pytest.mark.parametrize("geometry", [
    {"x": 1, "y": 2, "spatialReference": {"wkid": 4326}},
    {"type": "Point", "coordinates": [1, 2]},
])
def test_unrepresentable_geometry_never_sends_edits(native_server, geometry):
    target, requests, _ = native_server
    with HonuaGrpcClient(target, insecure=True) as client:
        with pytest.raises(ValueError, match="native edit geometry"):
            client.apply_edits(ApplyEditsRequest(adds=[Feature(geometry=geometry)]))
    assert not requests
