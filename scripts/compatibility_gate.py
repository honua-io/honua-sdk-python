"""Compatibility gate for server contracts and public SDK API drift."""

from __future__ import annotations

import argparse
import dataclasses
import difflib
import enum
import inspect
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
API_SNAPSHOT_PATH = ROOT / "compatibility" / "public-api.json"
MATRIX_PATH = ROOT / "compatibility" / "server-matrix.json"
PUBLIC_MODULES = ("honua_sdk", "honua_sdk.grpc", "honua_admin")


def _add_source_paths() -> None:
    for path in (ROOT / "packages" / "honua-admin", ROOT / "packages" / "honua-sdk"):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


_add_source_paths()

from honua_admin import AdminCompatibilityBaseline  # noqa: E402
from honua_admin import evaluate_admin_compatibility  # noqa: E402
from honua_admin._models import AdminCompatibilityMetadata  # noqa: E402


def _json_dumps(data: Mapping[str, Any]) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def _signature(value: Any) -> str | None:
    try:
        return str(inspect.signature(value))
    except (TypeError, ValueError):
        return None


def _annotation(value: Any) -> str:
    if isinstance(value, str):
        return value
    name = getattr(value, "__qualname__", None)
    module = getattr(value, "__module__", None)
    if name and module and module != "builtins":
        return f"{module}.{name}"
    if name:
        return name
    return repr(value)


def _field_default(field: dataclasses.Field[Any]) -> dict[str, str]:
    if field.default is not dataclasses.MISSING:
        return {"default": repr(field.default)}
    if field.default_factory is not dataclasses.MISSING:
        factory = field.default_factory
        factory_name = getattr(factory, "__qualname__", repr(factory))
        factory_module = getattr(factory, "__module__", None)
        if factory_module and factory_module != "builtins":
            factory_name = f"{factory_module}.{factory_name}"
        return {"defaultFactory": factory_name}
    return {}


def _collect_dataclass_fields(cls: type[Any]) -> list[dict[str, str]]:
    annotations = getattr(cls, "__annotations__", {})
    collected = []
    for field in dataclasses.fields(cls):
        item = {
            "name": field.name,
            "annotation": _annotation(annotations.get(field.name, field.type)),
        }
        item.update(_field_default(field))
        collected.append(item)
    return collected


def _collect_public_methods(cls: type[Any]) -> dict[str, dict[str, Any]]:
    methods: dict[str, dict[str, Any]] = {}
    for name, raw_value in sorted(cls.__dict__.items()):
        if name.startswith("_"):
            continue
        if isinstance(raw_value, (classmethod, staticmethod)):
            target = raw_value.__func__
            method_kind = "classmethod" if isinstance(raw_value, classmethod) else "staticmethod"
        elif isinstance(raw_value, property):
            methods[name] = {"kind": "property"}
            continue
        else:
            target = raw_value
            method_kind = "method"

        if not (inspect.isfunction(target) or inspect.ismethoddescriptor(target)):
            continue

        method: dict[str, Any] = {"kind": method_kind}
        signature = _signature(target)
        if signature is not None:
            method["signature"] = signature
        if inspect.iscoroutinefunction(target):
            method["async"] = True
        methods[name] = method
    return methods


def _collect_class(export_name: str, cls: type[Any]) -> dict[str, Any]:
    item: dict[str, Any] = {
        "kind": "class",
        "module": cls.__module__,
        "qualname": cls.__qualname__,
    }
    if issubclass(cls, enum.Enum):
        item["kind"] = "enum"
        item["members"] = {name: member.value for name, member in cls.__members__.items()}
        return item

    signature = _signature(cls)
    if signature is not None:
        item["signature"] = signature
    if dataclasses.is_dataclass(cls):
        item["fields"] = _collect_dataclass_fields(cls)

    methods = _collect_public_methods(cls)
    if methods:
        item["methods"] = methods
    return item


def _collect_export(module_name: str, export_name: str, value: Any) -> dict[str, Any]:
    if inspect.isclass(value):
        return _collect_class(export_name, value)
    if inspect.isfunction(value):
        item: dict[str, Any] = {
            "kind": "function",
            "module": value.__module__,
            "qualname": value.__qualname__,
        }
        signature = _signature(value)
        if signature is not None:
            item["signature"] = signature
        return item
    if export_name == "__version__":
        return {"kind": "constant", "type": type(value).__name__}
    return {"kind": "constant", "type": type(value).__name__, "value": repr(value)}


