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
        evidence_uri="https://github.com/honua-io/honua-sdk-python/actions/runs/1",
        candidate_cut_at="2026-08-20T00:00:00Z",
        certification_tier="release",
    )
    cases = [(_case(name), _result(name, "passed")) for name in CASE_CERTIFICATION]
    fragment = build_certification_fragment(FixtureBundle(Path("."), "fixture-v1"), target, cases)
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
