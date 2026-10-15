"""The product CLI delegates to one devkit, never to a server execution backend."""

from __future__ import annotations

from honua_sdk import cli


def test_gp_main_dispatches_before_server_or_js_routing(monkeypatch):
    monkeypatch.setattr(cli, "_delegate_gp", lambda args: 7 if args == ["doctor", "--json"] else 99)
    monkeypatch.delenv("HONUA_BASE_URL", raising=False)
    assert cli.main(["gp", "doctor", "--json"]) == 7


def test_gp_passes_literal_arguments_and_exit_code(monkeypatch):
    monkeypatch.setenv("HONUA_GP_CLI", "/tools with spaces/devkit")
    monkeypatch.setattr(cli.shutil, "which", lambda name: name)
    calls = []

    def run(args):
        calls.append(args)
        return 3

    assert cli._delegate_gp(["run", "geometry.buffer", "--param", "label=$(unsafe)", "--param", "name=a b"], run) == 3
    assert calls == [
        ["/tools with spaces/devkit", "run", "geometry.buffer", "--param", "label=$(unsafe)", "--param", "name=a b"]
    ]


def test_gp_missing_engine_is_actionable(monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)
    assert cli._delegate_gp(["list"]) == 127
    assert "honua-gp-devkit" in capsys.readouterr().err


def test_gp_launch_failure_is_nonzero(monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", lambda _: "/tools/devkit")

    def fail(*_args):
        raise PermissionError(13, "permission denied")

    monkeypatch.setattr(cli.os, "execv", fail)
    assert cli._delegate_gp(["list"]) == 127
    assert "could not launch" in capsys.readouterr().err
