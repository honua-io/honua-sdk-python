"""Explicit ephemeral rehearsal grants; release proof uses candidate-validated signed entitlements."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

import httpx


# Events that publish a governed certification fragment without a signed license.
# Their public cells are governed as ``anonymous-public-v1``, so the target runs
# with licensing disabled instead of a development grant (whose receipts carry
# the non-governed ``development-grant-rehearsal-v1`` policy).
FRAGMENT_REHEARSAL_EVENTS = frozenset({"push", "schedule", "workflow_dispatch"})


def profile(tier: str, event: str, environment: str, license_content: str) -> dict[str, str]:
    if tier == "release":
        if event != "workflow_dispatch":
            raise ValueError("release certification requires an explicit governed dispatch")
        try:
            envelope = json.loads(license_content)
        except (ValueError, TypeError) as exc:
            raise ValueError("HONUA_CERTIFICATION_LICENSE_CONTENT must supply the signed release license") from exc
        if not isinstance(envelope, dict) or not envelope:
            raise ValueError("signed release license envelope is absent")
        # Parsing is only input validation. The actual candidate must validate its
        # signature and expose the active non-dev entitlement before real edits.
        return {"mode": "signed", "devGrantEdition": "", "licensingMode": "Enabled"}
    if tier not in {"pr", "nightly"} or event not in {"pull_request", "push", "schedule", "workflow_dispatch", "local"}:
        raise ValueError("unknown certification rehearsal profile")
    if environment != "Development":
        raise ValueError("rehearsal entitlement grants require Development")
    if event in FRAGMENT_REHEARSAL_EVENTS:
        # Not release-eligible: observe() and the release validators only accept "signed".
        return {"mode": "licensing-disabled", "devGrantEdition": "", "licensingMode": "Disabled"}
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


def observe(target: Any) -> dict[str, Any]:
    if target.certification_tier != "release":
        return {"mode": target.entitlement_mode, "release_eligible": False}
    if target.entitlement_mode != "signed":
        raise AssertionError("release certification refuses rehearsal or missing entitlement provenance")
    # This authenticated metadata probe admits the entitlement only. The public
    # package's actual edit/rollback/readback operations remain mandatory proof.
    with httpx.Client(follow_redirects=False, timeout=20) as transport:
        response = transport.get(target.base_url.rstrip("/") + "/api/v1/admin/license/",
                                 headers={"X-API-Key": target.api_key} if target.api_key else {})
        response.raise_for_status()
        return signed_status(response.json())
