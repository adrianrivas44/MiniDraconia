"""Resolvedor de perfil por personaje (contrato MiniDraconia, parte B).

DyberPet.py/companion_chat.py/companion_voice.py/local_brain.py leen el
brain, las frases y el animo del personaje activo por aqui. Cada mascota
(Draconia, Kitty, ChrisKitty o una nueva) busca primero su propio archivo
`data/<petname en minusculas>_<kind>.json`; si no existe (hoy: Kitty y
ChrisKitty), cae al archivo generico compartido `data/companion_<kind>.json`
(comportamiento de siempre). Una mascota cuyo "propio" archivo es, por
nombre, el generico no tiene perfil propio.

Funciones puras, sin Qt, para poder testear sin abrir la app.
"""
from __future__ import annotations

from pathlib import Path

KINDS = ("brain", "lines", "mood")
GENERIC_PROFILE_NAME = "companion"


def _own_path(data_dir: Path, petname: str, kind: str) -> Path:
    return Path(data_dir) / f"{petname.lower()}_{kind}.json"


def generic_path(data_dir, kind: str) -> Path:
    """Archivo generico compartido por las mascotas sin perfil propio."""
    return Path(data_dir) / f"{GENERIC_PROFILE_NAME}_{kind}.json"


def has_own_profile(data_dir, petname: str) -> bool:
    """True si `petname` tiene su propio archivo *_brain.json, distinto
    del generico (si su "propio" archivo es, por nombre, el generico, no
    hay frase/idioma propios que mirar aparte -- contrato punto 8)."""
    own = _own_path(Path(data_dir), petname, "brain")
    if own == generic_path(data_dir, "brain"):
        return False
    return own.is_file()


def profile_path(data_dir, petname: str, kind: str) -> Path:
    """Ruta para `kind` ('brain'|'lines'|'mood') de `petname`.

    - brain/lines: propio archivo si existe, si no el generico
      (comportamiento actual para Kitty y ChrisKitty).
    - mood: cada personaje con brain propio persiste su propio animo
      (Draconia -> data/draconia_mood.json) aunque el archivo aun no
      exista (se crea al guardar); sin brain propio, comparte el
      generico como hoy.
    """
    if kind not in KINDS:
        raise ValueError(f"kind invalido: {kind!r}")
    data_dir = Path(data_dir)
    own = _own_path(data_dir, petname, kind)
    if kind == "mood":
        return own if has_own_profile(data_dir, petname) else generic_path(data_dir, "mood")
    return own if own.is_file() else generic_path(data_dir, kind)


def brain_path(data_dir, petname: str) -> Path:
    return profile_path(data_dir, petname, "brain")


def lines_path(data_dir, petname: str) -> Path:
    return profile_path(data_dir, petname, "lines")


def mood_path(data_dir, petname: str) -> Path:
    return profile_path(data_dir, petname, "mood")
