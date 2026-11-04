"""Path, URL and secret redaction shared by audit logs."""

from __future__ import annotations

import pytest

from honua_admin._redaction import (
    _is_sensitive_context,
    _looks_like_bare_secret,
    _looks_like_path,
    _looks_like_url,
    _redact_path,
    _redact_url,
)


@pytest.mark.parametrize("context", ["passwd", "credential", "auth", "api_key", "Token"])
def test_sensitive_contexts(context: str) -> None:
    assert _is_sensitive_context(context)


@pytest.mark.parametrize("context", [None, "", "distance"])
def test_non_sensitive_contexts(context: str | None) -> None:
    assert not _is_sensitive_context(context)


@pytest.mark.parametrize("value", ["api_key=hunter2", "passwd: x", "my secret", "Password1"])
def test_bare_secrets(value: str) -> None:
    assert _looks_like_bare_secret(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://host/path?auth=hunter2", "https://host/path?auth=<redacted>"),
        ("ftp://user:hunter2@host/path", "ftp://<redacted>@host/path"),
        ("https://host/path?f=json", "https://host/path?f=json"),
        ("file:///srv/data/parcels.shp", "file://<local-path>/parcels.shp"),
    ],
)
def test_redact_url(value: str, expected: str) -> None:
    assert _looks_like_url(value)
    assert _redact_url(value) == expected


@pytest.mark.parametrize("value", ["az://container/blob", "s3://bucket/key", "gs://bucket/key"])
def test_object_store_urls_are_urls(value: str) -> None:
    assert _looks_like_url(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/srv/data/parcels.gdb/Parcels", "<local-path>/parcels.gdb/Parcels"),
        ("C:\\GIS\\roads.sde", "<local-path>/roads.sde"),
        ("/srv/data/roads.shp", "<local-path>/roads.shp"),
        ("/", "<local-path>"),
        ("relative/roads.shp", "relative/roads.shp"),
    ],
)
def test_redact_path(value: str, expected: str) -> None:
    assert _redact_path(value) == expected


@pytest.mark.parametrize("value", ["/srv/a", "\\\\server\\share", "C:/x", "roads.zip", "data.gdb/Layer"])
def test_paths(value: str) -> None:
    assert _looks_like_path(value)


@pytest.mark.parametrize("value", ["", "plain text", "line\n/srv/a"])
def test_non_paths(value: str) -> None:
    assert not _looks_like_path(value)
