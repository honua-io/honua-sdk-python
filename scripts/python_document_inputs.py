"""Capture original ordered source-install inputs; never execute documentation's lint/test commands."""
from __future__ import annotations

import base64
import configparser
import csv
import hashlib
import importlib.util
import io
import json
import marshal
import struct
import zipfile
from pathlib import Path
import re
import shlex
import sys
import tempfile
from urllib.parse import unquote, urlsplit

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

SOURCE_TARGET = re.compile(r"(?:\./)?packages/(honua-sdk|honua-admin)(?:\[([a-z,]+)\])?")
TOOLS = {"pytest", "pytest-cov", "ruff", "mypy"}
FENCE = re.compile(r"^```([^\n]*)\n(.*?)^```[ \t]*$", re.MULTILINE | re.DOTALL)
INVENTORY_PROGRAM = r'''import base64,hashlib,importlib.metadata,json,pathlib,sys
rows={}
boundaries=[pathlib.Path(sys.prefix).resolve(), pathlib.Path(sys.prefix).resolve().parent/"source"]
site_files={}
site_roots=set()
for dist in importlib.metadata.distributions():
 files={}
 sizes={}
 generated={}
 site=pathlib.Path(dist.locate_file('')).resolve()
 site_roots.add(site)
 for item in dist.files or []:
  path=dist.locate_file(item)
  if not any(path.resolve().is_relative_to(root) for root in boundaries): raise ValueError('installed metadata escapes owned context')
  if path.is_symlink() or not path.is_file(): raise ValueError('installed record is not a regular file')
  data=path.read_bytes()
  key=str(item)
  files[key]=hashlib.sha256(data).hexdigest()
  sizes[key]=len(data)
  if path.resolve().is_relative_to(site): site_files[str(path.resolve())]=files[key]
  if key.endswith(('.pyc','/INSTALLER','/REQUESTED','/direct_url.json','/RECORD')) or key.startswith('../'):
   generated[key]=base64.b64encode(data).decode('ascii')
 name=dist.metadata['Name'].lower().replace('_','-')
 if name in rows: raise ValueError('duplicate installed distribution')
 direct=dist.read_text('direct_url.json')
 rows[name]={'name':name,'version':dist.version,'requiresDist':dist.requires or [],
             'metadataSha256':hashlib.sha256(dist.read_text('METADATA').encode()).hexdigest(),
             'files':files,'sizes':sizes,'generated':generated,'sitePackages':str(site),'python':sys.executable,
             'directUrl':json.loads(direct) if direct else None}
actual={}
for site in site_roots:
 for path in site.rglob('*'):
  if path.is_symlink(): raise ValueError('installed site contains symlink')
  if path.is_file(): actual[str(path.resolve())]=hashlib.sha256(path.read_bytes()).hexdigest()
  elif not path.is_dir(): raise ValueError('installed site contains special entry')
if actual!=site_files: raise ValueError('installed site contains unrecorded or missing files')
census=hashlib.sha256(json.dumps(site_files,sort_keys=True).encode()).hexdigest()
for row in rows.values(): row['siteCensusSha256']=census
print(json.dumps(rows,sort_keys=True))'''
HOOK_PROGRAM = "import hatchling.build,json; print(json.dumps({'wheel':hatchling.build.get_requires_for_build_wheel(), 'editable':hatchling.build.get_requires_for_build_editable()}))"


def plan(engine, root: Path, source: dict) -> list[dict]:
    contexts = []
    for document in ("README.md", "INSTALL.md"):
        text = (root / document).read_text()
        for index, block in enumerate(FENCE.finditer(text)):
            code = block[2]
            if "packages/honua-" not in code and "git clone https://github.com/honua-io/honua-sdk-python.git" not in code:
                continue
            if block[1].strip().split()[0] not in ("bash", "sh", "shell"):
                raise ValueError("source documentation is not executable shell")
            invocations = []
            for line in code.splitlines():
                words = shlex.split(line, comments=True)
                if words[:2] != ["pip", "install"]:
                    continue
                targets, editable, pending = [], [], False
                for word in words[2:]:
                    if word == "-e" and not pending:
                        pending = True
                        continue
                    match = SOURCE_TARGET.fullmatch(word)
                    if not match and (pending or word not in TOOLS):
                        raise ValueError("unreviewed documented source target or option")
                    targets.append(word)
                    editable.append(pending)
                    pending = False
                if not targets or pending:
                    raise ValueError("incomplete documented pip invocation")
                invocations.append({"ordinal": len(invocations), "command": line, "commandSha256": engine.digest(line.encode()),
                                    "requested": targets, "editable": editable})
            if not invocations:
                raise ValueError("source documentation has no install invocation")
            contexts.append({"document": document, "documentSha256": engine.digest(text.encode()),
                             "documentGitBlob": source["files"][document]["gitBlob"], "blockIndex": index,
                             "blockSha256": engine.digest(code.encode()), "blockBytes": code,
                             "invocations": invocations})
    if not any(x["document"] == "INSTALL.md" for x in contexts) or sum(x["document"] == "README.md" for x in contexts) < 2:
        raise ValueError("missing original source documentation contexts")
    return contexts


