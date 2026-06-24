from __future__ import annotations

from typing import Any

import httpx
import pytest

from honua_sdk import HonuaGeocodingClient, HonuaHttpError
from honua_sdk.errors import HonuaTransportError
from honua_sdk.geocoding import GeocodeResult, GeocodeSuggestion, ReverseGeocodeResult


# ---------------------------------------------------------------------------
# Forward geocode
# ---------------------------------------------------------------------------


def test_forward_geocode_returns_candidates() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
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

    transport = httpx.MockTransport(handler)
    with HonuaGeocodingClient("http://example.test", client=httpx.Client(base_url="http://example.test/", transport=transport)) as client:
        results = client.forward_geocode("123 Main St")

    assert len(results) == 2
    assert isinstance(results[0], GeocodeResult)
    assert results[0].address == "123 Main St"
    assert results[0].longitude == -117.1
    assert results[0].latitude == 32.7
    assert results[0].score == 95.5
    assert results[0].attributes == {"Addr_type": "StreetAddress"}

    assert results[1].address == "124 Main St"
    assert results[1].score == 88.0

    assert seen["method"] == "GET"
    assert "/GeocodeServer/findAddressCandidates" in seen["path"]
    assert seen["query"]["singleLine"] == "123 Main St"
    assert seen["query"]["f"] == "json"


def test_forward_geocode_empty_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"candidates": []})

    transport = httpx.MockTransport(handler)
    with HonuaGeocodingClient("http://example.test", client=httpx.Client(base_url="http://example.test/", transport=transport)) as client:
        results = client.forward_geocode("nonexistent place")

    assert results == []


def test_forward_geocode_error_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={"error": {"code": 500, "message": "Internal geocode failure"}},
        )

    transport = httpx.MockTransport(handler)
    with HonuaGeocodingClient("http://example.test", client=httpx.Client(base_url="http://example.test/", transport=transport)) as client:
        with pytest.raises(HonuaHttpError) as exc_info:
            client.forward_geocode("bad request")

    err = exc_info.value
    assert err.status_code == 500
    assert err.message == "Internal geocode failure"


def test_forward_geocode_max_results_option() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["query"] = dict(request.url.params.multi_items())
        return httpx.Response(200, json={"candidates": []})

    transport = httpx.MockTransport(handler)
    with HonuaGeocodingClient("http://example.test", client=httpx.Client(base_url="http://example.test/", transport=transport)) as client:
        client.forward_geocode("123 Main St", max_results=3)

    assert seen["query"]["maxLocations"] == "3"


def test_forward_geocode_country_code_option() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["query"] = dict(request.url.params.multi_items())
        return httpx.Response(200, json={"candidates": []})

    transport = httpx.MockTransport(handler)
    with HonuaGeocodingClient("http://example.test", client=httpx.Client(base_url="http://example.test/", transport=transport)) as client:
        client.forward_geocode("123 Main St", country_codes="US,CA")

    assert seen["query"]["countryCode"] == "US,CA"


# ---------------------------------------------------------------------------
# Reverse geocode
# ---------------------------------------------------------------------------


def test_reverse_geocode_success() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
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

    transport = httpx.MockTransport(handler)
    with HonuaGeocodingClient("http://example.test", client=httpx.Client(base_url="http://example.test/", transport=transport)) as client:
        result = client.reverse_geocode(32.7, -117.1)

    assert result is not None
    assert isinstance(result, ReverseGeocodeResult)
    assert result.address == "123 Main St, Springfield"
    assert result.longitude == -117.1
    assert result.latitude == 32.7
    assert result.attributes["City"] == "Springfield"

    assert seen["method"] == "GET"
    assert "/GeocodeServer/reverseGeocode" in seen["path"]
    assert seen["query"]["location"] == "-117.1,32.7"


def test_reverse_geocode_returns_none_on_empty() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    with HonuaGeocodingClient("http://example.test", client=httpx.Client(base_url="http://example.test/", transport=transport)) as client:
        result = client.reverse_geocode(0.0, 0.0)

    assert result is None


def test_reverse_geocode_error_handling() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"code": 400, "message": "Invalid location"}},
        )

    transport = httpx.MockTransport(handler)
    with HonuaGeocodingClient("http://example.test", client=httpx.Client(base_url="http://example.test/", transport=transport)) as client:
        with pytest.raises(HonuaHttpError) as exc_info:
            client.reverse_geocode(999.0, 999.0)

    err = exc_info.value
    assert err.status_code == 400
    assert err.message == "Invalid location"


# ---------------------------------------------------------------------------
# Suggest
# ---------------------------------------------------------------------------


