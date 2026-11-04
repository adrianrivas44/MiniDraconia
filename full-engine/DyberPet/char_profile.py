"""Resolvedor de perfil por personaje (contrato MiniDraconia, parte B).

Hoy DyberPet.py/mia_chat.py/mia_voice.py/local_brain.py leen
data/mia_brain.json, data/mia_lines.json y data/mia_mood.json con ruta
fija. Esta mascota activa puede ser Mia, Kitty, ChrisKitty o una nueva
(Draconia): cada una busca primero su propio archivo
`data/<petname en minusculas>_<kind>.json`; si no existe (hoy: Kitty,
ChrisKitty, y Mia misma porque su "propio" archivo ES el generico), cae
al archivo compartido de Mia (comportamiento de siempre).

Funciones puras, sin Qt, para poder testear sin abrir la app.
"""
from __future__ import annotations

from pathlib import Path

KINDS = ("brain", "lines", "mood")


def _own_path(data_dir: Path, petname: str, kind: str) -> Path:
    return Path(data_dir) / f"{petname.lower()}_{kind}.json"


def has_own_profile(data_dir, petname: str) -> bool:
    """True si `petname` tiene su propio archivo *_brain.json, distinto
    del generico de Mia (Mia siempre devuelve False aqui: su "propio"
    archivo es, por nombre, el mismo que el generico, asi que no hay
    frase/idioma propios que mirar aparte -- contrato punto 8)."""
    if petname == "Mia":
        return False
    return _own_path(Path(data_dir), petname, "brain").is_file()


def profile_path(data_dir, petname: str, kind: str) -> Path:
    """Ruta para `kind` ('brain'|'lines'|'mood') de `petname`.

    - brain/lines: propio archivo si existe, si no el de Mia (comportamiento
      actual para Mia, Kitty y ChrisKitty).
    - mood: cada personaje con brain propio persiste su propio animo
      (Draconia -> data/draconia_mood.json) aunque el archivo aun no
      exista (se crea al guardar); sin brain propio, comparte
      data/mia_mood.json como hoy.
    """
    if kind not in KINDS:
        raise ValueError(f"kind invalido: {kind!r}")
    data_dir = Path(data_dir)
    own = _own_path(data_dir, petname, kind)
    if kind == "mood":
        return own if has_own_profile(data_dir, petname) else data_dir / "mia_mood.json"
    return own if own.is_file() else data_dir / f"mia_{kind}.json"


def brain_path(data_dir, petname: str) -> Path:
    return profile_path(data_dir, petname, "brain")


def lines_path(data_dir, petname: str) -> Path:
    return profile_path(data_dir, petname, "lines")


def mood_path(data_dir, petname: str) -> Path:
    return profile_path(data_dir, petname, "mood")
