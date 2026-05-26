"""Async geocoding client tests, mirroring the sync ``test_geocoding`` suite."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from honua_sdk import (
    AsyncHonuaGeocodingClient,
    CallableAuthProvider,
    HonuaHttpError,
)
from honua_sdk.errors import HonuaTransportError
from honua_sdk.geocoding import GeocodeResult, GeocodeSuggestion, ReverseGeocodeResult


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


pytestmark = pytest.mark.anyio


def _async_client_with_transport(
    handler: Any,
    *,
    base_url: str = "http://example.test",
    locator_name: str = "World",
) -> AsyncHonuaGeocodingClient:
    """Build an :class:`AsyncHonuaGeocodingClient` bound to a mock transport."""
    transport = httpx.MockTransport(handler)
    external = httpx.AsyncClient(base_url=base_url + "/", transport=transport)
    return AsyncHonuaGeocodingClient(base_url, locator_name=locator_name, client=external)


# ---------------------------------------------------------------------------
# Forward geocode
# ---------------------------------------------------------------------------


async def test_forward_geocode_returns_candidates() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["query"] = dict(request.url.params.multi_items())
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "address": "123 Main St",
                        "location": {"x": -117.1, "y": 32.7},
                        "score": 95.5,
                        "attributes": {"Addr_type": "StreetAddress"},
                    },
                    {
                        "address": "124 Main St",
                        "location": {"x": -117.2, "y": 32.8},
                        "score": 88.0,
                        "attributes": {},
                    },
                ]
            },
        )

    async with _async_client_with_transport(handler) as client:
        results = await client.forward_geocode("123 Main St")

    assert len(results) == 2
    assert isinstance(results[0], GeocodeResult)
    assert results[0].address == "123 Main St"
    assert results[0].longitude == -117.1
    assert results[0].latitude == 32.7
    assert results[0].score == 95.5
    assert results[0].attributes == {"Addr_type": "StreetAddress"}
    assert results[1].score == 88.0

    assert seen["method"] == "GET"
    assert "/GeocodeServer/findAddressCandidates" in seen["path"]
    assert seen["query"]["singleLine"] == "123 Main St"
    assert seen["query"]["f"] == "json"


async def test_forward_geocode_empty_results() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": []})

    async with _async_client_with_transport(handler) as client:
        results = await client.forward_geocode("nonexistent place")

    assert results == []


async def test_forward_geocode_max_results_and_country_code_options() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["query"] = dict(request.url.params.multi_items())
        return httpx.Response(200, json={"candidates": []})

    async with _async_client_with_transport(handler) as client:
        await client.forward_geocode("123 Main St", max_results=7, country_codes="US,CA")

    assert seen["query"]["maxLocations"] == "7"
    assert seen["query"]["countryCode"] == "US,CA"


async def test_forward_geocode_error_payload() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={"error": {"code": 500, "message": "Internal geocode failure"}},
        )

    async with _async_client_with_transport(handler) as client:
        with pytest.raises(HonuaHttpError) as exc_info:
            await client.forward_geocode("bad request")

    err = exc_info.value
    assert err.status_code == 500
    assert err.message == "Internal geocode failure"


# ---------------------------------------------------------------------------
# Reverse geocode
# ---------------------------------------------------------------------------


async def test_reverse_geocode_success() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["query"] = dict(request.url.params.multi_items())
        return httpx.Response(
            200,
            json={
                "address": {
                    "Match_addr": "123 Main St, Springfield",
                    "City": "Springfield",
                },
                "location": {"x": -117.1, "y": 32.7},
            },
        )

    async with _async_client_with_transport(handler) as client:
        result = await client.reverse_geocode(32.7, -117.1)

    assert result is not None
    assert isinstance(result, ReverseGeocodeResult)
    assert result.address == "123 Main St, Springfield"
    assert result.longitude == -117.1
    assert result.latitude == 32.7
    assert result.attributes["City"] == "Springfield"

    assert seen["method"] == "GET"
    assert "/GeocodeServer/reverseGeocode" in seen["path"]
    assert seen["query"]["location"] == "-117.1,32.7"


async def test_reverse_geocode_returns_none_on_empty() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    async with _async_client_with_transport(handler) as client:
        result = await client.reverse_geocode(0.0, 0.0)

    assert result is None


async def test_reverse_geocode_error_handling() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"code": 400, "message": "Invalid location"}},
        )

    async with _async_client_with_transport(handler) as client:
        with pytest.raises(HonuaHttpError) as exc_info:
            await client.reverse_geocode(999.0, 999.0)

    err = exc_info.value
    assert err.status_code == 400
    assert err.message == "Invalid location"


# ---------------------------------------------------------------------------
# Suggest
# ---------------------------------------------------------------------------


async def test_suggest_success() -> None:
    seen: dict[str, Any] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["query"] = dict(request.url.params.multi_items())
        return httpx.Response(
            200,
            json={
                "suggestions": [
                    {"text": "123 Main St", "magicKey": "abc", "isCollection": False},
                    {"text": "123 Main Ave", "magicKey": "def", "isCollection": True},
                ]
            },
        )

    async with _async_client_with_transport(handler) as client:
        results = await client.suggest("123 Main", max_suggestions=4, country_codes="US")

    assert len(results) == 2
    assert isinstance(results[0], GeocodeSuggestion)
    assert results[0].text == "123 Main St"
    assert results[0].magic_key == "abc"
    assert results[0].is_collection is False
    assert results[1].is_collection is True

    assert seen["query"]["text"] == "123 Main"
    assert seen["query"]["maxSuggestions"] == "4"
    assert seen["query"]["countryCode"] == "US"
    assert "/GeocodeServer/suggest" in seen["path"]


async def test_suggest_empty_results() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"suggestions": []})

    async with _async_client_with_transport(handler) as client:
        results = await client.suggest("zzzzzzz")

    assert results == []


# ---------------------------------------------------------------------------
# Init paths and auth headers
# ---------------------------------------------------------------------------


async def test_init_with_api_key_sets_x_api_key_header() -> None:
    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["x_api_key"] = request.headers.get("x-api-key", "")
        seen["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"candidates": []})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaGeocodingClient(
        "http://example.test",
        api_key="async-key",
        transport=transport,
    ) as client:
        await client.forward_geocode("test")

    assert seen["x_api_key"] == "async-key"
    assert seen["authorization"] == ""


async def test_init_with_bearer_token_sets_authorization_header() -> None:
    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["x_api_key"] = request.headers.get("x-api-key", "")
        seen["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"candidates": []})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaGeocodingClient(
        "http://example.test",
        bearer_token="bearer-async",
        transport=transport,
    ) as client:
        await client.forward_geocode("test")

    assert seen["x_api_key"] == ""
    assert seen["authorization"] == "Bearer bearer-async"


async def test_init_with_auth_provider_invokes_provider() -> None:
    seen: dict[str, str] = {}
    calls = {"count": 0}

    def provider_fn() -> dict[str, str]:
        calls["count"] += 1
        return {"Authorization": "Bearer from-provider"}

    auth = CallableAuthProvider(provider_fn)

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"candidates": []})

    transport = httpx.MockTransport(handler)
    async with AsyncHonuaGeocodingClient(
        "http://example.test",
        auth_provider=auth,
        transport=transport,
    ) as client:
        await client.forward_geocode("test")

    assert seen["authorization"] == "Bearer from-provider"
    assert calls["count"] == 1


async def test_init_rejects_client_and_transport_together() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    external = httpx.AsyncClient(base_url="http://example.test", transport=transport)
    try:
        with pytest.raises(ValueError, match="either `client` or `transport`"):
            AsyncHonuaGeocodingClient(
                "http://example.test",
                client=external,
                transport=transport,
            )
    finally:
        await external.aclose()


async def test_init_with_external_client_rejects_sdk_auth_options() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200))
    external = httpx.AsyncClient(base_url="http://example.test", transport=transport)
    try:
        with pytest.raises(ValueError, match="supplied `client`"):
            AsyncHonuaGeocodingClient(
                "http://example.test",
                client=external,
                api_key="should-not-be-here",
            )
    finally:
        await external.aclose()


async def test_init_rejects_bearer_token_and_auth_provider() -> None:
    auth = CallableAuthProvider(lambda: {"Authorization": "Bearer x"})
    with pytest.raises(ValueError):
        AsyncHonuaGeocodingClient(
            "http://example.test",
            bearer_token="t",
            auth_provider=auth,
        )


# ---------------------------------------------------------------------------
# Close() semantics for externally owned clients
# ---------------------------------------------------------------------------


async def test_close_is_noop_for_external_client() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"candidates": []}))
    external = httpx.AsyncClient(base_url="http://example.test", transport=transport)
    client = AsyncHonuaGeocodingClient("http://example.test", client=external)
    try:
        await client.close()  # Must not close the externally supplied client.
        # External client should still be usable for another request.
        response = await external.get("/ping")
        assert response.status_code == 200
    finally:
        await external.aclose()


# ---------------------------------------------------------------------------
# HTTP errors
# ---------------------------------------------------------------------------


async def test_http_error_404_on_suggest() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": {"code": 404, "message": "Locator not found"}},
        )

    async with _async_client_with_transport(handler) as client:
        with pytest.raises(HonuaHttpError) as exc_info:
            await client.suggest("test")

    err = exc_info.value
    assert err.status_code == 404
    assert err.message == "Locator not found"


async def test_transport_error_raises_honua_transport_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with _async_client_with_transport(handler) as client:
        with pytest.raises(HonuaTransportError) as exc_info:
            await client.forward_geocode("test")

    assert "Transport error" in str(exc_info.value)


async def test_custom_locator_name_in_path() -> None:
    seen: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={"candidates": []})

    async with _async_client_with_transport(handler, locator_name="MyLocator") as client:
        await client.forward_geocode("test")

    assert "/rest/services/MyLocator/GeocodeServer/findAddressCandidates" in seen["path"]


async def test_non_json_response_returns_raw_dict() -> None:
    """A 200 with non-JSON body should still be tolerated by the helper."""
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    async with _async_client_with_transport(handler) as client:
        results = await client.forward_geocode("test")

    # No candidates key in the raw dict path, so results is empty.
    assert results == []


async def test_empty_response_body_returns_empty_results() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"")

    async with _async_client_with_transport(handler) as client:
        results = await client.forward_geocode("test")

    assert results == []
