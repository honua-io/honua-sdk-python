from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import grpc
import pytest

from honua_sdk import HonuaGrpcError
from honua_sdk.grpc import Feature, FeaturePage, QueryFeaturesResponse, SpatialReference
from honua_sdk.models import ApplyEditsResult
from scripts._conformance import ConformanceFixturesError, ConformanceTarget, FixtureBundle, build_cases
from scripts import _conformance_operations as operations


@pytest.fixture
def bundle(tmp_path: Path) -> FixtureBundle:
    directory = tmp_path / "fixtures"
    directory.mkdir()
    (tmp_path / "golden").mkdir()
    baseline = [
        {"id": "7", "attributes": {"NAME": {"stringValue": "Alamo"}, "AREA": {"doubleValue": 500.0}},
         "geometry": {"point": {"x": -122.4346, "y": 37.7764}}},
        {"id": "42", "attributes": {"NAME": {"stringValue": "Golden Gate"}, "AREA": {"doubleValue": 44340000.0}},
         "geometry": {"point": {"x": -122.486, "y": 37.769}}},
    ]
    payloads = {
        "feature_apply_edits_missing_target_verify_response": {"features": baseline},
        "feature_apply_edits_missing_target_request": {
            "updates": [{"id": "42", "attributes": {"AREA": {"doubleValue": 1.0}}}],
            "deletes": ["7", "8"], "rollbackOnFailure": True,
        },
        "feature_apply_edits_request": {
            "adds": [{"attributes": {"NAME": {"stringValue": "Dolores"}, "AREA": {"doubleValue": 660000.0}},
                      "geometry": {"point": {"x": -122.4271, "y": 37.7596}}}],
            "updates": [{"id": "42", "attributes": {"AREA": {"doubleValue": 44350000.0}}}],
            "deletes": ["7"], "rollbackOnFailure": True,
        },
        "feature_apply_edits_missing_target_status": {"name": "NOT_FOUND", "code": 5},
    }
    for name in ("feature_query", "feature_query_stream"):
        payloads[f"{name}_invalid_request"] = {"serviceId": "no-such-service"}
        payloads[f"{name}_invalid_status"] = {"name": "NOT_FOUND", "code": 5}
    for name, payload in payloads.items():
        (directory / f"{name}.json").write_text(json.dumps(payload))
    return FixtureBundle(tmp_path, "1.0.5")


class EditServer:
    """Oracle fault controls only; live certification runs the real installed package against Docker."""

    def __init__(self, fault=None):
        self.rows = {}
        self.next_id = 10
        self.calls = []
        self.fault = fault
        self.negative_seen = False

    def query_features(self, service, layer, *, where, **kwargs):
        if where.startswith("objectid ="):
            rows = [self.rows[int(where.split("=")[1])]] if int(where.split("=")[1]) in self.rows else []
        else:
            marker = where.split("'")[1]
            rows = [deepcopy(row) for row in self.rows.values() if row["attributes"]["description"] == marker]
        if self.fault == "readback" and self.negative_seen and rows:
            rows[0]["attributes"]["ratio"] = -1
        return {"features": rows, "exceededTransferLimit": False}

    def apply_edits_result(self, service, layer, *, adds=(), updates=(), deletes=(), rollback_on_failure):
        assert rollback_on_failure is True
        self.calls.append((len(adds), len(updates), len(deletes)))
        failed = any(identifier not in self.rows for identifier in deletes)
        if failed:
            self.negative_seen = True
            if self.fault == "committed-negative":
                self.rows[updates[0]["attributes"]["objectid"]]["attributes"].update(updates[0]["attributes"])
            return ApplyEditsResult.from_dict({
                "updateResults": [{"success": False, "error": {"code": 1000}} for _ in updates],
                "deleteResults": [{"success": False, "objectId": identifier, "error": {"code": 1003 if identifier not in self.rows else 1000}}
                                  for identifier in deletes],
            })
        response = {"addResults": [], "updateResults": [], "deleteResults": []}
        for feature in adds:
            identifier = self.next_id
            self.next_id += 1
            self.rows[identifier] = deepcopy(feature)
            self.rows[identifier]["attributes"]["objectid"] = identifier
            response["addResults"].append({"success": True, "objectId": identifier})
        for update in updates:
            identifier = update["attributes"]["objectid"]
            self.rows[identifier]["attributes"].update(update["attributes"])
            response["updateResults"].append({"success": True, "objectId": identifier})
        for identifier in deletes:
            if self.fault != "cleanup" or updates:
                del self.rows[identifier]
            response["deleteResults"].append({"success": True, "objectId": identifier})
        if self.fault == "partial" and adds:
            response["addResults"] = []
        return ApplyEditsResult.from_dict(response)


