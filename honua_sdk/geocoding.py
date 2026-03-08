"""Synchronous HTTP client for Honua GeocodeServer APIs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from .errors import HonuaHttpError


def _normalize_base_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/"


def _encode_path_segment(value: str) -> str:
    return quote(value, safe="")


def _build_sensitive_auth_headers(
    *,
    api_key: str | None,
    bearer_token: str | None,
) -> dict[str, str]:
    headers: dict[str, str] = {}
    if api_key:
        headers["X-API-Key"] = api_key
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    return headers


def _apply_sensitive_auth_headers(
    request: httpx.Request,
    *,
    trusted_host: str | None,
    auth_headers: Mapping[str, str],
) -> None:
    if not auth_headers or trusted_host is None:
        return

    if request.url.host == trusted_host:
        for name, value in auth_headers.items():
            request.headers.setdefault(name, value)
        return

    for name in auth_headers:
        request.headers.pop(name, None)


@dataclass
class GeocodeResult:
    address: str
    latitude: float
    longitude: float
    score: float
    attributes: dict[str, str | None]


@dataclass
class ReverseGeocodeResult:
    address: str
    latitude: float
    longitude: float
    attributes: dict[str, str | None]


@dataclass
class GeocodeSuggestion:
    text: str
    magic_key: str
    is_collection: bool


class HonuaGeocodingClient:
    """Task-oriented client for Honua GeocodeServer workflows."""

    def __init__(
        self,
        base_url: str,
        *,
        locator_name: str = "World",
        timeout: float = 30.0,
        api_key: str | None = None,
        bearer_token: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._locator_name = locator_name
        self._owns_client = client is None
        if client is not None:
            self._client = client
            return

        normalized_base_url = _normalize_base_url(base_url)
        trusted_host = httpx.URL(normalized_base_url).host
        auth_headers = _build_sensitive_auth_headers(api_key=api_key, bearer_token=bearer_token)

        def _request_hook(request: httpx.Request) -> None:
            _apply_sensitive_auth_headers(
                request,
                trusted_host=trusted_host,
                auth_headers=auth_headers,
            )

        self._client = httpx.Client(
            base_url=normalized_base_url,
            timeout=timeout,
            event_hooks={"request": [_request_hook]},
        )

    def __enter__(self) -> "HonuaGeocodingClient":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def close(self) -> None:
        """Release underlying resources if this instance owns the HTTP client."""
        if self._owns_client:
            self._client.close()

    def forward_geocode(
        self,
        address: str,
        *,
        max_results: int = 10,
        country_codes: str | None = None,
        spatial_reference_wkid: int = 4326,
    ) -> list[GeocodeResult]:
        """Find address candidates for a single-line address string."""
        locator_segment = _encode_path_segment(self._locator_name)
        params: dict[str, Any] = {
            "f": "json",
            "singleLine": address,
            "maxLocations": max_results,
            "outSR": spatial_reference_wkid,
        }
        if country_codes is not None:
            params["countryCode"] = country_codes

        data = self._request_json(
            "GET",
            f"/rest/services/{locator_segment}/GeocodeServer/findAddressCandidates",
            params=params,
        )

        results: list[GeocodeResult] = []
        for candidate in data.get("candidates", []):
            location = candidate.get("location", {})
            results.append(
                GeocodeResult(
                    address=candidate.get("address", ""),
                    longitude=float(location.get("x", 0)),
                    latitude=float(location.get("y", 0)),
                    score=float(candidate.get("score", 0)),
                    attributes=candidate.get("attributes", {}),
                )
            )
        return results

    def reverse_geocode(
        self,
        latitude: float,
        longitude: float,
        *,
        spatial_reference_wkid: int = 4326,
    ) -> ReverseGeocodeResult | None:
        """Reverse-geocode a coordinate pair into an address."""
        locator_segment = _encode_path_segment(self._locator_name)
        params: dict[str, Any] = {
            "f": "json",
            "location": f"{longitude},{latitude}",
            "outSR": spatial_reference_wkid,
        }

        data = self._request_json(
            "GET",
            f"/rest/services/{locator_segment}/GeocodeServer/reverseGeocode",
            params=params,
        )

        if not data.get("address") and not data.get("location"):
            return None

        addr_info = data.get("address", {})
        location = data.get("location", {})
        match_addr = addr_info.get("Match_addr", "") if isinstance(addr_info, Mapping) else ""
        attributes = dict(addr_info) if isinstance(addr_info, Mapping) else {}

        return ReverseGeocodeResult(
            address=match_addr,
            longitude=float(location.get("x", 0)),
            latitude=float(location.get("y", 0)),
            attributes=attributes,
        )

    def suggest(
        self,
        text: str,
        *,
        max_suggestions: int = 5,
        country_codes: str | None = None,
    ) -> list[GeocodeSuggestion]:
        """Get typeahead suggestions for partial address text."""
        locator_segment = _encode_path_segment(self._locator_name)
        params: dict[str, Any] = {
            "f": "json",
            "text": text,
            "maxSuggestions": max_suggestions,
        }
        if country_codes is not None:
            params["countryCode"] = country_codes

        data = self._request_json(
            "GET",
            f"/rest/services/{locator_segment}/GeocodeServer/suggest",
            params=params,
        )

        results: list[GeocodeSuggestion] = []
        for suggestion in data.get("suggestions", []):
            results.append(
                GeocodeSuggestion(
                    text=suggestion.get("text", ""),
                    magic_key=suggestion.get("magicKey", ""),
                    is_collection=suggestion.get("isCollection", False),
                )
            )
        return results

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = self._request(method, path, params=params, json_body=json_body)
        if not response.content:
            return {}

        try:
            payload = response.json()
        except ValueError:
            return {"raw": response.text}

        if isinstance(payload, Mapping):
            return dict(payload)
        return {"data": payload}

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        try:
            response = self._client.request(
                method=method,
                url=path,
                params=params,
                json=json_body,
            )
        except httpx.HTTPError as exc:
            raise self._to_transport_error(exc) from exc
        if response.status_code >= 400:
            raise self._to_http_error(response)
        return response

    @staticmethod
    def _to_http_error(response: httpx.Response) -> HonuaHttpError:
        body: Any | None = None
        message = response.reason_phrase or "Request failed"

        if response.content:
            try:
                body = response.json()
            except ValueError:
                body = response.text
        if isinstance(body, Mapping):
            error = body.get("error")
            if isinstance(error, Mapping):
                candidate = error.get("message")
                if isinstance(candidate, str) and candidate:
                    message = candidate
            else:
                candidate = body.get("detail") or body.get("message")
                if isinstance(candidate, str) and candidate:
                    message = candidate

        return HonuaHttpError(response.status_code, message, body=body)

    @staticmethod
    def _to_transport_error(error: httpx.HTTPError) -> HonuaHttpError:
        message = str(error) or error.__class__.__name__
        body: dict[str, Any] = {"type": error.__class__.__name__, "message": message}
        request = getattr(error, "request", None)
        if request is not None:
            body["url"] = str(request.url)
        return HonuaHttpError(0, f"Transport error: {message}", body=body)
