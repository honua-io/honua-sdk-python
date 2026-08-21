from __future__ import annotations

import importlib.metadata
from pathlib import Path

import pytest

from scripts._conformance import (
    CaseResult,
    ConformanceCase,
    ConformanceTarget,
    FixtureBundle,
    build_certification_fragment,
    validate_release_certification_fragment,
)


def _case(name: str, known_gap_issue: str | None = None) -> ConformanceCase:
    return ConformanceCase(
        name=name,
        fixture="fixture",
        sdk_method="sdk.method",
        request_path="/request",
        runner=lambda *_: {},
        known_gap_issue=known_gap_issue,
    )


def _result(name: str, status: str) -> CaseResult:
    return CaseResult(
        name=name,
        status=status,
        fixture="fixture",
        message_type="Message",
        sdk_method="sdk.method",
        request_path="/request",
        started_at="2026-08-20T00:00:00Z",
        completed_at="2026-08-20T00:00:01Z",
    )


def test_build_certification_fragment_normalizes_identity_and_results(monkeypatch) -> None:
    monkeypatch.setattr(importlib.metadata, "version", lambda _: "9.9.9")
    source_sha = "a" * 40
    sdk_sha = "c" * 40
    image_digest = "sha256:" + "b" * 64
    target = ConformanceTarget(
        base_url="http://localhost:5000",
        server_commit=source_sha,
        server_image_digest=image_digest,
        sdk_source_sha=sdk_sha,
        evidence_uri="https://example.test/run/1",
        candidate_cut_at="2026-08-20T00:00:00Z",
        certification_tier="release",
    )
    passing = _case("feature_query_envelope")
    gap = _case("temporal_query", "https://github.com/honua-io/honua-server/issues/2643")

    fragment = build_certification_fragment(
        FixtureBundle(Path("."), "fixture-v1"),
        target,
        [(passing, _result(passing.name, "passed")), (gap, _result(gap.name, "failed"))],
    )

    assert fragment["schema"] == "honua.protocol-certification-fragment/v1"
    assert fragment["producer"] == "honua-sdk-python"
    assert fragment["candidate"] == {
        "source_sha": source_sha,
        "image_digest": image_digest,
        "cut_at": "2026-08-20T00:00:00Z",
    }
    assert fragment["operation_scope"]["complete"] is False
    assert fragment["operation_scope"]["owner_issue"].endswith("/issues/21")
    with pytest.raises(AssertionError, match="operation scope is incomplete"):
        validate_release_certification_fragment(fragment)
    passed, failed = fragment["observations"]
    assert passed["operation"] == "query"
    assert passed["capability_key"] == "serve.geoservices-featureserver"
    assert passed["scenario_facets"] == ["positive", "pagination"]
    assert passed["client_version"] == "9.9.9"
    assert passed["result"] == "pass"
    assert passed["skip_reason"] is None
    assert passed["producer_source_sha"] == sdk_sha
    assert passed["fixture_revision"] == "geospatial-grpc@fixture-v1"
    assert failed["operation"] == "temporal-query"
    assert failed["result"] == "fail"
    assert failed["skip_reason"] == gap.known_gap_issue
