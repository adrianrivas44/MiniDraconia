"""Engine M3.1 for Draconia: the M3 audit findings closed, and her talking feels alive.

Behaviour contracts, standard library unittest + Qt, no network. Clip lengths and speeds are
read from Draconia's own role files (tests/test_engine_m3.py helpers).
"""
import json
import math
import os
import random
import re
import struct
import sys
import tempfile
import time
import unittest
import unittest.mock
import wave
from pathlib import Path

from test_engine_m3 import (ACTION, ENGINE, OWNER_DPR, REPO, ROLE, FakeClock, clip_seconds, frame_count,
                             qt_app, run_python)


def pcm16(*parts, rate=24000):
    """Mono PCM16: ('tone', seconds[, amplitude]) and ('silence', seconds[, noise])."""
    out = bytearray()
    for kind, seconds, *level in parts:
        n = int(round(seconds * rate))
        amp = level[0] if level else (8000 if kind == 'tone' else 0)
        for i in range(n):
            if kind == 'tone':
                value = int(amp * math.sin(2 * math.pi * 220 * i / rate))
            else:
                value = int(amp * (1 if i % 2 else -1))
            out += struct.pack('<h', value)
    return bytes(out)


def write_wav(path, pcm, rate=24000):
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)


# --- 2. Audit 2.1 (rejected): the timeout is seconds; only a 60 s clamp ------------------------

class BubbleClamp(unittest.TestCase):
    def test_say_never_holds_her_longer_than_60_seconds(self):
        from DyberPet.talk_controller import MAX_BUBBLE_S, TalkController
        clock = FakeClock()
        talk = TalkController(lambda pose: None, lambda pose: None, now_fn=clock)
        self.assertEqual(MAX_BUBBLE_S, 60.0)
        talk.say(5000.0)                     # a timeout in ms by mistake
        self.assertLessEqual(talk.ends_at - clock.t, 60.0)
        talk.say(7.5)                        # seconds, as bubble_dict["timeout"] is
        self.assertAlmostEqual(talk.ends_at - clock.t, 7.5)
        talk.say(-3)
        self.assertEqual(talk.ends_at, clock.t)

    def test_the_bubble_timeout_is_in_seconds(self):
        from DyberPet.companion_chat import build_companion_chat_bubble
        bubble = build_companion_chat_bubble('Hmph. Fine, I will stay a bit.', len)
        self.assertGreater(bubble['timeout'], 1)
        self.assertLess(bubble['timeout'], 60)
        pet = (ENGINE / 'DyberPet' / 'DyberPet.py').read_text(encoding='utf-8')
        self.assertIn('QTimer.singleShot(int(bubble_dict["timeout"] * 1000)', pet)


# --- 3. Audit 2.6: climb_down is never a random action, parallel lists stay aligned ----------

class ClimbDownOutOfTheRandomPool(unittest.TestCase):
    def setUp(self):
        qt_app()
        from DyberPet import settings
        from DyberPet.conf import ActData, PetConfig
        from DyberPet.frames import FrameStore
        from DyberPet.pet_life import PetLifeMixin
        self.settings = settings
        self.conf = PetConfig.init_config('Draconia', FrameStore(ACTION, scale=0.5))

        class Pet(PetLifeMixin):
            pass
        pet = Pet()
        pet.pet_conf = self.conf
        pet._life_add_climb_down()
        pet._life_add_climb_down()           # idempotent
        data = ActData.__new__(ActData)      # no file I/O: the same config the engine generates
        self.act_params = data._check_fvlock(data.generate_config('Draconia', 100), 100)

    def test_parallel_lists_of_the_pet_config_are_aligned(self):
        conf = self.conf
        n = len(conf.random_act)
        self.assertEqual([len(conf.act_name), len(conf.act_type), len(conf.act_sound), len(conf.act_prob)],
                         [n] * 4)
        i = conf.act_name.index('climb_down')
        self.assertEqual(conf.act_prob[i], 0)
        self.assertIs(conf.random_act[i][0], conf.act_dict['climb_down'])
        self.assertEqual(list(conf.act_dict['climb_down'].images.names),
                         list(conf.act_dict['climb'].images.names)[::-1])

    def test_random_pool_indices_match_and_never_pick_climb_down(self):
        from DyberPet.modules import Animation_worker
        pet_conf_json = json.loads((ROLE / 'pet_conf.json').read_text(encoding='utf-8'))
        conf = self.conf
        self.assertNotIn('climb_down', self.act_params)
        for name, params in self.act_params.items():
            if params['act_type'] == 'random_act':
                listed = next(a['act_list'] for a in pet_conf_json['random_act'] if a['name'] == name)
                acts = conf.random_act[conf.act_name.index(name)]
                self.assertEqual([id(a) for a in acts], [id(conf.act_dict[a]) for a in listed], name)

        class Pool:
            _cal_prob = Animation_worker._cal_prob
            _get_acts = Animation_worker._get_acts
            random_act = Animation_worker.random_act

            def _run_acts(self, acts, accs=None):
                self.chosen.append(acts)

        pool = Pool()
        pool.pet_conf, pool.chosen, pool.nonDefault_prob = conf, [], 1.0
        act_data = unittest.mock.Mock(allAct_params={'Draconia': self.act_params})
        with unittest.mock.patch.object(self.settings, 'act_data', act_data, create=True), \
                unittest.mock.patch.object(self.settings, 'petname', 'Draconia', create=True), \
                unittest.mock.patch.object(self.settings, 'focus_timer_on', False, create=True):
            pool.act_cmlt_prob = pool._cal_prob([2, 100])
            self.assertEqual(len(pool.act_cmlt_prob), len(self.act_params))
            random.seed(31)
            for _ in range(3000):
                pool.random_act()
        down = conf.act_dict['climb_down']
        played = {id(a) for acts in pool.chosen for a in acts}
        self.assertNotIn(id(down), played)
        self.assertIn(id(conf.act_dict['right_walk']), played, 'the pool really ran')


