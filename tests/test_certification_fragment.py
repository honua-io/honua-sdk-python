from __future__ import annotations

import importlib.metadata
import json
import tomllib
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from scripts._conformance import (
    CaseResult,
    CASE_CERTIFICATION,
    ConformanceCase,
    ConformanceTarget,
    FixtureBundle,
    build_cases,
    build_certification_fragment,
    validate_candidate_cut_at,
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
        sdk_wheel_filename="honua_sdk-9.9.9-py3-none-any.whl",
        sdk_wheel_sha256="d" * 64,
        sdk_wheel_source="pypi",
        evidence_uri="https://github.com/honua-io/honua-sdk-python/actions/runs/1",
        candidate_cut_at="2026-08-20T00:00:00Z",
        certification_tier="release",
    )
    cases_by_name = {case.name: case for case in build_cases()}
    passing = cases_by_name["feature_query_envelope"]
    gap = cases_by_name["temporal_query"]

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
    assert passed["canonical_client"] == "Honua SDK Python"
    assert passed["client_id"] == passed["canonical_client"]
    assert passed["runner_lane"] == "sdk-python-certification"
    assert passed["protocol_version"] == "11.0"
    assert passed["protocol_profile"] == "GeoServices REST"
    assert passed["performed_by"] == passed["client_id"]
    assert passed["request_url"] == (
        "http://localhost:5000/rest/services/test_service/FeatureServer/0/query"
    )
    assert passed["exercised_capabilities"] == passed["scenario_facets"]
    assert passed["client_version"] == "9.9.9"
    assert passed["result"] == "pass"
    assert passed["skip_reason"] is None
    assert passed["producer_source_sha"] == sdk_sha
    assert passed["client_package"] == {
        "filename": "honua_sdk-9.9.9-py3-none-any.whl",
        "sha256": "d" * 64,
        "source": "pypi",
    }
    assert passed["evidence_receipt"]["identity"]["client_package"] == passed["client_package"]
    assert passed["fixture_revision"] == "geospatial-grpc@fixture-v1"
    assert passed["contract_revision"] == f"sdk-python-certification@{sdk_sha}"
    assert passed["auth_policy_revision"] == "anonymous-public-v1"
    assert passed["evidence_receipt"]["identity"]["candidate_cut_at"] == target.candidate_cut_at
    assert passed["evidence_digest"].startswith("sha256:")
    assert set(passed["facet_results"]) == set(passed["scenario_facets"])
    assert all(
        facet == {"result": "pass", "evidence_digest": passed["evidence_digest"]}
        for facet in passed["facet_results"].values()
    )
    assert failed["operation"] == "temporal-query"
    assert failed["result"] == "skip"
    assert failed["skip_reason"] == gap.known_gap_issue
    assert failed["evidence_digest"] is None
    assert failed["facet_results"] is None
    assert failed["exercised_capabilities"] == []


def test_every_observation_satisfies_truthful_identity_ingest_rules(monkeypatch) -> None:
    monkeypatch.setattr(importlib.metadata, "version", lambda _: "9.9.9")
    target = ConformanceTarget(
        base_url="https://candidate.test/root/",
        server_commit="a" * 40,
        server_image_digest="sha256:" + "b" * 64,
        sdk_source_sha="c" * 40,
        sdk_wheel_filename="honua_sdk-9.9.9-py3-none-any.whl",
        sdk_wheel_sha256="d" * 64,
        sdk_wheel_source="pypi",
        evidence_uri="https://github.com/honua-io/honua-sdk-python/actions/runs/1",
        candidate_cut_at="2026-08-20T00:00:00Z",
        certification_tier="release",
    )
    cases = [(_case(name), _result(name, "passed")) for name in CASE_CERTIFICATION]

    fragment = build_certification_fragment(FixtureBundle(Path("."), "fixture-v1"), target, cases)
    expected_protocol_context = {
        "geoservices-root": ("11.0", "GeoServices REST"),
        "geoservices-featureserver": ("11.0", "GeoServices REST"),
        "ogc-api-features": ("1.0", "core"),
        "ogc-api-processes": ("1.0", "core"),
    }

    for observation in fragment["observations"]:
        assert observation["client_id"] == observation["canonical_client"]
        assert observation["runner_lane"] == "sdk-python-certification"
        assert observation["performed_by"] == observation["client_id"]
        assert (
            observation["protocol_version"], observation["protocol_profile"]
        ) == expected_protocol_context[observation["surface"]]
        parsed_url = urlsplit(observation["request_url"])
        assert parsed_url.scheme in {"http", "https"}
        assert parsed_url.netloc
        assert isinstance(observation["exercised_capabilities"], list)
        if observation["result"] == "pass":
            assert set(observation["scenario_facets"]).issubset(
                observation["exercised_capabilities"]
            )


