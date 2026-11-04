"""Voz en ingles (Kokoro, Emma) para Mia en DyberPet.

docs/contrato-voz-en.md: cuando `voice.enabled` es true, cada globo de Mia
se lee en voz alta con Kokoro `bf_emma` (ingles britanico) y el idioma del
cerebro local se fuerza a ingles. La voz es opcional (apagada por defecto).

Este modulo contiene:
- Funciones puras de config/idioma (testeables sin Qt ni Kokoro real).
- `KokoroEngine`: carga perezosa del modelo onnx, sintesis a WAV temporal.
- `VoiceWorker`/`MiaVoice`: QThread + reproduccion con QSoundEffect, una
  sola voz a la vez (la nueva corta la anterior). Si Kokoro falla: sin voz,
  sin excepcion, el globo normal sigue.
"""
from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from typing import Callable, Optional

try:
    from PySide6.QtCore import QObject, QThread, QUrl, Signal
    from PySide6.QtMultimedia import QSoundEffect
except Exception:  # pragma: no cover - entorno sin Qt (no deberia pasar en runtime real)
    QObject = object  # type: ignore
    QThread = None  # type: ignore
    QUrl = None  # type: ignore
    Signal = None  # type: ignore
    QSoundEffect = None  # type: ignore


BRAIN_CONFIG_NAME = "mia_brain.json"

DEFAULT_VOICE_CONFIG = {
    "enabled": False,
    "engine": "kokoro",
    "voice": "bf_emma",
    "lang": "en-gb",
    "speed": 1.0,
    "volume": 0.8,
}

DEFAULT_LANGUAGE = "es"


def default_voice_config() -> dict:
    return dict(DEFAULT_VOICE_CONFIG)