# --- 4. Audit 2.7: window, floor and drag follow the shown size --------------------------------

class ShownSizeGeometry(unittest.TestCase):
    CODE = '''
        import json, os
        from PySide6.QtCore import QPoint, QRect
        from PySide6.QtWidgets import QApplication, QLabel, QWidget
        app = QApplication([])
        from DyberPet import frames, settings
        from DyberPet.conf import PetConfig
        from DyberPet.pet_life import PetLifeMixin
        from DyberPet.modules import frame_step, scaled_anchor

        class Pet(QWidget, PetLifeMixin):
            pass

        STATBAR, BAR = 20, 100
        out = {'dpr': app.primaryScreen().devicePixelRatio(), 'cases': []}
        for scale in (0.5, 1.0):
            settings.tunable_scale = scale
            pet = Pet()
            pet.label = QLabel(pet)
            pet.frame_store = frames.FrameStore(os.environ['ACTION'], scale=scale, dpr=pet.devicePixelRatioF())
            pet.pet_conf = PetConfig.init_config('Draconia', pet.frame_store)
            pet._life_sync_frames()
            pet.setFixedSize(*pet._life_window_size(BAR, STATBAR))
            pet.current_screen, pet.screen_height = QRect(0, 0, 1280, 800), 752   # 150 %, taskbar
            pet.move(400, pet._life_floor_y())
            stand = pet.pet_conf.default.images[0]
            frames.present(pet.label, stand, store=pet.frame_store)
            shown = frames.shown_size(stand, settings.pet_display_scale)
            standing = pet._life_sprite_rect()
            # Drag: grab her 40 % down the sprite; the drag frame replaces stand under the cursor.
            grab = QPoint(standing.center().x(), standing.top() + int(standing.height() * 0.4))
            drag_pos = grab - pet.pos()
            frames.present(pet.label, pet.pet_conf.drag.images[0], store=pet.frame_store)
            pet.move(grab + QPoint(37, -120) - drag_pos)          # mouseMoveEvent
            dragged = pet._life_sprite_rect()
            grabbed = grab + QPoint(37, -120)
            out['cases'].append({
                'scale': scale, 'display_scale': settings.pet_display_scale,
                'shown': list(shown), 'label': [pet.label.width(), pet.label.height()],
                'window': [pet.width(), pet.height()], 'floor_y': pet._life_floor_y(),
                'sprite_bottom': standing.bottom() + 1, 'sprite_size': [standing.width(), standing.height()],
                'drag_size': [dragged.width(), dragged.height()],
                'grab_in_sprite': [grabbed.x() - dragged.x(), grabbed.y() - dragged.y()],
                'grab_before': [grab.x() - standing.x(), grab.y() - standing.y()],
                'anchor': scaled_anchor([30, 60]),
                'walk_step': frame_step(pet.pet_conf.act_dict['right_walk'])[0],
                'opaque_right': pet._life_climb_span(pet.pet_conf.act_dict['climb'])[1],
            })
            if scale == 0.5:
                # Pet Scale or devicePixelRatio change: the window follows around her feet.
                feet = (pet.pos().x() + pet.width() // 2, pet.pos().y() + pet.height())
                settings.tunable_scale = 0.3
                changed = pet._life_sync_frames()
                pet._life_fit_window(BAR, STATBAR)
                out['refit'] = {'changed': changed, 'window': [pet.width(), pet.height()],
                                'feet': [pet.pos().x() + pet.width() // 2, pet.pos().y() + pet.height()],
                                'feet_before': list(feet), 'floor_pos': pet.floor_pos,
                                'floor_y': pet._life_floor_y()}
        print(json.dumps(out))
    '''

    @classmethod
    def setUpClass(cls):
        cls.result = run_python(cls.CODE, {'QT_QPA_PLATFORM': 'offscreen', 'QT_SCALE_FACTOR': '1.5',
                                           'ACTION': str(ACTION)})

    def test_at_dpr_1_5_and_scale_0_5(self):
        self.assertAlmostEqual(self.result['dpr'], 1.5)
        case = self.result['cases'][0]
        self.assertAlmostEqual(case['display_scale'], 0.5)
        self.assertEqual(case['label'], [257, 230])              # 515 x 460 x 0.5, shown 1:1
        self.check(case)
        self.assertEqual(case['anchor'], [15, 30])
        self.assertAlmostEqual(case['walk_step'], 5.16 * 0.5)

    def test_at_dpr_1_5_and_scale_1_0_capped(self):
        case = self.result['cases'][1]
        self.assertAlmostEqual(case['display_scale'], 1 / 1.5)
        self.assertEqual(case['label'], [343, 307], 'capped at the source: 460 / 1.5, not 460')
        self.check(case)
        self.assertEqual(case['anchor'], [20, 40], 'anchors scale with the shown size, not Pet Scale 1.0')
        self.assertAlmostEqual(case['walk_step'], 5.16 / 1.5)

    def check(self, case):
        shown_w, shown_h = case['shown']
        self.assertEqual(case['label'], [round(shown_w), round(shown_h)])
        self.assertEqual(case['sprite_size'], case['label'])
        self.assertEqual(case['window'][1], 2 * 20 + case['label'][1])
        # Floor: the window bottom is the work area's bottom, and her feet are the window bottom.
        self.assertEqual(case['floor_y'] + case['window'][1], 752)
        self.assertEqual(case['sprite_bottom'], 752)
        # Drag: the grabbed point stays on the same spot of the (same-size) drag frame.
        self.assertEqual(case['drag_size'], case['label'])
        self.assertEqual(case['grab_in_sprite'], case['grab_before'])
        self.assertLessEqual(case['opaque_right'], shown_w + 1e-6)

    def test_a_new_shown_size_resizes_the_window_around_her_feet(self):
        refit = self.result['refit']
        self.assertTrue(refit['changed'])
        self.assertEqual(refit['window'][1], 2 * 20 + round(460 * 0.3))
        self.assertLessEqual(abs(refit['feet'][0] - refit['feet_before'][0]), 1)
        self.assertEqual(refit['feet'][1], refit['feet_before'][1])
        self.assertEqual(refit['floor_pos'], refit['floor_y'])

    def test_no_pet_geometry_left_on_the_unscaled_size(self):
        """grep of audit 2.7: nothing sizes or places the pet from current_img or pet_conf
        sizes times tunable_scale any more."""
        pattern = re.compile(r'(current_img\.(width|height)\(\)|pet_conf\.(width|height))\s*\*\s*settings\.tunable_scale'
                             r'|int\(i\s*\*\s*settings\.tunable_scale\)')
        offenders = []
        for name in ('DyberPet.py', 'modules.py', 'Notification.py', 'Accessory.py', 'pet_life.py'):
            for n, line in enumerate((ENGINE / 'DyberPet' / name).read_text(encoding='utf-8').splitlines(), 1):
                if pattern.search(line) and not line.strip().startswith('#'):
                    offenders.append('%s:%d' % (name, n))
        self.assertEqual(offenders, [])
        pet = (ENGINE / 'DyberPet' / 'DyberPet.py').read_text(encoding='utf-8')
        self.assertEqual(pet.count('anim_area = self._life_sprite_rect()'), 2)
        self.assertIn('self.floor_pos = self._life_floor_y()', pet)
        self.assertIn('self._life_fit_window(self.tomato_time.width(), statbar_h)', pet)


