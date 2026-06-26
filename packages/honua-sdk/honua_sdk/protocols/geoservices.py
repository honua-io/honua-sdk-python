"""GeoServices REST FeatureServer/MapServer/ImageServer/GeometryServer protocol clients."""

# ruff: noqa: E501, PLR0913

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from typing import Any, cast

import httpx

from honua_sdk._http import _encode_path_segment
from honua_sdk.models import Feature, FeatureSet, LayerSchema

from ._base import (
    BboxValue,
    CsvValue,
    JsonObject,
    Params,
    _AsyncProtocol,
    _bbox,
    _bool_text,
    _csv,
    _params,
    _query_value,
    _service_path,
    _SyncProtocol,
)


class GeoServicesFeatureServerClient(_SyncProtocol):
    """Synchronous GeoServices FeatureServer wrapper.

    Use this client to query, paginate, and edit features on the
    GeoServices ``FeatureServer`` REST surface (``/rest/services/<id>/FeatureServer``).
    Surfaces helpers for layer metadata, paginated ``query`` walks,
    ``applyEdits`` mutations, and related-record lookups; mirrors the
    same shape as :class:`AsyncGeoServicesFeatureServerClient` for async
    callers. Reach this via :meth:`HonuaClient.feature_server`.
    """

    def __init__(self, client: Any, service_id: str) -> None:
        super().__init__(client)
        self.service_id = service_id

    @property
    def path(self) -> str:
        return _service_path(self.service_id, "FeatureServer")

    def metadata(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", self.path, params=_params({"f": response_format}, extra_params))

    def layer_metadata(self, layer_id: int, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", f"{self.path}/{layer_id}", params=_params({"f": response_format}, extra_params))

    def schema(self, layer_id: int, *, extra_params: Params = None) -> LayerSchema:
        """Return a typed :class:`LayerSchema` for a layer (arcpy.Describe analogue).

        Fetches ``layer_metadata`` and parses the raw JSON into typed fields,
        a normalized geometry type, the resolved spatial-reference WKID, and a
        typed extent — so a GP tool maps outputs without hand-parsing JSON.
        """
        return LayerSchema.from_metadata(self.layer_metadata(layer_id, extra_params=extra_params))

    def query(
        self,
        layer_id: int,
        *,
        where: str = "1=1",
        out_fields: CsvValue = "*",
        return_geometry: bool = True,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        return cast(
            JsonObject,
            self.client.query_features(
                self.service_id,
                layer_id,
                where=where,
                out_fields=out_fields,
                return_geometry=return_geometry,
                extra_params=extra_params,
                timeout=timeout,
                extra_headers=extra_headers,
            ),
        )

    def query_pages(
        self,
        layer_id: int,
        *,
        page_size: int = 1000,
        limit: int | None = None,
        max_pages: int = 100,
        where: str = "1=1",
        out_fields: CsvValue = "*",
        return_geometry: bool = True,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Iterator[FeatureSet]:
        if page_size <= 0:
            raise ValueError("page_size must be greater than zero.")
        if max_pages <= 0:
            raise ValueError("max_pages must be greater than zero.")
        if limit is not None and limit <= 0:
            return

        total = 0
        base_extra = dict(extra_params or {})
        offset = int(base_extra.get("resultOffset", 0))
        seen_object_ids: set[int] = set()
        for _ in range(max_pages):
            remaining = None if limit is None else limit - total
            if remaining is not None and remaining <= 0:
                break
            record_count = page_size if remaining is None else min(page_size, remaining)
            page_extra_params = {
                **base_extra,
                "resultOffset": offset,
                "resultRecordCount": record_count,
            }
            page = FeatureSet.from_dict(
                self.query(
                    layer_id,
                    where=where,
                    out_fields=out_fields,
                    return_geometry=return_geometry,
                    extra_params=page_extra_params,
                    timeout=timeout,
                    extra_headers=extra_headers,
                )
            )
            # Non-advancing-cursor guard: stop before re-yielding a page a
            # server that ignores ``resultOffset`` keeps returning (it would
            # otherwise loop to ``max_pages`` with duplicate features).
            new_object_ids = {oid for f in page.features if (oid := f.object_id) is not None}
            if new_object_ids and new_object_ids.issubset(seen_object_ids):
                break
            seen_object_ids |= new_object_ids
            yield page
            page_count = len(page.features)
            total += page_count
            if page_count < record_count or not page.exceeded_transfer_limit:
                break
            offset += page_count

    def query_all(
        self,
        layer_id: int,
        *,
        page_size: int = 1000,
        limit: int | None = None,
        max_pages: int = 100,
        where: str = "1=1",
        out_fields: CsvValue = "*",
        return_geometry: bool = True,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[Feature]:
        features: list[Feature] = []
        for page in self.query_pages(
            layer_id,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            where=where,
            out_fields=out_fields,
            return_geometry=return_geometry,
            extra_params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            remaining = None if limit is None else limit - len(features)
            page_features = list(page.features) if remaining is None else list(page.features)[:remaining]
            features.extend(page_features)
            if remaining is not None and len(features) >= limit:  # type: ignore[operator]
                break
        return features

    def query_items(
        self,
        layer_id: int,
        *,
        page_size: int = 1000,
        limit: int | None = None,
        max_pages: int = 100,
        where: str = "1=1",
        out_fields: CsvValue = "*",
        return_geometry: bool = True,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Iterator[Feature]:
        emitted = 0
        for page in self.query_pages(
            layer_id,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            where=where,
            out_fields=out_fields,
            return_geometry=return_geometry,
            extra_params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            for feature in page.features:
                if limit is not None and emitted >= limit:
                    return
                yield feature
                emitted += 1

    def apply_edits(
        self,
        layer_id: int,
        *,
        adds: Sequence[Mapping[str, Any]] | None = None,
        updates: Sequence[Mapping[str, Any]] | None = None,
        deletes: Sequence[int] | str | None = None,
        rollback_on_failure: bool = True,
        idempotency_key: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        return cast(
            JsonObject,
            self.client.apply_edits(
                self.service_id,
                layer_id,
                adds=adds,
                updates=updates,
                deletes=deletes,
                rollback_on_failure=rollback_on_failure,
                idempotency_key=idempotency_key,
                timeout=timeout,
                extra_headers=extra_headers,
            ),
        )

    def query_related_records(
        self,
        layer_id: int,
        *,
        object_ids: CsvValue,
        relationship_id: int,
        response_format: str = "json",
        extra_params: Params = None,
    ) -> JsonObject:
        params = _params(
            {"f": response_format, "objectIds": _csv(object_ids), "relationshipId": relationship_id},
            extra_params,
        )
        return self._json("GET", f"{self.path}/{layer_id}/queryRelatedRecords", params=params)


class GeoServicesMapServerClient(_SyncProtocol):
    """Synchronous GeoServices MapServer wrapper.

    Wraps the GeoServices ``MapServer`` REST surface
    (``/rest/services/<id>/MapServer``) for rendered map exports, the
    ``identify`` lookup, raw tile fetches, and layer metadata. Use this
    when you need rasterized output or attribute-only identify requests;
    for vector query/edit flows reach for
    :class:`GeoServicesFeatureServerClient` instead. Reach this via
    :meth:`HonuaClient.map_server`.
    """

    def __init__(self, client: Any, service_id: str) -> None:
        super().__init__(client)
        self.service_id = service_id

    @property
    def path(self) -> str:
        return _service_path(self.service_id, "MapServer")

    def metadata(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", self.path, params=_params({"f": response_format}, extra_params))

    def layer_metadata(self, layer_id: int, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", f"{self.path}/{layer_id}", params=_params({"f": response_format}, extra_params))

    def export(
        self,
        bbox: BboxValue,
        *,
        size: tuple[int, int] = (400, 400),
        image_format: str = "png",
        transparent: bool = True,
        dpi: int = 96,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> bytes:
        return cast(
            bytes,
            self.client.export_map(
                self.service_id,
                bbox,
                size=size,
                image_format=image_format,
                transparent=transparent,
                dpi=dpi,
                extra_params=extra_params,
                timeout=timeout,
                extra_headers=extra_headers,
            ),
        )

    def identify(
        self,
        *,
        geometry: Mapping[str, Any] | str,
        map_extent: BboxValue,
        image_display: str,
        tolerance: int = 3,
        layers: str | None = None,
        return_geometry: bool = True,
        response_format: str = "json",
        extra_params: Params = None,
    ) -> JsonObject:
        params = _params(
            {
                "f": response_format,
                "geometry": _query_value(geometry),
                "mapExtent": _bbox(map_extent),
                "imageDisplay": image_display,
                "tolerance": tolerance,
                "returnGeometry": _bool_text(return_geometry),
            },
            extra_params,
        )
        if layers is not None:
            params["layers"] = layers
        return self._json("GET", f"{self.path}/identify", params=params)

    def tile(self, level: int, row: int, col: int) -> bytes:
        return self._bytes(f"{self.path}/tile/{level}/{row}/{col}")


class GeoServicesImageServerClient(_SyncProtocol):
    """GeoServices ImageServer wrapper."""

    def __init__(self, client: Any, service_id: str | None = None) -> None:
        super().__init__(client)
        self.service_id = service_id

    @property
    def path(self) -> str:
        if self.service_id is None:
            return "/rest/services/ImageServer"
        return _service_path(self.service_id, "ImageServer")

    def metadata(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", self.path, params=_params({"f": response_format}, extra_params))

    def export_image(
        self,
        bbox: BboxValue,
        *,
        size: tuple[int, int] | None = None,
        image_format: str = "png",
        response_format: str = "image",
        extra_params: Params = None,
    ) -> bytes:
        params = _params({"f": response_format, "bbox": _bbox(bbox), "format": image_format}, extra_params)
        if size is not None:
            params["size"] = f"{size[0]},{size[1]}"
        return self._bytes(f"{self.path}/exportImage", params=params)

    def identify(self, geometry: Mapping[str, Any] | str, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        params = _params({"f": response_format, "geometry": _query_value(geometry)}, extra_params)
        return self._json("GET", f"{self.path}/identify", params=params)

    def query(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", f"{self.path}/query", params=_params({"f": response_format}, extra_params))

    def tile(self, level: int, row: int, col: int) -> bytes:
        return self._bytes(f"{self.path}/tile/{level}/{row}/{col}")

    def legend(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", f"{self.path}/legend", params=_params({"f": response_format}, extra_params))


class GeoServicesGeometryServerClient(_SyncProtocol):
    """GeoServices GeometryServer wrapper."""

    def __init__(self, client: Any) -> None:
        super().__init__(client)
        self.path = "/rest/services/Utilities/Geometry/GeometryServer"

    def metadata(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", self.path, params=_params({"f": response_format}, extra_params))

    def operation(
        self,
        name: str,
        *,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
        method: str = "GET",
        response_format: str = "json",
    ) -> JsonObject:
        request_params = _params({"f": response_format}, params)
        return self._json(method, f"{self.path}/{_encode_path_segment(name)}", params=request_params, json_body=json_body)

    def project(
        self,
        geometries: Any,
        *,
        in_sr: int | str,
        out_sr: int | str,
        extra_params: Params = None,
    ) -> JsonObject:
        params: dict[str, Any] = {
            "geometries": _query_value(geometries),
            "inSR": in_sr,
            "outSR": out_sr,
        }
        if extra_params:
            params.update(extra_params)
        return self.operation("project", params=params)

    def buffer(
        self,
        geometries: Any,
        *,
        in_sr: int | str,
        distances: CsvValue,
        unit: str | None = None,
        extra_params: Params = None,
    ) -> JsonObject:
        params: dict[str, Any] = {
            "geometries": _query_value(geometries),
            "inSR": in_sr,
            "distances": _csv(distances),
        }
        if extra_params:
            params.update(extra_params)
        if unit is not None:
            params["unit"] = unit
        return self.operation("buffer", params=params)

    def simplify(
        self,
        geometries: Any,
        *,
        sr: int | str | None = None,
        extra_params: Params = None,
    ) -> JsonObject:
        params: dict[str, Any] = {"geometries": _query_value(geometries)}
        if extra_params:
            params.update(extra_params)
        if sr is not None:
            params["sr"] = sr
        return self.operation("simplify", params=params)


class AsyncGeoServicesFeatureServerClient(_AsyncProtocol):
    """Async GeoServices FeatureServer wrapper."""

    def __init__(self, client: Any, service_id: str) -> None:
        super().__init__(client)
        self.service_id = service_id

    @property
    def path(self) -> str:
        return _service_path(self.service_id, "FeatureServer")

    async def metadata(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", self.path, params=_params({"f": response_format}, extra_params))

    async def layer_metadata(self, layer_id: int, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", f"{self.path}/{layer_id}", params=_params({"f": response_format}, extra_params))

    async def schema(self, layer_id: int, *, extra_params: Params = None) -> LayerSchema:
        """Return a typed :class:`LayerSchema` for a layer (arcpy.Describe analogue).

        Fetches ``layer_metadata`` and parses the raw JSON into typed fields,
        a normalized geometry type, the resolved spatial-reference WKID, and a
        typed extent — so a GP tool maps outputs without hand-parsing JSON.
        """
        return LayerSchema.from_metadata(await self.layer_metadata(layer_id, extra_params=extra_params))

    async def query(
        self,
        layer_id: int,
        *,
        where: str = "1=1",
        out_fields: CsvValue = "*",
        return_geometry: bool = True,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        return cast(
            JsonObject,
            await self.client.query_features(
                self.service_id,
                layer_id,
                where=where,
                out_fields=out_fields,
                return_geometry=return_geometry,
                extra_params=extra_params,
                timeout=timeout,
                extra_headers=extra_headers,
            ),
        )

    async def query_pages(
        self,
        layer_id: int,
        *,
        page_size: int = 1000,
        limit: int | None = None,
        max_pages: int = 100,
        where: str = "1=1",
        out_fields: CsvValue = "*",
        return_geometry: bool = True,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[FeatureSet]:
        if page_size <= 0:
            raise ValueError("page_size must be greater than zero.")
        if max_pages <= 0:
            raise ValueError("max_pages must be greater than zero.")
        if limit is not None and limit <= 0:
            return

        total = 0
        base_extra = dict(extra_params or {})
        offset = int(base_extra.get("resultOffset", 0))
        seen_object_ids: set[int] = set()
        for _ in range(max_pages):
            remaining = None if limit is None else limit - total
            if remaining is not None and remaining <= 0:
                break
            record_count = page_size if remaining is None else min(page_size, remaining)
            page_extra_params = {
                **base_extra,
                "resultOffset": offset,
                "resultRecordCount": record_count,
            }
            page = FeatureSet.from_dict(
                await self.query(
                    layer_id,
                    where=where,
                    out_fields=out_fields,
                    return_geometry=return_geometry,
                    extra_params=page_extra_params,
                    timeout=timeout,
                    extra_headers=extra_headers,
                )
            )
            # Non-advancing-cursor guard: stop before re-yielding a page a
            # server that ignores ``resultOffset`` keeps returning (it would
            # otherwise loop to ``max_pages`` with duplicate features).
            new_object_ids = {oid for f in page.features if (oid := f.object_id) is not None}
            if new_object_ids and new_object_ids.issubset(seen_object_ids):
                break
            seen_object_ids |= new_object_ids
            yield page
            page_count = len(page.features)
            total += page_count
            if page_count < record_count or not page.exceeded_transfer_limit:
                break
            offset += page_count

    async def query_all(
        self,
        layer_id: int,
        *,
        page_size: int = 1000,
        limit: int | None = None,
        max_pages: int = 100,
        where: str = "1=1",
        out_fields: CsvValue = "*",
        return_geometry: bool = True,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[Feature]:
        features: list[Feature] = []
        async for page in self.query_pages(
            layer_id,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            where=where,
            out_fields=out_fields,
            return_geometry=return_geometry,
            extra_params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            remaining = None if limit is None else limit - len(features)
            page_features = list(page.features) if remaining is None else list(page.features)[:remaining]
            features.extend(page_features)
            if remaining is not None and len(features) >= limit:  # type: ignore[operator]
                break
        return features

    async def query_items(
        self,
        layer_id: int,
        *,
        page_size: int = 1000,
        limit: int | None = None,
        max_pages: int = 100,
        where: str = "1=1",
        out_fields: CsvValue = "*",
        return_geometry: bool = True,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[Feature]:
        emitted = 0
        async for page in self.query_pages(
            layer_id,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            where=where,
            out_fields=out_fields,
            return_geometry=return_geometry,
            extra_params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            for feature in page.features:
                if limit is not None and emitted >= limit:
                    return
                yield feature
                emitted += 1

    async def apply_edits(
        self,
        layer_id: int,
        *,
        adds: Sequence[Mapping[str, Any]] | None = None,
        updates: Sequence[Mapping[str, Any]] | None = None,
        deletes: Sequence[int] | str | None = None,
        rollback_on_failure: bool = True,
        idempotency_key: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        return cast(
            JsonObject,
            await self.client.apply_edits(
                self.service_id,
                layer_id,
                adds=adds,
                updates=updates,
                deletes=deletes,
                rollback_on_failure=rollback_on_failure,
                idempotency_key=idempotency_key,
                timeout=timeout,
                extra_headers=extra_headers,
            ),
        )

    async def query_related_records(
        self,
        layer_id: int,
        *,
        object_ids: CsvValue,
        relationship_id: int,
        response_format: str = "json",
        extra_params: Params = None,
    ) -> JsonObject:
        params = _params(
            {"f": response_format, "objectIds": _csv(object_ids), "relationshipId": relationship_id},
            extra_params,
        )
        return await self._json("GET", f"{self.path}/{layer_id}/queryRelatedRecords", params=params)


class AsyncGeoServicesMapServerClient(_AsyncProtocol):
    """Async GeoServices MapServer wrapper."""

    def __init__(self, client: Any, service_id: str) -> None:
        super().__init__(client)
        self.service_id = service_id

    @property
    def path(self) -> str:
        return _service_path(self.service_id, "MapServer")

    async def metadata(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", self.path, params=_params({"f": response_format}, extra_params))

    async def layer_metadata(self, layer_id: int, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", f"{self.path}/{layer_id}", params=_params({"f": response_format}, extra_params))

    async def export(
        self,
        bbox: BboxValue,
        *,
        size: tuple[int, int] = (400, 400),
        image_format: str = "png",
        transparent: bool = True,
        dpi: int = 96,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> bytes:
        return cast(
            bytes,
            await self.client.export_map(
                self.service_id,
                bbox,
                size=size,
                image_format=image_format,
                transparent=transparent,
                dpi=dpi,
                extra_params=extra_params,
                timeout=timeout,
                extra_headers=extra_headers,
            ),
        )

    async def identify(
        self,
        *,
        geometry: Mapping[str, Any] | str,
        map_extent: BboxValue,
        image_display: str,
        tolerance: int = 3,
        layers: str | None = None,
        return_geometry: bool = True,
        response_format: str = "json",
        extra_params: Params = None,
    ) -> JsonObject:
        params = _params(
            {
                "f": response_format,
                "geometry": _query_value(geometry),
                "mapExtent": _bbox(map_extent),
                "imageDisplay": image_display,
                "tolerance": tolerance,
                "returnGeometry": _bool_text(return_geometry),
            },
            extra_params,
        )
        if layers is not None:
            params["layers"] = layers
        return await self._json("GET", f"{self.path}/identify", params=params)

    async def tile(self, level: int, row: int, col: int) -> bytes:
        return await self._bytes(f"{self.path}/tile/{level}/{row}/{col}")


class AsyncGeoServicesImageServerClient(_AsyncProtocol):
    """Async GeoServices ImageServer wrapper."""

    def __init__(self, client: Any, service_id: str | None = None) -> None:
        super().__init__(client)
        self.service_id = service_id

    @property
    def path(self) -> str:
        if self.service_id is None:
            return "/rest/services/ImageServer"
        return _service_path(self.service_id, "ImageServer")

    async def metadata(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", self.path, params=_params({"f": response_format}, extra_params))

    async def export_image(
        self,
        bbox: BboxValue,
        *,
        size: tuple[int, int] | None = None,
        image_format: str = "png",
        response_format: str = "image",
        extra_params: Params = None,
    ) -> bytes:
        params = _params({"f": response_format, "bbox": _bbox(bbox), "format": image_format}, extra_params)
        if size is not None:
            params["size"] = f"{size[0]},{size[1]}"
        return await self._bytes(f"{self.path}/exportImage", params=params)

    async def identify(self, geometry: Mapping[str, Any] | str, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        params = _params({"f": response_format, "geometry": _query_value(geometry)}, extra_params)
        return await self._json("GET", f"{self.path}/identify", params=params)

    async def query(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", f"{self.path}/query", params=_params({"f": response_format}, extra_params))

    async def tile(self, level: int, row: int, col: int) -> bytes:
        return await self._bytes(f"{self.path}/tile/{level}/{row}/{col}")

    async def legend(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", f"{self.path}/legend", params=_params({"f": response_format}, extra_params))


class AsyncGeoServicesGeometryServerClient(_AsyncProtocol):
    """Async GeoServices GeometryServer wrapper."""

    def __init__(self, client: Any) -> None:
        super().__init__(client)
        self.path = "/rest/services/Utilities/Geometry/GeometryServer"

    async def metadata(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", self.path, params=_params({"f": response_format}, extra_params))

    async def operation(
        self,
        name: str,
        *,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
        method: str = "GET",
        response_format: str = "json",
    ) -> JsonObject:
        request_params = _params({"f": response_format}, params)
        return await self._json(method, f"{self.path}/{_encode_path_segment(name)}", params=request_params, json_body=json_body)

    async def project(
        self,
        geometries: Any,
        *,
        in_sr: int | str,
        out_sr: int | str,
        extra_params: Params = None,
    ) -> JsonObject:
        params: dict[str, Any] = {
            "geometries": _query_value(geometries),
            "inSR": in_sr,
            "outSR": out_sr,
        }
        if extra_params:
            params.update(extra_params)
        return await self.operation("project", params=params)

    async def buffer(
        self,
        geometries: Any,
        *,
        in_sr: int | str,
        distances: CsvValue,
        unit: str | None = None,
        extra_params: Params = None,
    ) -> JsonObject:
        params: dict[str, Any] = {
            "geometries": _query_value(geometries),
            "inSR": in_sr,
            "distances": _csv(distances),
        }
        if extra_params:
            params.update(extra_params)
        if unit is not None:
            params["unit"] = unit
        return await self.operation("buffer", params=params)

    async def simplify(
        self,
        geometries: Any,
        *,
        sr: int | str | None = None,
        extra_params: Params = None,
    ) -> JsonObject:
        params: dict[str, Any] = {"geometries": _query_value(geometries)}
        if extra_params:
            params.update(extra_params)
        if sr is not None:
            params["sr"] = sr
        return await self.operation("simplify", params=params)
