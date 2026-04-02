from __future__ import annotations

from pathlib import Path

import pytest

INTEGRATION_DIR = (Path(__file__).resolve().parent / "integration").resolve()


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run staging integration smoke tests under tests/integration.",
    )


def pytest_ignore_collect(collection_path: Path, config: pytest.Config) -> bool:
    path = Path(str(collection_path)).resolve()
    try:
        path.relative_to(INTEGRATION_DIR)
    except ValueError:
        return False
    return not config.getoption("--run-integration")