# --- 5. Talking feels alive ------------------------------------------------------------------

class NoBlinkOrEdgeWhileTalking(unittest.TestCase):
    def ticker(self, talking):
        from DyberPet.companion_director import CompanionMicroTicker
        self.clock = [100.0]
        self.played, self.edges = [], []
        ctx = {'state': 'default', 'at_edge': 'right', 'walking_toward': 'right',
               'available_poses': {'peek', 'climb', 'talk'}}
        return CompanionMicroTicker(get_context=lambda: dict(ctx), play_action=self.played.append,
                              apply_cursor_flip=lambda flip: None, on_edge=self.edges.append,
                              now_fn=lambda: self.clock[0], rng=random.Random(3),
                              climb_cfg={'enabled': True, 'prob': 1.0}, handle_talk=False,
                              is_talking=lambda: talking[0])

    def run_ticks(self, ticker, seconds):
        for _ in range(int(seconds / 0.15)):
            self.clock[0] += 0.15
            ticker.tick()

    def test_while_talking_no_blink_and_no_wall_decision(self):
        talking = [True]
        ticker = self.ticker(talking)
        self.run_ticks(ticker, 12.0)
        self.assertEqual(self.played, [], 'nothing replaces the talk clip')
        self.assertEqual(self.edges, [])
        self.assertFalse(ticker.is_climbing)
        talking[0] = False
        self.run_ticks(ticker, 12.0)
        self.assertEqual(self.edges[:1], ['right'], 'after the line she decides at the wall again')
        self.assertTrue(self.played)

    def test_blinks_when_not_talking(self):
        from DyberPet.companion_director import CompanionMicroTicker
        clock = [0.0]
        played = []
        ticker = CompanionMicroTicker(get_context=lambda: {'state': 'default'}, play_action=played.append,
                                apply_cursor_flip=lambda flip: None, on_edge=lambda side: None,
                                now_fn=lambda: clock[0], rng=random.Random(1), handle_talk=False,
                                is_talking=lambda: False)
        for _ in range(100):
            clock[0] += 0.15
            ticker.tick()
        self.assertIn('blink', played)

    def test_pet_wires_the_talk_state(self):
        pet = (ENGINE / 'DyberPet' / 'DyberPet.py').read_text(encoding='utf-8')
        self.assertIn("is_talking=lambda: bool(getattr(getattr(self, 'talk_controller', None), 'active', False))", pet)


