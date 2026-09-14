"""Bind arcpy output names to the inline results of honua-server GP jobs.

honua-server's layer-aware processes (``analytics.buffer-aggregate``,
``analytics.spatial-join``, ``generalization.dissolve``,
``conversion.feature-project``) return their FeatureLayer result *by value*:
the ``/jobs/{id}/results`` document carries ``outputFeatureLayer`` whose
``value`` is a GeoJSON FeatureCollection. Nothing is written to a server
layer, so the only real artifact an arcpy output name can be bound to is that
collection.

:func:`read_output_artifact` validates the results document and returns the
artifact, raising a typed :class:`ExecuteError` when the output is missing or
unreadable. :class:`OutputArtifactSource` serves ``GetCount`` /
``SearchCursor`` reads from the artifact and refuses every operation it cannot
honour (where clauses, output spatial references, ordering, edits) instead of
answering from a different dataset.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from ._errors import ExecuteError

OUTPUT_SOURCE_PREFIX = "honua-gp-output://"
OUTPUT_READ_ONLY_REASON = (
    "job results are read-only; persist the output through an authorized server write contract first"
)
_FEATURE_LAYER_OUTPUT = "outputFeatureLayer"
_BASE64_MARKER = ";base64,"
_RESULT_DOCUMENT_KEYS = frozenset({"jobID", "jobId", "links"})


@dataclass(frozen=True)
class OutputArtifact:
    """A completed job's FeatureLayer output, held by value."""

    function: str
    job_id: str
    output_id: str
    features: tuple[Mapping[str, Any], ...]
    srid: int | None = None
    """Spatial reference of the geometries when the collection declares it
    (``srid`` / ``inputSrid``); layer-aware outputs without one are in the
    input layer's storage CRS."""
    origin: str | None = None
    """``honua://services/<service>/<layer>`` the job read, when known."""

    @property
    def source(self) -> str:
        """Opaque identity recorded on the alias; never a server layer locator."""

        return f"{OUTPUT_SOURCE_PREFIX}{self.job_id}/{self.output_id}"


def _failure(function: str, job_id: str, kind: str, detail: str, compat_anchor: str | None) -> ExecuteError:
    return ExecuteError(
        f"{function} job {job_id or '<unknown>'} reported success but {detail}; "
        "the output name was not bound to any dataset.",
        function=function,
        error_kind=kind,
        compat_anchor=compat_anchor,
    )


def _outputs_map(results: Any) -> Mapping[str, Any]:
    if not isinstance(results, Mapping):
        return {}
    wrapped = results.get("outputs")
    if isinstance(wrapped, Mapping):
        return wrapped
    # honua-server answers /jobs/{id}/results with the outputs map itself.
    return {key: value for key, value in results.items() if key not in _RESULT_DOCUMENT_KEYS}


def _decode_data_uri(href: str) -> Any:
    if not href.startswith("data:") or _BASE64_MARKER not in href:
        return None
    try:
        return json.loads(base64.b64decode(href.split(_BASE64_MARKER, 1)[1], validate=True))
    except (binascii.Error, ValueError):
        return None


