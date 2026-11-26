"""Resilience hardening tests: GeoServices 200 retries, Honua-Retryable, reactive auth refresh, ProblemDetails."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import httpx
import pytest
from honua_admin import AsyncHonuaAdminClient, HonuaAdminClient

from honua_sdk import (
    AsyncHonuaClient,
    AsyncRefreshableBearerTokenProvider,
    BearerToken,
    FailureKind,
    HonuaAuthError,
    HonuaClient,
    HonuaHttpError,
    RefreshableBearerTokenProvider,
    StaticAuthProvider,
)


def test_http_503_with_honua_retryable_false_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            503,
            headers={"Honua-Retryable": "false"},
            json={"code": "CAPABILITY_UNAVAILABLE", "title": "Feature unavailable"},
        )

    with patch("honua_sdk._retry.time.sleep") as mock_sleep:
        with HonuaClient("https://example.test", transport=httpx.MockTransport(handler), max_retries=3) as client:
            with pytest.raises(HonuaHttpError) as excinfo:
                client.readiness()

    assert calls == 1
    mock_sleep.assert_not_called()
    assert excinfo.value.status_code == 503
    assert excinfo.value.retryable is False
    assert excinfo.value.message == "Feature unavailable"


@pytest.mark.parametrize("code", [429, 503])
def test_geoservices_http_200_retryable_envelope_retries_and_honors_retry_after(code: int) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                headers={"Honua-Retryable": "true", "Retry-After": "2"},
                json={"error": {"code": code, "message": "Transient error"}},
            )
        return httpx.Response(200, json={"features": [{"attributes": {"OBJECTID": 1}}]})

    with patch("honua_sdk._retry.time.sleep") as mock_sleep:
        with HonuaClient("https://example.test", transport=httpx.MockTransport(handler), max_retries=2) as client:
            result = client.query_features("Parcels", 0, where="1=1")

    assert calls == 2
    assert len(result["features"]) == 1
    mock_sleep.assert_called_once_with(2.0)


def test_geoservices_http_200_envelope_honua_retryable_false_does_not_retry() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            headers={"Honua-Retryable": "false"},
            json={"error": {"code": 503, "message": "Capability disabled"}},
        )

    with patch("honua_sdk._retry.time.sleep") as mock_sleep:
        with HonuaClient("https://example.test", transport=httpx.MockTransport(handler), max_retries=3) as client:
            with pytest.raises(HonuaHttpError) as excinfo:
                client.query_features("Parcels", 0, where="1=1")

    assert calls == 1
    mock_sleep.assert_not_called()
    assert excinfo.value.error_code == 503
    assert excinfo.value.retryable is False


def test_async_geoservices_http_200_retryable_envelope_retries() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                200,
                headers={"Honua-Retryable": "true", "Retry-After": "1"},
                json={"error": {"code": 429, "message": "Rate limited"}},
            )
        return httpx.Response(200, json={"features": []})

    async def run() -> dict[str, object]:
        with patch("honua_sdk._async_retry.asyncio.sleep") as mock_sleep:
            async with AsyncHonuaClient(
                "https://example.test", transport=httpx.MockTransport(handler), max_retries=2
            ) as client:
                result = await client.query_features("Parcels", 0, where="1=1")
            mock_sleep.assert_called_once_with(1.0)
            return result

    assert asyncio.run(run()) == {"features": []}
    assert calls == 2


def test_problem_details_title_fallback_when_detail_and_message_absent() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"type": "https://honua.io/errors/not-found", "title": "Layer not found", "status": 404},
        )

    with HonuaClient("https://example.test", transport=httpx.MockTransport(handler), max_retries=0) as client:
        with pytest.raises(HonuaHttpError) as excinfo:
            client.readiness()

    assert excinfo.value.status_code == 404
    assert excinfo.value.message == "Layer not found"


def test_problem_details_detail_takes_precedence_over_title() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"title": "Bad Request", "detail": "Field 'where' is invalid"},
        )

    with HonuaClient("https://example.test", transport=httpx.MockTransport(handler), max_retries=0) as client:
        with pytest.raises(HonuaHttpError) as excinfo:
            client.readiness()

    assert excinfo.value.message == "Field 'where' is invalid"


@pytest.mark.parametrize("challenge", ["http_401", "geo_498", "geo_499"])
def test_sync_reactive_auth_refresh_on_401_498_499(challenge: str) -> None:
    seen_auth: list[str | None] = []
    refresh_calls = 0

    def refresh() -> BearerToken:
        nonlocal refresh_calls
        refresh_calls += 1
        return BearerToken(f"fresh-token-{refresh_calls}")

    provider = RefreshableBearerTokenProvider(refresh, initial_token=BearerToken("stale-token"))

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("Authorization"))
        if len(seen_auth) == 1:
            if challenge == "http_401":
                return httpx.Response(401, json={"title": "Unauthorized"})
            code = 498 if challenge == "geo_498" else 499
            return httpx.Response(200, json={"error": {"code": code, "message": "Token expired"}})
        return httpx.Response(200, json={"features": []})

    with HonuaClient(
        "https://example.test",
        auth_provider=provider,
        transport=httpx.MockTransport(handler),
        max_retries=0,
    ) as client:
        result = client.query_features("Parcels", 0, where="1=1")

    assert result == {"features": []}
    assert refresh_calls == 1
    assert seen_auth == ["Bearer stale-token", "Bearer fresh-token-1"]


def test_sync_reactive_auth_refresh_works_on_post_and_stops_after_one_retry() -> None:
    seen_auth: list[str | None] = []
    refresh_calls = 0

    def refresh() -> BearerToken:
        nonlocal refresh_calls
        refresh_calls += 1
        return BearerToken(f"fresh-token-{refresh_calls}")

    provider = RefreshableBearerTokenProvider(refresh, initial_token=BearerToken("stale-token"))

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("Authorization"))
        return httpx.Response(200, json={"error": {"code": 498, "message": "Still invalid"}})

    with HonuaClient(
        "https://example.test",
        auth_provider=provider,
        transport=httpx.MockTransport(handler),
        max_retries=0,
    ) as client:
        with pytest.raises(HonuaAuthError) as excinfo:
            client.apply_edits("Parcels", 0, adds=[{"attributes": {"NAME": "x"}}])

    assert refresh_calls == 1
    assert seen_auth == ["Bearer stale-token", "Bearer fresh-token-1"]
    assert excinfo.value.status_code == 401
    assert excinfo.value.error_code == 498
    assert excinfo.value.failure_kind is FailureKind.AUTHENTICATION


def test_async_reactive_auth_refresh_on_401_and_498() -> None:
    seen_auth: list[str | None] = []
    refresh_calls = 0

    async def refresh() -> BearerToken:
        nonlocal refresh_calls
        refresh_calls += 1
        return BearerToken(f"async-fresh-{refresh_calls}")

    provider = AsyncRefreshableBearerTokenProvider(refresh, initial_token=BearerToken("async-stale"))

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("Authorization"))
        if len(seen_auth) == 1:
            return httpx.Response(200, json={"error": {"code": 498, "message": "Invalid Token"}})
        return httpx.Response(200, json={"features": []})

    async def run() -> dict[str, object]:
        async with AsyncHonuaClient(
            "https://example.test",
            auth_provider=provider,
            transport=httpx.MockTransport(handler),
            max_retries=0,
        ) as client:
            return await client.query_features("Parcels", 0, where="1=1")

    assert asyncio.run(run()) == {"features": []}
    assert refresh_calls == 1
    assert seen_auth == ["Bearer async-stale", "Bearer async-fresh-1"]


def test_static_auth_provider_does_not_retry_on_401() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"title": "Unauthorized"})

    provider = StaticAuthProvider({"Authorization": "Bearer static-token"})
    with HonuaClient(
        "https://example.test",
        auth_provider=provider,
        transport=httpx.MockTransport(handler),
        max_retries=0,
    ) as client:
        with pytest.raises(HonuaAuthError):
            client.readiness()

    assert calls == 1


def test_admin_client_reactive_auth_refresh_sync_and_async() -> None:
    sync_seen: list[str | None] = []
    provider = RefreshableBearerTokenProvider(
        lambda: BearerToken("admin-fresh"),
        initial_token=BearerToken("admin-stale"),
    )

    def sync_handler(request: httpx.Request) -> httpx.Response:
        sync_seen.append(request.headers.get("Authorization"))
        if len(sync_seen) == 1:
            return httpx.Response(401, json={"title": "Unauthorized"})
        return httpx.Response(
            200,
            json={"success": True, "data": {"items": [], "nextCursor": None, "totalCount": 0}},
        )

    with HonuaAdminClient(
        "https://example.test",
        auth_provider=provider,
        transport=httpx.MockTransport(sync_handler),
        max_retries=0,
    ) as admin:
        assert admin.list_services() == []
    assert sync_seen == ["Bearer admin-stale", "Bearer admin-fresh"]

    async_seen: list[str | None] = []

    async def async_refresh() -> BearerToken:
        return BearerToken("admin-async-fresh")

    async_provider = AsyncRefreshableBearerTokenProvider(
        async_refresh,
        initial_token=BearerToken("admin-async-stale"),
    )

    def async_handler(request: httpx.Request) -> httpx.Response:
        async_seen.append(request.headers.get("Authorization"))
        if len(async_seen) == 1:
            return httpx.Response(401, json={"title": "Unauthorized"})
        return httpx.Response(
            200,
            json={"success": True, "data": {"items": [], "nextCursor": None, "totalCount": 0}},
        )

    async def run() -> list[object]:
        async with AsyncHonuaAdminClient(
            "https://example.test",
            auth_provider=async_provider,
            transport=httpx.MockTransport(async_handler),
            max_retries=0,
        ) as admin:
            return list(await admin.list_services())

    assert asyncio.run(run()) == []
    assert async_seen == ["Bearer admin-async-stale", "Bearer admin-async-fresh"]
