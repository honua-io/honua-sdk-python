"""Tests for admin service settings endpoints."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from honua_sdk import CallableAuthProvider, HonuaHttpError
from honua_sdk.errors import HonuaTransportError
from honua_admin import (
    HonuaAdminClient,
    ServiceSettingsResponse,
    ServiceSummary,
)
from .conftest import make_api_response


def test_list_services_returns_typed_summaries(make_client) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        return httpx.Response(
            200,
            json=make_api_response([
                {
                    "serviceName": "default",
                    "description": "Default service",
                    "layerCount": 5,
                    "enabledProtocols": ["FeatureServer", "MapServer"],
                },
                {
                    "serviceName": "testing",
                    "description": None,
                    "layerCount": 0,
                    "enabledProtocols": [],
                },
            ]),
        )

    with make_client(handler) as client:
        result = client.list_services()

    assert seen["method"] == "GET"
    assert seen["path"] == "/api/v1/admin/services/"
    assert len(result) == 2
    assert isinstance(result[0], ServiceSummary)
    assert result[0].service_name == "default"
    assert result[0].layer_count == 5
    assert result[0].enabled_protocols == ["FeatureServer", "MapServer"]
    assert result[1].service_name == "testing"
    assert result[1].layer_count == 0


def test_get_service_settings_returns_nested_models(make_client) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        return httpx.Response(
            200,
            json=make_api_response({
                "serviceName": "default",
                "enabledProtocols": ["FeatureServer"],
                "availableProtocols": ["FeatureServer", "MapServer", "OGC"],
                "accessPolicy": {
                    "allowAnonymous": True,
                    "allowAnonymousWrite": False,
                    "allowedRoles": ["admin"],
                    "allowedWriteRoles": [],
                },
                "timeInfo": {
                    "startTimeField": "created",
                    "endTimeField": None,
                    "trackIdField": None,
                },
                "mapServer": {
                    "maxImageWidth": 4096,
                    "maxImageHeight": 4096,
                    "defaultImageWidth": 800,
                    "defaultImageHeight": 600,
                    "defaultDpi": 96,
                    "defaultFormat": "png",
                    "defaultTransparent": True,
                    "maxFeaturesPerLayer": 5000,
                },
            }),
        )

    with make_client(handler) as client:
        result = client.get_service_settings("default")

    assert seen["path"] == "/api/v1/admin/services/default/settings"
    assert isinstance(result, ServiceSettingsResponse)
    assert result.service_name == "default"
    assert result.enabled_protocols == ["FeatureServer"]

    assert result.access_policy is not None
    assert result.access_policy.allow_anonymous is True
    assert result.access_policy.allow_anonymous_write is False
    assert result.access_policy.allowed_roles == ["admin"]

    assert result.time_info is not None
    assert result.time_info.start_time_field == "created"

    assert result.map_server is not None
    assert result.map_server.max_image_width == 4096
    assert result.map_server.default_format == "png"


def test_update_protocols_sends_list_body(make_client) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json=make_api_response({
                "serviceName": "default",
                "enabledProtocols": ["FeatureServer", "OGC"],
                "availableProtocols": ["FeatureServer", "MapServer", "OGC"],
                "accessPolicy": None,
                "timeInfo": None,
                "mapServer": None,
            }),
        )

    with make_client(handler) as client:
        result = client.update_protocols("default", ["FeatureServer", "OGC"])

    assert seen["method"] == "PUT"
    assert seen["path"] == "/api/v1/admin/services/default/protocols"
    assert seen["body"] == ["FeatureServer", "OGC"]
    assert isinstance(result, ServiceSettingsResponse)
    assert result.enabled_protocols == ["FeatureServer", "OGC"]


def test_update_mapserver_settings_converts_to_camel(make_client) -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(
            200,
            json=make_api_response({
                "serviceName": "default",
                "enabledProtocols": ["FeatureServer"],
                "availableProtocols": ["FeatureServer"],
                "accessPolicy": None,
                "timeInfo": None,
                "mapServer": {
                    "maxImageWidth": 8192,
                    "maxImageHeight": 8192,
                    "defaultImageWidth": 800,
                    "defaultImageHeight": 600,
                    "defaultDpi": 96,
                    "defaultFormat": "png",
                    "defaultTransparent": True,
                    "maxFeaturesPerLayer": 10000,
                },
            }),
        )

    with make_client(handler) as client:
        result = client.update_mapserver_settings(
            "default",
            max_image_width=8192,
            max_image_height=8192,
            max_features_per_layer=10000,
        )

    assert seen["method"] == "PUT"
    assert seen["path"] == "/api/v1/admin/services/default/mapserver"
    assert seen["body"]["maxImageWidth"] == 8192
    assert seen["body"]["maxImageHeight"] == 8192
    assert seen["body"]["maxFeaturesPerLayer"] == 10000
    assert result.map_server is not None
    assert result.map_server.max_image_width == 8192


def test_list_services_404_raises_http_error(make_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            404,
            json={"message": "Not found"},
        )

    with make_client(handler) as client:
        with pytest.raises(HonuaHttpError) as exc_info:
            client.list_services()

    assert exc_info.value.status_code == 404


def test_update_protocols_400_raises_http_error(make_client) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"message": "Invalid protocol list"},
        )

    with make_client(handler) as client:
        with pytest.raises(HonuaHttpError) as exc_info:
            client.update_protocols("default", ["InvalidProtocol"])

    assert exc_info.value.status_code == 400
    assert "Invalid protocol" in exc_info.value.message


def test_does_not_follow_redirects_by_default() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((str(request.url), request.headers.get("x-api-key", "")))
        if request.url.host == "test.honua.io":
            return httpx.Response(
                302,
                headers={"Location": "https://evil.example/api/v1/admin/services/"},
            )
        raise AssertionError("Redirect target should not be requested by default")

    transport = httpx.MockTransport(handler)
    with HonuaAdminClient(
        "http://test.honua.io",
        transport=transport,
        api_key="test-key",
    ) as client:
        result = client.list_services()

    assert result == []
    assert len(seen) == 1
    assert seen[0][0] == "http://test.honua.io/api/v1/admin/services/"
    assert seen[0][1] == "test-key"


def test_follow_redirects_does_not_forward_sensitive_headers_to_different_host() -> None:
    seen: list[tuple[str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            (
                request.url.host or "",
                request.headers.get("x-api-key", ""),
                request.headers.get("authorization", ""),
            )
        )
        if request.url.host == "test.honua.io":
            return httpx.Response(
                302,
                headers={"Location": "https://evil.example/api/v1/admin/services/"},
            )
        return httpx.Response(
            200,
            json=make_api_response([]),
        )

    transport = httpx.MockTransport(handler)
    with HonuaAdminClient(
        "http://test.honua.io",
        transport=transport,
        api_key="test-key",
        bearer_token="test-token",
        follow_redirects=True,
    ) as client:
        result = client.list_services()

    assert result == []
    assert len(seen) == 2
    assert seen[0] == ("test.honua.io", "test-key", "Bearer test-token")
    assert seen[1] == ("evil.example", "", "")


def test_admin_client_auth_provider_headers_are_resolved_per_request() -> None:
    seen: list[str] = []
    api_keys = iter(["admin-key-1", "admin-key-2"])

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("x-api-key", ""))
        return httpx.Response(200, json=make_api_response([]))

    transport = httpx.MockTransport(handler)
    auth_provider = CallableAuthProvider(lambda: {"X-API-Key": next(api_keys)})

    with HonuaAdminClient("http://test.honua.io", transport=transport, auth_provider=auth_provider) as client:
        client.list_services()
        client.list_services()

    assert seen == ["admin-key-1", "admin-key-2"]


def test_custom_http_client_rejects_sdk_auth_options() -> None:
    client = httpx.Client(
        base_url="http://test.honua.io",
        transport=httpx.MockTransport(lambda request: httpx.Response(200)),
    )
    try:
        with pytest.raises(ValueError, match="supplied `client`"):
            HonuaAdminClient("http://ignored.test", client=client, api_key="test-key")
    finally:
        client.close()


def test_transport_errors_are_normalized_to_honua_transport_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("dial failed", request=request)

    transport = httpx.MockTransport(handler)
    with HonuaAdminClient("http://test.honua.io", transport=transport) as client:
        with pytest.raises(HonuaTransportError) as exc_info:
            client.list_services()

    err = exc_info.value
    assert "Transport error: dial failed" in str(err)
    assert err.cause_type == "ConnectError"
    assert err.url == "http://test.honua.io/api/v1/admin/services/"
