"""Protocol-specific clients for Honua Server surfaces."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

import httpx

from ._http import _encode_path_segment, _to_http_error, _to_transport_error

JsonObject = dict[str, Any]
Params = Mapping[str, Any] | None
FeatureId = str | int
BboxValue = str | Sequence[int | float]
CsvValue = str | Sequence[str | int | float]


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


def _service_path(service_id: str, service_type: str) -> str:
    return f"/rest/services/{_encode_path_segment(service_id)}/{service_type}"


def _ogc_collection_path(root: str, collection_id: FeatureId) -> str:
    return f"{root}/collections/{_encode_path_segment(str(collection_id))}"


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

    def _bytes(self, path: str, *, params: Params = None) -> bytes:
        return self.client._request("GET", path, params=params).content

    def _text(self, method: str, path: str, *, params: Params = None, content: bytes | str | None = None) -> str:
        body = content.encode("utf-8") if isinstance(content, str) else content
        try:
            response = self.client._client.request(method=method, url=path, params=params, content=body)
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

    def item(self, collection_id: FeatureId, item_id: FeatureId) -> JsonObject:
        path = f"{self.root}/collections/{_encode_path_segment(str(collection_id))}/items/{_encode_path_segment(str(item_id))}"
        return self._json("GET", path)

    def search(self, *, params: Params = None, json_body: Mapping[str, Any] | None = None) -> JsonObject:
        if json_body is not None:
            return self._json("POST", f"{self.root}/search", json_body=json_body)
        return self._json("GET", f"{self.root}/search", params=params)


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

    def capabilities(self) -> str:
        return self.request("GetCapabilities").decode("utf-8")

    def map(self, *, layers: CsvValue, bbox: BboxValue, width: int, height: int, crs: str = "EPSG:4326", image_format: str = "image/png", extra_params: Params = None) -> bytes:
        params = _params({"layers": _csv(layers), "bbox": _bbox(bbox), "width": width, "height": height, "crs": crs, "format": image_format}, extra_params)
        return self.request("GetMap", params=params)

    def feature_info(self, *, layers: CsvValue, query_layers: CsvValue, i: int, j: int, bbox: BboxValue, width: int, height: int, extra_params: Params = None) -> bytes:
        params = _params({"layers": _csv(layers), "query_layers": _csv(query_layers), "i": i, "j": j, "bbox": _bbox(bbox), "width": width, "height": height}, extra_params)
        return self.request("GetFeatureInfo", params=params)


class WmtsClient(_SyncProtocol):
    """WMTS wrapper."""

    def __init__(self, client: Any, service_id: str) -> None:
        super().__init__(client)
        self.service_id = service_id
        self.path = f"/ogc/services/{_encode_path_segment(service_id)}/wmts"

    def request(self, operation: str, *, params: Params = None) -> bytes:
        return self._bytes(self.path, params=_params({"service": "WMTS", "version": "1.0.0", "request": operation}, params))

    def capabilities(self) -> str:
        return self.request("GetCapabilities").decode("utf-8")

    def tile(self, *, layer: str, tile_matrix_set: str, tile_matrix: str, tile_row: int, tile_col: int, image_format: str = "image/png", extra_params: Params = None) -> bytes:
        params = _params({"layer": layer, "tileMatrixSet": tile_matrix_set, "tileMatrix": tile_matrix, "tileRow": tile_row, "tileCol": tile_col, "format": image_format}, extra_params)
        return self.request("GetTile", params=params)


class ODataClient(_SyncProtocol):
    """OData v4 wrapper."""

    root = "/odata"

    def service_document(self) -> JsonObject:
        return self._json("GET", self.root)

    def metadata(self) -> str:
        return self._text("GET", f"{self.root}/$metadata")

    def layers(self, *, extra_params: Params = None) -> JsonObject:
        return self._json("GET", f"{self.root}/Layers", params=extra_params)

    def layer(self, layer_id: int, *, extra_params: Params = None) -> JsonObject:
        return self._json("GET", f"{self.root}/Layers({layer_id})", params=extra_params)

    def features(self, *, layer_id: int | None = None, extra_params: Params = None) -> JsonObject:
        path = f"{self.root}/Features" if layer_id is None else f"{self.root}/Layers({layer_id})/Features"
        return self._json("GET", path, params=extra_params)

    def feature(self, layer_id: int, object_id: int) -> JsonObject:
        return self._json("GET", f"{self.root}/Features(LayerId={layer_id},ObjectId={object_id})")
