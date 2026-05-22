"""``arcpy.da`` shim -- 10 functions (3 cursor classes mapped, 7 stubbed).

The cursor classes implement context-manager semantics on top of the
:class:`honua_sdk.source.Source` facade:

* ``SearchCursor`` -- read-only iteration over ``Source.iter_features``.
* ``UpdateCursor`` -- buffered updates flushed on ``__exit__`` or
  ``cursor.flush()``.
* ``InsertCursor`` -- buffered inserts flushed on ``__exit__`` or
  ``cursor.flush()``.

The remaining 7 entries (Editor, Walk, the NumPy bridges, ExtendTable) raise
:class:`~honua_arcpy._errors.HonuaArcpyUnsupportedError` with a tracking
ticket. They are listed in the compatibility manifest so the matrix and
``honua-arcpy assess`` show them.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator, Sequence
from typing import Any

from .._audit import _shape_of, record_call
from .._compat import anchor_for
from .._dispatch import raise_unsupported
from .._errors import (
    ExecuteError,
    HonuaArcpyConfigurationError,
)
from .._resolve import resolve
from .._session import get_session


def _client_source(name: str) -> Any:
    session = get_session()
    client = session.client()
    if not hasattr(client, "source"):
        raise HonuaArcpyConfigurationError("Configured Honua client does not expose Source facade.")
    alias = session.get_layer(name)
    source_name = alias.source if alias is not None else resolve(name, session=session).source
    return client.source(source_name), alias


def _values_for_row(feature: Any, fields: Sequence[str]) -> tuple[Any, ...]:
    if hasattr(feature, "attributes"):
        attrs = dict(feature.attributes or {})
    elif isinstance(feature, dict):
        attrs = dict(feature.get("attributes") or feature.get("properties") or {})
    else:
        attrs = {}

    geometry = getattr(feature, "geometry", None)
    if geometry is None and isinstance(feature, dict):
        geometry = feature.get("geometry")

    out: list[Any] = []
    for field in fields:
        if field.upper() in {"SHAPE@", "SHAPE@JSON"}:
            out.append(_shape_value(geometry, field.upper()))
        elif field.upper() == "OID@":
            out.append(attrs.get("OBJECTID") or attrs.get("oid") or attrs.get("FID"))
        else:
            out.append(attrs.get(field))
    return tuple(out)


def _shape_value(geometry: Any, token: str) -> Any:
    if geometry is None:
        return None
    if token == "SHAPE@JSON":
        try:
            return json.dumps(geometry)
        except (TypeError, ValueError):
            return None
    return geometry


def _payload_for_row(row: Sequence[Any], fields: Sequence[str]) -> dict[str, Any]:
    attributes: dict[str, Any] = {}
    geometry: Any | None = None
    for value, field in zip(row, fields, strict=True):
        upper = field.upper()
        if upper in {"SHAPE@", "SHAPE@JSON"}:
            if isinstance(value, str) and upper == "SHAPE@JSON":
                try:
                    geometry = json.loads(value)
                except (TypeError, ValueError):
                    geometry = None
            else:
                geometry = value
        elif upper == "OID@":
            attributes["OBJECTID"] = value
        else:
            attributes[field] = value
    payload: dict[str, Any] = {"attributes": attributes}
    if geometry is not None:
        payload["geometry"] = geometry
    return payload


class _BaseCursor:
    """Common scaffolding for cursor classes."""

    qualified_name: str = ""

    def __init__(
        self,
        in_table: str,
        field_names: str | Sequence[str],
        where_clause: str | None = None,
        **extra: Any,
    ) -> None:
        if isinstance(field_names, str):
            self.fields: tuple[str, ...] = (field_names,)
        else:
            self.fields = tuple(field_names)
        self.in_table = str(in_table)
        self.where_clause = where_clause
        self.extra = extra
        self._record_cm = None
        self._record: dict[str, Any] | None = None
        self._entered = False
        self._closed = False

    def __enter__(self) -> "_BaseCursor":
        self._record_cm = record_call(
            self.qualified_name,
            args=(self.in_table, list(self.fields), self.where_clause),
            kwargs=self.extra,
            writer=get_session().audit_writer(),
        )
        self._record = self._record_cm.__enter__()
        self._entered = True
        self._open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        try:
            self._close(exc_type, exc, tb)
        finally:
            if self._record_cm is not None:
                self._record_cm.__exit__(exc_type, exc, tb)
                self._record_cm = None
            self._closed = True
            self._entered = False

    def __iter__(self) -> Iterator[Any]:
        self._ensure_open()
        return self

    def __next__(self) -> Any:  # pragma: no cover - overridden
        raise NotImplementedError

    def reset(self) -> None:
        """Re-iterate from the start; mirrors arcpy cursor semantics."""

        self._ensure_open()
        self._reset()

    def close(self) -> None:
        if not self._closed and self._entered:
            self.__exit__(None, None, None)

    # subclasses implement these
    def _open(self) -> None: ...
    def _close(self, exc_type, exc, tb) -> None: ...
    def _reset(self) -> None: ...

    def _ensure_open(self) -> None:
        if not self._entered:
            raise HonuaArcpyConfigurationError(
                f"{self.qualified_name} must be used as a context manager: with arcpy.da.{self.qualified_name.split('.')[-1]}(...) as cursor:"
            )


class SearchCursor(_BaseCursor):
    """Read-only iteration over the configured Honua source."""

    qualified_name = "da.SearchCursor"

    def __init__(
        self,
        in_table: str,
        field_names: str | Sequence[str],
        where_clause: str | None = None,
        spatial_reference: Any = None,
        explode_to_points: bool | None = None,
        sql_clause: Any = None,
    ) -> None:
        super().__init__(
            in_table,
            field_names,
            where_clause,
            spatial_reference=spatial_reference,
            explode_to_points=explode_to_points,
            sql_clause=sql_clause,
        )
        self._iterator: Iterator[Any] | None = None
        self._count = 0

    def _open(self) -> None:
        source, _alias = _client_source(self.in_table)
        self._source = source

    def _query_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if self.where_clause:
            kwargs["where"] = self.where_clause
        if self.extra.get("spatial_reference") is not None:
            kwargs["out_sr"] = self.extra["spatial_reference"]
        return kwargs

    def _reset(self) -> None:
        self._iterator = None
        self._count = 0

    def __next__(self) -> tuple[Any, ...]:
        if self._iterator is None:
            self._iterator = iter(self._source.iter_features(**self._query_kwargs()))
        try:
            feature = next(self._iterator)
        except StopIteration:
            if self._record is not None:
                self._record["result_shape"] = _shape_of({"rows": self._count})
            raise
        self._count += 1
        return _values_for_row(feature, self.fields)

    def _close(self, exc_type, exc, tb) -> None:
        if self._record is not None and self._record.get("result_shape") is None:
            self._record["result_shape"] = _shape_of({"rows": self._count})


class UpdateCursor(_BaseCursor):
    """Buffered updates flushed on context-exit or explicit ``cursor.flush()``."""

    qualified_name = "da.UpdateCursor"

    def __init__(
        self,
        in_table: str,
        field_names: str | Sequence[str],
        where_clause: str | None = None,
    ) -> None:
        super().__init__(in_table, field_names, where_clause)
        self._iterator: Iterator[Any] | None = None
        self._current_feature: Any | None = None
        self._updates: list[dict[str, Any]] = []
        self._deletes: list[Any] = []
        self._count = 0
        self._updated = 0
        self._deleted = 0

    def _open(self) -> None:
        self._source, _alias = _client_source(self.in_table)

    def _reset(self) -> None:
        self._iterator = None
        self._current_feature = None
        self._count = 0

    def __next__(self) -> list[Any]:
        if self._iterator is None:
            kwargs: dict[str, Any] = {}
            if self.where_clause:
                kwargs["where"] = self.where_clause
            self._iterator = iter(self._source.iter_features(**kwargs))
        try:
            feature = next(self._iterator)
        except StopIteration:
            if self._record is not None:
                self._record["result_shape"] = _shape_of({
                    "rows": self._count,
                    "updates": self._updated,
                    "deletes": self._deleted,
                })
            raise
        self._current_feature = feature
        self._count += 1
        return list(_values_for_row(feature, self.fields))

    def updateRow(self, row: Sequence[Any]) -> None:
        self._ensure_open()
        if self._current_feature is None:
            raise HonuaArcpyConfigurationError("updateRow called before the cursor produced a row.")
        payload = _payload_for_row(row, self.fields)
        oid = self._extract_oid(self._current_feature)
        if oid is None:
            raise HonuaArcpyConfigurationError("updateRow requires an OID-bearing row; include OID@ in field_names.")
        payload.setdefault("attributes", {})["OBJECTID"] = oid
        self._updates.append(payload)
        self._updated += 1

    def deleteRow(self) -> None:
        self._ensure_open()
        if self._current_feature is None:
            raise HonuaArcpyConfigurationError("deleteRow called before the cursor produced a row.")
        oid = self._extract_oid(self._current_feature)
        if oid is None:
            raise HonuaArcpyConfigurationError("deleteRow requires an OID-bearing row; include OID@ in field_names.")
        self._deletes.append(oid)
        self._deleted += 1

    def flush(self) -> dict[str, Any] | None:
        """Send buffered updates / deletes to the server. Safe to call repeatedly."""

        if not self._updates and not self._deletes:
            return None
        if not hasattr(self._source, "apply_edits"):
            raise HonuaArcpyConfigurationError("Configured source does not expose apply_edits.")
        kwargs: dict[str, Any] = {}
        if self._updates:
            kwargs["updates"] = list(self._updates)
        if self._deletes:
            kwargs["deletes"] = list(self._deletes)
        result = self._source.apply_edits(**kwargs)
        self._updates.clear()
        self._deletes.clear()
        return getattr(result, "to_dict", lambda: result)()

    def _close(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            return
        self.flush()
        if self._record is not None and self._record.get("result_shape") is None:
            self._record["result_shape"] = _shape_of({
                "rows": self._count,
                "updates": self._updated,
                "deletes": self._deleted,
            })

    def _extract_oid(self, feature: Any) -> Any:
        attrs = getattr(feature, "attributes", None) or (feature.get("attributes") if isinstance(feature, dict) else None) or {}
        return attrs.get("OBJECTID") or attrs.get("oid") or attrs.get("FID")


class InsertCursor(_BaseCursor):
    """Buffered inserts flushed on context-exit or explicit ``cursor.flush()``."""

    qualified_name = "da.InsertCursor"

    def __init__(self, in_table: str, field_names: str | Sequence[str]) -> None:
        super().__init__(in_table, field_names, None)
        self._inserts: list[dict[str, Any]] = []
        self._inserted = 0

    def _open(self) -> None:
        self._source, _alias = _client_source(self.in_table)

    def _reset(self) -> None:  # InsertCursor doesn't iterate; reset clears buffer
        self._inserts.clear()
        self._inserted = 0

    def insertRow(self, row: Sequence[Any]) -> int:
        self._ensure_open()
        payload = _payload_for_row(row, self.fields)
        self._inserts.append(payload)
        self._inserted += 1
        return self._inserted  # arcpy returns the new OID; we return a 1-based index pre-flush.

    def flush(self) -> dict[str, Any] | None:
        if not self._inserts:
            return None
        if not hasattr(self._source, "apply_edits"):
            raise HonuaArcpyConfigurationError("Configured source does not expose apply_edits.")
        result = self._source.apply_edits(adds=list(self._inserts))
        self._inserts.clear()
        return getattr(result, "to_dict", lambda: result)()

    def _close(self, exc_type, exc, tb) -> None:
        if exc_type is not None:
            return
        self.flush()
        if self._record is not None and self._record.get("result_shape") is None:
            self._record["result_shape"] = _shape_of({"inserts": self._inserted})


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------


def Editor(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("da.Editor")


def Walk(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("da.Walk")


def TableToNumPyArray(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("da.TableToNumPyArray")


def FeatureClassToNumPyArray(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("da.FeatureClassToNumPyArray")


def NumPyArrayToTable(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("da.NumPyArrayToTable")


def NumPyArrayToFeatureClass(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("da.NumPyArrayToFeatureClass")


def ExtendTable(*args: Any, **kwargs: Any) -> Any:
    raise_unsupported("da.ExtendTable")


__all__ = [
    "Editor",
    "ExtendTable",
    "FeatureClassToNumPyArray",
    "InsertCursor",
    "NumPyArrayToFeatureClass",
    "NumPyArrayToTable",
    "SearchCursor",
    "TableToNumPyArray",
    "UpdateCursor",
    "Walk",
]
