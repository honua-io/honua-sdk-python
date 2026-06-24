"""Synchronous HTTP client for Honua GeocodeServer APIs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import httpx

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
from ._retry import RetryTransport
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


def _extract_location_xy(location: Any) -> tuple[float, float] | None:
    """Return ``(longitude, latitude)`` from a GeocodeServer ``location``.

    Returns ``None`` when the location is missing, not a mapping, or lacks a
    usable ``x``/``y`` pair. Defaulting absent coordinates to ``0`` would
    silently emit a valid-looking ``(0, 0)`` "null island" result that masks
    a geocode miss — so a missing location is treated as "no result" instead.
    """
    if not isinstance(location, Mapping):
        return None
    raw_x = location.get("x")
    raw_y = location.get("y")
    if raw_x is None or raw_y is None:
        return None
    try:
        return float(raw_x), float(raw_y)
    except (TypeError, ValueError):
        return None


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

    def __enter__(self) -> HonuaGeocodingClient:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    def close(self) -> None:
        """Release underlying HTTP resources if this instance owns the client.

        When constructed with an externally supplied :class:`httpx.Client`,
        ownership stays with the caller and this method is a no-op.
        """
        if self._owns_client:
            self._client.close()

    def forward_geocode(
        self,
        address: str,
        *,
        max_results: int = 10,
        country_codes: str | None = None,
        spatial_reference_wkid: int = 4326,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[GeocodeResult]:
        """Find address candidates for a single-line address string.

        Args:
            address: Free-form single-line address.
            max_results: Maximum number of candidates the server may
                return (forwarded as ``maxLocations``).
            country_codes: Optional ISO country-code filter (forwarded as
                ``countryCode``).
            spatial_reference_wkid: WKID for returned coordinates
                (forwarded as ``outSR``); defaults to ``4326`` (WGS84).

        Returns:
            A list of :class:`GeocodeResult` candidates, ordered by the
            server-reported match score.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`_request`.

        Raises:
            HonuaHttpError: The server returned a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
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
            timeout=timeout,
            extra_headers=extra_headers,
        )

        results: list[GeocodeResult] = []
        for candidate in data.get("candidates", []):
            coords = _extract_location_xy(candidate.get("location"))
            if coords is None:
                # No usable location: skip rather than emit a (0, 0) result.
                continue
            longitude, latitude = coords
            results.append(
                GeocodeResult(
                    address=candidate.get("address", ""),
                    longitude=longitude,
                    latitude=latitude,
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
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> ReverseGeocodeResult | None:
        """Reverse-geocode a coordinate pair into a postal address.

        Args:
            latitude: Latitude of the input coordinate.
            longitude: Longitude of the input coordinate.
            spatial_reference_wkid: WKID for both the input coordinate
                interpretation and the response location; defaults to
                ``4326`` (WGS84).

        Returns:
            A :class:`ReverseGeocodeResult` when the server returned
            either an address or a location; ``None`` when neither field
            was present in the response.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`_request`.

        Raises:
            HonuaHttpError: The server returned a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
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
            timeout=timeout,
            extra_headers=extra_headers,
        )

        addr_info = data.get("address", {})
        match_addr = addr_info.get("Match_addr", "") if isinstance(addr_info, Mapping) else ""
        attributes = dict(addr_info) if isinstance(addr_info, Mapping) else {}
        coords = _extract_location_xy(data.get("location"))

        # No usable location and no address text means the server returned no
        # match — surface that as ``None`` rather than a (0, 0) "null island".
        if coords is None and not match_addr:
            return None

        longitude, latitude = coords if coords is not None else (0.0, 0.0)
        return ReverseGeocodeResult(
            address=match_addr,
            longitude=longitude,
            latitude=latitude,
            attributes=attributes,
        )

    def suggest(
        self,
        text: str,
        *,
        max_suggestions: int = 5,
        country_codes: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[GeocodeSuggestion]:
        """Fetch typeahead suggestions for partial address text.

        Args:
            text: Partial address text the user has typed so far.
            max_suggestions: Maximum number of suggestions to return
                (forwarded as ``maxSuggestions``).
            country_codes: Optional ISO country-code filter (forwarded as
                ``countryCode``).

        Returns:
            A list of :class:`GeocodeSuggestion` objects. Pair the
            ``magic_key`` field with a follow-up
            :meth:`forward_geocode` call to resolve a chosen suggestion.

        Per-request options (``timeout`` / ``extra_headers``) are forwarded
        to :meth:`_request`.

        Raises:
            HonuaHttpError: The server returned a non-success status.
            HonuaTransportError: The request failed at the transport layer.
        """
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
            timeout=timeout,
            extra_headers=extra_headers,
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
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        response = self._request(
            method,
            path,
            params=params,
            json_body=json_body,
            timeout=timeout,
            extra_headers=extra_headers,
            idempotency_key=idempotency_key,
        )
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
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        idempotency_key: str | None = None,
    ) -> httpx.Response:
        headers: dict[str, str] | None = None
        if extra_headers is not None or idempotency_key is not None:
            headers = {}
            if extra_headers:
                headers.update(extra_headers)
            if idempotency_key is not None:
                headers["Idempotency-Key"] = idempotency_key
        request_kwargs: dict[str, Any] = {
            "method": method,
            "url": path,
            "params": params,
            "json": json_body,
            "headers": headers,
        }
        if timeout is not None:
            request_kwargs["timeout"] = (
                timeout if isinstance(timeout, httpx.Timeout) else httpx.Timeout(timeout)
            )
        try:
            response = self._client.request(**request_kwargs)
        except httpx.HTTPError as exc:
            raise _to_transport_error(exc) from exc
        if response.status_code >= 400:
            raise _to_http_error(response)
        return response