def translated(invocation: dict, checkout: Path) -> list[str]:
    result = []
    for word, editable in zip(invocation["requested"], invocation["editable"], strict=True):
        if editable:
            result.append("-e")
        match = SOURCE_TARGET.fullmatch(word)
        result.append(str(checkout / "packages" / match[1]) + ("[" + match[2] + "]" if match[2] else "") if match else word)
    return result


def roots(source: dict, invocations: list[dict], backend: list[str]) -> list[str]:
    requested = set(backend)
    for invocation in invocations:
        for word in invocation["requested"]:
            match = SOURCE_TARGET.fullmatch(word)
            if match is None:
                requested.add(word)
                continue
            metadata = source["packages"][match[1]]["metadata"]
            values = list(metadata.get("dependencies", []))
            for extra in (match[2] or "").split(","):
                if extra:
                    values.extend(metadata["optional-dependencies"][extra])
            for value in values:
                req = Requirement(value)
                if canonicalize_name(req.name) not in ("honua-sdk", "honua-admin"):
                    requested.add(value)
                elif source["packages"][canonicalize_name(req.name)]["metadata"]["version"] not in req.specifier:
                    raise ValueError("source package dependency excludes immutable source version")
    return sorted(requested)


def inventory(engine, python: Path) -> dict:
    return json.loads(engine.run([str(python), "-c", INVENTORY_PROGRAM]))


def source_hashes(engine, source: dict, checkout: Path) -> dict:
    expected = {path: item["sha256"] for path, item in source["files"].items()
                if path.startswith(("packages/honua-sdk/", "packages/honua-admin/"))}
    expected_directories = {parent.as_posix() for path in expected for parent in Path(path).parents if parent.as_posix() != "."}
    if any(path.is_symlink() or not path.is_dir() for path in (checkout, checkout / "packages")):
        raise ValueError("copied immutable source ancestor is not a regular directory")
    actual = {}
    directories = set()
    for package in ("packages/honua-sdk", "packages/honua-admin"):
        base = checkout / package
        if base.is_symlink() or not base.is_dir():
            raise ValueError("copied immutable source root is not a regular directory")
        directories.add(package)
        for path in base.rglob("*"):
            relative = path.relative_to(checkout).as_posix()
            if path.is_symlink():
                raise ValueError("copied immutable source contains a symlink")
            if path.is_file():
                actual[relative] = engine.digest(path.read_bytes())
            elif path.is_dir():
                directories.add(relative)
            else:
                raise ValueError("copied immutable source contains a special entry")
    if actual != expected or directories != expected_directories - {"packages"}:
        raise ValueError("copied immutable source tree differs from finite tracked inputs")
    return actual


def copy_source(source: dict, root: Path, checkout: Path) -> None:
    for path, item in source["files"].items():
        if path.startswith(("packages/honua-sdk/", "packages/honua-admin/")):
            if item["mode"] not in ("100644", "100755"):
                raise ValueError("source build package contains unsupported entry")
            target = checkout / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((root / path).read_bytes())


def step_command(python: Path, checkout: Path, invocation: dict, report: Path, *, offline: Path | None) -> list[str]:
    flags = ["--no-index", "--find-links", str(offline)] if offline else ["--dry-run", "--index-url", "https://pypi.org/simple"]
    return [sys.executable, "-m", "pip", "--isolated", "--python", str(python), "install", "--no-build-isolation",
            "--only-binary=:all:", "--disable-pip-version-check", "--no-input", *flags, "--report", str(report),
            *translated(invocation, checkout)]


def expected_sources(source: dict, invocation: dict, checkout: Path) -> dict:
    return {match[1]: {"url": (checkout / "packages" / match[1]).as_uri(), "editable": editable,
                      "version": source["packages"][match[1]]["metadata"]["version"]}
            for word, editable in zip(invocation["requested"], invocation["editable"], strict=True)
            if (match := SOURCE_TARGET.fullmatch(word))}