class VoiceSync(unittest.TestCase):
    """The bubble, say() and the talk loop wait for the voice's on_started (thinking), at most
    2.5 s; without voice there is no wait."""

    def stub(self):
        qt_app()
        from DyberPet import settings
        from DyberPet.pet_conversation import ConversationMixin
        from DyberPet.pet_life import PetLifeMixin
        from DyberPet.talk_controller import TalkController
        saved = {k: getattr(settings, k, None) for k in ('petname', 'draging', 'onfloor')}
        self.addCleanup(lambda: [setattr(settings, k, v) for k, v in saved.items()])
        settings.petname, settings.draging, settings.onfloor = 'Draconia', 0, 1
        clock = FakeClock()

        class Voice:
            def __init__(self):
                self.spoken, self.cancelled, self.current_wav = [], 0, None

            def speak(self, text, cfg):
                self.spoken.append(text)

            def cancel(self):
                self.cancelled += 1

        class Interaction:
            interact, act_name = None, None

        class Pet(PetLifeMixin, ConversationMixin):
            def __init__(self):
                self.poses, self.bubbles = [], []
                self.workers = {'Interaction': Interaction()}
                self.companion_voice = Voice()
                self.talk_controller = TalkController(self._play, lambda pose: None, now_fn=clock,
                                                      on_release=self._life_release_line,
                                                      clip_s=clip_seconds)

            def _companion_play_pose(self, pose, **kwargs):
                self._play(pose)

            def _play(self, pose):                      # the engine plays the clip
                self.poses.append(pose)
                self.workers['Interaction'].interact, self.workers['Interaction'].act_name = 'animat', pose

            def _companion_show_bubble(self, bubble):
                self.bubbles.append((clock.t, bubble['text']))

            def _companion_log(self, kind, text):
                pass
        return Pet(), clock

    def bubble(self, text='Hello.', timeout=4.0):
        return {'text': text, 'timeout': timeout}

    def tick(self, pet, clock, until, step=0.15):
        while clock.t < until - 1e-9:
            clock.t = round(clock.t + step, 6)
            pet._life_talk_tick()

    def test_voiced_line_waits_for_the_voice_thinking(self):
        pet, clock = self.stub()
        pet._life_say_line('Hello.', self.bubble(), {'enabled': True})
        self.assertEqual(pet.companion_voice.spoken, ['Hello.'])
        self.assertEqual(pet.bubbles, [], 'the bubble waits for the voice')
        self.tick(pet, clock, 1.2)
        self.assertEqual(pet.poses, ['think'])
        self.assertTrue(pet._life_holds_animation(), 'she stays put while she thinks')
        pet._life_voice_started(3.0)                     # the WAV starts at 1.2 s
        self.assertEqual(pet.bubbles, [(1.2, 'Hello.')])
        self.tick(pet, clock, 1.5)
        self.assertEqual(pet.poses, ['think', 'talk'])
        self.tick(pet, clock, 4.0)
        self.assertTrue(pet.talk_controller.active, 'talks while the voice plays (until 4.2 s)')
        self.tick(pet, clock, 4.4)
        self.assertFalse(pet.talk_controller.active)
        self.assertEqual(pet.companion_voice.cancelled, 0)

    def test_after_2_5_s_the_line_goes_ahead_without_voice(self):
        from DyberPet.talk_controller import VOICE_WAIT_S
        self.assertEqual(VOICE_WAIT_S, 2.5)
        pet, clock = self.stub()
        pet._life_say_line('Late.', self.bubble('Late.', 3.0), {'enabled': True})
        self.tick(pet, clock, 2.4)
        self.assertEqual(pet.bubbles, [])
        self.tick(pet, clock, 2.7)
        self.assertEqual(len(pet.bubbles), 1)
        self.assertAlmostEqual(pet.bubbles[0][0], 2.55, delta=0.16)
        self.assertEqual(pet.companion_voice.cancelled, 1, 'a voice arriving later would be out of sync')
        self.assertEqual(pet.poses[-1], 'talk')
        self.tick(pet, clock, 5.4)
        self.assertTrue(pet.talk_controller.active, 'the bubble time counts from when it shows')
        self.tick(pet, clock, 5.8)
        self.assertFalse(pet.talk_controller.active)

    def test_a_failed_voice_releases_the_line_at_once(self):
        pet, clock = self.stub()
        pet._life_say_line('Oops.', self.bubble('Oops.'), {'enabled': True})
        self.tick(pet, clock, 0.3)
        pet.talk_controller.voice_failed()
        self.assertEqual(pet.bubbles, [(0.3, 'Oops.')])

    def test_without_voice_there_is_no_wait(self):
        pet, clock = self.stub()
        pet._life_say_line('Quiet.', self.bubble('Quiet.'), {'enabled': False})
        self.assertEqual(pet.bubbles, [(0.0, 'Quiet.')])
        self.assertEqual(pet.companion_voice.spoken, [])
        self.tick(pet, clock, 0.15)
        self.assertEqual(pet.poses, ['talk'])

    def test_the_emotion_of_a_waiting_line_shows_when_it_starts(self):
        from DyberPet.brain_client import Reply
        pet, clock = self.stub()
        pet._emit_companion_bubble = lambda text, voice=None, wav=None: pet._life_say_line(text, self.bubble(text), {'enabled': True})
        pet._conv_show_reply(Reply('chat', 'Hmph.', 'angry', 'angry', 'relay'))
        self.tick(pet, clock, 0.6)
        pet._life_voice_started(9.0)
        self.tick(pet, clock, 0.9)
        self.assertEqual(pet.poses, ['think', 'angry'])
        # The emotion plays one full clip (her angry clip: 49 frames, 4.08 s), then she talks.
        angry_s = clip_seconds('angry')
        self.tick(pet, clock, 0.75 + angry_s - 0.2)
        self.assertEqual(pet.poses[-1], 'angry')
        self.tick(pet, clock, 0.75 + angry_s + 0.4)
        self.assertEqual(pet.poses[-1], 'talk')

    def test_pet_window_routes_every_life_line_through_the_wait(self):
        pet = (ENGINE / 'DyberPet' / 'DyberPet.py').read_text(encoding='utf-8')
        body = pet.split('def _emit_companion_bubble', 1)[1].split('\n    def ', 1)[0]
        self.assertIn('self._life_say_line(text, bubble_dict, voice_cfg, wav=wav if pack_voice else None)', body)
        self.assertNotIn('register_bubble.emit', body, 'the bubble is shown by _companion_show_bubble only')


