"""2026.1 certification boots with licensing disabled.

Release and rehearsal both leave the signed license envelope unread. Release
still requires an explicit workflow_dispatch. The candidate's license status
must report mode disabled, with the catalog edit entitlement active, before
applyEdits evidence counts.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import httpx

_REHEARSAL_EVENTS = {"pull_request", "push", "schedule", "workflow_dispatch", "local"}


def profile(tier: str, event: str, environment: str, license_content: str) -> dict[str, str]:
    del license_content  # 2026.1 does not read a signed license envelope.
    if tier == "release":
        if event != "workflow_dispatch":
            raise ValueError("release certification requires an explicit governed dispatch")
        return {"mode": "disabled", "devGrantEdition": "", "licensingMode": "Disabled"}
    if tier not in {"pr", "nightly"} or event not in _REHEARSAL_EVENTS:
        raise ValueError("unknown certification rehearsal profile")
    if environment != "Development":
        raise ValueError("rehearsal entitlement grants require Development")
    return {"mode": "development-grant", "devGrantEdition": "Enterprise", "licensingMode": "Enabled"}


def signed_status(value: object, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    data = value.get("data") if isinstance(value, Mapping) and value.get("success") is True else None
    if not isinstance(data, Mapping):
        raise AssertionError("candidate did not return a successful license status")
    identifier = data.get("licenseId")
    if (data.get("mode") != "enabled" or data.get("isValid") is not True or data.get("validationState") != "Valid"
            or not isinstance(identifier, str) or not identifier.strip() or identifier.lower() in {"dev-grant", "community"}):
        raise AssertionError("candidate did not validate a signed non-development license")
    try:
        issued = datetime.fromisoformat(data["issuedAt"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(data["expiresAt"].replace("Z", "+00:00")) if data.get("expiresAt") else None
        if issued.tzinfo is None or issued > now or (expires and (expires.tzinfo is None or expires <= now)):
            raise ValueError("invalid license lifetime")
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise AssertionError("candidate license lifetime is absent, invalid or expired") from exc
    entitlements = data.get("entitlements")
    matching = [row for row in entitlements if isinstance(row, Mapping) and row.get("key") == "editing.featureserver-edits"] if isinstance(entitlements, list) else []
    if len(matching) != 1 or matching[0].get("isActive") is not True:
        raise AssertionError("candidate did not validate the required editing entitlement")
    return {"verification": "candidate-license-status-v1", "mode": "signed", "status": "active",
            "entitlement": "editing.featureserver-edits", "license_fingerprint": "sha256:" + hashlib.sha256(identifier.encode()).hexdigest(),
            "checked_at": now.isoformat().replace("+00:00", "Z")}


def disabled_status(value: object, *, now: datetime | None = None) -> dict[str, Any]:
    """Admit a 2026.1 candidate that reports licensing disabled and the edit entitlement active."""
    now = now or datetime.now(timezone.utc)
    data = value.get("data") if isinstance(value, Mapping) and value.get("success") is True else None
    if not isinstance(data, Mapping):
        raise AssertionError("candidate did not return a successful license status")
    identifier = data.get("licenseId")
    if (data.get("mode") != "disabled" or data.get("isValid") is not True or data.get("validationState") != "Disabled"
            or (isinstance(identifier, str) and identifier.strip())):
        raise AssertionError("candidate did not report licensing disabled")
    entitlements = data.get("entitlements")
    matching = [row for row in entitlements if isinstance(row, Mapping) and row.get("key") == "editing.featureserver-edits"] if isinstance(entitlements, list) else []
    if len(matching) != 1 or matching[0].get("isActive") is not True:
        raise AssertionError("candidate did not expose the required editing entitlement while licensing is disabled")
    return {"verification": "candidate-disabled-license-status-v1", "mode": "disabled", "status": "active",
            "entitlement": "editing.featureserver-edits", "checked_at": now.isoformat().replace("+00:00", "Z")}


def _license_status(target: Any) -> object:
    with httpx.Client(follow_redirects=False, timeout=20) as transport:
        response = transport.get(target.base_url.rstrip("/") + "/api/v1/admin/license/",
                                 headers={"X-API-Key": target.api_key} if target.api_key else {})
        response.raise_for_status()
        return response.json()


def observe(target: Any) -> dict[str, Any]:
    if target.certification_tier != "release":
        return {"mode": target.entitlement_mode, "release_eligible": False}
    if target.entitlement_mode == "disabled":
        # The probe admits the disabled runtime only. Edit, rollback, and readback stay mandatory.
        return disabled_status(_license_status(target))
    if target.entitlement_mode != "signed":
        raise AssertionError("release certification refuses rehearsal or missing entitlement provenance")
    return signed_status(_license_status(target))
