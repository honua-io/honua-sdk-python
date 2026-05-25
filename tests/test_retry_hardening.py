"""Tests for retry hardening (transport exceptions), idempotency keys, and ``with_options``."""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from honua_sdk._async_retry import AsyncRetryTransport
from honua_sdk._retry import RetryTransport
from honua_sdk.async_client import AsyncHonuaClient
from honua_sdk.client import HonuaClient


# ---------------------------------------------------------------------------
# Transport-exception retry coverage (sync)
# ---------------------------------------------------------------------------


def _build_exception_transport(
    raises: list[Exception | httpx.Response],
    **kwargs: Any,
) -> RetryTransport:
    """Wrap a MockTransport whose handler walks ``raises`` per call."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx = min(call_count["n"], len(raises) - 1)
        call_count["n"] += 1
        item = raises[idx]
        if isinstance(item, Exception):
            raise item
        return item

    inner = httpx.MockTransport(handler)
    kwargs.setdefault("jitter", False)
    transport = RetryTransport(inner, **kwargs)
    transport._call_count = call_count  # type: ignore[attr-defined]
    return transport


def test_retries_on_connect_error() -> None:
    request = httpx.Request("GET", "http://example.test/")
    transport = _build_exception_transport(
        [
            httpx.ConnectError("connect refused"),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    with patch("honua_sdk._retry.time.sleep") as mock_sleep:
        response = transport.handle_request(request)

    assert response.status_code == 200
    assert transport._call_count["n"] == 2  # type: ignore[attr-defined]
    mock_sleep.assert_called_once_with(0.5)


def test_retries_on_read_error() -> None:
    request = httpx.Request("GET", "http://example.test/")
    transport = _build_exception_transport(
        [
            httpx.ReadError("connection reset"),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    with patch("honua_sdk._retry.time.sleep"):
        response = transport.handle_request(request)

    assert response.status_code == 200
    assert transport._call_count["n"] == 2  # type: ignore[attr-defined]


def test_retries_on_timeout_exception() -> None:
    request = httpx.Request("GET", "http://example.test/")
    transport = _build_exception_transport(
        [
            httpx.ReadTimeout("server slow"),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    with patch("honua_sdk._retry.time.sleep"):
        response = transport.handle_request(request)

    assert response.status_code == 200
    assert transport._call_count["n"] == 2  # type: ignore[attr-defined]


def test_retries_on_pool_timeout_and_remote_protocol_error() -> None:
    request = httpx.Request("GET", "http://example.test/")
    transport = _build_exception_transport(
        [
            httpx.PoolTimeout("pool full"),
            httpx.RemoteProtocolError("bad framing"),
            httpx.Response(200, json={"ok": True}),
        ],
        max_retries=3,
    )

    with patch("honua_sdk._retry.time.sleep"):
        response = transport.handle_request(request)

    assert response.status_code == 200
    assert transport._call_count["n"] == 3  # type: ignore[attr-defined]


def test_post_not_retried_on_transport_exception_by_default() -> None:
    """POST is non-idempotent and must not be retried on transport errors."""
    request = httpx.Request("POST", "http://example.test/", json={"x": 1})
    transport = _build_exception_transport(
        [
            httpx.ConnectError("refused"),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    with pytest.raises(httpx.ConnectError):
        transport.handle_request(request)
    assert transport._call_count["n"] == 1  # type: ignore[attr-defined]


def test_post_retries_transport_exception_when_opted_in() -> None:
    request = httpx.Request("POST", "http://example.test/", json={"x": 1})
    transport = _build_exception_transport(
        [
            httpx.ConnectError("refused"),
            httpx.Response(200, json={"ok": True}),
        ],
        retry_methods=frozenset({"GET", "HEAD", "PUT", "DELETE", "OPTIONS", "POST"}),
    )

    with patch("honua_sdk._retry.time.sleep"):
        response = transport.handle_request(request)

    assert response.status_code == 200
    assert transport._call_count["n"] == 2  # type: ignore[attr-defined]


def test_transport_exception_exhausts_and_reraises() -> None:
    request = httpx.Request("GET", "http://example.test/")
    transport = _build_exception_transport(
        [
            httpx.ConnectError("boom"),
            httpx.ConnectError("boom"),
            httpx.ConnectError("boom"),
            httpx.ConnectError("final"),
        ],
        max_retries=3,
    )

    with patch("honua_sdk._retry.time.sleep"):
        with pytest.raises(httpx.ConnectError):
            transport.handle_request(request)
    assert transport._call_count["n"] == 4  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Transport-exception retry coverage (async)
# ---------------------------------------------------------------------------


def _build_async_exception_transport(
    raises: list[Exception | httpx.Response],
    **kwargs: Any,
) -> AsyncRetryTransport:
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        idx = min(call_count["n"], len(raises) - 1)
        call_count["n"] += 1
        item = raises[idx]
        if isinstance(item, Exception):
            raise item
        return item

    inner = httpx.MockTransport(handler)
    kwargs.setdefault("jitter", False)
    transport = AsyncRetryTransport(inner, **kwargs)
    transport._call_count = call_count  # type: ignore[attr-defined]
    return transport


def test_async_retries_on_connect_error() -> None:
    request = httpx.Request("GET", "http://example.test/")
    transport = _build_async_exception_transport(
        [
            httpx.ConnectError("connect refused"),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    async def _run() -> httpx.Response:
        with patch(
            "honua_sdk._async_retry.asyncio.sleep",
            new=_noop_async_sleep,
        ):
            return await transport.handle_async_request(request)

    response = asyncio.run(_run())
    assert response.status_code == 200
    assert transport._call_count["n"] == 2  # type: ignore[attr-defined]


def test_async_retries_on_read_error() -> None:
    request = httpx.Request("GET", "http://example.test/")
    transport = _build_async_exception_transport(
        [
            httpx.ReadError("conn reset"),
            httpx.Response(200, json={"ok": True}),
        ]
    )

    async def _run() -> httpx.Response:
        with patch("honua_sdk._async_retry.asyncio.sleep", new=_noop_async_sleep):
            return await transport.handle_async_request(request)

    response = asyncio.run(_run())
    assert response.status_code == 200


async def _noop_async_sleep(_delay: float) -> None:
    return None


# ---------------------------------------------------------------------------
# Idempotency-Key forwarding
# ---------------------------------------------------------------------------


def test_apply_edits_forwards_idempotency_key() -> None:
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json={"addResults": []})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport, max_retries=0) as client:
        client.apply_edits("svc", 0, adds=[{"x": 1}], idempotency_key="abc-123")

    assert seen_headers.get("idempotency-key") == "abc-123"


def test_apply_edits_no_header_when_unset_and_post_not_opted_in() -> None:
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json={"addResults": []})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport, max_retries=3) as client:
        client.apply_edits("svc", 0, adds=[{"x": 1}])

    assert "idempotency-key" not in {k.lower() for k in seen_headers}


def test_apply_edits_auto_generates_when_post_opted_in() -> None:
    """When POST is opted into retries, the SDK auto-generates an Idempotency-Key."""
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json={"addResults": []})

    transport = httpx.MockTransport(handler)
    # Build a client and force-retry POSTs by reaching into _retry_methods.
    with HonuaClient("http://example.test", transport=transport, max_retries=3) as client:
        client._retry_methods = frozenset(
            {"GET", "HEAD", "PUT", "DELETE", "OPTIONS", "POST"}
        )
        client.apply_edits("svc", 0, adds=[{"x": 1}])

    key = seen_headers.get("idempotency-key")
    assert key is not None
    # uuid4().hex is 32 hex chars
    assert re.fullmatch(r"[0-9a-f]{32}", key) is not None
    # Round-trip through uuid.UUID accepts the hex form.
    uuid.UUID(hex=key)


def test_async_apply_edits_forwards_idempotency_key() -> None:
    seen_headers: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.update(request.headers)
        return httpx.Response(200, json={"addResults": []})

    transport = httpx.MockTransport(handler)

    async def _run() -> None:
        async with AsyncHonuaClient(
            "http://example.test", transport=transport, max_retries=0
        ) as client:
            await client.apply_edits(
                "svc", 0, adds=[{"x": 1}], idempotency_key="async-key-9"
            )

    asyncio.run(_run())
    assert seen_headers.get("idempotency-key") == "async-key-9"


# ---------------------------------------------------------------------------
# with_options
# ---------------------------------------------------------------------------


def test_with_options_overrides_timeout_and_shares_transport() -> None:
    """The clone reuses the original's httpx.Client/connection pool."""
    seen_timeouts: list[Any] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_timeouts.append(request.extensions.get("timeout"))
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    original = HonuaClient(
        "http://example.test", transport=transport, timeout=5.0, max_retries=0
    )
    try:
        clone = original.with_options(timeout=42.0)
        assert clone is not original
        # Sharing the transport means the clone reuses the connection pool.
        assert clone._client is original._client
        # Original retains its constructor-time timeout.
        assert original._client.timeout.connect == 5.0
        # The clone applies its override per-request without rebuilding.
        assert clone._options_timeout == 42.0
        assert clone.readiness() == {"ok": True}
        assert seen_timeouts and seen_timeouts[-1]["connect"] == 42.0
        # Closing the clone must NOT close the shared underlying client.
        clone.close()
        assert original.readiness() == {"ok": True}
    finally:
        original.close()


