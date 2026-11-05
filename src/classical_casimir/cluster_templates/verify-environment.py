"""Read-only checks of the selected legacy runtime; records live on BIGWORK."""
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import sys

bundle = Path(os.environ["CASIMIR_BUNDLE"])
prefix = Path(os.environ["CASIMIR_ENV"])
cfg = json.loads((bundle / "bundle.json").read_text())
assert sys.version_info[:2] == (3, 12), "Python 3.12 required"
assert Path(sys.prefix).resolve() == prefix.resolve(), "unexpected interpreter prefix"
versions = {}
for name, expected in cfg["expected_versions"].items():
    try:
        versions[name] = metadata.version(name)
    except metadata.PackageNotFoundError as error:
        raise RuntimeError("Existing bempp environment is missing: " + name) from error
    assert versions[name] == expected, (name, expected, versions[name])
record = dict(release=cfg["release"], prefix=str(prefix.resolve()),
              python=sys.version, versions=versions)
target = bundle / "environment.json"
assert not target.is_symlink(), "environment marker is a symlink"
if "--record" in sys.argv:
    target.write_text(json.dumps(record, indent=2) + "\n")
elif "--inspect" not in sys.argv:
    assert json.loads(target.read_text()) == record, "existing environment changed"
print(json.dumps(record))
