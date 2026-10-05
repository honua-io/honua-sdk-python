"""Opt-in Docker interoperability against the independently built release server."""
from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest

SERVER_REVISION = "ff5f5671903e96e13cffac7b73546c3ed0f853c5"
SERVER_IMAGE = "ghcr.io/honua-io/honua-server:nightly-ff5f567@sha256:3ef3bd41a2f84d1f3a6194c11db496f741cc4d869b54bf57e9d7067dd9cf3d39"


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool:
    return collection_path.name == "test_server_interop.py" and not config.getoption("--run-integration")


def _fetch(path: str) -> bytes:
    url = f"https://raw.githubusercontent.com/honua-io/honua-server/{SERVER_REVISION}/{path}"
    for delay in (0, 10, 30, 60, 120):
        time.sleep(delay)
        try:
            with urlopen(url, timeout=15) as response:  # noqa: S310 -- fixed HTTPS repository URL
                return response.read()
        except URLError:
            if delay == 120:
                raise
    raise AssertionError("unreachable")


@pytest.fixture(scope="module")
def grpc_target(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Use canonical conformance configuration/seed, including its documented admin password.

    No local server build or Python service stub participates. Docker is required;
    infrastructure failures fail this explicitly requested suite.
    """
    root = tmp_path_factory.mktemp("grpc-interop")
    compose_dir = root / "docker" / "client-compat"
    compose_dir.mkdir(parents=True)
    compose = compose_dir / "compose.yml"
    compose.write_bytes(_fetch("docker/client-compat/compose.yml"))
    seed = _fetch("tests/seed/client-compat-v1.sql").decode()
    override = root / "override.json"
    override.write_text(json.dumps({"services": {"honua": {
        "image": SERVER_IMAGE,
        "ports": ["127.0.0.1::5001"],
    }}}))
    command = ["docker", "compose", "-p", root.name, "-f", str(compose), "-f", str(override)]

    def run(*args: str, input_text: str | None = None) -> str:
        result = subprocess.run(  # noqa: S603 -- fixed Docker commands, no shell
            [*command, *args], input=input_text, capture_output=True, text=True, timeout=240, check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout.strip()

    try:
        run("up", "-d", "--no-build", "--wait", "--wait-timeout", "180", "honua")
        run("exec", "-T", "postgres", "psql", "-U", "postgres", "-d", "honua_compat",
            "-v", "ON_ERROR_STOP=1", input_text=seed)
        yield run("port", "honua", "5001")
    finally:
        logs = subprocess.run([*command, "logs", "--no-color"], capture_output=True, text=True, check=False)  # noqa: S603
        (root / "server.log").write_text(logs.stdout + logs.stderr)
        run("down", "-v", "--remove-orphans")
