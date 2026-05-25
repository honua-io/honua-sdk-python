"""Pure request builders and response parsers for the data-plane clients.

The sync and async :class:`HonuaClient` / :class:`AsyncHonuaClient`
implementations historically duplicated every URL/payload/parse step
across mirrored ``def`` and ``async def`` methods. Those steps don't
involve any I/O, so they're factored out here as pure functions that
both clients call. The remaining sync/async wrappers boil down to::

    prep = build_xxx(...)
    response = self._request(prep.method, prep.path, ...)
    return parse_xxx(response.json())

Anything that **does** touch I/O — opening a connection, awaiting a
response, walking a paginated cursor — stays in the client modules,
where the sync/async split is unavoidable.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ._http import _encode_path_segment
from .models import (
    ApplyEditsResult,
    DataPlaneCapabilities,
    FeatureSet,
    ServiceSummary,
)


def _bool_text(value: bool) -> str:
    return "true" if value else "false"


@dataclass(frozen=True)
class PreparedRequest:
    """A bundle of (method, path, params, json, headers) ready for dispatch.

    Returned from every ``build_*`` helper. The sync and async clients
    each call ``self._request(prep.method, prep.path, params=...,
    json_body=..., headers=...)`` with these fields.
    """

    method: str
    path: str
    params: Mapping[str, Any] | None = None
    json: Mapping[str, Any] | None = None
    headers: Mapping[str, str] | None = None


# ---------------------------------------------------------------------------
# Readiness / capabilities / catalog
# ---------------------------------------------------------------------------


def build_readiness_request() -> PreparedRequest:
    return PreparedRequest(method="GET", path="/healthz/ready")


def build_capabilities_request() -> PreparedRequest:
    return PreparedRequest(method="GET", path="/api/v1/capabilities")


def parse_capabilities(payload: Mapping[str, Any]) -> DataPlaneCapabilities:
    return DataPlaneCapabilities.from_dict(payload)


def build_list_services_request(*, response_format: str = "json") -> PreparedRequest:
    return PreparedRequest(
        method="GET",
        path="/rest/services",
        params={"f": response_format},
    )


def parse_service_summaries(payload: Mapping[str, Any]) -> list[ServiceSummary]:
    """Pull the ``services`` array off the raw catalog payload."""
    services = payload.get("services")
    if not isinstance(services, list):
        return []
    return [
        ServiceSummary.from_dict(service)
        for service in services
        if isinstance(service, Mapping)
    ]


# ---------------------------------------------------------------------------
# FeatureServer query
# ---------------------------------------------------------------------------


def build_query_features_request(  # noqa: PLR0913 - mirrors the public client signature
    service_id: str,
    layer_id: int,
    *,
    where: str = "1=1",
    out_fields: str | Sequence[str] = "*",
    return_geometry: bool = True,
    extra_params: Mapping[str, Any] | None = None,
) -> PreparedRequest:
    """Build a FeatureServer ``query`` GET request."""
    service_segment = _encode_path_segment(service_id)
    if isinstance(out_fields, Sequence) and not isinstance(out_fields, str):
        out_fields_value = ",".join(str(value) for value in out_fields)
    else:
        out_fields_value = str(out_fields)

    params: dict[str, Any] = {
        "f": "json",
        "where": where,
        "outFields": out_fields_value,
        "returnGeometry": _bool_text(return_geometry),
    }
    if extra_params:
        params.update(extra_params)

    return PreparedRequest(
        method="GET",
        path=f"/rest/services/{service_segment}/FeatureServer/{layer_id}/query",
        params=params,
    )


def parse_feature_set(payload: Mapping[str, Any]) -> FeatureSet:
    return FeatureSet.from_dict(payload)


# ---------------------------------------------------------------------------
# FeatureServer applyEdits
# ---------------------------------------------------------------------------


def build_apply_edits_request(  # noqa: PLR0913 - mirrors the public client signature
    service_id: str,
    layer_id: int,
    *,
    adds: Sequence[Mapping[str, Any]] | None = None,
    updates: Sequence[Mapping[str, Any]] | None = None,
    deletes: Sequence[int] | str | None = None,
    rollback_on_failure: bool = True,
    headers: Mapping[str, str] | None = None,
) -> PreparedRequest:
    """Build a FeatureServer ``applyEdits`` POST request.

    Header construction (specifically the ``Idempotency-Key`` policy) is
    intentionally left to the calling client because it depends on
    runtime state (``self._retry_methods``); callers pass the already-
    built header dict in via ``headers``.
    """
    service_segment = _encode_path_segment(service_id)
    payload: dict[str, Any] = {
        "f": "json",
        "rollbackOnFailure": rollback_on_failure,
    }
    if adds is not None:
        payload["adds"] = list(adds)
    if updates is not None:
        payload["updates"] = list(updates)
    if deletes is not None:
        if isinstance(deletes, str):
            payload["deletes"] = deletes
        else:
            payload["deletes"] = list(deletes)

    return PreparedRequest(
        method="POST",
        path=f"/rest/services/{service_segment}/FeatureServer/{layer_id}/applyEdits",
        json=payload,
        headers=headers,
    )


def parse_apply_edits_result(payload: Mapping[str, Any]) -> ApplyEditsResult:
    return ApplyEditsResult.from_dict(payload)


# ---------------------------------------------------------------------------
# MapServer export
# ---------------------------------------------------------------------------


def build_export_map_request(  # noqa: PLR0913 - mirrors the public client signature
    service_id: str,
    bbox: Sequence[float] | str,
    *,
    size: tuple[int, int] = (400, 400),
    image_format: str = "png",
    transparent: bool = True,
    dpi: int = 96,
    extra_params: Mapping[str, Any] | None = None,
) -> PreparedRequest:
    service_segment = _encode_path_segment(service_id)
    bbox_value = (
        bbox if isinstance(bbox, str) else ",".join(str(value) for value in bbox)
    )

    params: dict[str, Any] = {
        "f": "image",
        "bbox": bbox_value,
        "size": f"{size[0]},{size[1]}",
        "format": image_format,
        "transparent": _bool_text(transparent),
        "dpi": str(dpi),
    }
    if extra_params:
        params.update(extra_params)

    return PreparedRequest(
        method="GET",
        path=f"/rest/services/{service_segment}/MapServer/export",
        params=params,
    )


# ---------------------------------------------------------------------------
# Paged query_features_all (pure paging logic; I/O remains on the client)
# ---------------------------------------------------------------------------


def validate_paging(page_size: int, max_pages: int) -> None:
    """Argument validation shared by sync/async ``query_features_all``."""
    if page_size <= 0:
        raise ValueError("page_size must be greater than zero.")
    if max_pages <= 0:
        raise ValueError("max_pages must be greater than zero.")


def initial_offset(extra_params: Mapping[str, Any] | None) -> int:
    """Honour any ``resultOffset`` value already in ``extra_params``."""
    return int((extra_params or {}).get("resultOffset", 0))


def page_extra_params(
    base_extra_params: Mapping[str, Any],
    *,
    offset: int,
    record_count: int,
) -> dict[str, Any]:
    """Merge the per-page offset/limit on top of ``base_extra_params``."""
    return {
        **dict(base_extra_params),
        "resultOffset": offset,
        "resultRecordCount": record_count,
    }


def page_record_count(page_size: int, remaining: int | None) -> int:
    """Return the per-page record count clamped by any remaining budget."""
    if remaining is None:
        return page_size
    return min(page_size, remaining)


def build_idempotency_headers(
    idempotency_key: str | None,
    *,
    retry_methods: frozenset[str],
) -> dict[str, str] | None:
    """Build the ``Idempotency-Key`` header dict, auto-generating if needed.

    When ``idempotency_key`` is ``None`` and ``retry_methods`` opts
    ``POST`` in, a fresh ``uuid4().hex`` is used. Returns ``None`` when
    no header should be sent.
    """
    if idempotency_key is not None:
        return {"Idempotency-Key": idempotency_key}
    if "POST" in retry_methods:
        return {"Idempotency-Key": uuid.uuid4().hex}
    return None


def parse_json_response_body(response: "Any") -> dict[str, Any]:
    """Parse an :class:`httpx.Response` into the SDK's ``dict`` convention.

    Returns ``{}`` for an empty body, ``{"raw": <text>}`` for a body that
    isn't JSON, the parsed mapping when JSON is an object, and
    ``{"data": <value>}`` for any other JSON type. Used identically by
    the sync and async ``_request_json`` helpers.
    """
    if not response.content:
        return {}
    try:
        payload = response.json()
    except ValueError:
        return {"raw": response.text}
    if isinstance(payload, Mapping):
        return dict(payload)
    return {"data": payload}


__all__ = [
    "PreparedRequest",
    "build_apply_edits_request",
    "build_capabilities_request",
    "build_export_map_request",
    "build_idempotency_headers",
    "build_list_services_request",
    "build_query_features_request",
    "build_readiness_request",
    "initial_offset",
    "page_extra_params",
    "page_record_count",
    "parse_apply_edits_result",
    "parse_capabilities",
    "parse_feature_set",
    "parse_json_response_body",
    "parse_service_summaries",
    "validate_paging",
]
