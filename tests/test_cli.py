from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from honua_sdk import HonuaClient
from honua_sdk import cli


def _client_with_handler(handler: Any) -> HonuaClient:
    return HonuaClient("http://example.test", transport=httpx.MockTransport(handler))


@pytest.fixture
def patch_client(monkeypatch: pytest.MonkeyPatch):
    """Return a helper that wires a MockTransport-backed client into the CLI."""

    def _install(handler: Any) -> None:
        monkeypatch.setattr(cli, "_make_client", lambda _args: _client_with_handler(handler))

    return _install


def test_services_json_output(patch_client: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/services"
        return httpx.Response(
            200,
            json={
                "services": [
                    {"name": "roads", "type": "FeatureServer", "url": "/rest/services/roads/FeatureServer"},
                    {"name": "imagery", "type": "MapServer"},
                ]
            },
        )

    patch_client(handler)
    out = io.StringIO()
    rc = cli._cmd_services(_ns(format="json"), out)
    assert rc == 0
    parsed = json.loads(out.getvalue())
    assert parsed == [
        {"name": "roads", "type": "FeatureServer", "url": "/rest/services/roads/FeatureServer"},
        {"name": "imagery", "type": "MapServer", "url": None},
    ]


def test_services_table_output(patch_client: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"services": [{"name": "roads", "type": "FeatureServer"}]})

    patch_client(handler)
    out = io.StringIO()
    rc = cli._cmd_services(_ns(format="table"), out)
    assert rc == 0
    text = out.getvalue()
    assert "name" in text
    assert "roads" in text
    assert "FeatureServer" in text


def test_layers_lists_layers_and_tables(patch_client: Any) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/rest/services/roads/FeatureServer"
        return httpx.Response(
            200,
            json={
                "layers": [{"id": 0, "name": "Highways", "type": "Feature Layer", "geometryType": "esriGeometryPolyline"}],
                "tables": [{"id": 1, "name": "Inspections"}],
            },
        )

    patch_client(handler)
    out = io.StringIO()
    rc = cli._cmd_layers(_ns(service_id="roads", format="json"), out)
    assert rc == 0
    parsed = json.loads(out.getvalue())
    assert parsed == [
        {"id": 0, "name": "Highways", "type": "Feature Layer", "geometryType": "esriGeometryPolyline"},
        {"id": 1, "name": "Inspections", "type": "Table", "geometryType": None},
    ]


def test_style_apply_writes_image(tmp_path: Any, patch_client: Any) -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["query"] = dict(request.url.params.multi_items())
        return httpx.Response(200, content=b"\x89PNG-bytes")

    patch_client(handler)
    out_path = tmp_path / "render.png"
    out = io.StringIO()
    rc = cli._cmd_style_apply(
        _ns(
            service_id="basemap",
            bbox="0,0,1,1",
            style="night",
            layers="show:0",
            image_format="png",
            out=str(out_path),
        ),
        out,
    )
    assert rc == 0
    assert out_path.read_bytes() == b"\x89PNG-bytes"
    assert "MapServer/export" in captured["path"]
    assert captured["query"]["style"] == "night"
    assert captured["query"]["layers"] == "show:0"


def test_main_returns_2_for_no_command() -> None:
    assert cli.main([]) == 2


def test_main_forwards_admin_before_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, list[str]] = {}

    def delegate(argv: list[str]) -> int:
        seen["argv"] = argv
        return 7

    monkeypatch.setattr(cli, "_delegate_control_plane", delegate)
    assert cli.main(["admin", "install", "status", "--directory", ".honua"]) == 7
    assert seen["argv"] == ["admin", "install", "status", "--directory", ".honua"]


