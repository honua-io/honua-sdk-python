from __future__ import annotations

from pathlib import Path

import pytest

INTEGRATION_DIR = (Path(__file__).resolve().parent / "integration").resolve()
CONFORMANCE_DIR = (Path(__file__).resolve().parent / "conformance").resolve()
_OPT_IN_DIRS = (INTEGRATION_DIR, CONFORMANCE_DIR)


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help=(
            "Run the opt-in live-server suites under tests/integration "
            "(staging smoke) and tests/conformance (shared-fixture conformance)."
        ),
    )


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool:
    path = Path(str(collection_path)).resolve()
    for opt_in_dir in _OPT_IN_DIRS:
        try:
            path.relative_to(opt_in_dir)
        except ValueError:
            continue
        return not config.getoption("--run-integration")
    return False
