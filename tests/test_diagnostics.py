from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from honua_sdk import diagnostics


SCHEMA_DIRECTORY = Path(diagnostics.__file__).parent / "schemas"


def test_canonical_schema_and_provenance_are_byte_pinned() -> None:
    schema = (SCHEMA_DIRECTORY / "diagnostic-bundle.v1.json").read_bytes()
    provenance = json.loads((SCHEMA_DIRECTORY / "diagnostic-bundle.v1.provenance.json").read_text())

    assert len(schema) == diagnostics.DIAGNOSTIC_SCHEMA_BYTES == provenance["bytes"]
    assert hashlib.sha256(schema).hexdigest() == diagnostics.DIAGNOSTIC_SCHEMA_SHA256 == provenance["sha256"]
    assert provenance["canonicalUrl"] == diagnostics.DIAGNOSTIC_SCHEMA_URL
    assert provenance["sourceCommit"] == "0c990fbe8f519a00a57e26dab21cbb8f80d559ea"


def test_merged_conformance_corpus_matches_validator() -> None:
    corpus = SCHEMA_DIRECTORY / "diagnostic-bundle.v1.conformance"
    manifest = json.loads((corpus / "manifest.json").read_text())
    assert manifest["schemaSha256"] == diagnostics.DIAGNOSTIC_SCHEMA_SHA256

    for case in manifest["cases"]:
        payload = json.loads((corpus / case["path"]).read_text())
        errors = diagnostics.validate_diagnostic_bundle(payload)
        assert (not errors) is case["valid"], f"{case['id']}: {errors}"
        if not case["valid"]:
            assert case["expectedErrorContains"] in "\n".join(errors)


def test_validator_rejects_every_bounded_wire_shape_violation() -> None:
    base = _minimal_bundle({"method": "GET", "normalizedPath": "/healthz/ready"})
    invalid_values: list[object] = [
        None,
        {**base, "unknown": True},
        {**base, "contentClassification": "not-a-classification"},
        {**base, "consent": None},
        {**base, "consent": {"redactionAcknowledged": True}},
        {**base, "consent": {"redactionAcknowledged": "yes", "shareWithSupport": False}},
        {**base, "consent": {"redactionAcknowledged": True, "shareWithSupport": False, "extra": True}},
        {**base, "envelopes": "not-an-array"},
        {**base, "envelopes": []},
        {**base, "envelopes": [base["envelopes"][0]] * 51},
        {**base, "envelopes": [None]},
        _minimal_bundle({"normalizedPath": "/healthz/ready"}),
        _minimal_bundle({"method": None, "normalizedPath": "/healthz/ready"}),
        _minimal_bundle({"method": "G" * 17, "normalizedPath": "/healthz/ready"}),
        _minimal_bundle({"method": "GET", "normalizedPath": "/x", "statusCode": True}),
        _minimal_bundle({"method": "GET", "normalizedPath": "/x", "statusCode": 99}),
        _minimal_bundle({"method": "GET", "normalizedPath": "/x", "mediaType": "x" * 257}),
        _minimal_bundle({"method": "GET", "normalizedPath": "/x", "requestHeaders": "bad"}),
        _minimal_bundle(
            {"method": "GET", "normalizedPath": "/x", "requestHeaders": [{"name": "x", "value": "y"}] * 33}
        ),
        _minimal_bundle({"method": "GET", "normalizedPath": "/x", "requestHeaders": [None]}),
        _minimal_bundle(
            {"method": "GET", "normalizedPath": "/x", "requestHeaders": [{"name": "x", "value": "y", "x": 1}]}
        ),
        _minimal_bundle({"method": "GET", "normalizedPath": "/x", "requestHeaders": [{"name": "x"}]}),
        _minimal_bundle({"method": "GET", "normalizedPath": "/x", "responseBody": "bad"}),
        _minimal_bundle(
            {
                "method": "GET",
                "normalizedPath": "/x",
                "responseBody": {"originalByteSize": 0, "redactionApplied": False, "truncated": False, "extra": 1},
            }
        ),
        _minimal_bundle(
            {"method": "GET", "normalizedPath": "/x", "responseBody": {"redactionApplied": False, "truncated": False}}
        ),
        _minimal_bundle(
            {
                "method": "GET",
                "normalizedPath": "/x",
                "responseBody": {"originalByteSize": -1, "redactionApplied": "no", "truncated": False},
            }
        ),
    ]

    for value in invalid_values:
        assert diagnostics.validate_diagnostic_bundle(value), value
        with pytest.raises(diagnostics.DiagnosticValidationError):
            diagnostics.assert_diagnostic_bundle(value)


