"""``honua query`` and the operator groups mounted on ``honua`` (honua-sdk-python#258)."""

from __future__ import annotations

import argparse
import importlib
import json
import re
from types import ModuleType
import httpx
import pytest

from honua_sdk import HonuaClient
from honua_sdk import cli

_FEATURES = {
    "type": "FeatureCollection",
    "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [-157.8, 21.3]}, "properties": {"gid": 1}},
    ],
}


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    """Route the data-plane client to an in-memory FeatureServer; return the request log."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        match = re.fullmatch(r"/rest/services/([^/]+)/FeatureServer/(\d+)/query", request.url.path)
        if match is None or match.group(1) != "sites":
            # Honua answers an unknown or disabled layer with a GeoServices error envelope.
            return httpx.Response(200, json={"error": {"code": 404, "message": "Layer not found."}})
        if request.url.params.get("returnCountOnly") == "true":
            return httpx.Response(200, json={"count": 7})
        if request.url.params["f"] == "json":
            return httpx.Response(200, json={"features": [{"attributes": {"gid": 1}}]})
        return httpx.Response(200, json=_FEATURES, headers={"content-type": "application/geo+json"})

    monkeypatch.setattr(
        cli, "_make_client", lambda _args: HonuaClient("http://example.test", transport=httpx.MockTransport(handler))
    )
    return seen


def test_query_prints_geojson_page(served: list[httpx.Request], capsys: pytest.CaptureFixture[str]) -> None:
    code = cli.main(
        ["query", "sites", "0", "--where", "status = 'open'", "--order-by", "gid", "--limit", "5", "--offset", "10"]
    )
    assert code == 0
    assert json.loads(capsys.readouterr().out) == _FEATURES
    params = dict(served[-1].url.params)
    assert params["f"] == "geojson"
    assert params["where"] == "status = 'open'"
    assert params["returnGeometry"] == "true"
    assert (params["orderByFields"], params["resultRecordCount"], params["resultOffset"]) == ("gid", "5", "10")


def test_query_esri_json_format(served: list[httpx.Request], capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["query", "sites", "0", "--format", "json", "--out-fields", "gid"]) == 0
    assert json.loads(capsys.readouterr().out) == {"features": [{"attributes": {"gid": 1}}]}
    assert served[-1].url.params["outFields"] == "gid"
    assert "orderByFields" not in served[-1].url.params


def test_query_count(served: list[httpx.Request], capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["query", "sites", "0", "--count", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"count": 7}
    params = dict(served[-1].url.params)
    assert params["returnCountOnly"] == "true"
    assert params["returnGeometry"] == "false"
    assert params["f"] == "json"  # count requests keep the client's f=json, never GeoJSON

    assert cli.main(["query", "sites", "0", "--count"]) == 0
    assert capsys.readouterr().out == "7\n"


def test_query_unpublished_layer_exits_1_with_http_status(
    served: list[httpx.Request], capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["query", "lifecycle", "1", "--format", "geojson"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert re.search(r"\bHTTP 404\b", captured.err)


def test_services_and_layers_accept_json_flag() -> None:
    parser = cli.build_parser()
    assert parser.parse_args(["services", "--json"]).format == "json"
    assert parser.parse_args(["layers", "sites", "--format", "table", "--json"]).format == "json"
    assert parser.parse_args(["layers", "sites", "--format", "table"]).format == "table"


def test_operator_groups_are_mounted_from_honua_admin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from honua_admin import HonuaAdminClient
    from honua_admin import cli as admin_cli

    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(403, json={"title": "Forbidden", "detail": "The requester cannot approve."})

    monkeypatch.setattr(
        admin_cli,
        "_make_client",
        lambda args: HonuaAdminClient(
            "http://example.test", api_key=admin_cli._resolve_api_key(args), transport=httpx.MockTransport(handler)
        ),
    )
    assert cli.main(["proposal", "approve", "prop-1", "--api-key", "proposer", "--json"]) == 1
    assert re.search(r"\bHTTP 403\b", capsys.readouterr().err)
    assert seen[-1].url.path == "/api/v1/admin/proposals/prop-1/approve"
    assert seen[-1].headers["X-API-Key"] == "proposer"

    assert cli.main(["layer", "publish", "conn-1"]) == 2
    assert "a table is required" in capsys.readouterr().err


def test_operator_groups_point_at_honua_admin_when_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    real_import = importlib.import_module

    def without_admin(name: str, package: str | None = None) -> ModuleType:
        if name == "honua_admin.cli":
            raise ImportError(name)
        return real_import(name, package)

    monkeypatch.setattr(cli.importlib, "import_module", without_admin)
    for group in ("datasource", "layer", "proposal"):
        assert cli.main([group, "create", "--name", "x"]) == 2
        assert f"`honua {group}` needs the control-plane package" in capsys.readouterr().err


def test_operator_groups_skip_an_admin_without_the_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.importlib, "import_module", lambda _name, _package=None: ModuleType("honua_admin.cli"))
    args = cli.build_parser().parse_args(["proposal", "approve", "p"])
    assert args.func is cli._missing_admin


def test_missing_js_cli_message_names_python_operator_commands(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("HONUA_JS_CLI", raising=False)
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(cli, "_sibling_js_cli", lambda: None)
    assert cli._delegate_control_plane(["admin", "connect"]) == 127
    assert "honua datasource|layer|proposal" in capsys.readouterr().err


def test_missing_admin_reports_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli._missing_admin(argparse.Namespace(command="layer"), None) == 2
    assert "pip install 'honua-admin>=0.1.10'" in capsys.readouterr().err
