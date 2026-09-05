"""Hash the wheel metadata's offline resolution for a clean installation."""

import hashlib
import sys
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZipFile

wheel_directory = Path(sys.argv[1])
requirements = []
for wheel in sorted(wheel_directory.glob("*.whl")):
    with ZipFile(wheel) as archive:
        metadata_files = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_files) != 1:
            raise ValueError(f"Expected one METADATA file in {wheel}")
        metadata = BytesParser().parsebytes(archive.read(metadata_files[0]))
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    requirements.append(
        f"{metadata['Name']}=={metadata['Version']} --hash=sha256:{digest}"
    )
if not requirements:
    raise ValueError("No resolved smoke-test wheels found")
Path(sys.argv[2]).write_text("\n".join(requirements) + "\n", encoding="utf-8")
