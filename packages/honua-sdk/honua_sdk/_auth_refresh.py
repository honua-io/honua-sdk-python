"""Reactive credential-refresh helpers for HTTP 401 and GeoServices 498/499 challenges."""

from __future__ import annotations

import inspect
from collections.abc import Mapping

import httpx
from anyio import to_thread

from ._http import _auth_provider_headers, _resolve_dynamic_auth_headers_async
from ._retry_core import AsyncAuthRefreshHook, AuthRefreshHook
from .auth import SENSITIVE_AUTH_HEADER_NAMES, AuthProvider

__all__ = [
    "build_auth_refresh_hook",
    "build_auth_refresh_hook_async",
    "refresh_auth_headers",
    "refresh_auth_headers_async",
]


def _replace_sensitive_auth_headers(request: httpx.Request, headers: Mapping[str, str]) -> bool:
    if not headers:
        return False
    for name in SENSITIVE_AUTH_HEADER_NAMES:
        request.headers.pop(name, None)
    for name, value in headers.items():
        request.headers[name] = value
    return True


def _invoke_provider_refresh(auth_provider: AuthProvider) -> bool:
    refresh_fn = getattr(auth_provider, "refresh", None)
    if not callable(refresh_fn):
        return False
    refresh_fn()
    return True


async def _invoke_provider_refresh_async(auth_provider: AuthProvider) -> bool:
    refresh_fn = getattr(auth_provider, "refresh", None)
    if not callable(refresh_fn):
        return False
    if inspect.iscoroutinefunction(refresh_fn):
        await refresh_fn()
        return True
    result = await to_thread.run_sync(refresh_fn)
    if inspect.isawaitable(result):
        await result
    return True


def refresh_auth_headers(
    request: httpx.Request,
    *,
    trusted_authority: tuple[str, str, int | None] | None,
    auth_provider: AuthProvider | None = None,
) -> bool:
    """Force-refresh credentials on a trusted origin after an auth challenge."""
    if trusted_authority is None or auth_provider is None:
        return False
    request_authority = (request.url.scheme, request.url.host, request.url.port)
    if request_authority != trusted_authority:
        return False
    if not _invoke_provider_refresh(auth_provider):
        return False
    return _replace_sensitive_auth_headers(request, _auth_provider_headers(auth_provider))


async def refresh_auth_headers_async(
    request: httpx.Request,
    *,
    trusted_authority: tuple[str, str, int | None] | None,
    auth_provider: AuthProvider | None = None,
) -> bool:
    """Async variant of :func:`refresh_auth_headers`."""
    if trusted_authority is None or auth_provider is None:
        return False
    request_authority = (request.url.scheme, request.url.host, request.url.port)
    if request_authority != trusted_authority:
        return False
    if not await _invoke_provider_refresh_async(auth_provider):
        return False
    dynamic_headers = await _resolve_dynamic_auth_headers_async(auth_provider)
    return _replace_sensitive_auth_headers(request, dynamic_headers)


def build_auth_refresh_hook(
    trusted_authority: tuple[str, str, int | None] | None,
    auth_provider: AuthProvider | None,
) -> AuthRefreshHook | None:
    """Return a sync auth-refresh callback bound to *trusted_authority*, or ``None``."""
    if auth_provider is None:
        return None

    def _hook(request: httpx.Request) -> bool:
        return refresh_auth_headers(
            request,
            trusted_authority=trusted_authority,
            auth_provider=auth_provider,
        )

    return _hook


def build_auth_refresh_hook_async(
    trusted_authority: tuple[str, str, int | None] | None,
    auth_provider: AuthProvider | None,
) -> AsyncAuthRefreshHook | None:
    """Return an async auth-refresh callback bound to *trusted_authority*, or ``None``."""
    if auth_provider is None:
        return None

    async def _hook(request: httpx.Request) -> bool:
        return await refresh_auth_headers_async(
            request,
            trusted_authority=trusted_authority,
            auth_provider=auth_provider,
        )

    return _hook
