"""Synchronous HTTP client for Honua GeocodeServer APIs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from ._retry import RetryTransport
from ._http import (
    _apply_sensitive_auth_headers,
    _build_sensitive_auth_headers,
    _encode_path_segment,
    _extract_trusted_authority,
    _normalize_base_url,
    _to_http_error,
    _to_transport_error,
    _validate_auth_configuration,
    _validate_external_client_auth_configuration,
)
from .auth import AuthProvider


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
        auth_provider: AuthProvider | None = None,
        client: httpx.Client | None = None,
        transport: httpx.BaseTransport | None = None,
        max_retries: int = 3,
    ) -> None:
        if client is not None and transport is not None:
            raise ValueError("Provide either `client` or `transport`, not both.")
        _validate_auth_configuration(bearer_token=bearer_token, auth_provider=auth_provider)
        _validate_external_client_auth_configuration(
            client=client,
            api_key=api_key,
            bearer_token=bearer_token,
            auth_provider=auth_provider,
        )

        self._locator_name = locator_name
        self._owns_client = client is None
        if client is not None:
            self._client = client
            return

        normalized_base_url = _normalize_base_url(base_url)
        trusted_authority = _extract_trusted_authority(httpx.URL(normalized_base_url))
        auth_headers = _build_sensitive_auth_headers(api_key=api_key, bearer_token=bearer_token)

        def _request_hook(request: httpx.Request) -> None:
            _apply_sensitive_auth_headers(
                request,
                trusted_authority=trusted_authority,
                auth_headers=auth_headers,
                auth_provider=auth_provider,
            )

        effective_transport = transport
        if max_retries > 0:
            inner = effective_transport or httpx.HTTPTransport()
            effective_transport = RetryTransport(inner, max_retries=max_retries)

        self._client = httpx.Client(
            base_url=normalized_base_url,
            timeout=timeout,
            transport=effective_transport,
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
            raise _to_transport_error(exc) from exc
        if response.status_code >= 400:
            raise _to_http_error(response)
        return response