def test_create_bundle_rejects_invalid_required_inputs_and_accepts_safe_identity() -> None:
    exchange = {"method": "GET", "url": "https://example.test/healthz/ready"}
    invalid_calls = [
        {
            "content_classification": "invalid",
            "redaction_acknowledged": True,
            "share_with_support": False,
            "exchanges": [exchange],
        },
        {
            "content_classification": "internal",
            "redaction_acknowledged": "yes",
            "share_with_support": False,
            "exchanges": [exchange],
        },
        {
            "content_classification": "internal",
            "redaction_acknowledged": True,
            "share_with_support": False,
            "exchanges": [],
        },
        {
            "content_classification": "internal",
            "redaction_acknowledged": True,
            "share_with_support": False,
            "exchanges": [exchange] * 51,
        },
    ]
    for arguments in invalid_calls:
        with pytest.raises(diagnostics.DiagnosticSafetyError):
            diagnostics.create_diagnostic_bundle(**arguments)  # type: ignore[arg-type]

    bundle = diagnostics.create_diagnostic_bundle(
        content_classification="internal",
        redaction_acknowledged=True,
        share_with_support=False,
        granted_by="safe-automation",
        exchanges=[exchange],
    )
    assert bundle["consent"]["grantedBy"] == "safe-automation"


def test_emitter_omits_absent_optional_fields_and_validates() -> None:
    bundle = diagnostics.create_diagnostic_bundle(
        content_classification="internal",
        redaction_acknowledged=True,
        share_with_support=False,
        exchanges=[{"method": "GET", "url": "https://example.test/healthz/ready"}],
    )

    diagnostics.assert_diagnostic_bundle(bundle)
    assert "bundleId" not in bundle
    assert "grantedBy" not in bundle["consent"]
    envelope = bundle["envelopes"][0]
    assert envelope == {"method": "GET", "normalizedPath": "/healthz/ready"}
    assert all(value is not None for value in _walk_values(bundle))


def test_emitter_never_serializes_raw_headers_urls_or_bodies() -> None:
    secret = "super-secret-token-value"
    request_body = f'{{"apiKey":"{secret}","query":"customer parcel 42"}}'
    bundle = diagnostics.create_diagnostic_bundle(
        content_classification="secret-suspected",
        redaction_acknowledged=True,
        share_with_support=False,
        bundle_id="doctor-safe-1",
        exchanges=[
            {
                "method": "POST",
                "url": f"https://user:{secret}@example.test/rest/services/private/FeatureServer/42/query?token={secret}&f=json",
                "statusCode": 500,
                "mediaType": "application/problem+json",
                "requestHeaders": {
                    "Authorization": f"Bearer {secret}",
                    "Cookie": f"session={secret}",
                    "X-API-Key": secret,
                    "Content-Type": "application/json",
                    "X-Request-Id": "request-safe-1",
                    "X-Internal-Debug": secret,
                },
                "responseHeaders": {"Set-Cookie": secret, "Content-Type": "application/problem+json"},
                "requestBody": request_body,
                "responseBody": {"password": secret, "error": "failed"},
            }
        ],
    )

    serialized = json.dumps(bundle)
    assert secret not in serialized
    assert "customer parcel" not in serialized
    assert "Authorization" not in serialized
    assert "Cookie" not in serialized
    assert "X-API-Key" not in serialized
    assert "X-Internal-Debug" not in serialized
    assert "private" not in serialized
    envelope = bundle["envelopes"][0]
    assert envelope["normalizedPath"] == "/rest/services/{value}/FeatureServer/{value}/query?f={value}"
    assert envelope["requestHeaders"] == [
        {"name": "Content-Type", "value": "application/json"},
        {"name": "X-Request-Id", "value": "request-safe-1"},
    ]
    assert envelope["responseHeaders"] == [{"name": "Content-Type", "value": "application/problem+json"}]
    assert envelope["requestBody"] == {
        "contentSha256": hashlib.sha256(request_body.encode()).hexdigest(),
        "originalByteSize": len(request_body.encode()),
        "redactionApplied": True,
        "truncated": True,
    }
    assert "preview" not in envelope["requestBody"]


def test_unsafe_metadata_fails_before_bundle_creation() -> None:
    with pytest.raises(diagnostics.DiagnosticSafetyError):
        diagnostics.create_diagnostic_bundle(
            content_classification="internal",
            redaction_acknowledged=True,
            share_with_support=False,
            bundle_id="Bearer should-not-survive",
            exchanges=[{"method": "GET", "url": "https://example.test/healthz/ready"}],
        )


