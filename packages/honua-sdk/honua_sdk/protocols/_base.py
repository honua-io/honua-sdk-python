"""Shared helpers and request/response base mixins for protocol clients."""

# ruff: noqa: PLR0913, PLR2004

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias, cast
from urllib.parse import parse_qsl, urlsplit

import httpx

from honua_sdk._http import _encode_path_segment, _to_http_error, _to_transport_error

JsonObject = dict[str, Any]
Params = Mapping[str, Any] | None
FeatureId = str | int
BboxValue = str | Sequence[int | float]
CsvValue = str | Sequence[str | int | float]
JsonResponseFormat: TypeAlias = Literal["json", "pjson"] | str
OgcImageFormat: TypeAlias = Literal["png", "jpeg", "jpg", "webp", "image/png", "image/jpeg", "image/webp"] | str
WmsVersion: TypeAlias = Literal["1.3.0", "1.1.1"] | str
WfsVersion: TypeAlias = Literal["2.0.0", "1.1.0", "1.0.0"] | str
WmtsVersion: TypeAlias = Literal["1.0.0"] | str
ODataOrderBy: TypeAlias = str | Sequence[str]


@dataclass(frozen=True)
class BinaryResponse:
    """Binary protocol response plus selected HTTP metadata."""

    content: bytes
    content_type: str | None = None
    cache_control: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    expires: str | None = None
    headers: Mapping[str, str] | None = None
    status_code: int = 200

    @classmethod
    def from_httpx(cls, response: httpx.Response) -> "BinaryResponse":
        return cls(
            content=response.content,
            content_type=response.headers.get("content-type"),
            cache_control=response.headers.get("cache-control"),
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
            expires=response.headers.get("expires"),
            headers=dict(response.headers),
            status_code=response.status_code,
        )


@dataclass(frozen=True)
class ODataQuery:
    """Convenience options for common OData query parameters."""

    filter: str | None = None
    select: CsvValue | None = None
    orderby: ODataOrderBy | None = None
    top: int | None = None
    skip: int | None = None
    count: bool | None = None


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


def _csv(value: CsvValue) -> str:
    if isinstance(value, str):
        return value
    return ",".join(str(item) for item in value)


def _bbox(value: BboxValue) -> str:
    if isinstance(value, str):
        return value
    return ",".join(str(item) for item in value)


def _query_value(value: Any) -> Any:
    if isinstance(value, (Mapping, list, tuple)):
        return json.dumps(value, separators=(",", ":"))
    return value


def _params(defaults: Mapping[str, Any] | None = None, extra: Params = None) -> dict[str, Any]:
    result: dict[str, Any] = dict(defaults or {})
    if extra:
        result.update(extra)
    return result


def _odata_params(
    *,
    query: ODataQuery | None = None,
    filter: str | None = None,
    select: CsvValue | None = None,
    orderby: ODataOrderBy | None = None,
    top: int | None = None,
    skip: int | None = None,
    count: bool | None = None,
    extra_params: Params = None,
) -> dict[str, Any]:
    options = query or ODataQuery()
    params: dict[str, Any] = {}
    effective_filter = filter if filter is not None else options.filter
    effective_select = select if select is not None else options.select
    effective_orderby = orderby if orderby is not None else options.orderby
    effective_top = top if top is not None else options.top
    effective_skip = skip if skip is not None else options.skip
    effective_count = count if count is not None else options.count
    if effective_filter is not None:
        params["$filter"] = effective_filter
    if effective_select is not None:
        params["$select"] = _csv(effective_select)
    if effective_orderby is not None:
        params["$orderby"] = _csv(effective_orderby)
    if effective_top is not None:
        params["$top"] = effective_top
    if effective_skip is not None:
        params["$skip"] = effective_skip
    if effective_count is not None:
        params["$count"] = _bool_text(effective_count)
    return _params(params, extra_params)


