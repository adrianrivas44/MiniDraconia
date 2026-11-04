"""Animo de Mia con continuidad (contrato mia-mood, pedido de User 2026-10-25).

Modulo puro, sin Qt, con reloj inyectable (`now_fn`) para que todo sea
testeable con `pytest` sin abrir la app y sin llamadas de red.

Estado con ejes 0..1 (joy, energy, annoyance, boredom, shyness) mas
`affection` de largo plazo. Los eventos (caricias, pellizcos, charla,
ausencia/regreso de User...) mueven los ejes; `decay()` los acerca a una
base por minuto transcurrido (energy sigue un ciclo circadiano en vez de
una base fija). De los ejes se deriva una emocion dominante.

No toca local_brain.py / mia_chat.py / mia_proxy.py / run_DyberPet.py (en
paralelo corre el contrato del cerebro Grok). Para pedir frases al LLM se
sigue usando la API que ya existe en DyberPet.py (`_mia_ask`).
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional, Sequence

MAX_EVENTS = 8

BASELINE = {
    "joy": 0.5,
    "annoyance": 0.0,
    "boredom": 0.2,
    "shyness": 0.0,
}

# Cuanto se acerca cada eje a su base por minuto transcurrido (energy aparte,
# sigue el ciclo circadiano en _decay_energy).
DECAY_PER_MIN = {
    "joy": 0.03,
    "annoyance": 0.08,
    "shyness": 0.10,
}

BOREDOM_RISE_PER_MIN = 0.03  # User inactivo
BOREDOM_FALL_PER_MIN = 0.02  # User activo/charlando

# Umbrales de la emocion dominante.
ANGRY_TH = 0.60
ANNOYED_TH = 0.35
SHY_TH = 0.50
BORED_TH = 0.60
SLEEPY_ENERGY_TH = 0.25
HAPPY_TH = 0.60
EXCITED_ENERGY_TH = 0.60

_EVENT_PHRASES = {
    "pat": "patted you",
    "touch_body": "poked you",
    "pinch": "pinched you",
    "drag": "dragged you around",
    "fall": "dropped you",
    "chat": "chatted with you",
    "climb_top": "watched you climb all the way up",
    "zero_returns": "came back to you",
}


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _move_toward(value: float, target: float, max_step: float) -> float:
    if max_step <= 0:
        return value
    diff = target - value
    if abs(diff) <= max_step:
        return target
    return value + max_step if diff > 0 else value - max_step


def hour_of(ts: float) -> float:
    """Hora local (0..24, fraccional) de un epoch; `time.localtime` es
    suficiente para el ciclo dia/noche que pide el contrato."""
    t = time.localtime(ts)
    return t.tm_hour + t.tm_min / 60.0


def hour_energy_baseline(hour: float) -> float:
    """Curva de energia segun la hora (alta de dia, baja de madrugada).

    Coseno centrado en las 15:00 (pico) con valle hacia las 03:00.
    """
    rad = (hour - 15.0) / 24.0 * 2 * math.pi
    base = 0.55 + 0.35 * math.cos(rad)
    return _clamp(base, 0.15, 0.95)


@dataclass
class MoodState:
    joy: float = 0.5
    energy: float = 0.6
    annoyance: float = 0.0
    boredom: float = 0.2
    shyness: float = 0.0
    affection: float = 0.2
    last_update: float = 0.0
    last_seen: float = 0.0
    awake_since: float = 0.0
    pending_soften: int = 0  # caricias seguidas desde que se puso angry
    events: list = field(default_factory=list)  # [(ts, kind), ...] <= MAX_EVENTS
    dominant: str = "content"

    # -- derivacion de la emocion dominante -------------------------------
    def recompute_dominant(self) -> str:
        if self.annoyance >= ANGRY_TH:
            self.dominant = "angry"
        elif self.shyness >= SHY_TH:
            self.dominant = "shy"
        elif self.annoyance >= ANNOYED_TH:
            self.dominant = "annoyed"
        elif self.boredom >= BORED_TH:
            self.dominant = "bored"
        elif self.energy <= SLEEPY_ENERGY_TH:
            self.dominant = "sleepy"
        elif self.joy >= HAPPY_TH and self.energy >= EXCITED_ENERGY_TH:
            self.dominant = "excited"
        elif self.joy >= HAPPY_TH:
            self.dominant = "happy"
        else:
            self.dominant = "content"
        if self.dominant != "angry":
            self.pending_soften = 0
        return self.dominant

    # -- decaimiento --------------------------------------------------------
    def decay(self, now: float) -> None:
        if not self.last_update:
            self.last_update = now
            self.last_seen = self.last_seen or now
            self.awake_since = self.awake_since or now
            self.recompute_dominant()
            return
        elapsed_min = (now - self.last_update) / 60.0
        if elapsed_min <= 0:
            return
        self.joy = _move_toward(self.joy, BASELINE["joy"], DECAY_PER_MIN["joy"] * elapsed_min)
        self.annoyance = _move_toward(self.annoyance, BASELINE["annoyance"],
                                       DECAY_PER_MIN["annoyance"] * elapsed_min)
        self.shyness = _move_toward(self.shyness, BASELINE["shyness"],
                                     DECAY_PER_MIN["shyness"] * elapsed_min)
        idle_min = (now - self.last_seen) / 60.0
        if idle_min > 1.0:
            self.boredom = _clamp(self.boredom + BOREDOM_RISE_PER_MIN * elapsed_min)
        else:
            self.boredom = _move_toward(self.boredom, BASELINE["boredom"],
                                         BOREDOM_FALL_PER_MIN * elapsed_min)
        self._decay_energy(now, elapsed_min)
        # affection es de largo plazo: decae muchisimo mas lento (casi no se
        # mueve en una sesion; se conserva al guardar/cargar incluso tras
        # varias horas, contrato punto 6).
        self.affection = _move_toward(self.affection, 0.15, 0.0002 * elapsed_min)
        self.last_update = now
        self.recompute_dominant()

    def _decay_energy(self, now: float, elapsed_min: float) -> None:
        target = hour_energy_baseline(hour_of(now))
        awake_h = max(0.0, (now - self.awake_since) / 3600.0)
        target = _clamp(target - min(0.30, 0.02 * awake_h))
        self.energy = _move_toward(self.energy, target, 0.05 * elapsed_min)

    # -- eventos --------------------------------------------------------
    def _recent(self, kind: str, now: float, within_s: float) -> int:
        return sum(1 for ts, k in self.events if k == kind and now - ts < within_s)

    def record_event(self, kind: str, now: float, **meta) -> None:
        self.events.append((now, kind))
        if len(self.events) > MAX_EVENTS:
            self.events = self.events[-MAX_EVENTS:]

        if kind == "pat":
            was_angry = self.dominant == "angry"
            self.joy = _clamp(self.joy + 0.08)
            self.affection = _clamp(self.affection + 0.01)
            if was_angry:
                self.pending_soften += 1
                reduction = 0.30 if self.pending_soften >= 3 else 0.12
                self.annoyance = _clamp(self.annoyance - reduction)
            if self._recent("pat", now, 30.0) >= 3:
                self.shyness = _clamp(self.shyness + 0.5)
        elif kind == "touch_body":
            if self._recent("touch_body", now, 30.0) >= 2:
                self.annoyance = _clamp(self.annoyance + 0.10)
            else:
                self.shyness = _clamp(self.shyness + 0.12)
        elif kind == "pinch":
            self.annoyance = _clamp(self.annoyance + 0.22)
            if self._recent("pinch", now, 60.0) >= 3:
                self.annoyance = _clamp(self.annoyance + 0.25)
        elif kind == "drag":
            if self.energy > 0.5:
                self.joy = _clamp(self.joy + 0.10)
            else:
                self.annoyance = _clamp(self.annoyance + 0.12)
        elif kind == "fall":
            self.annoyance = _clamp(self.annoyance + 0.05)
        elif kind == "chat":
            self.joy = _clamp(self.joy + 0.08)
            self.boredom = _clamp(self.boredom - 0.15)
            self.affection = _clamp(self.affection + 0.015)
        elif kind == "climb_top":
            self.joy = _clamp(self.joy + 0.10)
        elif kind == "zero_returns":
            absence_s = float(meta.get("absence_s", 0.0))
            if absence_s >= 1800:
                # ausencia muy larga: alivio pero tambien un puchero.
                self.annoyance = _clamp(self.annoyance + 0.08)
                self.joy = _clamp(self.joy + 0.05)
            else:
                self.joy = _clamp(self.joy + 0.10)
            self.boredom = _clamp(self.boredom - 0.20)
        self.recompute_dominant()

    # -- persistencia --------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "joy": self.joy,
            "energy": self.energy,
            "annoyance": self.annoyance,
            "boredom": self.boredom,
            "shyness": self.shyness,
            "affection": self.affection,
            "last_update": self.last_update,
            "last_seen": self.last_seen,
            "awake_since": self.awake_since,
            "pending_soften": self.pending_soften,
            "events": [[ts, kind] for ts, kind in self.events],
            "dominant": self.dominant,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MoodState":
        if not isinstance(data, dict):
            return cls()
        kwargs = {}
        for key in ("joy", "energy", "annoyance", "boredom", "shyness", "affection",
                    "last_update", "last_seen", "awake_since", "pending_soften", "dominant"):
            if key in data:
                kwargs[key] = data[key]
        events = data.get("events") or []
        parsed = []
        for item in events:
            try:
                ts, kind = item[0], item[1]
            except (TypeError, IndexError, KeyError):
                continue
            parsed.append((float(ts), str(kind)))
        kwargs["events"] = parsed[-MAX_EVENTS:]
        state = cls(**kwargs)
        state.recompute_dominant()
        return state


EVENT_KINDS = ("pat", "touch_body", "pinch", "drag", "fall", "chat", "climb_top", "zero_returns")


class MoodEngine:
    """Envoltura con reloj inyectable alrededor de `MoodState`.

    `now_fn` default `time.time`; en tests se inyecta un reloj falso
    (closure o contador) para avanzar el tiempo de forma determinista.
    """

    def __init__(self, now_fn: Callable[[], float] = time.time,
                 state: Optional[MoodState] = None):
        self.now_fn = now_fn
        self.state = state or MoodState()
        now = self.now_fn()
        if not self.state.last_update:
            self.state.last_update = now
        if not self.state.last_seen:
            self.state.last_seen = now
        if not self.state.awake_since:
            self.state.awake_since = now
        self.state.recompute_dominant()

    @property
    def dominant(self) -> str:
        return self.state.dominant

    def tick(self, now: Optional[float] = None) -> Optional[str]:
        """Aplica el decaimiento; devuelve la nueva dominante si cambio
        (para la bitacora "animo <emocion>"), o None si sigue igual."""
        now = self.now_fn() if now is None else now
        before = self.state.dominant
        self.state.decay(now)
        return self.state.dominant if self.state.dominant != before else None

    def record(self, kind: str, now: Optional[float] = None, **meta) -> Optional[str]:
        """Registra un evento (pat/touch_body/pinch/drag/fall/chat/
        climb_top/zero_returns). Devuelve la nueva dominante si cambio."""
        if kind not in EVENT_KINDS:
            return None
        now = self.now_fn() if now is None else now
        before = self.state.dominant
        self.state.decay(now)
        self.state.last_seen = now
        self.state.record_event(kind, now, **meta)
        return self.state.dominant if self.state.dominant != before else None

    def mark_seen(self, now: Optional[float] = None) -> None:
        now = self.now_fn() if now is None else now
        self.state.decay(now)
        self.state.last_seen = now

    def seconds_since_seen(self, now: Optional[float] = None) -> float:
        now = self.now_fn() if now is None else now
        return max(0.0, now - self.state.last_seen)

    def describe_events(self, now: Optional[float] = None, limit: int = 3) -> str:
        """Frase en ingles natural con los ultimos eventos, para darle
        continuidad a la charla espontanea del LLM (contrato punto 5)."""
        now = self.now_fn() if now is None else now
        if not self.state.events:
            return ""
        parts = []
        for ts, kind in self.state.events[-limit:]:
            phrase = _EVENT_PHRASES.get(kind)
            if not phrase:
                continue
            parts.append("User %s %s" % (phrase, _ago_phrase(max(0.0, now - ts))))
        return ", then ".join(parts)

    def mood_context_prompt(self, now: Optional[float] = None) -> str:
        """Prefijo para el prompt de charla espontanea: emocion, affection y
        continuidad de eventos (contrato punto 5)."""
        now = self.now_fn() if now is None else now
        bits = ["You currently feel %s (affection for User: %.2f)." %
                (self.state.dominant, self.state.affection)]
        events_text = self.describe_events(now)
        if events_text:
            bits.append(events_text + ".")
        return " ".join(bits)

    # -- persistencia --------------------------------------------------------
    def to_dict(self) -> dict:
        return self.state.to_dict()

    @classmethod
    def from_dict(cls, data: dict, now_fn: Callable[[], float] = time.time) -> "MoodEngine":
        return cls(now_fn=now_fn, state=MoodState.from_dict(data))

    def save(self, path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path, now_fn: Callable[[], float] = time.time) -> "MoodEngine":
        path = Path(path)
        if not path.is_file():
            return cls(now_fn=now_fn)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls(now_fn=now_fn)
        engine = cls.from_dict(data, now_fn=now_fn)
        engine.tick(now_fn())
        return engine


def _ago_phrase(seconds: float) -> str:
    if seconds < 90:
        return "a moment ago"
    minutes = seconds / 60.0
    if minutes < 2:
        return "a minute ago"
    if minutes < 60:
        return "%d minutes ago" % int(minutes)
    hours = minutes / 60.0
    if hours < 2:
        return "an hour ago"
    return "a while ago"
