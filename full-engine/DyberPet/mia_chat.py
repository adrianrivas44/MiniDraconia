"""Chat escrito con Mia (comportamiento 12, docs/contrato-chat.txt).

Reemplaza la voz/TTS anulada por User. User puede escribirle a Mia en una
caja de texto flotante; Mia responde en su globo usando el modelo local
(Ollama) con un historial corto en memoria (no se persiste a disco).

Este modulo contiene las funciones puras (testeables sin Qt): construccion
del payload con historial, duracion del globo, fallback cuando Ollama no
responde, wrap de texto largo y config de chat. La ventanita flotante (caja
de texto) vive tambien aqui como una clase Qt fina que usa estas funciones;
se cablea desde DyberPet.py con pocos ganchos (doble clic / menu).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, List, Optional

try:
    from PySide6.QtCore import Qt, QTimer, Signal
    from PySide6.QtWidgets import QLineEdit
except Exception:  # pragma: no cover - entorno sin Qt (no deberia pasar en runtime real)
    Qt = None  # type: ignore
    QTimer = None  # type: ignore
    Signal = None  # type: ignore
    QLineEdit = object  # type: ignore


BRAIN_CONFIG_NAME = "mia_brain.json"

DEFAULT_CHAT_CONFIG = {
    "max_turns": 8,
    "num_predict": 90,
}

FALLBACK_MESSAGE = "My head is a little foggy right now... try again in a moment?"


def default_chat_config() -> dict:
    return dict(DEFAULT_CHAT_CONFIG)


def load_chat_config(brain_path: Path) -> dict:
    cfg = default_chat_config()
    brain_path = Path(brain_path)
    if not brain_path.is_file():
        return cfg
    try:
        data = json.loads(brain_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return cfg
    user_chat = data.get("chat") if isinstance(data, dict) else None
    if isinstance(user_chat, dict):
        cfg.update({k: user_chat[k] for k in cfg if k in user_chat})
    return cfg


# ---------------------------------------------------------------------------
# Payload con historial (recorte a max_turns)
# ---------------------------------------------------------------------------

def build_messages(system_prompt: str, history: List[dict], user_text: str,
                    max_turns: int = 8) -> List[dict]:
    """Arma la lista de mensajes para /api/chat: system + ultimos
    `max_turns` turnos (usuario+Mia, osea 2*max_turns mensajes) + el nuevo
    mensaje del usuario.
    """
    trimmed = history[-(max_turns * 2):] if max_turns > 0 else []
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(trimmed)
    messages.append({"role": "user", "content": user_text})
    return messages


# ---------------------------------------------------------------------------
# Duracion del globo: min 4s + 0.05s/char, tope 15s
# ---------------------------------------------------------------------------

def bubble_duration_s(text: str, per_char_s: float = 0.05, min_s: float = 4.0,
                       max_s: float = 15.0) -> float:
    by_length = len(text or "") * per_char_s
    return max(min_s, min(by_length, max_s))


# ---------------------------------------------------------------------------
# Pregunta a Mia con fallback cuando Ollama no responde
# ---------------------------------------------------------------------------

def ask_mia(chat_fn: Callable[[List[dict], dict], Optional[str]], system_prompt: str,
            history: List[dict], user_text: str, cfg: dict) -> str:
    """`chat_fn(messages, cfg) -> str|None` hace la llamada real a Ollama.
    Se inyecta para poder testear sin red. Devuelve el texto de Mia o el
    mensaje de fallback si `chat_fn` devuelve None.
    """
    max_turns = cfg.get("max_turns", DEFAULT_CHAT_CONFIG["max_turns"])
    messages = build_messages(system_prompt, history, user_text, max_turns)
    reply = chat_fn(messages, cfg)
    return reply if reply else FALLBACK_MESSAGE


# ---------------------------------------------------------------------------
# Wrap de texto largo (ancho maximo ~280px)
# ---------------------------------------------------------------------------

def wrap_text(text: str, measure_fn: Callable[[str], int], max_width_px: int = 280) -> List[str]:
    """Parte `text` en lineas que no superen `max_width_px` segun
    `measure_fn` (inyectado para no depender de QFontMetrics en los tests).
    Una palabra sola mas ancha que el limite queda en su propia linea tal
    cual (no se corta a la mitad).
    """
    words = text.split()
    if not words:
        return [text]

    lines: List[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if measure_fn(candidate) <= max_width_px:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


# ---------------------------------------------------------------------------
# Globo de Mia listo para register_bubble.emit (contrato-chat.txt punto 4):
# wrap_text + bubble_duration_s usados juntos en runtime.
# ---------------------------------------------------------------------------

def build_mia_chat_bubble(text: str, measure_fn: Callable[[str], int],
                           max_width_px: int = 280) -> dict:
    """Arma el dict que espera `register_bubble.emit` para un globo
    `mia_chat`: texto con saltos de linea segun `wrap_text` y `timeout`
    (segundos) segun `bubble_duration_s`, ambos en runtime (antes se
    importaban pero no se usaban, M1 del informe del revisor).
    """
    lines = wrap_text(text, measure_fn, max_width_px)
    return {
        "bubble_type": "mia_chat",
        "message": "\n".join(lines),
        "icon": None,
        "start_audio": None,
        "end_audio": None,
        "timeout": bubble_duration_s(text),
    }


# ---------------------------------------------------------------------------
# Memoria corta en proceso (no se persiste a disco; punto 6 del contrato)
# ---------------------------------------------------------------------------

class ChatHistory:
    """Guarda los ultimos `max_turns` turnos (usuario+Mia) en memoria."""

    def __init__(self, max_turns: int = 8):
        self.max_turns = max_turns
        self._messages: List[dict] = []

    def add_turn(self, user_text: str, mia_text: str) -> None:
        self._messages.append({"role": "user", "content": user_text})
        self._messages.append({"role": "assistant", "content": mia_text})
        cutoff = self.max_turns * 2
        if len(self._messages) > cutoff:
            self._messages = self._messages[-cutoff:]

    def as_list(self) -> List[dict]:
        return list(self._messages)

    def clear(self) -> None:
        self._messages = []


# ---------------------------------------------------------------------------
# Qt: caja de texto flotante (ganchos de pocas lineas desde DyberPet.py)
# ---------------------------------------------------------------------------

class ChatBox(QLineEdit):
    """Caja de texto pequena flotante, sin marco, pegada encima del pet.

    Enter -> emite `message_sent(str)`. Esc o 30 s sin escribir -> se
    cierra sola (`closed` signal).
    """

    message_sent = Signal(str) if Signal is not None else None
    closed = Signal() if Signal is not None else None

    IDLE_TIMEOUT_MS = 30000

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('MiniDraconia — Talk to Draconia')
        self.setPlaceholderText('Talk to Draconia — Enter to send, Esc to close')
        if Qt is not None:
            self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint)
            self.setAttribute(Qt.WA_TranslucentBackground, True)
            self.setStyleSheet(
                "QLineEdit { border-radius: 10px; padding: 6px 10px; "
                "background-color: rgba(30,30,40,230); color: white; }"
            )
        self._idle_timer = None
        if QTimer is not None:
            self._idle_timer = QTimer(self)
            self._idle_timer.setSingleShot(True)
            self._idle_timer.timeout.connect(self._on_idle_timeout)
            self.textChanged.connect(self._restart_idle_timer)
            self._restart_idle_timer()
        self.returnPressed.connect(self._on_return)

    def _restart_idle_timer(self):
        if self._idle_timer is not None:
            self._idle_timer.start(self.IDLE_TIMEOUT_MS)

    def _on_idle_timeout(self):
        self.closed.emit()
        self.close()

    def _on_return(self):
        text = self.text().strip()
        if text:
            self.message_sent.emit(text)
        self.clear()

    def keyPressEvent(self, event):
        if Qt is not None and event.key() == Qt.Key_Escape:
            self.closed.emit()
            self.close()
            return
        super().keyPressEvent(event)