def collect_public_api_surface() -> dict[str, Any]:
    surface: dict[str, Any] = {
        "schemaVersion": 1,
        "modules": {},
    }
    for module_name in PUBLIC_MODULES:
        module = __import__(module_name, fromlist=["*"])
        exports = sorted(getattr(module, "__all__", ()))
        module_surface: dict[str, Any] = {
            "exports": exports,
            "symbols": {},
        }
        for export_name in exports:
            module_surface["symbols"][export_name] = _collect_export(
                module_name,
                export_name,
                getattr(module, export_name),
            )
        surface["modules"][module_name] = module_surface
    return surface


def update_api_snapshot(path: Path = API_SNAPSHOT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json_dumps(collect_public_api_surface()), encoding="utf-8")


def check_public_api_snapshot(path: Path = API_SNAPSHOT_PATH) -> list[str]:
    actual = collect_public_api_surface()
    try:
        expected = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"Public API snapshot is missing: {path}"]

    if actual == expected:
        return []

    expected_text = _json_dumps(expected).splitlines()
    actual_text = _json_dumps(actual).splitlines()
    diff = "\n".join(
        difflib.unified_diff(
            expected_text,
            actual_text,
            fromfile=str(path),
            tofile="current public API",
            lineterm="",
        )
    )
    return [
        "Public API snapshot drift detected. "
        "Run `python scripts/compatibility_gate.py --update-api-snapshot` "
        "after reviewing any intentional public API change.\n"
        f"{diff}"
    ]


def _required_str(data: Mapping[str, Any], key: str, scope: str) -> tuple[str | None, str | None]:
    value = data.get(key)
    if isinstance(value, str):
        return value, None
    return None, f"{scope}: expected {key!r} to be a string."


def _required_int(data: Mapping[str, Any], key: str, scope: str) -> tuple[int | None, str | None]:
    value = data.get(key)
    if isinstance(value, int):
        return value, None
    return None, f"{scope}: expected {key!r} to be an integer."


def _baseline_from_matrix(data: Mapping[str, Any]) -> tuple[AdminCompatibilityBaseline | None, list[str]]:
    minimum_server_version, version_error = _required_str(data, "minimumServerVersion", "baseline")
    control_plane_api_major, major_error = _required_int(data, "controlPlaneApiMajor", "baseline")
    base_path, base_path_error = _required_str(data, "basePath", "baseline")
    minimum_release_channel, channel_error = _required_str(data, "minimumReleaseChannel", "baseline")
    errors = [
        error
        for error in (
            version_error,
            major_error,
            base_path_error,
            channel_error,
        )
        if error is not None
    ]
    if errors:
        return None, errors
    assert minimum_server_version is not None
    assert control_plane_api_major is not None
    assert base_path is not None
    assert minimum_release_channel is not None
    return AdminCompatibilityBaseline(
        minimum_server_version=minimum_server_version,
        control_plane_api_major=control_plane_api_major,
        base_path=base_path,
        minimum_release_channel=minimum_release_channel,
    ), []


def _to_snake(name: str) -> str:
    s1 = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", name)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s1).replace("-", "_").lower()


def _contains_any(values: Sequence[str], expected: str) -> bool:
    return any(expected in value for value in values)


def _expected_strings(case_name: str, expected: Mapping[str, Any], key: str) -> tuple[list[str], list[str]]:
    value = expected.get(key)
    if value is None:
        return [], []
    if not isinstance(value, list):
        return [], [f"{case_name}: expected.{key} must be a list of strings."]
    failures = []
    strings = []
    for item in value:
        if isinstance(item, str):
            strings.append(item)
        else:
            failures.append(f"{case_name}: expected.{key} entries must be strings.")
    return strings, failures


def _check_expected_features(case_name: str, result: Any, expected: Mapping[str, Any]) -> list[str]:
    expected_features = expected.get("features")
    if expected_features is None:
        return []
    if not isinstance(expected_features, Mapping):
        return [f"{case_name}: expected.features must be an object."]
    if result.compatibility is None:
        return [f"{case_name}: expected feature checks but compatibility is missing."]

    failures = []
    for raw_name, expected_value in sorted(expected_features.items()):
        if not isinstance(expected_value, bool):
            failures.append(f"{case_name}: expected.features.{raw_name} must be a boolean.")
            continue
        attr = _to_snake(raw_name)
        actual_value = getattr(result.compatibility.features, attr, None)
        if actual_value != expected_value:
            failures.append(
                f"{case_name}: feature {raw_name!r} expected {expected_value!r}, "
                f"got {actual_value!r}."
            )
    return failures


