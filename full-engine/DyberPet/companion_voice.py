"""Voz en ingles (Kokoro, Emma) para la mascota en DyberPet.

Cuando `voice.enabled` es true, cada globo de la mascota
se lee en voz alta con Kokoro `bf_emma` (ingles britanico) y el idioma del
cerebro local se fuerza a ingles. La voz es opcional (apagada por defecto).

Este modulo contiene:
- Funciones puras de config/idioma (testeables sin Qt ni Kokoro real).
- `KokoroEngine`: carga perezosa del modelo onnx, sintesis a WAV temporal.
- `VoiceWorker`/`CompanionVoice`: hilo daemon + reproduccion con QSoundEffect, una
  sola voz a la vez (la nueva corta la anterior). Si Kokoro falla: sin voz,
  sin excepcion, el globo normal sigue.
"""
from __future__ import annotations

import json
import tempfile
import threading
import time
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


BRAIN_CONFIG_NAME = "companion_brain.json"

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
    """Lee `voice` de companion_brain.json; se relee en cada frase (contrato,
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
    """Lee `language` ("en"|"es") de companion_brain.json; default "es"."""
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
    convenia al perfil original (su voz es bf_emma/en-gb) pero rompia a cualquier otro
    perfil con voz propia en espanol (p. ej. ef_dora/es): hablaria en
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


def wav_seconds(wav_path, default: float = 0.0) -> float:
    """Duration of a PCM WAV with the standard library (the relay returns 24 kHz PCM16);
    `default` when the file cannot be read."""
    import wave
    try:
        with wave.open(str(wav_path), "rb") as wav:
            rate = wav.getframerate()
            return float(wav.getnframes()) / float(rate) if rate else default
    except (OSError, EOFError, wave.Error):
        return default


STALE_WAV_S = 3600.0    # voice WAVs older than this in the temp folder are leftovers


def sweep_stale_wavs(folder, max_age_s: float = STALE_WAV_S, now: Optional[float] = None) -> int:
    """Delete voice WAVs (`*.wav`) older than `max_age_s` in `folder` (left behind by a crash,
    a kill or a file the player still held). Returns how many were deleted; never raises."""
    folder = Path(folder)
    now = time.time() if now is None else now
    deleted = 0
    try:
        entries = list(folder.glob("*.wav"))
    except OSError:
        return 0
    for path in entries:
        try:
            if path.is_file() and now - path.stat().st_mtime > max_age_s:
                path.unlink()
                deleted += 1
        except OSError:
            continue
    return deleted


def _notify(callback, *args) -> None:
    """Optional observer callbacks (on_started/on_failed) never break the voice."""
    if callback is None:
        return
    try:
        callback(*args)
    except Exception:
        import logging
        logging.getLogger(__name__).exception("voice observer failed (ignored)")


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
            out_path = out_dir / f"voice-{uuid.uuid4().hex}.wav"
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

    def release(self) -> None:
        """Let go of the current file (on Windows a source still set keeps the WAV open and
        it cannot be deleted)."""
        if self._effect is not None and QUrl is not None and not self._effect.isPlaying():
            self._effect.setSource(QUrl())


class _SynthWorker(QObject if QObject is not object else object):
    """Corre KokoroEngine.synth() en un hilo daemon (nunca en el hilo de UI)."""

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


class CompanionVoice(QObject if QObject is not object else object):
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
        self._current_owned = True      # False: a stored voice-pack WAV, never deleted
        self._workers: dict = {}
        self._undeleted: list = []      # WAVs the OS would not delete yet (retried later)
        if tmp_dir is not None:
            # M3.1: leftovers of earlier runs (only in our own voice folder, never the system temp).
            sweep_stale_wavs(self._tmp_dir)

    @property
    def current_wav(self) -> Optional[str]:
        """The WAV playing now (deleted when it finishes)."""
        return self._current_wav

    def speak(self, text: str, cfg: dict) -> None:
        if not cfg.get("enabled", False):
            return
        # Una sola voz a la vez; cortar lo que estuviera sonando y
        # anular cualquier sintesis previa que llegue tarde.
        self._player.stop()
        self._cleanup_current_wav()
        self._token += 1
        token = self._token
        if QThread is None:
            return
        # Synthesis runs on a daemon thread (a relay TTS request can block for up to 30 s;
        # a QThread still running at quit aborts the process). The worker lives on the UI
        # thread, so `done` emitted from the daemon thread is delivered there, queued.
        worker = _SynthWorker(self._engine, text, cfg, self._tmp_dir, token)
        worker.done.connect(self._on_synth_done)
        self._workers[token] = worker
        self._volume = cfg.get("volume", DEFAULT_VOICE_CONFIG["volume"])
        threading.Thread(target=worker.run, name="companion-voice", daemon=True).start()

    def _on_synth_done(self, wav_path: str, token: int) -> None:
        self._workers.pop(token, None)
        if token != self._token:
            # Respuesta de una sintesis vieja (ya se pidio otra frase despues): descartar.
            if wav_path:
                self._delete(wav_path)
            return
        if not wav_path:
            self._log_cb("voz", "sintesis fallo") if getattr(self, "_log_cb", None) else None
            _notify(getattr(self, "on_failed", None))
            return
        self._play(wav_path, wav_seconds(wav_path), owned=True)

    def play_stored(self, wav_path, cfg: dict) -> bool:
        """D2.1: play a stored line's recorded WAV (optional voice pack) through the same playback
        as a synthesised one: one voice at a time (it cuts the current one and drops any late
        synthesis), `on_started(seconds)` when it starts, `on_failed()` when the file is missing
        or unreadable. The file belongs to the pack: it is never deleted. Never raises; True
        when it started."""
        if not cfg.get("enabled", False):
            return False
        try:
            self._player.stop()
            self._cleanup_current_wav()
            self._token += 1
            self._volume = cfg.get("volume", DEFAULT_VOICE_CONFIG["volume"])
            seconds = wav_seconds(wav_path, 0.0) if wav_path else 0.0
        except Exception:
            seconds = 0.0
        if seconds <= 0.0:
            if getattr(self, "_log_cb", None):
                self._log_cb("voice", "stored file unreadable")
            _notify(getattr(self, "on_failed", None))
            return False
        return self._play(str(wav_path), seconds, owned=False)

    def _play(self, wav_path: str, seconds: float, owned: bool) -> bool:
        """Start `wav_path` (synthesised: deleted when done; stored: kept) and report its
        duration to `on_started`: the pet talks for as long as it plays (M3)."""
        self._current_wav = wav_path
        self._current_owned = owned
        try:
            self._player.play_file(wav_path, self._volume)
        except Exception:
            self._current_wav = None
            self._current_owned = True
            _notify(getattr(self, "on_failed", None))
            return False
        if getattr(self, "_log_cb", None):
            self._log_cb("voz", "suena " + Path(wav_path).name)
        _notify(getattr(self, "on_started", None), seconds)
        return True

    def notify_playback_finished(self) -> None:
        """Llamado cuando el reproductor termina (en runtime real via
        `on_finished` del adaptador QSoundEffectPlayer); borra el WAV
        temporal (se borra al terminar)."""
        self._cleanup_current_wav()

    def _cleanup_current_wav(self) -> None:
        release = getattr(self._player, "release", None)
        if release is not None:
            try:
                release()
            except Exception:
                pass
        if self._current_wav:
            if self._current_owned:
                self._delete(self._current_wav)
            self._current_wav = None
            self._current_owned = True
        # Retry files a player still held last time.
        pending, self._undeleted = self._undeleted, []
        for path in pending:
            self._delete(path)

    def _delete(self, path) -> None:
        try:
            Path(path).unlink(missing_ok=True)
        except OSError:
            if len(self._undeleted) < 64:
                self._undeleted.append(str(path))

    def cancel(self) -> None:
        """Stop the line playing now and drop any synthesis still running (its late result
        is discarded and its WAV deleted)."""
        self._player.stop()
        self._token += 1
        self._cleanup_current_wav()

    def shutdown(self) -> None:
        """Stop playback and invalidate any synthesis still running (its late result
        is discarded and its WAV deleted). Never waits on a synthesis thread."""
        self.cancel()
