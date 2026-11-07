"""Public-asset policy shared by the PyInstaller spec, the builder and the release scanner.

Standard library only; loaded BY FILE PATH (it is not part of the frozen product).
One definition so the three gates cannot drift apart:

  * res/pet/ ships NO files. The only pet folder the inherited engine carried is a
    third-party character with no documented permission, and MiniDraconia ships no
    mini-pet at all. Any path containing the inherited character's name is rejected too.
  * Draconia voice clips ship only when individually approved. APPROVED_AUDIO is the
    reviewed allow-list of audio files under res/role/**/voice/; adding a name here is a
    deliberate reviewer decision (it must match an `approved: true` manifest entry).

  * A self-hosted relay seed (`minidraconia_relay.json`) or a stored own-AI key file (`*.dpapi`)
    never ships in the public source or build: whoever runs a relay places the seed beside
    their own executable (docs/SELF-HOSTED-RELAY.md).
  * Neither does a voice pack (any `voice_pack/` folder, D2.1): an optional recorded voice for
    her stored lines is placed beside one's own executable, like the seed (docs/VOICE-PACK.md).
  * No input of another product built on this engine may leak in: any path naming one is
    rejected. Those names are private, so they are not in this tree: they are read from the
    git-ignored `.release-private-markers` file at the repository root (one literal per line,
    `#` comments), the same file the release scanner reads. Without it this rule is idle.

Listing a file as allowed is NOT a rights determination; it only records that the
per-clip listening approval exists.
"""
from pathlib import Path, PurePosixPath

APPROVED_AUDIO = frozenset({'res/role/Draconia/note/voice/head-01.wav'})
_APPROVED_CANONICAL = frozenset(path.casefold() for path in APPROVED_AUDIO)
AUDIO_SUFFIXES = frozenset({'.wav', '.mp3', '.ogg', '.oga', '.flac', '.m4a', '.aac', '.opus', '.wma', '.aif', '.aiff'})
# Name of the inherited third-party character, matched case-insensitively in any path part.
FORBIDDEN_NAME_PARTS = ('派蒙', 'paimon')
RELAY_SEED_NAME = 'minidraconia_relay.json'
KEY_FILE_SUFFIX = '.dpapi'
VOICE_PACK_DIR = 'voice_pack'
MARKERS_FILE = Path(__file__).resolve().parents[2] / '.release-private-markers'


def load_other_product_names(path=MARKERS_FILE):
    """Lower-cased private names from the markers file; () when it is absent."""
    try:
        text = Path(path).read_text(encoding='utf-8')
    except (FileNotFoundError, NotADirectoryError):
        return ()
    names = []
    for line in text.splitlines():
        line = line.strip().casefold()
        if line and not line.startswith('#') and line not in names:
            names.append(line)
    return tuple(names)


OTHER_PRODUCT_NAMES = load_other_product_names()


def _res_tail(parts):
    for index, part in enumerate(parts):
        if part == 'res':
            return parts[index:]
    return None


def violation(path):
    """Rule name when this relative path must never be in the public source or build, else None.

    Accepts '/'-separated names as found in a source tree, a ZIP member or a frozen _internal/.
    """
    text = str(path).replace('\\', '/')
    # Windows resolves these directory names case-insensitively, including in source ZIPs.
    parts = tuple(part.casefold() for part in PurePosixPath(text).parts)
    low = text.casefold()
    if any(word in low for word in FORBIDDEN_NAME_PARTS):
        return 'inherited-pet-asset'
    if any(name in low for name in OTHER_PRODUCT_NAMES):
        return 'other-product-input'
    if parts and (parts[-1] == RELAY_SEED_NAME or parts[-1].endswith(KEY_FILE_SUFFIX)):
        return 'relay-seed' if parts[-1] == RELAY_SEED_NAME else 'own-key-file'
    if VOICE_PACK_DIR in parts:
        return 'voice-pack'
    tail = _res_tail(parts)
    if tail is None or len(tail) < 3:
        return None
    if tail[1] == 'pet':
        return 'inherited-pet-asset'
    if tail[1] == 'role' and 'voice' in tail[2:-1] and PurePosixPath(tail[-1]).suffix.lower() in AUDIO_SUFFIXES:
        if '/'.join(tail) not in _APPROVED_CANONICAL:
            return 'unapproved-audio'
    return None
