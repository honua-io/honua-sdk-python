"""Unit tests for the shared sync/async query dispatcher helpers.

These helpers (``honua_sdk._query_dispatch``) are the non-IO portion of the
``client.query`` / ``client.iter_query`` fan-out. The sync and async clients
each consume them identically; this module pins the contract so a future
helper change can't silently desync the two dispatchers.
"""

from __future__ import annotations

import pytest

from honua_sdk._query_dispatch import (
    feature_server_pages_kwargs,
    merge_idempotency_into_headers,
    merge_request_headers,
    odata_pages_kwargs,
    ogc_features_pages_kwargs,
    reject_odata_bbox,
    stac_pages_kwargs,
    validate_filter_routing,
)
from honua_sdk.models import FeatureQuery


def _query(**overrides: object) -> FeatureQuery:
    defaults: dict[str, object] = {
        "source": "svc",
        "protocol": "feature-server",
    }
    defaults.update(overrides)
    return FeatureQuery(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# validate_filter_routing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("protocol", ["ogc-features", "stac"])
def test_validate_filter_routing_rejects_where_without_filter(protocol: str) -> None:
    """``where`` on OGC Features / STAC must not be silently routed to CQL."""
    query = _query(protocol=protocol, where="name = 'a'")
    with pytest.raises(ValueError, match="SQL-style filter"):
        validate_filter_routing(query, protocol)


@pytest.mark.parametrize("protocol", ["ogc-features", "stac"])
def test_validate_filter_routing_allows_filter_only(protocol: str) -> None:
    """A bare ``filter`` (CQL2-text) on OGC/STAC dispatches without error."""
    query = _query(protocol=protocol, filter="name = 'a'")
    validate_filter_routing(query, protocol)  # does not raise


def test_validate_filter_routing_passes_through_feature_server() -> None:
    """FeatureServer's ``where`` slot is SQL-style; no rejection."""
    validate_filter_routing(
        _query(protocol="feature-server", where="status = 'active'"),
        "feature-server",
    )


# ---------------------------------------------------------------------------
# header merge helpers
# ---------------------------------------------------------------------------


def test_merge_idempotency_passes_extra_through_when_no_key() -> None:
    extra = {"X-Trace": "abc"}
    assert merge_idempotency_into_headers(extra, None) is extra


def test_merge_idempotency_returns_none_when_nothing_set() -> None:
    assert merge_idempotency_into_headers(None, None) is None


def test_merge_idempotency_folds_key_into_copy() -> None:
    extra = {"X-Trace": "abc"}
    merged = merge_idempotency_into_headers(extra, "k1")
    assert merged == {"X-Trace": "abc", "Idempotency-Key": "k1"}
    # original mapping not mutated
    assert "Idempotency-Key" not in extra


def test_merge_request_headers_precedence() -> None:
    """Precedence: extra → headers → idempotency_key."""
    merged = merge_request_headers(
        headers={"A": "from-headers", "C": "headers-c"},
        extra_headers={"A": "from-extra", "B": "from-extra"},
        idempotency_key="k1",
    )
    assert merged == {
        "A": "from-headers",
        "B": "from-extra",
        "C": "headers-c",
        "Idempotency-Key": "k1",
    }


def test_merge_request_headers_returns_none_when_unset() -> None:
    assert merge_request_headers(None, None, None) is None


# ---------------------------------------------------------------------------
# per-protocol kwarg builders
# ---------------------------------------------------------------------------


def test_feature_server_pages_kwargs_defaults() -> None:
    kwargs = feature_server_pages_kwargs(
        _query(layer_id=None, where=None), timeout=None, extra_headers=None
    )
    assert kwargs["layer_id"] == 0
    assert kwargs["where"] == "1=1"
    assert kwargs["out_fields"] == "*"
    assert kwargs["page_size"] == 1000
    # ``FeatureQuery.max_pages`` is forwarded verbatim: ``None`` means unbounded
    # (the 100-page default now lives on the canonical ``client.query`` /
    # ``Source`` method signatures, not silently in this dispatch helper).
    assert kwargs["max_pages"] is None


def test_feature_server_pages_kwargs_forwards_explicit_max_pages() -> None:
    kwargs = feature_server_pages_kwargs(
        _query(max_pages=7), timeout=None, extra_headers=None
    )
    assert kwargs["max_pages"] == 7


def test_feature_server_pages_kwargs_prefers_where_over_filter() -> None:
    kwargs = feature_server_pages_kwargs(
        _query(where="a = 1", filter="b = 2"), timeout=None, extra_headers=None
    )
    assert kwargs["where"] == "a = 1"


def test_ogc_features_pages_kwargs_forwards_bbox_and_filter() -> None:
    kwargs = ogc_features_pages_kwargs(
        _query(protocol="ogc-features", filter="name = 'a'", bbox=(1, 2, 3, 4)),
        timeout=None,
        extra_headers=None,
    )
    assert kwargs["filter"] == "name = 'a'"
    assert kwargs["bbox"] == (1, 2, 3, 4)


def test_stac_pages_kwargs_splices_into_extra_params() -> None:
    kwargs = stac_pages_kwargs(
        _query(
            protocol="stac",
            filter="cloud_cover<10",
            bbox=(1, 2, 3, 4),
            fields=["id", "geometry"],
        ),
        timeout=None,
        extra_headers=None,
    )
    extras = kwargs["extra_params"]
    assert extras["bbox"] == "1,2,3,4"
    assert extras["filter"] == "cloud_cover<10"
    assert extras["fields"] == "id,geometry"


def test_stac_pages_kwargs_respects_caller_extra_params() -> None:
    """Caller-provided values in ``extra_params`` win over dispatcher defaults."""
    kwargs = stac_pages_kwargs(
        _query(
            protocol="stac",
            bbox=(1, 2, 3, 4),
            extra_params={"bbox": "10,20,30,40"},
        ),
        timeout=None,
        extra_headers=None,
    )
    assert kwargs["extra_params"]["bbox"] == "10,20,30,40"


def test_odata_pages_kwargs_basic() -> None:
    kwargs = odata_pages_kwargs(
        _query(protocol="odata", layer_id=3, filter="x eq 1"),
        timeout=None,
        extra_headers=None,
    )
    assert kwargs["layer_id"] == 3
    assert kwargs["filter"] == "x eq 1"


def test_reject_odata_bbox() -> None:
    with pytest.raises(ValueError, match="bbox is not supported"):
        reject_odata_bbox(_query(protocol="odata", bbox=(1, 2, 3, 4)))


def test_reject_odata_bbox_passes_when_unset() -> None:
    reject_odata_bbox(_query(protocol="odata"))  # does not raise
