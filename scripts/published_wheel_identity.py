"""Validate the package identity used by both certification dispatch paths."""
import os
import re


def validate_identity(wheel):
    package, version, digest, source = (wheel[key] for key in ("package", "version", "digest", "sourceSha"))
    if package != "honua-sdk":
        raise ValueError("requires sdk_package=honua-sdk")
    if not isinstance(version, str) or not re.fullmatch(
        r"[0-9]+(\.[0-9]+)*((a|b|rc)[0-9]+)?(\.post[0-9]+)?(\.dev[0-9]+)?", version
    ):
        raise ValueError("requires sdk_package_version as an exact normalized release version")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("requires sdk_package_digest as sha256:<64 lowercase hex>")
    if not isinstance(source, str) or not re.fullmatch(r"[0-9a-f]{40}", source):
        raise ValueError("requires sdk_source_sha as a 40-hex source commit")


def main():
    try:
        validate_identity({
            "package": os.environ.get("SDK_PACKAGE", ""),
            "version": os.environ.get("SDK_PACKAGE_VERSION", ""),
            "digest": os.environ.get("SDK_PACKAGE_DIGEST", ""),
            "sourceSha": os.environ.get("SDK_SOURCE_SHA", ""),
        })
    except ValueError as exc:
        print(f"::error::nightly dispatch {exc}")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
