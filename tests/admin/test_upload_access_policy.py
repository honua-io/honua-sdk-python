"""Wire-contract tests for admin uploads and access-policy updates."""

from __future__ import annotations

import asyncio
import io
import json
from email import policy
from email.parser import BytesParser
from typing import Any

import httpx
import pytest

from honua_admin import AsyncHonuaAdminClient, BackgroundImportResponse, HonuaAdminClient, ImportResult
from honua_sdk import CallableAuthProvider
from honua_sdk.errors import HonuaAuthError, HonuaHttpError, HonuaTimeoutError
from honua_sdk.http import AsyncRetryTransport, RetryTransport

from .conftest import make_api_response

FILE_BYTES = b'{"type":"FeatureCollection","features":[]}\r\n\x00\xff'
IMPORT_RESULT = {
    "success": True,
    "tableName": "points",
    "physicalTableName": "imported_points",
    "schema": "honua_data",
    "featureCount": 2,
    "format": 0,
    "detectedSrid": 4326,
    "duration": "00:00:00.0010000",
    "warnings": ["repaired geometry"],
    "repairedGeometryCount": 1,
}
SETTINGS = {
    "serviceName": "default",
    "enabledProtocols": ["FeatureServer"],
    "availableProtocols": ["FeatureServer", "MapServer"],
    "accessPolicy": {
        "allowAnonymous": True,
        "allowAnonymousWrite": False,
        "allowedRoles": ["reader"],
        "allowedWriteRoles": [],
    },
}
UPLOAD_ARGS = {"filename": "points.geojson", "table_name": "points"}


def invoke(
    asynchronous: bool,
    method: str,
    handler: Any,
    argument: Any,
    *,
    request_options: dict[str, Any] | None = None,
    client_options: dict[str, Any] | None = None,
    clone_options: dict[str, Any] | None = None,
    retry_post: bool = False,
) -> Any:
    """Exercise the public API with real httpx construction in both clients."""
    options = dict(client_options or {})
    transport = options.pop("transport", httpx.MockTransport(handler))
    request_options = request_options or {}

    async def async_call() -> Any:
        if retry_post:
            async with httpx.AsyncClient(
                base_url="https://test.honua.io/prefix/",
                transport=AsyncRetryTransport(
                    transport, retry_methods=frozenset({"POST"}), max_retries=1, backoff_initial=0, jitter=False
                ),
            ) as external:
                async with AsyncHonuaAdminClient("https://ignored.invalid", client=external) as admin:
                    return await getattr(admin, method)(argument, **request_options)
        async with AsyncHonuaAdminClient("https://test.honua.io/prefix/", transport=transport, **options) as admin:
            clone = admin.with_options(**clone_options) if clone_options else admin
            return await getattr(clone, method)(argument, **request_options)

    if asynchronous:
        return asyncio.run(async_call())
    if retry_post:
        with httpx.Client(
            base_url="https://test.honua.io/prefix/",
            transport=RetryTransport(
                transport, retry_methods=frozenset({"POST"}), max_retries=1, backoff_initial=0, jitter=False
            ),
        ) as external, HonuaAdminClient("https://ignored.invalid", client=external) as admin:
            return getattr(admin, method)(argument, **request_options)
    with HonuaAdminClient("https://test.honua.io/prefix/", transport=transport, **options) as admin:
        clone = admin.with_options(**clone_options) if clone_options else admin
        return getattr(clone, method)(argument, **request_options)


