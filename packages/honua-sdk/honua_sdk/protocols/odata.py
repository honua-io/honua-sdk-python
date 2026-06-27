"""OData v4 protocol clients."""

# ruff: noqa: PLR0913

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping

import httpx

from ._base import (
    CsvValue,
    JsonObject,
    ODataOrderBy,
    ODataQuery,
    Params,
    _AsyncProtocol,
    _iter_page_indices,
    _next_link,
    _normalize_page_limit,
    _normalize_total_limit,
    _odata_params,
    _SyncProtocol,
    _values_from_page,
)


class ODataClient(_SyncProtocol):
    """Synchronous OData v4 wrapper.

    Wraps the OData v4 surface rooted at ``/odata``: service document,
    ``$metadata``, the ``Layers`` and ``Features`` entity sets, and
    keyed lookups by ``LayerId``/``ObjectId``. Pagination helpers
    (``features_pages``, ``iter_features``, ``layer_pages``) drive the
    ``$top``/``$skip`` window and follow ``@odata.nextLink`` cursors when
    present. Pass an :class:`ODataQuery` (or per-call ``filter``/
    ``select``/``orderby`` kwargs) to assemble OData query options. Reach
    this via :meth:`HonuaClient.odata`.
    """

    root = "/odata"

    def service_document(
        self,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        return self._json("GET", self.root, timeout=timeout, extra_headers=extra_headers)

    def metadata(
        self,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> str:
        return self._text(
            "GET", f"{self.root}/$metadata", timeout=timeout, extra_headers=extra_headers
        )

    def layers(
        self,
        *,
        query: ODataQuery | None = None,
        filter: str | None = None,
        select: CsvValue | None = None,
        orderby: ODataOrderBy | None = None,
        top: int | None = None,
        skip: int | None = None,
        count: bool | None = None,
        extra_params: Params = None,
    ) -> JsonObject:
        return self._json(
            "GET",
            f"{self.root}/Layers",
            params=_odata_params(
                query=query,
                filter=filter,
                select=select,
                orderby=orderby,
                top=top,
                skip=skip,
                count=count,
                extra_params=extra_params,
            ),
        )

    def layer_pages(
        self,
        *,
        query: ODataQuery | None = None,
        filter: str | None = None,
        select: CsvValue | None = None,
        orderby: ODataOrderBy | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Iterator[JsonObject]:
        yield from self._odata_pages(
            f"{self.root}/Layers",
            query=query,
            filter=filter,
            select=select,
            orderby=orderby,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            extra_params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
        )

    def iter_layers(
        self,
        *,
        query: ODataQuery | None = None,
        filter: str | None = None,
        select: CsvValue | None = None,
        orderby: ODataOrderBy | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Iterator[JsonObject]:
        emitted = 0
        for page in self.layer_pages(
            query=query,
            filter=filter,
            select=select,
            orderby=orderby,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            extra_params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            for layer in _values_from_page(page):
                if limit is not None and emitted >= limit:
                    return
                yield layer
                emitted += 1

    def layers_all(
        self,
        *,
        query: ODataQuery | None = None,
        filter: str | None = None,
        select: CsvValue | None = None,
        orderby: ODataOrderBy | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[JsonObject]:
        return list(
            self.iter_layers(
                query=query,
                filter=filter,
                select=select,
                orderby=orderby,
                page_size=page_size,
                limit=limit,
                max_pages=max_pages,
                extra_params=extra_params,
                timeout=timeout,
                extra_headers=extra_headers,
            )
        )

    def layer(self, layer_id: int, *, extra_params: Params = None) -> JsonObject:
        return self._json("GET", f"{self.root}/Layers({layer_id})", params=extra_params)

    def features(
        self,
        *,
        layer_id: int | None = None,
        query: ODataQuery | None = None,
        filter: str | None = None,
        select: CsvValue | None = None,
        orderby: ODataOrderBy | None = None,
        top: int | None = None,
        skip: int | None = None,
        count: bool | None = None,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        path = f"{self.root}/Features" if layer_id is None else f"{self.root}/Layers({layer_id})/Features"
        return self._json(
            "GET",
            path,
            params=_odata_params(
                query=query,
                filter=filter,
                select=select,
                orderby=orderby,
                top=top,
                skip=skip,
                count=count,
                extra_params=extra_params,
            ),
            timeout=timeout,
            extra_headers=extra_headers,
        )

    def features_pages(
        self,
        *,
        layer_id: int | None = None,
        query: ODataQuery | None = None,
        filter: str | None = None,
        select: CsvValue | None = None,
        orderby: ODataOrderBy | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Iterator[JsonObject]:
        path = f"{self.root}/Features" if layer_id is None else f"{self.root}/Layers({layer_id})/Features"
        yield from self._odata_pages(
            path,
            query=query,
            filter=filter,
            select=select,
            orderby=orderby,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            extra_params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
        )

    def feature_pages(
        self,
        *,
        layer_id: int | None = None,
        query: ODataQuery | None = None,
        filter: str | None = None,
        select: CsvValue | None = None,
        orderby: ODataOrderBy | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Iterator[JsonObject]:
        yield from self.features_pages(
            layer_id=layer_id,
            query=query,
            filter=filter,
            select=select,
            orderby=orderby,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            extra_params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
        )

    def iter_features(
        self,
        *,
        layer_id: int | None = None,
        query: ODataQuery | None = None,
        filter: str | None = None,
        select: CsvValue | None = None,
        orderby: ODataOrderBy | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Iterator[JsonObject]:
        emitted = 0
        for page in self.features_pages(
            layer_id=layer_id,
            query=query,
            filter=filter,
            select=select,
            orderby=orderby,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            extra_params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            for feature in _values_from_page(page):
                if limit is not None and emitted >= limit:
                    return
                yield feature
                emitted += 1

    def features_all(
        self,
        *,
        layer_id: int | None = None,
        query: ODataQuery | None = None,
        filter: str | None = None,
        select: CsvValue | None = None,
        orderby: ODataOrderBy | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[JsonObject]:
        return list(
            self.iter_features(
                layer_id=layer_id,
                query=query,
                filter=filter,
                select=select,
                orderby=orderby,
                page_size=page_size,
                limit=limit,
                max_pages=max_pages,
                extra_params=extra_params,
                timeout=timeout,
                extra_headers=extra_headers,
            )
        )

    def feature(
        self,
        layer_id: int,
        object_id: int,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        return self._json(
            "GET",
            f"{self.root}/Features(LayerId={layer_id},ObjectId={object_id})",
            timeout=timeout,
            extra_headers=extra_headers,
        )

    def _odata_pages(
        self,
        path: str,
        *,
        query: ODataQuery | None,
        filter: str | None,
        select: CsvValue | None,
        orderby: ODataOrderBy | None,
        page_size: int | None,
        limit: int | None,
        max_pages: int | None,
        extra_params: Params,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Iterator[JsonObject]:
        effective_page_size = _normalize_page_limit(page_size, limit)
        total_limit = _normalize_total_limit(limit)
        if total_limit == 0:
            return

        fetched = 0
        next_href: str | None = None
        skip = int((extra_params or {}).get("$skip", 0))
        for _ in _iter_page_indices(max_pages):
            remaining = effective_page_size if total_limit is None else max(0, total_limit - fetched)
            if remaining < 1:
                break
            page_limit = min(effective_page_size, remaining)
            if next_href is not None:
                page = self._json_href(next_href, timeout=timeout, extra_headers=extra_headers)
            else:
                page_params = _odata_params(
                    query=query,
                    filter=filter,
                    select=select,
                    orderby=orderby,
                    extra_params=extra_params,
                )
                page_params["$top"] = page_limit
                page_params["$skip"] = skip
                page = self._json(
                    "GET",
                    path,
                    params=page_params,
                    timeout=timeout,
                    extra_headers=extra_headers,
                )
            yield page
            page_values = _values_from_page(page)
            fetched += len(page_values)
            next_href = _next_link(page)
            if next_href is None:
                if len(page_values) < page_limit:
                    break
                skip += len(page_values)


class AsyncODataClient(_AsyncProtocol):
    """Async OData v4 wrapper."""

    root = "/odata"

    async def service_document(
        self,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        return await self._json(
            "GET", self.root, timeout=timeout, extra_headers=extra_headers
        )

    async def metadata(
        self,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> str:
        return await self._text(
            "GET", f"{self.root}/$metadata", timeout=timeout, extra_headers=extra_headers
        )

    async def layers(
        self,
        *,
        query: ODataQuery | None = None,
        filter: str | None = None,
        select: CsvValue | None = None,
        orderby: ODataOrderBy | None = None,
        top: int | None = None,
        skip: int | None = None,
        count: bool | None = None,
        extra_params: Params = None,
    ) -> JsonObject:
        return await self._json(
            "GET",
            f"{self.root}/Layers",
            params=_odata_params(
                query=query,
                filter=filter,
                select=select,
                orderby=orderby,
                top=top,
                skip=skip,
                count=count,
                extra_params=extra_params,
            ),
        )

    async def layer_pages(
        self,
        *,
        query: ODataQuery | None = None,
        filter: str | None = None,
        select: CsvValue | None = None,
        orderby: ODataOrderBy | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[JsonObject]:
        async for page in self._odata_pages(
            f"{self.root}/Layers",
            query=query,
            filter=filter,
            select=select,
            orderby=orderby,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            extra_params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            yield page

    async def iter_layers(
        self,
        *,
        query: ODataQuery | None = None,
        filter: str | None = None,
        select: CsvValue | None = None,
        orderby: ODataOrderBy | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[JsonObject]:
        emitted = 0
        async for page in self.layer_pages(
            query=query,
            filter=filter,
            select=select,
            orderby=orderby,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            extra_params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            for layer in _values_from_page(page):
                if limit is not None and emitted >= limit:
                    return
                yield layer
                emitted += 1

    async def layers_all(
        self,
        *,
        query: ODataQuery | None = None,
        filter: str | None = None,
        select: CsvValue | None = None,
        orderby: ODataOrderBy | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[JsonObject]:
        return [
            layer
            async for layer in self.iter_layers(
                query=query,
                filter=filter,
                select=select,
                orderby=orderby,
                page_size=page_size,
                limit=limit,
                max_pages=max_pages,
                extra_params=extra_params,
                timeout=timeout,
                extra_headers=extra_headers,
            )
        ]

    async def layer(self, layer_id: int, *, extra_params: Params = None) -> JsonObject:
        return await self._json("GET", f"{self.root}/Layers({layer_id})", params=extra_params)

    async def features(
        self,
        *,
        layer_id: int | None = None,
        query: ODataQuery | None = None,
        filter: str | None = None,
        select: CsvValue | None = None,
        orderby: ODataOrderBy | None = None,
        top: int | None = None,
        skip: int | None = None,
        count: bool | None = None,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        path = f"{self.root}/Features" if layer_id is None else f"{self.root}/Layers({layer_id})/Features"
        return await self._json(
            "GET",
            path,
            params=_odata_params(
                query=query,
                filter=filter,
                select=select,
                orderby=orderby,
                top=top,
                skip=skip,
                count=count,
                extra_params=extra_params,
            ),
            timeout=timeout,
            extra_headers=extra_headers,
        )

    async def features_pages(
        self,
        *,
        layer_id: int | None = None,
        query: ODataQuery | None = None,
        filter: str | None = None,
        select: CsvValue | None = None,
        orderby: ODataOrderBy | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[JsonObject]:
        path = f"{self.root}/Features" if layer_id is None else f"{self.root}/Layers({layer_id})/Features"
        async for page in self._odata_pages(
            path,
            query=query,
            filter=filter,
            select=select,
            orderby=orderby,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            extra_params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            yield page

    async def feature_pages(
        self,
        *,
        layer_id: int | None = None,
        query: ODataQuery | None = None,
        filter: str | None = None,
        select: CsvValue | None = None,
        orderby: ODataOrderBy | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[JsonObject]:
        async for page in self.features_pages(
            layer_id=layer_id,
            query=query,
            filter=filter,
            select=select,
            orderby=orderby,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            extra_params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            yield page

    async def iter_features(
        self,
        *,
        layer_id: int | None = None,
        query: ODataQuery | None = None,
        filter: str | None = None,
        select: CsvValue | None = None,
        orderby: ODataOrderBy | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[JsonObject]:
        emitted = 0
        async for page in self.features_pages(
            layer_id=layer_id,
            query=query,
            filter=filter,
            select=select,
            orderby=orderby,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            extra_params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            for feature in _values_from_page(page):
                if limit is not None and emitted >= limit:
                    return
                yield feature
                emitted += 1

    async def features_all(
        self,
        *,
        layer_id: int | None = None,
        query: ODataQuery | None = None,
        filter: str | None = None,
        select: CsvValue | None = None,
        orderby: ODataOrderBy | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[JsonObject]:
        return [
            feature
            async for feature in self.iter_features(
                layer_id=layer_id,
                query=query,
                filter=filter,
                select=select,
                orderby=orderby,
                page_size=page_size,
                limit=limit,
                max_pages=max_pages,
                extra_params=extra_params,
                timeout=timeout,
                extra_headers=extra_headers,
            )
        ]

    async def feature(
        self,
        layer_id: int,
        object_id: int,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        return await self._json(
            "GET",
            f"{self.root}/Features(LayerId={layer_id},ObjectId={object_id})",
            timeout=timeout,
            extra_headers=extra_headers,
        )

    async def _odata_pages(
        self,
        path: str,
        *,
        query: ODataQuery | None,
        filter: str | None,
        select: CsvValue | None,
        orderby: ODataOrderBy | None,
        page_size: int | None,
        limit: int | None,
        max_pages: int | None,
        extra_params: Params,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[JsonObject]:
        effective_page_size = _normalize_page_limit(page_size, limit)
        total_limit = _normalize_total_limit(limit)
        if total_limit == 0:
            return

        fetched = 0
        next_href: str | None = None
        skip = int((extra_params or {}).get("$skip", 0))
        for _ in _iter_page_indices(max_pages):
            remaining = effective_page_size if total_limit is None else max(0, total_limit - fetched)
            if remaining < 1:
                break
            page_limit = min(effective_page_size, remaining)
            if next_href is not None:
                page = await self._json_href(next_href, timeout=timeout, extra_headers=extra_headers)
            else:
                page_params = _odata_params(
                    query=query,
                    filter=filter,
                    select=select,
                    orderby=orderby,
                    extra_params=extra_params,
                )
                page_params["$top"] = page_limit
                page_params["$skip"] = skip
                page = await self._json(
                    "GET",
                    path,
                    params=page_params,
                    timeout=timeout,
                    extra_headers=extra_headers,
                )
            yield page
            page_values = _values_from_page(page)
            fetched += len(page_values)
            next_href = _next_link(page)
            if next_href is None:
                if len(page_values) < page_limit:
                    break
                skip += len(page_values)