def direct_matches(observed: dict, expected: dict) -> bool:
    return (isinstance(observed, dict) and set(observed) == {"url", "dir_info"}
            and observed["url"] == expected["url"] and isinstance(observed["dir_info"], dict)
            and set(observed["dir_info"]) <= {"editable"}
            and observed["dir_info"].get("editable", False) is expected["editable"])


def report_items(engine, raw: dict, source: dict, invocation: dict, checkout: Path, *, warehouse: Path | None = None) -> tuple[dict, list[dict]]:
    expected = expected_sources(source, invocation, checkout)
    local, remote = {}, []
    for item in raw["install"]:
        info, metadata = item["download_info"], item["metadata"]
        name = canonicalize_name(metadata["name"])
        url = info["url"]
        if urlsplit(url).scheme == "file":
            if name not in source["packages"]:
                filename = Path(unquote(urlsplit(url).path)).name
                if warehouse is None or url != (warehouse / filename).as_uri() or not filename.endswith(".whl"):
                    raise ValueError("offline artifact origin escaped captured warehouse")
                remote.append(item)
                continue
            if name not in expected or not direct_matches(info, expected[name]):
                raise ValueError("unbound source resolution origin")
            if metadata["version"] != expected[name]["version"]:
                raise ValueError("source resolution version or editable mode differs")
            if name in local:
                raise ValueError("duplicate source resolution item")
            local[name] = item
        else:
            engine.canonical_origin(url)
            remote.append(item)
    if set(local) != set(expected):
        raise ValueError("missing actual source resolution item")
    return local, remote


SCRIPT_TEMPLATE = """# -*- coding: utf-8 -*-
import re
import sys
if __name__ == '__main__':
    from {module} import {import_name}
    sys.argv[0] = re.sub(r'(-script\\.pyw|\\.exe)?$', '', sys.argv[0])
    sys.exit({function}())
"""


