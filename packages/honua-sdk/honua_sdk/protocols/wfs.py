"""OGC Web Feature Service (WFS) protocol clients."""

# ruff: noqa: E501

from __future__ import annotations

from ._base import (
    CsvValue,
    Params,
    _AsyncProtocol,
    _csv,
    _params,
    _SyncProtocol,
)


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

    def transaction(self, xml: str | bytes, *, content_type: str = "application/xml") -> str:
        # WFS-T request bodies are XML; declare the content type explicitly so a
        # conformant WFS endpoint (or a strict proxy/WAF) does not 415/400 the
        # transaction or mis-route it as form data. Override with text/xml if needed.
        return self._text("POST", self.path, content=xml, extra_headers={"Content-Type": content_type})


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

    async def transaction(self, xml: str | bytes, *, content_type: str = "application/xml") -> str:
        # See WfsClient.transaction: declare the XML content type explicitly.
        return await self._text("POST", self.path, content=xml, extra_headers={"Content-Type": content_type})
