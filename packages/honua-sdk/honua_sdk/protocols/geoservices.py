"""GeoServices REST FeatureServer/MapServer/ImageServer/GeometryServer protocol clients."""

# ruff: noqa: E501, PLR0913

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import IO, Any, cast

import httpx
from anyio import to_thread

from honua_sdk._http import _encode_path_segment
from honua_sdk.models import Feature, FeatureSet, LayerSchema

from ._base import (
    BboxValue,
    BinaryResponse,
    CsvValue,
    JsonObject,
    Params,
    _AsyncProtocol,
    _bbox,
    _bool_text,
    _csv,
    _iter_page_indices,
    _params,
    _query_value,
    _service_path,
    _SyncProtocol,
)

#: A file argument for :meth:`add_attachment` / :meth:`update_attachment`:
#: a path on disk, an open binary file object, or raw ``bytes``.
AttachmentFile = str | os.PathLike[str] | bytes | IO[bytes]


@dataclass(frozen=True)
class AttachmentInfo:
    """One attachment's metadata, as returned by the FeatureServer.

    Mirrors a GeoServices ``attachmentInfo`` entry (the same shape
    ``arcpy``'s attachment tools and the ArcGIS API for Python's
    ``FeatureLayer.attachments`` surface). ``object_id`` is the attachment's
    own id (used to download/delete it), distinct from the parent feature's
    object id (``parent_object_id``).
    """

    object_id: int
    name: "str | None" = None
    content_type: "str | None" = None
    size: "int | None" = None
    keywords: "str | None" = None
    url: "str | None" = None
    parent_object_id: "int | None" = None
    global_id: "str | None" = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any], *, parent_object_id: "int | None" = None) -> "AttachmentInfo":
        raw_id = payload.get("id", payload.get("objectId"))
        size = payload.get("size")
        return cls(
            object_id=int(raw_id) if raw_id is not None else 0,
            name=_opt_str(payload.get("name")),
            content_type=_opt_str(payload.get("contentType")),
            size=int(size) if isinstance(size, (int, float)) else None,
            keywords=_opt_str(payload.get("keywords")),
            url=_opt_str(payload.get("url")),
            parent_object_id=parent_object_id,
            global_id=_opt_str(payload.get("globalId")),
        )


@dataclass(frozen=True)
class AttachmentQueryResult:
    """Parsed ``queryAttachments`` response.

    ``infos`` is the flattened list of every :class:`AttachmentInfo` across
    all queried features; ``groups`` preserves the per-feature grouping the
    server returns in ``attachmentGroups`` (keyed by ``parentObjectId``).
    """

    infos: "tuple[AttachmentInfo, ...]" = ()
    groups: "Mapping[int, tuple[AttachmentInfo, ...]]" = field(default_factory=dict)
    raw: "JsonObject | None" = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AttachmentQueryResult":
        groups: dict[int, tuple[AttachmentInfo, ...]] = {}
        infos: list[AttachmentInfo] = []
        raw_groups = payload.get("attachmentGroups")
        if isinstance(raw_groups, list):
            for group in raw_groups:
                if not isinstance(group, Mapping):
                    continue
                parent_raw = group.get("parentObjectId")
                parent = int(parent_raw) if isinstance(parent_raw, (int, float)) else None
                group_infos = tuple(
                    AttachmentInfo.from_dict(info, parent_object_id=parent)
                    for info in group.get("attachmentInfos", [])
                    if isinstance(info, Mapping)
                )
                if parent is not None:
                    groups[parent] = group_infos
                infos.extend(group_infos)
        else:
            raw_infos = payload.get("attachmentInfos")
            if isinstance(raw_infos, list):
                infos = [AttachmentInfo.from_dict(info) for info in raw_infos if isinstance(info, Mapping)]
        return cls(infos=tuple(infos), groups=groups, raw=dict(payload))


@dataclass(frozen=True)
class AddAttachmentResult:
    """Parsed ``addAttachment`` response.

    ``object_id`` is the id of the newly created attachment (Esri returns the
    attachment id in ``addAttachmentResult.objectId``), usable directly with
    :meth:`download_attachment` / :meth:`delete_attachment`.
    """

    object_id: "int | None"
    success: bool
    global_id: "str | None" = None
    raw: "JsonObject | None" = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AddAttachmentResult":
        result = payload.get("addAttachmentResult")
        if not isinstance(result, Mapping):
            result = payload
        raw_id = result.get("objectId")
        return cls(
            object_id=int(raw_id) if isinstance(raw_id, (int, float)) else None,
            success=bool(result.get("success", False)),
            global_id=_opt_str(result.get("globalId")),
            raw=dict(payload),
        )


@dataclass(frozen=True)
class UpdateAttachmentResult:
    """Parsed ``updateAttachment`` response."""

    object_id: "int | None"
    success: bool
    global_id: "str | None" = None
    raw: "JsonObject | None" = None

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "UpdateAttachmentResult":
        result = payload.get("updateAttachmentResult")
        if not isinstance(result, Mapping):
            result = payload
        raw_id = result.get("objectId")
        return cls(
            object_id=int(raw_id) if isinstance(raw_id, (int, float)) else None,
            success=bool(result.get("success", False)),
            global_id=_opt_str(result.get("globalId")),
            raw=dict(payload),
        )


