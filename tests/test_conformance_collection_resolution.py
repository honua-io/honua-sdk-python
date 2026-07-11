"""Unit tests for the conformance harness' OGC collection resolution.

These run in the normal (non-integration) suite — they exercise
``scripts._conformance._resolve_ogc_collection_id`` against a fake OGC client so
no live server is required. They guard the fix for the review-bot finding that
the required OGC cases must validate the *configured* ``HONUA_SERVICE_ID``/
``HONUA_LAYER_ID`` target, not whichever collection the server lists first.
"""

from __future__ import annotations

from typing import Any

import pytest

from scripts._conformance import (
    ConformanceTarget,
    _configured_ogc_collection_candidates,
    _resolve_ogc_collection_id,
)


class _FakeOgcFeatures:
    def __init__(self, collections: list[dict[str, Any]]) -> None:
        self._collections = collections

    def collections(self) -> dict[str, Any]:
        return {"collections": self._collections}


class _FakeClient:
    def __init__(self, collections: list[dict[str, Any]]) -> None:
        self._ogc = _FakeOgcFeatures(collections)

    def ogc_features(self) -> _FakeOgcFeatures:
        return self._ogc


def _target(service_id: str = "test_service", layer_id: int = 0) -> ConformanceTarget:
    return ConformanceTarget(base_url="http://example.invalid", service_id=service_id, layer_id=layer_id)


def test_selects_configured_target_not_first_collection() -> None:
    # An unrelated collection is advertised first; the seeded target's collection
    # (serviceLocalId == layer index text, "0") is listed later. The resolver
    # must pick the configured target, not collections[0].
    client = _FakeClient(
        [
            {"id": "unrelated_layer", "title": "Some Other Layer"},
            {"id": "0", "title": "Test Layer"},
        ]
    )
    assert _resolve_ogc_collection_id(client, _target()) == "0"


def test_prefers_service_qualified_composite_when_present() -> None:
    # When a deployment names collections with a service-qualified composite,
    # that wins over a bare layer-index collection that also happens to exist.
    client = _FakeClient(
        [
            {"id": "0"},
            {"id": "test_service_0"},
        ]
    )
    assert _resolve_ogc_collection_id(client, _target()) == "test_service_0"


def test_matches_case_insensitively() -> None:
    client = _FakeClient([{"id": "Test_Service_0"}])
    assert _resolve_ogc_collection_id(client, _target()) == "Test_Service_0"


def test_no_matching_collection_raises_clear_error() -> None:
    # Multiple advertised collections, none of which correspond to the configured
    # target: fail loudly rather than silently validating an unrelated collection.
    client = _FakeClient(
        [
            {"id": "roads"},
            {"id": "parcels"},
        ]
    )
    with pytest.raises(AssertionError) as excinfo:
        _resolve_ogc_collection_id(client, _target())
    message = str(excinfo.value)
    assert "test_service" in message
    assert "roads" in message and "parcels" in message
    # Must not silently fall back to the first collection.
    assert "first" in message.lower()


def test_empty_collections_raises() -> None:
    client = _FakeClient([])
    with pytest.raises(AssertionError):
        _resolve_ogc_collection_id(client, _target())


def test_candidate_forms_cover_known_naming_schemes() -> None:
    candidates = _configured_ogc_collection_candidates(_target("svc", 3))
    assert "svc_3" in candidates
    assert "svc" in candidates
    assert "3" in candidates
    # Service-qualified composites precede the bare layer-index fallback.
    assert candidates.index("svc_3") < candidates.index("3")