def test_suggest_success() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["query"] = dict(request.url.params.multi_items())
        return httpx.Response(
            200,
            json={
                "suggestions": [
                    {"text": "123 Main St, Springfield", "magicKey": "abc123", "isCollection": False},
                    {"text": "123 Main Ave, Shelbyville", "magicKey": "def456", "isCollection": True},
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    with HonuaGeocodingClient("http://example.test", client=httpx.Client(base_url="http://example.test/", transport=transport)) as client:
        results = client.suggest("123 Main")

    assert len(results) == 2
    assert isinstance(results[0], GeocodeSuggestion)
    assert results[0].text == "123 Main St, Springfield"
    assert results[0].magic_key == "abc123"
    assert results[0].is_collection is False
    assert results[1].is_collection is True

    assert seen["method"] == "GET"
    assert "/GeocodeServer/suggest" in seen["path"]
    assert seen["query"]["text"] == "123 Main"


def test_suggest_empty_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"suggestions": []})

    transport = httpx.MockTransport(handler)
    with HonuaGeocodingClient("http://example.test", client=httpx.Client(base_url="http://example.test/", transport=transport)) as client:
        results = client.suggest("zzzzzzz")

    assert results == []


# ---------------------------------------------------------------------------
# Auth headers
# ---------------------------------------------------------------------------


def test_auth_headers_api_key() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["x_api_key"] = request.headers.get("x-api-key", "")
        seen["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"candidates": []})

    transport = httpx.MockTransport(handler)
    with HonuaGeocodingClient(
        "http://example.test",
        api_key="geo-test-key",
    ) as client:
        client._client = httpx.Client(base_url="http://example.test/", transport=transport, event_hooks=client._client._event_hooks)
        client.forward_geocode("test")

    assert seen["x_api_key"] == "geo-test-key"
    assert seen["authorization"] == ""


def test_auth_headers_bearer_token() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["x_api_key"] = request.headers.get("x-api-key", "")
        seen["authorization"] = request.headers.get("authorization", "")
        return httpx.Response(200, json={"candidates": []})

    transport = httpx.MockTransport(handler)
    with HonuaGeocodingClient(
        "http://example.test",
        bearer_token="geo-test-token",
    ) as client:
        client._client = httpx.Client(base_url="http://example.test/", transport=transport, event_hooks=client._client._event_hooks)
        client.forward_geocode("test")

    assert seen["x_api_key"] == ""
    assert seen["authorization"] == "Bearer geo-test-token"


def test_custom_http_client_rejects_sdk_auth_options() -> None:
    client = httpx.Client(
        base_url="http://example.test",
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
    )
    try:
        with pytest.raises(ValueError, match="supplied `client`"):
            HonuaGeocodingClient("http://ignored.test", client=client, api_key="geo-test-key")
    finally:
        client.close()


# ---------------------------------------------------------------------------
# HTTP errors
# ---------------------------------------------------------------------------


def test_http_error_404() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"error": {"code": 404, "message": "Locator not found"}},
        )

    transport = httpx.MockTransport(handler)
    with HonuaGeocodingClient("http://example.test", client=httpx.Client(base_url="http://example.test/", transport=transport)) as client:
        with pytest.raises(HonuaHttpError) as exc_info:
            client.forward_geocode("test")

    err = exc_info.value
    assert err.status_code == 404
    assert err.message == "Locator not found"
    assert isinstance(err.body, dict)


def test_http_error_500() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            500,
            json={"error": {"code": 500, "message": "Server error"}},
        )

    transport = httpx.MockTransport(handler)
    with HonuaGeocodingClient("http://example.test", client=httpx.Client(base_url="http://example.test/", transport=transport)) as client:
        with pytest.raises(HonuaHttpError) as exc_info:
            client.suggest("test")

    err = exc_info.value
    assert err.status_code == 500
    assert err.message == "Server error"


def test_transport_error_raises_honua_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    transport = httpx.MockTransport(handler)
    with HonuaGeocodingClient("http://example.test", client=httpx.Client(base_url="http://example.test/", transport=transport)) as client:
        with pytest.raises(HonuaTransportError) as exc_info:
            client.forward_geocode("test")

    err = exc_info.value
    assert "Transport error" in str(err)


def test_custom_locator_name_in_path() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(200, json={"candidates": []})

    transport = httpx.MockTransport(handler)
    with HonuaGeocodingClient(
        "http://example.test",
        locator_name="MyLocator",
        client=httpx.Client(base_url="http://example.test/", transport=transport),
    ) as client:
        client.forward_geocode("test")

    assert "/rest/services/MyLocator/GeocodeServer/findAddressCandidates" in seen["path"]


# ---------------------------------------------------------------------------
# Null-island guard (issue #106): missing location must not become (0, 0)
# ---------------------------------------------------------------------------


def _geocode_client(handler: Any) -> HonuaGeocodingClient:
    transport = httpx.MockTransport(handler)
    return HonuaGeocodingClient(
        "http://example.test",
        client=httpx.Client(base_url="http://example.test/", transport=transport),
    )


def test_forward_geocode_skips_candidates_without_location() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"address": "no loc", "score": 90.0},
                    {"address": "empty loc", "location": {}, "score": 80.0},
                    {
                        "address": "real",
                        "location": {"x": -117.1, "y": 32.7},
                        "score": 95.0,
                    },
                ]
            },
        )

    with _geocode_client(handler) as client:
        results = client.forward_geocode("test")

    # Only the candidate with a usable location survives; no (0, 0) entries.
    assert len(results) == 1
    assert results[0].address == "real"
    assert (results[0].longitude, results[0].latitude) == (-117.1, 32.7)
    assert all((r.longitude, r.latitude) != (0.0, 0.0) for r in results)


def test_reverse_geocode_missing_location_returns_none() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        # Location present but empty, and no address -> no match.
        return httpx.Response(200, json={"location": {}})

    with _geocode_client(handler) as client:
        result = client.reverse_geocode(32.7, -117.1)

    assert result is None


def test_reverse_geocode_address_without_location_keeps_address() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"address": {"Match_addr": "123 Main St"}})

    with _geocode_client(handler) as client:
        result = client.reverse_geocode(32.7, -117.1)

    assert result is not None
    assert result.address == "123 Main St"
