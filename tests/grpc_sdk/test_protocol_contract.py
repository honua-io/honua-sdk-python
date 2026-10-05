"""Canonical protocol invariants, independent of same-stub mock responses."""
from __future__ import annotations

import pickle
from unittest.mock import MagicMock

import pytest
from google.protobuf.descriptor import FieldDescriptor

from honua_sdk.grpc import QueryFeaturesRequest
from honua_sdk.grpc._generated.geospatial.v1 import feature_service_pb2 as pb2
from honua_sdk.grpc._generated.geospatial.v1 import feature_service_pb2_grpc
from honua_sdk.grpc._proto_adapter import to_proto_request


def test_canonical_feature_service_contract() -> None:
    assert pb2.DESCRIPTOR.package == "geospatial.v1"
    assert list(pb2.DESCRIPTOR.services_by_name["FeatureService"].methods_by_name) == [
        "QueryFeatures", "QueryFeaturesStream", "ApplyEdits",
    ]
    fields = pb2.QueryFeaturesRequest.DESCRIPTOR.fields_by_name
    assert "result_offset" not in fields
    assert "result_record_count" not in fields
    assert fields["result_offset_long"].number == 20
    assert fields["result_record_count_long"].number == 21
    assert fields["result_offset_long"].type == FieldDescriptor.TYPE_INT64
    assert fields["result_record_count_long"].type == FieldDescriptor.TYPE_INT64


def test_stub_dispatches_canonical_routes() -> None:
    channel = MagicMock()
    feature_service_pb2_grpc.FeatureServiceStub(channel)
    assert [call.args[0] for call in channel.unary_unary.call_args_list] == [
        "/geospatial.v1.FeatureService/QueryFeatures", "/geospatial.v1.FeatureService/ApplyEdits",
    ]
    assert channel.unary_stream.call_args.args[0] == "/geospatial.v1.FeatureService/QueryFeaturesStream"


@pytest.mark.parametrize("value", [0, 2**31 + 1])
def test_public_pagination_uses_int64_wire_fields(value: int) -> None:
    request = to_proto_request(QueryFeaturesRequest(
        service_id="test_service", layer_id=0, result_offset=value, result_record_count=value,
    ))
    decoded = pb2.QueryFeaturesRequest.FromString(request.SerializeToString())
    assert decoded.result_offset_long == value
    assert decoded.result_record_count_long == value


def test_generated_messages_use_installable_module_names() -> None:
    request = pb2.QueryFeaturesRequest(service_id="test_service", layer_id=0)
    assert pickle.loads(pickle.dumps(request)) == request  # noqa: S301 -- local trusted message
