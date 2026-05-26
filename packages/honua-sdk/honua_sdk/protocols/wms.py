"""OGC Web Map Service (WMS) protocol clients."""

# ruff: noqa: E501, PLR0913

from __future__ import annotations

from typing import Any

from honua_sdk._http import _encode_path_segment

from ._base import (
    BboxValue,
    BinaryResponse,
    CsvValue,
    OgcImageFormat,
    Params,
    _AsyncProtocol,
    _bbox,
    _csv,
    _params,
    _SyncProtocol,
)


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