@dataclass(frozen=True)
class DeleteAttachmentResult:
    """One entry from a ``deleteAttachments`` response."""

    object_id: "int | None"
    success: bool
    global_id: "str | None" = None

    @classmethod
    def from_list(cls, payload: Mapping[str, Any]) -> "tuple[DeleteAttachmentResult, ...]":
        results = payload.get("deleteAttachmentResults")
        if not isinstance(results, list):
            return ()
        parsed: list[DeleteAttachmentResult] = []
        for entry in results:
            if not isinstance(entry, Mapping):
                continue
            raw_id = entry.get("objectId")
            parsed.append(
                cls(
                    object_id=int(raw_id) if isinstance(raw_id, (int, float)) else None,
                    success=bool(entry.get("success", False)),
                    global_id=_opt_str(entry.get("globalId")),
                )
            )
        return tuple(parsed)


@dataclass(frozen=True)
class AttachmentContent:
    """Downloaded attachment bytes plus the server-reported content type."""

    content: bytes
    content_type: "str | None" = None

    @classmethod
    def from_binary_response(cls, response: "BinaryResponse") -> "AttachmentContent":
        return cls(content=response.content, content_type=response.content_type)


def _opt_str(value: Any) -> "str | None":
    if value is None:
        return None
    text = str(value)
    return text if text else None


def _attachment_ids_csv(attachment_ids: "int | CsvValue") -> str:
    """Normalize an ``attachmentIds`` argument (single id, CSV, or sequence)."""
    if isinstance(attachment_ids, int):
        return str(attachment_ids)
    return _csv(attachment_ids)


def _resolve_object_ids(object_id: "int | None", object_ids: "CsvValue | None") -> str:
    """Normalize the single/plural object-id arguments into the ``objectIds`` CSV.

    ``queryAttachments`` requires an ``objectIds`` filter; supplying neither
    is a usage error.
    """
    if object_ids is not None:
        return _csv(object_ids)
    if object_id is not None:
        return str(object_id)
    raise ValueError("query_attachments requires object_id or object_ids.")


def _attachment_multipart_file(file: AttachmentFile, *, content_type: "str | None") -> "tuple[str, Any, str | None]":
    """Build the httpx ``files`` tuple for a single uploaded attachment.

    The Honua server reads the first uploaded file regardless of field name
    (``form.Files[0]``), so the multipart part is always named ``attachment``
    (the Esri-conventional field name).
    """
    if isinstance(file, bytes):
        return ("upload", file, content_type)
    if isinstance(file, (str, os.PathLike)):
        path = os.fspath(file)
        with open(path, "rb") as handle:
            data = handle.read()
        return (os.path.basename(path), data, content_type)
    # Open binary file object.
    name = getattr(file, "name", None)
    filename = os.path.basename(name) if isinstance(name, str) else "upload"
    return (filename, file.read(), content_type)


