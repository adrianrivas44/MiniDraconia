"""Draconia's lines on the pet window: events, typed chat and goodbye.

`PetWidget` inherits `ConversationMixin`. The brain (`DyberPet/brain_client.py`) never raises;
here every reply becomes one bubble plus her talking body (`DyberPet/pet_life.py`).

D2.1 (owner: stored lines are repeated, only AI-written lines spend quota):
  - every pet event (greet, pat, pinch, touch_body, drag, fall, idle, chatter, bye) answers from
    her stored pool in every mode and never starts a request;
  - only typed chat goes to the active brain (self-hosted relay > own AI); when it fails, or
    offline, a stored `chat` line answers;
  - a stored line plays its recorded WAV when the optional voice pack has it
    (`DyberPet/voice_pack.py`), through the same playback and sync as relay voice.

Touch, drag and fall keep the v1 reaction controller (`draconia_reactions.py`): it picks the
pose from the reaction manifest and gates lines by its cooldown. The line itself:
  - an approved prerecorded clip (manifest `approved: true`) plays with its own text, in sync,
    in the own-key and offline modes, as in D2 (in relay mode her stored line answers, so a
    copy with a relay never mixes two voices);
  - otherwise her stored line for that event key.

Pet attributes used: _conv_brain, _conv_calls, mia_chat_history, _emit_mia_bubble(text, voice, wav),
_mia_play_pose(pose), _mia_note_mood_event(kind, **meta), _mia_log(kind, text), and when
present talk_controller, pet_conf, _draconia_reactions.
"""
import logging
import os
from typing import Optional

import DyberPet.settings as settings

# Reaction-manifest events -> conversation event keys (data/draconia_lines_en.json).
REACTION_EVENT_KEYS = {'head': 'pat', 'cheek': 'pinch', 'body': 'touch_body', 'drag': 'drag', 'fall': 'fall'}