def multipart_parts(request: httpx.Request) -> dict[str, Any]:
    """Parse MIME parts using the emitted Content-Type, including its boundary."""
    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + request.headers["Content-Type"].encode("ascii") + b"\r\n\r\n" + request.content
    )
    assert message.get_content_type() == "multipart/form-data"
    assert message.get_boundary()
    assert message.is_multipart()
    assert not message.defects
    parts = list(message.iter_parts())
    assert len(parts) == 2
    assert all(part.get_content_disposition() == "form-data" and not part.defects for part in parts)
    assert int(request.headers["Content-Length"]) == len(request.content)
    return {part.get_param("name", header="Content-Disposition"): part for part in parts}


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("envelope", [False, True])
def test_upload_multipart_and_completed_response(asynchronous: bool, stream: bool, envelope: bool) -> None:
    source = io.BytesIO(b"skip" + FILE_BYTES) if stream else FILE_BYTES
    if stream:
        source.seek(4)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.raw_path == b"/prefix/api/v1/admin/import/upload"
        parts = multipart_parts(request)
        assert set(parts) == {"file", "TableName"}
        assert parts["file"].get_filename() == "points.geojson"
        assert parts["file"].get_content_type() == "application/geo+json"
        assert parts["file"].get_payload(decode=True) == FILE_BYTES
        assert parts["TableName"].get_payload(decode=True) == b"points"
        assert "Idempotency-Key" not in request.headers
        return httpx.Response(200, json=make_api_response(IMPORT_RESULT) if envelope else IMPORT_RESULT)

    result = invoke(
        asynchronous, "upload_file", handler, source,
        request_options={**UPLOAD_ARGS, "content_type": "application/geo+json"},
    )
    assert isinstance(result, ImportResult)
    assert result.success and result.feature_count == 2
    assert (result.table_name, result.schema, result.physical_table_name) == ("points", "honua_data", "imported_points")
    assert result.detected_srid == 4326 and result.format == 0
    assert result.repaired_geometry_count == 1 and result.warnings == ["repaired geometry"]
    assert result.duration == "00:00:00.0010000"
    if stream:
        assert not source.closed
        assert source.tell() == len(b"skip" + FILE_BYTES)


@pytest.mark.parametrize("asynchronous", [False, True])
def test_upload_background_response(asynchronous: bool) -> None:
    payload = {
        "jobId": "job-1", "message": "File queued for background processing",
        "statusUrl": "/api/v1/admin/import/jobs/job-1", "cancelUrl": "/api/v1/admin/import/jobs/job-1/cancel",
        "uploadId": "upload-1", "operationInstanceId": "op-1", "correlationId": "correlation-1",
        "auditId": "audit-1", "proposalId": "proposal-1",
    }
    result = invoke(
        asynchronous, "upload_file", lambda _: httpx.Response(202, json=payload), FILE_BYTES,
        request_options=UPLOAD_ARGS,
    )
    assert isinstance(result, BackgroundImportResponse)
    assert result.job_id == "job-1" and result.status_url == payload["statusUrl"]
    assert result.cancel_url == payload["cancelUrl"] and result.upload_id == "upload-1"
    assert result.operation_instance_id == "op-1" and result.correlation_id == "correlation-1"
    assert result.audit_id == "audit-1" and result.proposal_id == "proposal-1"


