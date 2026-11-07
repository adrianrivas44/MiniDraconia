"""She visibly talks while she says a line (M3, M3.1).

Owner: "when she talks it must show that she is talking". Whenever a line appears (typed chat,
interaction events, spontaneous chatter, offline lines):

1. she stops what she is doing (walking included): the first pose request pauses the engine's
   random animation, and `PetWidget.resume_animation` keeps it paused while a line is active;
2. (M3.1) a voiced line waits for its voice: she shows `think` and the bubble is held until the
   WAV starts playing (`voice_started`), at most `VOICE_WAIT_S`; after that the line goes ahead
   without voice. An unvoiced line never waits;
3. if the line carries an emotion pose, she plays one full clip of it (M3.3: that clip's real
   length, `clip_s`; `EMOTE_S` only when the pet cannot say), capped by the line: if the line
   ends first she does not talk at all, and the clip still plays to its end (phase 'trail');
4. then she loops `talk` until the voice WAV ends (its duration, reported when playback starts)
   or, without voice, while the bubble is visible. (M3.2) `talk` is one seamless loop: the pet
   plays it (and the closed-mouth pause) as a looping clip (`LOOP_POSES`) that goes on from its
   frame 0 at its end, so it is never restarted mid-line and never passes through `default`.
   While the voice is silent for at least `MIN_PAUSE_S` (0.8 s, RMS envelope of the WAV,
   `mouth_pauses`) she shows the closed-mouth stand (`PAUSE_POSE`) and goes back to `talk` when
   the speech does; a mouth switch is never undone within `MOUTH_HOLD_S` (hysteresis);
5. then the talk clip is stopped at once (the mouth never moves without voice), she returns to
   her stand and normal behaviour resumes. An emotion clip is never stopped by the line's end.

(M3.3) A line never cuts a clip mid-way: when it arrives the pet asks the clip being played to
finish (modules.FINISH_CLIP_S rule: its end within 2.5 s, else its next natural point, else
2.5 s) and `body_busy()` is True until it has. Meanwhile nothing is played (not even `think`);
the voice wait, bubble and voice go on as in M3.1, only the body joins late. `BODY_WAIT_S` is a
safety bound on that wait.

Drag and fall are never interrupted (nor a wall climb): while `blocked`, nothing is played and
the clock keeps running; if time is left when she is free again, she talks for the rest.

(M3.2) A line that mentions her tea, a sip or her cup shows `tea` (her teacup clip) as its
emotion pose (`tea_pose`).

Pure state with an injected clock; the pet calls `tick()` from its own 40 ms timer (M3.3).
"""
import math
import re
import sys
import time
from array import array
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

EMOTE_S = 4.0            # only when the pet cannot report the emotion clip's real length (clip_s)
BODY_WAIT_S = 3.0        # M3.3: never wait longer than this for a clip to finish (2.5 s rule + margin)
TALK_POSE = 'talk'
THINK_POSE = 'think'     # waiting for the voice
PAUSE_POSE = 'default'   # the role's 'default' action is the closed-mouth stand clip
LOOP_POSES = (TALK_POSE, PAUSE_POSE)   # played as looping clips while a line lasts (M3.2)
TEA_POSE = 'tea'         # her teacup clip
MAX_BUBBLE_S = 60.0      # safety clamp: a line never holds her longer than this without voice
VOICE_WAIT_S = 2.5       # longest wait for the voice before the line goes ahead unvoiced

# Mouth pauses (relay voice: PCM16, 24 kHz, mono).
ENVELOPE_WINDOW_S = 0.020
MIN_PAUSE_S = 0.8            # M3.2: shorter silences keep the talk loop going
MOUTH_HOLD_S = 0.4           # M3.2: no switch back within this time of the last mouth switch
SILENCE_FLOOR = 300          # RMS below this (int16 units, about -40 dBFS) is always silence
SILENCE_REL = 0.10           # ... and below 10 % of the loudest window


