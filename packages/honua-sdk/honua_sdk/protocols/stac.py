"""STAC (SpatioTemporal Asset Catalog) protocol clients."""

# ruff: noqa: E501, PLR0913

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping
from typing import Any

import httpx

from honua_sdk._http import _encode_path_segment

from ._base import (
    FeatureId,
    JsonObject,
    Params,
    _AsyncProtocol,
    _features_from_page,
    _iter_page_indices,
    _next_link,
    _next_link_object,
    _normalize_page_limit,
    _normalize_total_limit,
    _params,
    _path_and_params_from_href,
    _SyncProtocol,
)


def _stac_post_next_request(
    link: Mapping[str, Any],
    original_body: Mapping[str, Any] | None,
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """Build the (path, params, body) for a STAC POST ``next`` link.

    Honors the STAC API pagination contract: when ``merge`` is true the link's
    ``body`` is merged onto the original request body; otherwise the link body is
    the complete next request body.
    """
    path, params = _path_and_params_from_href(str(link["href"]))
    raw_link_body = link.get("body")
    link_body = dict(raw_link_body) if isinstance(raw_link_body, Mapping) else {}
    body = (
        {**original_body, **link_body}
        if link.get("merge") and original_body is not None
        else link_body
    )
    return path, params, body


class StacClient(_SyncProtocol):
    """Synchronous STAC API wrapper.

    Use this client for SpatioTemporal Asset Catalog (STAC) surfaces
    rooted at ``/stac``: catalog/collection discovery, ``/items``
    pagination, single-item lookups, and the STAC ``/search`` endpoint
    (both GET and POST variants). Pagination wrappers (``item_pages``,
    ``iter_items``, ``search_pages``) follow the STAC ``links[rel=next]``
    cursor. Reach this via :meth:`HonuaClient.stac`.
    """

    root = "/stac"

    def catalog(self) -> JsonObject:
        return self._json("GET", self.root)

    def collections(self) -> JsonObject:
        return self._json("GET", f"{self.root}/collections")

    def collection(self, collection_id: FeatureId) -> JsonObject:
        return self._json("GET", f"{self.root}/collections/{_encode_path_segment(str(collection_id))}")

    def items(
        self,
        collection_id: FeatureId,
        *,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        return self._json(
            "GET",
            f"{self.root}/collections/{_encode_path_segment(str(collection_id))}/items",
            params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
        )

    def item_pages(
        self,
        collection_id: FeatureId,
        *,
        extra_params: Params = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Iterator[JsonObject]:
        effective_page_size = _normalize_page_limit(page_size, limit)
        total_limit = _normalize_total_limit(limit)
        if total_limit == 0:
            return

        fetched = 0
        next_href: str | None = None
        offset = int((extra_params or {}).get("offset", 0))
        for _ in _iter_page_indices(max_pages):
            remaining = effective_page_size if total_limit is None else max(0, total_limit - fetched)
            if remaining < 1:
                break
            page_limit = min(effective_page_size, remaining)
            if next_href is not None:
                page = self._json_href(next_href, timeout=timeout, extra_headers=extra_headers)
            else:
                params = _params(extra_params, {"limit": page_limit, "offset": offset})
                page = self.items(
                    collection_id,
                    extra_params=params,
                    timeout=timeout,
                    extra_headers=extra_headers,
                )

            yield page
            page_items = _features_from_page(page)
            fetched += len(page_items)
            next_href = _next_link(page)
            if next_href is None:
                if len(page_items) < page_limit:
                    break
                offset += len(page_items)

    def items_all(
        self,
        collection_id: FeatureId,
        *,
        extra_params: Params = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[JsonObject]:
        return list(
            self.iter_items(
                collection_id,
                extra_params=extra_params,
                page_size=page_size,
                limit=limit,
                max_pages=max_pages,
                timeout=timeout,
                extra_headers=extra_headers,
            )
        )

    def iter_items(
        self,
        collection_id: FeatureId,
        *,
        extra_params: Params = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Iterator[JsonObject]:
        emitted = 0
        for page in self.item_pages(
            collection_id,
            extra_params=extra_params,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            for item in _features_from_page(page):
                if limit is not None and emitted >= limit:
                    return
                yield item
                emitted += 1

    def item(
        self,
        collection_id: FeatureId,
        item_id: FeatureId,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        path = f"{self.root}/collections/{_encode_path_segment(str(collection_id))}/items/{_encode_path_segment(str(item_id))}"
        return self._json("GET", path, timeout=timeout, extra_headers=extra_headers)

    def search(
        self,
        *,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        if json_body is not None:
            return self._json(
                "POST",
                f"{self.root}/search",
                json_body=json_body,
                timeout=timeout,
                extra_headers=extra_headers,
            )
        return self._json(
            "GET",
            f"{self.root}/search",
            params=params,
            timeout=timeout,
            extra_headers=extra_headers,
        )

    def search_pages(
        self,
        *,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Iterator[JsonObject]:
        effective_page_size = _normalize_page_limit(page_size, limit)
        total_limit = _normalize_total_limit(limit)
        if total_limit == 0:
            return

        fetched = 0
        next_link: Mapping[str, Any] | None = None
        next_href: str | None = None
        offset = int((params or json_body or {}).get("offset", 0))
        for _ in _iter_page_indices(max_pages):
            remaining = effective_page_size if total_limit is None else max(0, total_limit - fetched)
            if remaining < 1:
                break
            page_limit = min(effective_page_size, remaining)
            if next_link is not None and str(next_link.get("method", "GET")).upper() == "POST":
                # STAC POST /search continuation: re-POST to the next href with
                # the link's body so the continuation token/body is preserved.
                post_path, post_params, post_body = _stac_post_next_request(next_link, json_body)
                page = self._json(
                    "POST",
                    post_path,
                    params=post_params or None,
                    json_body=post_body,
                    timeout=timeout,
                    extra_headers=extra_headers,
                )
            elif next_href is not None:
                page = self._json_href(next_href, timeout=timeout, extra_headers=extra_headers)
            elif json_body is not None:
                page_body = {**json_body, "limit": page_limit, "offset": offset}
                page = self.search(
                    json_body=page_body, timeout=timeout, extra_headers=extra_headers
                )
            else:
                page_params = _params(params, {"limit": page_limit, "offset": offset})
                page = self.search(
                    params=page_params, timeout=timeout, extra_headers=extra_headers
                )

            yield page
            page_items = _features_from_page(page)
            fetched += len(page_items)
            next_link = _next_link_object(page)
            next_href = _next_link(page)
            if next_href is None:
                if len(page_items) < page_limit:
                    break
                offset += len(page_items)

    def search_items(
        self,
        *,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[JsonObject]:
        return list(
            self.iter_search_items(
                params=params,
                json_body=json_body,
                page_size=page_size,
                limit=limit,
                max_pages=max_pages,
                timeout=timeout,
                extra_headers=extra_headers,
            )
        )

    def iter_search_items(
        self,
        *,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Iterator[JsonObject]:
        emitted = 0
        for page in self.search_pages(
            params=params,
            json_body=json_body,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            for item in _features_from_page(page):
                if limit is not None and emitted >= limit:
                    return
                yield item
                emitted += 1


class AsyncStacClient(_AsyncProtocol):
    """Async STAC API wrapper."""

    root = "/stac"

    async def catalog(self) -> JsonObject:
        return await self._json("GET", self.root)

    async def collections(self) -> JsonObject:
        return await self._json("GET", f"{self.root}/collections")

    async def collection(self, collection_id: FeatureId) -> JsonObject:
        return await self._json("GET", f"{self.root}/collections/{_encode_path_segment(str(collection_id))}")

    async def items(
        self,
        collection_id: FeatureId,
        *,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        return await self._json(
            "GET",
            f"{self.root}/collections/{_encode_path_segment(str(collection_id))}/items",
            params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
        )

    async def item_pages(
        self,
        collection_id: FeatureId,
        *,
        extra_params: Params = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[JsonObject]:
        effective_page_size = _normalize_page_limit(page_size, limit)
        total_limit = _normalize_total_limit(limit)
        if total_limit == 0:
            return

        fetched = 0
        next_href: str | None = None
        offset = int((extra_params or {}).get("offset", 0))
        for _ in _iter_page_indices(max_pages):
            remaining = effective_page_size if total_limit is None else max(0, total_limit - fetched)
            if remaining < 1:
                break
            page_limit = min(effective_page_size, remaining)
            if next_href is not None:
                page = await self._json_href(next_href, timeout=timeout, extra_headers=extra_headers)
            else:
                params = _params(extra_params, {"limit": page_limit, "offset": offset})
                page = await self.items(
                    collection_id,
                    extra_params=params,
                    timeout=timeout,
                    extra_headers=extra_headers,
                )

            yield page
            page_items = _features_from_page(page)
            fetched += len(page_items)
            next_href = _next_link(page)
            if next_href is None:
                if len(page_items) < page_limit:
                    break
                offset += len(page_items)

    async def items_all(
        self,
        collection_id: FeatureId,
        *,
        extra_params: Params = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[JsonObject]:
        return [
            item
            async for item in self.iter_items(
                collection_id,
                extra_params=extra_params,
                page_size=page_size,
                limit=limit,
                max_pages=max_pages,
                timeout=timeout,
                extra_headers=extra_headers,
            )
        ]

    async def iter_items(
        self,
        collection_id: FeatureId,
        *,
        extra_params: Params = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[JsonObject]:
        emitted = 0
        async for page in self.item_pages(
            collection_id,
            extra_params=extra_params,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            for item in _features_from_page(page):
                if limit is not None and emitted >= limit:
                    return
                yield item
                emitted += 1

    async def item(
        self,
        collection_id: FeatureId,
        item_id: FeatureId,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        path = f"{self.root}/collections/{_encode_path_segment(str(collection_id))}/items/{_encode_path_segment(str(item_id))}"
        return await self._json("GET", path, timeout=timeout, extra_headers=extra_headers)

    async def search(
        self,
        *,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        if json_body is not None:
            return await self._json(
                "POST",
                f"{self.root}/search",
                json_body=json_body,
                timeout=timeout,
                extra_headers=extra_headers,
            )
        return await self._json(
            "GET",
            f"{self.root}/search",
            params=params,
            timeout=timeout,
            extra_headers=extra_headers,
        )

    async def search_pages(
        self,
        *,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[JsonObject]:
        effective_page_size = _normalize_page_limit(page_size, limit)
        total_limit = _normalize_total_limit(limit)
        if total_limit == 0:
            return

        fetched = 0
        next_link: Mapping[str, Any] | None = None
        next_href: str | None = None
        offset = int((params or json_body or {}).get("offset", 0))
        for _ in _iter_page_indices(max_pages):
            remaining = effective_page_size if total_limit is None else max(0, total_limit - fetched)
            if remaining < 1:
                break
            page_limit = min(effective_page_size, remaining)
            if next_link is not None and str(next_link.get("method", "GET")).upper() == "POST":
                # STAC POST /search continuation: re-POST to the next href with
                # the link's body so the continuation token/body is preserved.
                post_path, post_params, post_body = _stac_post_next_request(next_link, json_body)
                page = await self._json(
                    "POST",
                    post_path,
                    params=post_params or None,
                    json_body=post_body,
                    timeout=timeout,
                    extra_headers=extra_headers,
                )
            elif next_href is not None:
                page = await self._json_href(next_href, timeout=timeout, extra_headers=extra_headers)
            elif json_body is not None:
                page_body = {**json_body, "limit": page_limit, "offset": offset}
                page = await self.search(
                    json_body=page_body, timeout=timeout, extra_headers=extra_headers
                )
            else:
                page_params = _params(params, {"limit": page_limit, "offset": offset})
                page = await self.search(
                    params=page_params, timeout=timeout, extra_headers=extra_headers
                )

            yield page
            page_items = _features_from_page(page)
            fetched += len(page_items)
            next_link = _next_link_object(page)
            next_href = _next_link(page)
            if next_href is None:
                if len(page_items) < page_limit:
                    break
                offset += len(page_items)

    async def search_items(
        self,
        *,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[JsonObject]:
        return [
            item
            async for item in self.iter_search_items(
                params=params,
                json_body=json_body,
                page_size=page_size,
                limit=limit,
                max_pages=max_pages,
                timeout=timeout,
                extra_headers=extra_headers,
            )
        ]

    async def iter_search_items(
        self,
        *,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[JsonObject]:
        emitted = 0
        async for page in self.search_pages(
            params=params,
            json_body=json_body,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            for item in _features_from_page(page):
                if limit is not None and emitted >= limit:
                    return
                yield item
                emitted += 1
