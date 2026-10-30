from __future__ import annotations

import base64
import copy
from dataclasses import replace
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts._conformance_entitlement import disabled_status, observe, profile, signed_status

NOW = datetime(2026, 10, 17, tzinfo=timezone.utc)
STATUS = {"success": True, "data": {"mode": "enabled", "isValid": True, "validationState": "Valid",
          "licenseId": "signed-license-identifier", "issuedAt": "2026-10-01T00:00:00Z",
          "expiresAt": "2027-10-01T00:00:00Z", "entitlements": [{"key": "editing.featureserver-edits", "isActive": True}]}}


def test_rehearsal_grant_is_explicit_and_development_only():
    assert profile("pr", "pull_request", "Development", "") == {
        "mode": "development-grant", "devGrantEdition": "Enterprise", "licensingMode": "Enabled"}
    for tier, event, environment in [("pr", "pull_request", "Production"), ("unknown", "local", "Development")]:
        with pytest.raises(ValueError):
            profile(tier, event, environment, "")


def test_release_boots_disabled_without_reading_a_license_envelope():
    for content in ("", "not JSON", "{}", '{"unverified":true}'):
        assert profile("release", "workflow_dispatch", "Development", content) == {
            "mode": "disabled", "devGrantEdition": "", "licensingMode": "Disabled"}
    with pytest.raises(ValueError, match="explicit governed dispatch"):
        profile("release", "pull_request", "Development", "")
    with pytest.raises(AssertionError, match="signed non-development"):
        signed_status({"success": True, "data": {}}, now=NOW)


def test_disabled_status_requires_the_2026_1_runtime_and_the_edit_entitlement():
    status = {"success": True, "data": {"mode": "disabled", "isValid": True, "validationState": "Disabled",
              "licenseId": None, "entitlements": [{"key": "editing.featureserver-edits", "isActive": True}]}}
    proof = disabled_status(status, now=NOW)
    assert proof["mode"] == "disabled" and proof["status"] == "active"
    assert proof["verification"] == "candidate-disabled-license-status-v1"
    assert "license_fingerprint" not in proof
    for field, value in (("mode", "enabled"), ("isValid", False), ("validationState", "Valid"),
                         ("licenseId", "signed-license-identifier"), ("entitlements", [])):
        refused = copy.deepcopy(status)
        refused["data"][field] = value
        with pytest.raises(AssertionError):
            disabled_status(refused, now=NOW)


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


def test_release_probe_refuses_rehearsal_before_any_network():
    with pytest.raises(AssertionError, match="refuses rehearsal"):
        observe(SimpleNamespace(certification_tier="release", entitlement_mode="development-grant"))


def test_workflow_boots_licensing_mode_from_the_profile_and_reads_no_license_secret():
    workflow = (Path(__file__).parents[1] / ".github/workflows/conformance.yml").read_text()
    assert 'from scripts._conformance_entitlement import profile' in workflow
    assert 'CERTIFICATION_EVENT: ${{ github.event_name }}' in workflow
    assert "HONUA_CERTIFICATION_LICENSE_CONTENT" not in workflow
    assert 'Licensing__LicenseContent' not in workflow
    assert 'Licensing__DevGrantEdition: "${dev_grant}"' in workflow
    assert "Licensing__Mode: ${licensing_mode}" in workflow
    assert '.licensingMode | select(. == "Disabled" or . == "Enabled")' in workflow


def test_release_fragment_rejects_rehearsal_and_stale_entitlement_receipts():
    from scripts._conformance import validate_release_certification_fragment
    record = {"case": "feature_apply_edits_roundtrip", "entitlement_mode": "disabled", "receipt": {
        "status": "passed", "started_at": "2026-10-17T00:00:00Z", "completed_at": "2026-10-17T00:00:01Z",
        "details": {"entitlement": disabled_status({"success": True, "data": {
            "mode": "disabled", "isValid": True, "validationState": "Disabled", "licenseId": None,
            "entitlements": [{"key": "editing.featureserver-edits", "isActive": True}]}}, now=NOW)}}}
    def fragment(value):
        return {"requirements_revision": "fixture-v2", "candidate": {"cut_at": "2026-10-17T00:00:00Z"}, "operation_scope": {"complete": True,
            "required_operations": [{"surface": "s", "operation": "edit"}]}, "observations": [{"surface": "s", "operation": "edit", "result": "pass", "maturity": "supported", "required_tier": "release",
            "evidence_receipt": {"schema": "honua.certification-evidence-receipt/v2", "identity": {"candidate_cut_at": "2026-10-17T00:00:00Z", "maturity": "supported", "required_tier": "release", "requirements_revision": "fixture-v2"}, "payload_base64": base64.b64encode(json.dumps([value]).encode()).decode()}}]}
    validate_release_certification_fragment(fragment(record))
    for mode in ("development-grant", "unspecified", "signed"):
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
    target = replace(target, entitlement_mode="disabled")
    disabled_governance = json.loads(governance.read_text())
    disabled_governance["requirements"][0]["auth_policy_revision"] = CERTIFICATION_AUTH_POLICY_REVISION
    governance.write_text(json.dumps(disabled_governance))
    fragment = build_certification_fragment(FixtureBundle(Path("."), "1.0.3"), target, [(case, result)])
    assert fragment["observations"][0]["auth_policy_revision"] == CERTIFICATION_AUTH_POLICY_REVISION
    target = replace(target, entitlement_mode="unspecified")
    with pytest.raises(ConformanceFixturesError, match="explicit disabled, signed, or development-grant"):
        build_certification_fragment(FixtureBundle(Path("."), "1.0.3"), target, [(case, result)])
