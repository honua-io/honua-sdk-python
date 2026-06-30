"""OGC API Features wrappers for Honua Server."""

from __future__ import annotations

import itertools
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import httpx

from ._client_protocol import SupportsAsyncRequest, SupportsSyncRequest
from ._http import _encode_path_segment

FeatureId = str | int
JsonObject = dict[str, Any]
CsvValue = str | Sequence[str | int | float]
BboxValue = str | Sequence[int | float]


def _metadata_params(
    *,
    response_format: str = "json",
    extra_params: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"f": response_format}
    if extra_params:
        params.update(extra_params)
    return params


def _comma_text(value: CsvValue) -> str:
    if isinstance(value, str):
        return value
    return ",".join(str(item) for item in value)


def _items_params(
    *,
    response_format: str = "json",
    extra_params: Mapping[str, Any] | None = None,
    limit: int | None = None,
    offset: int | None = None,
    bbox: BboxValue | None = None,
    datetime: str | None = None,
    filter: str | None = None,
    ids: CsvValue | None = None,
    properties: CsvValue | None = None,
    sortby: str | None = None,
    crs: str | None = None,
) -> dict[str, Any]:
    params = _metadata_params(response_format=response_format, extra_params=extra_params)
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    if bbox is not None:
        params["bbox"] = _comma_text(bbox)
    if datetime is not None:
        params["datetime"] = datetime
    if filter is not None:
        params["filter"] = filter
    if ids is not None:
        params["ids"] = _comma_text(ids)
    if properties is not None:
        params["properties"] = _comma_text(properties)
    if sortby is not None:
        params["sortby"] = sortby
    if crs is not None:
        params["crs"] = crs
    return params


def _item_params(
    *,
    response_format: str = "json",
    extra_params: Mapping[str, Any] | None = None,
    crs: str | None = None,
) -> dict[str, Any]:
    params = _metadata_params(response_format=response_format, extra_params=extra_params)
    if crs is not None:
        params["crs"] = crs
    return params


def _collection_path(collection_id: FeatureId) -> str:
    return f"/ogc/features/collections/{_encode_path_segment(str(collection_id))}"


def _item_path(collection_id: FeatureId, feature_id: FeatureId) -> str:
    return f"{_collection_path(collection_id)}/items/{_encode_path_segment(str(feature_id))}"


def _features_from_collection(response: Mapping[str, Any]) -> list[JsonObject]:
    features = response.get("features")
    if not isinstance(features, list):
        return []
    return [feature for feature in features if isinstance(feature, dict)]


def _next_link(response: Mapping[str, Any]) -> str | None:
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


def _normalize_page_size(page_size: int | None, limit: int | None) -> int:
    if isinstance(page_size, int) and page_size > 0:
        return page_size
    if isinstance(limit, int) and limit > 0:
        return limit
    return 100


def _iter_page_indices(max_pages: int | None) -> Iterator[int]:
    """Yield page indices for a pagination loop, honouring an unbounded cap.

    ``max_pages=None`` means *unbounded* -- the loop walks every page the server
    advertises (the next-link / short-page guard is what stops it), matching the
    FeatureServer walker. Previously ``None`` was silently capped at 100 pages,
    quietly truncating results when the server still advertised a ``rel=next``.
    A positive ``int`` caps the walk; ``max_pages <= 0`` yields nothing.
    """
    if max_pages is None:
        return itertools.count()
    if max_pages <= 0:
        return iter(())
    return iter(range(max_pages))


def _normalize_offset(offset: int | None) -> int:
    if not isinstance(offset, int):
        return 0
    return max(0, offset)


def _normalize_total_limit(limit: int | None) -> int | None:
    if isinstance(limit, int):
        return max(0, limit)
    return None


