from __future__ import annotations

import base64
import copy
from dataclasses import replace
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts._conformance_entitlement import observe, profile, signed_status

NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)
STATUS = {"success": True, "data": {"mode": "enabled", "isValid": True, "validationState": "Valid",
          "licenseId": "signed-license-identifier", "issuedAt": "2026-10-01T00:00:00Z",
          "expiresAt": "2027-10-01T00:00:00Z", "entitlements": [{"key": "editing.featureserver-edits", "isActive": True}]}}


def test_rehearsal_grant_is_explicit_and_development_only():
    assert profile("pr", "pull_request", "Development", "") == {"mode": "development-grant", "devGrantEdition": "Enterprise", "licensingMode": "Enabled"}
    for tier, event, environment in [("pr", "pull_request", "Production"), ("unknown", "local", "Development")]:
        with pytest.raises(ValueError):
            profile(tier, event, environment, "")


@pytest.mark.parametrize("event", ["push", "schedule", "workflow_dispatch"])
@pytest.mark.parametrize("tier", ["pr", "nightly"])
def test_fragment_events_without_signed_license_run_public_cells_with_licensing_disabled(tier, event):
    assert profile(tier, event, "Development", "") == {
        "mode": "licensing-disabled", "devGrantEdition": "", "licensingMode": "Disabled"}
    assert profile("pr", "pull_request", "Development", "")["licensingMode"] == "Enabled"
    assert profile("release", "workflow_dispatch", "Development", '{"x":1}')["licensingMode"] == "Enabled"


def test_release_never_inherits_rehearsal_defaults_and_requires_governed_input():
    for event, content in [("workflow_dispatch", ""), ("workflow_dispatch", "not JSON"), ("workflow_dispatch", "{}"), ("pull_request", '{"x":1}')]:
        with pytest.raises(ValueError):
            profile("release", event, "Development", content)
    # Merely shaped input does not establish eligibility; live signature/entitlement
    # validation by the candidate and actual edit/readback operations remain required.
    assert profile("release", "workflow_dispatch", "Development", '{"unverified":true}') == {"mode": "signed", "devGrantEdition": "", "licensingMode": "Enabled"}
    with pytest.raises(AssertionError, match="signed non-development"):
        signed_status({"success": True, "data": {}}, now=NOW)


@pytest.mark.parametrize(("field", "value"), [("mode", "disabled"), ("isValid", False), ("validationState", "Expired"),
    ("licenseId", "dev-grant"), ("licenseId", "community"), ("issuedAt", None), ("issuedAt", "2027-01-01T00:00:00Z"),
    ("expiresAt", "2025-01-01T00:00:00Z"), ("entitlements", []),
    ("entitlements", [{"key": "editing.featureserver-edits", "isActive": False}])])
def test_release_requires_actual_active_signed_candidate_status(field, value):
    status = copy.deepcopy(STATUS)
    status["data"][field] = value
    with pytest.raises(AssertionError):
        signed_status(status, now=NOW)


def test_signed_status_retains_only_safe_identity_and_observation():
    proof = signed_status(STATUS, now=NOW)
    assert proof["status"] == "active" and proof["mode"] == "signed"
    assert proof["license_fingerprint"].startswith("sha256:")
    assert "signed-license-identifier" not in json.dumps(proof)


@pytest.mark.parametrize("mode", ["development-grant", "licensing-disabled"])
def test_release_probe_refuses_rehearsal_before_any_network(mode):
    with pytest.raises(AssertionError, match="refuses rehearsal"):
        observe(SimpleNamespace(certification_tier="release", entitlement_mode=mode))


def test_workflow_invokes_profile_policy_and_never_persists_license_contents():
    workflow = (Path(__file__).parents[1] / ".github/workflows/conformance.yml").read_text()
    assert 'from scripts._conformance_entitlement import profile' in workflow
    assert 'CERTIFICATION_EVENT: ${{ github.event_name }}' in workflow
    assert "github.event_name == 'workflow_dispatch' && github.event.inputs.certification_tier == 'release' && secrets.HONUA_CERTIFICATION_LICENSE_CONTENT" in workflow
    assert 'Licensing__DevGrantEdition: "${dev_grant}"' in workflow
    assert 'Licensing__Mode: "${licensing_mode}"' in workflow
    assert 'Licensing__LicenseContent: "\\${HONUA_CERTIFICATION_LICENSE_CONTENT:-}"' in workflow


