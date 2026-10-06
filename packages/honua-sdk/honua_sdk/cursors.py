"""arcpy.da-style cursor ergonomics over the canonical Source facade.

Esri's core geoprocessing data-access idiom is the ``arcpy.da`` cursor family —
``SearchCursor`` to iterate rows lazily, ``InsertCursor`` / ``UpdateCursor`` to
write rows back. The Honua SDK already exposes a streaming query and a batched
``apply_edits`` helper; this module wraps them into the familiar cursor shape so
a GP tool can "iterate rows, edit, write back" without re-implementing batching.

The cursors are thin: :class:`SearchCursor` defers entirely to
``Source.stream`` (lazy, never materializing the full result), and
:class:`UpdateCursor` / :class:`InsertCursor` accumulate edits and flush them
through ``Source.apply_edits`` in batches. Geometry on a row is exposed as a
Shapely geometry via the feature's first-class ``__geo_interface__`` bridge,
matching the ``arcpy`` ``row[0] is SHAPE`` convention.
"""

from __future__ import annotations

from collections.abc import (
    AsyncIterator,
    Iterator,
    Mapping,
    Sequence,
)
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from .errors import HonuaError
from .models import ApplyEditsResult, QueryFeature

if TYPE_CHECKING:  # pragma: no cover - typing only
    from shapely.geometry.base import BaseGeometry

    from .source import AsyncSource, Source

#: Pseudo-field name selecting a row's geometry, mirroring ``arcpy``'s
#: ``"SHAPE@"`` token. When present in a cursor's ``fields`` it maps to the
#: row's Shapely geometry rather than an attribute.
SHAPE_TOKEN = "SHAPE@"  # noqa: S105 -- a geometry field token, not a credential


@dataclass(frozen=True)
class Row:
    """A single cursor row: a feature's geometry plus its attribute mapping.

    Mirrors an ``arcpy.da`` cursor row. :meth:`values` projects the row onto a
    requested field tuple (with the ``"SHAPE@"`` token selecting geometry),
    giving the positional-tuple ergonomic GP tools expect.
    """

    feature: QueryFeature

    @property
    def attributes(self) -> Mapping[str, Any]:
        """The feature's attribute mapping (GeoJSON ``properties``)."""
        return self.feature.properties

    @property
    def geometry(self) -> "BaseGeometry | None":
        """The row geometry as a Shapely geometry (``None`` when absent)."""
        return self.feature.geometry_shape

    @property
    def object_id(self) -> int | None:
        for key in ("objectid", "objectId", "OBJECTID"):
            value = self.feature.properties.get(key)
            if value is not None:
                return int(value)
        if isinstance(self.feature.id, int):
            return self.feature.id
        return None

    def values(self, fields: Sequence[str]) -> tuple[Any, ...]:
        """Project the row onto *fields* as a positional tuple.

        The ``"SHAPE@"`` token yields the Shapely geometry; every other name is
        looked up in the attribute mapping (``None`` when missing).
        """
        out: list[Any] = []
        for name in fields:
            if name == SHAPE_TOKEN:
                out.append(self.geometry)
            else:
                out.append(self.feature.properties.get(name))
        return tuple(out)


def _esri_feature_from(
    attributes: Mapping[str, Any],
    geometry: Mapping[str, Any] | None,
) -> dict[str, Any]:
    feature: dict[str, Any] = {"attributes": dict(attributes)}
    if geometry is not None:
        feature["geometry"] = dict(geometry)
    return feature


def _search_kwargs(
    query_kwargs: Mapping[str, Any],
    where: str | None,
    geometry_filter: Mapping[str, Any] | None,
    fields: tuple[str, ...] | None,
) -> dict[str, Any]:
    kwargs = dict(query_kwargs)
    if where is not None:
        kwargs.setdefault("where", where)
    if geometry_filter is not None:
        kwargs.setdefault("spatial_filter", {"geometry": geometry_filter})
    if fields is not None:
        attr_fields = [f for f in fields if f != SHAPE_TOKEN]
        if attr_fields and "out_fields" not in kwargs:
            kwargs["out_fields"] = attr_fields
    return kwargs


def _snapshot_object_id(row: Row) -> int:
    object_id = row.object_id
    if object_id is None:
        raise ValueError("UpdateCursor rows need an object id (OBJECTID) to snapshot the query.")
    return object_id