class TalkController:
    def __init__(self, play_pose: Callable[[str], None], stop_pose: Callable[[Optional[str]], None],
                 now_fn: Callable[[], float] = time.monotonic, emote_s: float = EMOTE_S,
                 on_release: Optional[Callable[[bool], None]] = None,
                 clip_s: Optional[Callable[[str], Optional[float]]] = None,
                 body_busy: Optional[Callable[[], bool]] = None):
        self._play = play_pose
        self._stop = stop_pose
        self._now = now_fn
        self._on_release = on_release
        self._clip_s = clip_s                # seconds of one full clip of a pose (M3.3)
        self._body_busy = body_busy          # a clip is finishing before the line's poses (M3.3)
        self.emote_s = float(emote_s)
        self.active = False
        self.phase = None            # ['wait' ->] 'start' -> 'emote' -> 'talk'; 'trail' (M3.3)
        self.pose = None
        self.playing = None          # pose this controller last started
        self._emote_until = 0.0
        self._bubble_s = 0.0
        self._bubble_until = 0.0
        self._wait_until = 0.0
        self._voice = 'none'         # 'none' | 'pending' | 'playing'
        self._voice_until = 0.0
        self._pauses: List[Tuple[float, float]] = []
        self._mouth_since = float('-inf')   # when the mouth (talk <-> pause) last switched
        self._body_until = 0.0       # M3.3: wait for a finishing clip at most until then

    # -- events --------------------------------------------------------------------------
    def say(self, bubble_s: float, voiced: bool = False, pose: Optional[str] = None) -> None:
        """A new line is on screen for `bubble_s` seconds; `voiced` when a voice was requested."""
        now = self._now()
        self.active = True
        self.phase = 'start'
        self._bubble_s = clamp_bubble_s(bubble_s)
        self._bubble_until = now + self._bubble_s
        self._voice = 'pending' if voiced else 'none'
        self._voice_until = 0.0
        self._pauses = []
        self._body_until = now + BODY_WAIT_S
        self._disown_clip()
        self.set_pose(pose)

    def wait_for_voice(self, bubble_s: float, pose: Optional[str] = None,
                       wait_s: float = VOICE_WAIT_S) -> None:
        """A voiced line: hold it (she thinks) until the voice starts, at most `wait_s`.
        `on_release(voiced)` tells the pet when to show the bubble."""
        now = self._now()
        self.active = True
        self.phase = 'wait'
        self.pose = pose if pose and pose != TALK_POSE else None
        self._bubble_s = clamp_bubble_s(bubble_s)
        self._bubble_until = now + max(0.0, float(wait_s)) + self._bubble_s
        self._wait_until = now + max(0.0, float(wait_s))
        self._voice = 'pending'
        self._voice_until = 0.0
        self._pauses = []
        self._body_until = now + BODY_WAIT_S
        self._disown_clip()

    def _disown_clip(self) -> None:
        """M3.3: an emotion clip of the previous line is not this line's to stop: the pet lets
        it finish. Only talk, its pause and think carry over (talk goes on without a restart)."""
        if self.playing not in LOOP_POSES + (THINK_POSE,):
            self.playing = None

    @property
    def waiting(self) -> bool:
        return self.active and self.phase == 'wait'

    def set_pose(self, pose: Optional[str]) -> None:
        """Emotion pose of the current line (before she has started showing it)."""
        if not self.active or self.phase not in ('start', 'wait'):
            return
        self.pose = pose if pose and pose != TALK_POSE else None

    def hold_body(self) -> None:
        """A touch reaction started during the line: its clip may finish too (M3.3)."""
        if self.active:
            self._body_until = self._now() + BODY_WAIT_S

    def voice_started(self, duration_s: float, pauses: Iterable[Tuple[float, float]] = ()) -> None:
        """The WAV started playing: she talks until it ends, even after the bubble is gone.
        `pauses`: (start, end) seconds into the WAV where the voice is silent."""
        now = self._now()
        if self.waiting:
            self._release(voiced=True)
        elif not self.active:
            if self._voice != 'pending':
                return
            # The bubble already ended while the voice was being synthesised: talk again.
            self.active, self.phase, self.pose = True, 'start', None
            self._body_until = now + BODY_WAIT_S
        self._voice = 'playing'
        self._voice_until = now + max(0.0, float(duration_s))
        self._pauses = [(now + float(a), now + float(b)) for a, b in pauses
                        if float(b) - float(a) >= MIN_PAUSE_S - 1e-9]

    def voice_failed(self) -> None:
        if self.waiting:
            self._release(voiced=False)
        if self._voice == 'pending':
            self._voice = 'none'

    def cancel(self) -> None:
        if self.active:
            self._finish()

    # -- clock ---------------------------------------------------------------------------
    @property
    def ends_at(self) -> float:
        if self._voice == 'playing':
            return self._voice_until
        return self._bubble_until

    def in_pause(self, now: Optional[float] = None) -> bool:
        if self._voice != 'playing':
            return False
        now = self._now() if now is None else now
        return any(a <= now < b for a, b in self._pauses)

    def tick(self, state: str = 'default', blocked: bool = False) -> None:
        """`state`: the engine interaction ('default' when no clip is playing);
        `blocked`: dragged, falling or climbing — never interrupted."""
        if not self.active:
            return
        now = self._now()
        if self.phase == 'trail':
            # M3.3: the line is over; her emotion clip plays to its end, then normal life.
            if blocked or state == 'default' or now >= self._emote_until:
                if not blocked and self._voice == 'playing' and now < self._voice_until:
                    self.phase = 'talk'          # a late voice still plays: she talks it
                    self._start(self._mouth(now), state)
                else:
                    self._finish(blocked)
            return
        busy = self.body_busy(now)
        if self.phase == 'wait':
            if now >= self._wait_until:
                self._release(voiced=False)     # no voice in time: go ahead without it
            elif not blocked and not busy and (self.playing != THINK_POSE or state == 'default'):
                self._start(THINK_POSE)         # M3.3: only when no clip is finishing
                return
            else:
                return
        if now >= self.ends_at:
            self._end_line(now, state, blocked)
            return
        if blocked:
            self.playing = None          # drag/fall/climb replaced her clip: start it again after
            return
        if busy:
            return                       # M3.3: the clip playing finishes first
        if self.phase == 'start':
            if self.pose:
                self.phase = 'emote'
                self._start(self.pose)
                self._emote_until = now + self._emote_len(self.pose)
            else:
                self.phase = 'talk'
                self._start(self._mouth(now), state)
        elif self.phase == 'emote':
            if now >= self._emote_until or state == 'default':
                self.phase = 'talk'
                self._start(self._mouth(now), state)
        elif self.phase == 'talk':
            mouth = self._mouth(now)
            # A pause began/ended, or something else stopped the clip: (re)start it. The talk
            # clip itself loops in the engine (LOOP_POSES), so its end is not a restart.
            if mouth != self.playing or state == 'default':
                self._start(mouth)

    def body_busy(self, now: Optional[float] = None) -> bool:
        """True while a clip finishes before the line's poses (at most until `_body_until`)."""
        if self._body_busy is None:
            return False
        now = self._now() if now is None else now
        if now >= self._body_until:
            return False
        try:
            return bool(self._body_busy())
        except Exception:
            return False

    def _emote_len(self, pose: str) -> float:
        """Seconds of one full clip of the emotion pose."""
        try:
            seconds = self._clip_s(pose) if self._clip_s is not None else None
        except Exception:
            seconds = None
        return float(seconds) if seconds and seconds > 0 else self.emote_s

    def _end_line(self, now: float, state: str, blocked: bool) -> None:
        """The line ends. Talk stops at once; an emotion clip still playing is never cut."""
        if not blocked and self.phase == 'emote' and self.pose and self.playing == self.pose \
                and state != 'default' and now < self._emote_until:
            self.phase = 'trail'
            self._pauses = []
            if self._voice == 'playing':
                self._voice = 'none'
            return
        self._finish(blocked)

    def _mouth(self, now: float) -> str:
        wanted = PAUSE_POSE if self.in_pause(now) else TALK_POSE
        if self.playing in LOOP_POSES and wanted != self.playing \
                and now - self._mouth_since < MOUTH_HOLD_S - 1e-9:
            return self.playing          # hysteresis: too soon after the last mouth switch
        return wanted

    def _release(self, voiced: bool) -> None:
        """End of the wait: the line starts now (bubble shown by the pet)."""
        now = self._now()
        self.phase = 'start'
        self._bubble_until = now + self._bubble_s
        if not voiced:
            self._voice = 'none'
        if self._on_release is not None:
            self._on_release(voiced)

    def _start(self, pose: str, state: Optional[str] = None) -> None:
        if pose == self.playing and pose in LOOP_POSES and state not in (None, 'default'):
            return                       # already looping (e.g. the next line): no restart
        if pose in LOOP_POSES and pose != self.playing:
            self._mouth_since = self._now()
        self.playing = pose
        self._play(pose)

    def _finish(self, blocked: bool = False) -> None:
        playing = self.playing
        self.active = False
        self.phase = None
        self.pose = None
        self.playing = None
        self._pauses = []
        if self._voice == 'playing':
            self._voice = 'none'
        if not blocked:
            self._stop(playing)