def test_certification_rejects_malformed_wheel_digest(monkeypatch) -> None:
    monkeypatch.setattr(importlib.metadata, "version", lambda _: "9.9.9")
    target = ConformanceTarget(
        base_url="http://localhost:5000",
        server_commit="a" * 40,
        server_image_digest="sha256:" + "b" * 64,
        sdk_source_sha="c" * 40,
        sdk_wheel_filename="honua_sdk-9.9.9-py3-none-any.whl",
        sdk_wheel_sha256="not-a-digest",
        sdk_wheel_source="pypi",
        evidence_uri="local://test",
        candidate_cut_at="2026-08-20T00:00:00Z",
    )

    with pytest.raises(RuntimeError, match="sdk_wheel_sha256"):
        build_certification_fragment(
            FixtureBundle(Path("."), "fixture-v1"),
            target,
            [(_case("feature_query_envelope"), _result("feature_query_envelope", "passed"))],
        )


@pytest.mark.parametrize(
    "value",
    [
        "2026-13-40T25:61:61Z",
        "2026-08-20T00:00:00+00:00",
        "2026-08-20T00:00:00.000Z",
        "2026-8-20T00:00:00Z",
        "",
        None,
    ],
)
def test_candidate_cut_requires_a_calendar_valid_canonical_utc_timestamp(
    value: str | None,
) -> None:
    with pytest.raises(RuntimeError, match="candidate_cut_at"):
        validate_candidate_cut_at(value)


def test_candidate_cut_changes_the_content_addressed_receipt(monkeypatch) -> None:
    monkeypatch.setattr(importlib.metadata, "version", lambda _: "9.9.9")
    case = _case("feature_query_envelope")

    def build(cut_at: str) -> dict:
        target = ConformanceTarget(
            base_url="http://localhost:5000",
            server_commit="a" * 40,
            server_image_digest="sha256:" + "b" * 64,
            sdk_source_sha="c" * 40,
            sdk_wheel_filename="honua_sdk-9.9.9-py3-none-any.whl",
            sdk_wheel_sha256="d" * 64,
            sdk_wheel_source="pypi",
            evidence_uri="https://github.com/honua-io/honua-sdk-python/actions/runs/1",
            candidate_cut_at=cut_at,
            certification_tier="release",
        )
        return build_certification_fragment(
            FixtureBundle(Path("."), "fixture-v1"),
            target,
            [(case, _result(case.name, "passed"))],
        )["observations"][0]

    first = build("2026-08-20T00:00:00Z")
    second = build("2026-08-20T00:00:01Z")
    assert first["evidence_digest"] != second["evidence_digest"]
    assert first["evidence_uri"] != second["evidence_uri"]


def test_release_validator_rejects_receipt_bound_to_another_cut(monkeypatch) -> None:
    monkeypatch.setattr(importlib.metadata, "version", lambda _: "9.9.9")
    target = ConformanceTarget(
        base_url="http://localhost:5000",
        server_commit="a" * 40,
        server_image_digest="sha256:" + "b" * 64,
        sdk_source_sha="c" * 40,
        sdk_wheel_filename="honua_sdk-9.9.9-py3-none-any.whl",
        sdk_wheel_sha256="d" * 64,
        sdk_wheel_source="pypi",
        evidence_uri="https://github.com/honua-io/honua-sdk-python/actions/runs/1",
        candidate_cut_at="2026-08-20T00:00:00Z",
        certification_tier="release",
    )
    cases = [(_case(name), _result(name, "passed")) for name in CASE_CERTIFICATION]
    fragment = build_certification_fragment(FixtureBundle(Path("."), "fixture-v1"), target, cases)
    # This test isolates receipt binding after the independent scope gate.
    fragment["operation_scope"]["complete"] = True
    fragment["operation_scope"]["required_operations"] = [
        {"surface": row["surface"], "operation": row["operation"]}
        for row in fragment["observations"]
    ]
    fragment["observations"][0]["evidence_receipt"]["identity"]["candidate_cut_at"] = (
        "2026-08-20T00:00:01Z"
    )

    with pytest.raises(AssertionError, match="not bound to candidate.cut_at"):
        validate_release_certification_fragment(fragment)


def test_machine_readable_certification_contract_matches_case_mapping() -> None:
    root = Path(__file__).resolve().parents[1]
    contract = json.loads(
        (root / "conformance" / "protocol-certification.v1.json").read_text(encoding="utf-8")
    )
    package = tomllib.loads((root / "packages" / "honua-sdk" / "pyproject.toml").read_text(encoding="utf-8"))
    expected = sorted(
        (
            {
                "capability_key": capability,
                "surface": surface,
                "operation": operation,
                "scenario_facets": facets,
            }
            for capability, surface, operation, facets in CASE_CERTIFICATION.values()
        ),
        key=lambda row: (row["surface"], row["operation"]),
    )
    assert sorted(
        contract["operations"], key=lambda row: (row["surface"], row["operation"])
    ) == expected
    assert contract["canonicalClient"] == "Honua SDK Python"
    assert contract["clientVersion"] == package["project"]["version"]