def _chunk_overrides(stream_kwargs: Mapping[str, Any], object_ids: Sequence[int]) -> dict[str, Any]:
    """Query overrides that re-fetch one snapshot chunk by object id.

    The original predicate stays applied, so rows edited elsewhere since the
    snapshot drop out, and any caller offset is reset so it cannot skip rows
    inside the chunk.
    """
    query = stream_kwargs.get("query")
    base = (query.get("extra_params") if isinstance(query, Mapping) else getattr(query, "extra_params", None)) or {}
    extra_params = {
        **dict(base),
        **dict(stream_kwargs.get("extra_params") or {}),
        "objectIds": ",".join(str(oid) for oid in object_ids),
        "resultOffset": 0,
    }
    return {"extra_params": extra_params}


class SearchCursor:
    """Lazy row iterator over a source query (``arcpy.da.SearchCursor`` analogue).

    Wraps :meth:`Source.stream`, yielding :class:`Row` objects one at a time so
    a tool never materializes the whole result. Pass ``fields`` to iterate
    positional value tuples (with ``"SHAPE@"`` selecting geometry) instead of
    rows. Supports the context-manager and iterator protocols.
    """

    def __init__(
        self,
        source: "Source",
        *,
        fields: Sequence[str] | None = None,
        where: str | None = None,
        geometry_filter: Mapping[str, Any] | None = None,
        **query_kwargs: Any,
    ) -> None:
        self._source = source
        self._fields = tuple(fields) if fields is not None else None
        self._where = where
        self._geometry_filter = geometry_filter
        self._query_kwargs = query_kwargs

    @property
    def fields(self) -> tuple[str, ...] | None:
        return self._fields

    def _stream_kwargs(self) -> dict[str, Any]:
        return _search_kwargs(self._query_kwargs, self._where, self._geometry_filter, self._fields)

    def _rows(self, **overrides: Any) -> Iterator[Row]:
        for feature in self._source.stream(**{**self._stream_kwargs(), **overrides}):
            yield Row(feature=feature)

    def __iter__(self) -> Iterator[Any]:
        for row in self._rows():
            yield row.values(self._fields) if self._fields is not None else row

    def rows(self) -> Iterator[Row]:
        """Iterate :class:`Row` objects regardless of the ``fields`` selection."""
        yield from self._rows()

    def __enter__(self) -> "SearchCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None


class _EditBuffer:
    """Shared add/update accumulation + batched flush for the write cursors."""

    def __init__(self, batch_size: int) -> None:
        if batch_size <= 0:
            raise ValueError("batch_size must be greater than zero.")
        self.batch_size = batch_size
        self.adds: list[dict[str, Any]] = []
        self.updates: list[dict[str, Any]] = []
        self.results: list[ApplyEditsResult] = []

    @property
    def pending(self) -> int:
        return len(self.adds) + len(self.updates)


class _BaseWriteCursor:
    def __init__(self, source: Any, *, batch_size: int, rollback_on_failure: bool) -> None:
        self._source = source
        self._buffer = _EditBuffer(batch_size)
        self._rollback_on_failure = rollback_on_failure

    @property
    def results(self) -> tuple[ApplyEditsResult, ...]:
        """All :class:`ApplyEditsResult` envelopes returned by flushed batches."""
        return tuple(self._buffer.results)

    def _record_result(self, result: ApplyEditsResult) -> None:
        self._buffer.results.append(result)
        if not result.all_succeeded:
            failed = sum(
                not item.success for item in (*result.add_results, *result.update_results, *result.delete_results)
            )
            raise HonuaError(f"applyEdits reported {failed} failed row operation(s).")


class InsertCursor(_BaseWriteCursor):
    """Batched feature inserts (``arcpy.da.InsertCursor`` analogue).

    Accumulate rows with :meth:`insert_row`; they are flushed to the source via
    ``Source.apply_edits(adds=...)`` once ``batch_size`` is reached, on
    :meth:`flush`, or when the context manager exits.
    """

    def __init__(
        self,
        source: "Source",
        *,
        batch_size: int = 200,
        rollback_on_failure: bool = True,
    ) -> None:
        super().__init__(source, batch_size=batch_size, rollback_on_failure=rollback_on_failure)

    def insert_row(
        self,
        attributes: Mapping[str, Any],
        geometry: Mapping[str, Any] | None = None,
    ) -> None:
        """Queue a feature for insertion, flushing when the batch fills."""
        self._buffer.adds.append(_esri_feature_from(attributes, geometry))
        if self._buffer.pending >= self._buffer.batch_size:
            self.flush()

    def flush(self) -> ApplyEditsResult | None:
        """Write any pending inserts; returns the batch result or ``None``."""
        if not self._buffer.adds:
            return None
        result = cast(
            ApplyEditsResult,
            self._source.apply_edits(adds=self._buffer.adds, rollback_on_failure=self._rollback_on_failure),
        )
        self._buffer.adds = []
        self._record_result(result)
        return result

    def __enter__(self) -> "InsertCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        if exc[0] is None:
            self.flush()