def test_with_options_disables_retries_on_clone() -> None:
    call_count = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(503, text="retry")

    transport = httpx.MockTransport(handler)
    original = HonuaClient(
        "http://example.test", transport=transport, max_retries=3
    )
    try:
        clone = original.with_options(max_retries=0)
        try:
            with patch("honua_sdk._retry.time.sleep"):
                from honua_sdk.errors import HonuaHttpError

                # With retries disabled on the clone, a 503 surfaces immediately
                # after a single call to the underlying transport.
                with pytest.raises(HonuaHttpError):
                    clone.readiness()
            assert call_count["n"] == 1
        finally:
            clone.close()
    finally:
        original.close()


def test_with_options_reuses_auth_provider_instance() -> None:
    from honua_sdk.auth import StaticAuthProvider

    provider = StaticAuthProvider(headers={"Authorization": "Bearer static"})
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={}))
    original = HonuaClient(
        "http://example.test",
        transport=transport,
        auth_provider=provider,
        max_retries=0,
    )
    try:
        clone = original.with_options(timeout=1.0)
        try:
            assert clone._init_auth_provider is provider
        finally:
            clone.close()
    finally:
        original.close()


def test_async_with_options_shares_transport_and_overrides_timeout() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={"ok": True}))

    async def _run() -> None:
        async with AsyncHonuaClient(
            "http://example.test", transport=transport, timeout=5.0, max_retries=0
        ) as original:
            clone = original.with_options(timeout=11.0, max_retries=0)
            assert clone is not original
            assert clone._client is original._client
            assert clone._options_timeout == 11.0
            assert (await clone.readiness()) == {"ok": True}
            # Closing the clone must be a no-op on the shared transport.
            await clone.close()
            assert (await original.readiness()) == {"ok": True}

    asyncio.run(_run())
