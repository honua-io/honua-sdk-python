"""Tests for Source.query filter routing across SQL- and CQL-style protocols.

Covers the precedence rules implemented in
:func:`honua_sdk.source._feature_query_for_source`:

* ``cql_filter`` on an OGC/STAC source routes to ``FeatureQuery.filter``.
* ``where`` (alone) on an OGC/STAC source raises ``ValueError`` — SQL
  syntax is not valid for CQL endpoints and silent forwarding is a
  footgun. Callers opt into the legacy silent forwarding by setting
  ``where_as_cql=True``.
* ``where`` on a FeatureServer source routes to ``FeatureQuery.where``.
* ``cql_filter`` on a FeatureServer/OData source raises ``ValueError`` —
  CQL2-text is not valid for SQL-only protocols and silently dropping it
  would mask the bug.
* ``where_as_cql=True`` on a FeatureServer source is a no-op (still
  routes ``where`` to the SQL ``where`` field).
"""

from __future__ import annotations

import pytest

from honua_sdk.models import Query, SourceDescriptor, SourceLocator
from honua_sdk.source import _feature_query_for_source


def _ogc_descriptor() -> SourceDescriptor:
    return SourceDescriptor(
        id="parcels",
        protocol="ogc-features",
        locator=SourceLocator(collection_id="parcels"),
    )


def _stac_descriptor() -> SourceDescriptor:
    return SourceDescriptor(
        id="landsat",
        protocol="stac",
        locator=SourceLocator(collection_id="landsat"),
    )


def _featureserver_descriptor() -> SourceDescriptor:
    return SourceDescriptor(
        id="counties",
        protocol="geoservices-feature-service",
        locator=SourceLocator(service_id="counties", layer_id=0),
    )


def _odata_descriptor() -> SourceDescriptor:
    return SourceDescriptor(
        id="orders",
        protocol="odata",
        locator=SourceLocator(entity_set="Orders", layer_id=None),
    )


def test_cql_filter_on_ogc_routes_to_filter() -> None:
    descriptor = _ogc_descriptor()
    query = Query(cql_filter="STATE='CA'")

    fq = _feature_query_for_source(descriptor, query)

    assert fq.filter == "STATE='CA'"
    assert fq.where is None


def test_cql_filter_on_ogc_overrides_where() -> None:
    """When both are set, ``cql_filter`` wins on a CQL-based protocol."""
    descriptor = _ogc_descriptor()
    query = Query(where="STATE='WA'", cql_filter="STATE='CA'")

    fq = _feature_query_for_source(descriptor, query)

    assert fq.filter == "STATE='CA'"
    assert fq.where is None


def test_where_on_ogc_raises_without_opt_in() -> None:
    """``where`` alone on a CQL endpoint is a footgun and is rejected."""
    descriptor = _ogc_descriptor()
    query = Query(where="STATE='CA'")

    with pytest.raises(ValueError, match="Query.where is a SQL-style filter"):
        _feature_query_for_source(descriptor, query)


def test_where_on_stac_raises_without_opt_in() -> None:
    descriptor = _stac_descriptor()
    query = Query(where="eo:cloud_cover<20")

    with pytest.raises(ValueError, match="where_as_cql=True"):
        _feature_query_for_source(descriptor, query)


def test_where_on_ogc_with_opt_in_routes_to_filter() -> None:
    """Back-compat: callers can opt into silent SQL-as-CQL forwarding."""
    descriptor = _ogc_descriptor()
    query = Query(where="STATE='CA'", where_as_cql=True)

    fq = _feature_query_for_source(descriptor, query)

    assert fq.filter == "STATE='CA'"
    assert fq.where is None


def test_where_on_stac_with_opt_in_routes_to_filter() -> None:
    descriptor = _stac_descriptor()
    query = Query(where="eo:cloud_cover<20", where_as_cql=True)

    fq = _feature_query_for_source(descriptor, query)

    assert fq.filter == "eo:cloud_cover<20"
    assert fq.where is None


def test_where_on_featureserver_routes_to_where() -> None:
    descriptor = _featureserver_descriptor()
    query = Query(where="POPULATION>100000")

    fq = _feature_query_for_source(descriptor, query)

    assert fq.where == "POPULATION>100000"
    assert fq.filter is None


def test_where_as_cql_on_featureserver_is_noop() -> None:
    """``where_as_cql=True`` does not change SQL routing on FeatureServer."""
    descriptor = _featureserver_descriptor()
    query = Query(where="POPULATION>100000", where_as_cql=True)

    fq = _feature_query_for_source(descriptor, query)

    assert fq.where == "POPULATION>100000"
    assert fq.filter is None


def test_cql_filter_on_featureserver_raises() -> None:
    descriptor = _featureserver_descriptor()
    query = Query(cql_filter="POPULATION>100000")

    with pytest.raises(ValueError, match="cql_filter is only valid for CQL-based protocols"):
        _feature_query_for_source(descriptor, query)


def test_cql_filter_on_odata_raises() -> None:
    descriptor = _odata_descriptor()
    query = Query(cql_filter="Total gt 100")

    with pytest.raises(ValueError, match="cql_filter is only valid for CQL-based protocols"):
        _feature_query_for_source(descriptor, query)
