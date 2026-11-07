"""Optional voice pack: a prerecorded WAV for lines of her stored pool (D2.1).

Owner rule: lines we already have are stored and repeated; only lines written by an AI spend
quota. Every pet event answers from `data/draconia_lines_en.json`; anyone can record an optional
voice pack that gives some of those lines a recorded voice (format: docs/VOICE-PACK.md). The
pack is never in the repository or in the public download: whoever records one places it
beside their own executable, like a self-hosted relay seed.

Where it is read from:
  - frozen build: `<folder of MiniDraconia.exe>/voice_pack/`
  - source run:   `full-engine/voice_pack/` (git-ignored)

    voice_pack/manifest.json
      {"voice_id": "...", "lines": [{"key", "text", "emotion", "file", "seconds", "sha256"}]}

A line is voiced only when the manifest lists its key and exact text, the file exists inside the
pack folder and its sha256 matches. Anything else (no pack, a broken manifest, a missing, altered
or unreadable file, a line added later) leaves the line unvoiced. Nothing here raises.
Standard library only.
"""
from __future__ import annotations

import hashlib
import json
import sys
import threading
from pathlib import Path, PurePosixPath
from typing import Dict, Optional, Tuple

PACK_DIR_NAME = 'voice_pack'
MANIFEST_NAME = 'manifest.json'


def default_pack_dir() -> Path:
    """`voice_pack/` beside the executable (frozen) or inside full-engine/ (source run)."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent / PACK_DIR_NAME
    from DyberPet.paths import resource_root
    return resource_root() / PACK_DIR_NAME


def _safe_file_name(name) -> bool:
    """A plain .wav file name inside the pack folder (the manifest is data, never a path)."""
    if not isinstance(name, str) or not name or name != name.strip():
        return False
    pure = PurePosixPath(name.replace('\\', '/'))
    return len(pure.parts) == 1 and name not in ('.', '..') and pure.suffix.lower() == '.wav'


def load_manifest(folder) -> Dict[Tuple[str, str], dict]:
    """{(key, text): entry} for every well-formed manifest entry; {} when it cannot be read."""
    try:
        data = json.loads((Path(folder) / MANIFEST_NAME).read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return {}
    lines = data.get('lines') if isinstance(data, dict) else None
    out = {}
    for entry in lines if isinstance(lines, list) else ():
        if not isinstance(entry, dict):
            continue
        key, text, name, sha = entry.get('key'), entry.get('text'), entry.get('file'), entry.get('sha256')
        if isinstance(key, str) and isinstance(text, str) and _safe_file_name(name) \
                and isinstance(sha, str) and len(sha) == 64:
            out[(key, text)] = dict(entry)
    return out


def file_sha256(path) -> Optional[str]:
    try:
        digest = hashlib.sha256()
        with open(path, 'rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return None


class VoicePack:
    """Looks up the WAV and emotion of a stored line. Thread-safe; never raises."""

    def __init__(self, folder=None):
        try:
            self.folder = Path(folder) if folder is not None else default_pack_dir()
        except Exception:
            self.folder = None
        try:
            self._entries = load_manifest(self.folder) if self.folder is not None else {}
        except Exception:
            self._entries = {}
        self._verified: Dict[str, Tuple[int, int, bool]] = {}
        self._lock = threading.Lock()

    @property
    def present(self) -> bool:
        """True when a readable manifest lists at least one line."""
        return bool(self._entries)

    def entry(self, key: str, text: str) -> Optional[dict]:
        return self._entries.get((key, text))

    def emotion(self, key: str, text: str) -> Optional[str]:
        entry = self.entry(key, text)
        value = entry.get('emotion') if entry else None
        return value if isinstance(value, str) else None

    def wav_for(self, key: str, text: str) -> Optional[str]:
        """Path of the line's WAV when the file exists and matches its manifest sha256, else None."""
        try:
            entry = self.entry(key, text)
            if entry is None or self.folder is None:
                return None
            path = self.folder / entry['file']
            stat = path.stat()
            if not path.is_file():
                return None
        except (OSError, ValueError, TypeError):
            return None
        stamp = (stat.st_size, stat.st_mtime_ns)
        with self._lock:
            known = self._verified.get(str(path))
        if known is not None and known[:2] == stamp:
            return str(path) if known[2] else None
        ok = file_sha256(path) == entry['sha256'].lower()
        with self._lock:
            self._verified[str(path)] = stamp + (ok,)
        return str(path) if ok else None
