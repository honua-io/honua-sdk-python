"""Compatibility coverage for admin's shared SDK utility boundary."""

from __future__ import annotations

from honua_admin import _async_client as admin_async_client
from honua_admin import _client as admin_client
from honua_sdk import _shared, http as honua_http
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


def test_public_http_module_reexports_admin_dependencies() -> None:
    """``honua_sdk.http`` is the supported public boundary; verify identity."""
    assert honua_http.AsyncRetryTransport is AsyncRetryTransport
    assert honua_http.AuthProvider is AuthProvider
    assert honua_http.HonuaHttpError is HonuaHttpError
    assert honua_http.RetryTransport is RetryTransport
    assert honua_http._apply_sensitive_auth_headers is _apply_sensitive_auth_headers
    assert honua_http._build_sensitive_auth_headers is _build_sensitive_auth_headers
    assert honua_http._encode_path_segment is _encode_path_segment
    assert honua_http._extract_trusted_authority is _extract_trusted_authority
    assert honua_http._normalize_base_url is _normalize_base_url
    assert honua_http._to_http_error is _to_http_error
    assert honua_http._to_transport_error is _to_transport_error
    assert honua_http._validate_auth_configuration is _validate_auth_configuration
    assert (
        honua_http._validate_external_client_auth_configuration
        is _validate_external_client_auth_configuration
    )


def test_shared_sdk_boundary_reexports_admin_dependencies() -> None:
    """``honua_sdk._shared`` is a back-compat alias for ``honua_sdk.http``."""
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


def test_admin_clients_use_public_http_boundary() -> None:
    """Admin clients import the canonical non-underscore public names."""
    assert admin_client.AuthProvider is honua_http.AuthProvider
    assert admin_client.HonuaHttpError is honua_http.HonuaHttpError
    assert admin_client.RetryTransport is honua_http.RetryTransport
    assert admin_client.apply_sensitive_auth_headers is honua_http.apply_sensitive_auth_headers
    assert admin_client.encode_path_segment is honua_http.encode_path_segment
    assert admin_client.to_http_error is honua_http.to_http_error

    assert admin_async_client.AsyncRetryTransport is honua_http.AsyncRetryTransport
    assert admin_async_client.AuthProvider is honua_http.AuthProvider
    assert admin_async_client.HonuaHttpError is honua_http.HonuaHttpError
    assert (
        admin_async_client.apply_sensitive_auth_headers_async
        is honua_http.apply_sensitive_auth_headers_async
    )
    assert admin_async_client.encode_path_segment is honua_http.encode_path_segment
    assert admin_async_client.to_http_error is honua_http.to_http_error
