"""Create distribution manifests and enforce exact PyPI file parity."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class ParityError(ValueError):
    """A built distribution does not match its occupied registry coordinate."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def create_manifest(dist_dir: Path, package: str, version: str) -> dict[str, Any]:
    files = sorted(path for path in dist_dir.iterdir() if path.is_file())
    wheels = [path for path in files if path.name.endswith(".whl")]
    sdists = [path for path in files if path.name.endswith(".tar.gz")]
    if len(files) != 2 or len(wheels) != 1 or len(sdists) != 1:
        raise ParityError(
            f"Expected exactly one wheel and one sdist in {dist_dir}; "
            f"found {[path.name for path in files]}."
        )

    normalized_name = package.replace("-", "_")
    if not wheels[0].name.startswith(f"{normalized_name}-{version}-"):
        raise ParityError(f"Wheel {wheels[0].name!r} does not match {package} {version}.")
    if sdists[0].name != f"{normalized_name}-{version}.tar.gz":
        raise ParityError(f"Sdist {sdists[0].name!r} does not match {package} {version}.")

    return {
        "schema_version": 1,
        "package": package,
        "version": version,
        "files": [
            {
                "filename": path.name,
                "packagetype": "bdist_wheel" if path.suffix == ".whl" else "sdist",
                "sha256": sha256_file(path),
            }
            for path in files
        ],
    }


def load_manifest(path: Path) -> dict[str, Any]:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not all(isinstance(key, str) for key in raw):
        raise ParityError(f"{path} must contain a JSON object with string keys.")
    data = {key: value for key, value in raw.items() if isinstance(key, str)}
    if data.get("schema_version") != 1:
        raise ParityError(f"{path} has an unsupported schema_version.")
    if not isinstance(data.get("package"), str) or not isinstance(data.get("version"), str):
        raise ParityError(f"{path} is missing package/version coordinates.")
    files = data.get("files")
    if not isinstance(files, list) or len(files) != 2:
        raise ParityError(f"{path} must describe exactly one wheel and one sdist.")
    return data


