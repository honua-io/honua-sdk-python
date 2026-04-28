"""Protocol-specific clients for Honua Server surfaces."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias
from urllib.parse import parse_qsl, urlsplit

import httpx

from ._http import _encode_path_segment, _to_http_error, _to_transport_error
from .models import Feature, FeatureSet

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
    ) -> JsonObject:
        return self.client._request_json(method, path, params=params, json_body=json_body, headers=headers)

    def _json_href(self, href: str) -> JsonObject:
        path, params = _path_and_params_from_href(href)
        return self._json("GET", path, params=params)

    def _bytes(self, path: str, *, params: Params = None) -> bytes:
        return self.client._request("GET", path, params=params).content

    def _binary_response(self, path: str, *, params: Params = None) -> BinaryResponse:
        return BinaryResponse.from_httpx(self.client._request("GET", path, params=params))

    def _text(self, method: str, path: str, *, params: Params = None, content: bytes | str | None = None) -> str:
        body = content.encode("utf-8") if isinstance(content, str) else content
        try:
            response = self.client._client.request(method=method, url=path, params=params, content=body)
        except httpx.HTTPError as exc:
            raise _to_transport_error(exc) from exc
        if response.status_code >= 400:
            raise _to_http_error(response)
        return response.text


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
    ) -> JsonObject:
        return await self.client._request_json(method, path, params=params, json_body=json_body, headers=headers)

    async def _json_href(self, href: str) -> JsonObject:
        path, params = _path_and_params_from_href(href)
        return await self._json("GET", path, params=params)

    async def _bytes(self, path: str, *, params: Params = None) -> bytes:
        response = await self.client._request("GET", path, params=params)
        return response.content

    async def _binary_response(self, path: str, *, params: Params = None) -> BinaryResponse:
        response = await self.client._request("GET", path, params=params)
        return BinaryResponse.from_httpx(response)

    async def _text(self, method: str, path: str, *, params: Params = None, content: bytes | str | None = None) -> str:
        body = content.encode("utf-8") if isinstance(content, str) else content
        try:
            response = await self.client._client.request(method=method, url=path, params=params, content=body)
        except httpx.HTTPError as exc:
            raise _to_transport_error(exc) from exc
        if response.status_code >= 400:
            raise _to_http_error(response)
        return response.text


class GeoServicesFeatureServerClient(_SyncProtocol):
    """GeoServices FeatureServer wrapper."""

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

    def query(self, layer_id: int, **kwargs: Any) -> JsonObject:
        return self.client.query_features(self.service_id, layer_id, **kwargs)

    def query_pages(
        self,
        layer_id: int,
        *,
        page_size: int = 1000,
        limit: int | None = None,
        max_pages: int = 100,
        **kwargs: Any,
    ) -> Iterator[FeatureSet]:
        if page_size <= 0:
            raise ValueError("page_size must be greater than zero.")
        if max_pages <= 0:
            raise ValueError("max_pages must be greater than zero.")
        if limit is not None and limit <= 0:
            return

        total = 0
        extra_params = dict(kwargs.pop("extra_params", {}) or {})
        offset = int(extra_params.get("resultOffset", 0))
        for _ in range(max_pages):
            remaining = None if limit is None else limit - total
            if remaining is not None and remaining <= 0:
                break
            record_count = page_size if remaining is None else min(page_size, remaining)
            page_extra_params = {
                **extra_params,
                "resultOffset": offset,
                "resultRecordCount": record_count,
            }
            page = FeatureSet.from_dict(
                self.query(layer_id, extra_params=page_extra_params, **kwargs)
            )
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
        **kwargs: Any,
    ) -> list[Feature]:
        features: list[Feature] = []
        for page in self.query_pages(layer_id, page_size=page_size, limit=limit, max_pages=max_pages, **kwargs):
            remaining = None if limit is None else limit - len(features)
            page_features = list(page.features) if remaining is None else list(page.features)[:remaining]
            features.extend(page_features)
            if remaining is not None and len(features) >= limit:
                break
        return features

    def query_items(
        self,
        layer_id: int,
        *,
        page_size: int = 1000,
        limit: int | None = None,
        max_pages: int = 100,
        **kwargs: Any,
    ) -> Iterator[Feature]:
        emitted = 0
        for page in self.query_pages(layer_id, page_size=page_size, limit=limit, max_pages=max_pages, **kwargs):
            for feature in page.features:
                if limit is not None and emitted >= limit:
                    return
                yield feature
                emitted += 1

    def apply_edits(self, layer_id: int, **kwargs: Any) -> JsonObject:
        return self.client.apply_edits(self.service_id, layer_id, **kwargs)

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
    """GeoServices MapServer wrapper."""

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

    def export(self, bbox: BboxValue, **kwargs: Any) -> bytes:
        return self.client.export_map(self.service_id, bbox, **kwargs)

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

    def project(self, geometries: Any, *, in_sr: int | str, out_sr: int | str, **kwargs: Any) -> JsonObject:
        return self.operation("project", params={"geometries": _query_value(geometries), "inSR": in_sr, "outSR": out_sr, **kwargs})

    def buffer(self, geometries: Any, *, in_sr: int | str, distances: CsvValue, unit: str | None = None, **kwargs: Any) -> JsonObject:
        params = {"geometries": _query_value(geometries), "inSR": in_sr, "distances": _csv(distances), **kwargs}
        if unit is not None:
            params["unit"] = unit
        return self.operation("buffer", params=params)

    def simplify(self, geometries: Any, *, sr: int | str | None = None, **kwargs: Any) -> JsonObject:
        params = {"geometries": _query_value(geometries), **kwargs}
        if sr is not None:
            params["sr"] = sr
        return self.operation("simplify", params=params)


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

    def coverage(self, collection_id: FeatureId, *, response_format: str = "json", extra_params: Params = None) -> bytes:
        return self._bytes(f"{_ogc_collection_path(self.root, collection_id)}/coverage", params=_params({"f": response_format}, extra_params))


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


class StacClient(_SyncProtocol):
    """STAC API wrapper."""

    root = "/stac"

    def catalog(self) -> JsonObject:
        return self._json("GET", self.root)

    def collections(self) -> JsonObject:
        return self._json("GET", f"{self.root}/collections")

    def collection(self, collection_id: FeatureId) -> JsonObject:
        return self._json("GET", f"{self.root}/collections/{_encode_path_segment(str(collection_id))}")

    def items(self, collection_id: FeatureId, *, extra_params: Params = None) -> JsonObject:
        return self._json("GET", f"{self.root}/collections/{_encode_path_segment(str(collection_id))}/items", params=extra_params)

    def item_pages(
        self,
        collection_id: FeatureId,
        *,
        extra_params: Params = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
    ) -> Iterator[JsonObject]:
        effective_page_size = _normalize_page_limit(page_size, limit)
        effective_max_pages = _normalize_max_pages(max_pages)
        total_limit = _normalize_total_limit(limit)
        if total_limit == 0:
            return

        fetched = 0
        next_href: str | None = None
        offset = int((extra_params or {}).get("offset", 0))
        for _ in range(effective_max_pages):
            remaining = effective_page_size if total_limit is None else max(0, total_limit - fetched)
            if remaining < 1:
                break
            page_limit = min(effective_page_size, remaining)
            if next_href is not None:
                page = self._json_href(next_href)
            else:
                params = _params(extra_params, {"limit": page_limit, "offset": offset})
                page = self.items(collection_id, extra_params=params)

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
    ) -> list[JsonObject]:
        return list(
            self.iter_items(
                collection_id,
                extra_params=extra_params,
                page_size=page_size,
                limit=limit,
                max_pages=max_pages,
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
    ) -> Iterator[JsonObject]:
        emitted = 0
        for page in self.item_pages(
            collection_id,
            extra_params=extra_params,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
        ):
            for item in _features_from_page(page):
                if limit is not None and emitted >= limit:
                    return
                yield item
                emitted += 1

    def item(self, collection_id: FeatureId, item_id: FeatureId) -> JsonObject:
        path = f"{self.root}/collections/{_encode_path_segment(str(collection_id))}/items/{_encode_path_segment(str(item_id))}"
        return self._json("GET", path)

    def search(self, *, params: Params = None, json_body: Mapping[str, Any] | None = None) -> JsonObject:
        if json_body is not None:
            return self._json("POST", f"{self.root}/search", json_body=json_body)
        return self._json("GET", f"{self.root}/search", params=params)

    def search_pages(
        self,
        *,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
    ) -> Iterator[JsonObject]:
        effective_page_size = _normalize_page_limit(page_size, limit)
        effective_max_pages = _normalize_max_pages(max_pages)
        total_limit = _normalize_total_limit(limit)
        if total_limit == 0:
            return

        fetched = 0
        next_href: str | None = None
        offset = int((params or json_body or {}).get("offset", 0))
        for _ in range(effective_max_pages):
            remaining = effective_page_size if total_limit is None else max(0, total_limit - fetched)
            if remaining < 1:
                break
            page_limit = min(effective_page_size, remaining)
            if next_href is not None:
                page = self._json_href(next_href)
            elif json_body is not None:
                page_body = {**json_body, "limit": page_limit, "offset": offset}
                page = self.search(json_body=page_body)
            else:
                page_params = _params(params, {"limit": page_limit, "offset": offset})
                page = self.search(params=page_params)

            yield page
            page_items = _features_from_page(page)
            fetched += len(page_items)
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
    ) -> list[JsonObject]:
        return list(
            self.iter_search_items(
                params=params,
                json_body=json_body,
                page_size=page_size,
                limit=limit,
                max_pages=max_pages,
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
    ) -> Iterator[JsonObject]:
        emitted = 0
        for page in self.search_pages(
            params=params,
            json_body=json_body,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
        ):
            for item in _features_from_page(page):
                if limit is not None and emitted >= limit:
                    return
                yield item
                emitted += 1


class WfsClient(_SyncProtocol):
    """WFS 2.0 wrapper."""

    path = "/wfs"

    def request(self, operation: str, *, params: Params = None) -> str:
        return self._text("GET", self.path, params=_params({"service": "WFS", "version": "2.0.0", "request": operation}, params))

    def capabilities(self) -> str:
        return self.request("GetCapabilities")

    def describe_feature_type(self, type_names: CsvValue | None = None) -> str:
        params = {"typeNames": _csv(type_names)} if type_names is not None else None
        return self.request("DescribeFeatureType", params=params)

    def get_feature(self, *, type_names: CsvValue | None = None, extra_params: Params = None) -> str:
        params = _params({"typeNames": _csv(type_names)} if type_names is not None else None, extra_params)
        return self.request("GetFeature", params=params)

    def transaction(self, xml: str | bytes) -> str:
        return self._text("POST", self.path, content=xml)


class WmsClient(_SyncProtocol):
    """WMS wrapper."""

    def __init__(self, client: Any, service_id: str) -> None:
        super().__init__(client)
        self.service_id = service_id
        self.path = f"/ogc/services/{_encode_path_segment(service_id)}/wms"

    def request(self, operation: str, *, params: Params = None) -> bytes:
        return self._bytes(self.path, params=_params({"service": "WMS", "version": "1.3.0", "request": operation}, params))

    def request_response(self, operation: str, *, params: Params = None) -> BinaryResponse:
        return self._binary_response(
            self.path,
            params=_params({"service": "WMS", "version": "1.3.0", "request": operation}, params),
        )

    def capabilities(self) -> str:
        return self.request("GetCapabilities").decode("utf-8")

    def map(self, *, layers: CsvValue, bbox: BboxValue, width: int, height: int, crs: str = "EPSG:4326", image_format: str = "image/png", extra_params: Params = None) -> bytes:
        return self.map_response(
            layers=layers,
            bbox=bbox,
            width=width,
            height=height,
            crs=crs,
            image_format=image_format,
            extra_params=extra_params,
        ).content

    def map_response(
        self,
        *,
        layers: CsvValue,
        bbox: BboxValue,
        width: int,
        height: int,
        crs: str = "EPSG:4326",
        image_format: OgcImageFormat = "image/png",
        extra_params: Params = None,
    ) -> BinaryResponse:
        params = _params({"layers": _csv(layers), "bbox": _bbox(bbox), "width": width, "height": height, "crs": crs, "format": image_format}, extra_params)
        return self.request_response("GetMap", params=params)

    def feature_info(self, *, layers: CsvValue, query_layers: CsvValue, i: int, j: int, bbox: BboxValue, width: int, height: int, extra_params: Params = None) -> bytes:
        return self.feature_info_response(
            layers=layers,
            query_layers=query_layers,
            i=i,
            j=j,
            bbox=bbox,
            width=width,
            height=height,
            extra_params=extra_params,
        ).content

    def feature_info_response(
        self,
        *,
        layers: CsvValue,
        query_layers: CsvValue,
        i: int,
        j: int,
        bbox: BboxValue,
        width: int,
        height: int,
        extra_params: Params = None,
    ) -> BinaryResponse:
        params = _params({"layers": _csv(layers), "query_layers": _csv(query_layers), "i": i, "j": j, "bbox": _bbox(bbox), "width": width, "height": height}, extra_params)
        return self.request_response("GetFeatureInfo", params=params)


class WmtsClient(_SyncProtocol):
    """WMTS wrapper."""

    def __init__(self, client: Any, service_id: str) -> None:
        super().__init__(client)
        self.service_id = service_id
        self.path = f"/ogc/services/{_encode_path_segment(service_id)}/wmts"

    def request(self, operation: str, *, params: Params = None) -> bytes:
        return self._bytes(self.path, params=_params({"service": "WMTS", "version": "1.0.0", "request": operation}, params))

    def request_response(self, operation: str, *, params: Params = None) -> BinaryResponse:
        return self._binary_response(
            self.path,
            params=_params({"service": "WMTS", "version": "1.0.0", "request": operation}, params),
        )

    def capabilities(self) -> str:
        return self.request("GetCapabilities").decode("utf-8")

    def tile(self, *, layer: str, tile_matrix_set: str, tile_matrix: str, tile_row: int, tile_col: int, image_format: str = "image/png", extra_params: Params = None) -> bytes:
        return self.tile_response(
            layer=layer,
            tile_matrix_set=tile_matrix_set,
            tile_matrix=tile_matrix,
            tile_row=tile_row,
            tile_col=tile_col,
            image_format=image_format,
            extra_params=extra_params,
        ).content

    def tile_response(
        self,
        *,
        layer: str,
        tile_matrix_set: str,
        tile_matrix: str,
        tile_row: int,
        tile_col: int,
        image_format: OgcImageFormat = "image/png",
        extra_params: Params = None,
    ) -> BinaryResponse:
        params = _params({"layer": layer, "tileMatrixSet": tile_matrix_set, "tileMatrix": tile_matrix, "tileRow": tile_row, "tileCol": tile_col, "format": image_format}, extra_params)
        return self.request_response("GetTile", params=params)


class ODataClient(_SyncProtocol):
    """OData v4 wrapper."""

    root = "/odata"

    def service_document(self) -> JsonObject:
        return self._json("GET", self.root)

    def metadata(self) -> str:
        return self._text("GET", f"{self.root}/$metadata")

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
        )

    def feature_pages(self, **kwargs: Any) -> Iterator[JsonObject]:
        yield from self.features_pages(**kwargs)

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
            )
        )

    def feature(self, layer_id: int, object_id: int) -> JsonObject:
        return self._json("GET", f"{self.root}/Features(LayerId={layer_id},ObjectId={object_id})")

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
    ) -> Iterator[JsonObject]:
        effective_page_size = _normalize_page_limit(page_size, limit)
        effective_max_pages = _normalize_max_pages(max_pages)
        total_limit = _normalize_total_limit(limit)
        if total_limit == 0:
            return

        fetched = 0
        next_href: str | None = None
        skip = int((extra_params or {}).get("$skip", 0))
        for _ in range(effective_max_pages):
            remaining = effective_page_size if total_limit is None else max(0, total_limit - fetched)
            if remaining < 1:
                break
            page_limit = min(effective_page_size, remaining)
            if next_href is not None:
                page = self._json_href(next_href)
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
                )
            yield page
            page_values = _values_from_page(page)
            fetched += len(page_values)
            next_href = _next_link(page)
            if next_href is None:
                if len(page_values) < page_limit:
                    break
                skip += len(page_values)


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

    async def query(self, layer_id: int, **kwargs: Any) -> JsonObject:
        return await self.client.query_features(self.service_id, layer_id, **kwargs)

    async def query_pages(
        self,
        layer_id: int,
        *,
        page_size: int = 1000,
        limit: int | None = None,
        max_pages: int = 100,
        **kwargs: Any,
    ) -> AsyncIterator[FeatureSet]:
        if page_size <= 0:
            raise ValueError("page_size must be greater than zero.")
        if max_pages <= 0:
            raise ValueError("max_pages must be greater than zero.")
        if limit is not None and limit <= 0:
            return

        total = 0
        extra_params = dict(kwargs.pop("extra_params", {}) or {})
        offset = int(extra_params.get("resultOffset", 0))
        for _ in range(max_pages):
            remaining = None if limit is None else limit - total
            if remaining is not None and remaining <= 0:
                break
            record_count = page_size if remaining is None else min(page_size, remaining)
            page_extra_params = {
                **extra_params,
                "resultOffset": offset,
                "resultRecordCount": record_count,
            }
            page = FeatureSet.from_dict(
                await self.query(layer_id, extra_params=page_extra_params, **kwargs)
            )
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
        **kwargs: Any,
    ) -> list[Feature]:
        features: list[Feature] = []
        async for page in self.query_pages(layer_id, page_size=page_size, limit=limit, max_pages=max_pages, **kwargs):
            remaining = None if limit is None else limit - len(features)
            page_features = list(page.features) if remaining is None else list(page.features)[:remaining]
            features.extend(page_features)
            if remaining is not None and len(features) >= limit:
                break
        return features

    async def query_items(
        self,
        layer_id: int,
        *,
        page_size: int = 1000,
        limit: int | None = None,
        max_pages: int = 100,
        **kwargs: Any,
    ) -> AsyncIterator[Feature]:
        emitted = 0
        async for page in self.query_pages(layer_id, page_size=page_size, limit=limit, max_pages=max_pages, **kwargs):
            for feature in page.features:
                if limit is not None and emitted >= limit:
                    return
                yield feature
                emitted += 1

    async def apply_edits(self, layer_id: int, **kwargs: Any) -> JsonObject:
        return await self.client.apply_edits(self.service_id, layer_id, **kwargs)

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

    async def export(self, bbox: BboxValue, **kwargs: Any) -> bytes:
        return await self.client.export_map(self.service_id, bbox, **kwargs)

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

    async def project(self, geometries: Any, *, in_sr: int | str, out_sr: int | str, **kwargs: Any) -> JsonObject:
        return await self.operation("project", params={"geometries": _query_value(geometries), "inSR": in_sr, "outSR": out_sr, **kwargs})

    async def buffer(self, geometries: Any, *, in_sr: int | str, distances: CsvValue, unit: str | None = None, **kwargs: Any) -> JsonObject:
        params = {"geometries": _query_value(geometries), "inSR": in_sr, "distances": _csv(distances), **kwargs}
        if unit is not None:
            params["unit"] = unit
        return await self.operation("buffer", params=params)

    async def simplify(self, geometries: Any, *, sr: int | str | None = None, **kwargs: Any) -> JsonObject:
        params = {"geometries": _query_value(geometries), **kwargs}
        if sr is not None:
            params["sr"] = sr
        return await self.operation("simplify", params=params)


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

    async def coverage(self, collection_id: FeatureId, *, response_format: str = "json", extra_params: Params = None) -> bytes:
        return await self._bytes(f"{_ogc_collection_path(self.root, collection_id)}/coverage", params=_params({"f": response_format}, extra_params))


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


class AsyncStacClient(_AsyncProtocol):
    """Async STAC API wrapper."""

    root = "/stac"

    async def catalog(self) -> JsonObject:
        return await self._json("GET", self.root)

    async def collections(self) -> JsonObject:
        return await self._json("GET", f"{self.root}/collections")

    async def collection(self, collection_id: FeatureId) -> JsonObject:
        return await self._json("GET", f"{self.root}/collections/{_encode_path_segment(str(collection_id))}")

    async def items(self, collection_id: FeatureId, *, extra_params: Params = None) -> JsonObject:
        return await self._json("GET", f"{self.root}/collections/{_encode_path_segment(str(collection_id))}/items", params=extra_params)

    async def item_pages(
        self,
        collection_id: FeatureId,
        *,
        extra_params: Params = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
    ) -> AsyncIterator[JsonObject]:
        effective_page_size = _normalize_page_limit(page_size, limit)
        effective_max_pages = _normalize_max_pages(max_pages)
        total_limit = _normalize_total_limit(limit)
        if total_limit == 0:
            return

        fetched = 0
        next_href: str | None = None
        offset = int((extra_params or {}).get("offset", 0))
        for _ in range(effective_max_pages):
            remaining = effective_page_size if total_limit is None else max(0, total_limit - fetched)
            if remaining < 1:
                break
            page_limit = min(effective_page_size, remaining)
            if next_href is not None:
                page = await self._json_href(next_href)
            else:
                params = _params(extra_params, {"limit": page_limit, "offset": offset})
                page = await self.items(collection_id, extra_params=params)

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
    ) -> list[JsonObject]:
        return [
            item
            async for item in self.iter_items(
                collection_id,
                extra_params=extra_params,
                page_size=page_size,
                limit=limit,
                max_pages=max_pages,
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
    ) -> AsyncIterator[JsonObject]:
        emitted = 0
        async for page in self.item_pages(
            collection_id,
            extra_params=extra_params,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
        ):
            for item in _features_from_page(page):
                if limit is not None and emitted >= limit:
                    return
                yield item
                emitted += 1

    async def item(self, collection_id: FeatureId, item_id: FeatureId) -> JsonObject:
        path = f"{self.root}/collections/{_encode_path_segment(str(collection_id))}/items/{_encode_path_segment(str(item_id))}"
        return await self._json("GET", path)

    async def search(self, *, params: Params = None, json_body: Mapping[str, Any] | None = None) -> JsonObject:
        if json_body is not None:
            return await self._json("POST", f"{self.root}/search", json_body=json_body)
        return await self._json("GET", f"{self.root}/search", params=params)

    async def search_pages(
        self,
        *,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
        page_size: int | None = None,
        limit: int | None = None,
        max_pages: int | None = None,
    ) -> AsyncIterator[JsonObject]:
        effective_page_size = _normalize_page_limit(page_size, limit)
        effective_max_pages = _normalize_max_pages(max_pages)
        total_limit = _normalize_total_limit(limit)
        if total_limit == 0:
            return

        fetched = 0
        next_href: str | None = None
        offset = int((params or json_body or {}).get("offset", 0))
        for _ in range(effective_max_pages):
            remaining = effective_page_size if total_limit is None else max(0, total_limit - fetched)
            if remaining < 1:
                break
            page_limit = min(effective_page_size, remaining)
            if next_href is not None:
                page = await self._json_href(next_href)
            elif json_body is not None:
                page_body = {**json_body, "limit": page_limit, "offset": offset}
                page = await self.search(json_body=page_body)
            else:
                page_params = _params(params, {"limit": page_limit, "offset": offset})
                page = await self.search(params=page_params)

            yield page
            page_items = _features_from_page(page)
            fetched += len(page_items)
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
    ) -> list[JsonObject]:
        return [
            item
            async for item in self.iter_search_items(
                params=params,
                json_body=json_body,
                page_size=page_size,
                limit=limit,
                max_pages=max_pages,
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
    ) -> AsyncIterator[JsonObject]:
        emitted = 0
        async for page in self.search_pages(
            params=params,
            json_body=json_body,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
        ):
            for item in _features_from_page(page):
                if limit is not None and emitted >= limit:
                    return
                yield item
                emitted += 1


class AsyncWfsClient(_AsyncProtocol):
    """Async WFS 2.0 wrapper."""

    path = "/wfs"

    async def request(self, operation: str, *, params: Params = None) -> str:
        return await self._text("GET", self.path, params=_params({"service": "WFS", "version": "2.0.0", "request": operation}, params))

    async def capabilities(self) -> str:
        return await self.request("GetCapabilities")

    async def describe_feature_type(self, type_names: CsvValue | None = None) -> str:
        params = {"typeNames": _csv(type_names)} if type_names is not None else None
        return await self.request("DescribeFeatureType", params=params)

    async def get_feature(self, *, type_names: CsvValue | None = None, extra_params: Params = None) -> str:
        params = _params({"typeNames": _csv(type_names)} if type_names is not None else None, extra_params)
        return await self.request("GetFeature", params=params)

    async def transaction(self, xml: str | bytes) -> str:
        return await self._text("POST", self.path, content=xml)


class AsyncWmsClient(_AsyncProtocol):
    """Async WMS wrapper."""

    def __init__(self, client: Any, service_id: str) -> None:
        super().__init__(client)
        self.service_id = service_id
        self.path = f"/ogc/services/{_encode_path_segment(service_id)}/wms"

    async def request(self, operation: str, *, params: Params = None) -> bytes:
        return await self._bytes(self.path, params=_params({"service": "WMS", "version": "1.3.0", "request": operation}, params))

    async def request_response(self, operation: str, *, params: Params = None) -> BinaryResponse:
        return await self._binary_response(
            self.path,
            params=_params({"service": "WMS", "version": "1.3.0", "request": operation}, params),
        )

    async def capabilities(self) -> str:
        return (await self.request("GetCapabilities")).decode("utf-8")

    async def map(self, *, layers: CsvValue, bbox: BboxValue, width: int, height: int, crs: str = "EPSG:4326", image_format: str = "image/png", extra_params: Params = None) -> bytes:
        return (
            await self.map_response(
                layers=layers,
                bbox=bbox,
                width=width,
                height=height,
                crs=crs,
                image_format=image_format,
                extra_params=extra_params,
            )
        ).content

    async def map_response(
        self,
        *,
        layers: CsvValue,
        bbox: BboxValue,
        width: int,
        height: int,
        crs: str = "EPSG:4326",
        image_format: OgcImageFormat = "image/png",
        extra_params: Params = None,
    ) -> BinaryResponse:
        params = _params({"layers": _csv(layers), "bbox": _bbox(bbox), "width": width, "height": height, "crs": crs, "format": image_format}, extra_params)
        return await self.request_response("GetMap", params=params)

    async def feature_info(self, *, layers: CsvValue, query_layers: CsvValue, i: int, j: int, bbox: BboxValue, width: int, height: int, extra_params: Params = None) -> bytes:
        return (
            await self.feature_info_response(
                layers=layers,
                query_layers=query_layers,
                i=i,
                j=j,
                bbox=bbox,
                width=width,
                height=height,
                extra_params=extra_params,
            )
        ).content

    async def feature_info_response(
        self,
        *,
        layers: CsvValue,
        query_layers: CsvValue,
        i: int,
        j: int,
        bbox: BboxValue,
        width: int,
        height: int,
        extra_params: Params = None,
    ) -> BinaryResponse:
        params = _params({"layers": _csv(layers), "query_layers": _csv(query_layers), "i": i, "j": j, "bbox": _bbox(bbox), "width": width, "height": height}, extra_params)
        return await self.request_response("GetFeatureInfo", params=params)


class AsyncWmtsClient(_AsyncProtocol):
    """Async WMTS wrapper."""

    def __init__(self, client: Any, service_id: str) -> None:
        super().__init__(client)
        self.service_id = service_id
        self.path = f"/ogc/services/{_encode_path_segment(service_id)}/wmts"

    async def request(self, operation: str, *, params: Params = None) -> bytes:
        return await self._bytes(self.path, params=_params({"service": "WMTS", "version": "1.0.0", "request": operation}, params))

    async def request_response(self, operation: str, *, params: Params = None) -> BinaryResponse:
        return await self._binary_response(
            self.path,
            params=_params({"service": "WMTS", "version": "1.0.0", "request": operation}, params),
        )

    async def capabilities(self) -> str:
        return (await self.request("GetCapabilities")).decode("utf-8")

    async def tile(self, *, layer: str, tile_matrix_set: str, tile_matrix: str, tile_row: int, tile_col: int, image_format: str = "image/png", extra_params: Params = None) -> bytes:
        return (
            await self.tile_response(
                layer=layer,
                tile_matrix_set=tile_matrix_set,
                tile_matrix=tile_matrix,
                tile_row=tile_row,
                tile_col=tile_col,
                image_format=image_format,
                extra_params=extra_params,
            )
        ).content

    async def tile_response(
        self,
        *,
        layer: str,
        tile_matrix_set: str,
        tile_matrix: str,
        tile_row: int,
        tile_col: int,
        image_format: OgcImageFormat = "image/png",
        extra_params: Params = None,
    ) -> BinaryResponse:
        params = _params({"layer": layer, "tileMatrixSet": tile_matrix_set, "tileMatrix": tile_matrix, "tileRow": tile_row, "tileCol": tile_col, "format": image_format}, extra_params)
        return await self.request_response("GetTile", params=params)


class AsyncODataClient(_AsyncProtocol):
    """Async OData v4 wrapper."""

    root = "/odata"

    async def service_document(self) -> JsonObject:
        return await self._json("GET", self.root)

    async def metadata(self) -> str:
        return await self._text("GET", f"{self.root}/$metadata")

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
        ):
            yield page

    async def feature_pages(self, **kwargs: Any) -> AsyncIterator[JsonObject]:
        async for page in self.features_pages(**kwargs):
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
            )
        ]

    async def feature(self, layer_id: int, object_id: int) -> JsonObject:
        return await self._json("GET", f"{self.root}/Features(LayerId={layer_id},ObjectId={object_id})")

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
    ) -> AsyncIterator[JsonObject]:
        effective_page_size = _normalize_page_limit(page_size, limit)
        effective_max_pages = _normalize_max_pages(max_pages)
        total_limit = _normalize_total_limit(limit)
        if total_limit == 0:
            return

        fetched = 0
        next_href: str | None = None
        skip = int((extra_params or {}).get("$skip", 0))
        for _ in range(effective_max_pages):
            remaining = effective_page_size if total_limit is None else max(0, total_limit - fetched)
            if remaining < 1:
                break
            page_limit = min(effective_page_size, remaining)
            if next_href is not None:
                page = await self._json_href(next_href)
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
                )
            yield page
            page_values = _values_from_page(page)
            fetched += len(page_values)
            next_href = _next_link(page)
            if next_href is None:
                if len(page_values) < page_limit:
                    break
                skip += len(page_values)
