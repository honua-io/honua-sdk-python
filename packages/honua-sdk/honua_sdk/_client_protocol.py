"""Typed structural protocols for the host-client transport surface.

Facade clients (for example :mod:`honua_sdk.geoprocessing`) need only a thin
slice of the bound :class:`~honua_sdk.client.HonuaClient` /
:class:`~honua_sdk.async_client.AsyncHonuaClient`: the low-level request
methods. Depending on these :class:`typing.Protocol` contracts instead of
``Any`` documents exactly what a facade requires from its host client and lets
the type checker verify it -- without leaking the full concrete client surface
or its private internals into the facade.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

import httpx

Params = Mapping[str, Any] | None


class SupportsSyncRequest(Protocol):
    """The synchronous request surface a facade client depends on."""

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
        files: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]: ...

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
        files: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response: ...


class SupportsAsyncRequest(Protocol):
    """The asynchronous request surface a facade client depends on."""

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
        files: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]: ...

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
        files: Mapping[str, Any] | None = None,
        data: Mapping[str, Any] | None = None,
        content: bytes | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response: ...