class MouthPauses(unittest.TestCase):
    def test_envelope_and_pauses_from_synthetic_pcm(self):
        from DyberPet.talk_controller import mouth_pauses, rms_envelope
        pcm = pcm16(('tone', 0.5), ('silence', 0.4), ('tone', 0.3), ('silence', 0.1),
                    ('tone', 0.2), ('silence', 0.3, 40))
        env = rms_envelope(pcm, 24000)
        self.assertEqual(len(env), 90)                        # 1.8 s in 20 ms windows
        self.assertAlmostEqual(env[5], 8000 / math.sqrt(2), delta=150)
        self.assertEqual(env[30], 0.0)
        self.assertEqual(mouth_pauses(env, min_pause_s=0.25), [(0.5, 0.9), (1.5, 1.8)],
                         '0.4 s and the quiet tail are pauses; 0.1 s is not')
        self.assertEqual(mouth_pauses(env), [], 'M3.2: only silences of 0.8 s or more close her mouth')

    def test_pauses_are_relative_to_her_loudness(self):
        from DyberPet.talk_controller import mouth_pauses, rms_envelope
        quiet_voice = pcm16(('tone', 0.4, 2000), ('silence', 0.3, 150), ('tone', 0.4, 2000))
        self.assertEqual(mouth_pauses(rms_envelope(quiet_voice), min_pause_s=0.25), [(0.4, 0.7)])
        self.assertEqual(mouth_pauses(rms_envelope(pcm16(('tone', 1.0)))), [])
        self.assertEqual(mouth_pauses([]), [])

    def test_wav_reader(self):
        from DyberPet.talk_controller import wav_mouth_pauses
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'line.wav'
            write_wav(path, pcm16(('tone', 0.3), ('silence', 1.0), ('tone', 0.3)))
            self.assertEqual(wav_mouth_pauses(path), [(0.3, 1.3)])
            self.assertEqual(wav_mouth_pauses(Path(tmp) / 'missing.wav'), [])

    def test_closed_mouth_during_pauses_then_talk_again(self):
        from DyberPet.talk_controller import PAUSE_POSE, TalkController
        self.assertEqual(PAUSE_POSE, 'default')
        self.assertEqual(json.loads((ROLE / 'act_conf.json').read_text(encoding='utf-8'))['default']['images'],
                         'stand', "her default is the closed-mouth stand")
        clock = FakeClock()
        played = []
        talk = TalkController(played.append, lambda pose: None, now_fn=clock)
        talk.say(5.0, voiced=True)
        talk.voice_started(2.0, [(0.6, 1.5)])            # M3.2: pauses of 0.8 s or more
        seen = []
        while clock.t < 2.1:
            clock.t = round(clock.t + 0.15, 6)
            talk.tick(state='animat')
            seen.append((round(clock.t, 2), talk.playing))
        self.assertEqual(played, ['talk', 'default', 'talk'])
        self.assertEqual([t for t, p in seen if p == 'default'], [0.6, 0.75, 0.9, 1.05, 1.2, 1.35])
        self.assertFalse(talk.active)

    def test_pet_computes_the_pauses_when_the_wav_starts(self):
        qt_app()
        from DyberPet.pet_life import PetLifeMixin
        from DyberPet.talk_controller import TalkController
        clock = FakeClock()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'line.wav'
            write_wav(path, pcm16(('tone', 0.3), ('silence', 1.0), ('tone', 0.3)))

            class Pet(PetLifeMixin):
                pass
            pet = Pet()
            pet.talk_controller = TalkController(lambda p: None, lambda p: None, now_fn=clock)
            pet.companion_voice = unittest.mock.Mock(current_wav=str(path))
            pet.talk_controller.say(3.0, voiced=True)
            clock.t = 1.0
            pet._life_voice_started(1.6)
        self.assertTrue(pet.talk_controller.in_pause(1.5))
        self.assertFalse(pet.talk_controller.in_pause(2.4))


