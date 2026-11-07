"""D2.1 behaviour contracts: pet events never call a brain; stored lines may speak with a voice pack.

Owner rule: the lines she already has are stored and repeated; only lines an AI must write spend
quota. Every pet event (greet, pat, pinch, touch_body, drag, fall, idle, chatter, bye) answers
from her stored pool in every mode (relay, own key, offline); only typed chat reaches a brain.
A stored line plays its recorded WAV when an optional voice pack (never in the repository) has
it, through the same playback and talk sync as relay voice.

Standard library unittest + PySide6, no network: a spy transport answers every request and the
socket is denied. The pet-window contracts run the real `PetWidget` entry points
(`_send_mia_greeting`, `_draconia_react`, `_mia_chatter`, `_send_mia_bye`, `_on_mia_chat_sent`,
`_emit_mia_bubble`) on a stand-in window in a fresh interpreter (pynput, which needs an X display
only to be imported, is stubbed there; nothing here uses it). No test reads source text.
"""
import hashlib
import json
import math
import os
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import unittest
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / 'full-engine'
EVENTS = ('greet', 'pat', 'pinch', 'touch_body', 'drag', 'fall', 'idle', 'chatter', 'bye')


def qt_app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def pcm_wav(path, parts, rate=24000):
    """A 24 kHz mono PCM16 WAV: ('tone', s) parts are a 220 Hz tone, ('rest', s) parts silence."""
    frames = bytearray()
    for kind, seconds in parts:
        for i in range(int(seconds * rate)):
            value = int(9000 * math.sin(2 * math.pi * 220 * i / rate)) if kind == 'tone' else 0
            frames += struct.pack('<h', value)
    with wave.open(str(path), 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(bytes(frames))
    return Path(path)


def make_pack(folder, lines):
    """A voice pack folder: `lines` is [(key, text, emotion, parts)]; returns {(key, text): wav}."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    entries, files = [], {}
    for index, (key, text, emotion, parts) in enumerate(lines):
        name = '%s_%02d.wav' % (key, index)
        path = pcm_wav(folder / name, parts)
        entries.append({'key': key, 'text': text, 'emotion': emotion, 'file': name,
                        'seconds': round(sum(s for _, s in parts), 3),
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
        files[(key, text)] = path
    (folder / 'manifest.json').write_text(json.dumps({'voice_id': 'test-voice', 'lines': entries}), encoding='utf-8')
    return files


# --------------------------------------------------------------------------------------------
# A stand-in pet window running the real PetWidget entry points, in a fresh interpreter
# --------------------------------------------------------------------------------------------

RIG = r'''
import json, math, os, random, socket, struct, sys, tempfile, time, types, wave
from pathlib import Path
from types import SimpleNamespace
def _stub_pynput():
    class _Listener:
        def __init__(self, *a, **k): pass
        def start(self): pass
        def stop(self): pass
    pyn, mouse = types.ModuleType('pynput'), types.ModuleType('pynput.mouse')
    mouse.Listener = mouse.Controller = _Listener
    mouse.Button = types.SimpleNamespace(left=1, right=2, middle=3)
    pyn.mouse = mouse
    sys.modules.setdefault('pynput', pyn)
    sys.modules.setdefault('pynput.mouse', mouse)
_stub_pynput()
from PySide6.QtWidgets import QApplication, QWidget
app = QApplication([])
from DyberPet import settings
from DyberPet.DyberPet import PetWidget
settings.petname = 'Draconia'          # after the import: loading the pet module resets settings
settings.onfloor, settings.draging = 1, 0
settings.volume = 0.5
from DyberPet.pet_life import PetLifeMixin
from DyberPet.pet_conversation import ConversationMixin
from DyberPet import brain_client
from DyberPet.brain_client import ConversationBrain, RelayVoiceEngine
from DyberPet.mia_chat import ChatHistory
from DyberPet.mia_voice import MiaVoice
from DyberPet.voice_pack import VoicePack
from DyberPet.draconia_reactions import Reactions

TMP = tempfile.mkdtemp()
RELAY = {'base_url': 'https://relay.invalid', 'token': 'relay-test-token'}
OWN = {'base_url': 'https://llm.invalid/api/v1', 'model': 'test/model', 'daily_cap': 200,
       'api_key': 'sk-test-secret-key-123'}
NOTE = os.path.join(os.environ['ENGINE'], 'res', 'role', 'Draconia', 'note')

def pcm_wav(path, parts, rate=24000):
    frames = bytearray()
    for kind, secs in parts:
        for i in range(int(secs * rate)):
            frames += struct.pack('<h', int(9000 * math.sin(2 * math.pi * 220 * i / rate)) if kind == 'tone' else 0)
    with wave.open(path, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(bytes(frames))
    return path

RELAY_WAV = open(pcm_wav(os.path.join(TMP, 'relay.wav'), [('tone', 0.4)]), 'rb').read()
requests = []      # every request any transport saw, as its path

class FakeResponse:
    def __init__(self, body): self._body, self.status = body, 200
    def read(self, *a): return self._body
    def close(self): pass

def spy(request, timeout):
    path = request.full_url.split('.invalid', 1)[-1]
    requests.append(path)
    if path.endswith('/v1/tts'):
        return FakeResponse(RELAY_WAV)
    if path.endswith('/v1/health'):
        return FakeResponse(b'{"ok": true}')
    if path.endswith('/chat/completions'):
        return FakeResponse(json.dumps({'choices': [{'message': {'content': '[happy] Typed reply.'}}]}).encode())
    return FakeResponse(json.dumps({'emotion': 'happy', 'text': 'Typed reply.'}).encode())

brain_client.default_transport = spy      # a client built without a transport is seen as well
def denied(*a, **k):
    requests.append('socket')
    raise OSError('network forbidden in this test')
socket.socket = denied
socket.create_connection = denied

class FakePlayer:
    def __init__(self): self.played = []
    def play_file(self, path, volume): self.played.append(os.path.basename(path))
    def stop(self): pass
    def release(self): pass

class Clock:
    def __init__(self): self.t = 1000.0
    def __call__(self): return self.t

def settle(pet, until=lambda: True, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        if pet._conv_calls.pending() == 0 and not pet.mia_voice._workers and until():
            break
        time.sleep(0.01)
    app.processEvents()

class Pet(QWidget, PetLifeMixin, ConversationMixin):
    _send_mia_greeting = PetWidget._send_mia_greeting
    _send_mia_bye = PetWidget._send_mia_bye
    _mia_ask = PetWidget._mia_ask
    _mia_chatter = PetWidget._mia_chatter
    _on_mia_chat_sent = PetWidget._on_mia_chat_sent
    _draconia_react = PetWidget._draconia_react
    _emit_mia_bubble = PetWidget._emit_mia_bubble
    _mia_available_poses = PetWidget._mia_available_poses

    def __init__(self, mode, pack=None, relay_voice=True):
        super().__init__()
        self.clock = Clock()
        self.bubbles, self.logs, self.poses, self.clips = [], [], [], []
        self.activity = 0
        self.mia_chat_history = ChatHistory()
        self.mia_chat_box = None
        self.pet_conf = SimpleNamespace(act_dict={p: 1 for p in (
            'patpat', 'pinch', 'touch_body', 'spell', 'angry', 'shy', 'hairflip', 'greet', 'bye',
            'talk', 'happy', 'think', 'tea', 'slowclap', 'bored')})
        self.workers = {'Interaction': SimpleNamespace(interact=None, act_name=None)}
        self.mia_mood = SimpleNamespace(dominant='content', mood_context_prompt=lambda: '')
        self.mia_director = SimpleNamespace(rng=random.Random(3), is_asleep=False,
                                            note_activity=self._note_activity)
        self.brain_file = os.path.join(TMP, 'brain-%s-%s.json' % (mode, id(self)))
        json.dump({'voice': {'enabled': False, 'volume': 0.8}, 'relay_voice': relay_voice},
                  open(self.brain_file, 'w'))
        self.player = FakePlayer()
        self.mia_voice = MiaVoice(engine=RelayVoiceEngine(lambda: dict(RELAY) if mode == 'relay' else None, spy),
                                  player=self.player, tmp_dir=os.path.join(TMP, 'voice-%s' % id(self)))
        brain = ConversationBrain(relay_loader=lambda: dict(RELAY) if mode == 'relay' else None,
                                  own_key_loader=lambda: dict(OWN) if mode == 'own_key' else None,
                                  transport=spy, clock=self.clock, rng=random.Random(5),
                                  prompt_loader=lambda: 'SOUL', sleep=lambda s: None,
                                  voice_pack=VoicePack(pack or os.path.join(TMP, 'no-pack')))
        self._conv_setup(brain=brain)
        settle(self)

    def _note_activity(self): self.activity += 1
    def _mia_brain_path(self): return Path(self.brain_file)
    def _mia_show_bubble(self, bubble): self.bubbles.append(bubble['message'].replace('\n', ' '))
    def _mia_play_pose(self, pose, **kw): self.poses.append(pose)
    def _mia_note_mood_event(self, kind, **meta): pass
    def _mia_log(self, kind, text): self.logs.append('%s %s' % (kind, text))
    def _mia_schedule_chatter(self, first=False): pass
    def fresh_reactions(self):
        # A fresh controller per event: its own 3 s line cooldown never hides a line here.
        self._draconia_reactions = Reactions(
            NOTE, bubble=lambda text: None, play=lambda path, volume: self.clips.append(os.path.basename(str(path))),
            is_playing=lambda: False, speak=self._conv_reaction_line)

def react(event):
    def run(pet):
        pet.fresh_reactions()
        pet._draconia_react(event)
    return run

def bye(pet):
    pet._send_mia_bye()
    pet._conv_finish_bye()

EVENT_CALLS = [('greet', lambda pet: pet._send_mia_greeting()), ('pat', react('head')),
               ('pinch', react('cheek')), ('touch_body', react('body')), ('drag', react('drag')),
               ('fall', react('fall')), ('idle', lambda pet: pet._mia_on_absence_return(400.0)),
               ('chatter', lambda pet: pet._mia_chatter()), ('bye', bye)]
'''


def run_rig(code, extra_env=None, timeout=240):
    env = dict(os.environ)
    env.update({'QT_QPA_PLATFORM': 'offscreen', 'ENGINE': str(ENGINE), 'MINIDRACONIA_MUTE': '0',
                'MINIDRACONIA_TEST_PROFILE': os.environ['MINIDRACONIA_TEST_PROFILE']})
    env.update(extra_env or {})
    env['PYTHONPATH'] = str(ENGINE) + os.pathsep + env.get('PYTHONPATH', '')
    proc = subprocess.run([sys.executable, '-c', RIG + code], env=env, cwd=str(ENGINE),
                          capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    if proc.returncode != 0:
        raise AssertionError('subprocess failed (%d):\n%s\n%s' % (proc.returncode, proc.stdout[-3000:], proc.stderr[-6000:]))
    lines = [line for line in proc.stdout.splitlines() if line.startswith('{')]
    return json.loads(lines[-1])


class EventsNeverCallABrain(unittest.TestCase):
    """Item 1: a spy transport in all three modes; typed chat is the positive control."""

    CODE = r'''
out = {}
for mode in ('relay', 'own_key', 'offline'):
    del requests[:]
    pet = Pet(mode)
    setup_requests = list(requests)
    del requests[:]
    answered = {}
    for key, call in EVENT_CALLS:
        pet.clock.t += 25.0                       # past the event rate limit: every event answers
        before = len(pet.bubbles)
        call(pet)
        settle(pet)
        answered[key] = len(pet.bubbles) - before
        assert pet._conv_calls.pending() == 0, key
    event_requests = list(requests)
    voice_played = list(pet.player.played)
    del requests[:]
    pet._on_mia_chat_sent('hello there')
    settle(pet, until=lambda: len(pet.bubbles) > sum(answered.values()))
    settle(pet, until=lambda: mode != 'relay' or '/v1/tts' in requests)
    out[mode] = {'setup': setup_requests, 'events': event_requests, 'answered': answered,
                 'voice_played_by_events': voice_played, 'chat': list(requests),
                 'chat_bubble': pet.bubbles[-1], 'clips': pet.clips, 'activity': pet.activity}
print(json.dumps(out))
'''

    @classmethod
    def setUpClass(cls):
        cls.out = run_rig(cls.CODE)

    def test_no_event_sends_any_request_in_any_mode(self):
        for mode in ('relay', 'own_key', 'offline'):
            with self.subTest(mode=mode):
                self.assertEqual(self.out[mode]['events'], [], 'the spy saw a request for a pet event')
                self.assertEqual(self.out[mode]['voice_played_by_events'], [], 'no relay voice for an event')

    def test_every_event_is_answered_by_a_line(self):
        for mode in ('relay', 'own_key', 'offline'):
            with self.subTest(mode=mode):
                self.assertEqual(self.out[mode]['answered'], {key: 1 for key in EVENTS})

    def test_typed_chat_is_the_only_path_to_the_brain(self):
        self.assertEqual(self.out['relay']['chat'], ['/v1/chat', '/v1/tts'])
        self.assertEqual(self.out['own_key']['chat'], ['/api/v1/chat/completions'])
        self.assertEqual(self.out['offline']['chat'], [])
        self.assertEqual(self.out['relay']['chat_bubble'], 'Typed reply.')
        self.assertEqual(self.out['own_key']['chat_bubble'], 'Typed reply.')

    def test_only_the_relay_health_check_runs_at_start(self):
        self.assertEqual(self.out['relay']['setup'], ['/v1/health'])
        self.assertEqual(self.out['own_key']['setup'], [])
        self.assertEqual(self.out['offline']['setup'], [])

    def test_approved_v1_clip_keeps_working_as_in_d2(self):
        # Own key and offline: the approved head clip plays; relay: her stored line, never two voices.
        self.assertEqual(self.out['own_key']['clips'], ['head-01.wav'])
        self.assertEqual(self.out['offline']['clips'], ['head-01.wav'])
        self.assertEqual(self.out['relay']['clips'], [])

    def test_lines_and_typed_messages_count_as_activity_for_naps(self):
        for mode in ('relay', 'own_key', 'offline'):
            with self.subTest(mode=mode):
                # 9 event lines + the typed message + its reply.
                self.assertEqual(self.out[mode]['activity'], 11)


class ChatFailureAnswersWithAStoredLine(unittest.TestCase):
    def test_a_failing_brain_gives_the_stored_chat_line_with_its_stored_voice(self):
        from DyberPet import brain_client
        from DyberPet.voice_pack import VoicePack
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        files = make_pack(folder, [('chat', 'Say that again, slowly.', 'thinking', [('tone', 0.5)])])
        calls = []

        def failing(request, timeout):
            calls.append(request.full_url)
            raise brain_client.urllib.error.HTTPError(request.full_url, 503, 'down', {}, None)
        for relay, own in (({'base_url': 'https://relay.invalid', 'token': 't0ken-x'}, None),
                           (None, {'base_url': 'https://llm.invalid/v1', 'model': 'm', 'api_key': 'k-1'})):
            brain = brain_client.ConversationBrain(
                relay_loader=lambda relay=relay: relay, own_key_loader=lambda own=own: own,
                transport=failing, lines={'chat': ['Say that again, slowly.']}, sleep=lambda s: None,
                prompt_loader=lambda: 'p', voice_pack=VoicePack(folder))
            reply = brain.remote_chat('hello')
            self.assertEqual((reply.source, reply.text, reply.emotion, reply.pose),
                             ('offline', 'Say that again, slowly.', 'thinking', 'think'))
            self.assertEqual(reply.wav, str(files[('chat', 'Say that again, slowly.')]))
        self.assertEqual(len(calls), 4, 'two attempts per mode, chat only')


class NoRepeat(unittest.TestCase):
    """No stored line repeats any of the last min(3, n-1) lines of its key."""

    def test_pools_of_every_size(self):
        from DyberPet.brain_client import ConversationBrain
        from DyberPet.voice_pack import VoicePack
        for size in (1, 2, 3, 4, 5, 9):
            pool = ['line %d' % i for i in range(size)]
            for seed in range(5):
                brain = ConversationBrain(relay_loader=lambda: None, lines={'pat': pool}, rng=random.Random(seed),
                                          voice_pack=VoicePack(Path(tempfile.gettempdir()) / 'no-pack-here'))
                drawn = [brain.offline_reply('pat').text for _ in range(120)]
                window = min(3, size - 1)
                for index in range(1, len(drawn)):
                    with self.subTest(size=size, seed=seed, index=index):
                        self.assertNotIn(drawn[index], drawn[max(0, index - window):index])
                self.assertEqual(set(drawn), set(pool), 'every line still comes up')

    def test_her_real_pools(self):
        from DyberPet.brain_client import ConversationBrain, load_offline_lines
        lines = load_offline_lines(ENGINE / 'data' / 'draconia_lines_en.json')
        brain = ConversationBrain(relay_loader=lambda: None, lines=lines, rng=random.Random(11))
        for key in EVENTS + ('chat',):
            drawn = [brain.offline_reply(key).text for _ in range(60)]
            window = min(3, len(lines[key]) - 1)
            for index in range(1, len(drawn)):
                self.assertNotIn(drawn[index], drawn[max(0, index - window):index], key)


class RateLimitUnchanged(unittest.TestCase):
    def test_offline_every_event_answers_and_with_a_brain_one_per_20_seconds(self):
        from DyberPet.brain_client import ConversationBrain
        clock = [0.0]
        offline = ConversationBrain(relay_loader=lambda: None, clock=lambda: clock[0])
        self.assertEqual([offline.plan(k) for k in EVENTS], ['offline'] * len(EVENTS))
        relay = ConversationBrain(relay_loader=lambda: {'base_url': 'https://r.invalid', 'token': 'tok-1'},
                                  clock=lambda: clock[0], transport=lambda r, t: None)
        self.assertEqual([relay.plan(k) for k in ('pat', 'pinch', 'greet', 'bye', 'chatter')],
                         ['offline', 'skip', 'offline', 'offline', 'skip'])
        clock[0] += 20.0
        self.assertEqual(relay.plan('drag'), 'offline')
        self.assertEqual(relay.plan('chat'), 'remote')


# --------------------------------------------------------------------------------------------
# Item 2: the optional voice pack
# --------------------------------------------------------------------------------------------

class VoicePackLookup(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        self.files = make_pack(self.folder, [('pat', 'One pat. I counted.', 'flustered', [('tone', 0.6)]),
                                             ('greet', 'There you are.', 'greet', [('tone', 0.4)])])

    def pack(self):
        from DyberPet.voice_pack import VoicePack
        return VoicePack(self.folder)

    def test_key_exact_text_existing_file_and_matching_sha(self):
        pack = self.pack()
        self.assertTrue(pack.present)
        self.assertEqual(pack.wav_for('pat', 'One pat. I counted.'), str(self.files[('pat', 'One pat. I counted.')]))
        self.assertEqual(pack.emotion('pat', 'One pat. I counted.'), 'flustered')
        self.assertIsNone(pack.wav_for('pat', 'One pat. I counted'), 'the text must be exact')
        self.assertIsNone(pack.wav_for('pinch', 'One pat. I counted.'), 'the key must match')

    def test_altered_or_missing_file_is_unvoiced(self):
        path = self.files[('pat', 'One pat. I counted.')]
        with open(path, 'ab') as stream:
            stream.write(b'\0\0')
        self.assertIsNone(self.pack().wav_for('pat', 'One pat. I counted.'), 'sha256 mismatch')
        self.files[('greet', 'There you are.')].unlink()
        self.assertIsNone(self.pack().wav_for('greet', 'There you are.'), 'missing file')

    def test_a_cached_check_notices_a_changed_file(self):
        pack = self.pack()
        self.assertIsNotNone(pack.wav_for('pat', 'One pat. I counted.'))
        path = self.files[('pat', 'One pat. I counted.')]
        data = bytearray(path.read_bytes())
        data[-1] ^= 0xFF
        path.write_bytes(bytes(data))
        os.utime(path, ns=(time.time_ns(), time.time_ns() + 10_000_000))
        self.assertIsNone(pack.wav_for('pat', 'One pat. I counted.'))

    def test_no_pack_and_broken_manifests_never_raise(self):
        from DyberPet.voice_pack import VoicePack
        self.assertFalse(VoicePack(self.folder / 'absent').present)
        for body in ('not json', '[]', '{"lines": 7}', '{"lines": [7, {"key": "pat"}]}'):
            (self.folder / 'manifest.json').write_text(body, encoding='utf-8')
            pack = VoicePack(self.folder)
            self.assertFalse(pack.present, body)
            self.assertIsNone(pack.wav_for('pat', 'One pat. I counted.'))

    def test_manifest_file_names_cannot_leave_the_pack(self):
        from DyberPet.voice_pack import VoicePack
        outside = pcm_wav(self.folder.parent / ('outside-%s.wav' % self.folder.name), [('tone', 0.2)])
        self.addCleanup(outside.unlink)
        sha = hashlib.sha256(outside.read_bytes()).hexdigest()
        for name in ('../' + outside.name, str(outside), '..\\' + outside.name, 'sub/x.wav', 'x.mp3', ''):
            (self.folder / 'manifest.json').write_text(json.dumps({'lines': [
                {'key': 'pat', 'text': 'x', 'emotion': 'happy', 'file': name, 'sha256': sha}]}), encoding='utf-8')
            self.assertIsNone(VoicePack(self.folder).wav_for('pat', 'x'), name)

    def test_the_default_folder_is_beside_the_exe_or_in_full_engine(self):
        from DyberPet import voice_pack
        self.assertEqual(voice_pack.default_pack_dir(), ENGINE / 'voice_pack')
        exe = Path(tempfile.gettempdir()) / 'install' / 'MiniDraconia.exe'
        from unittest import mock
        with mock.patch.object(sys, 'frozen', True, create=True), mock.patch.object(sys, 'executable', str(exe)):
            self.assertEqual(voice_pack.default_pack_dir(), exe.resolve().parent / 'voice_pack')

    def test_the_repository_ships_no_voice_pack(self):
        self.assertFalse((ENGINE / 'voice_pack').exists())
        tracked = subprocess.run(['git', 'ls-files'], cwd=str(REPO), capture_output=True, text=True).stdout.split('\n')
        self.assertEqual([name for name in tracked if 'voice_pack/' in name.lower()], [])


class StoredReplies(unittest.TestCase):
    def test_the_brain_attaches_wav_and_the_emotion_goes_to_a_pose(self):
        from DyberPet.brain_client import ConversationBrain
        from DyberPet.voice_pack import VoicePack
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        files = make_pack(folder, [('pat', 'One pat.', 'flustered', [('tone', 0.3)]),
                                   ('pat', 'Two pats.', 'nonsense', [('tone', 0.3)])])
        brain = ConversationBrain(relay_loader=lambda: None, lines={'pat': ['One pat.', 'Two pats.', 'Three pats.']},
                                  rng=random.Random(1), voice_pack=VoicePack(folder))
        seen = {}
        for _ in range(30):
            reply = brain.offline_reply('pat')
            seen[reply.text] = (reply.emotion, reply.pose, reply.wav)
        self.assertEqual(seen['One pat.'], ('flustered', 'shy', str(files[('pat', 'One pat.')])))
        self.assertEqual(seen['Two pats.'], ('neutral', 'talk', str(files[('pat', 'Two pats.')])),
                         'an unknown emotion is neutral')
        self.assertEqual(seen['Three pats.'], ('neutral', None, None), 'a line added later stays unvoiced, as in D2')


class StoredVoiceSync(unittest.TestCase):
    """A stored line goes through the relay voice's own playback and talk sync."""

    def rig(self, folder):
        qt_app()
        from DyberPet import settings
        for name, value in (('draging', 0), ('onfloor', 1)):
            saved = getattr(settings, name, None)
            self.addCleanup(setattr, settings, name, saved)
            setattr(settings, name, value)
        from DyberPet.mia_voice import MiaVoice
        from DyberPet.pet_conversation import ConversationMixin
        from DyberPet.pet_life import PetLifeMixin
        from DyberPet.talk_controller import TalkController
        clock = [0.0]

        class Player:
            def __init__(self):
                self.played = []

            def play_file(self, path, volume):
                self.played.append(path)

            def stop(self):
                pass

        class Engine:
            """The relay's synthesis, returning a copy of `source` (deleted after playback)."""
            source = None

            def synth(self, text, voice=None, lang=None, speed=None, out_dir=None):
                Path(out_dir).mkdir(parents=True, exist_ok=True)
                out = Path(out_dir) / ('relay-%d.wav' % time.monotonic_ns())
                shutil.copyfile(self.source, out)
                return str(out)

        class Pet(PetLifeMixin, ConversationMixin):
            def __init__(self):
                self.events, self.voice_started = [], []
                self.mia_voice = MiaVoice(Engine(), player=Player(), tmp_dir=folder / 'tmp')
                self.talk_controller = TalkController(lambda pose: None, lambda pose: None, now_fn=lambda: clock[0],
                                                      on_release=self._life_release_line)
                started = self.talk_controller.voice_started

                def record(duration, pauses=()):
                    self.voice_started.append((round(duration, 3), [tuple(round(x, 3) for x in p) for p in pauses]))
                    return started(duration, pauses)
                self.talk_controller.voice_started = record
                self.mia_voice.on_started = self._life_voice_started
                self.mia_voice.on_failed = self.talk_controller.voice_failed
                self.workers = {}

            def _mia_show_bubble(self, bubble):
                self.events.append(('bubble', bubble['message'], round(clock[0], 3)))

            def _mia_log(self, kind, text):
                pass

            def _mia_play_pose(self, pose, **kwargs):
                pass
        return Pet(), clock

    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.folder, True)
        # A line with a 1 s silence: the mouth closes there.
        self.files = make_pack(self.folder / 'pack', [('pat', 'One pat. I counted.', 'neutral',
                                                       [('tone', 0.8), ('rest', 1.0), ('tone', 0.7)])])
        self.wav = self.files[('pat', 'One pat. I counted.')]

    def test_stored_and_relay_lines_get_the_same_sync(self):
        from DyberPet.talk_controller import wav_mouth_pauses
        bubble = {'message': 'One pat. I counted.', 'timeout': 4.0}
        stored, clock = self.rig(self.folder)
        stored._life_say_line('One pat. I counted.', dict(bubble), {'enabled': True, 'volume': 0.8}, wav=str(self.wav))
        self.assertEqual(stored.mia_voice._player.played, [str(self.wav)])

        relay, clock2 = self.rig(self.folder)
        type(relay.mia_voice._engine).source = self.wav
        relay._life_say_line('One pat. I counted.', dict(bubble), {'enabled': True, 'volume': 0.8})
        app = qt_app()
        deadline = time.monotonic() + 5
        while not relay.voice_started and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        self.assertEqual(stored.voice_started, relay.voice_started)
        self.assertEqual(stored.voice_started[0][0], 2.5, 'the talk lasts the WAV')
        self.assertEqual(stored.voice_started[0][1], [tuple(round(x, 3) for x in p) for p in wav_mouth_pauses(self.wav)])
        self.assertTrue(stored.voice_started[0][1], 'the 1 s silence is a mouth pause')
        self.assertEqual(stored.events, [('bubble', 'One pat. I counted.', 0.0)], 'held, then shown when the voice starts')
        self.assertEqual(relay.events, [('bubble', 'One pat. I counted.', 0.0)])
        self.assertAlmostEqual(stored.talk_controller.ends_at, 2.5, places=3)

    def test_the_stored_file_is_never_deleted_and_the_relay_file_is(self):
        pet, _ = self.rig(self.folder)
        self.assertTrue(pet.mia_voice.play_stored(str(self.wav), {'enabled': True}))
        pet.mia_voice.notify_playback_finished()
        self.assertTrue(self.wav.is_file())
        type(pet.mia_voice._engine).source = self.wav
        pet.mia_voice.speak('x', {'enabled': True})
        app = qt_app()
        deadline = time.monotonic() + 5
        while pet.mia_voice.current_wav is None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        played = Path(pet.mia_voice.current_wav)
        self.assertTrue(played.is_file())
        pet.mia_voice.notify_playback_finished()
        self.assertFalse(played.exists())
        self.assertTrue(self.wav.is_file())

    def test_unreadable_files_release_the_line_unvoiced_and_never_raise(self):
        not_wav = self.folder / 'pack' / 'fake.wav'
        not_wav.write_bytes(b'RIFF but not really a wave file')
        for path in (str(not_wav), str(self.folder / 'pack' / 'gone.wav')):
            pet, clock = self.rig(self.folder)
            pet._life_say_line('Line.', {'message': 'Line.', 'timeout': 3.0}, {'enabled': True}, wav=path)
            with self.subTest(path=path):
                self.assertEqual(pet.events, [('bubble', 'Line.', 0.0)], 'shown at once, unvoiced')
                self.assertEqual(pet.voice_started, [])
                self.assertFalse(pet.talk_controller.waiting)

    def test_voice_off_plays_nothing(self):
        pet, _ = self.rig(self.folder)
        self.assertFalse(pet.mia_voice.play_stored(str(self.wav), {'enabled': False}))
        self.assertEqual(pet.mia_voice._player.played, [])


