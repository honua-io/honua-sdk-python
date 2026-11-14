"""Explicitly gated write roundtrip against a compatible native gRPC server."""
from __future__ import annotations

import os

import grpc
import pytest

from honua_sdk.grpc import ApplyEditsRequest, Feature, HonuaGrpcClient, build_grpc_metadata

pytestmark = pytest.mark.integration


def test_native_edit_roundtrip():
    target = os.environ.get("HONUA_GRPC_EDIT_TARGET")
    service = os.environ.get("HONUA_GRPC_EDIT_SERVICE")
    key = os.environ.get("HONUA_GRPC_EDIT_API_KEY")
    if not target or not service or not key:
        pytest.skip("set HONUA_GRPC_EDIT_TARGET, HONUA_GRPC_EDIT_SERVICE and HONUA_GRPC_EDIT_API_KEY")
    layer = int(os.environ.get("HONUA_GRPC_EDIT_LAYER", "0"))
    with HonuaGrpcClient(
        target, credentials=grpc.ssl_channel_credentials(), metadata=build_grpc_metadata(api_key=key),
    ) as client:
        added = client.apply_edits(ApplyEditsRequest(
            service_id=service, layer_id=layer,
            adds=[Feature(attributes={"name": "SDK native edit smoke"}, geometry={"x": 0.0, "y": 0.0})],
        ))
        assert added.error is None and len(added.add_results) == 1
        item = added.add_results[0]
        assert item.success and item.error is None
        try:
            updated = client.apply_edits(ApplyEditsRequest(
                service_id=service, layer_id=layer,
                updates=[Feature(id=item.object_id, attributes={"name": "SDK native edit updated"})],
            ))
            assert updated.error is None and updated.update_results[0].success
        finally:
            deleted = client.apply_edits(ApplyEditsRequest(
                service_id=service, layer_id=layer, deletes=[item.object_id],
            ))
            assert deleted.error is None and deleted.delete_results[0].success
