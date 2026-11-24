"""Generate the attestation examples embedded in the two PyPI READMEs."""

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
START = "<!-- BEGIN GENERATED ATTESTATION EXAMPLE -->"
END = "<!-- END GENERATED ATTESTATION EXAMPLE -->"
EXAMPLE = """\
```bash
(
  set -eu
  workdir="$(mktemp -d)"
  trap 'rm -r "$workdir"' EXIT
  cd "$workdir"

  version=0.3.3
  repo=honua-io/honua-sdk-python
  source=21a9ecb952e43ecc1450384e595259b1912f27b3
  wheel="@WHEEL@-${version}-py3-none-any.whl"
  python3 -m pip download --only-binary=:all: --no-deps "@PACKAGE@==$version"

  python3 - "$wheel" "$repo" <<'PYTHON' > attestations.jsonl
import hashlib
import json
import sys
from pathlib import Path
from urllib.request import urlopen

wheel, repo = sys.argv[1:]
digest = hashlib.sha256(Path(wheel).read_bytes()).hexdigest()
with urlopen(f"https://api.github.com/repos/{repo}/attestations/sha256:{digest}", timeout=30) as response:
    attestations = json.load(response)["attestations"]
for attestation in attestations:
    print(json.dumps(attestation["bundle"]))
PYTHON

  gh attestation verify "$wheel" --bundle attestations.jsonl --repo "$repo" --source-digest "$source"
)
```
""".rstrip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check that examples match the template.")
    args = parser.parse_args()
    stale = []
    for package in ("honua-admin", "honua-sdk"):
        readme = ROOT / "packages" / package / "README.md"
        original = readme.read_text(encoding="utf-8")
        before, body = original.split(START, 1)
        _, after = body.split(END, 1)
        example = EXAMPLE.replace("@PACKAGE@", package).replace("@WHEEL@", package.replace("-", "_"))
        expected = f"{before}{START}\n{example}\n{END}{after}"
        if expected == original:
            continue
        if args.check:
            stale.append(str(readme.relative_to(ROOT)))
        else:
            readme.write_text(expected, encoding="utf-8")
    if stale:
        print(f"Run python scripts/gen_attestation_examples.py to update {', '.join(stale)}")
    return int(bool(stale))


if __name__ == "__main__":
    raise SystemExit(main())