def installed_wheel_bytes(engine, observed: dict, archive_path: Path) -> None:
    files, sizes, generated = observed.get("files"), observed.get("sizes"), observed.get("generated")
    if not isinstance(files, dict) or not files or not isinstance(sizes, dict) or set(files) != set(sizes) or not isinstance(generated, dict):
        raise ValueError("installed file observation is incomplete")
    site, python = Path(observed["sitePackages"]), Path(observed["python"])
    if not site.is_absolute() or not python.is_absolute() or python.parent.name != "bin":
        raise ValueError("installed paths are not bound to an owned interpreter")
    expected = {}
    with zipfile.ZipFile(archive_path) as archive:
        metadata_dirs = {name.rsplit("/", 1)[0] for name in archive.namelist() if name.endswith(".dist-info/METADATA")}
        if len(metadata_dirs) != 1:
            raise ValueError("wheel metadata directory is ambiguous")
        metadata_dir = metadata_dirs.pop()
        record_name = metadata_dir + "/RECORD"
        for name in archive.namelist():
            if name.endswith("/") or name == record_name:
                continue
            data = archive.read(name)
            if ".data/scripts/" in name:
                if data.startswith((b"#!python\n", b"#!pythonw\n")):
                    raise ValueError("unmodeled wheel script shebang transformation")
                selected = str(Path("../../../bin") / Path(name).name)
            elif ".data/" in name:
                raise ValueError("unmodeled wheel install transformation")
            else:
                selected = name
            if selected in expected:
                raise ValueError("duplicate installed wheel mapping")
            expected[selected] = data
        entrypoints = metadata_dir + "/entry_points.txt"
        if entrypoints in archive.namelist():
            parser = configparser.ConfigParser(interpolation=None)
            parser.optionxform = str
            parser.read_string(archive.read(entrypoints).decode())
            for section in ("console_scripts", "gui_scripts"):
                for name, value in parser.items(section) if parser.has_section(section) else []:
                    match = re.fullmatch(r"([A-Za-z_][\w.]*)\s*:\s*([A-Za-z_][\w.]*)\s*", value)
                    if match is None or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
                        raise ValueError("unmodeled installed entrypoint")
                    if len(str(python).encode()) + 3 > 127 or any(c.isspace() for c in str(python)):
                        raise ValueError("unmodeled installed script interpreter path")
                    script = SCRIPT_TEMPLATE.format(module=match[1], import_name=match[2].split(".")[0], function=match[2])
                    expected["../../../bin/" + name] = ("#!" + str(python) + "\n" + script).encode()
        expected[metadata_dir + "/INSTALLER"] = b"pip\n"
        if metadata_dir + "/REQUESTED" in files:
            expected[metadata_dir + "/REQUESTED"] = b""
        if observed["directUrl"] is not None:
            expected[metadata_dir + "/direct_url.json"] = json.dumps(observed["directUrl"], sort_keys=True).encode()
        # Default pip compilation is retained. Validate cache code against verified
        # wheel sources and this exact interpreter, without executing package code.
        for name, source_bytes in list(expected.items()):
            if not name.endswith(".py") or name.startswith("../"):
                continue
            absolute = str(site / name)
            cache = str(Path(importlib.util.cache_from_source(absolute)).relative_to(site))
            if cache not in files:
                raise ValueError("default pip compiled bytecode is missing")
            raw = base64.b64decode(generated.get(cache, ""), validate=True)
            if len(raw) < 16 or raw[:4] != importlib.util.MAGIC_NUMBER or raw[4:8] != b"\x00" * 4:
                raise ValueError("unmodeled compiled bytecode header")
            if struct.unpack("<I", raw[12:16])[0] != len(source_bytes):
                raise ValueError("compiled bytecode source size differs")
            if raw[16:] != marshal.dumps(compile(source_bytes, absolute, "exec", dont_inherit=True, optimize=0)):
                raise ValueError("compiled bytecode differs from verified wheel source")
            expected[cache] = raw
        # RECORD is generated by pip; its finite rows must describe exactly the
        # modeled files, with actual digest/size and only bytecode/self unhashed.
        record = base64.b64decode(generated.get(record_name, ""), validate=True)
        rows = list(csv.reader(io.StringIO(record.decode(), newline="")))
        if any(len(row) != 3 for row in rows) or len({row[0] for row in rows}) != len(rows):
            raise ValueError("installed RECORD rows are malformed or duplicated")
        if {row[0] for row in rows} != set(expected) | {record_name}:
            raise ValueError("installed RECORD has extra or missing files")
        for name, digest, size in rows:
            if name == record_name or name.endswith(".pyc"):
                if digest or size:
                    raise ValueError("generated RECORD self/cache row differs")
            else:
                content = expected[name]
                encoded = base64.urlsafe_b64encode(hashlib.sha256(content).digest()).rstrip(b"=").decode()
                if digest != "sha256=" + encoded or size != str(len(content)):
                    raise ValueError("installed RECORD digest or size differs")
        expected[record_name] = record
    if set(files) != set(expected):
        raise ValueError("installed distribution has extra or missing files")
    if set(generated) != {name for name in expected if name.endswith((".pyc", "/INSTALLER", "/REQUESTED", "/direct_url.json", "/RECORD")) or name.startswith("../")}:
        raise ValueError("generated installed file census differs")
    for name, content in expected.items():
        if files[name] != engine.digest(content) or type(sizes[name]) is not int or sizes[name] != len(content):
            raise ValueError("installed file differs from modeled original wheel input")
        if name in generated and base64.b64decode(generated[name], validate=True) != content:
            raise ValueError("generated installed file bytes differ")
    if observed["metadataSha256"] != engine.digest(expected[metadata_dir + "/METADATA"]):
        raise ValueError("installed metadata differs from original wheel")


def installed_source_and_artifact_bytes(engine, *, after: dict, active: list[dict], warehouse: Path,
                                        origins: dict, source_build: dict, destination: Path, context: dict, public: Path) -> None:
    census = {}
    scratch = engine.scratch_identity(context["scratchRoot"], "honua-document-context-")
    expected_python = scratch / "environment/bin/python"
    expected_site = scratch / ("environment/lib/python" + str(sys.version_info.major) + "." + str(sys.version_info.minor) + "/site-packages")
    for row in after.values():
        site = Path(row["sitePackages"])
        if site != expected_site or row["python"] != str(expected_python):
            raise ValueError("installed observation differs from the owned interpreter context")
        for name, digest in row["files"].items():
            path = (site / name).resolve()
            if path.is_relative_to(site):
                if str(path) in census:
                    raise ValueError("installed distributions overlap")
                census[str(path)] = digest
    census_digest = engine.digest(json.dumps(census, sort_keys=True).encode())
    if any(row.get("siteCensusSha256") != census_digest for row in after.values()):
        raise ValueError("installed finite site census differs")
    for artifact in active:
        installed_wheel_bytes(engine, after[artifact["name"]], warehouse / artifact["filename"])
    for name, origin in origins.items():
        if origin["editable"]:
            item = next(item for item in context["editableWheels"] if item["name"] == name)
            archive = public / "editable-wheels" / item["filename"]
        else:
            item = next(item for item in source_build["wheels"] if item["name"] == name)
            archive = destination / "source-wheels" / item["filename"]
        installed_wheel_bytes(engine, after[name], archive)