_TEA_WORDS = re.compile(
    r"\b(tea|teas|teacup|teacups|teapot|earl\s+grey|sip|sips|sipped|sipping)\b"
    r"|\b(my|this|her|your)\s+(cup|drink|mug)\b", re.IGNORECASE)


def mentions_tea(text) -> bool:
    """True when a line talks about her tea: tea, a teacup, a sip, or her cup/drink."""
    return bool(_TEA_WORDS.search(str(text or '')))


def tea_pose(text, pose: Optional[str], available=None) -> Optional[str]:
    """The emotion pose of a line: `tea` (her teacup clip) when the line mentions it and the role
    has the clip, else `pose` unchanged."""
    if mentions_tea(text) and (available is None or TEA_POSE in available):
        return TEA_POSE
    return pose


def clamp_bubble_s(bubble_s) -> float:
    """Bubble time in seconds, never negative and never above MAX_BUBBLE_S."""
    try:
        value = float(bubble_s)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(value):
        return 0.0
    return min(max(0.0, value), MAX_BUBBLE_S)


# ---------------------------------------------------------------------------------------------
# Mouth pauses from the voice WAV
# ---------------------------------------------------------------------------------------------

def rms_envelope(pcm16: bytes, rate: int = 24000, window_s: float = ENVELOPE_WINDOW_S) -> List[float]:
    """RMS of each `window_s` window of little-endian mono PCM16 (the last partial window
    included)."""
    samples = array('h')
    samples.frombytes(bytes(pcm16)[:len(pcm16) - len(pcm16) % 2])
    if sys.byteorder != 'little':
        samples.byteswap()
    size = max(1, int(round(rate * window_s)))
    out = []
    for start in range(0, len(samples), size):
        chunk = samples[start:start + size]
        out.append(math.sqrt(sum(map(int.__mul__, chunk, chunk)) / len(chunk)))
    return out