def manifest_hashes(manifest: Mapping[str, Any]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for entry in manifest["files"]:
        filename = entry.get("filename")
        digest = entry.get("sha256")
        if not isinstance(filename, str) or not isinstance(digest, str) or len(digest) != 64:
            raise ParityError("Distribution manifest contains an invalid filename or SHA256.")
        hashes[filename] = digest.lower()
    if len(hashes) != 2:
        raise ParityError("Distribution manifest filenames must be unique.")
    return hashes


def verify_local_files(manifest: Mapping[str, Any], dist_dir: Path) -> None:
    expected = manifest_hashes(manifest)
    files = sorted(path for path in dist_dir.iterdir() if path.is_file())
    actual = {path.name: sha256_file(path) for path in files}
    if actual != expected:
        raise ParityError(
            "Downloaded artifact parity mismatch: "
            f"expected {json.dumps(expected, sort_keys=True)}, "
            f"received {json.dumps(actual, sort_keys=True)}."
        )


def pypi_hashes(payload: Mapping[str, Any]) -> dict[str, str]:
    urls = payload.get("urls")
    if not isinstance(urls, list):
        raise ParityError("PyPI JSON response does not contain a urls list.")
    hashes: dict[str, str] = {}
    for entry in urls:
        if not isinstance(entry, dict):
            raise ParityError("PyPI JSON response contains a malformed file entry.")
        filename = entry.get("filename")
        digests = entry.get("digests")
        digest = digests.get("sha256") if isinstance(digests, dict) else None
        if not isinstance(filename, str) or not isinstance(digest, str):
            raise ParityError("PyPI JSON response is missing a filename or SHA256 digest.")
        hashes[filename] = digest.lower()
    return hashes


def verify_hash_parity(manifest: Mapping[str, Any], payload: Mapping[str, Any]) -> None:
    expected = manifest_hashes(manifest)
    actual = pypi_hashes(payload)
    if actual != expected:
        raise ParityError(
            "PyPI file parity mismatch: "
            f"expected {json.dumps(expected, sort_keys=True)}, "
            f"received {json.dumps(actual, sort_keys=True)}."
        )


def fetch_pypi_payload(index_url: str, package: str, version: str) -> dict[str, Any] | None:
    if not index_url.startswith("https://"):
        raise ParityError("PyPI index URL must use HTTPS.")
    url = f"{index_url.rstrip('/')}/{quote(package, safe='')}/{quote(version, safe='')}/json"
    request = Request(  # noqa: S310 - HTTPS is required above
        url, headers={"Accept": "application/json", "User-Agent": "honua-release/1"}
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310 - HTTPS is required above
            payload = json.load(response)
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise ParityError(f"PyPI JSON request failed with HTTP {exc.code}.") from exc
    except URLError as exc:
        raise ParityError(f"PyPI JSON request failed: {exc.reason}.") from exc
    if not isinstance(payload, dict):
        raise ParityError("PyPI JSON response must be an object.")
    return payload


def write_github_output(path: Path | None, key: str, value: str) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as output_file:
        output_file.write(f"{key}={value}\n")


MAX_BACKOFF_DELAY_SECONDS = 60.0


def backoff_delays(initial_seconds: float, budget_seconds: float) -> list[float]:
    """Doubling delays capped at a minute whose sum stays within the budget."""
    delays: list[float] = []
    delay = initial_seconds
    while delay > 0 and sum(delays) + delay <= budget_seconds:
        delays.append(delay)
        delay = min(delay * 2, MAX_BACKOFF_DELAY_SECONDS)
    return delays


def check_preflight(manifest: Mapping[str, Any], payload: Mapping[str, Any] | None, github_output: Path | None) -> int:
    if payload is None:
        write_github_output(github_output, "publish_required", "true")
        print("PyPI coordinate is unoccupied; publication is required.")
        return 0
    verify_hash_parity(manifest, payload)
    write_github_output(github_output, "publish_required", "false")
    print("PyPI coordinate has exact filename/SHA256 parity.")
    return 0


def poll_until_published(
    manifest: Mapping[str, Any],
    fetch: Callable[[], Mapping[str, Any] | None],
    delays: Sequence[float],
    sleep: Callable[[float], None],
) -> None:
    """Retry while PyPI's JSON API catches up after an upload; raise the last mismatch once the delays run out."""
    last_error = ParityError("PyPI coordinate is still unoccupied after publication.")
    for delay in [*delays, None]:
        payload = fetch()
        if payload is not None:
            try:
                verify_hash_parity(manifest, payload)
                return
            except ParityError as exc:
                last_error = exc
        if delay is None:
            raise last_error
        sleep(delay)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    manifest_parser = subparsers.add_parser("manifest")
    manifest_parser.add_argument("--dist-dir", type=Path, required=True)
    manifest_parser.add_argument("--package", required=True)
    manifest_parser.add_argument("--version", required=True)
    manifest_parser.add_argument("--output", type=Path, required=True)

    pypi_parser = subparsers.add_parser("pypi")
    pypi_parser.add_argument("--manifest", type=Path, required=True)
    pypi_parser.add_argument("--dist-dir", type=Path, required=True)
    pypi_parser.add_argument("--phase", choices=("preflight", "post-publish"), required=True)
    pypi_parser.add_argument("--index-url", default="https://pypi.org/pypi")
    pypi_parser.add_argument("--max-wait-seconds", type=float, default=300.0)
    pypi_parser.add_argument("--initial-delay-seconds", type=float, default=5.0)
    pypi_parser.add_argument(
        "--github-output",
        type=Path,
        default=Path(os.environ["GITHUB_OUTPUT"]) if "GITHUB_OUTPUT" in os.environ else None,
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "manifest":
            manifest = create_manifest(args.dist_dir, args.package, args.version)
            args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(json.dumps(manifest, sort_keys=True))
            return 0

        manifest = load_manifest(args.manifest)
        verify_local_files(manifest, args.dist_dir)
        fetch = partial(fetch_pypi_payload, args.index_url, manifest["package"], manifest["version"])
        if args.phase == "preflight":
            return check_preflight(manifest, fetch(), args.github_output)
        schedule = backoff_delays(args.initial_delay_seconds, args.max_wait_seconds)
        poll_until_published(manifest, fetch, schedule, time.sleep)
        write_github_output(args.github_output, "publish_required", "false")
        print("PyPI coordinate has exact filename/SHA256 parity.")
        return 0
    except (OSError, ParityError, ValueError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