def capture(engine, proposal: dict, root: Path, destination: Path) -> list[dict]:
    source = proposal["source"]
    planned = plan(engine, root, source)
    base_artifacts = proposal["build"]["artifacts"]
    contexts = []
    for number, declaration in enumerate(planned):
        public = destination / f"document-{number}"
        public.mkdir()
        warehouse = public / "wheels"
        warehouse.mkdir()
        with tempfile.TemporaryDirectory(prefix="honua-document-context-", dir=str(Path(tempfile.gettempdir()).resolve())) as temporary:
            scratch = engine.scratch_identity(temporary, "honua-document-context-")
            checkout, environment = scratch / "source", scratch / "environment"
            python = environment / "bin/python"
            copy_source(source, root, checkout)
            engine.run([sys.executable, "-m", "venv", "--without-pip", str(environment)])
            lock = scratch / "backend.lock"
            lock.write_text("\n".join(f'{x["name"]}=={x["version"]} --hash=sha256:{x["sha256"]}' for x in base_artifacts) + "\n")
            bootstrap_command = [sys.executable, "-m", "pip", "--isolated", "--python", str(python), "install", "--no-index",
                                 "--find-links", str(destination / "build"), "--require-hashes", "-r", str(lock)]
            if engine.source(root, source["sourceSha"]) != source:
                raise ValueError("source changed before documentation backend bootstrap")
            source_hashes(engine, source, checkout)
            engine.run(bootstrap_command)
            source_hashes(engine, source, checkout)
            hooks = {}
            for name in ("honua-sdk", "honua-admin"):
                command = [str(python), "-c", HOOK_PROGRAM]
                source_hashes(engine, source, checkout)
                raw = engine.run(command, cwd=checkout / "packages" / name)
                source_hashes(engine, source, checkout)
                result = json.loads(raw)
                if set(result) != {"wheel", "editable"} or any(not isinstance(v, list) for v in result.values()):
                    raise ValueError("backend hook inputs are incomplete")
                hooks[name] = {"command": command, "cwd": str(checkout / "packages" / name),
                               "result": result, "rawSha256": engine.digest(raw)}
                (public / f"{name}-backend-hooks.json").write_bytes(raw)
            dynamic = sorted({value for item in hooks.values() for values in item["result"].values() for value in values})
            for value in dynamic:
                if Requirement(value).url:
                    raise ValueError("backend dynamic direct origin refused")
            baseline_roots = [f'{x["name"]}=={x["version"]}' for x in base_artifacts]
            backend_dynamic = None
            if dynamic:
                backend_dynamic = engine.resolve(sorted(set(baseline_roots + dynamic)), public / "backend-dynamic")
                lock.write_text("\n".join(f'{x["name"]}=={x["version"]} --hash=sha256:{x["sha256"]}' for x in backend_dynamic["artifacts"]) + "\n")
                dynamic_command = [sys.executable, "-m", "pip", "--isolated", "--python", str(python), "install", "--no-index",
                                   "--find-links", str(public / "backend-dynamic"), "--require-hashes", "-r", str(lock)]
                source_hashes(engine, source, checkout)
                engine.run(dynamic_command)
                source_hashes(engine, source, checkout)
                backend_artifacts = backend_dynamic["artifacts"]
            else:
                dynamic_command = None
                backend_artifacts = base_artifacts
            # Retain actual editable build provenance separately from regular wheels.
            editable_directory = public / "editable-wheels"
            editable_directory.mkdir()
            editable_wheels = []
            for name in ("honua-sdk", "honua-admin"):
                program = "import hatchling.build; print(hatchling.build.build_editable(" + repr(str(editable_directory)) + "))"
                command = [str(python), "-c", program]
                source_hashes(engine, source, checkout)
                engine.run(command, cwd=checkout / "packages" / name)
                source_hashes(engine, source, checkout)
                candidates = list(editable_directory.glob(name.replace("-", "_") + "-*.whl"))
                if len(candidates) != 1:
                    raise ValueError("editable build did not produce one exact source package")
                data = candidates[0].read_bytes()
                actual_name, version, dependencies = engine.wheel_metadata(data, candidates[0].name)
                if actual_name != name or version != source["packages"][name]["metadata"]["version"]:
                    raise ValueError("editable source-built wheel identity differs")
                editable_wheels.append({"name": name, "version": version, "filename": candidates[0].name,
                                        "sha256": engine.digest(data), "requiresDist": dependencies,
                                        "command": command, "cwd": str(checkout / "packages" / name),
                                        "publishedIdentity": False, "sourceSha": source["sourceSha"]})
            available = {(x["name"], x["version"]): x for x in backend_artifacts}
            for item in backend_artifacts:
                parent = public / "backend-dynamic" if dynamic else destination / "build"
                (warehouse / item["filename"]).write_bytes((parent / item["filename"]).read_bytes())
            initial = inventory(engine, python)
            if {k: v["version"] for k, v in initial.items()} != {x["name"]: x["version"] for x in backend_artifacts}:
                raise ValueError("documentation backend baseline differs")
            context = {**declaration, "scratchRoot": str(scratch), "bootstrapCommand": bootstrap_command,
                       "bootstrapLock": "\n".join(f'{x["name"]}=={x["version"]} --hash=sha256:{x["sha256"]}' for x in base_artifacts) + "\n",
                       "hooks": hooks, "dynamicBackend": backend_dynamic, "dynamicCommand": dynamic_command,
                       "dynamicLock": lock.read_text(), "editableWheels": editable_wheels,
                       "initialInstalled": initial, "steps": []}
            installed_source_and_artifact_bytes(engine, after=initial, active=backend_artifacts, warehouse=warehouse,
                                                origins={}, source_build=proposal["sourceBuild"], destination=destination,
                                                context=context, public=public)
            origins = {}
            for ordinal, invocation in enumerate(declaration["invocations"]):
                before = inventory(engine, python)
                before_hashes = source_hashes(engine, source, checkout)
                resolver_report = scratch / f"resolver-{ordinal}.json"
                installed_report = scratch / f"installed-{ordinal}.json"
                command = step_command(python, checkout, invocation, resolver_report, offline=None)
                stdout = engine.run(command, cwd=checkout)
                resolved_hashes = source_hashes(engine, source, checkout)
                raw = json.loads(resolver_report.read_bytes())
                local, remote = report_items(engine, raw, source, invocation, checkout)
                artifacts = engine.download_artifacts(remote, warehouse)
                for item in artifacts:
                    available[item["name"], item["version"]] = item
                install = step_command(python, checkout, invocation, installed_report, offline=warehouse)
                source_hashes(engine, source, checkout)
                install_output = engine.run(install, cwd=checkout)
                actual_install = json.loads(installed_report.read_bytes())
                installed_local, installed_remote = report_items(engine, actual_install, source, invocation, checkout, warehouse=warehouse)
                if installed_local.keys() != local.keys():
                    raise ValueError("offline source install differs from resolver")
                for item in installed_remote:
                    filename = Path(unquote(urlsplit(item["download_info"]["url"]).path)).name
                    if item["download_info"]["url"] != (warehouse / filename).as_uri():
                        raise ValueError("offline install escaped captured warehouse")
                after = inventory(engine, python)
                after_hashes = source_hashes(engine, source, checkout)
                versions = {k: x["version"] for k, x in before.items()}
                versions.update({canonicalize_name(x["metadata"]["name"]): x["metadata"]["version"] for x in raw["install"]})
                if versions != {k: v["version"] for k, v in after.items()}:
                    raise ValueError("actual installed delta differs from resolver")
                if any(after[k]["version"] != value["version"] for k, value in initial.items()):
                    raise ValueError("documentation install changed reviewed backend closure")
                active = [available[k, v["version"]] for k, v in after.items() if k not in source["packages"]]
                required = roots(source, declaration["invocations"][:ordinal + 1], [f'{x["name"]}=={x["version"]}' for x in backend_artifacts])
                engine.validate_closure(active, required, warehouse)
                for name, expected in expected_sources(source, invocation, checkout).items():
                    direct = after[name]["directUrl"]
                    if not direct_matches(direct, expected):
                        raise ValueError("actual source install origin or editable mode differs")
                origins.update(expected_sources(source, invocation, checkout))
                installed_source_and_artifact_bytes(engine, after=after, active=active, warehouse=warehouse,
                                                    origins=origins, source_build=proposal["sourceBuild"], destination=destination,
                                                    context=context, public=public)
                # Persist only validated canonical/local owned inputs. No raw failing URLs.
                for label, value in [("resolver", resolver_report.read_bytes()), ("installed", installed_report.read_bytes()),
                                     ("before", json.dumps(before, sort_keys=True).encode()), ("after", json.dumps(after, sort_keys=True).encode()),
                                     ("resolver.stdout", stdout), ("install.stdout", install_output)]:
                    (public / f"step-{ordinal}-{label}.json").write_bytes(value)
                context["steps"].append({**invocation, "sourceSha": source["sourceSha"], "blockIndex": declaration["blockIndex"],
                                         "blockSha256": declaration["blockSha256"], "commandDerived": command, "installCommand": install,
                                         "sourceBefore": before_hashes, "sourceResolved": resolved_hashes, "sourceAfter": after_hashes, "before": before, "after": after,
                                         "artifacts": artifacts, "activeArtifacts": active, "requiredClosure": required,
                                         "rawHashes": {label: engine.digest((public / f"step-{ordinal}-{label}.json").read_bytes())
                                                       for label in ("resolver", "installed", "before", "after", "resolver.stdout", "install.stdout")}})
            contexts.append(context)
    return contexts


