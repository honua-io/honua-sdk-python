"""Compatibility coverage for admin's shared SDK utility boundary."""

from __future__ import annotations

from honua_admin import _async_client as admin_async_client
from honua_admin import _client as admin_client
from honua_sdk import _shared
from honua_sdk._async_retry import AsyncRetryTransport
from honua_sdk._http import (
    _apply_sensitive_auth_headers,
    _build_sensitive_auth_headers,
    _encode_path_segment,
    _extract_trusted_authority,
    _normalize_base_url,
    _to_http_error,
    _to_transport_error,
    _validate_auth_configuration,
    _validate_external_client_auth_configuration,
)
from honua_sdk._retry import RetryTransport
from honua_sdk.auth import AuthProvider
from honua_sdk.errors import HonuaHttpError


def test_shared_sdk_boundary_reexports_admin_dependencies() -> None:
    assert _shared.AsyncRetryTransport is AsyncRetryTransport
    assert _shared.AuthProvider is AuthProvider
    assert _shared.HonuaHttpError is HonuaHttpError
    assert _shared.RetryTransport is RetryTransport
    assert _shared._apply_sensitive_auth_headers is _apply_sensitive_auth_headers
    assert _shared._build_sensitive_auth_headers is _build_sensitive_auth_headers
    assert _shared._encode_path_segment is _encode_path_segment
    assert _shared._extract_trusted_authority is _extract_trusted_authority
    assert _shared._normalize_base_url is _normalize_base_url
    assert _shared._to_http_error is _to_http_error
    assert _shared._to_transport_error is _to_transport_error
    assert _shared._validate_auth_configuration is _validate_auth_configuration
    assert (
        _shared._validate_external_client_auth_configuration
        is _validate_external_client_auth_configuration
    )


def test_admin_clients_use_shared_sdk_boundary() -> None:
    assert admin_client.AuthProvider is _shared.AuthProvider
    assert admin_client.HonuaHttpError is _shared.HonuaHttpError
    assert admin_client.RetryTransport is _shared.RetryTransport
    assert admin_client._apply_sensitive_auth_headers is _shared._apply_sensitive_auth_headers
    assert admin_client._encode_path_segment is _shared._encode_path_segment
    assert admin_client._to_http_error is _shared._to_http_error

    assert admin_async_client.AsyncRetryTransport is _shared.AsyncRetryTransport
    assert admin_async_client.AuthProvider is _shared.AuthProvider
    assert admin_async_client.HonuaHttpError is _shared.HonuaHttpError
    assert admin_async_client._apply_sensitive_auth_headers is _shared._apply_sensitive_auth_headers
    assert admin_async_client._encode_path_segment is _shared._encode_path_segment
    assert admin_async_client._to_http_error is _shared._to_http_error