def load_voice_config(brain_path) -> dict:
    """Lee `voice` de mia_brain.json; se relee en cada frase (contrato,
    seccion Tecnica). Si el archivo no existe o no trae `voice`, defaults."""
    cfg = default_voice_config()
    brain_path = Path(brain_path)
    if not brain_path.is_file():
        return cfg
    try:
        data = json.loads(brain_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return cfg
    user_voice = data.get("voice") if isinstance(data, dict) else None
    if isinstance(user_voice, dict):
        cfg.update({k: user_voice[k] for k in cfg if k in user_voice})
    return cfg


def load_language(brain_path) -> str:
    """Lee `language` ("en"|"es") de mia_brain.json; default "es"."""
    brain_path = Path(brain_path)
    if not brain_path.is_file():
        return DEFAULT_LANGUAGE
    try:
        data = json.loads(brain_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_LANGUAGE
    if not isinstance(data, dict):
        return DEFAULT_LANGUAGE
    lang = data.get("language")
    return lang if lang in ("en", "es") else DEFAULT_LANGUAGE


def effective_language(configured_language: str, voice_enabled: bool,
                        voice_lang: str | None = None) -> str:
    """Punto 2 del contrato: con voz activada se fuerza el idioma de ESA voz.

    Correccion FAIL t_ea577267 (B1): antes se forzaba "en" a secas, lo que
    convenia a Mia (su voz es bf_emma/en-gb) pero rompia a cualquier otro
    perfil con voz propia en espanol (Draconia: ef_dora/es): hablaria en
    ingles aunque su voz sonara en espanol. `voice_lang` (p.ej.
    `voice_cfg["lang"]`, "en-gb"/"es") decide: empieza con "en" -> "en",
    cualquier otra cosa -> "es". Sin `voice_lang` (llamadas viejas/tests)
    se conserva el comportamiento de siempre: fuerza "en" a secas.
    """
    if not voice_enabled:
        return configured_language
    if voice_lang:
        return "en" if voice_lang.lower().startswith("en") else "es"
    return "en"


# ---------------------------------------------------------------------------
# Sintesis: carga perezosa del modelo onnx, WAV temporal en data/tmp/
# ---------------------------------------------------------------------------

def wav_duration_s(wav_path) -> float:
    """Duracion en segundos de un WAV leido con soundfile."""
    import soundfile as sf
    info = sf.info(str(wav_path))
    return float(info.frames) / float(info.samplerate)


class KokoroEngine:
    """Motor Kokoro-onnx, CPU solamente. El modelo se carga en el primer
    `synth()` y se queda en memoria (contrato, seccion Tecnica). Si el
    modelo/voces no estan en disco o falla cualquier paso de la sintesis,
    `synth()` devuelve None (nunca lanza): el llamador sigue con el globo
    normal, sin voz."""

    def __init__(self, model_path, voices_path):
        self.model_path = Path(model_path)
        self.voices_path = Path(voices_path)
        self._kokoro = None
        self._load_failed = False

    def _ensure_loaded(self):
        if self._kokoro is not None or self._load_failed:
            return
        if not self.model_path.is_file() or not self.voices_path.is_file():
            self._load_failed = True
            return
        try:
            from kokoro_onnx import Kokoro
            self._kokoro = Kokoro(str(self.model_path), str(self.voices_path))
        except Exception:
            self._load_failed = True

    def synth(self, text: str, voice: str, lang: str, speed: float,
              out_dir) -> Optional[str]:
        """Sintetiza `text` a un WAV nuevo en `out_dir`. Devuelve la ruta
        (str) o None si el modelo falta o la sintesis falla por cualquier
        razon (nunca excepcion)."""
        self._ensure_loaded()
        if self._kokoro is None:
            return None
        try:
            import soundfile as sf
            samples, sample_rate = self._kokoro.create(
                text, voice=voice, speed=speed, lang=lang
            )
            out_dir = Path(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"mia-voice-{uuid.uuid4().hex}.wav"
            sf.write(str(out_path), samples, sample_rate)
            return str(out_path)
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Reproduccion real con QSoundEffect (adaptador fino, inyectable en tests)
# ---------------------------------------------------------------------------

class QSoundEffectPlayer:
    """Envoltorio fino sobre QSoundEffect: una instancia reutilizable,
    volumen 0-1, notifica fin de reproduccion via `on_finished`."""

    def __init__(self, on_finished: Optional[Callable[[], None]] = None):
        self._effect = QSoundEffect() if QSoundEffect is not None else None
        self._on_finished = on_finished
        if self._effect is not None:
            self._effect.playingChanged.connect(self._on_playing_changed)

    def _on_playing_changed(self):
        if self._effect is not None and not self._effect.isPlaying() and self._on_finished:
            self._on_finished()

    def play_file(self, path: str, volume: float) -> None:
        if self._effect is None:
            return
        self._effect.setSource(QUrl.fromLocalFile(str(path)))
        self._effect.setVolume(max(0.0, min(1.0, volume)))
        self._effect.play()

    def stop(self) -> None:
        if self._effect is not None:
            self._effect.stop()


class _SynthWorker(QObject if QObject is not object else object):
    """Corre KokoroEngine.synth() en un QThread (nunca en el hilo de UI,
    contrato-voz-en.md seccion Tecnica)."""

    done = Signal(str, object) if Signal is not None else None  # (wav_path|None, token)

    def __init__(self, engine: KokoroEngine, text: str, cfg: dict, tmp_dir, token):
        super().__init__()
        self._engine = engine
        self._text = text
        self._cfg = cfg
        self._tmp_dir = tmp_dir
        self._token = token

    def run(self):
        wav_path = self._engine.synth(
            self._text,
            voice=self._cfg.get("voice", DEFAULT_VOICE_CONFIG["voice"]),
            lang=self._cfg.get("lang", DEFAULT_VOICE_CONFIG["lang"]),
            speed=self._cfg.get("speed", DEFAULT_VOICE_CONFIG["speed"]),
            out_dir=self._tmp_dir,
        )
        self.done.emit(wav_path or "", self._token)


class MiaVoice(QObject if QObject is not object else object):
    """Orquesta sintesis (hilo) + reproduccion (QSoundEffect), una sola voz
    a la vez: `speak()` de nuevo corta la reproduccion en curso y descarta
    cualquier sintesis vieja que termine tarde (token incremental). El WAV
    temporal en `tmp_dir` se borra cuando termina de sonar."""

    def __init__(self, engine: KokoroEngine, player=None, tmp_dir=None):
        if QObject is not object:
            super().__init__()
        self._engine = engine
        self._player = player if player is not None else QSoundEffectPlayer(on_finished=self.notify_playback_finished)
        self._tmp_dir = Path(tmp_dir) if tmp_dir is not None else Path(tempfile.gettempdir())
        self._token = 0
        self._current_wav: Optional[str] = None
        self._thread: Optional["QThread"] = None
        self._worker = None
        self._pending_threads: list = []

    def speak(self, text: str, cfg: dict) -> None:
        if not cfg.get("enabled", False):
            return
        # Mia: una sola voz a la vez; cortar lo que estuviera sonando y
        # anular cualquier sintesis previa que llegue tarde.
        self._player.stop()
        self._cleanup_current_wav()
        self._token += 1
        token = self._token
        if QThread is None:
            return
        thread = QThread()
        worker = _SynthWorker(self._engine, text, cfg, self._tmp_dir, token)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.done.connect(self._on_synth_done)
        worker.done.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._forget_thread(thread))
        self._thread = thread
        self._worker = worker
        self._pending_threads.append(thread)
        self._volume = cfg.get("volume", DEFAULT_VOICE_CONFIG["volume"])
        thread.start()

    def _forget_thread(self, thread) -> None:
        if thread in self._pending_threads:
            self._pending_threads.remove(thread)

    def _on_synth_done(self, wav_path: str, token: int) -> None:
        if token != self._token:
            # Respuesta de una sintesis vieja (ya se pidio otra frase despues): descartar.
            if wav_path:
                try:
                    Path(wav_path).unlink(missing_ok=True)
                except OSError:
                    pass
            return
        if not wav_path:
            self._log_cb("voz", "sintesis fallo") if getattr(self, "_log_cb", None) else None
            return
        self._current_wav = wav_path
        self._player.play_file(wav_path, self._volume)
        if getattr(self, "_log_cb", None):
            self._log_cb("voz", "suena " + Path(wav_path).name)

    def notify_playback_finished(self) -> None:
        """Llamado cuando el reproductor termina (en runtime real via
        `on_finished` del adaptador QSoundEffectPlayer); borra el WAV
        temporal (contrato-voz-en.md: 'se borra al terminar')."""
        self._cleanup_current_wav()

    def _cleanup_current_wav(self) -> None:
        if self._current_wav:
            try:
                Path(self._current_wav).unlink(missing_ok=True)
            except OSError:
                pass
            self._current_wav = None

    def shutdown(self) -> None:
        self._player.stop()
        for thread in list(self._pending_threads):
            thread.quit()
            thread.wait(2000)
        self._cleanup_current_wav()
