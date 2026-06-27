from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from honua_sdk import (
    CAPABILITIES,
    DEFAULT_CAPABILITIES,
    PROTOCOLS,
    PROTOCOL_ALIASES,
    HonuaCapabilityNotSupportedError,
    HonuaClient,
    Pagination,
    Query,
    Source,
    SourceDescriptor,
    SourceLocator,
    default_capabilities,
    normalize_capability,
    normalize_protocol,
)

CONTRACT_PATH = Path(__file__).parent / "fixtures" / "sdk-contract" / "semantic-contract.v1.json"


def _contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_semantic_contract_protocols_and_capabilities_match_fixture() -> None:
    contract = _contract()

    assert PROTOCOLS == tuple(contract["protocols"])
    assert dict(PROTOCOL_ALIASES) == contract["protocolAliases"]
    assert CAPABILITIES == tuple(contract["capabilities"])
    assert {key: list(value) for key, value in DEFAULT_CAPABILITIES.items()} == contract["defaultCapabilities"]

    for alias, protocol in contract["protocolAliases"].items():
        assert normalize_protocol(alias) == protocol
    for protocol, capabilities in contract["defaultCapabilities"].items():
        assert default_capabilities(protocol) == frozenset(capabilities)


def test_semantic_contract_python_bindings_are_present() -> None:
    contract = _contract()
    python_bindings = {
        binding["concept"]: binding["python"]
        for binding in contract["languageBindings"]
        if "python" in binding
    }

    assert python_bindings["queryAll"] == "query_all()"
    assert python_bindings["applyEdits"] == "apply_edits()"
    assert python_bindings["returnGeometry"] == "return_geometry"
    assert python_bindings["outFields"] == "out_fields"
    assert python_bindings["protocolEscapeHatch"] == "source.protocol(...)"
    assert hasattr(Source, "query_all")
    assert hasattr(Source, "apply_edits")
    assert hasattr(Source, "protocol")
    assert normalize_capability("apply_edits") == "applyEdits"
    assert normalize_capability("query_object_ids") == "queryObjectIds"


def test_source_query_facade_uses_canonical_descriptor_and_returns_result() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(dict(request.url.params.multi_items()))
        assert request.url.path == "/rest/services/Parcels/FeatureServer/0/query"
        return httpx.Response(
            200,
            json={
                "features": [
                    {
                        "attributes": {"OBJECTID": 1, "NAME": "Ala Wai", "STATUS": "ACTIVE"},
                        "geometry": {"x": -157.836, "y": 21.284},
                    },
                    {
                        "attributes": {"OBJECTID": 2, "NAME": "Kapiolani", "STATUS": "ACTIVE"},
                        "geometry": {"x": -157.82, "y": 21.267},
                    },
                ],
                "exceededTransferLimit": False,
            },
        )

    descriptor = SourceDescriptor(
        id="parcels-fs",
        protocol="feature-server",
        locator=SourceLocator(service_id="Parcels", layer_id=0),
        capabilities=frozenset(("query", "queryObjectIds")),
    )
    query = Query(
        where="STATUS = 'ACTIVE'",
        out_fields=["OBJECTID", "NAME", "STATUS"],
        pagination=Pagination(limit=2),
        return_geometry=True,
        out_sr=4326,
    )

    transport = httpx.MockTransport(handler)
    with HonuaClient("http://example.test", transport=transport) as client:
        source = client.source(descriptor)
        assert source.supports("query") is True
        assert source.supports("stream") is False
        assert source.supports("apply_edits") is False
        result = source.query(query)

    assert result.protocol == "geoservices-feature-service"
    assert result.source_id == "parcels-fs"
    # FeatureServer query responses carry no grand total (no ``numberMatched``
    # equivalent), so ``total_count`` is unknown rather than the count of
    # features actually returned.
    assert result.total_count is None
    assert [feature.id for feature in result.features] == [1, 2]
    assert result.features[0].protocol == "geoservices-feature-service"
    assert result.features[0].source == "parcels-fs"
    assert result.features[0].properties == {"OBJECTID": 1, "NAME": "Ala Wai", "STATUS": "ACTIVE"}
    assert seen["where"] == "STATUS = 'ACTIVE'"
    assert seen["outFields"] == "OBJECTID,NAME,STATUS"
    assert seen["returnGeometry"] == "true"
    assert seen["resultRecordCount"] == "2"
    assert seen["outSR"] == "4326"


def test_source_protocol_escape_hatch_returns_native_client() -> None:
    descriptor = SourceDescriptor(
        id="parcels",
        protocol="geoservices-feature-service",
        locator=SourceLocator(service_id="Parcels", layer_id=0),
    )

    with HonuaClient("http://example.test", transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
        native = client.source(descriptor).protocol()

    assert native.service_id == "Parcels"
    assert native.path == "/rest/services/Parcels/FeatureServer"


def test_source_raises_contract_error_for_unsupported_capability() -> None:
    descriptor = SourceDescriptor(id="map", protocol="wms", locator=SourceLocator(service_id="BaseMap"))
    assert descriptor.supports("query") is True

    with HonuaClient("http://example.test", transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
        source = client.source(descriptor)
        assert source.supports("query") is False
        with pytest.raises(HonuaCapabilityNotSupportedError) as exc_info:
            source.query(where="1=1")

    assert exc_info.value.capability == "query"
    assert exc_info.value.protocol == "wms"
    assert exc_info.value.source_id == "map"


def test_source_raises_contract_error_for_unsupported_edit_operation() -> None:
    descriptor = SourceDescriptor.from_dict(
        {
            "id": "parcels-ogc",
            "protocol": "ogc-features",
            "locator": {"collectionId": "parcels"},
        }
    )
    assert descriptor.supports("applyEdits") is True

    with HonuaClient("http://example.test", transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
        source = client.source(descriptor)
        assert source.supports("applyEdits") is False
        with pytest.raises(HonuaCapabilityNotSupportedError) as exc_info:
            source.apply_edits(adds=[])

    assert exc_info.value.capability == "applyEdits"
    assert exc_info.value.protocol == "ogc-features"