def test_release_fragment_rejects_rehearsal_and_stale_entitlement_receipts():
    from scripts._conformance import validate_release_certification_fragment
    record = {"case": "feature_apply_edits_roundtrip", "entitlement_mode": "signed", "receipt": {
        "status": "passed", "started_at": "2026-10-17T00:00:00Z", "completed_at": "2026-10-17T00:00:01Z",
        "details": {"entitlement": signed_status(STATUS, now=NOW)}}}
    def fragment(value):
        return {"requirements_revision": "fixture-v2", "candidate": {"cut_at": "2026-10-17T00:00:00Z"}, "operation_scope": {"complete": True,
            "required_operations": [{"surface": "s", "operation": "edit"}]}, "observations": [{"surface": "s", "operation": "edit", "result": "pass", "maturity": "supported", "required_tier": "release",
            "evidence_receipt": {"schema": "honua.certification-evidence-receipt/v2", "identity": {"candidate_cut_at": "2026-10-17T00:00:00Z", "maturity": "supported", "required_tier": "release", "requirements_revision": "fixture-v2"}, "payload_base64": base64.b64encode(json.dumps([value]).encode()).decode()}}]}
    validate_release_certification_fragment(fragment(record))
    for mode in ("development-grant", "licensing-disabled", "unspecified"):
        wrong = copy.deepcopy(record)
        wrong["entitlement_mode"] = mode
        with pytest.raises(AssertionError, match="rehearsal evidence"):
            validate_release_certification_fragment(fragment(wrong))
    wrong = copy.deepcopy(record)
    wrong["receipt"]["details"]["entitlement"]["checked_at"] = "2026-10-16T00:00:00Z"
    with pytest.raises(AssertionError, match="fresh candidate-validated"):
        validate_release_certification_fragment(fragment(wrong))


def test_rehearsal_receipts_cannot_match_the_governed_release_auth_policy(monkeypatch, tmp_path):
    import importlib.metadata
    from scripts._conformance import (CaseResult, ConformanceFixturesError, ConformanceTarget, FixtureBundle, build_cases,
                                      build_certification_fragment, CERTIFICATION_AUTH_POLICY_REVISION)
    monkeypatch.setattr(importlib.metadata, "version", lambda _: "9.9.9")
    target = ConformanceTarget(base_url="http://localhost:5000", server_commit="a" * 40,
        server_image_digest="sha256:" + "b" * 64, sdk_source_sha="c" * 40,
        sdk_wheel_filename="honua_sdk-9.9.9-py3-none-any.whl", sdk_wheel_sha256="d" * 64,
        sdk_wheel_source="pypi", evidence_uri="https://evidence.example/run/1",
        candidate_cut_at="2026-10-17T00:00:00Z", entitlement_mode="development-grant")
    case = build_cases()[0]
    result = CaseResult(name=case.name, status="passed", fixture=case.fixture, message_type="message",
        sdk_method=case.sdk_method, request_path=case.request_path, started_at="2026-10-17T00:00:00Z",
        completed_at="2026-10-17T00:00:01Z")
    from scripts._conformance import CASE_CERTIFICATION
    cap, surface, operation, facets = CASE_CERTIFICATION[case.name]
    governance = tmp_path / "requirements.json"
    governance.write_text(json.dumps({"schema": "honua.protocol-certification-requirements/v1", "complete": True, "receipt_schema_min": "v2",
        "revision": "fixture-v2", "source_revisions": {"sdk-python": {"commit": "c" * 40}},
        "requirements": [{"capability_key": cap, "surface": surface, "operation": operation,
            "canonical_client": "Honua SDK Python", "client_lane": "sdk-python-certification",
            "maturity": "supported", "required_tier": "nightly", "client_version": "9.9.9",
            "fixture_revision": "geospatial-grpc@1.0.3", "scenario_facets": facets,
            "auth_policy_revision": CERTIFICATION_AUTH_POLICY_REVISION, "deployment_target": "local-docker",
            "contract_revision": "sdk-python-certification@" + "c" * 40,
            "client_package": {"filename": "honua_sdk-9.9.9-py3-none-any.whl", "sha256": "d" * 64, "source": "pypi"}}]}))
    monkeypatch.setenv("HONUA_CERTIFICATION_REQUIREMENTS_PATH", str(governance))
    with pytest.raises(ConformanceFixturesError, match="observed auth_policy_revision differs"):
        build_certification_fragment(FixtureBundle(Path("."), "1.0.3"), target, [(case, result)])
    rehearsal_governance = json.loads(governance.read_text())
    rehearsal_governance["requirements"][0]["auth_policy_revision"] = "development-grant-rehearsal-v1"
    governance.write_text(json.dumps(rehearsal_governance))
    fragment = build_certification_fragment(FixtureBundle(Path("."), "1.0.3"), target, [(case, result)])
    row = fragment["observations"][0]
    assert row["auth_policy_revision"] == "development-grant-rehearsal-v1"
    assert row["evidence_receipt"]["identity"]["auth_policy_revision"] == row["auth_policy_revision"]
    assert row["auth_policy_revision"] != CERTIFICATION_AUTH_POLICY_REVISION
    target = replace(target, entitlement_mode="unspecified")
    with pytest.raises(ConformanceFixturesError, match="explicit signed, licensing-disabled or development-grant"):
        build_certification_fragment(FixtureBundle(Path("."), "1.0.3"), target, [(case, result)])


