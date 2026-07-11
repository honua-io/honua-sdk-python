"""Tripwire: the SDK exposes no custom-code / local-execution submission surface.

Custom geoprocessing tools (operator-authored "custom code") execute only in an
isolated cloud-managed AWS Batch container, server-side (honua-server ADR-0063).
The Python SDK intentionally provides **no** way to submit custom code and **no**
way to select an execution backend — backend selection is server configuration.

This test walks the ``honua_sdk`` package AST and fails if anyone introduces a
public API (function/class name, or a function parameter) that would submit
custom code or let a caller pick a local/on-host execution backend. It scans
*identifiers*, not docstrings/comments, so prose that merely describes the policy
(e.g. the ``honua_sdk.migration`` module docstring) does not trip it.

If this test fails, you are (re)introducing a local-execution path the policy
forbids — do not weaken the test; remove the surface, or, if the policy itself is
changing, that is an ADR-0063 amendment, not an SDK change.
"""

from __future__ import annotations

import ast
from pathlib import Path

import honua_sdk

_PACKAGE_ROOT = Path(honua_sdk.__file__).resolve().parent

# Generated protobuf shims are excluded from lint/type/coverage; exclude here too.
_EXCLUDED_PARTS = frozenset({"_generated"})

# Identifier fragments that would signal a custom-code submission or an
# execution-backend selector on a public API. Compared against names with
# separators removed and lower-cased (so "custom_code"/"custom-code"/"CustomCode"
# all normalize to "customcode").
_FORBIDDEN_NAME_FRAGMENTS = ("customcode",)

# Parameter names that would let a caller pick where code runs. A bare "backend"
# parameter on a submission helper is exactly the knob ADR-0063 says must not
# exist on the client.
_FORBIDDEN_PARAM_NAMES = frozenset(
    {"backend", "customcode", "execution_backend", "compute_backend"}
)


def _normalize(name: str) -> str:
    return name.replace("_", "").replace("-", "").lower()


def _package_py_files() -> list[Path]:
    return [
        path
        for path in _PACKAGE_ROOT.rglob("*.py")
        if _EXCLUDED_PARTS.isdisjoint(path.parts)
    ]


def _iter_defs(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node


def test_no_custom_code_named_public_api() -> None:
    offenders: list[str] = []
    for path in _package_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in _iter_defs(tree):
            normalized = _normalize(node.name)
            if any(fragment in normalized for fragment in _FORBIDDEN_NAME_FRAGMENTS):
                offenders.append(f"{path.relative_to(_PACKAGE_ROOT)}::{node.name}")

    assert not offenders, (
        "honua_sdk must expose no custom-code execution surface (ADR-0063: custom "
        f"GP tools are AWS-Batch-only, server-side). Found: {offenders}"
    )


def test_no_execution_backend_selection_parameter() -> None:
    offenders: list[str] = []
    for path in _package_py_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in _iter_defs(tree):
            if isinstance(node, ast.ClassDef):
                continue
            args = node.args
            params = [*args.posonlyargs, *args.args, *args.kwonlyargs]
            if args.vararg is not None:
                params.append(args.vararg)
            if args.kwarg is not None:
                params.append(args.kwarg)
            for param in params:
                if _normalize(param.arg) in _FORBIDDEN_PARAM_NAMES:
                    offenders.append(
                        f"{path.relative_to(_PACKAGE_ROOT)}::{node.name}({param.arg})"
                    )

    assert not offenders, (
        "No honua_sdk API may accept an execution-backend selector: backend "
        "selection for geoprocessing is server configuration, and custom code is "
        f"AWS-Batch-only (ADR-0063). Found: {offenders}"
    )
