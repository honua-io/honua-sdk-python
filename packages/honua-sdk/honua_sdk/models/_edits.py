"""applyEdits response model dataclasses."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ._helpers import _first_present, _optional_int, _optional_str


@dataclass(frozen=True)
class EditOperationResult:
    """One add, update, or delete result from applyEdits."""

    success: bool
    object_id: int | None = None
    global_id: str | None = None
    error: Mapping[str, Any] | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EditOperationResult":
        return cls(
            success=bool(payload.get("success", False)),
            object_id=_optional_int(_first_present(payload, "objectId", "objectid")),
            global_id=_optional_str(_first_present(payload, "globalId", "globalid")),
            error=dict(payload["error"]) if isinstance(payload.get("error"), Mapping) else None,
            raw=dict(payload),
        )


@dataclass(frozen=True)
class ApplyEditsResult:
    """Typed applyEdits response grouped by operation."""

    add_results: tuple[EditOperationResult, ...] = ()
    update_results: tuple[EditOperationResult, ...] = ()
    delete_results: tuple[EditOperationResult, ...] = ()
    raw: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ApplyEditsResult":
        return cls(
            add_results=_edit_results(payload.get("addResults")),
            update_results=_edit_results(payload.get("updateResults")),
            delete_results=_edit_results(payload.get("deleteResults")),
            raw=dict(payload),
        )

    @property
    def all_succeeded(self) -> bool:
        results = [*self.add_results, *self.update_results, *self.delete_results]
        return bool(results) and all(result.success for result in results)


def _edit_results(value: Any) -> tuple[EditOperationResult, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str):
        return ()
    return tuple(EditOperationResult.from_dict(item) for item in value if isinstance(item, Mapping))
