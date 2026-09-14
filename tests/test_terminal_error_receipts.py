from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import grpc
import httpx
import pytest

from honua_sdk import FailureKind, HonuaGrpcError
from honua_sdk._http import _build_geoservices_error, _build_http_error


CONTRACT = json.loads(
    (Path(__file__).parent / "fixtures" / "terminal-error-receipts.v1.json").read_text(encoding="utf-8")
)
FAILURES = CONTRACT["failureClasses"]


def test_contract_has_exactly_40_global_and_10_python_cells() -> None:
    assert CONTRACT["expectedCellCount"] == 40
    assert len(CONTRACT["sdkPaths"]) * len(FAILURES) == 40
    assert len([path for path in CONTRACT["sdkPaths"] if path["sdk"] == "python"]) * len(FAILURES) == 10


@pytest.mark.parametrize("failure", FAILURES, ids=[failure["id"] for failure in FAILURES])
def test_http_and_geoservices_terminal_path_preserves_receipt(failure: dict[str, Any]) -> None:
    correlation_id = "contract-correlation-id"
    headers = {
        "X-Correlation-ID": correlation_id,
        "Retry-After": str(failure.get("retryAfterSeconds", "")),
        "Authorization": "secret",
    }
    body = {
        "kind": failure["kind"],
        "code": failure["code"],
        "retryable": failure["retryable"],
        "retryAfterSeconds": failure.get("retryAfterSeconds"),
        "correlationId": correlation_id,
        "errors": failure.get("errors"),
    }
    response = httpx.Response(failure["httpStatus"], headers=headers, json=body)
    http_error = _build_http_error(
        status_code=response.status_code,
        message=failure["detail"],
        body=body,
        response=response,
    )

    geo_body = {
        "error": {
            "code": failure["geoServicesCode"],
            "details": [f"Correlation ID: {correlation_id}"],
            "retryable": failure["retryable"],
            "retryAfterSeconds": failure.get("retryAfterSeconds"),
            "message": failure["detail"],
        }
    }
    geo_response = httpx.Response(200, headers=headers, json=geo_body)
    geo_error = _build_geoservices_error(
        error_code=failure["geoServicesCode"],
        message=failure["detail"],
        body=geo_body,
        response=geo_response,
    )

    _assert_receipt(http_error.receipt, failure, transport_status=failure["httpStatus"], protocol_code=None)
    _assert_receipt(
        geo_error.receipt,
        failure,
        transport_status=200,
        protocol_code=str(failure["geoServicesCode"]),
        expected_field_errors=0,
    )
    assert "authorization" not in http_error.protocol_metadata.initial


@pytest.mark.parametrize("failure", FAILURES, ids=[failure["id"] for failure in FAILURES])
def test_grpc_terminal_path_preserves_initial_and_trailing_metadata(failure: dict[str, Any]) -> None:
    status = getattr(grpc.StatusCode, failure["grpcStatus"]["name"])
    trailing: dict[str, Any] = {
        "honua-correlation-id": "contract-correlation-id",
        "honua-error-kind": failure["kind"],
        "honua-error-code": failure["code"],
        "honua-retryable": str(failure["retryable"]).lower(),
    }
    if retry_after := failure.get("retryAfterSeconds"):
        trailing["retry-after"] = str(retry_after)
    if errors := failure.get("errors"):
        trailing["honua-error-details"] = json.dumps(errors)
    error = HonuaGrpcError(
        status,
        failure["detail"],
        initial_metadata={"x-test-initial": failure["id"], "authorization": "secret"},
        trailing_metadata=trailing,
    )

    _assert_receipt(
        error.receipt,
        failure,
        transport_status=None,
        protocol_code=str(failure["grpcStatus"]["number"]),
    )
    assert error.protocol_metadata.initial
    assert error.protocol_metadata.trailing
    assert "authorization" not in error.protocol_metadata.initial


def test_unauthenticated_remains_distinct_from_permission_denied() -> None:
    auth = FAILURES[0]["authenticationRequired"]
    response = httpx.Response(auth["httpStatus"], json={})
    error = _build_http_error(
        status_code=response.status_code,
        message="Authentication required",
        body={},
        response=response,
    )

    assert error.failure_kind is FailureKind.AUTHENTICATION
    assert error.machine_code == "authentication_required"
    assert error.failure_kind is not FailureKind.AUTHORIZATION


@pytest.mark.parametrize("error_code", [498, 499])
def test_geoservices_token_codes_are_authentication_failures(error_code: int) -> None:
    body = {"error": {"code": error_code, "message": "Token required"}}
    response = httpx.Response(200, headers={"X-Request-ID": "geo-token"}, json=body)

    error = _build_geoservices_error(
        error_code=error_code,
        message="Token required",
        body=body,
        response=response,
    )

    assert error.receipt.transport_status == 200
    assert error.receipt.protocol_code == str(error_code)
    assert error.receipt.kind is FailureKind.AUTHENTICATION
    assert error.receipt.code == "authentication_required"
    assert error.receipt.correlation_id == "geo-token"


def _assert_receipt(
    receipt: Any,
    failure: dict[str, Any],
    *,
    transport_status: int | None,
    protocol_code: str | None,
    expected_field_errors: int | None = None,
) -> None:
    assert receipt.transport_status == transport_status
    assert receipt.protocol_code == protocol_code
    assert receipt.kind.value == failure["kind"]
    assert receipt.code == failure["code"]
    assert receipt.retryable is failure["retryable"]
    assert receipt.retry_after_seconds == failure.get("retryAfterSeconds")
    assert receipt.correlation_id == "contract-correlation-id"
    assert len(receipt.field_errors) == (
        len(failure.get("errors") or []) if expected_field_errors is None else expected_field_errors
    )