def _service_path(service_id: str, service_type: str) -> str:
    return f"/rest/services/{_encode_path_segment(service_id)}/{service_type}"


def _ogc_collection_path(root: str, collection_id: FeatureId) -> str:
    return f"{root}/collections/{_encode_path_segment(str(collection_id))}"


def _values_from_page(response: Mapping[str, Any], key: str = "value") -> list[JsonObject]:
    values = response.get(key)
    if not isinstance(values, list):
        return []
    return [value for value in values if isinstance(value, dict)]


def _features_from_page(response: Mapping[str, Any]) -> list[JsonObject]:
    features = response.get("features")
    if not isinstance(features, list):
        return []
    return [feature for feature in features if isinstance(feature, dict)]


def _records_from_page(response: Mapping[str, Any]) -> list[JsonObject]:
    records = response.get("records")
    if isinstance(records, list):
        return [record for record in records if isinstance(record, dict)]
    return _features_from_page(response)


def _ogc_records_params(
    *,
    response_format: str = "json",
    extra_params: Params = None,
    limit: int | None = None,
    offset: int | None = None,
    bbox: BboxValue | None = None,
    datetime: str | None = None,
    filter: str | None = None,
    q: str | None = None,
    ids: CsvValue | None = None,
    collections: CsvValue | None = None,
    properties: CsvValue | None = None,
    sortby: str | None = None,
    type: str | None = None,
) -> dict[str, Any]:
    params = _params({"f": response_format}, extra_params)
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    if bbox is not None:
        params["bbox"] = _bbox(bbox)
    if datetime is not None:
        params["datetime"] = datetime
    if filter is not None:
        params["filter"] = filter
    if q is not None:
        params["q"] = q
    if ids is not None:
        params["ids"] = _csv(ids)
    if collections is not None:
        params["collections"] = _csv(collections)
    if properties is not None:
        params["properties"] = _csv(properties)
    if sortby is not None:
        params["sortby"] = sortby
    if type is not None:
        params["type"] = type
    return params


def _next_link(response: Mapping[str, Any]) -> str | None:
    value = response.get("@odata.nextLink") or response.get("nextLink") or response.get("next")
    if isinstance(value, str) and value:
        return value
    links = response.get("links")
    if not isinstance(links, Sequence) or isinstance(links, str):
        return None
    for link in links:
        if not isinstance(link, Mapping):
            continue
        if link.get("rel") == "next" and isinstance(link.get("href"), str):
            return str(link["href"])
    return None


def _path_and_params_from_href(href: str) -> tuple[str, dict[str, str]]:
    parsed = urlsplit(href)
    path = parsed.path or href
    return path, dict(parse_qsl(parsed.query, keep_blank_values=True))


def _normalize_page_limit(page_size: int | None, limit: int | None, default: int = 100) -> int:
    if isinstance(page_size, int) and page_size > 0:
        return page_size
    if isinstance(limit, int) and limit > 0:
        return limit
    return default


def _normalize_total_limit(limit: int | None) -> int | None:
    if isinstance(limit, int):
        return max(0, limit)
    return None


def _normalize_max_pages(max_pages: int | None) -> int:
    if isinstance(max_pages, int) and max_pages > 0:
        return max_pages
    return 100