def test_sanitizer_rejects_bad_shapes_and_handles_header_sequences_and_empty_body() -> None:
    for exchange in ({"url": "https://example.test"}, {"method": "GET"}):
        with pytest.raises(diagnostics.DiagnosticSafetyError):
            diagnostics.sanitize_exchange(exchange)
    with pytest.raises(diagnostics.DiagnosticSafetyError):
        diagnostics.sanitize_headers("not-a-mapping")
    assert diagnostics.sanitize_headers(None) == []
    headers = diagnostics.sanitize_headers(
        {
            42: "ignored",
            "Accept": ["application/json", "application/problem+json"],
            "Content-Type": ["valid", 42],
            "X-Request-Id": "bad\r\nheader",
        }
    )
    assert headers == [{"name": "Accept", "value": "application/json, application/problem+json"}]
    assert diagnostics.sanitize_body(b"") == {
        "contentSha256": hashlib.sha256(b"").hexdigest(),
        "originalByteSize": 0,
        "redactionApplied": False,
        "truncated": False,
    }
    assert diagnostics.sanitize_body(bytearray(b"x"))["originalByteSize"] == 1
    with pytest.raises(diagnostics.DiagnosticSafetyError):
        diagnostics.sanitize_body({"not-json": object()})


def test_sanitizer_rejects_unsafe_and_overlong_paths_and_optional_types() -> None:
    for path in ("/safe/../secret", "/safe/%252e%252e/secret", "/safe\\secret"):
        with pytest.raises(diagnostics.DiagnosticSafetyError):
            diagnostics.normalize_diagnostic_path(path)
    with pytest.raises(diagnostics.DiagnosticSafetyError):
        diagnostics.normalize_diagnostic_path("/" + "/".join(f"segment-{index}" for index in range(500)))
    with pytest.raises(diagnostics.DiagnosticSafetyError):
        diagnostics.sanitize_exchange({"method": "GET", "url": "/healthz/ready", "statusCode": 600})
    with pytest.raises(diagnostics.DiagnosticSafetyError):
        diagnostics.sanitize_exchange({"method": "GET", "url": "/healthz/ready", "mediaType": 42})


def test_probe_is_anonymous_bounded_and_preserves_base_path() -> None:
    secret = "probe-response-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/honua/api/v1/services"
        assert dict(request.url.params) == {"limit": "1"}
        assert "authorization" not in request.headers
        assert "x-api-key" not in request.headers
        return httpx.Response(
            503,
            headers={"Content-Type": "application/problem+json", "X-Correlation-Id": "corr-1"},
            content=f'{{"token":"{secret}"}}',
        )

    probe = diagnostics.probe_capabilities(
        "https://example.test/honua",
        transport=httpx.MockTransport(handler),
    )
    bundle = diagnostics.create_diagnostic_bundle(
        content_classification="internal",
        redaction_acknowledged=True,
        share_with_support=False,
        exchanges=[probe],
    )

    assert secret not in json.dumps(bundle)
    envelope = bundle["envelopes"][0]
    assert envelope["statusCode"] == 503
    assert envelope["correlationId"] == "corr-1"
    assert envelope["normalizedPath"] == "/{value}/api/v1/services?limit={value}"


def test_probe_failure_returns_structured_minimal_envelope() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("contains sensitive network details", request=request)

    probe = diagnostics.probe_capabilities(
        "https://example.test",
        transport=httpx.MockTransport(handler),
    )
    envelope = diagnostics.sanitize_exchange(probe)

    assert envelope["method"] == "GET"
    assert envelope["normalizedPath"] == "/api/v1/services?limit={value}"
    assert "statusCode" not in envelope
    assert "sensitive" not in json.dumps(envelope)


def test_probe_over_budget_fails_closed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * (256 * 1024 + 1), request=request)

    with pytest.raises(diagnostics.DiagnosticSafetyError):
        diagnostics.probe_capabilities("https://example.test", transport=httpx.MockTransport(handler))


def test_body_over_canonical_budget_fails_closed() -> None:
    with pytest.raises(diagnostics.DiagnosticSafetyError):
        diagnostics.sanitize_body(b"x" * (25 * 1024 * 1024 + 1))


def test_unsafe_probe_origins_are_rejected() -> None:
    for value in (
        "http://example.test",
        "https://user:password@example.test",
        "https://example.test?token=secret",
        "file:///tmp/server",
    ):
        with pytest.raises(diagnostics.DiagnosticSafetyError):
            diagnostics.safe_probe_base_url(value)


