"""Regression tests for path-segment and raw request-path hardening."""

from __future__ import annotations

import httpx
import pytest
from honua_admin import AsyncHonuaAdminClient, HonuaAdminClient

from honua_sdk import AsyncHonuaClient, HonuaClient
from honua_sdk.http import encode_path_segment, encode_request_path


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize(
    "bad_segment",
    [
        "",
        "   ",
        ".",
        "..",
        "bad\r\nX-Injected: 1",
        "bad\nline",
        "bad\x00null",
        "bad\ttab",
        "bad\x1funit",
        "bad\x7fdel",
    ],
)
def test_encode_path_segment_rejects_empty_dot_and_control_chars(bad_segment: str) -> None:
    with pytest.raises(ValueError):
        encode_path_segment(bad_segment)


@pytest.mark.parametrize(
    ("segment", "expected"),
    [
        ("Parcels", "Parcels"),
        ("Field Survey", "Field%20Survey"),
        ("v1.2", "v1.2"),
        ("..parcels", "..parcels"),
        ("folder/sub", "folder%2Fsub"),
        ("Caf\u00e9", "Caf%C3%A9"),
    ],
)
def test_encode_path_segment_preserves_valid_identifiers(segment: str, expected: str) -> None:
    assert encode_path_segment(segment) == expected


@pytest.mark.parametrize(
    "bad_path",
    [
        "/rest/services/a\r\nX-Injected: 1",
        "/rest/services/a\nb",
        "/rest/services/a\x00b",
        "/rest/services/a\x1fb",
        "/rest/services/a\x7fb",
    ],
)
def test_encode_request_path_rejects_control_characters(bad_path: str) -> None:
    with pytest.raises(ValueError):
        encode_request_path(bad_path)


def test_encode_request_path_preserves_ascii_and_non_ascii_paths() -> None:
    assert encode_request_path("/rest/services/Field%20Survey/FeatureServer") == (
        b"/rest/services/Field%20Survey/FeatureServer"
    )
    assert encode_request_path("/ogc/features/collections/Caf\u00e9/items") == (
        b"/ogc/features/collections/Caf%C3%A9/items"
    )


@pytest.mark.parametrize("bad_id", [".", "..", "", " ", "evil\r\nheader"])
def test_sdk_client_refuses_hostile_path_segments_before_http_send(bad_id: str) -> None:
    def fail_if_called(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"Hostile identifier must fail before HTTP send: {request.url}")

    with HonuaClient("https://test.honua.io", transport=httpx.MockTransport(fail_if_called)) as client:
        with pytest.raises(ValueError):
            client.query_features(bad_id, 0)
        with pytest.raises(ValueError):
            client.ogc_features().items(bad_id)


@pytest.mark.anyio
@pytest.mark.parametrize("bad_id", [".", "..", "", "evil\r\nheader"])
async def test_async_sdk_client_refuses_hostile_path_segments_before_http_send(bad_id: str) -> None:
    def fail_if_called(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"Hostile identifier must fail before HTTP send: {request.url}")

    async with AsyncHonuaClient("https://test.honua.io", transport=httpx.MockTransport(fail_if_called)) as client:
        with pytest.raises(ValueError):
            await client.query_features(bad_id, 0)


@pytest.mark.parametrize("bad_id", [".", "..", "", " ", "evil\r\nheader"])
def test_admin_client_refuses_hostile_path_segments_before_http_send(bad_id: str) -> None:
    def fail_if_called(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"Hostile admin identifier must fail before HTTP send: {request.url}")

    with HonuaAdminClient("https://test.honua.io", transport=httpx.MockTransport(fail_if_called)) as admin:
        with pytest.raises(ValueError):
            admin.get_service_settings(bad_id)
        with pytest.raises(ValueError):
            admin.delete_folder(bad_id, if_match="*")
        with pytest.raises(ValueError):
            admin.get_connection(bad_id)
        with pytest.raises(ValueError):
            admin.approve_proposal(bad_id)
        with pytest.raises(ValueError):
            admin.get_style_metadata(bad_id)


@pytest.mark.anyio
@pytest.mark.parametrize("bad_id", [".", "..", "", "evil\r\nheader"])
async def test_async_admin_client_refuses_hostile_path_segments_before_http_send(bad_id: str) -> None:
    def fail_if_called(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"Hostile admin identifier must fail before HTTP send: {request.url}")

    async with AsyncHonuaAdminClient("https://test.honua.io", transport=httpx.MockTransport(fail_if_called)) as admin:
        with pytest.raises(ValueError):
            await admin.delete_folder(bad_id, if_match="*")
