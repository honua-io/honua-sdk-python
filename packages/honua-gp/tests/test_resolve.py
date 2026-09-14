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


@pytest.mark.parametrize(
    ("path", "source", "server_url", "locator"),
    [
        ("rest/services/test/FeatureServer/0", "honua://services/test/0", None, {"serviceId": "test", "layerId": 0}),
        ("/rest/services/test/FeatureServer/0/", "honua://services/test/0", None, {"serviceId": "test", "layerId": 0}),
        (
            "https://localhost:28446/rest/services/test/FeatureServer/0",
            "honua://services/test/0",
            "https://localhost:28446",
            {"serviceId": "test", "layerId": 0},
        ),
        (
            "https://honua.example.com/gis/rest/services/parcels/FeatureServer/12?f=json",
            "honua://services/parcels/12",
            "https://honua.example.com/gis",
            {"serviceId": "parcels", "layerId": 12},
        ),
    ],
)
def test_feature_server_layer_paths_resolve_to_service_and_layer(
    path: str, source: str, server_url: str | None, locator: dict[str, object]
) -> None:
    """#205: the licensed GetCount probe passed both of the first forms and got
    ``workspace-relative`` back, so GetCount queried the URL as a service id."""

    resolved = resolve(path)
    assert resolved.kind == "honua-uri"
    assert resolved.source == source
    assert resolved.server_url == server_url
    assert descriptor_mapping(resolved)["locator"] == locator


def test_foldered_feature_server_url_is_rejected_not_escaped() -> None:
    from honua_gp._errors import HonuaGpResolveError

    with pytest.raises(HonuaGpResolveError, match="Foldered ArcGIS services"):
        resolve("https://honua.example.com/gis/rest/services/folder/test/FeatureServer/12")


def test_feature_server_layer_url_decodes_escaped_service_name() -> None:
    from honua_sdk.protocols._base import _service_path

    resolved = resolve("https://honua.example.com/rest/services/My%20Service/FeatureServer/0")
    assert resolved.source == "honua://services/My Service/0"
    descriptor = descriptor_mapping(resolved)
    assert descriptor["locator"] == {"serviceId": "My Service", "layerId": 0}
    assert _service_path(descriptor["locator"]["serviceId"], "FeatureServer") == (
        "/rest/services/My%20Service/FeatureServer"
    )


@pytest.mark.parametrize(
    "configured",
    [
        "https://localhost:28446",
        "https://LOCALHOST:28446/",
    ],
)
def test_feature_server_url_on_configured_server_is_accepted(configured: str) -> None:
    honua_gp.configure(base_url=configured, client=object())
    resolved = resolve("https://localhost:28446/rest/services/test/FeatureServer/0")
    assert descriptor_mapping(resolved)["locator"] == {"serviceId": "test", "layerId": 0}


def test_feature_server_url_default_port_matches_configured_server() -> None:
    honua_gp.configure(base_url="https://honua.example.com/gis", client=object())
    resolved = resolve("https://honua.example.com:443/gis/rest/services/parcels/FeatureServer/3")
    assert descriptor_mapping(resolved)["locator"] == {"serviceId": "parcels", "layerId": 3}


@pytest.mark.parametrize(
    "url",
    [
        "https://other.example.com/rest/services/test/FeatureServer/0",
        "http://localhost:28446/rest/services/test/FeatureServer/0",
        "https://localhost:28447/rest/services/test/FeatureServer/0",
        "https://localhost:28446/gis/rest/services/test/FeatureServer/0",
    ],
)
def test_feature_server_url_for_another_server_is_rejected(url: str) -> None:
    from honua_gp._errors import HonuaGpResolveError

    honua_gp.configure(base_url="https://localhost:28446", client=object())
    with pytest.raises(HonuaGpResolveError, match="names the server"):
        descriptor_mapping(resolve(url))


def test_feature_server_url_is_checked_against_environment_before_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from honua_gp._errors import HonuaGpResolveError

    monkeypatch.setenv("HONUA_BASE_URL", "https://localhost:28446")
    with pytest.raises(HonuaGpResolveError, match="names the server"):
        descriptor_mapping(resolve("https://other.example.com/rest/services/test/FeatureServer/0"))


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
