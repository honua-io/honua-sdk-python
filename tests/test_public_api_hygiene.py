"""Tests for the trimmed public API surface, error hierarchy, and
``Source._feature_query_for_source`` where/filter routing.
"""

from __future__ import annotations

import pytest

import honua_sdk
from honua_sdk import (
    HonuaAuthError,
    HonuaError,
    HonuaHttpError,
    HonuaRateLimitError,
    HonuaTimeoutError,
    HonuaTransportError,
    Query,
    SourceDescriptor,
    SourceLocator,
    normalize_capability,
    normalize_protocol,
)
from honua_sdk.source import _feature_query_for_source


# ---------------------------------------------------------------------------
# Trimmed __all__ / submodule namespacing
# ---------------------------------------------------------------------------

# Names that used to live at the top of ``honua_sdk`` but must now be imported
# from ``honua_sdk.protocols`` or ``honua_sdk.ogc``.
_PROTOCOL_HANDLER_NAMES = (
    "GeoServicesFeatureServerClient",
    "GeoServicesMapServerClient",
    "GeoServicesImageServerClient",
    "GeoServicesGeometryServerClient",
    "OgcMapsClient",
    "OgcTilesClient",
    "OgcCoveragesClient",
    "OgcProcessesClient",
    "StacClient",
    "WfsClient",
    "WmsClient",
    "WmtsClient",
    "ODataClient",
    "AsyncGeoServicesFeatureServerClient",
    "AsyncGeoServicesMapServerClient",
    "AsyncGeoServicesImageServerClient",
    "AsyncGeoServicesGeometryServerClient",
    "AsyncOgcMapsClient",
    "AsyncOgcTilesClient",
    "AsyncOgcCoveragesClient",
    "AsyncOgcProcessesClient",
    "AsyncStacClient",
    "AsyncWfsClient",
    "AsyncWmsClient",
    "AsyncWmtsClient",
    "AsyncODataClient",
    "BinaryResponse",
    "ODataQuery",
    "ODataOrderBy",
    "JsonObject",
    "JsonResponseFormat",
    "OgcImageFormat",
    "BboxValue",
    "CsvValue",
    "FeatureId",
    "WfsVersion",
    "WmsVersion",
    "WmtsVersion",
)

_OGC_NAMES = (
    "HonuaOgcFeatures",
    "HonuaOgcFeatureCollection",
    "AsyncHonuaOgcFeatures",
    "AsyncHonuaOgcFeatureCollection",
)


@pytest.mark.parametrize("name", _PROTOCOL_HANDLER_NAMES)
def test_protocol_handler_name_removed_from_top_level(name: str) -> None:
    assert name not in honua_sdk.__all__, (
        f"{name} should no longer be in honua_sdk.__all__; "
        "import it from honua_sdk.protocols instead."
    )


@pytest.mark.parametrize("name", _PROTOCOL_HANDLER_NAMES)
def test_protocol_handler_name_importable_from_submodule(name: str) -> None:
    from honua_sdk import protocols

    assert hasattr(protocols, name), f"{name} should live under honua_sdk.protocols"


@pytest.mark.parametrize("name", _OGC_NAMES)
def test_ogc_classes_removed_from_top_level_and_importable_via_ogc(name: str) -> None:
    from honua_sdk import ogc

    assert name not in honua_sdk.__all__
    assert hasattr(ogc, name), f"{name} should live under honua_sdk.ogc"


def test_top_level_all_keeps_task_oriented_names() -> None:
    keep = {
        "HonuaClient",
        "AsyncHonuaClient",
        "HonuaGeocodingClient",
        "AsyncHonuaGeocodingClient",
        "Source",
        "AsyncSource",
        "SourceDescriptor",
        "SourceLocator",
        "Query",
        "Pagination",
        "Result",
        "QueryFeature",
        "HonuaError",
        "HonuaHttpError",
        "HonuaAuthError",
        "HonuaRateLimitError",
        "HonuaTransportError",
        "HonuaTimeoutError",
        "normalize_protocol",
        "normalize_capability",
    }
    missing = keep - set(honua_sdk.__all__)
    assert not missing, f"top-level __all__ is missing required names: {missing}"