class UpdateCursor(_BaseWriteCursor):
    """Iterate rows and write edits back (``arcpy.da.UpdateCursor`` analogue).

    Iterating yields :class:`Row` objects (lazily, via a search cursor). Call
    :meth:`update_row` with new attributes/geometry to queue an update keyed by
    the row's object id; queued updates flush in batches through
    ``Source.apply_edits(updates=...)`` on :meth:`flush` / context-manager exit.
    """

    def __init__(
        self,
        source: "Source",
        *,
        fields: Sequence[str] | None = None,
        where: str | None = None,
        geometry_filter: Mapping[str, Any] | None = None,
        batch_size: int = 200,
        rollback_on_failure: bool = True,
        **query_kwargs: Any,
    ) -> None:
        super().__init__(source, batch_size=batch_size, rollback_on_failure=rollback_on_failure)
        self._search = SearchCursor(
            source,
            fields=fields,
            where=where,
            geometry_filter=geometry_filter,
            **query_kwargs,
        )

    def __iter__(self) -> Iterator[Row]:
        # Snapshot the matching object ids (geometry-free) before allowing
        # writes: a batch flush can otherwise change the predicate while an
        # offset-paged search is still advancing. Full rows are then fetched
        # lazily one batch of ids at a time, so memory stays bounded.
        object_ids = [_snapshot_object_id(row) for row in self._search._rows(return_geometry=False)]
        stream_kwargs = self._search._stream_kwargs()
        for start in range(0, len(object_ids), self._buffer.batch_size):
            chunk = object_ids[start : start + self._buffer.batch_size]
            wanted = set(chunk)
            for row in self._search._rows(**_chunk_overrides(stream_kwargs, chunk)):
                if row.object_id in wanted:
                    wanted.discard(row.object_id)
                    yield row

    def update_row(
        self,
        row: Row,
        *,
        attributes: Mapping[str, Any] | None = None,
        geometry: Mapping[str, Any] | None = None,
    ) -> None:
        """Queue an update for *row*, merging *attributes* over its current ones."""
        object_id = row.object_id
        if object_id is None:
            raise ValueError("Cannot update a row without an object id (OBJECTID).")
        merged = dict(row.feature.properties)
        if attributes:
            merged.update(attributes)
        # Reuse whatever OID key the row already carries (server casing may be
        # 'objectid' or 'objectId'); only add the canonical 'OBJECTID' when none
        # of the recognized variants is present, so the applyEdits payload never
        # ends up with two object-id-like keys for the same row.
        if not any(key in merged for key in ("objectid", "objectId", "OBJECTID")):
            merged["OBJECTID"] = object_id
        geom = geometry if geometry is not None else row.feature.geometry
        self._buffer.updates.append(_esri_feature_from(merged, geom))
        if self._buffer.pending >= self._buffer.batch_size:
            self.flush()

    def flush(self) -> ApplyEditsResult | None:
        """Write any pending updates; returns the batch result or ``None``."""
        if not self._buffer.updates:
            return None
        result = cast(
            ApplyEditsResult,
            self._source.apply_edits(updates=self._buffer.updates, rollback_on_failure=self._rollback_on_failure),
        )
        self._buffer.updates = []
        self._record_result(result)
        return result

    def __enter__(self) -> "UpdateCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        if exc[0] is None:
            self.flush()


# ---------------------------------------------------------------------------
# Async cursor variants
# ---------------------------------------------------------------------------


class AsyncSearchCursor:
    """Async lazy row iterator over a source query (``SearchCursor`` analogue)."""

    def __init__(
        self,
        source: "AsyncSource",
        *,
        fields: Sequence[str] | None = None,
        where: str | None = None,
        geometry_filter: Mapping[str, Any] | None = None,
        **query_kwargs: Any,
    ) -> None:
        self._source = source
        self._fields = tuple(fields) if fields is not None else None
        self._where = where
        self._geometry_filter = geometry_filter
        self._query_kwargs = query_kwargs

    @property
    def fields(self) -> tuple[str, ...] | None:
        return self._fields

    def _stream_kwargs(self) -> dict[str, Any]:
        return _search_kwargs(self._query_kwargs, self._where, self._geometry_filter, self._fields)

    async def _rows(self, **overrides: Any) -> AsyncIterator[Row]:
        async for feature in self._source.stream(**{**self._stream_kwargs(), **overrides}):
            yield Row(feature=feature)

    async def __aiter__(self) -> AsyncIterator[Any]:
        async for row in self._rows():
            yield row.values(self._fields) if self._fields is not None else row

    async def rows(self) -> AsyncIterator[Row]:
        """Iterate :class:`Row` objects regardless of the ``fields`` selection."""
        async for row in self._rows():
            yield row

    async def __aenter__(self) -> "AsyncSearchCursor":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


