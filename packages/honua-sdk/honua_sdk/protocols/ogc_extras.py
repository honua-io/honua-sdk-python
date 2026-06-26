"""OGC API Maps/Tiles/Coverages/Processes protocol clients."""

# ruff: noqa: E501, PLR0913

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator, Mapping
from typing import Any

from honua_sdk._http import _encode_path_segment

from ._base import (
    BboxValue,
    CsvValue,
    FeatureId,
    JsonObject,
    Params,
    _AsyncProtocol,
    _bbox,
    _csv,
    _next_link,
    _normalize_max_pages,
    _normalize_page_limit,
    _normalize_total_limit,
    _ogc_collection_path,
    _ogc_records_params,
    _params,
    _records_from_page,
    _SyncProtocol,
)


def _coverage_window_params(
    *,
    response_format: str,
    bbox: BboxValue | None,
    bbox_crs: str | None,
    crs: str | None,
    scale_size: str | None,
    scale_factor: float | None,
    resolution: str | None,
    properties: CsvValue | None,
    datetime: str | None,
    extra_params: Params,
) -> dict[str, Any]:
    """Build the query params for a windowed/subset OGC Coverages read.

    Maps the SDK's snake_case keyword arguments onto the kebab-case query
    parameters the Honua coverage handler reads (``bbox``, ``bbox-crs``,
    ``crs``, ``scale-size``, ``scale-factor``, ``resolution``,
    ``properties``, ``datetime``). Only set parameters are emitted, so an
    unwindowed call still requests the whole coverage. Note: the server
    rejects the OGC ``subset`` parameter and ``scale-axes`` — use ``bbox``
    for spatial subsetting and ``scale-size``/``scale-factor`` for scaling.
    """
    params: dict[str, Any] = {"f": response_format}
    if bbox is not None:
        params["bbox"] = _bbox(bbox)
    if bbox_crs is not None:
        params["bbox-crs"] = bbox_crs
    if crs is not None:
        params["crs"] = crs
    if scale_size is not None:
        params["scale-size"] = scale_size
    if scale_factor is not None:
        params["scale-factor"] = scale_factor
    if resolution is not None:
        params["resolution"] = resolution
    if properties is not None:
        params["properties"] = _csv(properties)
    if datetime is not None:
        params["datetime"] = datetime
    return _params(params, extra_params)