@pytest.mark.parametrize("command", sorted(cli.JS_CLI_COMMANDS))
def test_main_forwards_each_js_cli_command(command: str, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[list[str]] = []
    monkeypatch.setattr(cli, "_delegate_control_plane", lambda argv: seen.append(list(argv)) or 0)
    assert cli.main([command, "--json"]) == 0
    assert seen == [[command, "--json"]]


def test_js_cli_commands_do_not_shadow_python_commands() -> None:
    assert cli.JS_CLI_COMMANDS.isdisjoint(cli._parser_commands(cli.build_parser()))


def test_console_python_commands_never_forward(monkeypatch: pytest.MonkeyPatch, patch_client: Any) -> None:
    monkeypatch.setattr(cli, "_delegate_control_plane", lambda _argv: pytest.fail("forwarded"))
    monkeypatch.setattr(cli, "_control_plane_cli", lambda: pytest.fail("looked up the JS CLI"))
    patch_client(lambda _request: httpx.Response(200, json={"folders": [], "services": []}))
    monkeypatch.setattr(cli.sys, "argv", ["honua", "services", "--base-url", "http://example.test"])
    assert cli.main() == 0


@pytest.mark.parametrize("argv", [["frobnicate"], ["frobnicate", "--api-key", "k"], ["Admin"]])
def test_unknown_command_is_a_usage_error_and_never_execs(
    argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "_control_plane_cli", lambda: pytest.fail("looked up the JS CLI"))
    monkeypatch.setattr(cli.os, "execv", lambda *_args: pytest.fail("exec'd"))
    monkeypatch.setattr(cli.sys, "argv", ["honua", *argv])
    assert cli.main() == 2
    err = capsys.readouterr().err
    assert f"unknown command {argv[0]!r}" in err
    assert "services" in err
    assert "admin" in err


def _fake_js_package(root: Path, *, name: str = "@honua/sdk-js", declare_bin: bool = True) -> Path:
    package = root / "node_modules" / "@honua" / "sdk-js"
    binary = package / "dist" / "src" / "cli" / "bin.js"
    binary.parent.mkdir(parents=True)
    binary.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    manifest: dict[str, Any] = {"name": name}
    if declare_bin:
        manifest["bin"] = {"honua": "./dist/src/cli/bin.js"}
    (package / "package.json").write_text(json.dumps(manifest), encoding="utf-8")
    return binary


def test_admin_delegate_uses_honua_js_cli(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    binary = tmp_path / "bin.js"
    binary.write_text("#!/usr/bin/env node\n", encoding="utf-8")
    monkeypatch.setenv("HONUA_JS_CLI", str(binary))
    seen: dict[str, list[str]] = {}

    def runner(command: list[str]) -> int:
        seen["command"] = command
        return 0

    assert cli._delegate_control_plane(["admin", "install", "status"], runner=runner) == 0
    assert seen["command"][1:] == [str(binary), "admin", "install", "status"]
    assert Path(seen["command"][0]).stem.lower() == "node"


def test_control_plane_cli_follows_npm_symlink_to_package(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary = _fake_js_package(tmp_path / "lib")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    binary.chmod(0o755)
    (bin_dir / "honua").symlink_to(binary)
    monkeypatch.delenv("HONUA_JS_CLI", raising=False)
    monkeypatch.setenv("PATH", str(bin_dir))
    assert cli._control_plane_cli() == binary.resolve()


def test_control_plane_cli_reads_windows_cmd_shim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary = _fake_js_package(tmp_path)
    (tmp_path / "honua.cmd").write_text(
        '@ECHO off\r\nSET dp0=%~dp0\r\n"%_prog%"  "%dp0%\\node_modules\\@honua\\sdk-js\\dist\\src\\cli\\bin.js" %*\r\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("HONUA_JS_CLI", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert cli._control_plane_cli() == binary.resolve()


def test_control_plane_cli_reads_powershell_shim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    binary = _fake_js_package(tmp_path)
    (tmp_path / "honua.ps1").write_text(
        '& "$basedir/node$exe"  "$basedir/node_modules/@honua/sdk-js/dist/src/cli/bin.js" $args\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("HONUA_JS_CLI", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert cli._control_plane_cli() == binary.resolve()


def test_control_plane_cli_ignores_unrelated_honua_executable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    impostor = tmp_path / "honua"
    impostor.write_text("#!/bin/sh\necho pwned\n", encoding="utf-8")
    impostor.chmod(0o755)
    monkeypatch.delenv("HONUA_JS_CLI", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert cli._control_plane_cli() is None
    assert cli._delegate_control_plane(["admin"], runner=lambda _cmd: pytest.fail("ran impostor")) == 127


@pytest.mark.parametrize(("name", "declare_bin"), [("@evil/sdk-js", True), ("@honua/sdk-js", False)])
def test_control_plane_cli_requires_the_package_identity(
    name: str, declare_bin: bool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _fake_js_package(tmp_path, name=name, declare_bin=declare_bin)
    (tmp_path / "honua.cmd").write_text('"%dp0%\\node_modules\\@honua\\sdk-js\\dist\\src\\cli\\bin.js" %*', encoding="utf-8")
    monkeypatch.delenv("HONUA_JS_CLI", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert cli._control_plane_cli() is None


def test_admin_delegate_skips_python_shim_on_path(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    shim = tmp_path / "honua"
    shim.write_text("#!/usr/bin/python3\nfrom honua_sdk.cli import main\n", encoding="utf-8")
    shim.chmod(0o755)
    monkeypatch.delenv("HONUA_JS_CLI", raising=False)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert cli._control_plane_cli() is None
    assert cli._delegate_control_plane(["admin"]) == 127


def test_no_sibling_checkout_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HONUA_JS_CLI", raising=False)
    monkeypatch.setenv("PATH", "")
    assert not hasattr(cli, "_sibling_js_cli")
    assert cli._control_plane_cli() is None


def test_admin_delegate_explains_missing_js_cli(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("HONUA_JS_CLI", raising=False)
    monkeypatch.setenv("PATH", "")
    assert cli._delegate_control_plane(["map", "export", "svc"]) == 127
    err = capsys.readouterr().err
    assert "`honua map`" in err
    assert "@honua/sdk-js" in err
    assert "HONUA_JS_CLI" in err


def test_main_handles_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    monkeypatch.setattr(cli, "_make_client", lambda _args: _client_with_handler(handler))
    rc = cli.main(["services", "--base-url", "http://example.test"])
    assert rc == 1


def test_resolve_base_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HONUA_BASE_URL", "http://env.test")
    args = _ns()
    args.base_url = None
    assert cli._resolve_base_url(args) == "http://env.test"


def test_resolve_base_url_missing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HONUA_BASE_URL", raising=False)
    args = _ns()
    args.base_url = None
    with pytest.raises(SystemExit):
        cli._resolve_base_url(args)


def test_build_parser_exposes_commands() -> None:
    parser = cli.build_parser()
    ns = parser.parse_args(["services", "--base-url", "http://x"])
    assert ns.func is cli._cmd_services


def test_style_without_subcommand_returns_2() -> None:
    rc = cli._dispatch_style(_ns(), io.StringIO())
    assert rc == 2


class _Namespace:
    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


def _ns(**kwargs: Any) -> Any:
    defaults: dict[str, Any] = {"base_url": "http://example.test", "api_key": None}
    defaults.update(kwargs)
    return _Namespace(**defaults)



def test_make_client_refuses_credentials_over_plain_http(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HONUA_ALLOW_INSECURE_HTTP", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        cli.main(["services", "--base-url", "http://api.example.test", "--api-key", "secret-key"])
    message = str(excinfo.value.code)
    assert message.startswith("error: Refusing to send credentials over plain HTTP")
    assert "secret-key" not in message