# --- 6. Audit 2.10: 12 fps -------------------------------------------------------------------

class TwelveFps(unittest.TestCase):
    def test_her_frames_play_at_about_12_fps(self):
        from DyberPet.modules import ticks_per_frame
        pet_conf = json.loads((ROLE / 'pet_conf.json').read_text(encoding='utf-8'))
        tick_ms = pet_conf['interact_speed'] * 1000
        self.assertAlmostEqual(tick_ms, 21.0)
        act_conf = json.loads((ROLE / 'act_conf.json').read_text(encoding='utf-8'))
        for name, conf in act_conf.items():
            period = ticks_per_frame(conf['frame_refresh'], tick_ms) * tick_ms / 1000
            with self.subTest(name):
                self.assertAlmostEqual(period, conf['frame_refresh'], delta=0.01 * conf['frame_refresh'])
        self.assertEqual(ticks_per_frame(1 / 12, 21), 4)
        self.assertEqual(ticks_per_frame(1 / 12, 20), 5, 'the old 20 ms tick showed 10 fps')

    def test_engine_clip_advances_a_frame_every_4_ticks(self):
        qt_app()
        from DyberPet import settings
        from DyberPet.conf import PetConfig
        from DyberPet.frames import FrameStore
        from DyberPet.modules import Interaction_worker
        conf = PetConfig.init_config('Draconia', FrameStore(ACTION, scale=0.5))
        self.assertAlmostEqual(conf.interact_speed, 21.0)
        keys = ('current_act', 'previous_act', 'anim_act', 'playid', 'current_img', 'previous_img',
                'current_anchor', 'previous_anchor', 'pet_display_scale', 'act_started_at', 'act_frame_shown')
        saved = {k: getattr(settings, k, None) for k in keys}
        self.addCleanup(lambda: [setattr(settings, k, v) for k, v in saved.items()])
        settings.current_act = settings.previous_act = settings.anim_act = None
        settings.current_img = settings.previous_img = None
        settings.current_anchor = settings.previous_anchor = [0, 0]
        settings.playid, settings.pet_display_scale = 0, 0.5

        now = [0.0]

        class Worker:                                   # M3.2: frames follow the clock
            pet_conf = conf
            clock = staticmethod(lambda: now[0])
        act = conf.act_dict['talk']
        shown = []
        for _ in range(12):
            Interaction_worker.img_from_act(Worker(), act)
            shown.append(settings.current_img.cacheKey())
            now[0] += 0.021
        self.assertEqual(len(set(shown)), 3)
        self.assertEqual(shown[0:4], [shown[0]] * 4)

    def test_walk_distance_per_frame_is_kept_so_speed_rises_with_the_frame_rate(self):
        from DyberPet.conf import Act
        from DyberPet.companion_director import frame_period_s
        from DyberPet.modules import frame_step
        walk = Act(images=[], need_move=True, direction='right', frame_move=5.16)
        per_frame = frame_step(walk, scale=0.5)[0]
        self.assertAlmostEqual(per_frame, 2.58)
        old_speed = per_frame / frame_period_s(1 / 12, 0.020)
        new_speed = per_frame / frame_period_s(1 / 12, 0.021)
        self.assertAlmostEqual(new_speed, 2.58 / 0.084)
        self.assertAlmostEqual(new_speed / old_speed, 0.1 / 0.084)