class OgcMapsClient(_SyncProtocol):
    """OGC API Maps wrapper."""

    root = "/ogc/maps"

    def landing(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", self.root, params=_params({"f": response_format}, extra_params))

    def conformance(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", f"{self.root}/conformance", params=_params({"f": response_format}, extra_params))

    def openapi(self) -> JsonObject:
        return self._json("GET", f"{self.root}/openapi.json")

    def map(self, *, collections: CsvValue, bbox: BboxValue, response_format: str = "png", extra_params: Params = None) -> bytes:
        return self._bytes(f"{self.root}/map", params=_params({"f": response_format, "collections": _csv(collections), "bbox": _bbox(bbox)}, extra_params))

    def collection_map(self, collection_id: FeatureId, *, bbox: BboxValue, response_format: str = "png", extra_params: Params = None) -> bytes:
        path = f"{_ogc_collection_path(self.root, collection_id)}/map"
        return self._bytes(path, params=_params({"f": response_format, "bbox": _bbox(bbox)}, extra_params))

    def styled_collection_map(
        self,
        collection_id: FeatureId,
        style_id: str,
        *,
        bbox: BboxValue,
        response_format: str = "png",
        extra_params: Params = None,
    ) -> bytes:
        path = f"{_ogc_collection_path(self.root, collection_id)}/styles/{_encode_path_segment(style_id)}/map"
        return self._bytes(path, params=_params({"f": response_format, "bbox": _bbox(bbox)}, extra_params))

    def collection_tilesets(self, collection_id: FeatureId) -> JsonObject:
        return self._json("GET", f"{_ogc_collection_path(self.root, collection_id)}/map/tiles")

    def collection_tileset(self, collection_id: FeatureId, tile_matrix_set_id: str) -> JsonObject:
        path = f"{_ogc_collection_path(self.root, collection_id)}/map/tiles/{_encode_path_segment(tile_matrix_set_id)}"
        return self._json("GET", path)


class OgcTilesClient(_SyncProtocol):
    """OGC API Tiles wrapper."""

    root = "/ogc/tiles"

    def landing(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", self.root, params=_params({"f": response_format}, extra_params))

    def conformance(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", f"{self.root}/conformance", params=_params({"f": response_format}, extra_params))

    def collections(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", f"{self.root}/collections", params=_params({"f": response_format}, extra_params))

    def collection(self, collection_id: FeatureId, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", _ogc_collection_path(self.root, collection_id), params=_params({"f": response_format}, extra_params))

    def tile_matrix_sets(self) -> JsonObject:
        return self._json("GET", f"{self.root}/tileMatrixSets")

    def tile_matrix_set(self, tile_matrix_set_id: str) -> JsonObject:
        return self._json("GET", f"{self.root}/tileMatrixSets/{_encode_path_segment(tile_matrix_set_id)}")

    def dataset_tilesets(self) -> JsonObject:
        return self._json("GET", f"{self.root}/tiles")

    def collection_tilesets(self, collection_id: FeatureId) -> JsonObject:
        return self._json("GET", f"{_ogc_collection_path(self.root, collection_id)}/tiles")

    def tile(self, tile_matrix_set_id: str, tile_matrix: str, row: int, col: int, *, collection_id: FeatureId | None = None) -> bytes:
        prefix = f"{self.root}/tiles" if collection_id is None else f"{_ogc_collection_path(self.root, collection_id)}/tiles"
        path = f"{prefix}/{_encode_path_segment(tile_matrix_set_id)}/{_encode_path_segment(tile_matrix)}/{row}/{col}"
        return self._bytes(path)


class OgcCoveragesClient(_SyncProtocol):
    """OGC API Coverages wrapper."""

    root = "/ogc/coverages"

    def landing(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", self.root, params=_params({"f": response_format}, extra_params))

    def collections(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", f"{self.root}/collections", params=_params({"f": response_format}, extra_params))

    def collection(self, collection_id: FeatureId, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", _ogc_collection_path(self.root, collection_id), params=_params({"f": response_format}, extra_params))

    def coverage(
        self,
        collection_id: FeatureId,
        *,
        bbox: BboxValue | None = None,
        bbox_crs: str | None = None,
        crs: str | None = None,
        scale_size: str | None = None,
        scale_factor: float | None = None,
        resolution: str | None = None,
        properties: CsvValue | None = None,
        datetime: str | None = None,
        response_format: str = "json",
        extra_params: Params = None,
    ) -> bytes:
        """Read a coverage, optionally windowed to a subset of the source raster.

        With no subset arguments this returns the whole coverage (as before).
        Pass ``bbox`` (in ``bbox_crs``) to clip a spatial window, and one of
        ``scale_size`` (e.g. ``"x(512),y(512)"``), ``scale_factor``, or
        ``resolution`` to read at a reduced/target resolution rather than
        downloading the full-resolution blob — the raster-GP equivalent of
        reading a clipped, possibly resampled extent. ``properties`` selects a
        band subset; ``datetime`` selects a temporal slice; ``crs`` sets the
        output CRS.
        """
        params = _coverage_window_params(
            response_format=response_format,
            bbox=bbox,
            bbox_crs=bbox_crs,
            crs=crs,
            scale_size=scale_size,
            scale_factor=scale_factor,
            resolution=resolution,
            properties=properties,
            datetime=datetime,
            extra_params=extra_params,
        )
        return self._bytes(f"{_ogc_collection_path(self.root, collection_id)}/coverage", params=params)


class OgcProcessesClient(_SyncProtocol):
    """OGC API Processes wrapper."""

    root = "/ogc/processes"

    def landing(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", self.root, params=_params({"f": response_format}, extra_params))

    def conformance(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", f"{self.root}/conformance", params=_params({"f": response_format}, extra_params))

    def processes(self) -> JsonObject:
        return self._json("GET", f"{self.root}/processes")

    def process(self, process_id: str) -> JsonObject:
        return self._json("GET", f"{self.root}/processes/{_encode_path_segment(process_id)}")

    def execute(self, process_id: str, payload: Mapping[str, Any]) -> JsonObject:
        return self._json("POST", f"{self.root}/processes/{_encode_path_segment(process_id)}/execution", json_body=payload)

    def jobs(self) -> JsonObject:
        return self._json("GET", f"{self.root}/jobs")

    def job(self, job_id: str) -> JsonObject:
        return self._json("GET", f"{self.root}/jobs/{_encode_path_segment(job_id)}")

    def job_results(self, job_id: str) -> JsonObject:
        return self._json("GET", f"{self.root}/jobs/{_encode_path_segment(job_id)}/results")

    def dismiss_job(self, job_id: str) -> None:
        self._json("DELETE", f"{self.root}/jobs/{_encode_path_segment(job_id)}")


class AsyncOgcMapsClient(_AsyncProtocol):
    """Async OGC API Maps wrapper."""

    root = "/ogc/maps"

    async def landing(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", self.root, params=_params({"f": response_format}, extra_params))

    async def conformance(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", f"{self.root}/conformance", params=_params({"f": response_format}, extra_params))

    async def openapi(self) -> JsonObject:
        return await self._json("GET", f"{self.root}/openapi.json")

    async def map(self, *, collections: CsvValue, bbox: BboxValue, response_format: str = "png", extra_params: Params = None) -> bytes:
        return await self._bytes(f"{self.root}/map", params=_params({"f": response_format, "collections": _csv(collections), "bbox": _bbox(bbox)}, extra_params))

    async def collection_map(self, collection_id: FeatureId, *, bbox: BboxValue, response_format: str = "png", extra_params: Params = None) -> bytes:
        path = f"{_ogc_collection_path(self.root, collection_id)}/map"
        return await self._bytes(path, params=_params({"f": response_format, "bbox": _bbox(bbox)}, extra_params))

    async def styled_collection_map(
        self,
        collection_id: FeatureId,
        style_id: str,
        *,
        bbox: BboxValue,
        response_format: str = "png",
        extra_params: Params = None,
    ) -> bytes:
        path = f"{_ogc_collection_path(self.root, collection_id)}/styles/{_encode_path_segment(style_id)}/map"
        return await self._bytes(path, params=_params({"f": response_format, "bbox": _bbox(bbox)}, extra_params))

    async def collection_tilesets(self, collection_id: FeatureId) -> JsonObject:
        return await self._json("GET", f"{_ogc_collection_path(self.root, collection_id)}/map/tiles")

    async def collection_tileset(self, collection_id: FeatureId, tile_matrix_set_id: str) -> JsonObject:
        path = f"{_ogc_collection_path(self.root, collection_id)}/map/tiles/{_encode_path_segment(tile_matrix_set_id)}"
        return await self._json("GET", path)


class AsyncOgcTilesClient(_AsyncProtocol):
    """Async OGC API Tiles wrapper."""

    root = "/ogc/tiles"

    async def landing(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", self.root, params=_params({"f": response_format}, extra_params))

    async def conformance(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", f"{self.root}/conformance", params=_params({"f": response_format}, extra_params))

    async def collections(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", f"{self.root}/collections", params=_params({"f": response_format}, extra_params))

    async def collection(self, collection_id: FeatureId, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", _ogc_collection_path(self.root, collection_id), params=_params({"f": response_format}, extra_params))

    async def tile_matrix_sets(self) -> JsonObject:
        return await self._json("GET", f"{self.root}/tileMatrixSets")

    async def tile_matrix_set(self, tile_matrix_set_id: str) -> JsonObject:
        return await self._json("GET", f"{self.root}/tileMatrixSets/{_encode_path_segment(tile_matrix_set_id)}")

    async def dataset_tilesets(self) -> JsonObject:
        return await self._json("GET", f"{self.root}/tiles")

    async def collection_tilesets(self, collection_id: FeatureId) -> JsonObject:
        return await self._json("GET", f"{_ogc_collection_path(self.root, collection_id)}/tiles")

    async def tile(self, tile_matrix_set_id: str, tile_matrix: str, row: int, col: int, *, collection_id: FeatureId | None = None) -> bytes:
        prefix = f"{self.root}/tiles" if collection_id is None else f"{_ogc_collection_path(self.root, collection_id)}/tiles"
        path = f"{prefix}/{_encode_path_segment(tile_matrix_set_id)}/{_encode_path_segment(tile_matrix)}/{row}/{col}"
        return await self._bytes(path)


class AsyncOgcCoveragesClient(_AsyncProtocol):
    """Async OGC API Coverages wrapper."""

    root = "/ogc/coverages"

    async def landing(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", self.root, params=_params({"f": response_format}, extra_params))

    async def collections(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", f"{self.root}/collections", params=_params({"f": response_format}, extra_params))

    async def collection(self, collection_id: FeatureId, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", _ogc_collection_path(self.root, collection_id), params=_params({"f": response_format}, extra_params))

    async def coverage(
        self,
        collection_id: FeatureId,
        *,
        bbox: BboxValue | None = None,
        bbox_crs: str | None = None,
        crs: str | None = None,
        scale_size: str | None = None,
        scale_factor: float | None = None,
        resolution: str | None = None,
        properties: CsvValue | None = None,
        datetime: str | None = None,
        response_format: str = "json",
        extra_params: Params = None,
    ) -> bytes:
        """Read a coverage, optionally windowed to a subset of the source raster.

        With no subset arguments this returns the whole coverage (as before).
        Pass ``bbox`` (in ``bbox_crs``) to clip a spatial window, and one of
        ``scale_size`` (e.g. ``"x(512),y(512)"``), ``scale_factor``, or
        ``resolution`` to read at a reduced/target resolution rather than
        downloading the full-resolution blob — the raster-GP equivalent of
        reading a clipped, possibly resampled extent. ``properties`` selects a
        band subset; ``datetime`` selects a temporal slice; ``crs`` sets the
        output CRS.
        """
        params = _coverage_window_params(
            response_format=response_format,
            bbox=bbox,
            bbox_crs=bbox_crs,
            crs=crs,
            scale_size=scale_size,
            scale_factor=scale_factor,
            resolution=resolution,
            properties=properties,
            datetime=datetime,
            extra_params=extra_params,
        )
        return await self._bytes(f"{_ogc_collection_path(self.root, collection_id)}/coverage", params=params)


class AsyncOgcProcessesClient(_AsyncProtocol):
    """Async OGC API Processes wrapper."""

    root = "/ogc/processes"

    async def landing(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", self.root, params=_params({"f": response_format}, extra_params))

    async def conformance(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", f"{self.root}/conformance", params=_params({"f": response_format}, extra_params))

    async def processes(self) -> JsonObject:
        return await self._json("GET", f"{self.root}/processes")

    async def process(self, process_id: str) -> JsonObject:
        return await self._json("GET", f"{self.root}/processes/{_encode_path_segment(process_id)}")

    async def execute(self, process_id: str, payload: Mapping[str, Any]) -> JsonObject:
        return await self._json("POST", f"{self.root}/processes/{_encode_path_segment(process_id)}/execution", json_body=payload)

    async def jobs(self) -> JsonObject:
        return await self._json("GET", f"{self.root}/jobs")

    async def job(self, job_id: str) -> JsonObject:
        return await self._json("GET", f"{self.root}/jobs/{_encode_path_segment(job_id)}")

    async def job_results(self, job_id: str) -> JsonObject:
        return await self._json("GET", f"{self.root}/jobs/{_encode_path_segment(job_id)}/results")

    async def dismiss_job(self, job_id: str) -> None:
        await self._json("DELETE", f"{self.root}/jobs/{_encode_path_segment(job_id)}")


class OgcRecordsClient(_SyncProtocol):
    """OGC API Records wrapper."""

    root = "/ogc/records"

    def collection(self, collection_id: FeatureId) -> "OgcRecordsCollectionClient":
        return OgcRecordsCollectionClient(self.client, collection_id)

    def landing(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", self.root, params=_params({"f": response_format}, extra_params))

    def conformance(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", f"{self.root}/conformance", params=_params({"f": response_format}, extra_params))

    def openapi(self) -> JsonObject:
        return self._json("GET", f"{self.root}/openapi.json")

    def collections(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", f"{self.root}/collections", params=_params({"f": response_format}, extra_params))

    def get_collection(
        self,
        collection_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Params = None,
    ) -> JsonObject:
        return self._json(
            "GET",
            _ogc_collection_path(self.root, collection_id),
            params=_params({"f": response_format}, extra_params),
        )

    def queryables(
        self,
        collection_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Params = None,
    ) -> JsonObject:
        return self._json(
            "GET",
            f"{_ogc_collection_path(self.root, collection_id)}/queryables",
            params=_params({"f": response_format}, extra_params),
        )

    def records(
        self,
        collection_id: FeatureId,
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
        properties: CsvValue | None = None,
        sortby: str | None = None,
        type: str | None = None,
    ) -> JsonObject:
        return self._json(
            "GET",
            f"{_ogc_collection_path(self.root, collection_id)}/items",
            params=_ogc_records_params(
                response_format=response_format,
                extra_params=extra_params,
                limit=limit,
                offset=offset,
                bbox=bbox,
                datetime=datetime,
                filter=filter,
                q=q,
                ids=ids,
                properties=properties,
                sortby=sortby,
                type=type,
            ),
        )

    def items(self, collection_id: FeatureId, **kwargs: Any) -> JsonObject:
        return self.records(collection_id, **kwargs)

    def record(
        self,
        collection_id: FeatureId,
        record_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Params = None,
    ) -> JsonObject:
        path = f"{_ogc_collection_path(self.root, collection_id)}/items/{_encode_path_segment(str(record_id))}"
        return self._json("GET", path, params=_params({"f": response_format}, extra_params))

    def item(self, collection_id: FeatureId, record_id: FeatureId, **kwargs: Any) -> JsonObject:
        return self.record(collection_id, record_id, **kwargs)

    def search(
        self,
        *,
        collection_id: FeatureId | None = None,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> JsonObject:
        if collection_id is None:
            path = f"{self.root}/search"
        else:
            path = f"{_ogc_collection_path(self.root, collection_id)}/items"
        if json_body is not None:
            return self._json("POST", path, params=params, json_body=json_body)
        return self._json("GET", path, params=params)

    def record_pages(
        self,
        collection_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Params = None,
        limit: int | None = None,
        offset: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        bbox: BboxValue | None = None,
        datetime: str | None = None,
        filter: str | None = None,
        q: str | None = None,
        ids: CsvValue | None = None,
        properties: CsvValue | None = None,
        sortby: str | None = None,
        type: str | None = None,
    ) -> Iterator[JsonObject]:
        yield from self.collection(collection_id).record_pages(
            response_format=response_format,
            extra_params=extra_params,
            limit=limit,
            offset=offset,
            page_size=page_size,
            max_pages=max_pages,
            bbox=bbox,
            datetime=datetime,
            filter=filter,
            q=q,
            ids=ids,
            properties=properties,
            sortby=sortby,
            type=type,
        )

    def records_all(self, collection_id: FeatureId, **kwargs: Any) -> list[JsonObject]:
        return list(self.iter_records(collection_id, **kwargs))

    def iter_records(self, collection_id: FeatureId, **kwargs: Any) -> Iterator[JsonObject]:
        yield from self.collection(collection_id).iter_records(**kwargs)


class OgcRecordsCollectionClient:
    """Collection-bound synchronous OGC API Records wrapper."""

    def __init__(self, client: Any, collection_id: FeatureId) -> None:
        self.client = client
        self.collection_id = collection_id

    def metadata(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return OgcRecordsClient(self.client).get_collection(
            self.collection_id,
            response_format=response_format,
            extra_params=extra_params,
        )

    def queryables(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return OgcRecordsClient(self.client).queryables(
            self.collection_id,
            response_format=response_format,
            extra_params=extra_params,
        )

    def records(
        self,
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
        properties: CsvValue | None = None,
        sortby: str | None = None,
        type: str | None = None,
    ) -> JsonObject:
        return OgcRecordsClient(self.client).records(
            self.collection_id,
            response_format=response_format,
            extra_params=extra_params,
            limit=limit,
            offset=offset,
            bbox=bbox,
            datetime=datetime,
            filter=filter,
            q=q,
            ids=ids,
            properties=properties,
            sortby=sortby,
            type=type,
        )

    def items(self, **kwargs: Any) -> JsonObject:
        return self.records(**kwargs)

    def record(
        self,
        record_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Params = None,
    ) -> JsonObject:
        return OgcRecordsClient(self.client).record(
            self.collection_id,
            record_id,
            response_format=response_format,
            extra_params=extra_params,
        )

    def item(self, record_id: FeatureId, **kwargs: Any) -> JsonObject:
        return self.record(record_id, **kwargs)

    def search(self, *, params: Params = None, json_body: Mapping[str, Any] | None = None) -> JsonObject:
        return OgcRecordsClient(self.client).search(
            collection_id=self.collection_id,
            params=params,
            json_body=json_body,
        )

    def record_pages(
        self,
        *,
        response_format: str = "json",
        extra_params: Params = None,
        limit: int | None = None,
        offset: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        bbox: BboxValue | None = None,
        datetime: str | None = None,
        filter: str | None = None,
        q: str | None = None,
        ids: CsvValue | None = None,
        properties: CsvValue | None = None,
        sortby: str | None = None,
        type: str | None = None,
    ) -> Iterator[JsonObject]:
        effective_page_size = _normalize_page_limit(page_size, limit)
        effective_max_pages = _normalize_max_pages(max_pages)
        total_limit = _normalize_total_limit(limit)
        if total_limit == 0:
            return

        fetched = 0
        next_href: str | None = None
        current_offset = 0 if offset is None else max(0, offset)
        for _ in range(effective_max_pages):
            remaining = effective_page_size if total_limit is None else max(0, total_limit - fetched)
            if remaining < 1:
                break
            page_limit = min(effective_page_size, remaining)
            if next_href is not None:
                page = OgcRecordsClient(self.client)._json_href(next_href)
            else:
                page = self.records(
                    response_format=response_format,
                    extra_params=extra_params,
                    limit=page_limit,
                    offset=current_offset,
                    bbox=bbox,
                    datetime=datetime,
                    filter=filter,
                    q=q,
                    ids=ids,
                    properties=properties,
                    sortby=sortby,
                    type=type,
                )

            yield page
            page_records = _records_from_page(page)
            fetched += len(page_records)
            next_href = _next_link(page)
            if next_href is None:
                if len(page_records) < page_limit:
                    break
                current_offset += len(page_records)

    def records_all(self, **kwargs: Any) -> list[JsonObject]:
        return list(self.iter_records(**kwargs))

    def iter_records(self, **kwargs: Any) -> Iterator[JsonObject]:
        emitted = 0
        limit = kwargs.get("limit")
        for page in self.record_pages(**kwargs):
            for record in _records_from_page(page):
                if limit is not None and emitted >= limit:
                    return
                yield record
                emitted += 1

    def items_all(self, **kwargs: Any) -> list[JsonObject]:
        return self.records_all(**kwargs)


class AsyncOgcRecordsClient(_AsyncProtocol):
    """Async OGC API Records wrapper."""

    root = "/ogc/records"

    def collection(self, collection_id: FeatureId) -> "AsyncOgcRecordsCollectionClient":
        return AsyncOgcRecordsCollectionClient(self.client, collection_id)

    async def landing(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", self.root, params=_params({"f": response_format}, extra_params))

    async def conformance(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", f"{self.root}/conformance", params=_params({"f": response_format}, extra_params))

    async def openapi(self) -> JsonObject:
        return await self._json("GET", f"{self.root}/openapi.json")

    async def collections(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", f"{self.root}/collections", params=_params({"f": response_format}, extra_params))

    async def get_collection(
        self,
        collection_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Params = None,
    ) -> JsonObject:
        return await self._json(
            "GET",
            _ogc_collection_path(self.root, collection_id),
            params=_params({"f": response_format}, extra_params),
        )

    async def queryables(
        self,
        collection_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Params = None,
    ) -> JsonObject:
        return await self._json(
            "GET",
            f"{_ogc_collection_path(self.root, collection_id)}/queryables",
            params=_params({"f": response_format}, extra_params),
        )

    async def records(
        self,
        collection_id: FeatureId,
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
        properties: CsvValue | None = None,
        sortby: str | None = None,
        type: str | None = None,
    ) -> JsonObject:
        return await self._json(
            "GET",
            f"{_ogc_collection_path(self.root, collection_id)}/items",
            params=_ogc_records_params(
                response_format=response_format,
                extra_params=extra_params,
                limit=limit,
                offset=offset,
                bbox=bbox,
                datetime=datetime,
                filter=filter,
                q=q,
                ids=ids,
                properties=properties,
                sortby=sortby,
                type=type,
            ),
        )

    async def items(self, collection_id: FeatureId, **kwargs: Any) -> JsonObject:
        return await self.records(collection_id, **kwargs)

    async def record(
        self,
        collection_id: FeatureId,
        record_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Params = None,
    ) -> JsonObject:
        path = f"{_ogc_collection_path(self.root, collection_id)}/items/{_encode_path_segment(str(record_id))}"
        return await self._json("GET", path, params=_params({"f": response_format}, extra_params))

    async def item(self, collection_id: FeatureId, record_id: FeatureId, **kwargs: Any) -> JsonObject:
        return await self.record(collection_id, record_id, **kwargs)

    async def search(
        self,
        *,
        collection_id: FeatureId | None = None,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> JsonObject:
        if collection_id is None:
            path = f"{self.root}/search"
        else:
            path = f"{_ogc_collection_path(self.root, collection_id)}/items"
        if json_body is not None:
            return await self._json("POST", path, params=params, json_body=json_body)
        return await self._json("GET", path, params=params)

    async def record_pages(self, collection_id: FeatureId, **kwargs: Any) -> AsyncIterator[JsonObject]:
        async for page in self.collection(collection_id).record_pages(**kwargs):
            yield page

    async def records_all(self, collection_id: FeatureId, **kwargs: Any) -> list[JsonObject]:
        return [record async for record in self.iter_records(collection_id, **kwargs)]

    async def iter_records(self, collection_id: FeatureId, **kwargs: Any) -> AsyncIterator[JsonObject]:
        async for record in self.collection(collection_id).iter_records(**kwargs):
            yield record


class AsyncOgcRecordsCollectionClient:
    """Collection-bound asynchronous OGC API Records wrapper."""

    def __init__(self, client: Any, collection_id: FeatureId) -> None:
        self.client = client
        self.collection_id = collection_id

    async def metadata(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await AsyncOgcRecordsClient(self.client).get_collection(
            self.collection_id,
            response_format=response_format,
            extra_params=extra_params,
        )

    async def queryables(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await AsyncOgcRecordsClient(self.client).queryables(
            self.collection_id,
            response_format=response_format,
            extra_params=extra_params,
        )

    async def records(
        self,
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
        properties: CsvValue | None = None,
        sortby: str | None = None,
        type: str | None = None,
    ) -> JsonObject:
        return await AsyncOgcRecordsClient(self.client).records(
            self.collection_id,
            response_format=response_format,
            extra_params=extra_params,
            limit=limit,
            offset=offset,
            bbox=bbox,
            datetime=datetime,
            filter=filter,
            q=q,
            ids=ids,
            properties=properties,
            sortby=sortby,
            type=type,
        )

    async def items(self, **kwargs: Any) -> JsonObject:
        return await self.records(**kwargs)

    async def record(
        self,
        record_id: FeatureId,
        *,
        response_format: str = "json",
        extra_params: Params = None,
    ) -> JsonObject:
        return await AsyncOgcRecordsClient(self.client).record(
            self.collection_id,
            record_id,
            response_format=response_format,
            extra_params=extra_params,
        )

    async def item(self, record_id: FeatureId, **kwargs: Any) -> JsonObject:
        return await self.record(record_id, **kwargs)

    async def search(self, *, params: Params = None, json_body: Mapping[str, Any] | None = None) -> JsonObject:
        return await AsyncOgcRecordsClient(self.client).search(
            collection_id=self.collection_id,
            params=params,
            json_body=json_body,
        )

    async def record_pages(
        self,
        *,
        response_format: str = "json",
        extra_params: Params = None,
        limit: int | None = None,
        offset: int | None = None,
        page_size: int | None = None,
        max_pages: int | None = None,
        bbox: BboxValue | None = None,
        datetime: str | None = None,
        filter: str | None = None,
        q: str | None = None,
        ids: CsvValue | None = None,
        properties: CsvValue | None = None,
        sortby: str | None = None,
        type: str | None = None,
    ) -> AsyncIterator[JsonObject]:
        effective_page_size = _normalize_page_limit(page_size, limit)
        effective_max_pages = _normalize_max_pages(max_pages)
        total_limit = _normalize_total_limit(limit)
        if total_limit == 0:
            return

        fetched = 0
        next_href: str | None = None
        current_offset = 0 if offset is None else max(0, offset)
        for _ in range(effective_max_pages):
            remaining = effective_page_size if total_limit is None else max(0, total_limit - fetched)
            if remaining < 1:
                break
            page_limit = min(effective_page_size, remaining)
            if next_href is not None:
                page = await AsyncOgcRecordsClient(self.client)._json_href(next_href)
            else:
                page = await self.records(
                    response_format=response_format,
                    extra_params=extra_params,
                    limit=page_limit,
                    offset=current_offset,
                    bbox=bbox,
                    datetime=datetime,
                    filter=filter,
                    q=q,
                    ids=ids,
                    properties=properties,
                    sortby=sortby,
                    type=type,
                )

            yield page
            page_records = _records_from_page(page)
            fetched += len(page_records)
            next_href = _next_link(page)
            if next_href is None:
                if len(page_records) < page_limit:
                    break
                current_offset += len(page_records)

    async def records_all(self, **kwargs: Any) -> list[JsonObject]:
        return [record async for record in self.iter_records(**kwargs)]

    async def iter_records(self, **kwargs: Any) -> AsyncIterator[JsonObject]:
        emitted = 0
        limit = kwargs.get("limit")
        async for page in self.record_pages(**kwargs):
            for record in _records_from_page(page):
                if limit is not None and emitted >= limit:
                    return
                yield record
                emitted += 1

    async def items_all(self, **kwargs: Any) -> list[JsonObject]:
        return await self.records_all(**kwargs)

    async def iter_items(self, **kwargs: Any) -> AsyncIterator[JsonObject]:
        async for record in self.iter_records(**kwargs):
            yield record