def test_sdkpy_003_full_rest_case_list_does_not_complete_grpc_operation_scope(monkeypatch) -> None:
    """SDKPY-003: REST-only evidence must not certify public gRPC operations."""
    monkeypatch.setattr(importlib.metadata, "version", lambda _: "9.9.9")
    target = ConformanceTarget(
        base_url="http://localhost:5000",
        server_commit="a" * 40,
        server_image_digest="sha256:" + "b" * 64,
        sdk_source_sha="c" * 40,
        sdk_wheel_filename="honua_sdk-9.9.9-py3-none-any.whl",
        sdk_wheel_sha256="d" * 64,
        sdk_wheel_source="pypi",
        evidence_uri="https://evidence.invalid/run/1",
        candidate_cut_at="2026-08-20T00:00:00Z",
        certification_tier="release",
    )
    cases = [(_case(name), _result(name, "passed")) for name in CASE_CERTIFICATION]

    fragment = build_certification_fragment(FixtureBundle(Path("."), "fixture-v1"), target, cases)

    assert fragment["operation_scope"]["complete"] is False
    assert {("grpc-feature-service", "query-features"), ("grpc-feature-service", "query-features-stream")} <= {
        (row["surface"], row["operation"]) for row in fragment["operation_scope"]["required_operations"]
    }
    with pytest.raises(AssertionError, match="operation scope is incomplete"):
        validate_release_certification_fragment(fragment)


def test_sdkpy_007_sync_metadata_probe_is_not_edit_certification() -> None:
    """SDKPY-007: metadata-only evidence must not claim an apply-edits capability."""
    capability, surface, operation, facets = CASE_CERTIFICATION["replica_sync_surface"]

    assert capability == "sync.featureserver-replicas"
    assert (surface, operation, facets) == (
        "geoservices-featureserver",
        "sync-capability",
        ["positive", "metadata"],
    )


def test_apply_edits_stays_required_when_grpc_cases_join_the_harness(monkeypatch) -> None:
    """Closing the two gRPC cells must not complete scope without a live applyEdits case.

    REQUIRED_CERTIFICATION_OPERATIONS is fixed at import from the current harness
    plus the independent cells. A later harness that adds live gRPC cases makes
    those cells observed, but geoservices-featureserver/apply-edits stays required
    and unobserved, so release validation still fails closed.
    """
    import scripts._conformance as conformance

    extended = dict(conformance.CASE_CERTIFICATION)
    extended["grpc_query_features"] = (
        "grpc.feature-service",
        "grpc-feature-service",
        "query-features",
        ["positive"],
    )
    extended["grpc_query_features_stream"] = (
        "grpc.feature-service",
        "grpc-feature-service",
        "query-features-stream",
        ["positive"],
    )
    monkeypatch.setattr(conformance, "CASE_CERTIFICATION", extended)
    monkeypatch.setitem(
        conformance.CERTIFICATION_PROTOCOL_CONTEXT,
        "grpc-feature-service",
        ("1.0", "grpc"),
    )
    monkeypatch.setattr(importlib.metadata, "version", lambda _: "9.9.9")
    target = ConformanceTarget(
        base_url="http://localhost:5000",
        server_commit="a" * 40,
        server_image_digest="sha256:" + "b" * 64,
        sdk_source_sha="c" * 40,
        sdk_wheel_filename="honua_sdk-9.9.9-py3-none-any.whl",
        sdk_wheel_sha256="d" * 64,
        sdk_wheel_source="pypi",
        evidence_uri="https://evidence.invalid/run/1",
        candidate_cut_at="2026-08-20T00:00:00Z",
        certification_tier="release",
    )
    cases = [(_case(name), _result(name, "passed")) for name in extended]

    fragment = conformance.build_certification_fragment(
        FixtureBundle(Path("."), "fixture-v1"), target, cases
    )

    observed = {(row["surface"], row["operation"]) for row in fragment["observations"]}
    required = {
        (row["surface"], row["operation"]) for row in fragment["operation_scope"]["required_operations"]
    }
    assert ("geoservices-featureserver", "apply-edits") in required
    assert ("geoservices-featureserver", "apply-edits") not in observed
    assert observed == required - {("geoservices-featureserver", "apply-edits")}
    assert fragment["operation_scope"]["complete"] is False
    sync = next(row for row in fragment["observations"] if row["capability_key"] == "sync.featureserver-replicas")
    assert sync["operation"] == "sync-capability"
    with pytest.raises(AssertionError, match="operation scope is incomplete"):
        conformance.validate_release_certification_fragment(fragment)