# --- 7. Audit 2.12 / 2.14: premultiplied scaling, cached pixmaps ------------------------------

class FrameQuality(unittest.TestCase):
    def test_scaling_is_premultiplied_no_fringe(self):
        qt_app()
        from PySide6.QtGui import QColor, QImage
        from DyberPet.frames import FrameStore
        with tempfile.TemporaryDirectory() as tmp:
            # Opaque dark ink next to an almost transparent, very light matte left by unmixing.
            img = QImage(100, 20, QImage.Format_ARGB32)
            for x in range(100):
                for y in range(20):
                    img.setPixelColor(x, y, QColor(20, 10, 30, 255) if x < 50 else QColor(255, 255, 255, 2))
            img.save(str(Path(tmp) / 'stand_0.png'))
            frame = FrameStore(tmp, scale=0.3, dpr=1.0).frame('stand_0')
            self.assertEqual(frame.format(), QImage.Format_ARGB32_Premultiplied)
            edge = [frame.pixelColor(x, 10) for x in range(frame.width())]
            for color in edge:
                if color.alpha() >= 64:
                    with self.subTest(x=edge.index(color)):
                        self.assertLess(color.lightness(), 60, 'no light fringe on the outline')

    def test_pixmaps_are_cached_per_frame_within_the_lru(self):
        qt_app()
        from PySide6.QtWidgets import QLabel
        from DyberPet.frames import FrameStore, present
        store = FrameStore(ACTION, scale=0.3, dpr=1.0, keep_recent=1)
        label = QLabel()
        first = present(label, store.frame('happy_0'), store=store)
        again = present(label, store.frame('happy_0'), store=store)
        self.assertEqual(first.cacheKey(), again.cacheKey(), 'the same pixmap, not a new conversion')
        self.assertEqual(store.cached_pixmaps(), 1)
        mirrored = present(label, store.frame('happy_0'), mirror=True, store=store)
        self.assertNotEqual(mirrored.cacheKey(), first.cacheKey())
        self.assertEqual(store.cached_pixmaps(), 1, 'mirrored views are not kept')
        present(label, store.frame('angry_0'), store=store)   # evicts 'happy' (keep_recent=1)
        self.assertNotIn('happy', store.cached_groups())
        self.assertEqual(store.cached_pixmaps(), 1, "the evicted frame's pixmap is released")
        transformed = store.frame('angry_0').mirrored(True, False)
        present(label, transformed, store=store)                # a copy the store does not hold
        self.assertEqual(store.cached_pixmaps(), 1)
        store.configure(0.4, 1.0)
        present(label, store.frame('stand_0'), store=store)
        self.assertEqual(store.cached_pixmaps(), 1)


# --- 8. Audit 2.11, 2.13, 2.19, 2.20 ---------------------------------------------------------

