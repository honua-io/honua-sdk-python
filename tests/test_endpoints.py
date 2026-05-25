"""Tests for the pure endpoint helpers in ``honua_sdk._endpoints``.

These helpers are pure functions (no I/O) so they're trivially testable
in isolation. They are exercised by the integration tests through the
sync/async clients as well; this module asserts their behaviour
directly so regressions surface independently of the client code.
"""

from __future__ import annotations

import re

import pytest

from honua_sdk import _endpoints


# ---------------------------------------------------------------------------
# Catalog / capabilities
# ---------------------------------------------------------------------------


def test_build_readiness_request_targets_healthz() -> None:
    prep = _endpoints.build_readiness_request()
    assert prep.method == "GET"
    assert prep.path == "/healthz/ready"
    assert prep.params is None
    assert prep.json is None


def test_build_capabilities_request_targets_v1_capabilities() -> None:
    prep = _endpoints.build_capabilities_request()
    assert prep.method == "GET"
    assert prep.path == "/api/v1/capabilities"


def test_build_list_services_request_passes_response_format() -> None:
    prep = _endpoints.build_list_services_request(response_format="pjson")
    assert prep.method == "GET"
    assert prep.path == "/rest/services"
    assert prep.params == {"f": "pjson"}


def test_parse_service_summaries_handles_non_list_payload() -> None:
    assert _endpoints.parse_service_summaries({}) == []
    assert _endpoints.parse_service_summaries({"services": "not a list"}) == []


def test_parse_service_summaries_returns_typed_objects() -> None:
    payload = {
        "services": [
            {"name": "svc-a", "type": "FeatureServer"},
            {"name": "svc-b", "type": "MapServer"},
            "ignored-non-mapping-entry",
        ]
    }
    summaries = _endpoints.parse_service_summaries(payload)
    assert [s.name for s in summaries] == ["svc-a", "svc-b"]


# ---------------------------------------------------------------------------
# FeatureServer query / applyEdits
# ---------------------------------------------------------------------------


def test_build_query_features_encodes_service_id_and_defaults() -> None:
    prep = _endpoints.build_query_features_request("svc with space", 7)
    assert prep.method == "GET"
    assert prep.path == "/rest/services/svc%20with%20space/FeatureServer/7/query"
    params = dict(prep.params or {})
    assert params == {
        "f": "json",
        "where": "1=1",
        "outFields": "*",
        "returnGeometry": "true",
    }


def test_build_query_features_joins_field_sequence_and_merges_extras() -> None:
    prep = _endpoints.build_query_features_request(
        "svc",
        0,
        where="OBJECTID < 10",
        out_fields=["NAME", "POPULATION"],
        return_geometry=False,
        extra_params={"resultOffset": 100, "resultRecordCount": 50},
    )
    params = dict(prep.params or {})
    assert params["outFields"] == "NAME,POPULATION"
    assert params["returnGeometry"] == "false"
    assert params["resultOffset"] == 100
    assert params["resultRecordCount"] == 50


def test_build_apply_edits_builds_payload_and_forwards_headers() -> None:
    headers = {"Idempotency-Key": "abc-123"}
    prep = _endpoints.build_apply_edits_request(
        "svc/name",
        3,
        adds=[{"attributes": {"x": 1}}],
        deletes=[7, 8, 9],
        rollback_on_failure=False,
        headers=headers,
    )
    assert prep.method == "POST"
    assert prep.path == "/rest/services/svc%2Fname/FeatureServer/3/applyEdits"
    assert prep.headers == headers
    body = dict(prep.json or {})
    assert body["f"] == "json"
    assert body["rollbackOnFailure"] is False
    assert body["adds"] == [{"attributes": {"x": 1}}]
    assert body["deletes"] == [7, 8, 9]
    assert "updates" not in body


def test_build_apply_edits_passes_deletes_string_verbatim() -> None:
    prep = _endpoints.build_apply_edits_request(
        "svc", 0, deletes="1,2,3"
    )
    assert prep.json is not None and prep.json["deletes"] == "1,2,3"


# ---------------------------------------------------------------------------
# Paging helpers (pure)
# ---------------------------------------------------------------------------


def test_validate_paging_rejects_non_positive_values() -> None:
    with pytest.raises(ValueError, match="page_size"):
        _endpoints.validate_paging(0, 5)
    with pytest.raises(ValueError, match="max_pages"):
        _endpoints.validate_paging(10, 0)


def test_initial_offset_honours_result_offset() -> None:
    assert _endpoints.initial_offset(None) == 0
    assert _endpoints.initial_offset({}) == 0
    assert _endpoints.initial_offset({"resultOffset": 42}) == 42


def test_page_record_count_clamps_by_remaining() -> None:
    assert _endpoints.page_record_count(1000, None) == 1000
    assert _endpoints.page_record_count(1000, 50) == 50
    assert _endpoints.page_record_count(1000, 5000) == 1000


def test_page_extra_params_overrides_paging_fields() -> None:
    merged = _endpoints.page_extra_params(
        {"resultOffset": 999, "extra": "value"},
        offset=10,
        record_count=20,
    )
    assert merged["resultOffset"] == 10
    assert merged["resultRecordCount"] == 20
    assert merged["extra"] == "value"


# ---------------------------------------------------------------------------
# Idempotency / JSON parsing
# ---------------------------------------------------------------------------


def test_build_idempotency_headers_explicit_key_wins() -> None:
    headers = _endpoints.build_idempotency_headers(
        "explicit-key", retry_methods=frozenset({"GET", "POST"})
    )
    assert headers == {"Idempotency-Key": "explicit-key"}


def test_build_idempotency_headers_autogenerates_when_post_opted_in() -> None:
    headers = _endpoints.build_idempotency_headers(
        None, retry_methods=frozenset({"GET", "POST"})
    )
    assert headers is not None
    assert re.fullmatch(r"[0-9a-f]{32}", headers["Idempotency-Key"]) is not None


def test_build_idempotency_headers_returns_none_when_no_post_retry() -> None:
    headers = _endpoints.build_idempotency_headers(
        None, retry_methods=frozenset({"GET"})
    )
    assert headers is None


class _StubResponse:
    """Minimal stand-in mimicking the bits of httpx.Response we use."""

    def __init__(self, *, content: bytes, payload: object = None, text: str = "") -> None:
        self.content = content
        self._payload = payload
        self.text = text

    def json(self) -> object:
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def test_parse_json_response_body_returns_empty_for_empty_body() -> None:
    assert _endpoints.parse_json_response_body(_StubResponse(content=b"")) == {}


def test_parse_json_response_body_wraps_non_mapping_payload() -> None:
    response = _StubResponse(content=b"[1,2]", payload=[1, 2])
    assert _endpoints.parse_json_response_body(response) == {"data": [1, 2]}


def test_parse_json_response_body_returns_raw_text_for_non_json() -> None:
    response = _StubResponse(content=b"not-json", payload=ValueError("bad json"), text="raw-text")
    assert _endpoints.parse_json_response_body(response) == {"raw": "raw-text"}


def test_parse_json_response_body_returns_mapping_copy() -> None:
    payload = {"a": 1}
    response = _StubResponse(content=b"{}", payload=payload)
    parsed = _endpoints.parse_json_response_body(response)
    assert parsed == {"a": 1}
    parsed["a"] = 99
    assert payload == {"a": 1}  # original not mutated