def verify(engine, proposal: dict, root: Path, destination: Path) -> None:
    source = proposal["source"]
    expected = plan(engine, root, source)
    contexts = proposal.get("documentationSequences")
    if not isinstance(contexts, list) or len(contexts) != len(expected):
        raise ValueError("missing original documentation sequence")
    expected_source = {path: item["sha256"] for path, item in source["files"].items()
                       if path.startswith(("packages/honua-sdk/", "packages/honua-admin/"))}
    base = proposal["build"]["artifacts"]
    for number, (context, declaration) in enumerate(zip(contexts, expected, strict=True)):
        if any(context.get(key) != value for key, value in declaration.items()):
            raise ValueError("documentation command/source/block bytes differ")
        public = destination / f"document-{number}"
        warehouse = public / "wheels"
        scratch = engine.scratch_identity(context["scratchRoot"], "honua-document-context-")
        python, checkout = scratch / "environment/bin/python", scratch / "source"
        lock = scratch / "backend.lock"
        bootstrap = [sys.executable, "-m", "pip", "--isolated", "--python", str(python), "install", "--no-index",
                     "--find-links", str(destination / "build"), "--require-hashes", "-r", str(lock)]
        if context["bootstrapCommand"] != bootstrap or context["bootstrapLock"] != "\n".join(
                f'{x["name"]}=={x["version"]} --hash=sha256:{x["sha256"]}' for x in base) + "\n":
            raise ValueError("documentation backend bootstrap input differs")
        if set(context["hooks"]) != set(source["packages"]):
            raise ValueError("incomplete actual backend hook observations")
        dynamic = set()
        for name, item in context["hooks"].items():
            raw = (public / f"{name}-backend-hooks.json").read_bytes()
            if (engine.digest(raw) != item["rawSha256"] or json.loads(raw) != item["result"]
                    or item["command"] != [str(python), "-c", HOOK_PROGRAM]
                    or item["cwd"] != str(checkout / "packages" / name) or set(item["result"]) != {"wheel", "editable"}):
                raise ValueError("original backend hook inputs differ")
            for values in item["result"].values():
                for value in values:
                    if Requirement(value).url:
                        raise ValueError("backend direct origin refused")
                    dynamic.add(value)
        if dynamic:
            value = context["dynamicBackend"]
            requested = sorted(set([f'{x["name"]}=={x["version"]}' for x in base]) | dynamic)
            if value["requested"] != requested:
                raise ValueError("editable backend closure input differs")
            engine.verify_resolution(value, requested, public / "backend-dynamic", {"pip": proposal["runtime"]["pip"]})
            artifacts = value["artifacts"]
            dynamic_command = [sys.executable, "-m", "pip", "--isolated", "--python", str(python), "install", "--no-index",
                               "--find-links", str(public / "backend-dynamic"), "--require-hashes", "-r", str(lock)]
            if context["dynamicCommand"] != dynamic_command:
                raise ValueError("editable backend command differs")
        else:
            if context["dynamicBackend"] is not None or context["dynamicCommand"] is not None:
                raise ValueError("unexpected dynamic backend")
            artifacts = base
        if context["dynamicLock"] != "\n".join(f'{x["name"]}=={x["version"]} --hash=sha256:{x["sha256"]}' for x in artifacts) + "\n":
            raise ValueError("actual backend lock differs")
        if {x["name"] for x in context["editableWheels"]} != set(source["packages"]):
            raise ValueError("editable build coverage incomplete")
        for item in context["editableWheels"]:
            name = item["name"]
            data = (public / "editable-wheels" / item["filename"]).read_bytes()
            actual_name, version, dependencies = engine.wheel_metadata(data, item["filename"])
            program = "import hatchling.build; print(hatchling.build.build_editable(" + repr(str(public / "editable-wheels")) + "))"
            if (engine.digest(data) != item["sha256"] or actual_name != name or version != source["packages"][name]["metadata"]["version"]
                    or dependencies != item["requiresDist"] or item["publishedIdentity"] is not False or item["sourceSha"] != source["sourceSha"]
                    or item["command"] != [str(python), "-c", program] or item["cwd"] != str(checkout / "packages" / name)):
                raise ValueError("editable build source/runtime provenance differs")
        previous = context["initialInstalled"]
        if {k: v["version"] for k, v in previous.items()} != {x["name"]: x["version"] for x in artifacts}:
            raise ValueError("original backend installed baseline differs")
        installed_source_and_artifact_bytes(engine, after=previous, active=artifacts, warehouse=warehouse,
                                            origins={}, source_build=proposal["sourceBuild"], destination=destination,
                                            context=context, public=public)
        steps = context["steps"]
        if len(steps) != len(declaration["invocations"]):
            raise ValueError("missing ordered pip invocation")
        available = {(x["name"], x["version"]): x for x in artifacts}
        source_origins = {}
        for ordinal, (step, invocation) in enumerate(zip(steps, declaration["invocations"], strict=True)):
            if any(step.get(k) != v for k, v in invocation.items()) or any(step.get(k) != declaration[k] for k in ("blockIndex", "blockSha256")):
                raise ValueError("original invocation order/editable/target bytes differ")
            if step["sourceSha"] != source["sourceSha"] or step["sourceBefore"] != expected_source or step["sourceResolved"] != expected_source or step["sourceAfter"] != expected_source:
                raise ValueError("per-invocation source input lineage differs")
            if step["before"] != previous:
                raise ValueError("ordered installed closure lineage differs")
            resolver = scratch / f"resolver-{ordinal}.json"
            installed = scratch / f"installed-{ordinal}.json"
            if (step["commandDerived"] != step_command(python, checkout, invocation, resolver, offline=None)
                    or step["installCommand"] != step_command(python, checkout, invocation, installed, offline=warehouse)):
                raise ValueError("fixed interpreter invocation differs")
            for label in ("resolver", "installed", "before", "after", "resolver.stdout", "install.stdout"):
                data = (public / f"step-{ordinal}-{label}.json").read_bytes()
                if engine.digest(data) != step["rawHashes"][label]:
                    raise ValueError("original invocation observation bytes differ")
                if label in ("before", "after") and json.loads(data) != step[label]:
                    raise ValueError("original installed metadata differs")
            raw = json.loads((public / f"step-{ordinal}-resolver.json").read_bytes())
            actual = json.loads((public / f"step-{ordinal}-installed.json").read_bytes())
            local, remote = report_items(engine, raw, source, invocation, checkout)
            installed_local, installed_remote = report_items(engine, actual, source, invocation, checkout, warehouse=warehouse)
            expected_artifacts = {canonicalize_name(x["metadata"]["name"]): (x["metadata"]["version"], x["download_info"]["url"],
                                         x["download_info"]["archive_info"]["hashes"]["sha256"]) for x in remote}
            if {x["name"]: (x["version"], x["origin"], x["sha256"]) for x in step["artifacts"]} != expected_artifacts:
                raise ValueError("original resolver artifact delta differs")
            for item in step["artifacts"]:
                available[item["name"], item["version"]] = item
            versions = {k: v["version"] for k, v in step["before"].items()}
            versions.update({canonicalize_name(x["metadata"]["name"]): x["metadata"]["version"] for x in raw["install"]})
            if versions != {k: v["version"] for k, v in step["after"].items()} or local.keys() != installed_local.keys():
                raise ValueError("actual installed version delta differs")
            for item in installed_remote:
                name = canonicalize_name(item["metadata"]["name"])
                version = item["metadata"]["version"]
                expected_item = available[name, version]
                if item["download_info"]["url"] != (warehouse / expected_item["filename"]).as_uri():
                    raise ValueError("offline artifact delta differs")
            active = [available[k, v["version"]] for k, v in step["after"].items() if k not in source["packages"]]
            required = roots(source, declaration["invocations"][:ordinal + 1], [f'{x["name"]}=={x["version"]}' for x in artifacts])
            if step["activeArtifacts"] != active or step["requiredClosure"] != required:
                raise ValueError("complete per-invocation installed closure differs")
            engine.validate_closure(active, required, warehouse)
            source_origins.update(expected_sources(source, invocation, checkout))
            for name, origin in source_origins.items():
                observed = step["after"][name]
                if not direct_matches(observed["directUrl"], origin):
                    raise ValueError("installed source origin differs")
            if any(step["after"][name]["version"] != value["version"] for name, value in context["initialInstalled"].items()):
                raise ValueError("backend runtime changed during sequence")
            installed_source_and_artifact_bytes(engine, after=step["after"], active=active, warehouse=warehouse,
                                                origins=source_origins, source_build=proposal["sourceBuild"], destination=destination,
                                                context=context, public=public)
            previous = step["after"]