class AsyncInsertCursor(_BaseWriteCursor):
    """Async batched feature inserts (``InsertCursor`` analogue)."""

    def __init__(
        self,
        source: "AsyncSource",
        *,
        batch_size: int = 200,
        rollback_on_failure: bool = True,
    ) -> None:
        super().__init__(source, batch_size=batch_size, rollback_on_failure=rollback_on_failure)

    def insert_row(
        self,
        attributes: Mapping[str, Any],
        geometry: Mapping[str, Any] | None = None,
    ) -> None:
        """Queue a feature for insertion (flush is explicit on the async cursor)."""
        self._buffer.adds.append(_esri_feature_from(attributes, geometry))

    async def flush(self) -> ApplyEditsResult | None:
        """Write any pending inserts; returns the batch result or ``None``."""
        if not self._buffer.adds:
            return None
        result = cast(
            ApplyEditsResult,
            await self._source.apply_edits(adds=self._buffer.adds, rollback_on_failure=self._rollback_on_failure),
        )
        self._buffer.adds = []
        self._record_result(result)
        return result

    async def __aenter__(self) -> "AsyncInsertCursor":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if exc[0] is None:
            await self.flush()


class AsyncUpdateCursor(_BaseWriteCursor):
    """Async iterate-and-write-back cursor (``UpdateCursor`` analogue)."""

    def __init__(
        self,
        source: "AsyncSource",
        *,
        fields: Sequence[str] | None = None,
        where: str | None = None,
        geometry_filter: Mapping[str, Any] | None = None,
        batch_size: int = 200,
        rollback_on_failure: bool = True,
        **query_kwargs: Any,
    ) -> None:
        super().__init__(source, batch_size=batch_size, rollback_on_failure=rollback_on_failure)
        self._search = AsyncSearchCursor(
            source,
            fields=fields,
            where=where,
            geometry_filter=geometry_filter,
            **query_kwargs,
        )

    async def __aiter__(self) -> AsyncIterator[Row]:
        # See UpdateCursor.__iter__: snapshot ids, then fetch rows per batch.
        object_ids = [_snapshot_object_id(row) async for row in self._search._rows(return_geometry=False)]
        stream_kwargs = self._search._stream_kwargs()
        for start in range(0, len(object_ids), self._buffer.batch_size):
            chunk = object_ids[start : start + self._buffer.batch_size]
            wanted = set(chunk)
            async for row in self._search._rows(**_chunk_overrides(stream_kwargs, chunk)):
                if row.object_id in wanted:
                    wanted.discard(row.object_id)
                    yield row

    def update_row(
        self,
        row: Row,
        *,
        attributes: Mapping[str, Any] | None = None,
        geometry: Mapping[str, Any] | None = None,
    ) -> None:
        """Queue an update for *row*, merging *attributes* over its current ones."""
        object_id = row.object_id
        if object_id is None:
            raise ValueError("Cannot update a row without an object id (OBJECTID).")
        merged = dict(row.feature.properties)
        if attributes:
            merged.update(attributes)
        # Reuse whatever OID key the row already carries (server casing may be
        # 'objectid' or 'objectId'); only add the canonical 'OBJECTID' when none
        # of the recognized variants is present, so the applyEdits payload never
        # ends up with two object-id-like keys for the same row.
        if not any(key in merged for key in ("objectid", "objectId", "OBJECTID")):
            merged["OBJECTID"] = object_id
        geom = geometry if geometry is not None else row.feature.geometry
        self._buffer.updates.append(_esri_feature_from(merged, geom))

    async def flush(self) -> ApplyEditsResult | None:
        """Write any pending updates; returns the batch result or ``None``."""
        if not self._buffer.updates:
            return None
        result = cast(
            ApplyEditsResult,
            await self._source.apply_edits(updates=self._buffer.updates, rollback_on_failure=self._rollback_on_failure),
        )
        self._buffer.updates = []
        self._record_result(result)
        return result

    async def __aenter__(self) -> "AsyncUpdateCursor":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if exc[0] is None:
            await self.flush()
