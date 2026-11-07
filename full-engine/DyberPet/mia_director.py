"""Director de conducta de Mia para DyberPet.

Toda la logica nueva de comportamiento (saludo/despedida, eleccion de accion
ociosa, zonas de toque, reglas de borde, mirar al cursor, hablar, parpadeo,
pantalla primaria) vive aqui. Se separa en:

- Funciones puras (sin Qt) -> testeables con `pytest` sin abrir la app.
- `MiaDirector`, un QObject fino que usa un QTimer para disparar `tick()` y
  llama a las funciones puras; cablea con PetWidget mediante pocos ganchos
  en DyberPet.py (ver docs/contrato-motor.md).

Este archivo es codigo nuestro sobre DyberPet (GPL-3.0). No toca el nucleo
upstream salvo los ganchos de pocas lineas documentados en DyberPet.py.
"""
from __future__ import annotations

import json
import math
import random
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional, Sequence

try:
    from PySide6.QtCore import QObject, QTimer
except Exception:  # pragma: no cover - entorno sin Qt (no debe pasar en runtime real)
    QObject = object  # type: ignore
    QTimer = None  # type: ignore


# ---------------------------------------------------------------------------
# 1. Pantalla primaria
# ---------------------------------------------------------------------------

def pick_primary_screen(screens: Sequence[object], primary: object) -> object:
    """Devuelve la pantalla que debe usarse como `current_screen` al arrancar.

    `screens` es la lista completa de pantallas (QScreen u objetos con
    `.geometry()`); `primary` es `QGuiApplication.primaryScreen()`. Si
    `primary` esta en la lista, se devuelve esa instancia (no una copia),
    para que `is`/`==` corriente aguas abajo siga funcionando. Si no esta
    (nunca deberia pasar), cae al primero de la lista.
    """
    for screen in screens:
        if screen is primary:
            return screen
    if primary is not None:
        return primary
    return screens[0]


def primary_screen_start_pos(screen_rect, pet_width: int, pet_height: int,
                              width_frac: float = 0.3) -> tuple[int, int]:
    """Posicion inicial (arriba-izquierda del widget) dentro de `screen_rect`.

    `screen_rect` necesita `.x()`, `.y()`, `.width()`, `.height()` (como
    QRect). El pet queda apoyado en el suelo (parte inferior del rect) y
    centrado en `width_frac` del ancho de esa pantalla.
    """
    x = screen_rect.x() + int(screen_rect.width() * width_frac) - pet_width // 2
    y = screen_rect.y() + screen_rect.height() - pet_height
    return x, y


# ---------------------------------------------------------------------------
# 10b. Multimonitor (User: "solo se queda en una pantalla a pesar de que tengo dos")
# Rectángulos (x, y, w, h) como QRect; quien llama convierte con _rect().
# ---------------------------------------------------------------------------

def _rect(r):
    """Acepta QRect, QScreen (usa geometry()) o tupla (x, y, w, h)."""
    if isinstance(r, tuple):
        return r
    if hasattr(r, "geometry") and not hasattr(r, "x"):
        r = r.geometry()
    return (r.x(), r.y(), r.width(), r.height())


def _v_overlap(a, b) -> bool:
    return a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def _side_neighbor(screens, current, side):
    """Pantalla más cercana a ese lado de `current` que comparte altura; admite
    hueco entre pantallas (Qt con DPI 125 %: D1 lógico acaba en 2752 y D2 empieza en 3440)."""
    cur = _rect(current)
    cx, cy, cw, ch = cur
    best, best_d = None, None
    for scr in screens:
        r = _rect(scr)
        if r == cur or not _v_overlap(r, cur):
            continue
        if side == "right" and r[0] >= cx + cw - 2:
            d = r[0] - (cx + cw)
        elif side == "left" and r[0] + r[2] <= cx + 2:
            d = cx - (r[0] + r[2])
        else:
            continue
        if best_d is None or d < best_d:
            best, best_d = scr, d
    return best


def neighbor_screen(screens, current, center_x: float, foot_y: float):
    """Si el centro del pet salió de `current` por un lado y hay pantalla a ese
    lado (con o sin hueco), devuelve esa pantalla (el objeto de `screens`).
    Si no, None (se queda y choca con el borde)."""
    cx, cy, cw, ch = _rect(current)
    if center_x >= cx + cw:
        return _side_neighbor(screens, current, "right")
    if center_x < cx:
        return _side_neighbor(screens, current, "left")
    return None


def entry_center_x(from_rect, to_rect) -> int:
    """Centro x con el que entra en `to_rect` viniendo de `from_rect` (salta el hueco)."""
    f, t = _rect(from_rect), _rect(to_rect)
    if t[0] >= f[0] + f[2] - 2:
        return t[0] + 1
    return t[0] + t[2] - 1


def outer_edge(screens, current, pos_x: float, width: int):
    """Borde 'left'/'right' solo si es borde de fuera del escritorio: la costura
    con otra pantalla no cuenta (antes giraba o se asomaba justo ahí)."""
    cx, cy, cw, ch = _rect(current)
    if pos_x <= cx and _side_neighbor(screens, current, "left") is None:
        return "left"
    if pos_x + width >= cx + cw and _side_neighbor(screens, current, "right") is None:
        return "right"
    return None


def start_screen_and_frac(rng, screens, primary):
    """Dónde nace: cualquier pantalla (la principal el doble de probable) y en
    cualquier punto entre 15 % y 85 % del ancho, no siempre a la izquierda."""
    pool = list(screens) or [primary]
    weights = [2 if _rect(s) == _rect(primary) else 1 for s in pool]
    scr = rng.choices(pool, weights=weights, k=1)[0]
    return scr, rng.uniform(0.15, 0.85)


# ---------------------------------------------------------------------------
# 11. Poses: fallback cuando falta el arte
# ---------------------------------------------------------------------------

def resolve_pose(requested: str, available: Iterable[str], fallback_chain=("happy", "default")) -> str:
    """Devuelve `requested` si existe en `available`; si no, la primera pose
    de `fallback_chain` que exista; si ninguna existe, `"default"` igual
    (el llamador ya garantiza que default siempre esta generado).
    """
    available = set(available)
    if requested in available:
        return requested
    for fb in fallback_chain:
        if fb in available:
            return fb
    return "default"


# ---------------------------------------------------------------------------
# 4. Eleccion ponderada de comportamiento ocioso
# ---------------------------------------------------------------------------

IDLE_POSES = ("yawn", "sit", "read", "stretch", "think")

DEFAULT_WEIGHTS = {
    "idle": 0.55,
    "walk": 0.25,
    "follow_cursor": 0.10,
    "sleep": 0.05,
}

# M3.2: an idle pose never repeats any of the last IDLE_NO_REPEAT idle poses.
IDLE_NO_REPEAT = 3


def choose_behavior(weights: dict, rng: random.Random) -> str:
    """Elige una accion entre las claves de `weights` con pesos proporcionales.

    Determinista si `rng` viene con `random.seed` fijo. Si `weights` esta
    vacio devuelve "idle".
    """
    if not weights:
        return "idle"
    names = list(weights.keys())
    values = [max(0.0, float(weights[n])) for n in names]
    total = sum(values)
    if total <= 0:
        return names[0]
    pick = rng.uniform(0, total)
    acc = 0.0
    for name, value in zip(names, values):
        acc += value
        if pick <= acc:
            return name
    return names[-1]


def choose_idle_pose(rng: random.Random, available_idle_poses: Sequence[str] = IDLE_POSES) -> str:
    poses = list(available_idle_poses) or list(IDLE_POSES)
    return rng.choice(poses)


# Mia: pool extendido de poses "sueltas" que el tick idle puede elegir
# cuando hay animo/mesa mood disponibles (contrato mia-mood punto 4,
# bloqueante B2: mia_brain.json["mood"] trae entradas para stretch, yawn,
# climb, read, happy, greet, angry, shy, bored y peek que antes nunca se
# aplicaban). pinch/touch_body se excluyen a propósito: necesitan un
# toque real de User (TouchMoodReactor), no tienen sentido como idle
# espontaneo.
IDLE_MOOD_POSES = IDLE_POSES + ("happy", "greet", "climb", "bored", "angry", "shy", "peek")


def choose_weighted_pose(rng: random.Random, candidates: Sequence[str],
                          dominant: Optional[str], mood_table: Optional[dict]) -> str:
    """Elige una pose entre `candidates` ponderada por `mood_table` segun
    `dominant` (bloqueante B2). Sin tabla o sin dominante conocido, cae a
    una eleccion uniforme (compat exacto con choose_idle_pose de siempre).
    """
    pool = list(candidates) or list(IDLE_POSES)
    if not dominant or not mood_table:
        return rng.choice(pool)
    weights = mood_weighted_choice({c: 1.0 for c in pool}, dominant, mood_table)
    if sum(weights.values()) <= 0:
        return rng.choice(pool)
    return choose_behavior(weights, rng)


