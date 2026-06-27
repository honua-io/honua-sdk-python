"""Regression tests for the pre-release transport/auth/de-duplication audit.

Covers:

* #125 — request-path encoding: a non-ASCII (server-controlled next-link) path
  no longer crashes ``_request`` with an unwrapped ``UnicodeEncodeError``.
* #125 — geocoding installs the retry transport consistently (always-on, even
  at ``max_retries=0``), matching the core client.
* #126 — the async client refreshes auth tokens without blocking the loop:
  an :class:`AsyncRefreshableBearerTokenProvider` is awaited, and a plain
  synchronous provider is offloaded to a worker thread.
* #129 (AUD-162) — protocol ``_text`` requests honour per-call options
  (``with_options(max_retries=…)``), which previously only applied to the JSON
  path because ``_text`` bypassed the client's request path.
"""

from __future__ import annotations

import threading

import httpx
import pytest

from honua_sdk import (
    AsyncHonuaGeocodingClient,
    AsyncRefreshableBearerTokenProvider,
    HonuaClient,
    HonuaGeocodingClient,
    StaticAuthProvider,
)
from honua_sdk._async_retry import AsyncRetryTransport
from honua_sdk._http import encode_request_path
from honua_sdk._retry import RetryTransport
from honua_sdk.async_client import AsyncHonuaClient


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# ---------------------------------------------------------------------------
# #125 — request-path encoding
# ---------------------------------------------------------------------------


def test_encode_request_path_ascii_passthrough() -> None:
    assert encode_request_path("/rest/services/World") == b"/rest/services/World"


def test_encode_request_path_preserves_existing_percent_encoding() -> None:
    # An already percent-encoded segment must not be double-encoded.
    assert encode_request_path("/rest/services/a%20b/Query") == b"/rest/services/a%20b/Query"


def test_encode_request_path_percent_encodes_non_ascii_only() -> None:
    # Only the non-ASCII characters are percent-encoded (UTF-8); ASCII and the
    # path delimiters are left intact.
    assert encode_request_path("/rest/services/café") == b"/rest/services/caf%C3%A9"


def test_request_with_non_ascii_path_does_not_crash() -> None:
    seen: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path)
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport, max_retries=0) as client:
        # Simulates following a server-controlled next-link path with non-ASCII
        # characters — previously this raised an unwrapped UnicodeEncodeError.
        response = client._request("GET", "/rest/services/München/FeatureServer/0/query")
    assert response.status_code == 200
    assert seen[0] == b"/rest/services/M%C3%BCnchen/FeatureServer/0/query"


# ---------------------------------------------------------------------------
# #125 — geocoding retry transport is installed consistently (always-on)
# ---------------------------------------------------------------------------


def test_geocoding_installs_retry_transport_even_at_zero_retries() -> None:
    with HonuaGeocodingClient("http://example.test", max_retries=0) as geo:
        assert isinstance(geo._client._transport, RetryTransport)


@pytest.mark.anyio
async def test_async_geocoding_installs_retry_transport_even_at_zero_retries() -> None:
    async with AsyncHonuaGeocodingClient("http://example.test", max_retries=0) as geo:
        assert isinstance(geo._client._transport, AsyncRetryTransport)


# ---------------------------------------------------------------------------
# #129 (AUD-162) — protocol _text honours per-call options
# ---------------------------------------------------------------------------


def test_text_request_honors_with_options_max_retries() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(503)
        return httpx.Response(200, content=b"<capabilities/>")

    transport = httpx.MockTransport(handler)
    # The base client has a zero retry budget; the WFS GetCapabilities call goes
    # through the _text path. with_options(max_retries=1) must be honoured there
    # too — previously _text bypassed the per-call override entirely.
    with HonuaClient("http://example.test", transport=transport, max_retries=0) as client:
        body = client.with_options(max_retries=1).wfs().capabilities()
    assert body == "<capabilities/>"
    assert attempts["count"] == 2  # one 503 retried once, then 200


def test_text_request_joins_base_url_path_prefix() -> None:
    seen: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.raw_path)
        return httpx.Response(200, content=b"<capabilities/>")

    transport = httpx.MockTransport(handler)
    # A sub-path base URL must be preserved on the _text path (it routes through
    # _request, which joins the base path) just like the JSON path.
    with HonuaClient("http://example.test/honua/", transport=transport, max_retries=0) as client:
        client.wfs().capabilities()
    assert seen[0].split(b"?")[0] == b"/honua/wfs"