class HonuaOgcFeatures:
    """Synchronous OGC API Features entry point."""

    def __init__(self, client: SupportsSyncRequest) -> None:
        self.client = client

    def collection(self, collection_id: FeatureId) -> "HonuaOgcFeatureCollection":
        """Return a collection-bound OGC Features wrapper."""
        return HonuaOgcFeatureCollection(self.client, collection_id)

    def landing(
        self,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
    ) -> JsonObject:
        """Get the OGC API Features landing page."""
        return self.client._request_json(
            "GET",
            "/ogc/features",
            params=_metadata_params(response_format=response_format, extra_params=extra_params),
        )

    def conformance(
        self,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
    ) -> JsonObject:
        """Get OGC API conformance classes."""
        return self.client._request_json(
            "GET",
            "/ogc/features/conformance",
            params=_metadata_params(response_format=response_format, extra_params=extra_params),
        )

    def collections(
        self,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
    ) -> JsonObject:
        """List OGC API Features collections."""
        return self.client._request_json(
            "GET",
            "/ogc/features/collections",
            params=_metadata_params(response_format=response_format, extra_params=extra_params),
        )

    def get_collection(
        self,
        collection_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
    ) -> JsonObject:
        """Get metadata for one OGC API Features collection."""
        return self.client._request_json(
            "GET",
            _collection_path(collection_id),
            params=_metadata_params(response_format=response_format, extra_params=extra_params),
        )

    def queryables(
        self,
        collection_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
    ) -> JsonObject:
        """Get queryable property metadata for one collection."""
        return self.client._request_json(
            "GET",
            f"{_collection_path(collection_id)}/queryables",
            params=_metadata_params(response_format=response_format, extra_params=extra_params),
        )

    def items(
        self,
        collection_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        bbox: BboxValue | None = None,
        datetime: str | None = None,
        filter: str | None = None,
        ids: CsvValue | None = None,
        properties: CsvValue | None = None,
        sortby: str | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        """List GeoJSON items for one collection."""
        return self.client._request_json(
            "GET",
            f"{_collection_path(collection_id)}/items",
            params=_items_params(
                response_format=response_format,
                extra_params=extra_params,
                limit=limit,
                offset=offset,
                bbox=bbox,
                datetime=datetime,
                filter=filter,
                ids=ids,
                properties=properties,
                sortby=sortby,
                crs=crs,
            ),
            timeout=timeout,
            extra_headers=extra_headers,
        )

    def items_all(
        self,
        collection_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        bbox: BboxValue | None = None,
        datetime: str | None = None,
        filter: str | None = None,
        ids: CsvValue | None = None,
        properties: CsvValue | None = None,
        sortby: str | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[JsonObject]:
        """Page through collection items and return all fetched features."""
        return list(
            self.iter_items(
                collection_id,
                response_format=response_format,
                extra_params=extra_params,
                limit=limit,
                offset=offset,
                page_size=page_size,
                max_pages=max_pages,
                bbox=bbox,
                datetime=datetime,
                filter=filter,
                ids=ids,
                properties=properties,
                sortby=sortby,
                crs=crs,
                timeout=timeout,
                extra_headers=extra_headers,
            )
        )

    def items_pages(
        self,
        collection_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        bbox: BboxValue | None = None,
        datetime: str | None = None,
        filter: str | None = None,
        ids: CsvValue | None = None,
        properties: CsvValue | None = None,
        sortby: str | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Iterator[JsonObject]:
        yield from self.collection(collection_id).items_pages(
            response_format=response_format,
            extra_params=extra_params,
            limit=limit,
            offset=offset,
            page_size=page_size,
            max_pages=max_pages,
            bbox=bbox,
            datetime=datetime,
            filter=filter,
            ids=ids,
            properties=properties,
            sortby=sortby,
            crs=crs,
            timeout=timeout,
            extra_headers=extra_headers,
        )

    def iter_items(
        self,
        collection_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        bbox: BboxValue | None = None,
        datetime: str | None = None,
        filter: str | None = None,
        ids: CsvValue | None = None,
        properties: CsvValue | None = None,
        sortby: str | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Iterator[JsonObject]:
        yield from self.collection(collection_id).iter_items(
            response_format=response_format,
            extra_params=extra_params,
            limit=limit,
            offset=offset,
            page_size=page_size,
            max_pages=max_pages,
            bbox=bbox,
            datetime=datetime,
            filter=filter,
            ids=ids,
            properties=properties,
            sortby=sortby,
            crs=crs,
            timeout=timeout,
            extra_headers=extra_headers,
        )

    def item(
        self,
        collection_id: FeatureId,
        feature_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        crs: str | None = None,
    ) -> JsonObject:
        """Get one GeoJSON feature by id."""
        return self.client._request_json(
            "GET",
            _item_path(collection_id, feature_id),
            params=_item_params(response_format=response_format, extra_params=extra_params, crs=crs),
        )

    def create_item(
        self,
        collection_id: FeatureId,
        feature: Mapping[str, Any],
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> JsonObject:
        """Create one GeoJSON feature in a collection."""
        return self.client._request_json(
            "POST",
            f"{_collection_path(collection_id)}/items",
            params=_metadata_params(response_format=response_format, extra_params=extra_params),
            json_body=feature,
            headers={"Content-Type": "application/geo+json"},
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )

    def replace_item(
        self,
        collection_id: FeatureId,
        feature_id: FeatureId,
        feature: Mapping[str, Any],
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> JsonObject:
        """Replace one GeoJSON feature in a collection."""
        return self.client._request_json(
            "PUT",
            _item_path(collection_id, feature_id),
            params=_item_params(response_format=response_format, extra_params=extra_params, crs=crs),
            json_body=feature,
            headers={"Content-Type": "application/geo+json"},
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )

    def patch_item(
        self,
        collection_id: FeatureId,
        feature_id: FeatureId,
        patch: Mapping[str, Any],
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> JsonObject:
        """Patch one GeoJSON feature in a collection."""
        return self.client._request_json(
            "PATCH",
            _item_path(collection_id, feature_id),
            params=_item_params(response_format=response_format, extra_params=extra_params, crs=crs),
            json_body=patch,
            headers={"Content-Type": "application/merge-patch+json"},
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )

    def delete_item(
        self,
        collection_id: FeatureId,
        feature_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        """Delete one GeoJSON feature from a collection."""
        self.client._request_json(
            "DELETE",
            _item_path(collection_id, feature_id),
            params=_item_params(response_format=response_format, extra_params=extra_params, crs=crs),
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )


class HonuaOgcFeatureCollection:
    """Collection-bound synchronous OGC API Features wrapper."""

    def __init__(self, client: SupportsSyncRequest, collection_id: FeatureId) -> None:
        self.client = client
        self.collection_id = collection_id

    def metadata(
        self,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
    ) -> JsonObject:
        return HonuaOgcFeatures(self.client).get_collection(
            self.collection_id,
            response_format=response_format,
            extra_params=extra_params,
        )

    def queryables(
        self,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
    ) -> JsonObject:
        return HonuaOgcFeatures(self.client).queryables(
            self.collection_id,
            response_format=response_format,
            extra_params=extra_params,
        )

    def items(
        self,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        bbox: BboxValue | None = None,
        datetime: str | None = None,
        filter: str | None = None,
        ids: CsvValue | None = None,
        properties: CsvValue | None = None,
        sortby: str | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        return HonuaOgcFeatures(self.client).items(
            self.collection_id,
            response_format=response_format,
            extra_params=extra_params,
            limit=limit,
            offset=offset,
            bbox=bbox,
            datetime=datetime,
            filter=filter,
            ids=ids,
            properties=properties,
            sortby=sortby,
            crs=crs,
            timeout=timeout,
            extra_headers=extra_headers,
        )

    def items_all(
        self,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        bbox: BboxValue | None = None,
        datetime: str | None = None,
        filter: str | None = None,
        ids: CsvValue | None = None,
        properties: CsvValue | None = None,
        sortby: str | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[JsonObject]:
        return list(
            self.iter_items(
                response_format=response_format,
                extra_params=extra_params,
                limit=limit,
                offset=offset,
                page_size=page_size,
                max_pages=max_pages,
                bbox=bbox,
                datetime=datetime,
                filter=filter,
                ids=ids,
                properties=properties,
                sortby=sortby,
                crs=crs,
                timeout=timeout,
                extra_headers=extra_headers,
            )
        )

    def items_pages(
        self,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        bbox: BboxValue | None = None,
        datetime: str | None = None,
        filter: str | None = None,
        ids: CsvValue | None = None,
        properties: CsvValue | None = None,
        sortby: str | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Iterator[JsonObject]:
        effective_page_size = _normalize_page_size(page_size, limit)
        start_offset = _normalize_offset(offset)
        total_limit = _normalize_total_limit(limit)
        if total_limit == 0:
            return

        fetched = 0
        next_href: str | None = None
        previous_next_href: str | None = None
        for page in _iter_page_indices(max_pages):
            remaining = effective_page_size if total_limit is None else max(0, total_limit - fetched)
            if remaining < 1:
                break

            page_limit = min(effective_page_size, remaining)
            if next_href is not None:
                path, params = _path_and_params_from_href(next_href)
                response = self.client._request_json(
                    "GET",
                    path,
                    params=params,
                    timeout=timeout,
                    extra_headers=extra_headers,
                )
            else:
                response = self.items(
                    response_format=response_format,
                    extra_params=extra_params,
                    limit=page_limit,
                    offset=start_offset + page * effective_page_size,
                    bbox=bbox,
                    datetime=datetime,
                    filter=filter,
                    ids=ids,
                    properties=properties,
                    sortby=sortby,
                    crs=crs,
                    timeout=timeout,
                    extra_headers=extra_headers,
                )
            yield response
            page_features = _features_from_collection(response)
            fetched += len(page_features)
            next_href = _next_link(response)
            if next_href is None and len(page_features) < page_limit:
                break
            # Guard against a non-advancing cursor: a server that echoes a
            # constant ``rel=next`` would otherwise loop forever (max_pages=None
            # is unbounded) re-fetching the same page. Mirrors the STAC walker.
            if next_href is not None and next_href == previous_next_href:
                break
            previous_next_href = next_href

    def iter_items(
        self,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        bbox: BboxValue | None = None,
        datetime: str | None = None,
        filter: str | None = None,
        ids: CsvValue | None = None,
        properties: CsvValue | None = None,
        sortby: str | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Iterator[JsonObject]:
        emitted = 0
        for page in self.items_pages(
            response_format=response_format,
            extra_params=extra_params,
            limit=limit,
            offset=offset,
            page_size=page_size,
            max_pages=max_pages,
            bbox=bbox,
            datetime=datetime,
            filter=filter,
            ids=ids,
            properties=properties,
            sortby=sortby,
            crs=crs,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            for item in _features_from_collection(page):
                if limit is not None and emitted >= limit:
                    return
                yield item
                emitted += 1

    def item(
        self,
        feature_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        crs: str | None = None,
    ) -> JsonObject:
        return HonuaOgcFeatures(self.client).item(
            self.collection_id,
            feature_id,
            response_format=response_format,
            extra_params=extra_params,
            crs=crs,
        )

    def create_item(
        self,
        feature: Mapping[str, Any],
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> JsonObject:
        return HonuaOgcFeatures(self.client).create_item(
            self.collection_id,
            feature,
            response_format=response_format,
            extra_params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )

    def replace_item(
        self,
        feature_id: FeatureId,
        feature: Mapping[str, Any],
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> JsonObject:
        return HonuaOgcFeatures(self.client).replace_item(
            self.collection_id,
            feature_id,
            feature,
            response_format=response_format,
            extra_params=extra_params,
            crs=crs,
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )

    def patch_item(
        self,
        feature_id: FeatureId,
        patch: Mapping[str, Any],
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> JsonObject:
        return HonuaOgcFeatures(self.client).patch_item(
            self.collection_id,
            feature_id,
            patch,
            response_format=response_format,
            extra_params=extra_params,
            crs=crs,
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )

    def delete_item(
        self,
        feature_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        HonuaOgcFeatures(self.client).delete_item(
            self.collection_id,
            feature_id,
            response_format=response_format,
            extra_params=extra_params,
            crs=crs,
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )


class AsyncHonuaOgcFeatures:
    """Asynchronous OGC API Features entry point."""

    def __init__(self, client: SupportsAsyncRequest) -> None:
        self.client = client

    def collection(self, collection_id: FeatureId) -> "AsyncHonuaOgcFeatureCollection":
        """Return a collection-bound async OGC Features wrapper."""
        return AsyncHonuaOgcFeatureCollection(self.client, collection_id)

    async def landing(
        self,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
    ) -> JsonObject:
        return await self.client._request_json(
            "GET",
            "/ogc/features",
            params=_metadata_params(response_format=response_format, extra_params=extra_params),
        )

    async def conformance(
        self,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
    ) -> JsonObject:
        return await self.client._request_json(
            "GET",
            "/ogc/features/conformance",
            params=_metadata_params(response_format=response_format, extra_params=extra_params),
        )

    async def collections(
        self,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
    ) -> JsonObject:
        return await self.client._request_json(
            "GET",
            "/ogc/features/collections",
            params=_metadata_params(response_format=response_format, extra_params=extra_params),
        )

    async def get_collection(
        self,
        collection_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
    ) -> JsonObject:
        return await self.client._request_json(
            "GET",
            _collection_path(collection_id),
            params=_metadata_params(response_format=response_format, extra_params=extra_params),
        )

    async def queryables(
        self,
        collection_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
    ) -> JsonObject:
        return await self.client._request_json(
            "GET",
            f"{_collection_path(collection_id)}/queryables",
            params=_metadata_params(response_format=response_format, extra_params=extra_params),
        )

    async def items(
        self,
        collection_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        bbox: BboxValue | None = None,
        datetime: str | None = None,
        filter: str | None = None,
        ids: CsvValue | None = None,
        properties: CsvValue | None = None,
        sortby: str | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        return await self.client._request_json(
            "GET",
            f"{_collection_path(collection_id)}/items",
            params=_items_params(
                response_format=response_format,
                extra_params=extra_params,
                limit=limit,
                offset=offset,
                bbox=bbox,
                datetime=datetime,
                filter=filter,
                ids=ids,
                properties=properties,
                sortby=sortby,
                crs=crs,
            ),
            timeout=timeout,
            extra_headers=extra_headers,
        )

    async def items_all(
        self,
        collection_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        bbox: BboxValue | None = None,
        datetime: str | None = None,
        filter: str | None = None,
        ids: CsvValue | None = None,
        properties: CsvValue | None = None,
        sortby: str | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[JsonObject]:
        return [
            item
            async for item in self.iter_items(
                collection_id,
                response_format=response_format,
                extra_params=extra_params,
                limit=limit,
                offset=offset,
                page_size=page_size,
                max_pages=max_pages,
                bbox=bbox,
                datetime=datetime,
                filter=filter,
                ids=ids,
                properties=properties,
                sortby=sortby,
                crs=crs,
                timeout=timeout,
                extra_headers=extra_headers,
            )
        ]

    async def items_pages(
        self,
        collection_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        bbox: BboxValue | None = None,
        datetime: str | None = None,
        filter: str | None = None,
        ids: CsvValue | None = None,
        properties: CsvValue | None = None,
        sortby: str | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[JsonObject]:
        async for page in self.collection(collection_id).items_pages(
            response_format=response_format,
            extra_params=extra_params,
            limit=limit,
            offset=offset,
            page_size=page_size,
            max_pages=max_pages,
            bbox=bbox,
            datetime=datetime,
            filter=filter,
            ids=ids,
            properties=properties,
            sortby=sortby,
            crs=crs,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            yield page

    async def iter_items(
        self,
        collection_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        bbox: BboxValue | None = None,
        datetime: str | None = None,
        filter: str | None = None,
        ids: CsvValue | None = None,
        properties: CsvValue | None = None,
        sortby: str | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[JsonObject]:
        async for item in self.collection(collection_id).iter_items(
            response_format=response_format,
            extra_params=extra_params,
            limit=limit,
            offset=offset,
            page_size=page_size,
            max_pages=max_pages,
            bbox=bbox,
            datetime=datetime,
            filter=filter,
            ids=ids,
            properties=properties,
            sortby=sortby,
            crs=crs,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            yield item

    async def item(
        self,
        collection_id: FeatureId,
        feature_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        crs: str | None = None,
    ) -> JsonObject:
        return await self.client._request_json(
            "GET",
            _item_path(collection_id, feature_id),
            params=_item_params(response_format=response_format, extra_params=extra_params, crs=crs),
        )

    async def create_item(
        self,
        collection_id: FeatureId,
        feature: Mapping[str, Any],
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> JsonObject:
        return await self.client._request_json(
            "POST",
            f"{_collection_path(collection_id)}/items",
            params=_metadata_params(response_format=response_format, extra_params=extra_params),
            json_body=feature,
            headers={"Content-Type": "application/geo+json"},
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )

    async def replace_item(
        self,
        collection_id: FeatureId,
        feature_id: FeatureId,
        feature: Mapping[str, Any],
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> JsonObject:
        return await self.client._request_json(
            "PUT",
            _item_path(collection_id, feature_id),
            params=_item_params(response_format=response_format, extra_params=extra_params, crs=crs),
            json_body=feature,
            headers={"Content-Type": "application/geo+json"},
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )

    async def patch_item(
        self,
        collection_id: FeatureId,
        feature_id: FeatureId,
        patch: Mapping[str, Any],
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> JsonObject:
        return await self.client._request_json(
            "PATCH",
            _item_path(collection_id, feature_id),
            params=_item_params(response_format=response_format, extra_params=extra_params, crs=crs),
            json_body=patch,
            headers={"Content-Type": "application/merge-patch+json"},
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )

    async def delete_item(
        self,
        collection_id: FeatureId,
        feature_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        await self.client._request_json(
            "DELETE",
            _item_path(collection_id, feature_id),
            params=_item_params(response_format=response_format, extra_params=extra_params, crs=crs),
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )


class AsyncHonuaOgcFeatureCollection:
    """Collection-bound asynchronous OGC API Features wrapper."""

    def __init__(self, client: SupportsAsyncRequest, collection_id: FeatureId) -> None:
        self.client = client
        self.collection_id = collection_id

    async def metadata(
        self,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
    ) -> JsonObject:
        return await AsyncHonuaOgcFeatures(self.client).get_collection(
            self.collection_id,
            response_format=response_format,
            extra_params=extra_params,
        )

    async def queryables(
        self,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
    ) -> JsonObject:
        return await AsyncHonuaOgcFeatures(self.client).queryables(
            self.collection_id,
            response_format=response_format,
            extra_params=extra_params,
        )

    async def items(
        self,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        bbox: BboxValue | None = None,
        datetime: str | None = None,
        filter: str | None = None,
        ids: CsvValue | None = None,
        properties: CsvValue | None = None,
        sortby: str | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        return await AsyncHonuaOgcFeatures(self.client).items(
            self.collection_id,
            response_format=response_format,
            extra_params=extra_params,
            limit=limit,
            offset=offset,
            bbox=bbox,
            datetime=datetime,
            filter=filter,
            ids=ids,
            properties=properties,
            sortby=sortby,
            crs=crs,
            timeout=timeout,
            extra_headers=extra_headers,
        )

    async def items_all(
        self,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        bbox: BboxValue | None = None,
        datetime: str | None = None,
        filter: str | None = None,
        ids: CsvValue | None = None,
        properties: CsvValue | None = None,
        sortby: str | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[JsonObject]:
        return [
            item
            async for item in self.iter_items(
                response_format=response_format,
                extra_params=extra_params,
                limit=limit,
                offset=offset,
                page_size=page_size,
                max_pages=max_pages,
                bbox=bbox,
                datetime=datetime,
                filter=filter,
                ids=ids,
                properties=properties,
                sortby=sortby,
                crs=crs,
                timeout=timeout,
                extra_headers=extra_headers,
            )
        ]

    async def items_pages(
        self,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        bbox: BboxValue | None = None,
        datetime: str | None = None,
        filter: str | None = None,
        ids: CsvValue | None = None,
        properties: CsvValue | None = None,
        sortby: str | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[JsonObject]:
        effective_page_size = _normalize_page_size(page_size, limit)
        start_offset = _normalize_offset(offset)
        total_limit = _normalize_total_limit(limit)
        if total_limit == 0:
            return

        fetched = 0
        next_href: str | None = None
        previous_next_href: str | None = None
        for page in _iter_page_indices(max_pages):
            remaining = effective_page_size if total_limit is None else max(0, total_limit - fetched)
            if remaining < 1:
                break

            page_limit = min(effective_page_size, remaining)
            if next_href is not None:
                path, params = _path_and_params_from_href(next_href)
                response = await self.client._request_json(
                    "GET",
                    path,
                    params=params,
                    timeout=timeout,
                    extra_headers=extra_headers,
                )
            else:
                response = await self.items(
                    response_format=response_format,
                    extra_params=extra_params,
                    limit=page_limit,
                    offset=start_offset + page * effective_page_size,
                    bbox=bbox,
                    datetime=datetime,
                    filter=filter,
                    ids=ids,
                    properties=properties,
                    sortby=sortby,
                    crs=crs,
                    timeout=timeout,
                    extra_headers=extra_headers,
                )
            yield response
            page_features = _features_from_collection(response)
            fetched += len(page_features)
            next_href = _next_link(response)
            if next_href is None and len(page_features) < page_limit:
                break
            # Guard against a non-advancing cursor: a server that echoes a
            # constant ``rel=next`` would otherwise loop forever (max_pages=None
            # is unbounded) re-fetching the same page. Mirrors the STAC walker.
            if next_href is not None and next_href == previous_next_href:
                break
            previous_next_href = next_href

    async def iter_items(
        self,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        bbox: BboxValue | None = None,
        datetime: str | None = None,
        filter: str | None = None,
        ids: CsvValue | None = None,
        properties: CsvValue | None = None,
        sortby: str | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[JsonObject]:
        emitted = 0
        async for page in self.items_pages(
            response_format=response_format,
            extra_params=extra_params,
            limit=limit,
            offset=offset,
            page_size=page_size,
            max_pages=max_pages,
            bbox=bbox,
            datetime=datetime,
            filter=filter,
            ids=ids,
            properties=properties,
            sortby=sortby,
            crs=crs,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            for item in _features_from_collection(page):
                if limit is not None and emitted >= limit:
                    return
                yield item
                emitted += 1

    async def item(
        self,
        feature_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        crs: str | None = None,
    ) -> JsonObject:
        return await AsyncHonuaOgcFeatures(self.client).item(
            self.collection_id,
            feature_id,
            response_format=response_format,
            extra_params=extra_params,
            crs=crs,
        )

    async def create_item(
        self,
        feature: Mapping[str, Any],
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> JsonObject:
        return await AsyncHonuaOgcFeatures(self.client).create_item(
            self.collection_id,
            feature,
            response_format=response_format,
            extra_params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )

    async def replace_item(
        self,
        feature_id: FeatureId,
        feature: Mapping[str, Any],
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> JsonObject:
        return await AsyncHonuaOgcFeatures(self.client).replace_item(
            self.collection_id,
            feature_id,
            feature,
            response_format=response_format,
            extra_params=extra_params,
            crs=crs,
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )

    async def patch_item(
        self,
        feature_id: FeatureId,
        patch: Mapping[str, Any],
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> JsonObject:
        return await AsyncHonuaOgcFeatures(self.client).patch_item(
            self.collection_id,
            feature_id,
            patch,
            response_format=response_format,
            extra_params=extra_params,
            crs=crs,
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )

    async def delete_item(
        self,
        feature_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Mapping[str, Any] | None = None,
        crs: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> None:
        await AsyncHonuaOgcFeatures(self.client).delete_item(
            self.collection_id,
            feature_id,
            response_format=response_format,
            extra_params=extra_params,
            crs=crs,
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )
