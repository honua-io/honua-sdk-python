"""OGC Web Map Tile Service (WMTS) protocol clients."""

# ruff: noqa: E501, PLR0913

from __future__ import annotations

from typing import Any

from honua_sdk._http import _encode_path_segment

from ._base import (
    BinaryResponse,
    OgcImageFormat,
    Params,
    _AsyncProtocol,
    _params,
    _SyncProtocol,
)


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

    def tile(self, *, layer: str, tile_matrix_set: str, tile_matrix: str, tile_row: int, tile_col: int, style: str = "default", image_format: str = "image/png", extra_params: Params = None) -> bytes:
        return self.tile_response(
            layer=layer,
            tile_matrix_set=tile_matrix_set,
            tile_matrix=tile_matrix,
            tile_row=tile_row,
            tile_col=tile_col,
            style=style,
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
        style: str = "default",
        image_format: OgcImageFormat = "image/png",
        extra_params: Params = None,
    ) -> BinaryResponse:
        # STYLE is a mandatory GetTile KVP parameter in WMTS 1.0.0; ``"default"``
        # selects the layer's advertised default style.
        params = _params({"layer": layer, "style": style, "tileMatrixSet": tile_matrix_set, "tileMatrix": tile_matrix, "tileRow": tile_row, "tileCol": tile_col, "format": image_format}, extra_params)
        return self.request_response("GetTile", params=params)


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

    async def tile(self, *, layer: str, tile_matrix_set: str, tile_matrix: str, tile_row: int, tile_col: int, style: str = "default", image_format: str = "image/png", extra_params: Params = None) -> bytes:
        return (
            await self.tile_response(
                layer=layer,
                tile_matrix_set=tile_matrix_set,
                tile_matrix=tile_matrix,
                tile_row=tile_row,
                tile_col=tile_col,
                style=style,
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
        style: str = "default",
        image_format: OgcImageFormat = "image/png",
        extra_params: Params = None,
    ) -> BinaryResponse:
        # STYLE is a mandatory GetTile KVP parameter in WMTS 1.0.0; ``"default"``
        # selects the layer's advertised default style.
        params = _params({"layer": layer, "style": style, "tileMatrixSet": tile_matrix_set, "tileMatrix": tile_matrix, "tileRow": tile_row, "tileCol": tile_col, "format": image_format}, extra_params)
        return await self.request_response("GetTile", params=params)