@pytest.mark.parametrize("asynchronous", [False, True])
def test_upload_dataset_validation_failure(asynchronous: bool) -> None:
    payload = {
        "success": False, "tableName": "points", "format": "GeoJson", "errorCode": "import.empty_dataset",
        "errorMessage": "No features", "validationErrors": [{"code": "import.empty_dataset", "message": "No features"}],
    }
    result = invoke(
        asynchronous, "upload_file", lambda _: httpx.Response(200, json=payload), FILE_BYTES,
        request_options=UPLOAD_ARGS,
    )
    assert isinstance(result, ImportResult) and not result.success
    assert result.error_code == "import.empty_dataset" and result.error_message == "No features"
    assert result.validation_errors == payload["validationErrors"]
    assert result.feature_count == 0 and result.warnings == []


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("updates,expected", [
    ({"allow_anonymous": True}, {"allowAnonymous": True}),
    ({"allow_anonymous": False, "allow_anonymous_write": False, "allowed_roles": [], "allowed_write_roles": ["editor"]},
     {"allowAnonymous": False, "allowAnonymousWrite": False, "allowedRoles": [], "allowedWriteRoles": ["editor"]}),
    ({"allow_anonymous": None, "allowed_roles": None}, {}),
])
def test_access_policy_body_path_and_response(asynchronous: bool, updates: dict[str, Any], expected: dict[str, Any]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert request.url.raw_path == b"/prefix/api/v1/admin/services/caf%C3%A9%2Fpublic%3F%23%25%20layer/access-policy"
        assert not request.url.query
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == expected
        return httpx.Response(200, json=make_api_response(SETTINGS))

    result = invoke(asynchronous, "update_access_policy", handler, "café/public?#% layer", request_options=updates)
    assert result.service_name == "default"
    assert result.access_policy.allow_anonymous and not result.access_policy.allow_anonymous_write
    assert result.access_policy.allowed_roles == ["reader"] and result.access_policy.allowed_write_roles == []


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("method", ["upload_file", "update_access_policy"])
@pytest.mark.parametrize("api_key", [False, True])
def test_operation_options_and_auth(asynchronous: bool, method: str, api_key: bool) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if api_key:
            assert request.headers["X-API-Key"] == "test-key"
        else:
            assert request.headers["Authorization"] == "Bearer request-token"
        assert request.headers["X-Trace"] == "trace-1"
        assert request.headers["Idempotency-Key"] == "explicit-key"
        assert request.extensions["timeout"] == {"connect": 1.0, "read": 2.0, "write": 3.0, "pool": 4.0}
        if method == "upload_file":
            assert multipart_parts(request)["file"].get_payload(decode=True) == FILE_BYTES
        return httpx.Response(200, json=IMPORT_RESULT if method == "upload_file" else make_api_response(SETTINGS))

    auth = {"api_key": "test-key"} if api_key else {"auth_provider": CallableAuthProvider(lambda: {"Authorization": "Bearer request-token"})}
    invoke(
        asynchronous, method, handler, FILE_BYTES if method == "upload_file" else "default",
        client_options=auth,
        request_options={
            **(UPLOAD_ARGS if method == "upload_file" else {"allow_anonymous": True}),
            "timeout": httpx.Timeout(connect=1, read=2, write=3, pool=4),
            "extra_headers": {"X-Trace": "trace-1", "Idempotency-Key": "header-key"},
            "idempotency_key": "explicit-key",
        },
    )


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("method", ["upload_file", "update_access_policy"])
@pytest.mark.parametrize("failure", ["auth", "http", "timeout"])
def test_operation_error_translation_and_stream_ownership(asynchronous: bool, method: str, failure: str) -> None:
    source = io.BytesIO(FILE_BYTES)

    def handler(request: httpx.Request) -> httpx.Response:
        if failure == "timeout":
            raise httpx.ReadTimeout("slow upload", request=request)
        return httpx.Response(401 if failure == "auth" else 400, json={"message": "Rejected"})

    error = {"auth": HonuaAuthError, "http": HonuaHttpError, "timeout": HonuaTimeoutError}[failure]
    with pytest.raises(error):
        invoke(
            asynchronous, method, handler, source if method == "upload_file" else "default",
            client_options={"max_retries": 0},
            request_options=UPLOAD_ARGS if method == "upload_file" else {"allow_anonymous": True},
        )
    assert not source.closed


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("source", [b"", io.BytesIO(b""), io.StringIO("text")])
def test_upload_rejects_empty_exhausted_or_text_input(asynchronous: bool, source: Any) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        pytest.fail("invalid upload must not reach the server")

    with pytest.raises(TypeError if isinstance(source, io.StringIO) else ValueError):
        invoke(asynchronous, "upload_file", handler, source, request_options=UPLOAD_ARGS)
    if hasattr(source, "closed"):
        assert not source.closed


@pytest.mark.parametrize("asynchronous", [False, True])
def test_second_stream_upload_requires_explicit_rewind(asynchronous: bool) -> None:
    source = io.BytesIO(FILE_BYTES)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=IMPORT_RESULT)

    invoke(asynchronous, "upload_file", handler, source, request_options=UPLOAD_ARGS)
    with pytest.raises(ValueError, match="exhausted"):
        invoke(asynchronous, "upload_file", lambda _: pytest.fail("exhausted stream sent"), source, request_options=UPLOAD_ARGS)
    source.seek(0)
    invoke(asynchronous, "upload_file", handler, source, request_options=UPLOAD_ARGS)
    assert not source.closed


