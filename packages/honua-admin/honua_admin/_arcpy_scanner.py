"""AST-based ArcPy geoprocessing migration inventory scanner."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, parse_qsl, urlsplit, urlunsplit


_ARTIFACT_KIND = "honua.migration.arcpy-script-inventory"
_ARTIFACT_VERSION = "1.0"
_SOURCE_KIND = "arcpy-python-script"

_ARCPY_TOOLBOX_MODULES = {
    "analysis",
    "cartography",
    "conversion",
    "da",
    "ddd",
    "editing",
    "ia",
    "lr",
    "management",
    "md",
    "na",
    "sa",
    "stats",
}

_SUFFIX_TOOLBOXES = {
    "analysis": "analysis",
    "conversion": "conversion",
    "management": "management",
    "data_management": "management",
    "cartography": "cartography",
    "3d": "ddd",
    "spatial": "sa",
    "sa": "sa",
    "ia": "ia",
}

_AUTOMATED_VECTOR_PROCESSES = {
    "buffer": "honua.process.vector.buffer",
    "intersect": "honua.process.vector.intersect",
    "clip": "honua.process.vector.clip",
    "project": "honua.process.vector.project",
}

_RASTER_SURFACE_TOOL_NAMES = {
    "aspect",
    "contour",
    "hillshade",
    "rastercalculator",
    "slope",
    "surfacevolume",
    "viewshed",
}

_RASTER_SURFACE_TERMS = (
    "raster",
    "surface",
    "terrain",
    "tin",
    "mosaic",
)

_DESTRUCTIVE_TOOL_NAMES = {
    "delete",
    "deletefeatures",
    "deletefield",
    "deleterows",
    "truncate",
    "truncatetable",
}

_LICENSE_FUNCTIONS = {
    "CheckExtension",
    "CheckInExtension",
    "CheckOutExtension",
    "ProductInfo",
    "SetProduct",
}

_PATH_EXTENSIONS = (
    ".csv",
    ".dbf",
    ".fgdb",
    ".gdb",
    ".geojson",
    ".gpkg",
    ".json",
    ".lyr",
    ".lyrx",
    ".sde",
    ".shp",
    ".tif",
    ".tiff",
    ".xlsx",
    ".zip",
)

_URL_SCHEMES = {"http", "https", "ftp", "s3", "gs", "az", "file"}
_SENSITIVE_NAME_PATTERN = re.compile(
    r"(api[_-]?key|auth|credential|passwd|password|secret|token)",
    re.IGNORECASE,
)
_SENSITIVE_VALUE_PATTERN = re.compile(
    r"(api[_-]?key|passwd|password|secret|token)\s*[=:]",
    re.IGNORECASE,
)
_WINDOWS_ABSOLUTE_PATTERN = re.compile(r"^[a-zA-Z]:[\\/]")


def _to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def _to_json_value(value: Any) -> Any:
    if is_dataclass(value):
        return _dataclass_to_camel_dict(value)
    if isinstance(value, list):
        return [_to_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _to_json_value(item) for key, item in value.items()}
    return value


def _dataclass_to_camel_dict(instance: Any) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in fields(instance):
        value = getattr(instance, item.name)
        if value is not None:
            result[_to_camel(item.name)] = _to_json_value(value)
    return result


class _JsonModel:
    def to_dict(self) -> dict[str, Any]:
        """Serialize this inventory model to a camelCase JSON dictionary."""
        return _dataclass_to_camel_dict(self)


@dataclass(frozen=True, slots=True)
class ArcPyScriptSource(_JsonModel):
    """Source metadata for a scanned ArcPy script."""

    path: str
    filename: str
    sha256: str
    line_count: int


@dataclass(frozen=True, slots=True)
class ArcPyImport(_JsonModel):
    """ArcPy import statement detected in a script."""

    module: str
    line: int
    name: str | None = None
    alias: str | None = None


@dataclass(frozen=True, slots=True)
class ArcPyParameterReference(_JsonModel):
    """ArcPy geoprocessing parameter read or write detected in a script."""

    function: str
    direction: str
    line: int
    index: int | None = None
    name: str | None = None
    value: Any | None = None


@dataclass(frozen=True, slots=True)
class ArcPyEnvironmentAssignment(_JsonModel):
    """Assignment to arcpy.env or an imported env alias."""

    name: str
    value: Any
    line: int


@dataclass(frozen=True, slots=True)
class ArcPyLicenseCall(_JsonModel):
    """ArcPy product or extension license call detected in a script."""

    function: str
    line: int
    action: str
    extension: str | None = None


@dataclass(frozen=True, slots=True)
class ArcPyToolCall(_JsonModel):
    """ArcPy tool call and conservative migration classification."""

    call: str
    tool: str
    line: int
    classification: str
    category: str
    reason: str
    toolbox: str | None = None
    honua_process_id: str | None = None
    arguments: list[Any] = field(default_factory=list)
    keywords: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ArcPyLiteralReference(_JsonModel):
    """Path, URL, or secret literal detected in a script with safe redaction."""

    kind: str
    value: str
    line: int
    context: str | None = None


@dataclass(frozen=True, slots=True)
class ArcPyScanCompleteness(_JsonModel):
    """Scanner completeness status and warnings."""

    status: str = "complete"
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ArcPyScriptInventorySummary(_JsonModel):
    """Aggregate counts for an ArcPy script inventory."""

    arcpy_import_count: int = 0
    parameter_count: int = 0
    environment_assignment_count: int = 0
    license_call_count: int = 0
    tool_call_count: int = 0
    automated_candidate_count: int = 0
    unsupported_count: int = 0
    manual_review_count: int = 0
    literal_count: int = 0


@dataclass(frozen=True, slots=True)
class ArcPyScriptInventoryArtifact(_JsonModel):
    """Deterministic inventory artifact for an ArcPy geoprocessing script."""

    source: ArcPyScriptSource
    scan_completeness: ArcPyScanCompleteness
    summary: ArcPyScriptInventorySummary
    imports: list[ArcPyImport] = field(default_factory=list)
    parameters: list[ArcPyParameterReference] = field(default_factory=list)
    environments: list[ArcPyEnvironmentAssignment] = field(default_factory=list)
    license_calls: list[ArcPyLicenseCall] = field(default_factory=list)
    tool_calls: list[ArcPyToolCall] = field(default_factory=list)
    literals: list[ArcPyLiteralReference] = field(default_factory=list)
    artifact_kind: str = _ARTIFACT_KIND
    artifact_version: str = _ARTIFACT_VERSION
    source_kind: str = _SOURCE_KIND

    def to_dict(self) -> dict[str, Any]:
        data = _dataclass_to_camel_dict(self)
        return {
            "artifactKind": data.pop("artifactKind"),
            "artifactVersion": data.pop("artifactVersion"),
            "sourceKind": data.pop("sourceKind"),
            **data,
        }


@dataclass(frozen=True, slots=True)
class _ToolClassification:
    classification: str
    category: str
    reason: str
    honua_process_id: str | None = None


@dataclass(frozen=True, slots=True)
class _ToolIdentity:
    tool: str
    normalized_tool: str
    toolbox: str | None


def scan_arcpy_script(path: str | Path) -> ArcPyScriptInventoryArtifact:
    """Scan a Python script file and return a deterministic ArcPy inventory artifact."""
    script_path = Path(path)
    source = script_path.read_text(encoding="utf-8")
    return scan_arcpy_source(source, filename=str(script_path))


def scan_arcpy_source(source: str, *, filename: str = "<memory>") -> ArcPyScriptInventoryArtifact:
    """Scan Python source text and return a deterministic ArcPy inventory artifact."""
    tree = ast.parse(source, filename=filename)
    imports, aliases = _collect_arcpy_imports(tree)
    scanner = _ArcPyAstScanner(aliases)
    scanner.visit(tree)

    warnings: list[str] = []
    if not imports:
        warnings.append("No arcpy imports detected.")

    summary = _build_summary(
        imports=imports,
        parameters=scanner.parameters,
        environments=scanner.environments,
        license_calls=scanner.license_calls,
        tool_calls=scanner.tool_calls,
        literals=scanner.literals,
    )
    script_source = ArcPyScriptSource(
        path=_redact_source_path(filename),
        filename=_source_filename(filename),
        sha256=hashlib.sha256(source.encode("utf-8")).hexdigest(),
        line_count=len(source.splitlines()),
    )
    return ArcPyScriptInventoryArtifact(
        source=script_source,
        scan_completeness=ArcPyScanCompleteness(status="complete", warnings=warnings),
        summary=summary,
        imports=imports,
        parameters=scanner.parameters,
        environments=scanner.environments,
        license_calls=scanner.license_calls,
        tool_calls=scanner.tool_calls,
        literals=scanner.literals,
    )


def _build_summary(
    *,
    imports: Sequence[ArcPyImport],
    parameters: Sequence[ArcPyParameterReference],
    environments: Sequence[ArcPyEnvironmentAssignment],
    license_calls: Sequence[ArcPyLicenseCall],
    tool_calls: Sequence[ArcPyToolCall],
    literals: Sequence[ArcPyLiteralReference],
) -> ArcPyScriptInventorySummary:
    return ArcPyScriptInventorySummary(
        arcpy_import_count=len(imports),
        parameter_count=len(parameters),
        environment_assignment_count=len(environments),
        license_call_count=len(license_calls),
        tool_call_count=len(tool_calls),
        automated_candidate_count=sum(1 for call in tool_calls if call.classification == "automated"),
        unsupported_count=sum(1 for call in tool_calls if call.classification == "unsupported"),
        manual_review_count=sum(1 for call in tool_calls if call.classification == "manual-review"),
        literal_count=len(literals),
    )


class _ArcPyAstScanner(ast.NodeVisitor):
    def __init__(self, aliases: Mapping[str, tuple[str, ...]]) -> None:
        self._aliases = dict(aliases)
        self._literal_context: list[str | None] = []
        self.parameters: list[ArcPyParameterReference] = []
        self.environments: list[ArcPyEnvironmentAssignment] = []
        self.license_calls: list[ArcPyLicenseCall] = []
        self.tool_calls: list[ArcPyToolCall] = []
        self.literals: list[ArcPyLiteralReference] = []

    def visit_Assign(self, node: ast.Assign) -> None:  # noqa: N802
        self._record_environment_assignment(node.targets, node.value, node.lineno)
        self._visit_value_with_context(node.value, _assignment_context(node.targets))

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:  # noqa: N802
        if node.value is None:
            return
        self._record_environment_assignment([node.target], node.value, node.lineno)
        self._visit_value_with_context(node.value, _assignment_context([node.target]))

    def visit_AugAssign(self, node: ast.AugAssign) -> None:  # noqa: N802
        self._record_environment_assignment([node.target], node.value, node.lineno)
        self._visit_value_with_context(node.value, _assignment_context([node.target]))

    def visit_Dict(self, node: ast.Dict) -> None:  # noqa: N802
        for key, value in zip(node.keys, node.values, strict=False):
            context = self._current_literal_context()
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                context = key.value
            if key is not None:
                self.visit(key)
            self._visit_value_with_context(value, context)

    def visit_keyword(self, node: ast.keyword) -> None:
        self._visit_value_with_context(node.value, node.arg)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        path = self._resolve_path(node.func)
        if path is not None and _is_arcpy_path(path):
            self._record_arcpy_call(node, path)

        for arg in node.args:
            self.visit(arg)
        for keyword in node.keywords:
            self.visit(keyword)

    def visit_Constant(self, node: ast.Constant) -> None:  # noqa: N802
        if not isinstance(node.value, str):
            return
        context = self._current_literal_context()
        literal = _literal_reference(node.value, line=node.lineno, context=context)
        if literal is not None:
            self.literals.append(literal)

    def _record_arcpy_call(self, node: ast.Call, path: tuple[str, ...]) -> None:
        function = path[-1]
        if function.startswith("GetParameter"):
            self.parameters.append(_parameter_reference(node, function, "input"))
            return
        if function.startswith("SetParameter"):
            self.parameters.append(_parameter_reference(node, function, "output"))
            return
        if function in _LICENSE_FUNCTIONS:
            self.license_calls.append(_license_call(node, function))
            return

        identity = _tool_identity(path)
        classification = _classify_tool(identity)
        self.tool_calls.append(
            ArcPyToolCall(
                call=".".join(path),
                tool=identity.tool,
                toolbox=identity.toolbox,
                line=node.lineno,
                classification=classification.classification,
                category=classification.category,
                reason=classification.reason,
                honua_process_id=classification.honua_process_id,
                arguments=[_node_preview(arg) for arg in node.args],
                keywords={
                    keyword.arg or "**": _node_preview(keyword.value)
                    for keyword in node.keywords
                },
            )
        )

    def _record_environment_assignment(
        self,
        targets: Sequence[ast.expr],
        value: ast.expr,
        line: int,
    ) -> None:
        for target in targets:
            path = self._resolve_path(target)
            if path is None or len(path) < 3 or path[:2] != ("arcpy", "env"):
                continue
            self.environments.append(
                ArcPyEnvironmentAssignment(
                    name=".".join(path[2:]),
                    value=_node_preview(value, context=path[-1]),
                    line=line,
                )
            )

    def _visit_value_with_context(self, node: ast.AST, context: str | None) -> None:
        self._literal_context.append(context)
        try:
            self.visit(node)
        finally:
            self._literal_context.pop()

    def _current_literal_context(self) -> str | None:
        for context in reversed(self._literal_context):
            if context:
                return context
        return None

    def _resolve_path(self, node: ast.AST) -> tuple[str, ...] | None:
        raw_path = _attribute_path(node)
        if not raw_path:
            return None
        alias = self._aliases.get(raw_path[0])
        if alias is not None:
            return (*alias, *raw_path[1:])
        if raw_path[0] == "arcpy":
            return raw_path
        return None


def _collect_arcpy_imports(tree: ast.AST) -> tuple[list[ArcPyImport], dict[str, tuple[str, ...]]]:
    imports: list[ArcPyImport] = []
    aliases: dict[str, tuple[str, ...]] = {"arcpy": ("arcpy",)}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for imported in node.names:
                if not _is_arcpy_module(imported.name):
                    continue
                module_path = tuple(imported.name.split("."))
                if imported.asname:
                    aliases[imported.asname] = module_path
                else:
                    aliases["arcpy"] = ("arcpy",)
                imports.append(
                    ArcPyImport(
                        module=imported.name,
                        alias=imported.asname,
                        line=node.lineno,
                    )
                )
        elif isinstance(node, ast.ImportFrom) and node.module and _is_arcpy_module(node.module):
            base_path = tuple(node.module.split("."))
            for imported in node.names:
                if imported.name != "*":
                    aliases[imported.asname or imported.name] = (*base_path, imported.name)
                imports.append(
                    ArcPyImport(
                        module=node.module,
                        name=imported.name,
                        alias=imported.asname,
                        line=node.lineno,
                    )
                )

    imports.sort(key=lambda item: (item.line, item.module, item.name or "", item.alias or ""))
    return imports, aliases


def _is_arcpy_module(name: str) -> bool:
    return name == "arcpy" or name.startswith("arcpy.")


def _is_arcpy_path(path: tuple[str, ...]) -> bool:
    return bool(path) and path[0] == "arcpy"


def _attribute_path(node: ast.AST) -> tuple[str, ...] | None:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        parent = _attribute_path(node.value)
        if parent is None:
            return None
        return (*parent, node.attr)
    return None


def _assignment_context(targets: Sequence[ast.expr]) -> str | None:
    names: list[str] = []
    for target in targets:
        name = _target_name(target)
        if name is not None:
            names.append(name)
    return ",".join(names) if names else None


def _target_name(target: ast.expr) -> str | None:
    if isinstance(target, ast.Name):
        return target.id
    path = _attribute_path(target)
    if path is not None:
        return ".".join(path)
    if isinstance(target, (ast.Tuple, ast.List)):
        names = [_target_name(item) for item in target.elts]
        compact = [name for name in names if name]
        return ",".join(compact) if compact else None
    return None


def _parameter_reference(
    node: ast.Call,
    function: str,
    direction: str,
) -> ArcPyParameterReference:
    first_arg = _node_preview(node.args[0]) if node.args else None
    index = first_arg if isinstance(first_arg, int) else None
    name = first_arg if isinstance(first_arg, str) else None
    value = _node_preview(node.args[1]) if direction == "output" and len(node.args) > 1 else None
    return ArcPyParameterReference(
        function=function,
        direction=direction,
        line=node.lineno,
        index=index,
        name=name,
        value=value,
    )


def _license_call(node: ast.Call, function: str) -> ArcPyLicenseCall:
    extension = _node_preview(node.args[0]) if node.args else None
    return ArcPyLicenseCall(
        function=function,
        action=_license_action(function),
        extension=extension if isinstance(extension, str) else None,
        line=node.lineno,
    )


def _license_action(function: str) -> str:
    if function == "CheckOutExtension":
        return "checkout"
    if function == "CheckInExtension":
        return "checkin"
    if function == "CheckExtension":
        return "check"
    if function == "SetProduct":
        return "set-product"
    return "product-info"


def _tool_identity(path: tuple[str, ...]) -> _ToolIdentity:
    toolbox: str | None = None
    raw_tool = path[-1]
    if len(path) >= 3 and path[1] in _ARCPY_TOOLBOX_MODULES:
        toolbox = path[1]
        raw_tool = path[2]
    elif "_" in raw_tool:
        tool_part, suffix = raw_tool.rsplit("_", maxsplit=1)
        toolbox = _SUFFIX_TOOLBOXES.get(suffix.lower())
        if toolbox is not None:
            raw_tool = tool_part

    normalized = _normalize_tool_name(raw_tool)
    return _ToolIdentity(tool=raw_tool, normalized_tool=normalized, toolbox=toolbox)


def _normalize_tool_name(tool: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", tool.casefold())


def _classify_tool(identity: _ToolIdentity) -> _ToolClassification:
    process_id = _AUTOMATED_VECTOR_PROCESSES.get(identity.normalized_tool)
    if process_id is not None:
        return _ToolClassification(
            classification="automated",
            category="vector",
            reason="Known vector geoprocessing tool maps to a Honua process candidate.",
            honua_process_id=process_id,
        )
    if _is_raster_or_surface_tool(identity):
        return _ToolClassification(
            classification="unsupported",
            category="raster-surface",
            reason="Raster, surface, or image analyst processing requires manual migration planning.",
        )
    if identity.normalized_tool in _DESTRUCTIVE_TOOL_NAMES:
        return _ToolClassification(
            classification="manual-review",
            category="destructive",
            reason="Destructive geoprocessing calls are not automated by the migration scanner.",
        )
    if identity.toolbox == "da":
        return _ToolClassification(
            classification="manual-review",
            category="data-access",
            reason="ArcPy data access cursors require manual migration planning.",
        )
    return _ToolClassification(
        classification="manual-review",
        category="unknown",
        reason="No automated Honua process mapping is known for this ArcPy call.",
    )


def _is_raster_or_surface_tool(identity: _ToolIdentity) -> bool:
    if identity.toolbox in {"ia", "sa", "ddd"}:
        return True
    if identity.normalized_tool in _RASTER_SURFACE_TOOL_NAMES:
        return True
    return any(term in identity.normalized_tool for term in _RASTER_SURFACE_TERMS)


def _node_preview(node: ast.AST, *, context: str | None = None) -> Any:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, str):
            return _redact_string(node.value, context=context).value
        if isinstance(node.value, (bool, int, float)) or node.value is None:
            return node.value
    if isinstance(node, ast.Name):
        return {"ref": node.id}
    if isinstance(node, ast.Attribute):
        path = _attribute_path(node)
        if path is not None:
            return {"ref": ".".join(path)}
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [_node_preview(item, context=context) for item in node.elts]
    if isinstance(node, ast.Dict):
        result: dict[str, Any] = {}
        for key, value in zip(node.keys, node.values, strict=False):
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                key_text = key.value
                result[key_text] = _node_preview(value, context=key_text)
            elif key is not None:
                result[json.dumps(_node_preview(key), sort_keys=True)] = _node_preview(value, context=context)
        return result
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        value = _node_preview(node.operand, context=context)
        if isinstance(value, (int, float)):
            return -value
    return {"expression": node.__class__.__name__}


def _literal_reference(value: str, *, line: int, context: str | None) -> ArcPyLiteralReference | None:
    redacted = _redact_string(value, context=context)
    if redacted.kind is None:
        return None
    return ArcPyLiteralReference(
        kind=redacted.kind,
        value=redacted.value,
        context=context,
        line=line,
    )


@dataclass(frozen=True, slots=True)
class _RedactedString:
    value: str
    kind: str | None


def _redact_string(value: str, *, context: str | None = None) -> _RedactedString:
    if _is_sensitive_context(context):
        return _RedactedString("<redacted>", "secret")
    if _looks_like_url(value):
        return _RedactedString(_redact_url(value), "url")
    if _looks_like_bare_secret(value):
        return _RedactedString("<redacted>", "secret")
    if _looks_like_path(value):
        return _RedactedString(_redact_path(value), "path")
    return _RedactedString(value, None)


def _is_sensitive_context(context: str | None) -> bool:
    return bool(context and _SENSITIVE_NAME_PATTERN.search(context))


def _looks_like_bare_secret(value: str) -> bool:
    lowered = value.casefold()
    return "secret" in lowered or "password" in lowered or bool(_SENSITIVE_VALUE_PATTERN.search(value))


def _looks_like_url(value: str) -> bool:
    parsed = urlsplit(value)
    return parsed.scheme.casefold() in _URL_SCHEMES and bool(parsed.netloc or parsed.scheme == "file")


def _redact_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme.casefold() == "file":
        return f"file://{_redact_path(parsed.path)}"

    netloc = parsed.netloc
    if "@" in netloc:
        host = netloc.rsplit("@", maxsplit=1)[1]
        netloc = f"<redacted>@{host}"

    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    redacted_query = "&".join(
        f"{quote(key)}={quote('<redacted>' if _is_sensitive_context(key) else item, safe='<>')}"
        for key, item in query_pairs
    )
    return urlunsplit((parsed.scheme, netloc, parsed.path, redacted_query, parsed.fragment))


def _looks_like_path(value: str) -> bool:
    if not value or "\n" in value:
        return False
    normalized = value.replace("\\", "/")
    lowered = normalized.casefold()
    if normalized.startswith("/") or value.startswith("\\\\") or _WINDOWS_ABSOLUTE_PATTERN.match(value):
        return True
    if any(lowered.endswith(extension) for extension in _PATH_EXTENSIONS):
        return True
    return any(f"{extension}/" in lowered for extension in _PATH_EXTENSIONS)


def _source_filename(value: str) -> str:
    if value == "<memory>":
        return value
    return value.replace("\\", "/").rsplit("/", maxsplit=1)[-1]


def _redact_source_path(value: str) -> str:
    if value == "<memory>":
        return value
    return _redact_path(str(Path(value).resolve()))


def _redact_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    if not (
        normalized.startswith("/")
        or value.startswith("\\\\")
        or _WINDOWS_ABSOLUTE_PATTERN.match(value)
    ):
        return value

    compact = normalized.rstrip("/")
    lowered = compact.casefold()
    for extension in (".gdb", ".sde"):
        marker = f"{extension}/"
        if marker in lowered:
            start = lowered.rfind("/", 0, lowered.index(marker)) + 1
            return f"<local-path>/{compact[start:]}"
        if lowered.endswith(extension):
            return f"<local-path>/{compact.rsplit('/', maxsplit=1)[-1]}"
    basename = compact.rsplit("/", maxsplit=1)[-1]
    return f"<local-path>/{basename}" if basename else "<local-path>"


def main(argv: Sequence[str] | None = None) -> int:
    """Console entry point for scanning ArcPy scripts."""
    parser = argparse.ArgumentParser(description="Scan an ArcPy Python script and emit a Honua inventory artifact.")
    parser.add_argument("script", type=Path, help="Path to the ArcPy Python script to scan.")
    parser.add_argument("-o", "--output", type=Path, help="Write JSON output to this path instead of stdout.")
    args = parser.parse_args(argv)

    artifact = scan_arcpy_script(args.script)
    payload = json.dumps(artifact.to_dict(), indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.write_text(payload, encoding="utf-8")
    else:
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
