#!/usr/bin/env python3
"""Generate the staging client-compat deployment binding.

The binding is a non-secret JSON object held in the `HONUA_CLIENT_COMPAT_BINDING_JSON`
repository variable. It pins the staging deployment the Python SDK's remote smoke
suite certifies against: the base URL, service and layer, the exact server commit
and `@sha256`-pinned image, and a commit-pinned descriptor in honua-demo-infra
whose bytes are digest-matched at smoke time.

It also expires, by design, at most 30 days after it is generated
(`_smoke_harness.validate_client_compat_binding`). Until now it was written by
hand, which meant the staging suite went red the day the window closed and stayed
red until somebody reconstructed the JSON from the validator's error messages.
That is what this script is for: one command, and the result is validated through
the same function the smoke suite uses before it is printed, so it cannot emit a
binding the suite will reject.

    python scripts/make_client_compat_binding.py \
        --descriptor-url https://raw.githubusercontent.com/honua-io/honua-demo-infra/<40-hex>/manifest/client-compat.v1.json

Every other value is read from the staging variables the workflow already sets, so
the binding cannot drift from them: HONUA_BASE_URL, HONUA_SERVICE_ID,
HONUA_LAYER_ID, HONUA_SERVER_COMMIT, HONUA_SERVER_IMAGE, HONUA_SEED_PROFILE.
Pass --check to validate the binding already in the variable instead of making a
new one.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts._smoke_harness import (  # noqa: E402
    CLIENT_COMPAT_BINDING_ENV,
    CLIENT_COMPAT_BINDING_FORMAT,
    CLIENT_COMPAT_OWNER_REPOSITORY,
    SmokeConfigError,
    validate_client_compat_binding,
)

# The validator caps the window at 30 days. Default to the cap: a shorter window
# only means going red sooner, and the binding is non-secret.
MAX_WINDOW_DAYS = 30


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(
            f"{name} is not set. This script reads the same staging variables the "
            "workflow does, so the binding cannot disagree with them. Export them "
            "(gh variable list --repo honua-io/honua-sdk-python shows the values) "
            "and run it again."
        )
    return value


def build(descriptor_url: str, descriptor_sha256: str, days: int) -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    return {
        "format": CLIENT_COMPAT_BINDING_FORMAT,
        "schemaVersion": "1.0.0",
        "generatedAt": now.isoformat().replace("+00:00", "Z"),
        "expiresAt": (now + timedelta(days=days)).isoformat().replace("+00:00", "Z"),
        "owner": {"repository": CLIENT_COMPAT_OWNER_REPOSITORY},
        "descriptor": {"url": descriptor_url, "sha256": descriptor_sha256},
        "target": {
            "baseUrl": required_env("HONUA_BASE_URL").rstrip("/"),
            "serviceName": required_env("HONUA_SERVICE_ID"),
            "layerId": int(required_env("HONUA_LAYER_ID")),
            "seedProfile": os.environ.get("HONUA_SEED_PROFILE") or None,
            "server": {
                "commit": required_env("HONUA_SERVER_COMMIT"),
                "image": required_env("HONUA_SERVER_IMAGE"),
            },
        },
        # The suite proves the deployment is protected and that no credential was
        # recorded in the evidence. Both are assertions about how it was reached,
        # so they are fixed here rather than configurable.
        "access": {"allowAnonymous": False, "credentialRecorded": False},
    }


def descriptor_bytes(url: str) -> bytes:
    from urllib.error import HTTPError, URLError

    from scripts._smoke_harness import _fetch_descriptor_bytes

    try:
        return _fetch_descriptor_bytes(url)
    except HTTPError as exc:
        raise SystemExit(
            f"descriptor fetch returned HTTP {exc.code} for {url}\n"
            "The URL must be commit-pinned to a commit that exists on "
            "honua-io/honua-demo-infra and carries manifest/client-compat.v1.json."
        ) from exc
    except URLError as exc:
        raise SystemExit(f"descriptor fetch failed for {url}: {exc.reason}") from exc


def check(binding_json: str) -> dict:
    """Run the binding through the suite's own validator."""
    return validate_client_compat_binding(
        binding_json,
        base_url=required_env("HONUA_BASE_URL"),
        service_id=required_env("HONUA_SERVICE_ID"),
        layer_id=int(required_env("HONUA_LAYER_ID")),
        server_commit=required_env("HONUA_SERVER_COMMIT"),
        server_image=required_env("HONUA_SERVER_IMAGE"),
        seed_profile=os.environ.get("HONUA_SEED_PROFILE") or None,
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--descriptor-url",
                        help="Commit-pinned honua-demo-infra manifest/client-compat.v1.json URL.")
    parser.add_argument("--days", type=int, default=MAX_WINDOW_DAYS,
                        help=f"Validity window in days (max {MAX_WINDOW_DAYS}).")
    parser.add_argument("--check", action="store_true",
                        help=f"Validate the binding in ${CLIENT_COMPAT_BINDING_ENV} instead of generating one.")
    args = parser.parse_args(argv)

    if args.check:
        existing = os.environ.get(CLIENT_COMPAT_BINDING_ENV, "").strip()
        if not existing:
            raise SystemExit(f"{CLIENT_COMPAT_BINDING_ENV} is not set.")
        summary = check(existing)
        print(f"binding is valid; expires {summary['expires_at']}")
        return 0

    if not args.descriptor_url:
        raise SystemExit("--descriptor-url is required when generating a binding.")
    if not 0 < args.days <= MAX_WINDOW_DAYS:
        raise SystemExit(f"--days must be between 1 and {MAX_WINDOW_DAYS}.")

    from hashlib import sha256

    digest = sha256(descriptor_bytes(args.descriptor_url)).hexdigest()
    binding = build(args.descriptor_url, digest, args.days)
    binding_json = json.dumps(binding, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    # Fail here rather than in CI a week from now. Everything the smoke suite
    # checks - the descriptor digest, its agreement with the staging variables,
    # the expiry window, the access assertions - is checked against the real
    # descriptor before this prints anything.
    try:
        summary = check(binding_json)
    except SmokeConfigError as exc:
        raise SystemExit(f"generated binding is not valid: {exc}") from exc

    print(binding_json)
    print(f"\n# valid until {summary['expires_at']}", file=sys.stderr)
    print("# apply with:", file=sys.stderr)
    print(f"#   gh variable set {CLIENT_COMPAT_BINDING_ENV} "
          f"--repo honua-io/honua-sdk-python --body '<the JSON above>'", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