class PetWindowVoiceGate(unittest.TestCase):
    """The real `_emit_mia_bubble`: pack audio follows the Voice switch, Settings' Mute (volume 0)
    and MINIDRACONIA_MUTE; without a pack, or for a line it does not have, she is unvoiced."""

    CODE = r'''
pack = os.path.join(TMP, 'pack')
os.makedirs(pack)
import hashlib
lines = json.load(open(os.path.join(os.environ['ENGINE'], 'data', 'draconia_lines_en.json'), encoding='utf-8'))
entries = []
for key in ('greet', 'pinch', 'chat'):
    for i, text in enumerate(lines[key]):
        name = '%s_%d.wav' % (key, i)
        pcm_wav(os.path.join(pack, name), [('tone', 0.3)])
        entries.append({'key': key, 'text': text, 'emotion': 'angry' if key == 'pinch' else 'greet',
                        'file': name, 'sha256': hashlib.sha256(open(os.path.join(pack, name), 'rb').read()).hexdigest()})
json.dump({'voice_id': 'v', 'lines': entries}, open(os.path.join(pack, 'manifest.json'), 'w'))

def run(mode, pack_dir, relay_voice=True, volume=0.5):
    settings.volume = volume
    pet = Pet(mode, pack=pack_dir, relay_voice=relay_voice)
    pet._send_mia_greeting()
    pet.fresh_reactions(); pet.clock.t += 25; pet._draconia_react('cheek')
    pet.clock.t += 25; pet._mia_chatter()            # chatter has no recording in this pack
    pet.clock.t += 25; pet._on_mia_chat_sent('hi') if mode == 'offline' else None
    settle(pet)
    return {'played': pet.player.played, 'poses': pet.poses, 'voice_menu': pet._conv_has_voice_pack(),
            'logs': [l for l in pet.logs if l.startswith('voice ')]}

out = {}
for mode in ('offline', 'own_key', 'relay'):
    out[mode] = run(mode, pack)
out['no_pack'] = run('offline', None)
out['switch_off'] = run('offline', pack, relay_voice=False)
out['muted_in_settings'] = run('offline', pack, volume=0.0)
os.environ['MINIDRACONIA_MUTE'] = '1'
out['mute_env'] = run('offline', pack)
del requests[:]
print(json.dumps(out))
'''

    @classmethod
    def setUpClass(cls):
        cls.out = run_rig(cls.CODE)

    def test_stored_lines_play_their_pack_wav_in_every_mode(self):
        for mode in ('offline', 'own_key', 'relay'):
            with self.subTest(mode=mode):
                played = self.out[mode]['played']
                self.assertTrue(any(name.startswith('greet_') for name in played), played)
                self.assertTrue(any(name.startswith('pinch_') for name in played), played)
                self.assertFalse(any(name.startswith('chatter') for name in played), 'no recording: unvoiced')
                self.assertTrue(self.out[mode]['voice_menu'])
        self.assertTrue(any(name.startswith('chat_') for name in self.out['offline']['played']),
                        'the stored chat line speaks too')

    def test_the_manifest_emotion_picks_the_pose(self):
        self.assertIn('angry', self.out['offline']['poses'], 'pinch: manifest angry -> angry clip')

    def test_without_a_pack_or_with_the_voice_off_she_is_unvoiced(self):
        for case in ('no_pack', 'switch_off', 'muted_in_settings', 'mute_env'):
            with self.subTest(case=case):
                self.assertEqual(self.out[case]['played'], [])
        self.assertFalse(self.out['no_pack']['voice_menu'])

    def test_the_log_names_the_file_never_the_text(self):
        logs = ' '.join(self.out['offline']['logs'])
        self.assertIn('voice stored greet_', logs)
        lines = json.loads((ENGINE / 'data' / 'draconia_lines_en.json').read_text(encoding='utf-8'))
        for text in lines['greet'] + lines['pinch']:
            self.assertNotIn(text, logs)


if __name__ == '__main__':
    unittest.main()