class ConversationMixin:
    # --- setup ------------------------------------------------------------------------------
    def _conv_setup(self, brain=None) -> None:
        """Create the brain once per pet load; a self-hosted relay is health-checked in the
        background (logged only: events never wait for it)."""
        from DyberPet.brain_client import BackgroundCalls, ConversationBrain, DailyCounter
        if brain is None:
            from DyberPet.brain import load_own_key
            from DyberPet.paths import user_root
            brain = ConversationBrain(own_key_loader=load_own_key,
                                      counter=DailyCounter(user_root() / 'own_key_usage.json'))
        self._conv_brain = brain
        if getattr(self, '_conv_calls', None) is None:
            self._conv_calls = BackgroundCalls(self)
        self._conv_bye_shown = False
        try:
            mode = brain.mode()
            self._mia_log('mode', mode)
            if mode == 'relay':
                self._conv_calls.submit(brain.check_relay, lambda ok: self._mia_log('relay', 'health %s' % ok))
        except Exception:
            logging.getLogger(__name__).exception('_conv_setup failed (ignored)')

    def _conv_mode(self) -> str:
        brain = getattr(self, '_conv_brain', None)
        try:
            return brain.mode() if brain is not None else 'offline'
        except Exception:
            return 'offline'

    def _conv_has_voice_pack(self) -> bool:
        """True when an optional voice pack with at least one line is installed."""
        brain = getattr(self, '_conv_brain', None)
        try:
            return bool(brain.has_voice_pack()) if brain is not None else False
        except Exception:
            return False

    # --- events -----------------------------------------------------------------------------
    def _conv_event(self, key: str, doing: Optional[str] = None) -> None:
        """Interaction event -> one stored line, or nothing when the event rate limit skips it.
        Never a request, in any mode (D2.1). `doing` (what she is doing, from the chatter
        caller) only described her action to a remote brain and is no longer used."""
        try:
            brain = self._conv_brain
            if brain.plan(key) == 'skip':
                self._mia_log('line', 'skip ' + key)
            else:
                self._conv_show_reply(brain.offline_reply(key))
        except Exception:
            logging.getLogger(__name__).exception('_conv_event failed (ignored)')

    def _conv_show_reply(self, reply, voice: Optional[bool] = None) -> None:
        """Bubble with the line, then the pose for her emotion. A line about her tea shows `tea`.
        A relay reply (typed chat) is read by the relay voice; a stored line plays its pack WAV
        when it has one; `voice=False` shows it unvoiced. The log keeps source, key, emotion,
        error kind and whether a stored voice was found, never the text."""
        if reply is None or not getattr(reply, 'text', ''):
            return
        from DyberPet.talk_controller import tea_pose
        act_dict = getattr(getattr(self, 'pet_conf', None), 'act_dict', None)
        pose = tea_pose(reply.text, reply.pose, act_dict.keys() if act_dict is not None else None)
        notice = getattr(reply, 'notice', None)
        relay = reply.source == 'relay'
        # A notice changes the bubble text, so the recorded line would not match it: unvoiced.
        wav = getattr(reply, 'wav', None) if not relay and not notice and voice is not False else None
        self._mia_log('line', '%s %s %s %s%s' % (reply.source, reply.key, reply.emotion, reply.error or '',
                                                 ' stored-voice' if wav else ''))
        text = reply.text if not notice else '%s %s' % (notice, reply.text)
        self._emit_mia_bubble(text, voice=relay if voice is None else voice, wav=wav)
        self._life_begin_talk(pose)

    # --- typed chat -------------------------------------------------------------------------
    def _conv_chat(self, text: str) -> None:
        self._mia_play_pose('think')
        brain = self._conv_brain
        if brain.plan('chat') != 'remote':
            self._conv_on_chat_reply(text, brain.offline_or_cap_reply('chat'))
            return
        history = self.mia_chat_history.as_list()
        self._conv_calls.submit(lambda: brain.remote_chat(text, history),
                                lambda reply: self._conv_on_chat_reply(text, reply))

    def _conv_on_chat_reply(self, user_text: str, reply) -> None:
        if reply is None:
            reply = self._conv_brain.offline_reply('chat', 'error')
        if reply.source in ('relay', 'own_key'):
            # Only a real conversation is sent back as history (kept in memory only).
            self.mia_chat_history.add_turn(user_text, reply.text)
        self._conv_show_reply(reply)
        self._mia_note_mood_event('chat')

    # --- goodbye ----------------------------------------------------------------------------
    def _conv_send_bye(self) -> None:
        """Goodbye at quit: a stored line, at once (never a request). Never voiced: quit stops
        the voice before a recorded goodbye could end."""
        self._conv_bye_shown = False
        brain = self._conv_brain
        brain.plan('bye')                  # greet and bye always answer; keeps the event slot rule
        self._conv_on_bye_reply(brain.offline_reply('bye'))

    def _conv_on_bye_reply(self, reply) -> None:
        if reply is None or getattr(self, '_conv_bye_shown', False):
            return
        self._conv_bye_shown = True
        self._conv_show_reply(reply, voice=False)

    def _conv_finish_bye(self) -> bool:
        """True when no goodbye was shown yet and a stored one was shown now."""
        if getattr(self, '_conv_bye_shown', False):
            return False
        self._conv_on_bye_reply(self._conv_brain.offline_reply('bye', 'timeout'))
        return True

    def _mia_on_absence_return(self, absence_s: float) -> None:
        """Director callback when the user comes back; she reacts to a long absence."""
        self._mia_note_mood_event('zero_returns', absence_s=absence_s)
        from DyberPet.brain_client import IDLE_EVENT_AFTER_S
        if absence_s >= IDLE_EVENT_AFTER_S and getattr(self, '_conv_brain', None) is not None:
            self._conv_event('idle')

    # --- touch / drag / fall reactions ------------------------------------------------------
    def _conv_reaction_line(self, event: str, entry: dict, audio_path) -> None:
        """Reaction controller hook: the line of a touch/drag/fall reaction it let through.
        `audio_path` is set only for an approved clip that may be heard now."""
        try:
            if audio_path and self._conv_mode() != 'relay':
                self._conv_prerecorded(entry.get('text', ''), audio_path)
                return
            key = REACTION_EVENT_KEYS.get(event)
            if key is not None:
                self._conv_event(key)
        except Exception:
            logging.getLogger(__name__).exception('_conv_reaction_line failed (ignored)')

    def _conv_prerecorded(self, text: str, path) -> None:
        """An approved prerecorded clip: its own text in the bubble, the clip playing, and her
        mouth following the clip (duration and pauses of the WAV)."""
        if not text:
            return
        self._mia_log('line', 'prerecorded %s' % os.path.basename(str(path)))
        self._emit_mia_bubble(text, voice=False, wav=None)
        controller = getattr(self, '_draconia_reactions', None)
        if controller is not None:
            controller.play(path, max(0.0, min(1.0, float(getattr(settings, 'volume', 1.0) or 0.0))))
        talk = getattr(self, 'talk_controller', None)
        if talk is not None and talk.active:
            from DyberPet.mia_voice import wav_seconds
            from DyberPet.talk_controller import wav_mouth_pauses
            talk.voice_started(wav_seconds(path), wav_mouth_pauses(path))
