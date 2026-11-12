"""Keep retired vocabulary out of public SDK names, CLI help and authored docs.

The canonical vocabulary is the honua-server glossary
(``docs/concepts/domain/README.md``) and the shared retired-terms policy
(``scripts/ci/retired-terms.v1.json``). Deprecated aliases and names that
describe a foreign format or a server wire field are listed explicitly below.
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import inspect
import pkgutil
import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

from honua_admin import cli as admin_cli
from honua_sdk import cli as sdk_cli

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ROOTS = ("honua_sdk", "honua_admin")

RETIRED_NAME_TOKEN = re.compile(
    r"(?:^|_)(workspace|slot|serving_target|projection|esri|hosted|portal|web_map|webmap"
    r"|api_token|package|family|composition|tenant)(?:s|_|$)"
)
RETIRED_TEXT = re.compile(
    r"\b(workspace|slot|serving target|hosted layer|portal item|web ?map(?! (?:tile )?service)"
    r"|HonuaApiToken|MapPackage|AppPackage|HostedMap|content item|tenant)s?\b",
    re.IGNORECASE,
)

DEPRECATED_ALIASES = {
    f"honua_sdk.workflow.{cls}.{member}": replacement
    for cls in ("HonuaWorkflow", "AsyncHonuaWorkflow")
    for member, replacement in (
        ("packages", "drafts"),
        ("package", "draft"),
        ("package(package_id)", "draft(workflow_id)"),
        ("save_package", "save_draft"),
        ("save_package(package_id)", "save_draft(workflow_id)"),
        ("update_package", "update_draft"),
        ("update_package(package_id)", "update_draft(workflow_id)"),
    )
}

KEPT_NAMES = (
    (
        re.compile(
            r"^honua_sdk\.protocols(?:\.scenes)?\.(?:\w*Scene\w*|\w*scene_package\w*|CURRENT_PACKAGE_SCHEMA_VERSION)"
        ),
        "offline scene package: a downloadable archive format, not Studio content",
    ),
    (
        re.compile(r"^honua_admin\.FolderMetadata\.tenant$"),
        "mirrors the server's Folder wire field until the server contract migration renames it",
    ),
)

AUTHORED_DOC_EXCLUSIONS = ("CHANGELOG.md", "packages/honua-gp/", "docs/honua-gp/")  # history; desktop GIS API emulation
BUILD_TOOLING_TERMS = re.compile(r"build-slot|workspace-(?:wide|root)")


def _snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()


def _public_modules() -> Iterator[str]:
    for root in PUBLIC_ROOTS:
        yield root
        package = importlib.import_module(root)
        for info in pkgutil.walk_packages(package.__path__, f"{root}."):
            if not any(part.startswith("_") for part in info.name.split(".")[1:]):
                yield info.name


def _parameters(qualified: str, function: object) -> Iterator[tuple[str, str]]:
    try:
        signature = inspect.signature(function)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return
    for parameter in signature.parameters:
        yield f"{qualified}({parameter})", parameter


def _class_members(qualified: str, cls: type) -> Iterator[tuple[str, str]]:
    for name, value in vars(cls).items():
        if name.startswith("_"):
            continue
        yield f"{qualified}.{name}", name
        function = getattr(value, "__func__", value)
        if callable(function):
            yield from _parameters(f"{qualified}.{name}", function)
    if dataclasses.is_dataclass(cls):
        for field in dataclasses.fields(cls):
            yield f"{qualified}.{field.name}", field.name


def _is_own(value: object, root: str) -> bool:
    return isinstance(value, str | int) or str(getattr(value, "__module__", "")).startswith(root)


def _public_names() -> Iterator[tuple[str, str]]:
    for module_name in _public_modules():
        module = importlib.import_module(module_name)
        root = module_name.split(".")[0]
        for name, value in vars(module).items():
            if name.startswith("_") or not _is_own(value, root):
                continue
            qualified = f"{module_name}.{name}"
            yield qualified, name
            if inspect.isclass(value):
                yield from _class_members(qualified, value)
            elif inspect.isfunction(value):
                yield from _parameters(qualified, value)


def _is_kept(qualified: str) -> bool:
    return qualified in DEPRECATED_ALIASES or any(pattern.match(qualified) for pattern, _ in KEPT_NAMES)


def test_public_names_use_the_canonical_vocabulary() -> None:
    offenders = sorted({qualified for qualified, name in _public_names() if RETIRED_NAME_TOKEN.search(_snake(name))})

    unexpected = [qualified for qualified in offenders if not _is_kept(qualified)]

    assert not unexpected, f"public names use retired vocabulary (see the honua-server glossary): {unexpected}"


def test_deprecated_aliases_are_still_present() -> None:
    names = {qualified for qualified, _ in _public_names()}

    missing = sorted(set(DEPRECATED_ALIASES) - names)

    assert not missing, f"remove these entries from DEPRECATED_ALIASES too: {missing}"


def _parser_texts(parser: argparse.ArgumentParser) -> Iterator[str]:
    yield from (text for text in (parser.description, parser.epilog) if text)
    for action in parser._actions:
        if action.help and action.help is not argparse.SUPPRESS:
            yield action.help
        if isinstance(action, argparse._SubParsersAction):
            for name, child in action.choices.items():
                yield name
                yield from _parser_texts(child)
            yield from (choice.help for choice in action._choices_actions if choice.help)


def test_cli_help_uses_the_canonical_vocabulary() -> None:
    texts = [*_parser_texts(sdk_cli.build_parser()), *_parser_texts(admin_cli.build_parser())]

    offenders = sorted({text for text in texts if RETIRED_TEXT.search(text)})

    assert not offenders, f"CLI help uses retired vocabulary: {offenders}"


def _authored_docs() -> Iterator[Path]:
    git = shutil.which("git")
    assert git, "git is required to enumerate the public tree"
    listing = subprocess.run(  # noqa: S603 -- resolved git + literal args
        [git, "ls-files", "-z", "*.md"], cwd=ROOT, capture_output=True, check=True
    ).stdout.decode("utf-8")
    for name in filter(None, listing.split("\0")):
        if not any(excluded in name for excluded in AUTHORED_DOC_EXCLUSIONS):
            yield ROOT / name


def test_authored_docs_use_the_canonical_vocabulary() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _authored_docs():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if RETIRED_TEXT.search(BUILD_TOOLING_TERMS.sub("", line)):
                offenders.setdefault(path.relative_to(ROOT).as_posix(), []).append(f"{number}: {line.strip()}")

    assert not offenders, f"authored docs use retired vocabulary: {offenders}"
