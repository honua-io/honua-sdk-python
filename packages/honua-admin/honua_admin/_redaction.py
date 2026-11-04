"""Path, URL and secret redaction heuristics shared by audit logs."""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, quote, urlsplit, urlunsplit

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
