"""Protocol-dispatch helpers shared by the sync and async client query facades.

The :meth:`HonuaClient.query` / :meth:`AsyncHonuaClient.query` (and their
``iter_query`` / ``_collect_query_pages`` siblings) all dispatch the same
shape: validate the query, normalize the protocol, build a protocol-specific
kwargs dict, walk the protocol-wrapper iterator, then convert each item to a
:class:`QueryFeature`. The wrappers themselves are inherently sync-or-async
(httpx ``for`` vs ``async for``), so the loops live in the client modules,
but everything around them is pure and lives here.

Public helpers (callable from both ``client.py`` and ``async_client.py``):

- :func:`validate_filter_routing` -- reject silent ``where``→CQL forwarding
- :func:`merge_idempotency_into_headers` -- fold ``Idempotency-Key`` into
  ``extra_headers`` so the dispatcher can fan out a single mapping
- :func:`merge_request_headers` -- per-request header precedence merge
- :func:`feature_server_pages_kwargs` / :func:`feature_server_items_kwargs`
- :func:`ogc_features_pages_kwargs` / :func:`ogc_features_items_kwargs`
- :func:`stac_pages_kwargs` / :func:`stac_items_kwargs`
- :func:`odata_pages_kwargs` / :func:`odata_items_kwargs`
- :func:`reject_odata_bbox` -- raise ``ValueError`` when ``bbox`` is set on
  an OData query (sync and async dispatcher share the same wording)
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from ._query import (
    bbox_text,
    feature_server_extra_params,
    field_list,
    field_text,
    odata_layer_id,
    query_filter,
    query_max_pages,
    query_page_size,
)
from .models import FeatureQuery

# Protocols whose ``filter`` slot expects CQL2-text; rejecting silent
# ``where``→CQL forwarding here keeps the legacy dispatcher honest.
_CQL_FILTER_DISPATCH_PROTOCOLS = frozenset(("ogc-features", "stac"))


def validate_filter_routing(query: FeatureQuery, normalized_protocol: str) -> None:
    """Reject silent ``where``→CQL forwarding on OGC Features / STAC.

    Mirrors the rule enforced by :func:`honua_sdk.source._feature_query_for_source`
    so the legacy :meth:`HonuaClient.query` / :meth:`HonuaClient.iter_query`
    dispatcher does not quietly route a SQL-style ``where`` clause into a
    CQL2-text ``filter`` slot. The dispatcher operates on
    :class:`FeatureQuery`, whose ``filter`` slot is the CQL2-text channel
    (the equivalent of ``Query.cql_filter`` on the canonical facade); we
    require callers to use that slot (or ``Source.query`` with
    ``where_as_cql=True``) instead.
    """
    if normalized_protocol not in _CQL_FILTER_DISPATCH_PROTOCOLS:
        return
    if query.where is not None and query.filter is None:
        raise ValueError(
            "Query.where is a SQL-style filter; pass `cql_filter=...` "
            "(CQL2-text) when targeting OGC Features or STAC. To accept "
            "silent forwarding, pass where_as_cql=True explicitly."
        )


def merge_idempotency_into_headers(
    extra_headers: Mapping[str, str] | None,
    idempotency_key: str | None,
) -> Mapping[str, str] | None:
    """Fold ``idempotency_key`` into ``extra_headers`` for dispatcher fan-out.

    The query / iter_query dispatcher forwards a single ``extra_headers``
    mapping into each protocol's pagination wrapper, so we merge any
    explicit ``idempotency_key`` here. Returns the original mapping
    unchanged (or ``None``) when no key is supplied so we don't
    needlessly copy.
    """
    if idempotency_key is None:
        return extra_headers
    merged: dict[str, str] = dict(extra_headers) if extra_headers else {}
    merged["Idempotency-Key"] = idempotency_key
    return merged


def merge_request_headers(
    headers: Mapping[str, str] | None,
    extra_headers: Mapping[str, str] | None,
    idempotency_key: str | None,
) -> dict[str, str] | None:
    """Merge per-request header overrides.

    Precedence (lowest → highest): ``extra_headers`` → ``headers`` →
    explicit ``idempotency_key``. Returns ``None`` when no headers are set
    so we don't perturb httpx's default header handling.
    """
    if headers is None and extra_headers is None and idempotency_key is None:
        return None
    merged: dict[str, str] = {}
    if extra_headers:
        merged.update(extra_headers)
    if headers:
        merged.update(headers)
    if idempotency_key is not None:
        merged["Idempotency-Key"] = idempotency_key
    return merged


# ---------------------------------------------------------------------------
# Protocol-specific kwarg builders for the wrapper iterators
# ---------------------------------------------------------------------------


def _feature_server_layer_id(query: FeatureQuery) -> int:
    """FeatureServer layers default to ``0`` when unspecified on the query."""
    return 0 if query.layer_id is None else query.layer_id


def _feature_server_where_text(query: FeatureQuery) -> str:
    """FeatureServer accepts ``where`` (preferred) or ``filter``; default ``1=1``."""
    return query.where if query.where is not None else (query.filter or "1=1")


def feature_server_pages_kwargs(
    query: FeatureQuery,
    *,
    timeout: float | httpx.Timeout | None,
    extra_headers: Mapping[str, str] | None,
) -> dict[str, Any]:
    """Kwargs for ``feature_server(...).query_pages(...)`` (dispatcher fan-out).

    Shared by sync and async ``_collect_query_pages``. The positional
    ``layer_id`` is included as ``layer_id=...`` so callers can ``**spread``
    it without an extra positional.
    """
    return {
        "layer_id": _feature_server_layer_id(query),
        "where": _feature_server_where_text(query),
        "out_fields": field_text(query.fields, wildcard="*") or "*",
        "return_geometry": query.return_geometry,
        "page_size": query_page_size(query, 1000),
        "limit": query.limit,
        "max_pages": query_max_pages(query, 100),
        "extra_params": feature_server_extra_params(query),
        "timeout": timeout,
        "extra_headers": extra_headers,
    }


def feature_server_items_kwargs(
    query: FeatureQuery,
    *,
    timeout: float | httpx.Timeout | None,
    extra_headers: Mapping[str, str] | None,
) -> dict[str, Any]:
    """Kwargs for ``feature_server(...).query_items(...)`` (iter_query fan-out)."""
    return feature_server_pages_kwargs(
        query, timeout=timeout, extra_headers=extra_headers
    )


def ogc_features_pages_kwargs(
    query: FeatureQuery,
    *,
    timeout: float | httpx.Timeout | None,
    extra_headers: Mapping[str, str] | None,
) -> dict[str, Any]:
    """Kwargs for ``ogc_features().collection(...).items_pages(...)``."""
    return {
        "filter": query_filter(query),
        "bbox": query.bbox,
        "properties": field_list(query.fields),
        "page_size": query.page_size,
        "limit": query.limit,
        "max_pages": query.max_pages,
        "extra_params": query.extra_params,
        "timeout": timeout,
        "extra_headers": extra_headers,
    }


def ogc_features_items_kwargs(
    query: FeatureQuery,
    *,
    timeout: float | httpx.Timeout | None,
    extra_headers: Mapping[str, str] | None,
) -> dict[str, Any]:
    """Kwargs for ``ogc_features().collection(...).iter_items(...)``."""
    return ogc_features_pages_kwargs(
        query, timeout=timeout, extra_headers=extra_headers
    )


def _stac_extra_params(query: FeatureQuery) -> dict[str, Any]:
    """Assemble the STAC ``extra_params`` dict from the canonical query slots.

    STAC's search endpoint encodes ``bbox`` / ``filter`` / ``fields`` as
    query-string params rather than dedicated kwargs on the iterator, so
    we splice them into ``extra_params`` (preserving any caller-supplied
    values via ``setdefault``).
    """
    params = dict(query.extra_params)
    if query.bbox is not None:
        params.setdefault("bbox", bbox_text(query.bbox))
    if query_filter(query) is not None:
        params.setdefault("filter", query_filter(query))
    if field_text(query.fields) is not None:
        params.setdefault("fields", field_text(query.fields))
    return params


def stac_pages_kwargs(
    query: FeatureQuery,
    *,
    timeout: float | httpx.Timeout | None,
    extra_headers: Mapping[str, str] | None,
) -> dict[str, Any]:
    """Kwargs for ``stac().item_pages(query.source, ...)``."""
    return {
        "extra_params": _stac_extra_params(query),
        "page_size": query.page_size,
        "limit": query.limit,
        "max_pages": query.max_pages,
        "timeout": timeout,
        "extra_headers": extra_headers,
    }


def stac_items_kwargs(
    query: FeatureQuery,
    *,
    timeout: float | httpx.Timeout | None,
    extra_headers: Mapping[str, str] | None,
) -> dict[str, Any]:
    """Kwargs for ``stac().iter_items(query.source, ...)``."""
    return stac_pages_kwargs(query, timeout=timeout, extra_headers=extra_headers)


def reject_odata_bbox(query: FeatureQuery) -> None:
    """OData has no spatial-filter equivalent; reject ``bbox`` at the dispatcher."""
    if query.bbox is not None:
        raise ValueError(
            "bbox is not supported for OData shared queries; "
            "express spatial filters in `filter`."
        )


def odata_pages_kwargs(
    query: FeatureQuery,
    *,
    timeout: float | httpx.Timeout | None,
    extra_headers: Mapping[str, str] | None,
) -> dict[str, Any]:
    """Kwargs for ``odata().features_pages(...)`` (dispatcher fan-out).

    Callers must invoke :func:`reject_odata_bbox` first; this helper does
    not re-validate ``bbox``.
    """
    return {
        "layer_id": odata_layer_id(query),
        "filter": query_filter(query),
        "select": field_list(query.fields),
        "page_size": query.page_size,
        "limit": query.limit,
        "max_pages": query.max_pages,
        "extra_params": query.extra_params,
        "timeout": timeout,
        "extra_headers": extra_headers,
    }


def odata_items_kwargs(
    query: FeatureQuery,
    *,
    timeout: float | httpx.Timeout | None,
    extra_headers: Mapping[str, str] | None,
) -> dict[str, Any]:
    """Kwargs for ``odata().iter_features(...)`` (iter_query fan-out)."""
    return odata_pages_kwargs(query, timeout=timeout, extra_headers=extra_headers)


__all__ = [
    "feature_server_items_kwargs",
    "feature_server_pages_kwargs",
    "merge_idempotency_into_headers",
    "merge_request_headers",
    "odata_items_kwargs",
    "odata_pages_kwargs",
    "ogc_features_items_kwargs",
    "ogc_features_pages_kwargs",
    "reject_odata_bbox",
    "stac_items_kwargs",
    "stac_pages_kwargs",
    "validate_filter_routing",
]
