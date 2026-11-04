"""Offline Draconia reactions. No synthesis, network, mood writes or physics."""
from __future__ import annotations

import json
import random
import time
import wave
from pathlib import Path


class Reactions:
    def __init__(self, note_dir, *, bubble=lambda text: None,
                 play=lambda path, volume: None, is_playing=lambda: False, rng=None):
        self.note_dir = Path(note_dir).resolve()
        try:
            manifest = json.loads((self.note_dir / 'manifest.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            manifest = {}
        self.events = manifest.get('events', {})
        self.cooldown = max(3.0, float(manifest.get('cooldown_s', 3)))
        self.bubble, self.play, self.is_playing = bubble, play, is_playing
        self.rng = rng or random.Random()
        self.last_visual = {}
        self.last_spoken = {}
        self.last_audio = None
        self.last_time = float('-inf')
        self.drag_seen = False
        self.stop = lambda: None

    def begin_gesture(self):
        self.drag_seen = False

    def drag(self, **kwargs):
        if self.drag_seen:
            return
        self.drag_seen = True
        self.react('drag', **kwargs)

    def _audio_path(self, entry):
        if not entry.get('approved') or not entry.get('audio'):
            return None
        path = (self.note_dir / entry['audio']).resolve()
        if not path.is_relative_to(self.note_dir / 'voice') or not path.is_file():
            return None
        try:
            with wave.open(str(path), 'rb') as wav:
                if wav.getcomptype() != 'NONE' or not wav.getnframes():
                    return None
        except (OSError, EOFError, wave.Error):
            return None
        return path

    def react(self, event, mood='content', available=(), *, now=None, volume=1.0, muted=False):
        now = time.monotonic() if now is None else now
        entries = [e for e in self.events.get(event, [])
                   if not e.get('pose') or e['pose'] in available]
        if not entries:
            return None
        relevant = [e for e in entries if mood in e.get('moods', [])]
        visual = relevant or entries
        visual = [e for e in visual if e.get('pose') != self.last_visual.get(event)] or visual
        chosen = self.rng.choice(visual)
        self.last_visual[event] = chosen.get('pose')
        # Visuals remain responsive; only balloons/audio share a global gate.
        if now - self.last_time >= self.cooldown and not self.is_playing():
            spoken = [e for e in entries if e != self.last_spoken.get(event)] or entries
            # Match the selected visual unless that would repeat the last spoken variant.
            entry = chosen if chosen in spoken else self.rng.choice(spoken)
            self.last_time = now
            self.last_spoken[event] = entry
            self.bubble(entry['text'])
            path = self._audio_path(entry)
            if path == self.last_audio:
                alternatives = [(e, self._audio_path(e)) for e in spoken]
                alternatives = [(e, p) for e, p in alternatives if p and p != self.last_audio]
                path = self.rng.choice(alternatives)[1] if alternatives else path
            if path and not muted and volume > 0:
                self.play(path, max(0.0, min(1.0, float(volume))))
                self.last_audio = path
        return chosen.get('pose')


def install_broom(pet_conf):
    """Representation only; the native drop/landing engine keeps its gravity."""
    broom = pet_conf.act_dict.get('climb')
    if broom is not None:
        pet_conf.fall = pet_conf.prefall = broom


def make_qt_reactions(widget, note_dir):
    from PySide6.QtCore import QUrl
    from PySide6.QtMultimedia import QSoundEffect
    effect = QSoundEffect(widget)
    effect.setLoopCount(1)
    import os
    effect.setMuted(os.environ.get('MINIDRACONIA_MUTE') == '1')

    def play(path, volume):
        effect.setVolume(volume)
        effect.setSource(QUrl.fromLocalFile(str(path)))
        effect.play()

    controller = Reactions(note_dir, bubble=widget._draconia_bubble,
                           play=play, is_playing=effect.isPlaying)
    controller.effect = effect
    controller.stop = effect.stop
    return controller