def _per_call_kwargs(
    *,
    timeout: float | httpx.Timeout | None = None,
    extra_headers: Mapping[str, str] | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Build the per-call kwargs dict for forwarding to client._request*."""
    kwargs: dict[str, Any] = {}
    if timeout is not None:
        kwargs["timeout"] = timeout
    if extra_headers is not None:
        kwargs["extra_headers"] = extra_headers
    if idempotency_key is not None:
        kwargs["idempotency_key"] = idempotency_key
    return kwargs


class _SyncProtocol:
    def __init__(self, client: Any) -> None:
        self.client = client

    def _json(
        self,
        method: str,
        path: str,
        *,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> JsonObject:
        return cast(
            JsonObject,
            self.client._request_json(
                method,
                path,
                params=params,
                json_body=json_body,
                headers=headers,
                **_per_call_kwargs(
                    timeout=timeout,
                    extra_headers=extra_headers,
                    idempotency_key=idempotency_key,
                ),
            ),
        )

    def _json_href(
        self,
        href: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        path, params = _path_and_params_from_href(href)
        return self._json(
            "GET",
            path,
            params=params,
            timeout=timeout,
            extra_headers=extra_headers,
        )

    def _bytes(
        self,
        path: str,
        *,
        params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> bytes:
        return cast(
            bytes,
            self.client._request(
                "GET",
                path,
                params=params,
                **_per_call_kwargs(timeout=timeout, extra_headers=extra_headers),
            ).content,
        )

    def _binary_response(
        self,
        path: str,
        *,
        params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> BinaryResponse:
        return BinaryResponse.from_httpx(
            self.client._request(
                "GET",
                path,
                params=params,
                **_per_call_kwargs(timeout=timeout, extra_headers=extra_headers),
            )
        )

    def _text(
        self,
        method: str,
        path: str,
        *,
        params: Params = None,
        content: bytes | str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> str:
        body = content.encode("utf-8") if isinstance(content, str) else content
        kwargs: dict[str, Any] = {
            "method": method,
            "url": path,
            "params": params,
            "content": body,
        }
        if timeout is not None:
            kwargs["timeout"] = (
                timeout if isinstance(timeout, httpx.Timeout) else httpx.Timeout(timeout)
            )
        if extra_headers is not None:
            kwargs["headers"] = dict(extra_headers)
        try:
            response = self.client._client.request(**kwargs)
        except httpx.HTTPError as exc:
            raise _to_transport_error(exc) from exc
        if response.status_code >= 400:
            raise _to_http_error(response)
        return cast(str, response.text)


class _AsyncProtocol:
    def __init__(self, client: Any) -> None:
        self.client = client

    async def _json(
        self,
        method: str,
        path: str,
        *,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> JsonObject:
        return cast(
            JsonObject,
            await self.client._request_json(
                method,
                path,
                params=params,
                json_body=json_body,
                headers=headers,
                **_per_call_kwargs(
                    timeout=timeout,
                    extra_headers=extra_headers,
                    idempotency_key=idempotency_key,
                ),
            ),
        )

    async def _json_href(
        self,
        href: str,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        path, params = _path_and_params_from_href(href)
        return await self._json(
            "GET",
            path,
            params=params,
            timeout=timeout,
            extra_headers=extra_headers,
        )

    async def _bytes(
        self,
        path: str,
        *,
        params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> bytes:
        response = await self.client._request(
            "GET",
            path,
            params=params,
            **_per_call_kwargs(timeout=timeout, extra_headers=extra_headers),
        )
        return cast(bytes, response.content)

    async def _binary_response(
        self,
        path: str,
        *,
        params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> BinaryResponse:
        response = await self.client._request(
            "GET",
            path,
            params=params,
            **_per_call_kwargs(timeout=timeout, extra_headers=extra_headers),
        )
        return BinaryResponse.from_httpx(response)

    async def _text(
        self,
        method: str,
        path: str,
        *,
        params: Params = None,
        content: bytes | str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> str:
        body = content.encode("utf-8") if isinstance(content, str) else content
        kwargs: dict[str, Any] = {
            "method": method,
            "url": path,
            "params": params,
            "content": body,
        }
        if timeout is not None:
            kwargs["timeout"] = (
                timeout if isinstance(timeout, httpx.Timeout) else httpx.Timeout(timeout)
            )
        if extra_headers is not None:
            kwargs["headers"] = dict(extra_headers)
        try:
            response = await self.client._client.request(**kwargs)
        except httpx.HTTPError as exc:
            raise _to_transport_error(exc) from exc
        if response.status_code >= 400:
            raise _to_http_error(response)
        return cast(str, response.text)
