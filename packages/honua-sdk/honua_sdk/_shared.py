"""Shared internal SDK utilities for first-party Honua packages.

This module is not part of the public ``honua_sdk`` API. It is the stable
internal import boundary for first-party packages such as ``honua-admin`` that
need to reuse SDK HTTP, auth, error, and retry behavior without depending on
the lower-level implementation modules directly.
"""

from __future__ import annotations

from ._async_retry import AsyncRetryTransport
from ._http import (
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
from ._retry import RetryTransport
from .auth import AuthProvider
from .errors import HonuaHttpError

__all__ = [
    "AsyncRetryTransport",
    "AuthProvider",
    "HonuaHttpError",
    "RetryTransport",
    "_apply_sensitive_auth_headers",
    "_build_sensitive_auth_headers",
    "_encode_path_segment",
    "_extract_trusted_authority",
    "_normalize_base_url",
    "_to_http_error",
    "_to_transport_error",
    "_validate_auth_configuration",
    "_validate_external_client_auth_configuration",
]
