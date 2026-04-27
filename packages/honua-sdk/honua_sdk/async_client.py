"""Asynchronous HTTP client for Honua Server APIs."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

import httpx

from ._async_retry import AsyncRetryTransport
from ._http import (
    _apply_sensitive_auth_headers,
    _build_sensitive_auth_headers,
    _encode_path_segment,
    _extract_trusted_authority,
    _normalize_base_url,
    _to_http_error,
    _to_transport_error,
)

if TYPE_CHECKING:
    from .ogc import AsyncHonuaOgcFeatures


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


class AsyncHonuaClient:
    """Async task-oriented client for common Honua workflows."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        api_key: str | None = None,
        bearer_token: str | None = None,
        follow_redirects: bool = False,
        client: httpx.AsyncClient | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        max_retries: int = 3,
    ) -> None:
        if client is not None and transport is not None:
            raise ValueError("Provide either `client` or `transport`, not both.")

        self._owns_client = client is None
        if client is not None:
            self._client = client
            return

        normalized_base_url = _normalize_base_url(base_url)
        trusted_authority = _extract_trusted_authority(httpx.URL(normalized_base_url))
        auth_headers = _build_sensitive_auth_headers(api_key=api_key, bearer_token=bearer_token)

        async def _request_hook(request: httpx.Request) -> None:
            _apply_sensitive_auth_headers(
                request,
                trusted_authority=trusted_authority,
                auth_headers=auth_headers,
            )

        effective_transport = transport
        if max_retries > 0:
            inner = effective_transport or httpx.AsyncHTTPTransport()
            effective_transport = AsyncRetryTransport(inner, max_retries=max_retries)

        self._client = httpx.AsyncClient(
            base_url=normalized_base_url,
            timeout=timeout,
            follow_redirects=follow_redirects,
            transport=effective_transport,
            event_hooks={"request": [_request_hook]},
        )

    async def __aenter__(self) -> "AsyncHonuaClient":
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.close()

    async def close(self) -> None:
        """Release underlying resources if this instance owns the HTTP client."""
        if self._owns_client:
            await self._client.aclose()

    async def readiness(self) -> dict[str, Any]:
        """Get readiness status from ``/healthz/ready``."""
        return await self._request_json("GET", "/healthz/ready")

    async def list_services(self, *, response_format: str = "json") -> dict[str, Any]:
        """List services from the GeoServices catalog endpoint."""
        return await self._request_json(
            "GET",
            "/rest/services",
            params={"f": response_format},
        )

    def ogc_features(self) -> "AsyncHonuaOgcFeatures":
        """Return an async OGC API Features wrapper bound to this client."""
        from .ogc import AsyncHonuaOgcFeatures

        return AsyncHonuaOgcFeatures(self)

    async def query_features(
        self,
        service_id: str,
        layer_id: int,
        *,
        where: str = "1=1",
        out_fields: str | Sequence[str] = "*",
        return_geometry: bool = True,
        extra_params: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Query features from a FeatureServer layer."""
        service_segment = _encode_path_segment(service_id)
        if isinstance(out_fields, Sequence) and not isinstance(out_fields, str):
            out_fields_value = ",".join(str(value) for value in out_fields)
        else:
            out_fields_value = str(out_fields)

        params: dict[str, Any] = {
            "f": "json",
            "where": where,
            "outFields": out_fields_value,
            "returnGeometry": _bool_text(return_geometry),
        }
        if extra_params:
            params.update(extra_params)

        return await self._request_json(
            "GET",
            f"/rest/services/{service_segment}/FeatureServer/{layer_id}/query",
            params=params,
        )

    async def apply_edits(
        self,
        service_id: str,
        layer_id: int,
        *,
        adds: Sequence[Mapping[str, Any]] | None = None,
        updates: Sequence[Mapping[str, Any]] | None = None,
        deletes: Sequence[int] | str | None = None,
        rollback_on_failure: bool = True,
    ) -> dict[str, Any]:
        """Submit a layer-level applyEdits request."""
        service_segment = _encode_path_segment(service_id)
        payload: dict[str, Any] = {
            "f": "json",
            "rollbackOnFailure": rollback_on_failure,
        }
        if adds is not None:
            payload["adds"] = list(adds)
        if updates is not None:
            payload["updates"] = list(updates)
        if deletes is not None:
            if isinstance(deletes, str):
                payload["deletes"] = deletes
            else:
                payload["deletes"] = list(deletes)

        return await self._request_json(
            "POST",
            f"/rest/services/{service_segment}/FeatureServer/{layer_id}/applyEdits",
            json_body=payload,
        )

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
    ) -> bytes:
        """Request rendered map bytes from MapServer export."""
        service_segment = _encode_path_segment(service_id)
        if isinstance(bbox, str):
            bbox_value = bbox
        else:
            bbox_value = ",".join(str(value) for value in bbox)

        params: dict[str, Any] = {
            "f": "image",
            "bbox": bbox_value,
            "size": f"{size[0]},{size[1]}",
            "format": image_format,
            "transparent": _bool_text(transparent),
            "dpi": str(dpi),
        }
        if extra_params:
            params.update(extra_params)

        response = await self._request("GET", f"/rest/services/{service_segment}/MapServer/export", params=params)
        return response.content

    async def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        response = await self._request(method, path, params=params, json_body=json_body, headers=headers)
        if not response.content:
            return {}

        try:
            payload = response.json()
        except ValueError:
            return {"raw": response.text}

        if isinstance(payload, Mapping):
            return dict(payload)
        return {"data": payload}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        # Build a full URL so httpx does not re-decode percent-encoded
        # path segments during base-URL resolution.
        base = self._client._base_url
        url = base.copy_with(raw_path=path.encode("ascii"))
        try:
            response = await self._client.request(
                method=method,
                url=url,
                params=params,
                json=json_body,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise _to_transport_error(exc) from exc
        if response.status_code >= 400:
            raise _to_http_error(response)
        return response
