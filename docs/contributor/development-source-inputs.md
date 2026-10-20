---
type: guide
title: "Produce immutable development source inputs"
description: "Capture review-only source, dependency and backend inputs without admitting or publishing packages."
resource: "https://github.com/honua-io/honua-sdk-python/issues/311"
tags: [python, development, release]
---
# Review-only development source inputs

`python scripts/development_source_inputs.py --source /absolute/clean/checkout --revision FULL_40_CHARACTER_SHA --destination /absolute/new/proposal-directory`

Run with the exact Python, pip, packaging and platform declared in
`scripts/development-inputs/runtime.json`. The source must be a clean immutable
checkout of this repository. Outputs stay outside the checkout. The producer
captures every tracked source input and derives the core, grpc, geopandas,
raster, and combined SDK-with-all-extras plus Admin profiles from the actual
package metadata. All five profiles are mandatory.

The producer implementation and subject checkout have separate immutable
identities. A protected producer can inspect an older, still-governed clean
subject using `--source` and `--revision`; this does not adopt newer package
versions or turn source-built wheels into published artifacts.

The proposal also captures each original README and INSTALL source-install
block, including its exact document and fence bytes, ordered pip commands,
requested extras and editable flags. Each block uses an isolated environment;
each pip step records its actual resolver delta and installed closure before
and after execution. The backend closure is installed with hash enforcement
before source metadata or editable build hooks execute. Non-pip lint and test
commands remain unchanged for the executable-docs replay and are not executed
or counted as passed by this producer.

Default pip compilation remains enabled. Verification checks a finite mapping
from original wheel members to installed files, including pip metadata,
entrypoint scripts and compiled bytecode, and rejects extra installed or
editable-source files. Editable wheels and their exact copied source tree have
separate provenance from regular source-built wheels.

The default runtime policy describes the reviewed producer runtime. It does
not assert equivalence with a documentation container image. The later harness
must bind the actual governed image and invoked interpreter; a runtime mismatch
remains nonpassing until that exact input is produced and reviewed.

For the original governed documentation subject, first make the exact
`python:3.12-bookworm@sha256:e91fec3d1ac69f04e4eddcd29c327e630ce34658cf31075bfa7e8b0e052bafea`
image available to Docker, then use the governed launcher:

```bash
python3 scripts/run_governed_source_inputs.py --implementation /absolute/clean/producer-checkout --source /absolute/clean/governed-subject --revision 5a79352066b8aa23f1bae45b5c38e6d83efd003f --destination /absolute/new/governed-inputs
```

This subject remains SDK 0.1.16 and Admin 0.1.12. The producer implementation
has its own revision. The launcher uses the original image's Python 3.12.15
and pip 25.0.1, with their exact reviewed executable and tool hashes. Packaging
26.3 is a separately hash-verified, read-only implementation import; it is
never installed into the image and is excluded from every subject pip/backend
subprocess. Actual child observations and seven input-refusal controls check
that separation. Original pip compilation remains enabled.

The outer `execution.json` and original container observations bind the actual
image digest, container image ID, immutable subject and implementation, command,
read-only mounts, terminal state and cleanup. The inner `proposal/proposal.json`
binds all artifact and ordered input captures. A consumer must rejudge both
sets of original evidence; the policy's image string alone grants no identity
or admission. Failed actions retain their original output and daemon state.
A transport failure waits for live owned work to finish rather than cancelling
it. Unresolved work remains explicitly pending.

This captures inputs using declared fixed-interpreter commands, including
separate offline installation of the verified artifacts. It does not report
that the unchanged documentation commands, lint commands or full tests ran.
Those original commands and their actual runtime replay remain required by
honua-release issue 721.

Each profile retains the actual resolver command, interpreter environment,
original report and output, and anonymously downloaded wheels with canonical
PyPI origins, metadata, exact versions and SHA256 hashes. An independent registry
response must agree with every artifact. Dependency markers and extras are
rejudged recursively; missing dependencies fail. The exact Hatchling build
closure is resolved separately, installed with hash enforcement into a disposable
backend environment, and used without build isolation, dependency resolution or
network indexes to build both packages from tracked source bytes only.

`python scripts/development_source_inputs.py --verify --source /absolute/clean/checkout --revision FULL_40_CHARACTER_SHA --destination /absolute/existing/proposal-directory`

Verification rejoins source/runtime, original resolver reports, all profiles,
artifact bytes and recursive closure, and the separate source-built wheels.
Source or runtime refusal occurs before resolver execution. Drift detected after
resolution refuses before backend installation. Failure outputs are retained;
a missing final `proposal.json` is a failed proposal, never an admitted input.

This is an input proposal for honua-release issue 721 and Python issue 311.
Generation and verification do not admit a source install, relax default
PEP610/direct-origin refusal, establish published wheel identity, publish a
package, change a version or release pin, or qualify a release candidate. The
SDK and Admin publication sources may differ; these source-built wheels carry
their actual checkout identity and never inherit a published artifact's identity.
Every original document and command remains required for the later admitted
source and exact-candidate replay.