# ---------------------------------------------------------------------------
# #126 — async non-blocking auth refresh
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_async_refreshable_bearer_token_provider_is_awaited() -> None:
    refreshed: list[str] = []

    async def refresh() -> str:
        refreshed.append("called")
        return "async-token"

    provider = AsyncRefreshableBearerTokenProvider(refresh)

    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization", ""))
        return httpx.Response(200, json={"services": []})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient(
        "http://example.test", transport=transport, auth_provider=provider
    ) as client:
        await client.list_services()

    assert refreshed == ["called"]
    assert seen == ["Bearer async-token"]


@pytest.mark.anyio
async def test_async_client_offloads_sync_auth_provider_off_the_loop() -> None:
    loop_thread = threading.get_ident()
    call_threads: list[int] = []

    class _RecordingProvider:
        def auth_headers(self) -> dict[str, str]:
            call_threads.append(threading.get_ident())
            return {"Authorization": "Bearer sync-token"}

    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization", ""))
        return httpx.Response(200, json={"services": []})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaClient(
        "http://example.test", transport=transport, auth_provider=_RecordingProvider()
    ) as client:
        await client.list_services()

    assert seen == ["Bearer sync-token"]
    # The synchronous provider ran in a worker thread, not on the event loop.
    assert call_threads and all(tid != loop_thread for tid in call_threads)


@pytest.mark.anyio
async def test_async_refreshable_provider_caches_and_forces_refresh() -> None:
    counter = {"n": 0}

    async def refresh() -> dict[str, object]:
        counter["n"] += 1
        # No expiry metadata => token never looks expired, so it is cached.
        return {"access_token": f"tok-{counter['n']}"}

    provider = AsyncRefreshableBearerTokenProvider(refresh)
    first = await provider.get_token()
    second = await provider.get_token()
    assert first.access_token == "tok-1"
    assert second.access_token == "tok-1"  # cached; refresh not called again
    assert counter["n"] == 1

    forced = await provider.refresh()
    assert forced.access_token == "tok-2"
    assert counter["n"] == 2


@pytest.mark.anyio
async def test_async_refreshable_provider_revoke_runs_hook_and_clears() -> None:
    revoked: list[str] = []

    async def refresh() -> str:
        return "tok"

    async def revoke(token: object) -> None:
        revoked.append(getattr(token, "access_token", ""))

    provider = AsyncRefreshableBearerTokenProvider(refresh, revoke=revoke)
    await provider.get_token()
    await provider.revoke()
    assert revoked == ["tok"]
    # Token cache cleared, so the next access refreshes again.
    assert (await provider.get_token()).access_token == "tok"


def test_async_refreshable_provider_rejects_negative_window() -> None:
    async def refresh() -> str:
        return "tok"

    with pytest.raises(ValueError, match="refresh_window_seconds"):
        AsyncRefreshableBearerTokenProvider(refresh, refresh_window_seconds=-1)


@pytest.mark.anyio
async def test_async_auth_headers_stripped_on_redirect_to_other_host() -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization", ""))
        return httpx.Response(200, json={"services": []})

    transport = httpx.MockTransport(handler)
    provider = AsyncRefreshableBearerTokenProvider(_const_token)
    # Build a client bound to one authority, then fire a request at a different
    # host through the same event hook to exercise the strip branch.
    async with AsyncHonuaClient(
        "http://example.test", transport=transport, auth_provider=provider
    ) as client:
        await client._request("GET", "/rest/services")
        # Re-target the underlying client at a foreign host: the trusted-origin
        # gate must drop the provider-supplied Authorization header.
        other = httpx.Request("GET", "http://evil.test/rest/services")
        await client._client.send(other)
    assert seen[0] == "Bearer const-token"
    assert seen[1] == ""  # stripped on the foreign authority


async def _const_token() -> str:
    return "const-token"


@pytest.mark.anyio
async def test_async_static_auth_provider_still_attaches_headers() -> None:
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("x-api-key", ""))
        return httpx.Response(200, json={"services": []})

    transport = httpx.MockTransport(handler)
    provider = StaticAuthProvider({"X-API-Key": "k"})
    async with AsyncHonuaClient(
        "http://example.test", transport=transport, auth_provider=provider
    ) as client:
        await client.list_services()
    assert seen == ["k"]