# perfil: pool de idle propio del personaje activo (data/<x>_brain.json
# ["own_idle_poses"], p. ej. spell/tea/hairflip/slowclap/read/
# think/stretch/sit). Vacio (default) == comportamiento de siempre.
def load_own_idle_poses(brain_path) -> dict:
    """Lee `own_idle_poses` (pose -> peso) de un *_brain.json. Si falta el
    archivo, no es JSON valido o no trae la clave, devuelve {} (sin pool
    propio, el director usa solo IDLE_POSES/IDLE_MOOD_POSES de siempre)."""
    brain_path = Path(brain_path)
    if not brain_path.is_file():
        return {}
    try:
        data = json.loads(brain_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    table = data.get("own_idle_poses") if isinstance(data, dict) else None
    return dict(table) if isinstance(table, dict) else {}


def _extend_pool(base: Sequence[str], available: Iterable[str], own_idle_poses: dict) -> list:
    available = set(available)
    pool = [p for p in base if p in available]
    pool += [p for p in own_idle_poses if p in available and p not in pool]
    return pool


# ---------------------------------------------------------------------------
# t_108e7d40 punto 3: secuencias de caracter (combos cortos, probabilidad
# configurable), genericas por perfil via data/<x>_brain.json["combos"]:
# {"spell": {"hairflip": 0.4}, "tea": {"read": 0.3}, ...}. Sin tabla o sin
# entrada para `pose`, no hay combo (comportamiento de siempre).
# ---------------------------------------------------------------------------

def load_combos(brain_path) -> dict:
    """Lee `combos` (pose -> {pose_siguiente: probabilidad}) de un
    *_brain.json. Igual contrato de tolerancia que load_own_idle_poses:
    sin archivo/JSON invalido/clave ausente devuelve {}."""
    brain_path = Path(brain_path)
    if not brain_path.is_file():
        return {}
    try:
        data = json.loads(brain_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    table = data.get("combos") if isinstance(data, dict) else None
    if not isinstance(table, dict):
        return {}
    return {k: dict(v) for k, v in table.items() if isinstance(v, dict)}


def choose_combo_followup(rng: random.Random, pose: str, combos: dict) -> Optional[str]:
    """Un sorteo para seguimientos mutuamente excluyentes de `pose`.

    Cada valor es una probabilidad marginal (la suma debe ser <= 1);
    la masa restante significa no encadenar. Sin entrada no consume RNG,
    preservando exactamente los perfiles que no definen combos.
    """
    table = combos.get(pose) if combos else None
    if not table:
        return None
    pick = rng.random()
    cumulative = 0.0
    for name, prob in table.items():
        cumulative += max(0.0, min(1.0, float(prob)))
        if pick < cumulative:
            return name
    return None


def choose_profile_idle_pose(rng: random.Random, available: Iterable[str],
                              dominant: Optional[str], mood_table: Optional[dict],
                              own_idle_poses: Optional[dict] = None) -> str:
    """Elige pose idle incluyendo el pool propio del perfil (own_idle_poses,
    ponderado por sus pesos y, si hay animo, tambien por mood_table). Con
    `own_idle_poses` vacio (Mia/Kitty/ChrisKitty hoy) el resultado es
    exactamente el de `choose_weighted_pose`/`choose_idle_pose` de siempre.
    """
    own_idle_poses = own_idle_poses or {}
    if mood_table and dominant:
        pool = _extend_pool(IDLE_MOOD_POSES, available, own_idle_poses) or list(IDLE_MOOD_POSES)
        base_weights = {p: float(own_idle_poses.get(p, 1.0)) for p in pool}
        weights = mood_weighted_choice(base_weights, dominant, mood_table)
        if sum(weights.values()) > 0:
            return choose_behavior(weights, rng)
        return rng.choice(pool)
    pool = _extend_pool(IDLE_POSES, available, own_idle_poses) or list(IDLE_POSES)
    if own_idle_poses and any(p in own_idle_poses for p in pool):
        weights = {p: float(own_idle_poses.get(p, 1.0)) for p in pool}
        return choose_behavior(weights, rng)
    return choose_idle_pose(rng, pool)


# ---------------------------------------------------------------------------
# M3.2: idle pool built into the role (res/role/<pet>/pet_conf.json["idle_poses"]),
# so it does not depend on a profile file the user never had.
# ---------------------------------------------------------------------------

def load_role_idle_poses(pet_conf_path) -> dict:
    """`idle_poses` (pose -> weight) of a role's pet_conf.json; {} when absent or invalid."""
    try:
        data = json.loads(Path(pet_conf_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    table = data.get("idle_poses") if isinstance(data, dict) else None
    if not isinstance(table, dict):
        return {}
    out = {}
    for pose, weight in table.items():
        try:
            weight = float(weight)
        except (TypeError, ValueError):
            continue
        if weight > 0:
            out[str(pose)] = weight
    return out


def choose_fresh_idle_pose(rng: random.Random, pool: dict, recent: Sequence[str] = (),
                           available: Optional[Iterable[str]] = None,
                           dominant: Optional[str] = None,
                           mood_table: Optional[dict] = None) -> Optional[str]:
    """A weighted pick from `pool` (pose -> weight) that is none of the `recent` poses.

    Only poses the role really has (`available`) are candidates, so a missing clip never
    falls back to standing. The mood multiplies the weights (never to zero: every pose keeps a
    small chance). None when the pool has no playable pose."""
    poses = [p for p in pool if available is None or p in set(available)]
    if not poses:
        return None
    fresh = [p for p in poses if p not in set(recent)] or poses
    weights = {p: float(pool[p]) for p in fresh}
    if mood_table and dominant:
        moody = mood_weighted_choice(weights, dominant, mood_table)
        weights = {p: max(moody.get(p, 0.0), 0.1 * weights[p]) for p in fresh}
    return choose_behavior(weights, rng)


BEHAVIORS = ("idle", "walk", "follow_cursor", "sleep")


def fold_pose_weights(weights: dict) -> dict:
    """With a role idle pool every idle clip goes through `pick_idle_pose` (no repeat of the last
    IDLE_NO_REPEAT): weights an older profile gives to single poses (spell, tea...) are added to
    `idle` instead of being chosen directly."""
    out = {k: float(v) for k, v in weights.items() if k in BEHAVIORS}
    extra = sum(float(v) for k, v in weights.items() if k not in BEHAVIORS and float(v) > 0)
    if extra:
        out["idle"] = out.get("idle", 0.0) + extra
    return out


def walk_room(x: int, width: int, screen_left: int, screen_width: int) -> dict:
    """D2.3: logical px she can walk toward each side of her screen before her window's side
    reaches that edge (where the micro ticker's edge reaction, turn/peek/climb, takes over)."""
    left = int(x) - int(screen_left)
    right = int(screen_left) + int(screen_width) - (int(x) + int(width))
    return {"left": max(0, left), "right": max(0, right)}


def walk_distance(acts, scale: float) -> float:
    """D2.3: logical px one full walk travels: frames x frame_move (sprite px) x display scale,
    summed over the walking acts of `acts` (an act list may end with her stand)."""
    total = 0.0
    for act in acts or ():
        if getattr(act, "need_move", False) and getattr(act, "direction", None) in ("left", "right"):
            frames = len(getattr(act, "images", None) or ()) * int(getattr(act, "act_num", 1) or 1)
            total += frames * abs(float(getattr(act, "frame_move", 0) or 0)) * float(scale)
    return total


# D2.3: when no side has room for a whole walk (her 515 px window at 100 % leaves 509 px of a
# 1024 px screen, less than two 330 px walks), she still walks toward the roomier side if it holds
# at least this fraction of a walk; below that (a tiny screen) she does not walk.
MIN_WALK_FRACTION = 0.5


def walkable_sides(room: dict, need: dict) -> tuple:
    """Sides a random walk may take: those with room for one full walk; if there is none, the
    roomier side when it holds MIN_WALK_FRACTION of a walk; else none."""
    room = {side: float(room.get(side, 0) or 0) for side in ("left", "right")}
    need = {side: float(need.get(side, 0) or 0) for side in ("left", "right")}
    full = tuple(side for side in ("left", "right") if room[side] >= need[side] - 1e-6)
    if full:
        return full
    best = max(("left", "right"), key=lambda side: room[side])
    return (best,) if room[best] >= MIN_WALK_FRACTION * need[best] - 1e-6 else ()


def choose_walk_direction(rng: random.Random, room: Optional[dict] = None,
                          need: Optional[dict] = None) -> Optional[str]:
    """Direction of a random walk. D2.3: with her `room` toward each side and the `need` of one
    full walk each way, a side with less room than a walk is not chosen while the other has room;
    both sides with room keep the coin flip; with no room on either side, the roomier side if it
    holds MIN_WALK_FRACTION of a walk, else None (she does not walk). Without geometry: the coin
    flip of before."""
    if room is None or need is None:
        return rng.choice(("left", "right"))
    sides = walkable_sides(room, need)
    if len(sides) == 2:
        return rng.choice(sides)
    return sides[0] if sides else None


def choose_walk_duration(rng: random.Random, lo: float = 2.0, hi: float = 6.0) -> float:
    return rng.uniform(lo, hi)


def choose_follow_duration(rng: random.Random, lo: float = 5.0, hi: float = 10.0) -> float:
    return rng.uniform(lo, hi)


def choose_next_tick_delay(rng: random.Random, lo: float = 8.0, hi: float = 20.0) -> float:
    return rng.uniform(lo, hi)


def should_sleep(idle_seconds: float, sleep_after_s: float = 300.0) -> bool:
    return idle_seconds >= sleep_after_s


# ---------------------------------------------------------------------------
# M3: behavior_weights y sleep_after_s desde data/mia_brain.json
# ---------------------------------------------------------------------------

def load_director_config(brain_path) -> dict:
    """Lee `behavior_weights` y `sleep_after_s` de mia_brain.json.

    Si el archivo no existe, no es JSON valido, o no trae esas claves, cae a
    DEFAULT_WEIGHTS / 300.0 (contrato-motor.md punto 4).
    """
    cfg = {"weights": dict(DEFAULT_WEIGHTS), "sleep_after_s": 300.0}
    brain_path = Path(brain_path)
    if not brain_path.is_file():
        return cfg
    try:
        data = json.loads(brain_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return cfg
    if not isinstance(data, dict):
        return cfg
    weights = data.get("behavior_weights")
    if isinstance(weights, dict) and weights:
        cfg["weights"] = dict(weights)
    sleep_after_s = data.get("sleep_after_s")
    if isinstance(sleep_after_s, (int, float)):
        cfg["sleep_after_s"] = sleep_after_s
    chatter = data.get("chatter")
    if isinstance(chatter, dict):
        cfg["chatter"] = dict(chatter)
    cfg["climb"] = load_climb_config(data)
    return cfg


# ---------------------------------------------------------------------------
# 5. Mirar al cursor
# ---------------------------------------------------------------------------

def should_mirror_frame(cursor_flip: bool, anim_act, current_act) -> bool:
    """Espejar el cuadro hacia el cursor SOLO si lo que se pinta no tiene dirección propia.
    Mira primero el acto de Animation_worker (caminatas aleatorias, C1 revisión 2) y luego el de la interacción."""
    if not cursor_flip:
        return False
    act = anim_act if anim_act is not None else current_act
    if act is None:
        return True
    return not (getattr(act, "need_move", False) or getattr(act, "direction", None))


def pose_allowed(pose: str, interact, onfloor: int, dragging: int) -> bool:
    """Puerta única para las poses del director.

    User vio a Mia "flotando": una pose (kick/blink/idle) reemplazaba la
    interacción 'mousedrag' del motor y la caída nunca terminaba. En el aire,
    arrastrando o mientras corre mousedrag, el motor original manda.
    """
    if dragging or not onfloor:
        return False
    if interact == "mousedrag":
        return False
    return True


def should_flip_to_cursor(pet_center_x: int, cursor_x: int, state: str,
                           threshold_px: int = 300) -> Optional[bool]:
    """Devuelve True/False (si hay que voltear hacia el cursor) o None si no
    aplica (p. ej. mientras camina, que ya trae su propia direccion).
    """
    if state != "default":
        return None
    if abs(cursor_x - pet_center_x) >= threshold_px:
        return None
    return cursor_x < pet_center_x  # True -> cursor a la izquierda -> flip


# ---------------------------------------------------------------------------
# 6. Zonas de toque
# ---------------------------------------------------------------------------

def detect_touch_zone(rect_width: int, rect_height: int, click_x: int, click_y: int) -> str:
    """rect_* son el tamano del sprite visible; click_* son relativos a la
    esquina superior-izquierda de ese rect. Devuelve "head", "cheek" o
    "body".
    """
    if rect_height <= 0 or rect_width <= 0:
        return "body"
    y_frac = click_y / rect_height
    x_frac = click_x / rect_width

    if y_frac <= 0.30:
        return "head"
    if 0.30 < y_frac <= 0.42 and 0.35 <= x_frac <= 0.65:
        return "cheek"
    return "body"


TOUCH_ZONE_ACTIONS = {
    "head": {"anim": "patpat", "prompt": "User just gave you a gentle pat on the head. Say one short, warm line directly to him."},
    "cheek": {"anim": "pinch", "prompt": "User just pinched your cheek playfully. Say one short, teasing line directly to him."},
    "body": {"anim": "touch_body", "prompt": "User just poked your shoulder to get your attention. Say one short line directly to him."},
}


# ---------------------------------------------------------------------------
# 8. Bordes: girar o asomarse
# ---------------------------------------------------------------------------

def decide_edge_action(rng: random.Random, climb_cfg: Optional[dict] = None) -> str:
    """50/50 entre "turn" (darse la vuelta) y "peek" (asomarse).

    Mia: si `climb_cfg` trae `enabled=True`, "climb" entra primero con
    `climb_cfg["prob"]` de probabilidad (default 0.35, comportamiento 1 del
    contrato trepar-paredes); si no sale climb (o esta deshabilitado), se
    cae al 50/50 turn/peek de siempre. Sin climb_cfg el comportamiento es
    idéntico al de antes (compat con llamadas existentes).
    """
    if climb_cfg and climb_cfg.get("enabled") and rng.uniform(0, 1) < float(climb_cfg.get("prob", 0.0)):
        return "climb"
    return "turn" if rng.uniform(0, 1) < 0.5 else "peek"


def peek_duration(rng: random.Random, lo: float = 4.0, hi: float = 8.0) -> float:
    return rng.uniform(lo, hi)


def opposite_walk_pose(side: str) -> str:
    """Al tocar el borde 'left'/'right' y decidir 'turn', Mia camina hacia
    el lado contrario (C4 informe revisor 2)."""
    return "right_walk" if side == "left" else "left_walk"


def peek_pose_for_side(side: str, available_poses: Iterable[str]) -> tuple[str, bool]:
    """Pose a pedir para asomarse por `side` y si hay que espejarla a mano.

    build_mia_role.py puede terminar registrando 'peek_left'/'peek_right'
    como clips dedicados (igual que left_walk/right_walk, nota de Mia
    2026-10-12: "peek_right/peek_left pasan a ser clips"); si ya existen en
    el role se piden tal cual, sin espejo manual. Si el role actual solo
    trae el acto generico 'peek' (hoy: arte base de peek_right), se espeja
    a mano para el lado izquierdo.
    """
    dedicated = "peek_%s" % side
    if dedicated in available_poses:
        return dedicated, False
    return "peek", side == "left"


# ---------------------------------------------------------------------------
# 9. Hablar: duracion de "boca que se mueve"
# ---------------------------------------------------------------------------

def talk_duration(text: str, bubble_duration_s: Optional[float] = None,
                   per_char_s: float = 0.06, max_s: float = 4.0) -> float:
    candidates = [len(text or "") * per_char_s, max_s]
    if bubble_duration_s is not None:
        candidates.append(bubble_duration_s)
    return max(0.0, min(candidates))


# ---------------------------------------------------------------------------
# 10. Parpadeo
# ---------------------------------------------------------------------------

def choose_blink_delay(rng: random.Random, lo: float = 3.0, hi: float = 7.0) -> float:
    return rng.uniform(lo, hi)


BLINK_DURATION_S = 0.15

TALK_ALTERNATE_PERIOD_S = 0.18
KICK_ALTERNATE_PERIOD_S = 0.25

# D2.2: falling asleep (a random nap or away sleep) is yawn -> doze -> sleep; the yawn plays once,
# complete. A stage the role has no clip for is skipped.
YAWN_POSE = "yawn"


def first_sleep_stage(available: Iterable[str], dragging: bool = False, on_floor: bool = True) -> str:
    """The clip she plays when she falls asleep: 'yawn' if the role has it and she is on the
    floor and not dragged; else 'doze' if the role has it; else 'sleep'."""
    available = set(available or ())
    if YAWN_POSE in available and not dragging and on_floor:
        return YAWN_POSE
    return "doze" if "doze" in available else "sleep"


def next_sleep_stage(stage: Optional[str], available: Iterable[str]) -> str:
    """The clip after `stage` once it is over: yawn -> doze (if the role has it) -> sleep -> sleep."""
    available = set(available or ())
    if stage == YAWN_POSE and "doze" in available:
        return "doze"
    return "sleep"


class MiaMicroTicker:
    """Microcomportamientos que se revisan en cada tick corto (parpadeo,
    mirar al cursor, patalear mientras la arrastran, bordes, hablar).

    Independiente del QTimer de 8-20s de MiaDirector: este ticker esta
    pensado para dispararse cada ~0.1-0.2s desde un QTimer propio en
    DyberPet.py. `now_fn` se inyecta para poder testear con un reloj falso
    (contrato-motor.md: "mocks del reloj").
    """

    def __init__(self, get_context: Callable[[], dict],
                 play_action: Callable[[str], None],
                 apply_cursor_flip: Callable[[bool], None],
                 on_edge: Callable[[str], None],
                 now_fn: Callable[[], float] = time.time,
                 rng: Optional[random.Random] = None,
                 climb_cfg: Optional[dict] = None,
                 set_pos_y: Optional[Callable[[float], None]] = None,
                 on_climb_log: Optional[Callable[[str], None]] = None,
                 allow_fall: Optional[Callable[[], bool]] = None,
                 start_fall: Optional[Callable[[], None]] = None,
                 on_climb_top: Optional[Callable[[], None]] = None,
                 get_climb_speed: Optional[Callable[[], float]] = None,
                 on_climb_start: Optional[Callable[[str], None]] = None,
                 hold_pose: Optional[Callable[[], None]] = None,
                 handle_talk: bool = True,
                 is_talking: Optional[Callable[[], bool]] = None):
        self._get_context = get_context
        self._play_action = play_action
        self._apply_cursor_flip = apply_cursor_flip
        self._on_edge = on_edge
        self._now_fn = now_fn
        self.rng = rng or random.Random()
        # Mia: trepar paredes (comportamiento climb, contrato trepar-paredes).
        self._climb_cfg = dict(climb_cfg) if climb_cfg else dict(DEFAULT_CLIMB_CFG)
        self._set_pos_y = set_pos_y
        self._on_climb_log = on_climb_log
        self._climb: Optional[ClimbSession] = None
        # Mia: al soltarse cae de verdad (gravedad del motor) solo si "Allow Drop"
        # está encendido; si User lo apagó, baja trepando.
        self._allow_fall = allow_fall or (lambda: True)
        self._start_fall = start_fall
        # Mia: animo (contrato mia-mood punto 2) -- +joy al llegar arriba.
        self._on_climb_top = on_climb_top
        # M3: speed matched to the sprite (holds do not slide), wall snap, freeze while hanging.
        self._get_climb_speed = get_climb_speed
        self._on_climb_start = on_climb_start
        self._hold_pose = hold_pose
        # M3: talking is driven by talk_controller.TalkController; the one-shot talk here is off.
        self._handle_talk = handle_talk
        # M3.1: while she says a line (talk_controller.TalkController.active) neither a blink nor a wall
        # decision (turn/peek/climb, end of a peek) may replace her talk clip.
        self._is_talking = is_talking
        self._edge_retry_at: Optional[float] = None

        self._next_blink_at: Optional[float] = None
        self._last_drag_pose: Optional[str] = None
        self._next_drag_toggle_at: Optional[float] = None
        self._last_edge_seen: Optional[str] = None
        self._next_talk_toggle_at: Optional[float] = None
        self._talking_default_shown = True
        self._sleep_stage: Optional[str] = None
        self._peek_until: Optional[float] = None

    @property
    def is_climbing(self) -> bool:
        """Expuesto para que MiaDirector (is_busy) e is_busy de DyberPet.py
        sepan que Mia esta trepando: ni duerme ni cambia de pose mientras
        tanto (comportamiento 5 del contrato trepar-paredes)."""
        return self._climb is not None and self._climb.active

    @property
    def is_talking(self) -> bool:
        if self._is_talking is None:
            return False
        try:
            return bool(self._is_talking())
        except Exception:
            return False

    def tick(self) -> None:
        ctx = self._get_context()
        now = self._now_fn()

        if ctx.get("dragging"):
            # Mia: arrastrar cancela la trepada al instante (comportamiento 5:
            # "el arrastre manda, como hoy").
            if self._climb is not None:
                self._cancel_climb()
            self._tick_drag(now)
        else:
            self._last_drag_pose = None
            self._next_drag_toggle_at = None

        climbing = self._tick_climb(ctx, now)

        if ctx.get("sleeping") and not climbing:
            # Mia: dormida de verdad (C2 informe revisor 2). Mientras
            # sleeping=True: sin mirar al cursor, sin parpadeo, sin hablar;
            # solo 'doze'/'sleep' (MiaDirector.is_asleep ya hace que
            # may_chatter() calle). Despierta solo con note_interaction().
            self._apply_cursor_flip(False)
            self._next_blink_at = None
            self._next_talk_toggle_at = None
            self._talking_default_shown = True
            self._peek_until = None
            self._tick_sleep(ctx)
            return
        self._sleep_stage = None

        talking = self.is_talking
        if not climbing and not talking:
            self._tick_edge(ctx, now)

        if self._peek_until is None and not climbing:
            self._tick_cursor_flip(ctx)

        if talking:
            self._next_blink_at = None   # M3.1: a blink would cut the talk clip mid-line
        elif not climbing:
            self._tick_blink(ctx, now)   # M3: no other clip may replace the climb
        if self._handle_talk:
            self._tick_talk(ctx, now)

    def _log(self, msg: str) -> None:
        if self._on_climb_log:
            self._on_climb_log(msg)

    def _cancel_climb(self) -> None:
        self._climb = None
        self._apply_cursor_flip(False)

    def _start_climb(self, side: str, ctx: dict, now: float) -> None:
        available = ctx.get("available_poses") or set()
        pose, mirror = climb_pose_for_side(side, available)
        self._apply_cursor_flip(bool(mirror))
        if self._on_climb_start is not None:
            self._on_climb_start(side)
        self._play_action(pose)
        self._climb_pose = pose
        self._peek_until = None
        speed = None
        if self._get_climb_speed is not None:
            try:
                speed = float(self._get_climb_speed())
            except Exception:
                speed = None
        if not speed or speed <= 0:
            speed = float(self._climb_cfg.get("speed", DEFAULT_CLIMB_CFG["speed"]))
        self._climb = ClimbSession.start(
            side=side,
            start_y=ctx.get("pos_y", 0.0),
            floor_y=ctx.get("floor_y", ctx.get("pos_y", 0.0)),
            screen_top=ctx.get("screen_top", 0.0),
            screen_height=ctx.get("screen_height", 0.0),
            speed=speed,
            rng=self.rng,
            now=now,
        )
        self._log("trepa %s" % side)

    def _tick_climb(self, ctx: dict, now: float) -> bool:
        """Avanza una trepada en curso. Devuelve True mientras siga trepando
        (para que tick() no la interrumpa con borde/espejo al cursor)."""
        if self._climb is None:
            return False
        hold_s = tuple(self._climb_cfg.get("hold_s", DEFAULT_CLIMB_CFG["hold_s"]))
        phase_before = self._climb.phase
        event = self._climb.advance(now, self.rng, hold_s)
        if self._set_pos_y is not None:
            self._set_pos_y(self._climb.y)
        if phase_before == "up" and self._climb is not None and self._climb.phase == "hold":
            # Mia: animo (contrato mia-mood punto 2) -- llego arriba.
            if self._on_climb_top is not None:
                self._on_climb_top()
            # M3: hanging still -> freeze on the current frame (a running clip would slide).
            if self._hold_pose is not None:
                self._hold_pose()
        if event in ("ceiling", "released_fall"):
            if not self._allow_fall():
                self._climb.phase = "down"
                self._log("baja")
                # M3.3: the climb clip loops in the engine; going down plays climb_down.
                self._play_climb_clip(ctx, down=True)
                return True
            self._cancel_climb()
            self._log("suelta")
            self._play_action("fall")
            if self._start_fall is not None:
                self._start_fall()
            return False
        if event == "walk_down_start":
            self._log("baja")
            self._play_climb_clip(ctx, down=True)
            return True
        if event == "reached_floor":
            self._cancel_climb()
            self._play_action("default")
            return False
        # M3: keep the climb clip running while she moves on the wall (the clip is 73 frames;
        # a climb lasts longer). M3.3: the pet plays climb clips as engine loops, so this is
        # only a fallback for a clip that was stopped from outside.
        if self._climb is not None and self._climb.phase in ("up", "down") \
                and ctx.get("state", "default") == "default":
            self._play_climb_clip(ctx, down=self._climb.phase == "down")
        return True

    def _play_climb_clip(self, ctx: dict, down: bool) -> None:
        available = ctx.get("available_poses") or set()
        pose = getattr(self, "_climb_pose", "climb")
        if down and CLIMB_DOWN_POSE in available and pose == "climb":
            pose = CLIMB_DOWN_POSE
        self._play_action(pose)

    def _tick_sleep(self, ctx: dict) -> None:
        """C2 informe revisor 2: mientras sleeping=True, 'sleep' se queda
        en bucle (se re-dispara cuando el cuadro anterior termina, es decir
        cuando `state` vuelve a 'default'). La primera vez pide 'doze' si
        el role la trae (nota de Mia 2026-10-12: bostezo y se queda dormida
        de pie, una vez); si no existe, va directo a 'sleep'.

        D2.2: when the role has a 'yawn' clip she first yawns once, complete (the next stage
        starts only when the clip is over, `state` back to 'default'), then doze -> sleep as
        before. No yawn when sleep starts while she is dragged or falling: then doze -> sleep."""
        available = ctx.get("available_poses") or set()
        if self._sleep_stage is None:
            self._sleep_stage = first_sleep_stage(available, bool(ctx.get("dragging")),
                                                  bool(ctx.get("on_floor", True)))
            self._play_action(self._sleep_stage)
            return
        if ctx.get("state", "default") == "default":
            self._sleep_stage = next_sleep_stage(self._sleep_stage, available)
            self._play_action(self._sleep_stage)

    def _tick_blink(self, ctx: dict, now: float) -> None:
        if ctx.get("state") != "default":
            self._next_blink_at = None
            return
        if self._next_blink_at is None:
            self._next_blink_at = now + choose_blink_delay(self.rng)
            return
        if now >= self._next_blink_at:
            self._play_action("blink")
            self._next_blink_at = now + choose_blink_delay(self.rng)

    def _tick_cursor_flip(self, ctx: dict) -> None:
        # Mia: fuera de 'default' (caminar, seguir cursor, poses) el espejo SE APAGA;
        # antes quedaba pegado y el ciclo de caminar salía invertido (moonwalk).
        if ctx.get("state", "default") != "default":
            self._apply_cursor_flip(False)
            return
        flip = should_flip_to_cursor(ctx.get("pet_center_x", 0), ctx.get("cursor_x", 0),
                                      ctx.get("state", "default"))
        self._apply_cursor_flip(bool(flip))

    def _tick_drag(self, now: float) -> None:
        """C5 informe revisor 2: pide 'kick'/'drag' alternados mientras
        arrastran a Mia. En produccion es efectivamente inerte: llega hasta
        `_mia_play_pose`, pero `pose_allowed()` bloquea SIEMPRE las poses
        del director mientras `dragging=1` (el pataleo real que ve User sale
        de la animacion 'drag' del motor base, no de aqui). Se deja
        documentado y sin tocar su cableado desde `tick()` porque
        `tests/test_mia_director.py::test_microticker_alternates_kick_and_drag_while_dragging`
        (archivo fuera del alcance de esta tarea) ejercita este metodo
        llamando a `tick()` con un `play_action` que no pasa por
        `pose_allowed`; quitar la llamada rompería ese test sin poder
        corregirlo aquí."""
        if self._next_drag_toggle_at is None:
            self._last_drag_pose = "kick"
            self._play_action("kick")
            self._next_drag_toggle_at = now + KICK_ALTERNATE_PERIOD_S
            return
        if now >= self._next_drag_toggle_at:
            self._last_drag_pose = "drag" if self._last_drag_pose == "kick" else "kick"
            self._play_action(self._last_drag_pose)
            self._next_drag_toggle_at = now + KICK_ALTERNATE_PERIOD_S

    def _tick_edge(self, ctx: dict, now: float) -> None:
        """C4 informe revisor 2: al tocar un borde por primera vez se decide
        turn/peek (50/50). 'turn' solo dispara el ciclo de caminar opuesto;
        'peek' pega la pose (con espejo manual si el role solo trae el acto
        generico 'peek') durante peek_duration() y luego vuelve a 'default'.
        """
        at_edge = ctx.get("at_edge")
        new_touch = bool(at_edge) and at_edge != self._last_edge_seen
        # M3: walks now really travel, so a later walk can head into the same wall she is
        # already at; decide again (turn/peek/climb) instead of walking in place against it.
        if (not new_touch and at_edge and ctx.get("walking_toward") == at_edge
                and self._peek_until is None
                and (self._edge_retry_at is None or now >= self._edge_retry_at)):
            new_touch = True
        if new_touch:
            self._edge_retry_at = now + 1.0
        self._last_edge_seen = at_edge

        if new_touch:
            self._on_edge(at_edge)
            action = decide_edge_action(self.rng, self._climb_cfg)
            if action == "climb":
                self._start_climb(at_edge, ctx, now)
            elif action == "turn":
                self._peek_until = None
                self._play_action(opposite_walk_pose(at_edge))
            else:
                available = ctx.get("available_poses") or set()
                pose, mirror = peek_pose_for_side(at_edge, available)
                self._apply_cursor_flip(bool(mirror))
                self._play_action(pose)
                self._peek_until = now + peek_duration(self.rng)
                self._peek_pose = pose
            return

        if self._peek_until is not None and now >= self._peek_until:
            self._peek_until = None
            self._apply_cursor_flip(False)
            # D2: back to her stand only if she is still peeking; a clip that started meanwhile
            # (a walk, a touch reaction, a line) is never cut by the old peek timer.
            if ctx.get("act_name", getattr(self, "_peek_pose", None)) == getattr(self, "_peek_pose", None):
                self._play_action("default")

    def _tick_talk(self, ctx: dict, now: float) -> None:
        # Mia: 'talk' ya es un clip de video completo (boca + gesto, ~4 s, vuelve a la pose).
        # Se lanza UNA vez por globo; alternarlo cada 0.18 s lo reiniciaba sin parar.
        # H4 (informe revisor 3): si el globo aparece mientras state != 'default'
        # (caminando, leyendo...), 'talk' quedaba marcado como "hablado" sin
        # llegar a lanzarse jamas. Ahora queda pendiente (_talk_launched=False)
        # y se dispara en cuanto vuelva a 'default' mientras el globo siga
        # visible.
        if not ctx.get("chat_bubble_visible"):
            self._next_talk_toggle_at = None
            self._talking_default_shown = True
            return
        if self._next_talk_toggle_at is None:
            self._next_talk_toggle_at = now
            self._talking_default_shown = False
        if not self._talking_default_shown and ctx.get("state", "default") == "default":
            self._talking_default_shown = True
            self._play_action("talk")


# ---------------------------------------------------------------------------
# Director Qt: cablea las funciones puras con QTimer/senales.
# ---------------------------------------------------------------------------

@dataclass
class DirectorState:
    last_interaction_ts: float = field(default_factory=time.time)
    dragging: bool = False
    active_interact: Optional[str] = None
    on_floor: bool = True
    sleeping: bool = False
    last_activity_ts: float = float('-inf')   # D2.1: last line or typed message
    sleep_kind: Optional[str] = None     # Mia: "nap" (siesta al azar, despierta sola) | "away" (User lejos del PC)
    wake_at: float = 0.0
    combo_pending: Optional[str] = None  # perfil: secuencia de caracter en cola (t_108e7d40 punto 3)


NAP_RANGE_S = (45.0, 120.0)

# D2.1 (owner: "se quedó dormida a los segundos"): random naps are rare and never early.
NAP_WARMUP_S = 600.0              # no random nap in the first 10 minutes after start
NAP_QUIET_S = 180.0               # nor within 3 minutes of an interaction, typed message or line
NAP_MIN_MEAN_INTERVAL_S = 600.0   # whatever the tick range: at most ~1 random nap per 10 min


def cap_nap_weight(weights: dict, elapsed_s: float,
                   min_mean_interval_s: float = NAP_MIN_MEAN_INTERVAL_S) -> dict:
    """`weights` with 'sleep' lowered so one behaviour roll naps with a share of at most
    `elapsed_s / min_mean_interval_s`, where `elapsed_s` is the time since the previous roll.

    Summed over rolls, the expected number of random naps is then at most
    (time elapsed) / min_mean_interval_s, however short the role's `director_tick_s` is.
    The director restarts that clock when she falls asleep and when she wakes, so the bound
    holds over her awake time. A weight that is already rarer is kept. A configuration whose
    only weight is 'sleep' gets no random naps (away sleep is separate)."""
    out = dict(weights or {})
    try:
        sleep = max(0.0, float(out.get('sleep', 0.0) or 0.0))
        others = sum(max(0.0, float(v)) for k, v in out.items() if k != 'sleep')
    except (TypeError, ValueError):
        return out
    if sleep <= 0.0:
        return out
    if min_mean_interval_s <= 0:
        return out
    max_share = max(0.0, float(elapsed_s)) / float(min_mean_interval_s)
    if max_share >= 1.0:
        return out
    if others <= 0.0:
        out['sleep'] = 0.0
        return out
    limit = max_share * others / (1.0 - max_share)
    if sleep > limit:
        out['sleep'] = limit
    return out


def expected_nap_interval_s(weights: dict, tick_range_s: Sequence[float],
                            min_mean_interval_s: float = NAP_MIN_MEAN_INTERVAL_S) -> float:
    """Mean seconds between random naps while she is awake, idle and past the warm-up and
    quiet rules, when every director tick rolls a behaviour (busy ticks only make it longer).
    Uses the mean tick; the per-roll cap of `cap_nap_weight` included."""
    lo, hi = float(tick_range_s[0]), float(tick_range_s[1])
    tick = (lo + hi) / 2.0
    capped = cap_nap_weight(weights, tick, min_mean_interval_s)
    total = sum(max(0.0, float(v)) for v in capped.values())
    share = max(0.0, float(capped.get('sleep', 0.0))) / total if total > 0 else 0.0
    return tick / share if share > 0 else float('inf')


TALK_LOG_MAX_BYTES = 2 * 1024 * 1024


def append_talk_log(path, kind: str, text: str, max_bytes: int = TALK_LOG_MAX_BYTES,
                    now: Optional[float] = None) -> None:
    """One `HH:MM:SS kind text` line in the pet's local talk log. Past `max_bytes` the log is
    moved to `<name>.1` (one old copy) first. One stat and one append per line; never raises."""
    import datetime
    try:
        path = Path(path)
        try:
            if path.stat().st_size >= max_bytes:
                path.replace(path.with_name(path.name + '.1'))
        except OSError:
            pass
        stamp = datetime.datetime.fromtimestamp(time.time() if now is None else now).strftime('%H:%M:%S')
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write('%s %s %s\n' % (stamp, kind, text))
    except Exception:
        pass


class RateLimitedLog:
    """At most `max_lines` per `window_s` reach `sink`; the rest are counted and the next line
    that gets through says how many were dropped. Cheap: a deque of timestamps."""

    def __init__(self, sink: Callable[[str], None], clock: Callable[[], float],
                 max_lines: int = 20, window_s: float = 60.0):
        self._sink = sink
        self._clock = clock
        self._max = max(1, int(max_lines))
        self._window = float(window_s)
        self._times: deque = deque()
        self.dropped = 0

    def __call__(self, message: str) -> bool:
        try:
            now = self._clock()
            while self._times and now - self._times[0] >= self._window:
                self._times.popleft()
            if len(self._times) >= self._max:
                self.dropped += 1
                return False
            self._times.append(now)
            if self.dropped:
                message = '%s (+%d dropped)' % (message, self.dropped)
                self.dropped = 0
            self._sink(message)
            return True
        except Exception:
            return False


def system_idle_seconds() -> Optional[float]:
    """Segundos desde la última tecla/ratón de User en Windows (GetLastInputInfo); None fuera de Windows.

    H5 (informe revisor 3): GetTickCount() devuelve un DWORD (32 bits sin
    signo); sin declarar `.restype`, ctypes lo trata como `c_long` CON
    signo y, con más de 24.8 días de uptime, da negativo -> Mia creía que
    User SIEMPRE está usando el PC y el sueño 'away' nunca llegaba a
    ocurrir. Se declara DWORD y la resta se enmascara a 32 bits para que
    la vuelta del contador (a los ~49.7 días) tampoco rompa el cálculo.
    """
    try:
        import ctypes
        from ctypes import wintypes

        class _LII(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        lii = _LII()
        lii.cbSize = ctypes.sizeof(_LII)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            return None
        ctypes.windll.kernel32.GetTickCount.restype = wintypes.DWORD
        tick = ctypes.windll.kernel32.GetTickCount()
        return ((tick - lii.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:
        return None


class MiaDirector(QObject if QTimer is not None else object):
    """Orquesta el timer de 8-20 s y delega en las funciones puras de arriba.

    Se construye con callbacks pequenos que leen/escriben el PetWidget, para
    no acoplar este modulo a los detalles de PetWidget ni duplicar estado.
    """

    def __init__(self, get_available_poses: Callable[[], set],
                 play_action: Callable[[str], None],
                 is_busy: Callable[[], bool],
                 weights: Optional[dict] = None,
                 sleep_after_s: float = 300.0,
                 rng: Optional[random.Random] = None,
                 parent=None,
                 system_idle_fn: Optional[Callable[[], Optional[float]]] = system_idle_seconds,
                 now_fn: Callable[[], float] = time.time,
                 mood_table: Optional[dict] = None,
                 get_dominant_mood: Optional[Callable[[], str]] = None,
                 on_absence_return: Optional[Callable[[float], None]] = None,
                 absence_threshold_s: float = 120.0,
                 on_mood_tick: Optional[Callable[[], None]] = None,
                 own_idle_poses: Optional[dict] = None,
                 combos: Optional[dict] = None,
                 tick_range_s: Sequence[float] = (8.0, 20.0),
                 idle_pool: Optional[dict] = None,
                 on_log: Optional[Callable[[str], None]] = None,
                 nap_warmup_s: float = NAP_WARMUP_S,
                 nap_quiet_s: float = NAP_QUIET_S,
                 nap_min_mean_interval_s: float = NAP_MIN_MEAN_INTERVAL_S,
                 walk_room: Optional[Callable[[], Optional[tuple]]] = None):
        if QTimer is not None:
            super().__init__(parent)
        # D2.3: (room, need) from where she stands now, for the direction of a random walk
        # (choose_walk_direction); None, or a failing provider, keeps the coin flip.
        self._walk_room = walk_room
        self._get_available_poses = get_available_poses
        self._play_action = play_action
        self._is_busy = is_busy
        self.weights = dict(weights or DEFAULT_WEIGHTS)
        # perfil: pool de idle propio del personaje activo (contrato
        # perfil por personaje, punto 7); vacio == comportamiento de siempre.
        self._own_idle_poses = dict(own_idle_poses or {})
        # M3.2: the role's own idle pool (pose -> weight). When given it is the whole idle pool,
        # shared with the engine's random animation (pick_idle_pose), never repeating any of
        # the last IDLE_NO_REPEAT idle poses.
        self._idle_pool = dict(idle_pool or {})
        self._recent_idle = deque(maxlen=IDLE_NO_REPEAT)
        self._idle_lock = threading.Lock()
        if self._idle_pool:
            self.weights = fold_pose_weights(self.weights)
        # perfil: secuencias de caracter (t_108e7d40 punto 3), generico;
        # vacio (Mia/Kitty/ChrisKitty hoy) == sin combos, comportamiento de siempre.
        self._combos = dict(combos or {})
        self._tick_range_s = tuple(tick_range_s)
        self._emitting_pose = False
        self.sleep_after_s = sleep_after_s
        self.rng = rng or random.Random()
        self._system_idle = system_idle_fn
        self._now = now_fn
        # Mia: pesos de accion multiplicados por la emocion dominante
        # (contrato mia-mood punto 4). Sin tabla/get_dominant_mood el
        # comportamiento es idéntico al de antes (self.weights tal cual).
        self._mood_table = mood_table
        self._get_dominant_mood = get_dominant_mood
        self._on_absence_return = on_absence_return
        self._absence_threshold_s = absence_threshold_s
        # Mia: decaimiento temporal real (contrato mia-mood, changes
        # requested ronda 1). self.tick() corre cada 8-20 s sin importar si
        # el pet esta dormido/ocupado/arrastrandose (a diferencia de
        # _tick_once, que se sale temprano en esos casos); por eso el
        # decaimiento de MoodEngine se engancha aqui y no dentro de
        # _tick_once, para que boredom/energy/annoyance/shyness evolucionen
        # con el paso del tiempo real aunque User no toque el pet.
        self._on_mood_tick = on_mood_tick
        # Mia: reaccion de toque segun animo (bloqueante B1).
        self._touch_reactor = TouchMoodReactor()
        self.state = DirectorState(last_interaction_ts=now_fn())
        # D2.1: no early naps. The warm-up counts from construction (the pet's start).
        self._started_at = self.state.last_interaction_ts
        self._last_roll_ts = self._started_at
        self._nap_warmup_s = float(nap_warmup_s)
        self._nap_quiet_s = float(nap_quiet_s)
        self._nap_min_mean_interval_s = float(nap_min_mean_interval_s)
        # D2.1: one talk-log line per decision, rate-limited (never chat text).
        self._log_sink = RateLimitedLog(on_log, self._now) if on_log is not None else None
        self.timer = None
        if QTimer is not None:
            self.timer = QTimer(self)
            self.timer.setSingleShot(True)
            self.timer.timeout.connect(self.tick)

    def start(self):
        if self.timer is not None:
            self._schedule_next()

    def _schedule_next(self):
        if self.timer is None:
            return
        # t_108e7d40 punto 3: con una secuencia de caracter en cola (combo),
        # el siguiente tick llega pronto (como una reaccion encadenada), no
        # tras la espera normal de 8-20s -- si no, el combo "se siente"
        # igual de separado que cualquier otra pose suelta.
        if self.state.combo_pending:
            delay = 0.25  # espera fin real (is_busy), no interrumpe el clip.
        else:
            delay = choose_next_tick_delay(self.rng, *self._tick_range_s)
        self.timer.start(int(delay * 1000))

    def note_interaction(self):
        self.state.combo_pending = None
        now = self._now()
        absence_s = now - self.state.last_interaction_ts
        self.state.last_interaction_ts = now
        if self.state.sleeping:
            self._wake_up()
        # Mia: User vuelve tras ausencia (contrato mia-mood punto 2).
        if self._on_absence_return and absence_s >= self._absence_threshold_s:
            try:
                self._on_absence_return(absence_s)
            except Exception:
                pass

    def note_activity(self):
        """A line was shown or a message typed (D2.1): no random nap for NAP_QUIET_S. Unlike
        note_interaction it neither wakes her nor counts as the user coming back."""
        self.state.last_activity_ts = self._now()

    def nap_allowed(self, now: Optional[float] = None) -> bool:
        """A random nap may start: past the warm-up and quiet since the last interaction,
        typed message or line. Away sleep does not ask this."""
        now = self._now() if now is None else now
        quiet_since = max(self.state.last_interaction_ts, self.state.last_activity_ts)
        return now - self._started_at >= self._nap_warmup_s and now - quiet_since >= self._nap_quiet_s

    def _log(self, message: str) -> None:
        if self._log_sink is not None:
            self._log_sink(message)

    def note_action(self, pose: str):
        """Notifica una pose real externa (p. ej. cambio de animo a bored)."""
        if not self._combos or self._emitting_pose:
            return
        followup = choose_combo_followup(self.rng, pose, self._combos)
        self.state.combo_pending = followup if followup in self._get_available_poses() else None
        if self.state.combo_pending:
            self._schedule_next()

    def _emit_pose(self, pose: str, *, combo=False):
        self._log('act %s' % pose)
        self._emitting_pose = True
        try:
            self._play_action(pose)
        finally:
            self._emitting_pose = False
        if not combo:
            self.note_action(pose)

    def _effective_weights(self) -> dict:
        """Pesos base multiplicados por la emocion dominante (contrato
        mia-mood punto 4); sin tabla o sin dominante conocido, devuelve
        self.weights tal cual (compat con llamadas existentes)."""
        dominant = self._current_dominant()
        if not self._mood_table or not dominant:
            return self.weights
        return mood_weighted_choice(self.weights, dominant, self._mood_table)

    def _current_dominant(self) -> Optional[str]:
        """Emocion dominante actual, o None si no hay callback o falla
        (compat: el llamador cae al comportamiento de siempre sin animo)."""
        if not self._get_dominant_mood:
            return None
        try:
            return self._get_dominant_mood()
        except Exception:
            return None

    def touch_mood_pose(self, zone: str) -> Optional[str]:
        """Pose a reproducir en una caricia/toque segun el animo dominante
        VIGENTE (bloqueante B1); None si el animo no sobreescribe nada (el
        llamador sigue con la reaccion de zona de siempre)."""
        return self._touch_reactor.react(self._current_dominant(), zone)

    @property
    def recent_idle(self) -> list:
        return list(self._recent_idle)

    def pick_idle_pose(self, available: Optional[Iterable[str]] = None) -> Optional[str]:
        """Next idle pose from the role's pool, none of the last IDLE_NO_REPEAT ones. Thread-safe:
        the engine's random animation thread asks here too."""
        if not self._idle_pool:
            return None
        if available is None:
            try:
                available = set(self._get_available_poses())
            except Exception:
                available = None
        with self._idle_lock:
            pose = choose_fresh_idle_pose(self.rng, self._idle_pool, self._recent_idle, available,
                                          self._current_dominant(), self._mood_table)
            if pose is not None:
                self._recent_idle.append(pose)
            return pose

    def _emit_idle(self, available) -> None:
        if self._idle_pool:
            pose = self.pick_idle_pose(available)
            if pose is not None:
                self._emit_pose(pose)
            return
        # perfil: el pool se amplia con own_idle_poses del personaje
        # activo (contrato de perfil por personaje, punto 7); vacio ==
        # exactamente choose_weighted_pose/choose_idle_pose de siempre.
        dominant = self._current_dominant()
        pose = choose_profile_idle_pose(
            self.rng, available, dominant, self._mood_table, self._own_idle_poses)
        self._emit_pose(resolve_pose(pose, available))

    def _walk_direction(self) -> Optional[str]:
        """D2.3: a random walk's direction from her real room on her screen (wall-aware)."""
        geometry = None
        if self._walk_room is not None:
            try:
                geometry = self._walk_room()
            except Exception:
                geometry = None
        room, need = geometry if geometry else (None, None)
        return choose_walk_direction(self.rng, room, need)

    def _wake_up(self):
        self.state.sleeping = False
        self.state.sleep_kind = None
        self._last_roll_ts = self._now()     # D2.1: time asleep never counts toward the next nap
        self._log('wake')
        available = self._get_available_poses()
        wake_pose = "wake" if "wake" in available else "yawn"
        self._play_action(resolve_pose(wake_pose, available))

    def _go_to_sleep(self, kind: str):
        # El primer 'doze'/'sleep' lo dispara el MicroTicker (ve sleeping=True en ~150 ms).
        self.state.sleeping = True
        self.state.sleep_kind = kind
        self._last_roll_ts = self._now()
        if kind == "nap":
            seconds = self.rng.uniform(*NAP_RANGE_S)
            self.state.wake_at = self._now() + seconds
            self._log('nap %d' % round(seconds))
        else:
            self.state.wake_at = 0.0
            self._log('away sleep')

    @property
    def is_asleep(self) -> bool:
        """Expuesto para que _mia_chatter (DyberPet.py) y cualquier otro
        gancho sepan si Mia esta dormida sin leer el dataclass interno
        (C2 informe revisor 2)."""
        return self.state.sleeping

    def tick(self):
        if self._on_mood_tick is not None:
            try:
                self._on_mood_tick()
            except Exception:
                pass
        try:
            self._tick_once()
        finally:
            self._schedule_next()

    def _tick_once(self):
        if self.state.dragging or self._is_busy() or not self.state.on_floor:
            return

        now = self._now()
        sys_idle = self._system_idle() if self._system_idle else None
        if self.state.sleeping:
            # Mia: siesta -> despierta sola; sueño "away" -> despierta cuando User vuelve al PC.
            if self.state.sleep_kind == "nap" and now >= self.state.wake_at:
                self._wake_up()
            elif self.state.sleep_kind == "away" and sys_idle is not None and sys_idle < 60:
                self._wake_up()
            return
        # Sueño largo: nadie toca a Mia Y (si se puede saber) User no usa el PC.
        idle_s = now - self.state.last_interaction_ts
        if sys_idle is not None:
            idle_s = min(idle_s, sys_idle)
        if should_sleep(idle_s, self.sleep_after_s):
            self.state.combo_pending = None
            self._go_to_sleep("away")
            return

        available = self._get_available_poses()
        if self.state.combo_pending:
            followup = self.state.combo_pending
            self.state.combo_pending = None
            if followup in available and not (self._idle_pool and followup in self._recent_idle):
                if self._idle_pool and followup in self._idle_pool:
                    with self._idle_lock:
                        self._recent_idle.append(followup)
                self._emit_pose(followup, combo=True)
                return
        # D2.1: random naps only past the warm-up and quiet rules, and never more often than
        # about one per NAP_MIN_MEAN_INTERVAL_S whatever the tick range.
        elapsed, self._last_roll_ts = now - self._last_roll_ts, now
        weights = dict(self._effective_weights())
        if self.nap_allowed(now):
            weights = cap_nap_weight(weights, elapsed, self._nap_min_mean_interval_s)
        elif "sleep" in weights:
            weights["sleep"] = 0.0
        action = choose_behavior(weights, self.rng)
        if action == "idle":
            self._emit_idle(available)
        elif action == "walk":
            direction = self._walk_direction()
            if direction is None:
                # D2.3: no room for a walk on either side (a tiny screen): an idle pose instead.
                self._log('walk none (no room)')
                self._emit_idle(available)
                return
            # build_mia_role.py registra el ciclo de caminar como
            # "left_walk"/"right_walk" (pet_conf['random_act'], no
            # "walk_left"/"walk_right"); con el nombre equivocado caminar
            # era un NO-OP real (informe revisor B2).
            self._log('walk %s' % direction)
            self._play_action(f"{direction}_walk")
        elif action == "follow_cursor":
            self._log('follow')
            self._play_action("follow_cursor")
        elif action == "sleep":
            # Mia: siesta corta al azar; despierta sola (antes quedaba dormida para siempre).
            self._go_to_sleep("nap")
        elif self._combos and action in available:
            # Solo perfiles que optan por secuencias: pesos de poses propias.
            self._emit_pose(action)


# --- Mia: charla espontánea con el modelo local (User: "no habla, solo saluda") ---

_POSE_DESC = {
    "read": "you are reading a book", "sit": "you are sitting down for a rest",
    "think": "you are lost in thought", "stretch": "you just stretched",
    "yawn": "you just yawned", "walk": "you are strolling along the taskbar",
    "sleep": "you are waking up from a nap", "happy": "you are in a good mood",
    "tea": "you are sipping your tea",
}


def pose_description(pose: Optional[str]) -> Optional[str]:
    """What she is doing in `pose`, for the chatter context ('tea' -> sipping her tea)."""
    return _POSE_DESC.get((pose or "").replace("right_", "").replace("left_", ""))

_CHATTER_TOPICS = (
    "Share a short thought about what you are doing right now.",
    "Tell User one short, true fact about the stars or space.",
    "Recommend a kind of book or story to User, in one line.",
    "Ask User, with real curiosity, what he is working on.",
    "Gently remind User to drink some water or stretch.",
    "Make a short remark about the time of day.",
    "Say something kind or funny to User, no empty flattery.",
    "Make up the title of a short story you would like to write.",
)

# Globos fijos (respaldo cuando el modelo local no responde).
LINES = {
    "greet": "Hi, User!",
    "bye": "See you later, User.",
    "touch": "Hey! That tickles.",
    "pat": "Mm, thanks, User.",
}

# perfil: alias para reusar frases propias del perfil activo cuando LINES
# no tiene una clave 1:1 en *_lines.json (p. ej. "touch"/"pat" generico ->
# "touch_body"/"patpat", que si existen en un <pet>_lines.json propio).
_FALLBACK_LINE_ALIASES = {"touch": "touch_body", "pat": "patpat"}


def fallback_line(key: str, lines: Optional[dict] = None) -> str:
    """Frase de respaldo para `key` ("greet"/"bye"/"touch"/"pat").

    Sin `lines` (perfil sin *_lines.json propio: Mia/Kitty/ChrisKitty,
    contrato punto 8) devuelve LINES[key] tal cual, sin cambios. Con
    `lines` (perfil propio ya cargado) usa su primera
    frase para `key` o, si no la tiene, para el alias en
    `_FALLBACK_LINE_ALIASES`; solo si ninguna existe cae a LINES[key]
    (ingles) -- contrato punto 7: la respuesta de respaldo nunca debe
    salir en ingles para un perfil que ya trae sus propias frases.
    """
    if lines:
        options = lines.get(key) or lines.get(_FALLBACK_LINE_ALIASES.get(key, ""))
        if options:
            return options[0] if isinstance(options, list) else options
    return LINES[key]


def _part_of_day(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 18:
        return "afternoon"
    if 18 <= hour < 22:
        return "evening"
    return "night"


def greeting_prompt(now) -> str:
    """Saludo al abrir con la hora real: sin ella el 3B decía 'Good morning' a las 5 PM."""
    clock = now.strftime("%I:%M %p").lstrip("0")
    part = _part_of_day(now.hour)
    return ("It is %s in the %s. User just turned on his computer and opened you. "
            "Greet him in one short line that fits the %s." % (clock, part, part))


def choose_chatter_prompt(rng, now, pose: Optional[str] = None) -> str:
    """Pide al modelo local una frase espontánea con contexto real (hora y pose), en inglés."""
    topic = rng.choice(_CHATTER_TOPICS)
    clock = now.strftime("%I:%M %p").lstrip("0")
    ctx = "It is %s in the %s." % (clock, _part_of_day(now.hour))
    desc = pose_description(pose)
    if desc:
        ctx += " Right now %s." % desc
    return "%s %s Talk to User directly (use you), one sentence." % (ctx, topic)


def next_chatter_delay(rng, cfg: Optional[dict] = None) -> float:
    cfg = cfg or {}
    lo = float(cfg.get("min_s", 90))
    hi = float(cfg.get("max_s", 240))
    return rng.uniform(lo, max(lo, hi))


def may_chatter(onfloor: int, dragging: int, chat_open: bool,
                bubble_visible: bool, asleep: bool) -> bool:
    """Solo habla sola si está en el suelo, libre y sin otra conversación en pantalla."""
    return bool(onfloor) and not dragging and not chat_open and not bubble_visible and not asleep


# ---------------------------------------------------------------------------
# 12. Trepar paredes (climb) — pedido de User: "hay forma de hacer que
# escale.. suba, que esté por toda la pantalla?"
#
# Arte: 'climb' (96 cuadros climb_right_*, pared a SU DERECHA); para la
# pared izquierda se espeja a mano, igual que peek con cursor_flip.
# Solo se dispara en bordes EXTERIORES del escritorio (outer_edge(), ya
# resuelto en la seccion 10b): nunca en la costura entre pantallas.
# ---------------------------------------------------------------------------

CLIMB_HEIGHT_FRAC = (0.20, 0.85)
CLIMB_HOLD_RANGE_S = (2.5, 10.0)   # M3.1: half of M3's 5-20 s (the climb felt slow)
CLIMB_RELEASE_FALL_PROB = 0.6     # 60% suelta y cae, 40% baja trepando
CLIMB_CEILING_MARGIN_PX = 10      # "y <= top + 10" del contrato

# M3: on by default ("she only stays on the bottom"); the "Climb walls" menu toggle
# still writes climb.enabled in the user's brain file and that choice wins.
DEFAULT_CLIMB_CFG = {
    "enabled": True,
    "prob": 0.35,
    "speed": 40.0,
    "hold_s": [2.5, 10.0],
}


def load_climb_config(brain_cfg_or_path) -> dict:
    """Lee la clave "climb" de mia_brain.json.

    Acepta la ruta del archivo o un dict ya cargado (p. ej. por
    `load_director_config`). Si falta el archivo, no es JSON valido, o no
    trae la clave "climb", cae a DEFAULT_CLIMB_CFG (M3: habilitado por defecto;
    el toggle del menu lo apaga y esa eleccion se guarda).
    """
    if isinstance(brain_cfg_or_path, dict):
        data = brain_cfg_or_path
    else:
        path = Path(brain_cfg_or_path)
        if not path.is_file():
            return dict(DEFAULT_CLIMB_CFG)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return dict(DEFAULT_CLIMB_CFG)
        if not isinstance(data, dict):
            return dict(DEFAULT_CLIMB_CFG)
    climb = data.get("climb")
    cfg = dict(DEFAULT_CLIMB_CFG)
    if isinstance(climb, dict):
        for key in DEFAULT_CLIMB_CFG:
            if key in climb:
                cfg[key] = climb[key]
    return cfg


def climb_target_frac(rng: random.Random, height_frac=CLIMB_HEIGHT_FRAC) -> float:
    """Altura objetivo al azar entre 20% y 85% de la altura de la pantalla."""
    lo, hi = height_frac
    return rng.uniform(lo, hi)


def climb_hold_duration(rng: random.Random, hold_s=CLIMB_HOLD_RANGE_S) -> float:
    """5-20 s colgada arriba (comportamiento 2)."""
    lo, hi = hold_s
    return rng.uniform(lo, hi)


def climb_release_outcome(rng: random.Random, fall_prob: float = CLIMB_RELEASE_FALL_PROB) -> str:
    """60% "fall" (se suelta y cae), 40% "walk_down" (baja trepando, comportamiento 3)."""
    return "fall" if rng.uniform(0, 1) < fall_prob else "walk_down"


def climb_pose_for_side(side: str, available_poses: Iterable[str]) -> tuple[str, bool]:
    """Pose a pedir para trepar por `side` y si hay que espejarla a mano.

    El arte solo trae 'climb_right_*' (acto generico 'climb'); para la pared
    izquierda se espeja a mano, igual que peek_pose_for_side.
    """
    dedicated = "climb_%s" % side
    if dedicated in available_poses:
        return dedicated, False
    return "climb", side == "left"


CLIMB_DOWN_POSE = "climb_down"   # the climb clip played backwards (built by the pet window)


def frame_period_s(frame_refresh: float, tick_s: float) -> float:
    """How long the engine's interaction timer really shows one frame: whole ticks."""
    if tick_s <= 0:
        return max(frame_refresh, 1e-3)
    return max(1, math.ceil(round(frame_refresh / tick_s, 6))) * tick_s


def climb_speed_px_s(frame_move: float, display_scale: float, frame_refresh: float, tick_s: float) -> float:
    """Climb speed (logical px/s) at which the holds do not slide on the wall:
    `frame_move` sprite px per frame (scripts/measure_sprite_motion.py) at the on-screen
    scale, once per displayed frame of the climb clip."""
    return float(frame_move) * float(display_scale) / frame_period_s(frame_refresh, tick_s)


@dataclass
class ClimbSession:
    """Estado puro (sin Qt) de una trepada en curso.

    `y` es la coordenada logica Qt del tope del sprite (decrece al subir,
    como toda coordenada de pantalla). `floor_y` es donde esta parada antes
    de trepar (y a donde vuelve si baja trepando); `screen_top` es el borde
    superior de SU pantalla actual (si lo toca, se suelta: comportamiento 4).
    """
    side: str
    y: float
    floor_y: float
    screen_top: float
    speed: float
    target_y: float
    phase: str = "up"              # up -> hold -> down|released_fall -> done
    hold_until: Optional[float] = None
    last_t: float = 0.0

    @classmethod
    def start(cls, side: str, start_y: float, floor_y: float, screen_top: float,
              screen_height: float, speed: float, rng: random.Random, now: float,
              height_frac=CLIMB_HEIGHT_FRAC) -> "ClimbSession":
        frac = climb_target_frac(rng, height_frac)
        target_y = floor_y - frac * screen_height
        target_y = max(target_y, screen_top + CLIMB_CEILING_MARGIN_PX)
        return cls(side=side, y=start_y, floor_y=floor_y, screen_top=screen_top,
                    speed=speed, target_y=target_y, last_t=now)

    @property
    def active(self) -> bool:
        return self.phase in ("up", "hold", "down")

    def advance(self, now: float, rng: random.Random,
                hold_s=CLIMB_HOLD_RANGE_S) -> Optional[str]:
        """Avanza el estado segun el tiempo transcurrido desde la ultima
        llamada. Devuelve un evento ("ceiling", "released_fall",
        "walk_down_start", "reached_floor") o None si no paso nada notable.
        """
        dt = max(0.0, now - self.last_t)
        self.last_t = now

        if self.phase == "up":
            self.y -= self.speed * dt
            if self.y <= self.screen_top + CLIMB_CEILING_MARGIN_PX:
                self.y = self.screen_top + CLIMB_CEILING_MARGIN_PX
                self.phase = "released_fall"
                return "ceiling"
            if self.y <= self.target_y:
                self.y = self.target_y
                self.phase = "hold"
                self.hold_until = now + climb_hold_duration(rng, hold_s)
            return None

        if self.phase == "hold":
            if self.hold_until is not None and now >= self.hold_until:
                if climb_release_outcome(rng) == "fall":
                    self.phase = "released_fall"
                    return "released_fall"
                self.phase = "down"
                return "walk_down_start"
            return None

        if self.phase == "down":
            self.y += self.speed * dt
            if self.y >= self.floor_y:
                self.y = self.floor_y
                self.phase = "done"
                return "reached_floor"
            return None

        return None


def clean_reply(text: Optional[str], limit: int = 140) -> Optional[str]:
    """Quita comillas, prefijo 'Mia:' y recorta en palabra."""
    if not text:
        return None
    t = " ".join(str(text).split()).strip()
    for prefix in ("Mia:", "Mía:", "MIA:", "Mia says:"):
        if t.startswith(prefix):
            t = t[len(prefix):].strip()
    t = t.strip('"“”«»\'').strip()
    if not t:
        return None
    if len(t) > limit:
        cut = t[:limit].rsplit(" ", 1)[0].rstrip(",;:")
        t = cut + "…"
    return t


# ---------------------------------------------------------------------------
# 12. Animo: pesos de accion por emocion y frase por clip (contrato mia-mood)
# ---------------------------------------------------------------------------

def load_mood_table(brain_path) -> dict:
    """Lee data/mia_brain.json["mood"] (pose -> {emocion: multiplicador}).

    Si falta el archivo, no es JSON valido o no trae la clave, devuelve {}
    (sin tabla, mood_weighted_choice deja los pesos intactos).
    """
    brain_path = Path(brain_path)
    if not brain_path.is_file():
        return {}
    try:
        data = json.loads(brain_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    table = data.get("mood") if isinstance(data, dict) else None
    return dict(table) if isinstance(table, dict) else {}


def merge_mood_tables(own: Optional[dict], bundled: Optional[dict]) -> dict:
    """The profile's mood table plus the bundled entries for the poses it does not list.

    D2.2: the profile copies the brain file once, so a profile made before a clip existed (mirror,
    quill) has no mood entry for it. Every pose the profile does list keeps the profile's entry
    exactly as it is (the user's edits win); the bundled table only fills the gaps."""
    out = dict(bundled or {}) if isinstance(bundled, dict) else {}
    if isinstance(own, dict):
        out.update(own)
    return out


def mood_weighted_choice(weights: dict, dominant: str, mood_table: dict) -> dict:
    """Multiplica `weights` (pesos base de una accion/pose) por el
    multiplicador que mood_table trae para `dominant`; sin entrada en la
    tabla el multiplicador es 1.0 (sin cambio)."""
    out = {}
    for name, base in weights.items():
        mult = 1.0
        entry = mood_table.get(name) if mood_table else None
        if isinstance(entry, dict) and dominant in entry:
            try:
                mult = float(entry[dominant])
            except (TypeError, ValueError):
                mult = 1.0
        out[name] = max(0.0, float(base) * mult)
    return out


def load_lines(lines_path) -> dict:
    """Lee data/mia_lines.json (clave "pose" o "pose|emocion" -> lista de
    frases). Si falta o es invalido, devuelve {} (sin frase instantanea,
    el llamador sigue con la charla del LLM o sin globo)."""
    lines_path = Path(lines_path)
    if not lines_path.is_file():
        return {}
    try:
        data = json.loads(lines_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def pick_line(lines: dict, pose: str, dominant: str, recent: Sequence[str],
              rng: random.Random) -> Optional[str]:
    """Frase instantanea para una pose "con significado": prueba primero
    "pose|emocion", luego solo "pose"; evita repetir las ultimas 5 de
    `recent` si hay alternativa (contrato punto 5)."""
    options = lines.get("%s|%s" % (pose, dominant)) or lines.get(pose)
    if not options:
        return None
    options = list(options)
    avoid = set(recent[-5:]) if recent else set()
    fresh = [o for o in options if o not in avoid]
    pool = fresh or options
    return rng.choice(pool)


def should_say_line(rng: random.Random, is_touch_reaction: bool, prob: float = 0.5) -> bool:
    """Probabilidad de frase instantanea al arrancar una pose con
    significado: 1.0 en reacciones a toques, `prob` (default 0.5) el resto."""
    if is_touch_reaction:
        return True
    return rng.uniform(0, 1) < prob


MEANINGFUL_POSES = (
    "happy", "angry", "shy", "bored", "pinch", "touch_body", "patpat",
    "stretch", "yawn", "wake", "onfloor", "climb", "read", "think",
    "peek", "bye", "greet",
)


# ---------------------------------------------------------------------------
# 13. Fix B1 (t_a82d63b9): el toque consulta el animo dominante.
# ---------------------------------------------------------------------------

class TouchMoodReactor:
    """Reaccion de toque segun la emocion dominante (bloqueante B1).

    angry -> 'pinch' (zona mejilla) o 'angry' (cabeza/cuerpo); el
    ablandamiento gradual ("1a caricia angry/pinch, 2a-3a se ablanda a shy
    o happy") ya lo hace MoodEngine (pending_soften, ventana de tiempo
    real entre caricias): esta clase solo traduce la dominante VIGENTE a
    una pose, asi que en cuanto MoodEngine saca a Mia de angry, deja de
    devolver 'angry'/'pinch' sola.

    shy -> 'shy' la primera vez de la racha; si User sigue tocando
    (segundo toque en racha, sin que la dominante cambie de shy) ->
    'peek' (se asoma en vez de repetir 'shy').

    bored -> 'bored' (la saca de su letargo).

    Para cualquier otra dominante, devuelve None: el llamador sigue con
    la reaccion de zona de siempre (patpat/pinch/touch_body).
    """

    def __init__(self):
        self._shy_streak = 0

    def react(self, dominant: Optional[str], zone: str) -> Optional[str]:
        if dominant == "angry":
            self._shy_streak = 0
            return "pinch" if zone == "cheek" else "angry"
        if dominant == "shy":
            self._shy_streak += 1
            return "peek" if self._shy_streak >= 2 else "shy"
        if dominant == "bored":
            self._shy_streak = 0
            return "bored"
        self._shy_streak = 0
        return None


# Frases/prompts de respaldo para la reaccion de toque cuando el animo
# sobreescribe la pose de zona de siempre (DyberPet.py: patpat()). El
# prompt se le pide al LLM local (fallback a la frase fija si no responde),
# igual que ya se hacia para pinch/touch_body de zona.
MOOD_TOUCH_PROMPTS = {
    "angry": "User just touched you again even though you are annoyed at him. Say one short, grumpy line that pushes him away a little.",
    "pinch": "User pinched your cheek while you are still annoyed at him. Say one short, grumpy line that pushes him away a little.",
    "shy": "User's touch caught you off guard and you feel shy about it. Say one short, bashful line.",
    "peek": "You feel too shy to look at User directly right now. Say one short line while barely peeking at him.",
    "bored": "User's touch pulled you out of being bored. Say one short line about finally having something to do.",
}

MOOD_TOUCH_LINES = {
    "angry": "Hmph. Not right now, User.",
    "pinch": "Hey! I'm still a little mad, User.",
    "shy": "O-oh... stop that, User.",
    "peek": "...I'm still here, User. Just peeking.",
    "bored": "Finally, something to do, User.",
}


def mood_touch_fallback_line(mood_pose: str, lines: Optional[dict] = None) -> str:
    """Respaldo del toque con animo para `mood_pose` ("angry"/"pinch"/"shy"/
    "peek"/"bored").

    Correccion FAIL t_ea577267 (B2): antes `MOOD_TOUCH_LINES[mood_pose]` se
    usaba a secas, en ingles fijo, aunque el perfil activo ya
    traiga su propia frase para esa clave (<pet>_lines.json: angry,
    shy, bored, peek, pinch). Con `lines` (perfil propio, igual que
    `fallback_line`) se usa esa frase; sin `lines` (Mia/Kitty/ChrisKitty,
    contrato punto 8) cae exactamente a MOOD_TOUCH_LINES de siempre."""
    if lines:
        options = lines.get(mood_pose)
        if options:
            return options[0] if isinstance(options, list) else options
    return MOOD_TOUCH_LINES[mood_pose]


# Mia: cuando la dominante CAMBIA (toque o decaimiento) a una de estas, el
# director debe reproducir ese clip una vez con frase (bloqueante B1:
# "Cuando la dominante cambia a angry/shy/bored, el director reproduce
# ese clip una vez (con frase)"). Logica minima, usada por los ganchos
# _mia_note_mood_event/_mia_mood_tick de DyberPet.py.
MOOD_ANNOUNCE_CLIPS = ("angry", "shy", "bored")


def should_play_mood_clip(new_dominant: Optional[str]) -> bool:
    return new_dominant in MOOD_ANNOUNCE_CLIPS