class GeoServicesFeatureServerClient(_SyncProtocol):
    """Synchronous GeoServices FeatureServer wrapper.

    Use this client to query, paginate, and edit features on the
    GeoServices ``FeatureServer`` REST surface (``/rest/services/<id>/FeatureServer``).
    Surfaces helpers for layer metadata, paginated ``query`` walks,
    ``applyEdits`` mutations, and related-record lookups; mirrors the
    same shape as :class:`AsyncGeoServicesFeatureServerClient` for async
    callers. Reach this via :meth:`HonuaClient.feature_server`.
    """

    def __init__(self, client: Any, service_id: str) -> None:
        super().__init__(client)
        self.service_id = service_id

    @property
    def path(self) -> str:
        return _service_path(self.service_id, "FeatureServer")

    def metadata(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", self.path, params=_params({"f": response_format}, extra_params))

    def layer_metadata(self, layer_id: int, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", f"{self.path}/{layer_id}", params=_params({"f": response_format}, extra_params))

    def schema(self, layer_id: int, *, extra_params: Params = None) -> LayerSchema:
        """Return a typed :class:`LayerSchema` for a layer (arcpy.Describe analogue).

        Fetches ``layer_metadata`` and parses the raw JSON into typed fields,
        a normalized geometry type, the resolved spatial-reference WKID, and a
        typed extent — so a GP tool maps outputs without hand-parsing JSON.
        """
        return LayerSchema.from_metadata(self.layer_metadata(layer_id, extra_params=extra_params))

    def query(
        self,
        layer_id: int,
        *,
        where: str = "1=1",
        out_fields: CsvValue = "*",
        return_geometry: bool = True,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        return cast(
            JsonObject,
            self.client.query_features(
                self.service_id,
                layer_id,
                where=where,
                out_fields=out_fields,
                return_geometry=return_geometry,
                extra_params=extra_params,
                timeout=timeout,
                extra_headers=extra_headers,
            ),
        )

    def query_pages(
        self,
        layer_id: int,
        *,
        page_size: int = 1000,
        limit: int | None = None,
        max_pages: int | None = 100,
        where: str = "1=1",
        out_fields: CsvValue = "*",
        return_geometry: bool = True,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Iterator[FeatureSet]:
        if page_size <= 0:
            raise ValueError("page_size must be greater than zero.")
        if max_pages is not None and max_pages <= 0:
            raise ValueError("max_pages must be greater than zero (or None for unbounded).")
        if limit is not None and limit <= 0:
            return

        total = 0
        base_extra = dict(extra_params or {})
        offset = int(base_extra.get("resultOffset", 0))
        previous_object_ids: set[int] = set()
        for _ in _iter_page_indices(max_pages):
            remaining = None if limit is None else limit - total
            if remaining is not None and remaining <= 0:
                break
            record_count = page_size if remaining is None else min(page_size, remaining)
            page_extra_params = {
                **base_extra,
                "resultOffset": offset,
                "resultRecordCount": record_count,
            }
            page = FeatureSet.from_dict(
                self.query(
                    layer_id,
                    where=where,
                    out_fields=out_fields,
                    return_geometry=return_geometry,
                    extra_params=page_extra_params,
                    timeout=timeout,
                    extra_headers=extra_headers,
                )
            )
            # Non-advancing-cursor guard: stop before re-yielding a page a
            # server that ignores ``resultOffset`` keeps returning (it would
            # otherwise loop to ``max_pages`` with duplicate features). Compare
            # against the previous page only — not every id seen across the
            # whole walk — so the tracking set stays bounded to a single page on
            # the streaming path.
            new_object_ids = {oid for f in page.features if (oid := f.object_id) is not None}
            if new_object_ids and new_object_ids.issubset(previous_object_ids):
                break
            previous_object_ids = new_object_ids
            yield page
            page_count = len(page.features)
            total += page_count
            if page_count < record_count or not page.exceeded_transfer_limit:
                break
            offset += page_count

    def query_all(
        self,
        layer_id: int,
        *,
        page_size: int = 1000,
        limit: int | None = None,
        max_pages: int | None = 100,
        where: str = "1=1",
        out_fields: CsvValue = "*",
        return_geometry: bool = True,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[Feature]:
        features: list[Feature] = []
        for page in self.query_pages(
            layer_id,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            where=where,
            out_fields=out_fields,
            return_geometry=return_geometry,
            extra_params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            remaining = None if limit is None else limit - len(features)
            page_features = list(page.features) if remaining is None else list(page.features)[:remaining]
            features.extend(page_features)
            if remaining is not None and len(features) >= limit:  # type: ignore[operator]
                break
        return features

    def query_items(
        self,
        layer_id: int,
        *,
        page_size: int = 1000,
        limit: int | None = None,
        max_pages: int | None = 100,
        where: str = "1=1",
        out_fields: CsvValue = "*",
        return_geometry: bool = True,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Iterator[Feature]:
        emitted = 0
        for page in self.query_pages(
            layer_id,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            where=where,
            out_fields=out_fields,
            return_geometry=return_geometry,
            extra_params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            for feature in page.features:
                if limit is not None and emitted >= limit:
                    return
                yield feature
                emitted += 1

    def apply_edits(
        self,
        layer_id: int,
        *,
        adds: Sequence[Mapping[str, Any]] | None = None,
        updates: Sequence[Mapping[str, Any]] | None = None,
        deletes: Sequence[int] | str | None = None,
        rollback_on_failure: bool = True,
        idempotency_key: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        return cast(
            JsonObject,
            self.client.apply_edits(
                self.service_id,
                layer_id,
                adds=adds,
                updates=updates,
                deletes=deletes,
                rollback_on_failure=rollback_on_failure,
                idempotency_key=idempotency_key,
                timeout=timeout,
                extra_headers=extra_headers,
            ),
        )

    def query_related_records(
        self,
        layer_id: int,
        *,
        object_ids: CsvValue,
        relationship_id: int,
        response_format: str = "json",
        extra_params: Params = None,
    ) -> JsonObject:
        params = _params(
            {"f": response_format, "objectIds": _csv(object_ids), "relationshipId": relationship_id},
            extra_params,
        )
        return self._json("GET", f"{self.path}/{layer_id}/queryRelatedRecords", params=params)

    # --- attachments ------------------------------------------------------

    def query_attachments(
        self,
        layer_id: int,
        object_id: int | None = None,
        *,
        object_ids: CsvValue | None = None,
        return_url: bool = False,
        attachment_types: CsvValue | None = None,
        keywords: CsvValue | None = None,
        response_format: str = "json",
        extra_params: Params = None,
    ) -> AttachmentQueryResult:
        """Query attachment metadata for one or more features.

        Wraps ``GET .../{layerId}/queryAttachments``. Pass either a single
        ``object_id`` or a CSV/sequence of ``object_ids`` (one is required).
        Set ``return_url=True`` to have the server include a download ``url``
        on each :class:`AttachmentInfo`.
        """
        ids = _resolve_object_ids(object_id, object_ids)
        params: dict[str, Any] = {"f": response_format, "objectIds": ids}
        if return_url:
            params["returnUrl"] = _bool_text(True)
        if attachment_types is not None:
            params["attachmentTypes"] = _csv(attachment_types)
        if keywords is not None:
            params["keywords"] = _csv(keywords)
        payload = self._json("GET", f"{self.path}/{layer_id}/queryAttachments", params=_params(params, extra_params))
        return AttachmentQueryResult.from_dict(payload)

    def list_attachments(self, layer_id: int, object_id: int, *, extra_params: Params = None) -> tuple[AttachmentInfo, ...]:
        """List a single feature's attachments via the canonical infos resource.

        Wraps ``GET .../{layerId}/{objectId}/attachments``.
        """
        payload = self._json(
            "GET",
            f"{self.path}/{layer_id}/{object_id}/attachments",
            params=_params({"f": "json"}, extra_params),
        )
        infos = payload.get("attachmentInfos")
        if not isinstance(infos, list):
            return ()
        return tuple(
            AttachmentInfo.from_dict(info, parent_object_id=object_id) for info in infos if isinstance(info, Mapping)
        )

    def add_attachment(
        self,
        layer_id: int,
        object_id: int,
        file: AttachmentFile,
        *,
        content_type: str | None = None,
        keywords: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AddAttachmentResult:
        """Upload a file attachment to a feature.

        Wraps ``POST .../{layerId}/{objectId}/addAttachment`` as
        ``multipart/form-data``. ``file`` may be a path, an open binary file
        object, or raw ``bytes``. The returned ``object_id`` is the id of the
        newly created attachment.
        """
        files = {"attachment": _attachment_multipart_file(file, content_type=content_type)}
        data = {"f": "json"}
        if keywords is not None:
            data["keywords"] = keywords
        payload = self._json(
            "POST",
            f"{self.path}/{layer_id}/{object_id}/addAttachment",
            files=files,
            data=data,
            timeout=timeout,
            extra_headers=extra_headers,
        )
        return AddAttachmentResult.from_dict(payload)

    def update_attachment(
        self,
        layer_id: int,
        object_id: int,
        attachment_id: int,
        *,
        file: AttachmentFile | None = None,
        content_type: str | None = None,
        keywords: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> UpdateAttachmentResult:
        """Replace an attachment's bytes and/or update its keywords.

        Wraps ``POST .../{layerId}/{objectId}/updateAttachment``. Provide
        ``file`` to replace the stored bytes; omit it to update ``keywords``
        only.
        """
        data: dict[str, Any] = {"f": "json", "attachmentId": attachment_id}
        if keywords is not None:
            data["keywords"] = keywords
        files = (
            {"attachment": _attachment_multipart_file(file, content_type=content_type)} if file is not None else None
        )
        payload = self._json(
            "POST",
            f"{self.path}/{layer_id}/{object_id}/updateAttachment",
            files=files,
            data=data,
            timeout=timeout,
            extra_headers=extra_headers,
        )
        return UpdateAttachmentResult.from_dict(payload)

    def delete_attachment(
        self,
        layer_id: int,
        object_id: int,
        attachment_ids: int | CsvValue,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> tuple[DeleteAttachmentResult, ...]:
        """Delete one or more attachments from a feature.

        Wraps ``POST .../{layerId}/{objectId}/deleteAttachments``.
        ``attachment_ids`` is a single id, a CSV string, or a sequence.
        """
        data = {"f": "json", "attachmentIds": _attachment_ids_csv(attachment_ids)}
        payload = self._json(
            "POST",
            f"{self.path}/{layer_id}/{object_id}/deleteAttachments",
            data=data,
            timeout=timeout,
            extra_headers=extra_headers,
        )
        return DeleteAttachmentResult.from_list(payload)

    def download_attachment(
        self,
        layer_id: int,
        object_id: int,
        attachment_id: int,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AttachmentContent:
        """Download an attachment's binary content.

        Wraps ``GET .../{layerId}/{objectId}/attachments/{attachmentId}``,
        returning the raw bytes plus the server-reported content type.
        """
        response = self._binary_response(
            f"{self.path}/{layer_id}/{object_id}/attachments/{attachment_id}",
            timeout=timeout,
            extra_headers=extra_headers,
        )
        return AttachmentContent.from_binary_response(response)


class GeoServicesMapServerClient(_SyncProtocol):
    """Synchronous GeoServices MapServer wrapper.

    Wraps the GeoServices ``MapServer`` REST surface
    (``/rest/services/<id>/MapServer``) for rendered map exports, the
    ``identify`` lookup, raw tile fetches, and layer metadata. Use this
    when you need rasterized output or attribute-only identify requests;
    for vector query/edit flows reach for
    :class:`GeoServicesFeatureServerClient` instead. Reach this via
    :meth:`HonuaClient.map_server`.
    """

    def __init__(self, client: Any, service_id: str) -> None:
        super().__init__(client)
        self.service_id = service_id

    @property
    def path(self) -> str:
        return _service_path(self.service_id, "MapServer")

    def metadata(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", self.path, params=_params({"f": response_format}, extra_params))

    def layer_metadata(self, layer_id: int, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", f"{self.path}/{layer_id}", params=_params({"f": response_format}, extra_params))

    def export(
        self,
        bbox: BboxValue,
        *,
        size: tuple[int, int] = (400, 400),
        image_format: str = "png",
        transparent: bool = True,
        dpi: int = 96,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> bytes:
        return cast(
            bytes,
            self.client.export_map(
                self.service_id,
                bbox,
                size=size,
                image_format=image_format,
                transparent=transparent,
                dpi=dpi,
                extra_params=extra_params,
                timeout=timeout,
                extra_headers=extra_headers,
            ),
        )

    def identify(
        self,
        *,
        geometry: Mapping[str, Any] | str,
        map_extent: BboxValue,
        image_display: str,
        tolerance: int = 3,
        layers: str | None = None,
        return_geometry: bool = True,
        response_format: str = "json",
        extra_params: Params = None,
    ) -> JsonObject:
        params = _params(
            {
                "f": response_format,
                "geometry": _query_value(geometry),
                "mapExtent": _bbox(map_extent),
                "imageDisplay": image_display,
                "tolerance": tolerance,
                "returnGeometry": _bool_text(return_geometry),
            },
            extra_params,
        )
        if layers is not None:
            params["layers"] = layers
        return self._json("GET", f"{self.path}/identify", params=params)

    def tile(self, level: int, row: int, col: int) -> bytes:
        return self._bytes(f"{self.path}/tile/{level}/{row}/{col}")


class GeoServicesImageServerClient(_SyncProtocol):
    """GeoServices ImageServer wrapper."""

    def __init__(self, client: Any, service_id: str | None = None) -> None:
        super().__init__(client)
        self.service_id = service_id

    @property
    def path(self) -> str:
        if self.service_id is None:
            return "/rest/services/ImageServer"
        return _service_path(self.service_id, "ImageServer")

    def metadata(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", self.path, params=_params({"f": response_format}, extra_params))

    def export_image(
        self,
        bbox: BboxValue,
        *,
        size: tuple[int, int] | None = None,
        image_format: str = "png",
        bbox_sr: int | str | None = None,
        image_sr: int | str | None = None,
        pixel_type: str | None = None,
        no_data: str | int | float | None = None,
        interpolation: str | None = None,
        band_ids: CsvValue | None = None,
        response_format: str = "image",
        extra_params: Params = None,
    ) -> bytes:
        """Export a windowed raster image from the ImageServer.

        ``bbox`` (in ``bbox_sr``) clips the spatial window and ``size`` sets
        the output pixel dimensions, so a raster-GP tool reads a clipped,
        resampled extent rather than the whole image. ``image_sr`` reprojects
        the output; ``band_ids`` selects bands; ``interpolation`` /
        ``pixel_type`` / ``no_data`` tune resampling and output encoding.
        """
        params = _params({"f": response_format, "bbox": _bbox(bbox), "format": image_format}, None)
        if size is not None:
            params["size"] = f"{size[0]},{size[1]}"
        if bbox_sr is not None:
            params["bboxSR"] = bbox_sr
        if image_sr is not None:
            params["imageSR"] = image_sr
        if pixel_type is not None:
            params["pixelType"] = pixel_type
        if no_data is not None:
            params["noData"] = no_data
        if interpolation is not None:
            params["interpolation"] = interpolation
        if band_ids is not None:
            params["bandIds"] = _csv(band_ids)
        if extra_params:
            params.update(extra_params)
        return self._bytes(f"{self.path}/exportImage", params=params)

    def identify(self, geometry: Mapping[str, Any] | str, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        params = _params({"f": response_format, "geometry": _query_value(geometry)}, extra_params)
        return self._json("GET", f"{self.path}/identify", params=params)

    def query(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", f"{self.path}/query", params=_params({"f": response_format}, extra_params))

    def tile(self, level: int, row: int, col: int) -> bytes:
        return self._bytes(f"{self.path}/tile/{level}/{row}/{col}")

    def legend(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", f"{self.path}/legend", params=_params({"f": response_format}, extra_params))


class GeoServicesGeometryServerClient(_SyncProtocol):
    """GeoServices GeometryServer wrapper."""

    def __init__(self, client: Any) -> None:
        super().__init__(client)
        self.path = "/rest/services/Utilities/Geometry/GeometryServer"

    def metadata(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return self._json("GET", self.path, params=_params({"f": response_format}, extra_params))

    def operation(
        self,
        name: str,
        *,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
        method: str = "GET",
        response_format: str = "json",
    ) -> JsonObject:
        request_params = _params({"f": response_format}, params)
        return self._json(method, f"{self.path}/{_encode_path_segment(name)}", params=request_params, json_body=json_body)

    def project(
        self,
        geometries: Any,
        *,
        in_sr: int | str,
        out_sr: int | str,
        extra_params: Params = None,
    ) -> JsonObject:
        params: dict[str, Any] = {
            "geometries": _query_value(geometries),
            "inSR": in_sr,
            "outSR": out_sr,
        }
        if extra_params:
            params.update(extra_params)
        return self.operation("project", params=params)

    def buffer(
        self,
        geometries: Any,
        *,
        in_sr: int | str,
        distances: CsvValue,
        unit: str | None = None,
        extra_params: Params = None,
    ) -> JsonObject:
        params: dict[str, Any] = {
            "geometries": _query_value(geometries),
            "inSR": in_sr,
            "distances": _csv(distances),
        }
        if extra_params:
            params.update(extra_params)
        if unit is not None:
            params["unit"] = unit
        return self.operation("buffer", params=params)

    def simplify(
        self,
        geometries: Any,
        *,
        sr: int | str | None = None,
        extra_params: Params = None,
    ) -> JsonObject:
        params: dict[str, Any] = {"geometries": _query_value(geometries)}
        if extra_params:
            params.update(extra_params)
        if sr is not None:
            params["sr"] = sr
        return self.operation("simplify", params=params)


class AsyncGeoServicesFeatureServerClient(_AsyncProtocol):
    """Async GeoServices FeatureServer wrapper."""

    def __init__(self, client: Any, service_id: str) -> None:
        super().__init__(client)
        self.service_id = service_id

    @property
    def path(self) -> str:
        return _service_path(self.service_id, "FeatureServer")

    async def metadata(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", self.path, params=_params({"f": response_format}, extra_params))

    async def layer_metadata(self, layer_id: int, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", f"{self.path}/{layer_id}", params=_params({"f": response_format}, extra_params))

    async def schema(self, layer_id: int, *, extra_params: Params = None) -> LayerSchema:
        """Return a typed :class:`LayerSchema` for a layer (arcpy.Describe analogue).

        Fetches ``layer_metadata`` and parses the raw JSON into typed fields,
        a normalized geometry type, the resolved spatial-reference WKID, and a
        typed extent — so a GP tool maps outputs without hand-parsing JSON.
        """
        return LayerSchema.from_metadata(await self.layer_metadata(layer_id, extra_params=extra_params))

    async def query(
        self,
        layer_id: int,
        *,
        where: str = "1=1",
        out_fields: CsvValue = "*",
        return_geometry: bool = True,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        return cast(
            JsonObject,
            await self.client.query_features(
                self.service_id,
                layer_id,
                where=where,
                out_fields=out_fields,
                return_geometry=return_geometry,
                extra_params=extra_params,
                timeout=timeout,
                extra_headers=extra_headers,
            ),
        )

    async def query_pages(
        self,
        layer_id: int,
        *,
        page_size: int = 1000,
        limit: int | None = None,
        max_pages: int | None = 100,
        where: str = "1=1",
        out_fields: CsvValue = "*",
        return_geometry: bool = True,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[FeatureSet]:
        if page_size <= 0:
            raise ValueError("page_size must be greater than zero.")
        if max_pages is not None and max_pages <= 0:
            raise ValueError("max_pages must be greater than zero (or None for unbounded).")
        if limit is not None and limit <= 0:
            return

        total = 0
        base_extra = dict(extra_params or {})
        offset = int(base_extra.get("resultOffset", 0))
        previous_object_ids: set[int] = set()
        for _ in _iter_page_indices(max_pages):
            remaining = None if limit is None else limit - total
            if remaining is not None and remaining <= 0:
                break
            record_count = page_size if remaining is None else min(page_size, remaining)
            page_extra_params = {
                **base_extra,
                "resultOffset": offset,
                "resultRecordCount": record_count,
            }
            page = FeatureSet.from_dict(
                await self.query(
                    layer_id,
                    where=where,
                    out_fields=out_fields,
                    return_geometry=return_geometry,
                    extra_params=page_extra_params,
                    timeout=timeout,
                    extra_headers=extra_headers,
                )
            )
            # Non-advancing-cursor guard: stop before re-yielding a page a
            # server that ignores ``resultOffset`` keeps returning (it would
            # otherwise loop to ``max_pages`` with duplicate features). Compare
            # against the previous page only — not every id seen across the
            # whole walk — so the tracking set stays bounded to a single page on
            # the streaming path.
            new_object_ids = {oid for f in page.features if (oid := f.object_id) is not None}
            if new_object_ids and new_object_ids.issubset(previous_object_ids):
                break
            previous_object_ids = new_object_ids
            yield page
            page_count = len(page.features)
            total += page_count
            if page_count < record_count or not page.exceeded_transfer_limit:
                break
            offset += page_count

    async def query_all(
        self,
        layer_id: int,
        *,
        page_size: int = 1000,
        limit: int | None = None,
        max_pages: int | None = 100,
        where: str = "1=1",
        out_fields: CsvValue = "*",
        return_geometry: bool = True,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> list[Feature]:
        features: list[Feature] = []
        async for page in self.query_pages(
            layer_id,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            where=where,
            out_fields=out_fields,
            return_geometry=return_geometry,
            extra_params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            remaining = None if limit is None else limit - len(features)
            page_features = list(page.features) if remaining is None else list(page.features)[:remaining]
            features.extend(page_features)
            if remaining is not None and len(features) >= limit:  # type: ignore[operator]
                break
        return features

    async def query_items(
        self,
        layer_id: int,
        *,
        page_size: int = 1000,
        limit: int | None = None,
        max_pages: int | None = 100,
        where: str = "1=1",
        out_fields: CsvValue = "*",
        return_geometry: bool = True,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[Feature]:
        emitted = 0
        async for page in self.query_pages(
            layer_id,
            page_size=page_size,
            limit=limit,
            max_pages=max_pages,
            where=where,
            out_fields=out_fields,
            return_geometry=return_geometry,
            extra_params=extra_params,
            timeout=timeout,
            extra_headers=extra_headers,
        ):
            for feature in page.features:
                if limit is not None and emitted >= limit:
                    return
                yield feature
                emitted += 1

    async def apply_edits(
        self,
        layer_id: int,
        *,
        adds: Sequence[Mapping[str, Any]] | None = None,
        updates: Sequence[Mapping[str, Any]] | None = None,
        deletes: Sequence[int] | str | None = None,
        rollback_on_failure: bool = True,
        idempotency_key: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> JsonObject:
        return cast(
            JsonObject,
            await self.client.apply_edits(
                self.service_id,
                layer_id,
                adds=adds,
                updates=updates,
                deletes=deletes,
                rollback_on_failure=rollback_on_failure,
                idempotency_key=idempotency_key,
                timeout=timeout,
                extra_headers=extra_headers,
            ),
        )

    async def query_related_records(
        self,
        layer_id: int,
        *,
        object_ids: CsvValue,
        relationship_id: int,
        response_format: str = "json",
        extra_params: Params = None,
    ) -> JsonObject:
        params = _params(
            {"f": response_format, "objectIds": _csv(object_ids), "relationshipId": relationship_id},
            extra_params,
        )
        return await self._json("GET", f"{self.path}/{layer_id}/queryRelatedRecords", params=params)

    # --- attachments ------------------------------------------------------

    async def query_attachments(
        self,
        layer_id: int,
        object_id: int | None = None,
        *,
        object_ids: CsvValue | None = None,
        return_url: bool = False,
        attachment_types: CsvValue | None = None,
        keywords: CsvValue | None = None,
        response_format: str = "json",
        extra_params: Params = None,
    ) -> AttachmentQueryResult:
        """Query attachment metadata for one or more features.

        Wraps ``GET .../{layerId}/queryAttachments``. Pass either a single
        ``object_id`` or a CSV/sequence of ``object_ids`` (one is required).
        Set ``return_url=True`` to have the server include a download ``url``
        on each :class:`AttachmentInfo`.
        """
        ids = _resolve_object_ids(object_id, object_ids)
        params: dict[str, Any] = {"f": response_format, "objectIds": ids}
        if return_url:
            params["returnUrl"] = _bool_text(True)
        if attachment_types is not None:
            params["attachmentTypes"] = _csv(attachment_types)
        if keywords is not None:
            params["keywords"] = _csv(keywords)
        payload = await self._json(
            "GET", f"{self.path}/{layer_id}/queryAttachments", params=_params(params, extra_params)
        )
        return AttachmentQueryResult.from_dict(payload)

    async def list_attachments(
        self, layer_id: int, object_id: int, *, extra_params: Params = None
    ) -> tuple[AttachmentInfo, ...]:
        """List a single feature's attachments via the canonical infos resource.

        Wraps ``GET .../{layerId}/{objectId}/attachments``.
        """
        payload = await self._json(
            "GET",
            f"{self.path}/{layer_id}/{object_id}/attachments",
            params=_params({"f": "json"}, extra_params),
        )
        infos = payload.get("attachmentInfos")
        if not isinstance(infos, list):
            return ()
        return tuple(
            AttachmentInfo.from_dict(info, parent_object_id=object_id) for info in infos if isinstance(info, Mapping)
        )

    async def add_attachment(
        self,
        layer_id: int,
        object_id: int,
        file: AttachmentFile,
        *,
        content_type: str | None = None,
        keywords: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AddAttachmentResult:
        """Upload a file attachment to a feature.

        Wraps ``POST .../{layerId}/{objectId}/addAttachment`` as
        ``multipart/form-data``. ``file`` may be a path, an open binary file
        object, or raw ``bytes``. The returned ``object_id`` is the id of the
        newly created attachment.
        """
        # Offload the (blocking, whole-file) read to a worker thread so the
        # event loop is not stalled for the duration of the disk read, mirroring
        # _resolve_dynamic_auth_headers_async in _http.py.
        part = await to_thread.run_sync(partial(_attachment_multipart_file, file, content_type=content_type))
        files = {"attachment": part}
        data = {"f": "json"}
        if keywords is not None:
            data["keywords"] = keywords
        payload = await self._json(
            "POST",
            f"{self.path}/{layer_id}/{object_id}/addAttachment",
            files=files,
            data=data,
            timeout=timeout,
            extra_headers=extra_headers,
        )
        return AddAttachmentResult.from_dict(payload)

    async def update_attachment(
        self,
        layer_id: int,
        object_id: int,
        attachment_id: int,
        *,
        file: AttachmentFile | None = None,
        content_type: str | None = None,
        keywords: str | None = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> UpdateAttachmentResult:
        """Replace an attachment's bytes and/or update its keywords.

        Wraps ``POST .../{layerId}/{objectId}/updateAttachment``. Provide
        ``file`` to replace the stored bytes; omit it to update ``keywords``
        only.
        """
        data: dict[str, Any] = {"f": "json", "attachmentId": attachment_id}
        if keywords is not None:
            data["keywords"] = keywords
        files = None
        if file is not None:
            # Offload the blocking read off the event loop (see add_attachment).
            part = await to_thread.run_sync(partial(_attachment_multipart_file, file, content_type=content_type))
            files = {"attachment": part}
        payload = await self._json(
            "POST",
            f"{self.path}/{layer_id}/{object_id}/updateAttachment",
            files=files,
            data=data,
            timeout=timeout,
            extra_headers=extra_headers,
        )
        return UpdateAttachmentResult.from_dict(payload)

    async def delete_attachment(
        self,
        layer_id: int,
        object_id: int,
        attachment_ids: int | CsvValue,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> tuple[DeleteAttachmentResult, ...]:
        """Delete one or more attachments from a feature.

        Wraps ``POST .../{layerId}/{objectId}/deleteAttachments``.
        ``attachment_ids`` is a single id, a CSV string, or a sequence.
        """
        data = {"f": "json", "attachmentIds": _attachment_ids_csv(attachment_ids)}
        payload = await self._json(
            "POST",
            f"{self.path}/{layer_id}/{object_id}/deleteAttachments",
            data=data,
            timeout=timeout,
            extra_headers=extra_headers,
        )
        return DeleteAttachmentResult.from_list(payload)

    async def download_attachment(
        self,
        layer_id: int,
        object_id: int,
        attachment_id: int,
        *,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> AttachmentContent:
        """Download an attachment's binary content.

        Wraps ``GET .../{layerId}/{objectId}/attachments/{attachmentId}``,
        returning the raw bytes plus the server-reported content type.
        """
        response = await self._binary_response(
            f"{self.path}/{layer_id}/{object_id}/attachments/{attachment_id}",
            timeout=timeout,
            extra_headers=extra_headers,
        )
        return AttachmentContent.from_binary_response(response)


class AsyncGeoServicesMapServerClient(_AsyncProtocol):
    """Async GeoServices MapServer wrapper."""

    def __init__(self, client: Any, service_id: str) -> None:
        super().__init__(client)
        self.service_id = service_id

    @property
    def path(self) -> str:
        return _service_path(self.service_id, "MapServer")

    async def metadata(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", self.path, params=_params({"f": response_format}, extra_params))

    async def layer_metadata(self, layer_id: int, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", f"{self.path}/{layer_id}", params=_params({"f": response_format}, extra_params))

    async def export(
        self,
        bbox: BboxValue,
        *,
        size: tuple[int, int] = (400, 400),
        image_format: str = "png",
        transparent: bool = True,
        dpi: int = 96,
        extra_params: Params = None,
        timeout: float | httpx.Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> bytes:
        return cast(
            bytes,
            await self.client.export_map(
                self.service_id,
                bbox,
                size=size,
                image_format=image_format,
                transparent=transparent,
                dpi=dpi,
                extra_params=extra_params,
                timeout=timeout,
                extra_headers=extra_headers,
            ),
        )

    async def identify(
        self,
        *,
        geometry: Mapping[str, Any] | str,
        map_extent: BboxValue,
        image_display: str,
        tolerance: int = 3,
        layers: str | None = None,
        return_geometry: bool = True,
        response_format: str = "json",
        extra_params: Params = None,
    ) -> JsonObject:
        params = _params(
            {
                "f": response_format,
                "geometry": _query_value(geometry),
                "mapExtent": _bbox(map_extent),
                "imageDisplay": image_display,
                "tolerance": tolerance,
                "returnGeometry": _bool_text(return_geometry),
            },
            extra_params,
        )
        if layers is not None:
            params["layers"] = layers
        return await self._json("GET", f"{self.path}/identify", params=params)

    async def tile(self, level: int, row: int, col: int) -> bytes:
        return await self._bytes(f"{self.path}/tile/{level}/{row}/{col}")


class AsyncGeoServicesImageServerClient(_AsyncProtocol):
    """Async GeoServices ImageServer wrapper."""

    def __init__(self, client: Any, service_id: str | None = None) -> None:
        super().__init__(client)
        self.service_id = service_id

    @property
    def path(self) -> str:
        if self.service_id is None:
            return "/rest/services/ImageServer"
        return _service_path(self.service_id, "ImageServer")

    async def metadata(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", self.path, params=_params({"f": response_format}, extra_params))

    async def export_image(
        self,
        bbox: BboxValue,
        *,
        size: tuple[int, int] | None = None,
        image_format: str = "png",
        bbox_sr: int | str | None = None,
        image_sr: int | str | None = None,
        pixel_type: str | None = None,
        no_data: str | int | float | None = None,
        interpolation: str | None = None,
        band_ids: CsvValue | None = None,
        response_format: str = "image",
        extra_params: Params = None,
    ) -> bytes:
        """Export a windowed raster image from the ImageServer.

        ``bbox`` (in ``bbox_sr``) clips the spatial window and ``size`` sets
        the output pixel dimensions, so a raster-GP tool reads a clipped,
        resampled extent rather than the whole image. ``image_sr`` reprojects
        the output; ``band_ids`` selects bands; ``interpolation`` /
        ``pixel_type`` / ``no_data`` tune resampling and output encoding.
        """
        params = _params({"f": response_format, "bbox": _bbox(bbox), "format": image_format}, None)
        if size is not None:
            params["size"] = f"{size[0]},{size[1]}"
        if bbox_sr is not None:
            params["bboxSR"] = bbox_sr
        if image_sr is not None:
            params["imageSR"] = image_sr
        if pixel_type is not None:
            params["pixelType"] = pixel_type
        if no_data is not None:
            params["noData"] = no_data
        if interpolation is not None:
            params["interpolation"] = interpolation
        if band_ids is not None:
            params["bandIds"] = _csv(band_ids)
        if extra_params:
            params.update(extra_params)
        return await self._bytes(f"{self.path}/exportImage", params=params)

    async def identify(self, geometry: Mapping[str, Any] | str, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        params = _params({"f": response_format, "geometry": _query_value(geometry)}, extra_params)
        return await self._json("GET", f"{self.path}/identify", params=params)

    async def query(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", f"{self.path}/query", params=_params({"f": response_format}, extra_params))

    async def tile(self, level: int, row: int, col: int) -> bytes:
        return await self._bytes(f"{self.path}/tile/{level}/{row}/{col}")

    async def legend(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", f"{self.path}/legend", params=_params({"f": response_format}, extra_params))


class AsyncGeoServicesGeometryServerClient(_AsyncProtocol):
    """Async GeoServices GeometryServer wrapper."""

    def __init__(self, client: Any) -> None:
        super().__init__(client)
        self.path = "/rest/services/Utilities/Geometry/GeometryServer"

    async def metadata(self, *, response_format: str = "json", extra_params: Params = None) -> JsonObject:
        return await self._json("GET", self.path, params=_params({"f": response_format}, extra_params))

    async def operation(
        self,
        name: str,
        *,
        params: Params = None,
        json_body: Mapping[str, Any] | None = None,
        method: str = "GET",
        response_format: str = "json",
    ) -> JsonObject:
        request_params = _params({"f": response_format}, params)
        return await self._json(method, f"{self.path}/{_encode_path_segment(name)}", params=request_params, json_body=json_body)

    async def project(
        self,
        geometries: Any,
        *,
        in_sr: int | str,
        out_sr: int | str,
        extra_params: Params = None,
    ) -> JsonObject:
        params: dict[str, Any] = {
            "geometries": _query_value(geometries),
            "inSR": in_sr,
            "outSR": out_sr,
        }
        if extra_params:
            params.update(extra_params)
        return await self.operation("project", params=params)

    async def buffer(
        self,
        geometries: Any,
        *,
        in_sr: int | str,
        distances: CsvValue,
        unit: str | None = None,
        extra_params: Params = None,
    ) -> JsonObject:
        params: dict[str, Any] = {
            "geometries": _query_value(geometries),
            "inSR": in_sr,
            "distances": _csv(distances),
        }
        if extra_params:
            params.update(extra_params)
        if unit is not None:
            params["unit"] = unit
        return await self.operation("buffer", params=params)

    async def simplify(
        self,
        geometries: Any,
        *,
        sr: int | str | None = None,
        extra_params: Params = None,
    ) -> JsonObject:
        params: dict[str, Any] = {"geometries": _query_value(geometries)}
        if extra_params:
            params.update(extra_params)
        if sr is not None:
            params["sr"] = sr
        return await self.operation("simplify", params=params)