def test_apply_edits_runs_real_operation_shape_and_checks_both_readbacks(bundle):
    client = EditServer()
    result = operations.apply_edits(client, ConformanceTarget("http://localhost:5000"), bundle)
    assert result["positive_operations"] == ["add", "update", "delete"]
    assert result["negative_code"] == 1003
    assert result["rollback_readback"] and result["positive_readback"] and result["cleanup_readback"]
    assert client.calls == [(2, 0, 0), (0, 1, 2), (1, 1, 1), (0, 0, 2)]
    assert not client.rows


@pytest.mark.parametrize("fault", ["partial", "committed-negative", "readback", "cleanup"])
def test_apply_edits_rejects_partial_lying_or_unreadable_mutation_evidence(bundle, fault):
    with pytest.raises(AssertionError):
        operations.apply_edits(EditServer(fault), ConformanceTarget("http://localhost:5000"), bundle)


@pytest.mark.parametrize("endpoint", [None, "another-host:5001", "localhost", "localhost:0", "localhost:65536",
                                      "user:password@localhost:5001", "localhost:5001/path", "localhost:5001?x=1"])
def test_grpc_listener_must_be_explicit_same_candidate_authority(endpoint):
    with pytest.raises(ConformanceFixturesError):
        ConformanceTarget("http://localhost:5000", grpc_target=endpoint).grpc_base_url()


class GrpcConnection:
    def __init__(self, *, fault=None):
        self.requests = []
        self.fault = fault

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def response(self, request):
        self.requests.append(request)
        if request.service_id == "no-such-service":
            if self.fault == "missing-succeeds":
                return QueryFeaturesResponse()
            raise HonuaGrpcError(grpc.StatusCode.PERMISSION_DENIED if self.fault == "wrong-negative" else grpc.StatusCode.NOT_FOUND,
                                 "Service unavailable")
        features = [Feature(id=1, attributes={"name": "alpha", "count": 1}, geometry={"x": -122.49, "y": 37.71}),
                    Feature(id=2, attributes={"name": "beta", "count": 2}, geometry={"x": -122.475, "y": 37.72})]
        if self.fault == "wrong-seed":
            features[0].geometry["x"] = 0
        if self.fault == "empty":
            features = []
        return QueryFeaturesResponse(object_id_field_name="objectid", features=features, spatial_reference=SpatialReference(wkid=4326))

    def query_features(self, request):
        return self.response(request)

    def query_features_stream(self, request):
        response = self.response(request)
        yield FeaturePage(object_id_field_name=response.object_id_field_name, features=response.features,
                          spatial_reference=response.spatial_reference, is_last_page=self.fault != "unterminated")


@pytest.mark.parametrize("runner", [operations.grpc_query, operations.grpc_stream])
def test_grpc_producers_issue_public_unary_or_stream_and_typed_negative(bundle, runner):
    connection = GrpcConnection()
    targets = []

    def factory(*, target):
        targets.append(target)
        return connection

    result = runner(SimpleNamespace(grpc=factory), ConformanceTarget("http://localhost:5000", grpc_target="localhost:5001"), bundle)
    assert targets == ["localhost:5001"]
    assert result["observed_names"] == ["alpha", "beta"]
    assert result["negative_status"] == "NOT_FOUND"
    assert [request.service_id for request in connection.requests] == ["test_service", "no-such-service"]
    assert connection.requests[0].return_geometry and connection.requests[0].result_record_count == 2


@pytest.mark.parametrize("runner", [operations.grpc_query, operations.grpc_stream])
@pytest.mark.parametrize("fault", ["wrong-seed", "empty", "wrong-negative", "missing-succeeds"])
def test_grpc_producer_rejects_irrelevant_partial_or_wrong_negative_evidence(bundle, runner, fault):
    client = SimpleNamespace(grpc=lambda **_: GrpcConnection(fault=fault))
    with pytest.raises(AssertionError):
        runner(client, ConformanceTarget("http://localhost:5000", grpc_target="localhost:5001"), bundle)


def test_stream_requires_a_terminal_page(bundle):
    client = SimpleNamespace(grpc=lambda **_: GrpcConnection(fault="unterminated"))
    with pytest.raises(AssertionError, match="terminal"):
        operations.grpc_stream(client, ConformanceTarget("http://localhost:5000", grpc_target="localhost:5001"), bundle)


def test_new_operations_are_required_live_cases_without_known_gap_exemptions():
    cases = {case.name: case for case in build_cases()}
    for name in ("grpc_query_features", "grpc_query_features_stream", "feature_apply_edits_roundtrip"):
        assert cases[name].known_gap_issue is None
        assert cases[name].runner.__module__ == operations.__name__