# ---------------------------------------------------------------------------
# Error hierarchy
# ---------------------------------------------------------------------------


def test_auth_and_rate_limit_errors_subclass_http_error() -> None:
    assert issubclass(HonuaAuthError, HonuaHttpError)
    assert issubclass(HonuaRateLimitError, HonuaHttpError)
    assert issubclass(HonuaHttpError, HonuaError)


def test_timeout_subclasses_transport_error() -> None:
    assert issubclass(HonuaTimeoutError, HonuaTransportError)
    assert issubclass(HonuaTransportError, HonuaError)


def test_rate_limit_error_carries_retry_after() -> None:
    err = HonuaRateLimitError(429, "slow down", body={"detail": "x"}, retry_after=2.5)
    assert err.status_code == 429
    assert err.retry_after == 2.5
    assert err.body == {"detail": "x"}
    # Drop-in compatibility: callers catching HonuaHttpError still see it.
    assert isinstance(err, HonuaHttpError)


def test_rate_limit_error_retry_after_defaults_none() -> None:
    err = HonuaRateLimitError(429, "slow down")
    assert err.retry_after is None


def test_auth_error_is_drop_in_http_error() -> None:
    err = HonuaAuthError(401, "unauthorized")
    assert isinstance(err, HonuaHttpError)
    assert err.status_code == 401


# ---------------------------------------------------------------------------
# Strict Literal protocol/capability types + explicit normalization helper
# ---------------------------------------------------------------------------


def test_normalize_protocol_accepts_aliases_and_rejects_unknown() -> None:
    assert normalize_protocol("feature-server") == "geoservices-feature-service"
    assert normalize_protocol("OGC-Features") == "ogc-features"
    with pytest.raises(ValueError) as exc:
        normalize_protocol("not-a-real-protocol")
    assert "Unsupported protocol" in str(exc.value)


def test_normalize_capability_rejects_unknown_strings() -> None:
    assert normalize_capability("apply_edits") == "applyEdits"
    with pytest.raises(ValueError):
        normalize_capability("definitely-not-a-capability")


# ---------------------------------------------------------------------------
# _feature_query_for_source: where vs. filter routing
# ---------------------------------------------------------------------------


def _descriptor(protocol: str) -> SourceDescriptor:
    locator = SourceLocator(
        service_id="svc",
        layer_id=0,
        collection_id="parcels",
        entity_set="Layers",
    )
    return SourceDescriptor(
        id="src",
        protocol=protocol,
        locator=locator,
        capabilities=frozenset(("query",)),
    )


def test_feature_query_routes_where_for_feature_server() -> None:
    fq = _feature_query_for_source(
        _descriptor("geoservices-feature-service"),
        Query(where="STATUS = 'ACTIVE'"),
    )
    assert fq.where == "STATUS = 'ACTIVE'"
    assert fq.filter is None


def test_feature_query_routes_filter_for_ogc_features() -> None:
    # Canonical CQL path: callers should pass cql_filter on OGC Features.
    fq = _feature_query_for_source(
        _descriptor("ogc-features"),
        Query(cql_filter="STATUS = 'ACTIVE'"),
    )
    # OGC Features uses CQL/`filter`, not SQL/`where`.
    assert fq.filter == "STATUS = 'ACTIVE'"
    assert fq.where is None


def test_feature_query_routes_filter_for_stac() -> None:
    fq = _feature_query_for_source(
        _descriptor("stac"),
        Query(cql_filter="datetime >= '2024-01-01'"),
    )
    assert fq.filter == "datetime >= '2024-01-01'"
    assert fq.where is None


def test_feature_query_routes_where_for_odata() -> None:
    fq = _feature_query_for_source(
        _descriptor("odata"),
        Query(where="Status eq 'ACTIVE'"),
    )
    assert fq.where == "Status eq 'ACTIVE'"
    assert fq.filter is None