class Housekeeping(unittest.TestCase):
    def test_decode_log_is_bounded_with_a_counter(self):
        qt_app()
        from DyberPet.frames import DECODE_LOG_LEN, FrameStore
        self.assertEqual(DECODE_LOG_LEN, 256)
        store = FrameStore(ACTION, scale=0.1, dpr=1.0, keep_recent=8)
        groups = ('happy', 'angry', 'shy', 'bored', 'think', 'spell')
        for group in groups:
            for i in range(frame_count(group)):
                store.frame('%s_%d' % (group, i))
        total = sum(frame_count(g) for g in groups)
        self.assertGreater(total, 256)
        self.assertEqual(store.decode_count, total)
        self.assertEqual(len(store.decode_log), 256)
        self.assertEqual(store.decode_log[-1], 'spell_%d' % (frame_count('spell') - 1))
        self.assertEqual(store.decoded_groups(), set(groups))

    def test_wall_snap_span_is_cached_per_group_and_config(self):
        qt_app()
        from DyberPet import frames
        from DyberPet.conf import PetConfig
        from DyberPet.pet_life import PetLifeMixin
        store = frames.FrameStore(ACTION, scale=0.5, dpr=1.0)
        climb = PetConfig.init_config('Draconia', store).act_dict['climb']
        with unittest.mock.patch('DyberPet.frames.opaque_span', wraps=frames.opaque_span) as spy:
            first = PetLifeMixin._life_climb_span(climb)
            for _ in range(5):
                self.assertEqual(PetLifeMixin._life_climb_span(climb), first)
            self.assertEqual(spy.call_count, 1)
            store.configure(0.25, 1.0)
            half = PetLifeMixin._life_climb_span(climb)
            self.assertEqual(spy.call_count, 2, 'a new size is measured again')
        self.assertAlmostEqual(half[1], first[1] / 2, delta=1.0)

    def test_voice_wav_is_deleted_after_playback(self):
        qt_app()
        from DyberPet.companion_voice import CompanionVoice

        class Player:
            def __init__(self):
                self.events = []

            def play_file(self, path, volume):
                self.events.append('play')

            def stop(self):
                self.events.append('stop')

            def release(self):
                self.events.append('release')

        with tempfile.TemporaryDirectory() as tmp:
            first, second = Path(tmp) / 'voice-1.wav', Path(tmp) / 'voice-2.wav'
            for path in (first, second):
                write_wav(path, pcm16(('tone', 0.2)))
            player = Player()
            voice = CompanionVoice(engine=None, player=player, tmp_dir=tmp)
            voice._volume, voice._token = 0.5, 1
            voice._on_synth_done(str(first), 1)
            self.assertEqual(voice.current_wav, str(first))
            voice.notify_playback_finished()
            self.assertFalse(first.exists(), 'deleted when it finishes')
            self.assertEqual(player.events[-1], 'release', 'the player lets go of the file first')
            # A file the OS will not delete yet (still held) is retried at the next cleanup.
            voice._token = 2
            voice._on_synth_done(str(second), 2)
            real_unlink = Path.unlink
            with unittest.mock.patch.object(Path, 'unlink', side_effect=PermissionError):
                voice.notify_playback_finished()
            self.assertTrue(second.exists())
            with unittest.mock.patch.object(Path, 'unlink', real_unlink):
                voice.cancel()
            self.assertFalse(second.exists())
            self.assertEqual(sorted(os.listdir(tmp)), [])

    def test_stale_wavs_are_swept_at_start(self):
        qt_app()
        from DyberPet.companion_voice import STALE_WAV_S, CompanionVoice
        self.assertEqual(STALE_WAV_S, 3600)
        with tempfile.TemporaryDirectory() as tmp:
            old, fresh, other = Path(tmp) / 'voice-old.wav', Path(tmp) / 'voice-new.wav', Path(tmp) / 'note.txt'
            for path in (old, fresh, other):
                path.write_bytes(b'x')
            two_hours_ago = time.time() - 7200
            os.utime(old, (two_hours_ago, two_hours_ago))
            os.utime(other, (two_hours_ago, two_hours_ago))
            CompanionVoice(engine=None, player=unittest.mock.Mock(), tmp_dir=tmp)
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ['note.txt', 'voice-new.wav'])

    def test_climb_is_shorter(self):
        """Hold at the top halved (5-20 s -> 2.5-10 s), also in her bundled profile; on the owner's
        screen (1280 x 800 logical at 150 %, her default size shown at 1/1.5) the broom ride up
        the highest wall takes 12 s or less."""
        from DyberPet.companion_director import (CLIMB_HOLD_RANGE_S, DEFAULT_CLIMB_CFG, ClimbSession,
                                           climb_speed_px_s, load_climb_config)
        self.assertEqual(CLIMB_HOLD_RANGE_S, (2.5, 10.0))
        self.assertEqual(DEFAULT_CLIMB_CFG['hold_s'], [2.5, 10.0])
        self.assertEqual(load_climb_config(ENGINE / 'data' / 'draconia_brain.json')['hold_s'], [2.5, 10.0])
        with tempfile.TemporaryDirectory() as tmp:
            brain = Path(tmp) / 'brain.json'
            brain.write_text(json.dumps({'climb': {'enabled': False}}), encoding='utf-8')
            self.assertEqual(load_climb_config(brain)['hold_s'], [2.5, 10.0], 'a toggle keeps new defaults')
        act_conf = json.loads((ROLE / 'act_conf.json').read_text(encoding='utf-8'))
        pet_conf = json.loads((ROLE / 'pet_conf.json').read_text(encoding='utf-8'))
        climb = act_conf['climb']
        display = 1 / OWNER_DPR
        speed = climb_speed_px_s(climb['frame_move'], display, climb['frame_refresh'], pet_conf['interact_speed'])
        floor_y = 800 - round(460 * display)             # no taskbar: the longest wall
        session = ClimbSession.start('right', floor_y, floor_y, 0.0, 800.0, speed, random.Random(0), now=0.0,
                                     height_frac=(0.85, 0.85))
        t = 0.0
        while session.phase == 'up':
            t = round(t + 0.15, 6)
            session.advance(t, random.Random(0))
        self.assertLessEqual(t, 12.0)
        self.assertGreater(t, 3.0)

    def test_climb_toggle_writes_only_the_choice(self):
        pet = (ENGINE / 'DyberPet' / 'DyberPet.py').read_text(encoding='utf-8')
        body = pet.split('def _toggle_companion_climb', 1)[1].split('\n    def ', 1)[0]
        self.assertIn('user_climb["enabled"] = bool(checked)', body)
        self.assertIn('data["climb"] = user_climb', body)


if __name__ == '__main__':
    unittest.main()
