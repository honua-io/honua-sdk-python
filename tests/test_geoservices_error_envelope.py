"""GeoServices error-envelope handling (HTTP 200 + ``{"error": {...}}``).

The Esri GeoServices REST protocol reports failures as an HTTP 200 response
whose body is ``{"error": {"code": <int>, "message": <str>, ...}}``. These
tests pin that such envelopes raise :class:`HonuaHttpError` instead of being
returned to callers as success data (audit AUD-091, issue #122).
"""

from __future__ import annotations

import httpx
import pytest

from honua_sdk import HonuaAuthError, HonuaClient, HonuaGeocodingClient, HonuaHttpError
from honua_sdk._endpoints import parse_json_response_body


def _envelope_handler(code: int = 400, message: str = "Unable to complete operation.") -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"error": {"code": code, "message": message, "details": []}})

    return httpx.MockTransport(handler)


def test_query_features_raises_on_error_envelope() -> None:
    with HonuaClient("http://example.test", transport=_envelope_handler(code=400)) as client:
        with pytest.raises(HonuaHttpError) as excinfo:
            client.query_features("Parcels", 0, where="1=1")
    assert excinfo.value.status_code == 400
    assert "Unable to complete" in str(excinfo.value)


def test_apply_edits_raises_auth_on_token_required_envelope() -> None:
    # Esri code 499 (Token Required) is an application code, not an HTTP status:
    # it must surface as HonuaAuthError (catchable via ``except HonuaAuthError``)
    # while preserving the original Esri code on ``error_code`` and normalizing
    # the HTTP ``status_code`` surface to 403.
    with HonuaClient(
        "http://example.test", transport=_envelope_handler(code=499, message="Token Required")
    ) as client:
        with pytest.raises(HonuaAuthError) as excinfo:
            client.apply_edits("Parcels", 0, adds=[{"attributes": {"NAME": "x"}}])
    assert excinfo.value.error_code == 499
    assert excinfo.value.status_code == 403


def test_invalid_token_envelope_maps_to_auth_error() -> None:
    # Esri code 498 (Invalid Token) likewise maps to HonuaAuthError.
    with HonuaClient(
        "http://example.test", transport=_envelope_handler(code=498, message="Invalid Token")
    ) as client:
        with pytest.raises(HonuaAuthError) as excinfo:
            client.query_features("Parcels", 0, where="1=1")
    assert excinfo.value.error_code == 498
    assert excinfo.value.status_code == 403


def test_exotic_negative_code_normalizes_status_but_preserves_error_code() -> None:
    # A large negative HRESULT-style code must not be surfaced verbatim as an HTTP
    # status; it normalizes to 500 while the original code is kept on error_code.
    with HonuaClient(
        "http://example.test", transport=_envelope_handler(code=-2147217395, message="Workspace error")
    ) as client:
        with pytest.raises(HonuaHttpError) as excinfo:
            client.query_features("Parcels", 0, where="1=1")
    assert excinfo.value.error_code == -2147217395
    assert excinfo.value.status_code == 500


def test_list_services_raises_on_error_envelope() -> None:
    with HonuaClient("http://example.test", transport=_envelope_handler(code=500)) as client:
        with pytest.raises(HonuaHttpError):
            client.list_services()


def test_geocode_raises_on_error_envelope() -> None:
    with HonuaGeocodingClient(
        "http://example.test", transport=_envelope_handler(code=400, message="Invalid locator")
    ) as client:
        with pytest.raises(HonuaHttpError) as excinfo:
            client.forward_geocode("123 Main St")
    assert excinfo.value.status_code == 400


def test_normal_payload_with_error_named_field_is_not_treated_as_envelope() -> None:
    # A legitimate result that merely contains an ``error`` field that is not the
    # GeoServices envelope (no integer ``code``) must pass through untouched.
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"features": [], "error": "rate", "count": 0})

    with HonuaClient("http://example.test", transport=httpx.MockTransport(handler)) as client:
        result = client.query_features("Parcels", 0)
    assert result == {"features": [], "error": "rate", "count": 0}


class _StubResponse:
    def __init__(self, payload: object) -> None:
        self.content = b"{}"
        self._payload = payload
        self.text = ""
        self.reason_phrase = "OK"
        self.headers: dict[str, str] = {}

    def json(self) -> object:
        return self._payload


def test_parse_json_response_body_raises_on_error_envelope() -> None:
    response = _StubResponse({"error": {"code": 403, "message": "Forbidden"}})
    with pytest.raises(HonuaHttpError) as excinfo:
        parse_json_response_body(response)  # type: ignore[arg-type]
    assert excinfo.value.status_code == 403


def test_parse_json_response_body_ignores_bool_code() -> None:
    # ``True`` is an ``int`` subclass; the envelope check must not fire on it.
    response = _StubResponse({"error": {"code": True}})
    assert parse_json_response_body(response) == {"error": {"code": True}}  # type: ignore[arg-type]