class StreamingTransport(httpx.BaseTransport, httpx.AsyncBaseTransport):
    """Consume the original multipart stream on every transport attempt.

    MockTransport normally caches request.content, masking exhausted-stream
    replay bugs. Delegate a new request to it after consuming the original.
    """

    def __init__(self, handler: Any) -> None:
        self.mock = httpx.MockTransport(handler)
        self.bodies: list[bytes] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return self.deliver(request, b"".join(request.stream))

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = b"".join([chunk async for chunk in request.stream])
        return self.deliver(request, body)

    def deliver(self, request: httpx.Request, body: bytes) -> httpx.Response:
        self.bodies.append(body)
        replay = httpx.Request(request.method, request.url, headers=request.headers, content=body, extensions=request.extensions)
        return self.mock.handle_request(replay)


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("failure", ["status", "timeout"])
def test_opted_in_post_retries_replay_nonseekable_stream(asynchronous: bool, failure: str) -> None:
    class NonSeekable(io.BytesIO):
        def seek(self, *_: Any) -> int:
            raise io.UnsupportedOperation("seek")

    source = NonSeekable(FILE_BYTES)
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        assert request.headers["Idempotency-Key"] == "upload-once"
        parts = multipart_parts(request)
        assert parts["file"].get_payload(decode=True) == FILE_BYTES
        assert parts["TableName"].get_payload(decode=True) == b"points"
        if attempts == 1:
            if failure == "timeout":
                raise httpx.ReadTimeout("first attempt failed", request=request)
            return httpx.Response(503, headers={"Retry-After": "0"})
        return httpx.Response(200, json=IMPORT_RESULT)

    transport = StreamingTransport(handler)
    result = invoke(
        asynchronous, "upload_file", handler, source, retry_post=True,
        client_options={"transport": transport}, request_options={**UPLOAD_ARGS, "idempotency_key": "upload-once"},
    )
    assert result.success and attempts == 2
    assert transport.bodies[0] == transport.bodies[1]
    assert not source.closed and source.tell() == len(FILE_BYTES)


@pytest.mark.parametrize("asynchronous", [False, True])
def test_default_post_is_not_retried(asynchronous: bool) -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, headers={"Retry-After": "0"})

    with pytest.raises(HonuaHttpError):
        invoke(asynchronous, "upload_file", handler, FILE_BYTES, request_options={**UPLOAD_ARGS, "idempotency_key": "key"})
    assert attempts == 1


@pytest.mark.parametrize("asynchronous", [False, True])
@pytest.mark.parametrize("method", ["upload_file", "update_access_policy"])
def test_sticky_timeout_and_retry_options(asynchronous: bool, method: str) -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        assert request.extensions["timeout"] == {"connect": 45.0, "read": 45.0, "write": 45.0, "pool": 45.0}
        return httpx.Response(503, headers={"Retry-After": "0"})

    with pytest.raises(HonuaHttpError):
        invoke(
            asynchronous, method, handler, FILE_BYTES if method == "upload_file" else "default",
            clone_options={"timeout": 45, "max_retries": 0},
            request_options=UPLOAD_ARGS if method == "upload_file" else {"allow_anonymous": True},
        )
    assert attempts == 1


@pytest.mark.parametrize("asynchronous", [False, True])
def test_upload_rejects_content_type_override(asynchronous: bool) -> None:
    with pytest.raises(ValueError, match="boundary"):
        invoke(
            asynchronous, "upload_file", lambda _: pytest.fail("invalid multipart header sent"), FILE_BYTES,
            request_options={**UPLOAD_ARGS, "extra_headers": {"cOnTeNt-TyPe": "multipart/form-data"}},
        )