def test_replay_performs_one_anonymous_read_and_returns_new_sanitized_bundle() -> None:
    bundle = diagnostics.create_diagnostic_bundle(
        content_classification="internal",
        redaction_acknowledged=True,
        share_with_support=False,
        bundle_id="doctor-replay-safe",
        granted_by="safe-automation",
        exchanges=[{"method": "GET", "url": "https://source.test/healthz/ready"}],
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, headers={"Content-Type": "application/json"}, content=b'{"ready":true}')

    replayed = diagnostics.replay_diagnostic_bundle(
        bundle,
        "https://target.test/honua",
        transport=httpx.MockTransport(handler),
    )

    diagnostics.assert_diagnostic_bundle(replayed)
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/honua/healthz/ready"
    assert not requests[0].url.query
    assert "authorization" not in requests[0].headers
    assert "x-api-key" not in requests[0].headers
    assert b'"ready":true' not in json.dumps(replayed).encode()


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_replay_refuses_mutations_before_network(method: str) -> None:
    bundle = diagnostics.create_diagnostic_bundle(
        content_classification="internal",
        redaction_acknowledged=True,
        share_with_support=False,
        exchanges=[{"method": method, "url": "https://source.test/api/v1/services"}],
    )
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    with pytest.raises(diagnostics.DiagnosticSafetyError):
        diagnostics.replay_diagnostic_bundle(
            bundle,
            "https://target.test",
            transport=httpx.MockTransport(handler),
        )
    assert called is False


def test_replay_refuses_placeholder_unsafe_header_and_hash_drift_before_network() -> None:
    unsafe_bundles = [
        _minimal_bundle({"method": "GET", "normalizedPath": "/rest/services/{value}/FeatureServer"}),
        _minimal_bundle({"method": "GET", "normalizedPath": "/admin/delete-all"}),
        _minimal_bundle(
            {
                "method": "GET",
                "normalizedPath": "/healthz/ready",
                "requestHeaders": [{"name": "Authorization", "value": "Bearer credential"}],
            }
        ),
        _minimal_bundle(
            {
                "method": "GET",
                "normalizedPath": "/healthz/ready",
                "responseBody": {
                    "preview": "safe-looking",
                    "contentSha256": "0" * 64,
                    "originalByteSize": 12,
                    "redactionApplied": False,
                    "truncated": False,
                },
            }
        ),
    ]
    called = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200)

    for bundle in unsafe_bundles:
        diagnostics.assert_diagnostic_bundle(bundle)
        with pytest.raises(diagnostics.DiagnosticSafetyError):
            diagnostics.replay_diagnostic_bundle(
                bundle,
                "https://target.test",
                transport=httpx.MockTransport(handler),
            )
    assert called is False


def test_replay_refuses_request_body_secret_preview_network_failure_and_over_budget() -> None:
    unsafe = [
        _minimal_bundle(
            {
                "method": "GET",
                "normalizedPath": "/healthz/ready",
                "requestBody": {"originalByteSize": 0, "redactionApplied": False, "truncated": False},
            }
        ),
        _minimal_bundle(
            {
                "method": "GET",
                "normalizedPath": "/healthz/ready",
                "responseBody": {
                    "preview": "Bearer credential",
                    "originalByteSize": 17,
                    "redactionApplied": True,
                    "truncated": True,
                },
            }
        ),
    ]
    for bundle in unsafe:
        with pytest.raises(diagnostics.DiagnosticSafetyError):
            diagnostics.replay_diagnostic_bundle(
                bundle, "https://target.test", transport=httpx.MockTransport(lambda _: httpx.Response(200))
            )

    safe = _minimal_bundle({"method": "GET", "normalizedPath": "/healthz/ready"})

    def failed(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network detail", request=request)

    with pytest.raises(diagnostics.DiagnosticSafetyError):
        diagnostics.replay_diagnostic_bundle(safe, "https://target.test", transport=httpx.MockTransport(failed))
    with pytest.raises(diagnostics.DiagnosticSafetyError):
        diagnostics.replay_diagnostic_bundle(
            safe,
            "https://target.test",
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b"x" * (256 * 1024 + 1), request=request)
            ),
        )


def _walk_values(value: object) -> list[object]:
    if isinstance(value, dict):
        return [item for nested in value.values() for item in _walk_values(nested)]
    if isinstance(value, list):
        return [item for nested in value for item in _walk_values(nested)]
    return [value]


def _minimal_bundle(envelope: dict[str, Any]) -> dict[str, Any]:
    return {
        "schemaVersion": "1.0",
        "contentClassification": "internal",
        "consent": {"redactionAcknowledged": True, "shareWithSupport": False},
        "envelopes": [envelope],
    }
