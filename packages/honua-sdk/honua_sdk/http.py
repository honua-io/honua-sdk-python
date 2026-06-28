"""Public HTTP utility surface shared with first-party Honua packages.

This module is the supported import boundary for first-party packages
(e.g. ``honua-admin``) that need to reuse the SDK's HTTP transport,
auth-header handling, URL normalization, retry transports, and error
translation. Importing these symbols from this module — rather than
from the historical leading-underscore :mod:`honua_sdk._shared` or
:mod:`honua_sdk._http` modules — signals that the dependency is part
of the SDK's intentional public-for-first-parties surface.

Canonical public names (use these in new code)
----------------------------------------------

Transports / auth / error helpers:

* :class:`AsyncRetryTransport`
* :class:`RetryTransport`
* :class:`AuthProvider`

HTTP helpers (no leading underscore):

* :func:`normalize_base_url`        — strip + re-append trailing slash
* :func:`encode_path_segment`       — URL-safe path segment encoder
* :func:`build_sensitive_auth_headers`
* :func:`apply_sensitive_auth_headers`
* :func:`apply_sensitive_auth_headers_async` — awaitable variant for async
  clients; resolves dynamic/async auth providers without blocking the loop
* :func:`extract_trusted_authority`
* :func:`validate_auth_configuration`
* :func:`validate_external_client_auth_configuration`
* :func:`warn_deprecated_bearer_token`
* :func:`to_http_error`             — :class:`httpx.Response` → :class:`HonuaHttpError`
* :func:`to_transport_error`        — :class:`httpx.HTTPError` → :class:`HonuaTransportError`
* :func:`parse_retry_after`         — accepts seconds-int or HTTP-date

Error classes:

* :class:`HonuaAuthError`, :class:`HonuaHttpError`, :class:`HonuaRateLimitError`,
  :class:`HonuaTimeoutError`, :class:`HonuaTransportError`

Back-compat aliases
-------------------

The original leading-underscore names
(``_apply_sensitive_auth_headers``, ``_build_sensitive_auth_headers``,
``_encode_path_segment``, ``_extract_trusted_authority``,
``_normalize_base_url``, ``_to_http_error``, ``_to_transport_error``,
``_validate_auth_configuration``,
``_validate_external_client_auth_configuration``) are kept as aliases
for first-party packages still pinned to the underscore spelling, and
remain re-exported from :mod:`honua_sdk._shared`. New code should use
the canonical names above.
"""

from __future__ import annotations

from ._async_retry import AsyncNonClosingTransport, AsyncRetryTransport
from ._http import (
    _apply_sensitive_auth_headers,
    _apply_sensitive_auth_headers_async,
    _build_sensitive_auth_headers,
    _encode_path_segment,
    _extract_trusted_authority,
    _normalize_base_url,
    _parse_retry_after,
    _to_http_error,
    _to_transport_error,
    _validate_auth_configuration,
    _validate_external_client_auth_configuration,
    _warn_deprecated_bearer_token,
)
from ._retry import NonClosingTransport, RetryTransport
from .auth import AuthProvider
from .errors import (
    HonuaAuthError,
    HonuaHttpError,
    HonuaRateLimitError,
    HonuaTimeoutError,
    HonuaTransportError,
)

# Canonical (non-underscore) aliases. The underscore-prefixed originals
# remain importable for back-compat with code pinned to those names.
apply_sensitive_auth_headers = _apply_sensitive_auth_headers
apply_sensitive_auth_headers_async = _apply_sensitive_auth_headers_async
build_sensitive_auth_headers = _build_sensitive_auth_headers
encode_path_segment = _encode_path_segment
extract_trusted_authority = _extract_trusted_authority
normalize_base_url = _normalize_base_url
parse_retry_after = _parse_retry_after
to_http_error = _to_http_error
to_transport_error = _to_transport_error
validate_auth_configuration = _validate_auth_configuration
validate_external_client_auth_configuration = _validate_external_client_auth_configuration
warn_deprecated_bearer_token = _warn_deprecated_bearer_token

__all__ = [
    "AsyncNonClosingTransport",
    "AsyncRetryTransport",
    "AuthProvider",
    "HonuaAuthError",
    "HonuaHttpError",
    "HonuaRateLimitError",
    "HonuaTimeoutError",
    "HonuaTransportError",
    "NonClosingTransport",
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
    "_warn_deprecated_bearer_token",
    "apply_sensitive_auth_headers",
    "apply_sensitive_auth_headers_async",
    "build_sensitive_auth_headers",
    "encode_path_segment",
    "extract_trusted_authority",
    "normalize_base_url",
    "parse_retry_after",
    "to_http_error",
    "to_transport_error",
    "validate_auth_configuration",
    "validate_external_client_auth_configuration",
    "warn_deprecated_bearer_token",
]