def read_output_artifact(
    results: Any,
    *,
    function: str,
    job_id: str,
    compat_anchor: str | None = None,
) -> OutputArtifact:
    """Validate a successful job's results document and return its FeatureLayer output.

    ``missing_output``: no outputs, no FeatureLayer output, or an output with no
    value. ``unreadable_output``: an ambiguous FeatureLayer output, a
    by-reference href that is not a GeoJSON data URI, a value that is not a
    FeatureCollection, or a collection whose ``featureCount`` disagrees with
    the features it carries. An empty FeatureCollection is a valid output.
    """

    outputs = _outputs_map(results)
    if not outputs:
        raise _failure(function, job_id, "missing_output", "its results document carried no outputs", compat_anchor)

    if _FEATURE_LAYER_OUTPUT in outputs:
        output_id = _FEATURE_LAYER_OUTPUT
    else:
        candidates = sorted(str(key) for key in outputs if str(key).startswith(_FEATURE_LAYER_OUTPUT))
        if len(candidates) != 1:
            names = ", ".join(sorted(str(key) for key in outputs))
            kind = "unreadable_output" if candidates else "missing_output"
            raise _failure(
                function, job_id, kind, f"its results carried no single FeatureLayer output (outputs: {names})",
                compat_anchor,
            )
        output_id = candidates[0]

    member = outputs[output_id]
    collection: Any = None
    if isinstance(member, Mapping):
        collection = member.get("value")
        href = member.get("href")
        if collection is None and isinstance(href, str):
            collection = _decode_data_uri(href)
            if collection is None:
                raise _failure(
                    function, job_id, "unreadable_output",
                    f"its {output_id} output is a by-reference href honua_gp cannot read", compat_anchor,
                )
    if collection is None:
        raise _failure(function, job_id, "missing_output", f"its {output_id} output carried no value", compat_anchor)

    features = collection.get("features") if isinstance(collection, Mapping) else None
    if (
        not isinstance(collection, Mapping)
        or collection.get("type") != "FeatureCollection"
        or not isinstance(features, list)
        or not all(isinstance(feature, Mapping) for feature in features)
    ):
        raise _failure(
            function, job_id, "unreadable_output", f"its {output_id} output is not a GeoJSON FeatureCollection",
            compat_anchor,
        )
    declared = collection.get("featureCount")
    if isinstance(declared, int) and not isinstance(declared, bool) and declared != len(features):
        raise _failure(
            function, job_id, "unreadable_output",
            f"its {output_id} output declares featureCount={declared} but carries {len(features)} features",
            compat_anchor,
        )
    srid = next(
        (
            value
            for value in (collection.get("srid"), collection.get("inputSrid"))
            if isinstance(value, int) and not isinstance(value, bool) and value > 0
        ),
        None,
    )
    return OutputArtifact(
        function=function, job_id=job_id, output_id=output_id, features=tuple(features), srid=srid
    )


@dataclass(frozen=True)
class OutputQueryResult:
    """``Source.query``-shaped result over an :class:`OutputArtifact`."""

    features: tuple[dict[str, Any], ...]
    total_count: int


class OutputArtifactSource:
    """Read-only ``Source`` facade over a bound :class:`OutputArtifact`.

    Rows carry the feature ``properties`` as ``attributes`` and the GeoJSON
    geometry unchanged (``SHAPE@JSON`` is GeoJSON here, not Esri JSON).
    """

    def __init__(self, artifact: OutputArtifact, *, name: str) -> None:
        self.artifact = artifact
        self.name = name

    def refusal(self, operation: str, reason: str) -> ExecuteError:
        return ExecuteError(
            f"{operation} on {self.name!r} is not supported: it is the inline result of "
            f"{self.artifact.function} job {self.artifact.job_id}, not a server layer, and {reason}.",
            error_kind="unsupported_output_operation",
        )

    def _check(self, where: Any, options: Mapping[str, Any]) -> None:
        if where:
            raise self.refusal(f"where={where!r}", "honua_gp does not evaluate SQL against job results")
        applied = sorted(key for key, value in options.items() if value not in (None, "", [], ()))
        if applied:
            raise self.refusal(", ".join(applied), "those query options are not applied to job results")

    def _rows(self, *, return_geometry: bool) -> Iterator[dict[str, Any]]:
        for feature in self.artifact.features:
            properties = feature.get("properties")
            row: dict[str, Any] = {"attributes": dict(properties) if isinstance(properties, Mapping) else {}}
            geometry = feature.get("geometry")
            if return_geometry and isinstance(geometry, Mapping):
                row["geometry"] = dict(geometry)
            yield row

    def query(self, where: Any = None, **options: Any) -> OutputQueryResult:
        self._check(where, options)
        rows = tuple(self._rows(return_geometry=True))
        return OutputQueryResult(features=rows, total_count=len(rows))

    def iter_features(
        self,
        where: Any = None,
        out_fields: Any = None,
        return_geometry: bool = True,
        **options: Any,
    ) -> Iterator[dict[str, Any]]:
        # out_fields only narrows the payload; rows are picked by field name.
        self._check(where, options)
        return self._rows(return_geometry=bool(return_geometry))

    def apply_edits(self, **_: Any) -> Any:
        raise self.refusal("apply_edits", OUTPUT_READ_ONLY_REASON)


def output_source_for(alias: Any) -> OutputArtifactSource | None:
    """Return a read-only source when ``alias`` is bound to a job output."""

    artifact = getattr(alias, "output", None)
    if not isinstance(artifact, OutputArtifact):
        return None
    return OutputArtifactSource(artifact, name=alias.name)


__all__ = [
    "OUTPUT_READ_ONLY_REASON",
    "OUTPUT_SOURCE_PREFIX",
    "OutputArtifact",
    "OutputArtifactSource",
    "OutputQueryResult",
    "output_source_for",
    "read_output_artifact",
]
