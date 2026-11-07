"""Windows version resource of MiniDraconia.exe, built from the repository's VERSION file (D2.1).

Standard library only; loaded BY FILE PATH by the PyInstaller spec (it is not part of the frozen
product). `version_file_text()` returns PyInstaller's version-file format (the text
`pyi-grab_version` writes), which the spec writes into the build folder and passes as
`EXE(version=...)`.

The numeric FILEVERSION/PRODUCTVERSION are four integers: `1.0.0-rc.2` -> (1, 0, 0, 2), a final
`1.0.0` -> (1, 0, 0, 0). The string fields carry the exact VERSION text.
"""
import re
from pathlib import Path

PRODUCT_NAME = 'MiniDraconia'
FILE_DESCRIPTION = 'MiniDraconia desktop companion'
EXE_NAME = 'MiniDraconia.exe'
VERSION_FILE_NAME = 'MiniDraconia-version-info.txt'
_VERSION = re.compile(r'^(\d+)\.(\d+)\.(\d+)(?:-rc\.(\d+))?$')


def numeric_version(version: str) -> tuple:
    """(major, minor, patch, rc) for VERSION's `X.Y.Z` or `X.Y.Z-rc.N`; ValueError otherwise."""
    match = _VERSION.match(str(version).strip())
    if not match:
        raise ValueError('VERSION must be X.Y.Z or X.Y.Z-rc.N, got %r' % version)
    numbers = tuple(int(part) for part in match.groups(default='0'))
    if any(part > 65535 for part in numbers):
        raise ValueError('version parts must fit 16 bits: %r' % version)
    return numbers


def string_fields(version: str) -> dict:
    version = str(version).strip()
    return {
        'ProductName': PRODUCT_NAME,
        'FileDescription': FILE_DESCRIPTION,
        'FileVersion': version,
        'ProductVersion': version,
        'InternalName': PRODUCT_NAME,
        'OriginalFilename': EXE_NAME,
    }


def version_file_text(version: str) -> str:
    numbers = numeric_version(version)
    strings = ',\n'.join('          StringStruct(%r, %r)' % item for item in string_fields(version).items())
    return (
        "VSVersionInfo(\n"
        "  ffi=FixedFileInfo(\n"
        "    filevers=%r,\n"
        "    prodvers=%r,\n"
        "    mask=0x3f,\n"
        "    flags=0x0,\n"
        "    OS=0x40004,\n"
        "    fileType=0x1,\n"
        "    subtype=0x0,\n"
        "    date=(0, 0)\n"
        "  ),\n"
        "  kids=[\n"
        "    StringFileInfo([\n"
        "      StringTable(\n"
        "        '040904B0',\n"
        "        [\n%s\n"
        "        ])\n"
        "    ]),\n"
        "    VarFileInfo([VarStruct('Translation', [1033, 1200])])\n"
        "  ]\n"
        ")\n" % (numbers, numbers, strings))


def write_version_file(version: str, folder) -> Path:
    """Write the version file into `folder` (the build's work folder) and return its path."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / VERSION_FILE_NAME
    path.write_text(version_file_text(version), encoding='utf-8')
    return path
