"""Single source of the product version: the VERSION file (stdlib only).

Source checkout: <repo>/VERSION, one level above the engine tree.
Frozen build: the build bundles that same file at the resource root.
"""
import re
from pathlib import Path

_PATTERN = re.compile(r'^\d+\.\d+\.\d+(?:-[0-9A-Za-z]+(?:\.[0-9A-Za-z]+)*)?$')


def read_version(resource_root=None):
    root = Path(resource_root) if resource_root is not None else Path(__file__).resolve().parents[1]
    for candidate in (root / 'VERSION', root.parent / 'VERSION'):
        if candidate.is_file():
            value = candidate.read_text(encoding='utf-8').strip()
            if not _PATTERN.match(value):
                raise RuntimeError('Malformed VERSION file: ' + str(candidate))
            return value
    raise RuntimeError('VERSION file not found next to ' + str(root))