def test_licensing_disabled_public_cells_match_the_governed_anonymous_policy(monkeypatch, tmp_path):
    import importlib.metadata
    from scripts._conformance import (CASE_CERTIFICATION, CERTIFICATION_AUTH_POLICY_REVISION, CaseResult,
                                      ConformanceTarget, FixtureBundle, build_cases, build_certification_fragment)
    monkeypatch.setattr(importlib.metadata, "version", lambda _: "9.9.9")
    target = ConformanceTarget(base_url="http://localhost:5000", server_commit="a" * 40,
        server_image_digest="sha256:" + "b" * 64, sdk_source_sha="c" * 40,
        sdk_wheel_filename="honua_sdk-9.9.9-py3-none-any.whl", sdk_wheel_sha256="d" * 64,
        sdk_wheel_source="pypi", evidence_uri="https://evidence.example/run/1",
        candidate_cut_at="2026-10-17T00:00:00Z", entitlement_mode="licensing-disabled")
    case = build_cases()[0]
    result = CaseResult(name=case.name, status="passed", fixture=case.fixture, message_type="message",
        sdk_method=case.sdk_method, request_path=case.request_path, started_at="2026-10-17T00:00:00Z",
        completed_at="2026-10-17T00:00:01Z")
    cap, surface, operation, facets = CASE_CERTIFICATION[case.name]
    governance = tmp_path / "requirements.json"
    governance.write_text(json.dumps({"schema": "honua.protocol-certification-requirements/v1", "complete": True, "receipt_schema_min": "v2",
        "revision": "fixture-v2", "source_revisions": {"sdk-python": {"commit": "c" * 40}},
        "requirements": [{"capability_key": cap, "surface": surface, "operation": operation,
            "canonical_client": "Honua SDK Python", "client_lane": "sdk-python-certification",
            "maturity": "supported", "required_tier": "nightly", "client_version": "9.9.9",
            "fixture_revision": "geospatial-grpc@1.0.3", "scenario_facets": facets,
            "auth_policy_revision": CERTIFICATION_AUTH_POLICY_REVISION, "deployment_target": "local-docker",
            "contract_revision": "sdk-python-certification@" + "c" * 40,
            "client_package": {"filename": "honua_sdk-9.9.9-py3-none-any.whl", "sha256": "d" * 64, "source": "pypi"}}]}))
    monkeypatch.setenv("HONUA_CERTIFICATION_REQUIREMENTS_PATH", str(governance))
    row = build_certification_fragment(FixtureBundle(Path("."), "1.0.3"), target, [(case, result)])["observations"][0]
    assert row["auth_policy_revision"] == CERTIFICATION_AUTH_POLICY_REVISION == "anonymous-public-v1"