def _check_matrix_case(case: Mapping[str, Any], baseline: AdminCompatibilityBaseline) -> list[str]:
    case_name = case.get("name")
    if not isinstance(case_name, str) or not case_name:
        return ["Matrix case is missing a non-empty string name."]

    expected = case.get("expected")
    if not isinstance(expected, Mapping):
        return [f"{case_name}: expected must be an object."]
    expected_supported = expected.get("supported")
    if not isinstance(expected_supported, bool):
        return [f"{case_name}: expected.supported must be a boolean."]

    if "compatibility" not in case:
        return [f"{case_name}: compatibility must be present as an object or null."]

    raw_compatibility = case["compatibility"]
    if raw_compatibility is None:
        compatibility = None
    elif isinstance(raw_compatibility, Mapping):
        compatibility = AdminCompatibilityMetadata.from_dict(dict(raw_compatibility))
    else:
        return [f"{case_name}: compatibility must be an object or null."]

    result = evaluate_admin_compatibility(compatibility, baseline)
    failures = []
    if result.supported != expected_supported:
        failures.append(
            f"{case_name}: expected supported={expected_supported!r}, "
            f"got supported={result.supported!r}; reasons={result.reasons!r}."
        )

    expected_reasons, reason_failures = _expected_strings(case_name, expected, "reasonsContain")
    failures.extend(reason_failures)
    for expected_reason in expected_reasons:
        if not _contains_any(result.reasons, expected_reason):
            failures.append(
                f"{case_name}: no compatibility reason contained {expected_reason!r}; "
                f"reasons={result.reasons!r}."
            )

    expected_warnings, warning_failures = _expected_strings(case_name, expected, "warningsContain")
    failures.extend(warning_failures)
    for expected_warning in expected_warnings:
        if not _contains_any(result.warnings, expected_warning):
            failures.append(
                f"{case_name}: no compatibility warning contained {expected_warning!r}; "
                f"warnings={result.warnings!r}."
            )

    failures.extend(_check_expected_features(case_name, result, expected))
    return failures


def check_server_matrix(path: Path = MATRIX_PATH) -> list[str]:
    try:
        matrix = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [f"Compatibility server matrix is missing: {path}"]

    if not isinstance(matrix, Mapping):
        return ["Compatibility server matrix must be a JSON object."]

    failures = []
    if matrix.get("schemaVersion") != 1:
        failures.append("Compatibility server matrix schemaVersion must be 1.")

    raw_baseline = matrix.get("baseline")
    if not isinstance(raw_baseline, Mapping):
        failures.append("Compatibility server matrix baseline must be an object.")
        baseline = AdminCompatibilityBaseline()
    else:
        parsed_baseline, baseline_failures = _baseline_from_matrix(raw_baseline)
        if baseline_failures:
            failures.extend(baseline_failures)
            baseline = AdminCompatibilityBaseline()
        else:
            assert parsed_baseline is not None
            baseline = parsed_baseline
            code_baseline = AdminCompatibilityBaseline()
            if baseline != code_baseline:
                failures.append(
                    "Compatibility matrix baseline does not match honua_admin "
                    f"constants: matrix={baseline!r}, code={code_baseline!r}."
                )

    cases = matrix.get("cases")
    if not isinstance(cases, list) or not cases:
        failures.append("Compatibility server matrix must include at least one case.")
        return failures

    for case in cases:
        if not isinstance(case, Mapping):
            failures.append("Compatibility server matrix cases must be objects.")
            continue
        failures.extend(_check_matrix_case(case, baseline))

    return failures


def run_gate() -> list[str]:
    failures = []
    failures.extend(check_public_api_snapshot())
    failures.extend(check_server_matrix())
    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update-api-snapshot",
        action="store_true",
        help="Rewrite compatibility/public-api.json from the current public SDK surface.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.update_api_snapshot:
        update_api_snapshot()
        print(f"Updated {API_SNAPSHOT_PATH.relative_to(ROOT)}")
        return 0

    failures = run_gate()
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print("Compatibility gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