def mouth_pauses(envelope: Sequence[float], window_s: float = ENVELOPE_WINDOW_S,
                 min_pause_s: float = MIN_PAUSE_S, floor: float = SILENCE_FLOOR,
                 rel: float = SILENCE_REL) -> List[Tuple[float, float]]:
    """(start_s, end_s) of every silence longer than `min_pause_s` in an RMS envelope."""
    if not envelope:
        return []
    threshold = max(float(floor), float(rel) * max(envelope))
    pauses, start = [], None
    for i, value in enumerate(list(envelope) + [float('inf')]):
        if value < threshold:
            if start is None:
                start = i
        elif start is not None:
            begin, end = start * window_s, min(i, len(envelope)) * window_s
            if end - begin > min_pause_s + 1e-9:
                pauses.append((round(begin, 6), round(end, 6)))
            start = None
    return pauses


def wav_mouth_pauses(path) -> List[Tuple[float, float]]:
    """Mouth pauses of a PCM16 mono WAV (the relay's 24 kHz voice); [] if it cannot be read
    or is in another format."""
    import wave
    try:
        with wave.open(str(path), 'rb') as wav:
            if wav.getsampwidth() != 2 or wav.getnchannels() != 1 or not wav.getframerate():
                return []
            rate = wav.getframerate()
            pcm = wav.readframes(wav.getnframes())
    except (OSError, EOFError, wave.Error):
        return []
    return mouth_pauses(rms_envelope(pcm, rate))
