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

from collections.abc import Mapping, Sequence
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


class SupportsSyncFeatureService(SupportsSyncRequest, Protocol):
    """Sync host surface a GeoServices FeatureServer facade depends on.

    Extends the bare request surface with the high-level FeatureServer
    convenience methods (``query_features`` / ``apply_edits``) that the
    facade delegates to on its bound client.
    """

    def query_features(
        self,
        service_id: str,
        layer_id: int,
        *,
        where: str = "1=1",
        out_fields: str | Sequence[str] = "*",
        return_geometry: bool = True,
        extra_params: Mapping[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]: ...

    def apply_edits(
        self,
        service_id: str,
        layer_id: int,
        *,
        adds: Sequence[Mapping[str, Any]] | None = None,
        updates: Sequence[Mapping[str, Any]] | None = None,
        deletes: Sequence[int] | str | None = None,
        rollback_on_failure: bool = True,
        idempotency_key: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]: ...


class SupportsSyncMapService(SupportsSyncRequest, Protocol):
    """Sync host surface a GeoServices MapServer facade depends on.

    Extends the bare request surface with the high-level ``export_map``
    convenience method the facade delegates to on its bound client.
    """

    def export_map(
        self,
        service_id: str,
        bbox: Sequence[float] | str,
        *,
        size: tuple[int, int] = (400, 400),
        image_format: str = "png",
        transparent: bool = True,
        dpi: int = 96,
        extra_params: Mapping[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> bytes: ...


class SupportsAsyncFeatureService(SupportsAsyncRequest, Protocol):
    """Async host surface a GeoServices FeatureServer facade depends on.

    Extends the bare request surface with the high-level FeatureServer
    convenience methods (``query_features`` / ``apply_edits``) that the
    facade delegates to on its bound client.
    """

    async def query_features(
        self,
        service_id: str,
        layer_id: int,
        *,
        where: str = "1=1",
        out_fields: str | Sequence[str] = "*",
        return_geometry: bool = True,
        extra_params: Mapping[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]: ...

    async def apply_edits(
        self,
        service_id: str,
        layer_id: int,
        *,
        adds: Sequence[Mapping[str, Any]] | None = None,
        updates: Sequence[Mapping[str, Any]] | None = None,
        deletes: Sequence[int] | str | None = None,
        rollback_on_failure: bool = True,
        idempotency_key: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]: ...


class SupportsAsyncMapService(SupportsAsyncRequest, Protocol):
    """Async host surface a GeoServices MapServer facade depends on.

    Extends the bare request surface with the high-level ``export_map``
    convenience method the facade delegates to on its bound client.
    """

    async def export_map(
        self,
        service_id: str,
        bbox: Sequence[float] | str,
        *,
        size: tuple[int, int] = (400, 400),
        image_format: str = "png",
        transparent: bool = True,
        dpi: int = 96,
        extra_params: Mapping[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> bytes: ...
