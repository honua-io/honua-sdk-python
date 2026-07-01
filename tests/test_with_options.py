"""Targeted ``with_options`` tests focused on transport sharing semantics.

The legacy ``with_options`` rebuilt the full :class:`httpx.Client` (and
thus the connection pool) on every call. The current implementation
returns a lightweight clone that **shares the parent transport** and
applies overrides per-request. These tests pin that behaviour so the
old pool-rebuilding pattern can't sneak back in.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from honua_admin import AsyncHonuaAdminClient, HonuaAdminClient
from honua_sdk import HonuaClient
from honua_sdk.async_client import AsyncHonuaClient
from honua_sdk.errors import HonuaHttpError


# ---------------------------------------------------------------------------
# Sync HonuaClient.with_options
# ---------------------------------------------------------------------------


def test_sync_with_options_reuses_parent_transport_and_pool() -> None:
    """The clone must dispatch through the same MockTransport / pool."""
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    ) as original:
        clone = original.with_options(timeout=99.0)
        # Identity check: the clone literally holds the same httpx.Client
        # (and therefore the same connection pool) as the parent.
        assert clone._client is original._client
        # Both dispatch through the MockTransport supplied to the parent.
        assert clone.readiness() == {"ok": True}
        assert original.readiness() == {"ok": True}
        assert len(seen_requests) == 2


def test_sync_with_options_close_does_not_close_parent_transport() -> None:
    """The clone has no lifecycle ownership of the shared client."""
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={}))
    original = HonuaClient(
        "http://example.test", transport=transport, max_retries=0
    )
    try:
        clone = original.with_options(timeout=1.0)
        clone.close()
        # The parent must remain usable after the clone is closed.
        assert original.readiness() == {}
    finally:
        original.close()


def test_sync_with_options_timeout_override_is_per_request() -> None:
    """The per-request timeout is forwarded as ``httpx.Timeout(...)``."""
    seen_timeouts: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_timeouts.append(request.extensions.get("timeout", {}))
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    with HonuaClient(
        "http://example.test", transport=transport, timeout=30.0, max_retries=0
    ) as original:
        clone = original.with_options(timeout=2.5)
        clone.readiness()
        original.readiness()

    assert seen_timeouts[0]["connect"] == 2.5
    # The original's request used the constructor-time default (30s), not 2.5.
    assert seen_timeouts[1]["connect"] == 30.0


def test_sync_with_options_max_retries_zero_disables_retries_on_clone() -> None:
    """``max_retries=0`` on the clone must skip retries but keep the pool."""
    call_count = {"n": 0}

    def handler(_r: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(503, text="retry")

    transport = httpx.MockTransport(handler)
    original = HonuaClient(
        "http://example.test", transport=transport, max_retries=3
    )
    try:
        clone = original.with_options(max_retries=0)
        assert clone._client is original._client
        with patch("honua_sdk._retry.time.sleep"):
            with pytest.raises(HonuaHttpError):
                clone.readiness()
        # Exactly one call: the per-request override killed the retry loop.
        assert call_count["n"] == 1
    finally:
        original.close()


def test_sync_with_options_chained_overrides_accumulate() -> None:
    """Chaining ``with_options`` preserves earlier overrides for fields not set."""
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={}))
    with HonuaClient(
        "http://example.test", transport=transport, timeout=30.0, max_retries=0
    ) as original:
        # Use a timeout >= parent's so transport sharing stays in effect.
        first = original.with_options(timeout=60.0)
        second = first.with_options(max_retries=0)
        # The second clone inherits the first clone's timeout override.
        assert second._options_timeout == 60.0
        assert second._options_max_retries == 0
        # All three reuse the same underlying client when the override
        # timeout is not lower than the parent's configured timeout.
        assert original._client is first._client is second._client


def test_sync_with_options_timeout_lower_than_parent_builds_independent_client() -> None:
    """``with_options(timeout=<smaller>)`` auto-falls-through to an independent clone.

    A per-request ``timeout`` override on a shared transport can only
    extend the parent's bound deadline, not tighten it. Smaller values
    must therefore build a fresh ``httpx.Client`` with the smaller
    transport timeout so the deadline is actually applied end-to-end.
    """
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={}))
    with HonuaClient(
        "http://example.test", transport=transport, timeout=30.0, max_retries=0
    ) as original:
        clone = original.with_options(timeout=1.0)
        # The clone holds its own httpx.Client (independent connection pool).
        assert clone._client is not original._client
        # And that client's transport-level timeout is the smaller value
        # — confirming the 1-second deadline is actually applied.
        assert clone._client.timeout == httpx.Timeout(1.0)
        # The original's transport-level timeout is unchanged.
        assert original._client.timeout == httpx.Timeout(30.0)
        # The clone owns its client and must close it independently.
        assert clone._owns_client is True
        clone.close()


# ---------------------------------------------------------------------------
# Async AsyncHonuaClient.with_options
# ---------------------------------------------------------------------------


def test_async_with_options_reuses_parent_transport_and_pool() -> None:
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)

    async def _run() -> None:
        async with AsyncHonuaClient(
            "http://example.test", transport=transport, timeout=30.0, max_retries=0
        ) as original:
            # ``timeout=60.0`` >= parent's 30.0 -> shared transport.
            clone = original.with_options(timeout=60.0)
            assert clone._client is original._client
            assert (await clone.readiness()) == {"ok": True}
            assert (await original.readiness()) == {"ok": True}

    asyncio.run(_run())
    assert len(seen_requests) == 2


# ---------------------------------------------------------------------------
# Admin clients
# ---------------------------------------------------------------------------


def test_admin_with_options_reuses_parent_transport() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={}))
    # Use ``timeout=10.0`` so the override (60.0) is >= the parent's,
    # keeping the transport-sharing path active.
    original = HonuaAdminClient(
        "http://example.test", transport=transport, timeout=10.0
    )
    try:
        clone = original.with_options(timeout=60.0, max_retries=0)
        assert clone._client is original._client
        assert clone._options_timeout == 60.0
        assert clone._options_max_retries == 0
    finally:
        original.close()


def test_async_admin_with_options_reuses_parent_transport() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={}))

    async def _run() -> None:
        # Same shape as the sync admin test: override timeout >= parent's
        # configured timeout so the transport-sharing path is exercised.
        client = AsyncHonuaAdminClient(
            "http://example.test", transport=transport, timeout=10.0
        )
        try:
            clone = client.with_options(timeout=60.0, max_retries=0)
            assert clone._client is client._client
            assert clone._options_timeout == 60.0
            assert clone._options_max_retries == 0
        finally:
            await client.close()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# with_options(base_url=...) creates an independent client
# ---------------------------------------------------------------------------


def test_sync_with_options_base_url_returns_independent_client() -> None:
    """Passing ``base_url`` must build a fresh ``httpx.Client`` for the clone.

    The new base URL has to be honored end-to-end (including the bound
    ``httpx.Client.base_url`` used by event hooks / pool keys), which
    means the clone cannot share the parent's underlying client.
    """
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={}))
    original = HonuaClient(
        "http://original.test", transport=transport, max_retries=0
    )
    try:
        clone = original.with_options(base_url="http://other.test")
        # Independent client: not the same object as the parent's httpx.Client.
        assert clone._client is not original._client
        # The clone OWNS its own client (must be closed independently).
        assert clone._owns_client is True
        # The underlying httpx.Client's bound base_url tracks the override —
        # not just our SDK-level ``_base_url`` cache.
        assert str(clone._client.base_url).rstrip("/") == "http://other.test"
        assert str(clone._base_url).rstrip("/") == "http://other.test"
        # The original is unaffected.
        assert str(original._client.base_url).rstrip("/") == "http://original.test"
    finally:
        clone.close()
        original.close()


def test_async_with_options_base_url_returns_independent_client() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={}))

    async def _run() -> None:
        original = AsyncHonuaClient(
            "http://original.test", transport=transport, max_retries=0
        )
        try:
            clone = original.with_options(base_url="http://other.test")
            assert clone._client is not original._client
            assert clone._owns_client is True
            assert str(clone._client.base_url).rstrip("/") == "http://other.test"
            assert str(original._client.base_url).rstrip("/") == "http://original.test"
            await clone.close()
        finally:
            await original.close()

    asyncio.run(_run())


def test_admin_with_options_base_url_returns_independent_client() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={}))
    original = HonuaAdminClient(
        "http://original.test", transport=transport, max_retries=0
    )
    try:
        clone = original.with_options(base_url="http://other.test")
        assert clone._client is not original._client
        assert clone._owns_client is True
        assert str(clone._client.base_url).rstrip("/") == "http://other.test"
        assert str(original._client.base_url).rstrip("/") == "http://original.test"
        clone.close()
    finally:
        original.close()


def test_async_admin_with_options_base_url_returns_independent_client() -> None:
    transport = httpx.MockTransport(lambda _r: httpx.Response(200, json={}))

    async def _run() -> None:
        original = AsyncHonuaAdminClient(
            "http://original.test", transport=transport, max_retries=0
        )
        try:
            clone = original.with_options(base_url="http://other.test")
            assert clone._client is not original._client
            assert clone._owns_client is True
            assert str(clone._client.base_url).rstrip("/") == "http://other.test"
            assert str(original._client.base_url).rstrip("/") == "http://original.test"
            await clone.close()
        finally:
            await original.close()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# RetryTransport.retry_methods public property
# ---------------------------------------------------------------------------


def test_retry_transport_exposes_public_retry_methods_property() -> None:
    from honua_sdk._async_retry import AsyncRetryTransport
    from honua_sdk._retry import RetryTransport

    sync_transport = RetryTransport(httpx.MockTransport(lambda _r: httpx.Response(200)))
    async_transport = AsyncRetryTransport(
        httpx.MockTransport(lambda _r: httpx.Response(200))
    )
    # The public property mirrors the (now-internal) ``_retry_methods``
    # frozenset; callers must rely on the property going forward.
    assert sync_transport.retry_methods == sync_transport._retry_methods
    assert async_transport.retry_methods == async_transport._retry_methods
    assert "GET" in sync_transport.retry_methods
    assert "POST" not in sync_transport.retry_methods


# ---------------------------------------------------------------------------
# issue #105: with_options(max_retries=N) on a client built with max_retries=0
# must actually take effect (RetryTransport is always installed).
# ---------------------------------------------------------------------------


def test_with_options_enables_retries_on_zero_built_sync_client() -> None:
    call_count = {"n": 0}

    def handler(_r: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] <= 2:
            return httpx.Response(503, text="retry")
        return httpx.Response(200, json={"status": "ready"})

    transport = httpx.MockTransport(handler)
    original = HonuaClient("http://example.test", transport=transport, max_retries=0)
    try:
        retrying = original.with_options(max_retries=5)
        with patch("honua_sdk._retry.time.sleep"):
            result = retrying.readiness()
        assert result == {"status": "ready"}
        # Two retries consumed before the 200 — the override took effect.
        assert call_count["n"] == 3
    finally:
        original.close()


def test_zero_built_sync_client_still_does_not_retry_by_default() -> None:
    call_count = {"n": 0}

    def handler(_r: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(503, text="retry")

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport, max_retries=0) as client:
        with patch("honua_sdk._retry.time.sleep"):
            with pytest.raises(HonuaHttpError):
                client.readiness()
    # No override => single attempt, behaviour unchanged for the default path.
    assert call_count["n"] == 1


def test_with_options_enables_retries_on_zero_built_async_client() -> None:
    call_count = {"n": 0}

    def handler(_r: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] <= 2:
            return httpx.Response(503, text="retry")
        return httpx.Response(200, json={"status": "ready"})

    async def run() -> dict[str, Any]:
        transport = httpx.MockTransport(handler)
        original = AsyncHonuaClient(
            "http://example.test", transport=transport, max_retries=0
        )
        try:
            retrying = original.with_options(max_retries=5)
            with patch("honua_sdk._async_retry.asyncio.sleep"):
                return await retrying.readiness()
        finally:
            await original.close()

    result = asyncio.run(run())
    assert result == {"status": "ready"}
    assert call_count["n"] == 3


# ---------------------------------------------------------------------------
# AUD-162 (issue #129): protocol ``_text`` requests must route through the
# client's normal request path so per-call options carried by ``with_options``
# (``timeout`` / ``max_retries``) apply to text protocols — every WFS operation
# and OData ``$metadata`` — exactly like the JSON path. These previously
# bypassed ``_request`` and silently ignored the overrides.
# ---------------------------------------------------------------------------


def test_with_options_timeout_applies_to_wfs_text_path() -> None:
    seen_timeouts: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_timeouts.append(request.extensions.get("timeout", {}))
        return httpx.Response(200, text="<wfs:Capabilities/>")

    transport = httpx.MockTransport(handler)
    with HonuaClient(
        "http://example.test", transport=transport, timeout=30.0, max_retries=0
    ) as original:
        # WfsClient.capabilities() flows through the protocol ``_text`` path.
        original.with_options(timeout=2.5).wfs().capabilities()
        original.wfs().capabilities()

    assert seen_timeouts[0]["connect"] == 2.5
    # The un-cloned client still uses its constructor-time default (30s).
    assert seen_timeouts[1]["connect"] == 30.0


def test_with_options_timeout_applies_to_odata_metadata_text_path() -> None:
    seen_timeouts: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_timeouts.append(request.extensions.get("timeout", {}))
        return httpx.Response(200, text="<edmx:Edmx/>")

    transport = httpx.MockTransport(handler)
    with HonuaClient(
        "http://example.test", transport=transport, timeout=30.0, max_retries=0
    ) as original:
        # ODataClient.metadata() fetches ``$metadata`` over the ``_text`` path.
        original.with_options(timeout=4.0).odata().metadata()

    assert seen_timeouts[0]["connect"] == 4.0


def test_with_options_max_retries_applies_to_wfs_text_path() -> None:
    call_count = {"n": 0}

    def handler(_r: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] <= 2:
            return httpx.Response(503, text="retry")
        return httpx.Response(200, text="<wfs:Capabilities/>")

    transport = httpx.MockTransport(handler)
    original = HonuaClient("http://example.test", transport=transport, max_retries=0)
    try:
        retrying = original.with_options(max_retries=5)
        with patch("honua_sdk._retry.time.sleep"):
            result = retrying.wfs().capabilities()
        assert result == "<wfs:Capabilities/>"
        # Two 503s retried before the 200 — the override reached the _text path.
        assert call_count["n"] == 3
    finally:
        original.close()


def test_async_with_options_timeout_applies_to_wfs_text_path() -> None:
    seen_timeouts: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_timeouts.append(request.extensions.get("timeout", {}))
        return httpx.Response(200, text="<wfs:Capabilities/>")

    async def run() -> None:
        transport = httpx.MockTransport(handler)
        async with AsyncHonuaClient(
            "http://example.test", transport=transport, timeout=30.0, max_retries=0
        ) as original:
            await original.with_options(timeout=2.5).wfs().capabilities()
            await original.wfs().capabilities()

    asyncio.run(run())
    assert seen_timeouts[0]["connect"] == 2.5
    assert seen_timeouts[1]["connect"] == 30.0
