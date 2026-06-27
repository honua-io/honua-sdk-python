"""Path resolution semantics."""

from __future__ import annotations

import pytest

import honua_gp
from honua_gp._resolve import descriptor_mapping, resolve


def test_alias_takes_precedence_over_other_classifications() -> None:
    honua_gp.configure(client=object())  # we don't dispatch -- just exercise the alias.
    honua_gp.get_session().register_layer(honua_gp.LayerAlias(name="lyr", source="honua://services/roads"))

    resolved = resolve("lyr")
    assert resolved.kind == "alias"
    assert resolved.source == "honua://services/roads"


def test_honua_uri_is_passed_through() -> None:
    resolved = resolve("honua://services/transport/0")
    assert resolved.kind == "honua-uri"
    assert resolved.source == "honua://services/transport/0"


def test_in_memory_paths_are_recognized() -> None:
    resolved = resolve("in_memory/parcels")
    assert resolved.kind == "in-memory"
    assert resolved.source.startswith("in_memory:")


@pytest.mark.parametrize(
    "path",
    [r"C:\GIS\parcels.gdb\Parcels", "/srv/data/parcels.gdb/Parcels"],
)
def test_absolute_paths_extract_workspace(path: str) -> None:
    resolved = resolve(path)
    assert resolved.kind == "absolute"
    assert resolved.source == "Parcels"
    assert resolved.workspace and ".gdb" in resolved.workspace


def test_workspace_relative_is_default_classification() -> None:
    resolved = resolve("roads")
    assert resolved.kind == "workspace-relative"
    assert resolved.source == "roads"


def test_honua_path_map_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HONUA_GP_PATH_MAP", '{"roads": "honua://services/transport/0"}')
    resolved = resolve("roads")
    assert resolved.kind == "honua-uri"
    assert resolved.source == "honua://services/transport/0"


def test_descriptor_mapping_parses_honua_uri_service_and_layer() -> None:
    resolved = resolve("honua://services/transport/2")
    descriptor = descriptor_mapping(resolved)
    assert descriptor["protocol"] == "geoservices-feature-service"
    assert descriptor["locator"] == {"serviceId": "transport", "layerId": 2}


def test_descriptor_mapping_rejects_named_honua_uri_layer() -> None:
    resolved = resolve("honua://services/transport/roads")
    with pytest.raises(honua_gp.HonuaGpResolveError):
        descriptor_mapping(resolved)


def test_descriptor_mapping_falls_back_to_workspace_context() -> None:
    honua_gp.get_session().workspace = "honua://services/transport"
    resolved = resolve("roads")
    descriptor = descriptor_mapping(resolved)
    assert descriptor["locator"]["serviceId"] == "transport"
    assert descriptor["locator"]["layerId"] == 0


def test_descriptor_mapping_round_trips_through_honua_sdk() -> None:
    # The real SDK rejects bare strings with TypeError. Building a descriptor
    # via descriptor_mapping should produce a mapping the SDK accepts.
    from honua_sdk.models import SourceDescriptor

    resolved = resolve("honua://services/parcels/0")
    descriptor = descriptor_mapping(resolved)
    coerced = SourceDescriptor.from_dict(descriptor)
    assert coerced.protocol == "geoservices-feature-service"
    assert coerced.locator.service_id == "parcels"
    assert coerced.locator.layer_id == 0
