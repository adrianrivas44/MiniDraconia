"""Engine contracts ported from cut M3.2 to Draconia: she feels alive on a 150 % laptop.

Owner symptoms the engine fixes: she walked in place, long lines changed her animation, clips
stuttered, her drink clip never matched what she said, and the same 5 or 6 idle clips repeated.
For Draconia: her `tea` clip is a teacup, her idle pool is in her role (pet_conf.json
`idle_poses`), and every clip length is her own (walk 16 frames x 4, talk 39, stand 97...).

Standard library unittest + PySide6, no network, fake clocks. The pet-window contracts run the
real `PetWidget._move_customized`, `limit_in_screen`, `_companion_play_pose`, `resume_animation` and
`_companion_chatter` in a fresh interpreter, on a stand-in window with a screen rect (pynput, which
needs an X display only to be imported, is stubbed there; nothing here uses it).
"""
import json
import os
import random
import subprocess
import sys
import inspect
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / 'full-engine'
ROLE = ENGINE / 'res' / 'role' / 'Draconia'
ACTION = ROLE / 'action'
SOURCE_W, SOURCE_H = 515, 460

IDLE = ('tea', 'read', 'sit', 'think', 'stretch', 'hairflip', 'spell', 'slowclap', 'bored',
        'happy', 'shy', 'peek', 'doze', 'mirror', 'quill')          # D2.2: mirror and quill
# Her own clip lengths (frames), measured from res/role/Draconia/action.
FRAMES = {'bored': 49, 'angry': 49, 'happy': 49, 'shy': 43, 'spell': 69, 'talk': 39, 'stand': 97,
          'think': 49, 'tea': 73, 'walkcycle_right': 16, 'walkcycle_left': 16, 'climb': 96,
          'drag': 96, 'fall': 96}


def qt_app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def run_python(code, env_extra, timeout=180):
    """Run `code` in a fresh interpreter (Qt scale factor / settings must be set before start)."""
    env = dict(os.environ)
    env.update(env_extra)
    env['PYTHONPATH'] = str(ENGINE) + os.pathsep + env.get('PYTHONPATH', '')
    proc = subprocess.run([sys.executable, '-c', inspect.cleandoc(code)], env=env, cwd=str(ENGINE),
                          capture_output=True, text=True, encoding='utf-8', errors='replace',
                          timeout=timeout)
    if proc.returncode != 0:
        raise AssertionError('subprocess failed (%d):\n%s\n%s' % (proc.returncode, proc.stdout, proc.stderr))
    lines = [l for l in proc.stdout.splitlines() if l.startswith('{')]
    return json.loads(lines[-1])


PRELUDE = '''
import json, math, os, random, struct, sys, tempfile, types, wave
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
from types import SimpleNamespace
from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QLabel
app = QApplication([])
from DyberPet import settings, frames
from DyberPet.conf import PetConfig
from DyberPet.pet_life import PetLifeMixin
from DyberPet.modules import Interaction_worker, Animation_worker
from DyberPet.DyberPet import PetWidget

settings.petname = 'Draconia'
settings.onfloor, settings.draging, settings.set_fall = 1, 0, 1
settings.screens = []
settings.focus_timer_on = False
settings.pet_display_scale = settings.tunable_scale = 0.5
settings.pet_data = SimpleNamespace(hp_tier=3, fv_lvl=0)
store = frames.FrameStore(os.environ['ACTION'], scale=0.5, dpr=1.0)
conf = PetConfig.init_config('Draconia', store)
NAMES = [a['name'] for a in json.load(open(os.path.join(os.environ['ROLE'], 'pet_conf.json')))['random_act']]
settings.act_data = SimpleNamespace(allAct_params={'Draconia': {
    n: {'act_type': 'random_act', 'act_prob': 0, 'status_type': [0, 0], 'unlocked': True,
        'in_playlist': True} for n in NAMES}})

def reset_engine():
    settings.current_anchor = [0, 0]
    settings.previous_anchor = [0, 0]
    settings.current_act = settings.previous_act = settings.anim_act = None
    settings.current_img = settings.previous_img = None
    settings.playid = settings.act_id = 0
    settings.act_started_at = None

class Clock:
    t = 0.0
    def __call__(self):
        return self.t

class FakeAnimation:
    def __init__(self):
        self.resumed = self.skipped = 0
    def pause(self): pass
    def resume(self): self.resumed += 1
    def skip_clip(self): self.skipped += 1

class Pet(PetLifeMixin):
    """A stand-in window running the real PetWidget move path and pose entry point."""
    _move_customized = PetWidget._move_customized
    limit_in_screen = PetWidget.limit_in_screen
    _companion_play_pose = PetWidget._companion_play_pose
    resume_animation = PetWidget.resume_animation
    _companion_stop_follow_cursor = PetWidget._companion_stop_follow_cursor
    _companion_chatter = PetWidget._companion_chatter
    _companion_ask = PetWidget._companion_ask

    def __init__(self, centre_x, screen=QRect(0, 0, 1280, 760), w=300, h=260):
        self._x, self._y, self._w, self._h = centre_x - w // 2, screen.height() - h, w, h
        self.current_screen = screen
        self.screen_width, self.screen_height = screen.width(), screen.height()
        self.floor_pos = self._y
        self.label = QLabel()
        self.label.setFixedSize(257, 230)
        self.pet_conf = conf
        self.lines = []
        self.workers = {'Animation': FakeAnimation()}
    def pos(self): return QPoint(self._x, self._y)
    def move(self, x, y): self._x, self._y = int(x), int(y)
    def width(self): return self._w
    def height(self): return self._h
    def centre(self): return self._x + self._w // 2
    def devicePixelRatioF(self): return 1.5
    def _companion_log(self, kind, text): self.lines.append('%s %s' % (kind, text))
    def _companion_maybe_say_pose_line(self, pose): pass

def interaction_for(pet, clock):
    reset_engine()
    w = Interaction_worker(conf)
    w.timer.stop()
    w.clock = clock
    w.sig_move_inter.connect(pet._move_customized)
    w.sig_act_finished.connect(pet.resume_animation)
    pet.workers['Interaction'] = w
    return w

def walk_lines(pet):
    return [l for l in pet.lines if l.startswith('walk ')]
'''


ENGINE_STATE = ('petname', 'draging', 'onfloor', 'current_act', 'previous_act', 'anim_act', 'playid',
                'act_id', 'current_img', 'previous_img', 'current_anchor', 'previous_anchor',
                'pet_display_scale', 'act_started_at', 'act_frame_shown', 'act_frames_advanced')


def engine_state(test, **values):
    """Fresh engine globals for an in-process test, restored afterwards."""
    from DyberPet import settings
    saved = {k: getattr(settings, k, None) for k in ENGINE_STATE}
    test.addCleanup(lambda: [setattr(settings, k, v) for k, v in saved.items()])
    settings.petname, settings.draging, settings.onfloor = 'Draconia', 0, 1
    settings.current_act = settings.previous_act = settings.anim_act = None
    settings.current_img = settings.previous_img = None
    settings.current_anchor, settings.previous_anchor = [0, 0], [0, 0]
    settings.playid = settings.act_id = 0
    settings.pet_display_scale = 0.5
    settings.act_started_at = None
    for key, value in values.items():
        setattr(settings, key, value)
    return settings


def run_pet(code, timeout=240):
    return run_python(PRELUDE + code, {
        'QT_QPA_PLATFORM': 'offscreen', 'ACTION': str(ACTION), 'ROLE': str(ROLE),
        'MINIDRACONIA_TEST_PROFILE': os.environ['MINIDRACONIA_TEST_PROFILE']}, timeout=timeout)


def walk_step(scale=0.5):
    """Window px per walk frame at `scale` (act_conf frame_move x display scale)."""
    acts = json.loads((ROLE / 'act_conf.json').read_text(encoding='utf-8'))
    return acts['right_walk']['frame_move'] * scale


class FakeResponse:
    def __init__(self, data, status=200):
        self.status = status
        self._body = json.dumps(data).encode('utf-8')

    def read(self, limit=-1):
        return self._body if limit < 0 else self._body[:limit]

    def close(self):
        pass


class FakeTransport:
    """Records each request (URL, JSON body) and answers without any network."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, request, timeout):
        self.calls.append({'url': request.full_url, 'timeout': timeout,
                           'body': json.loads(request.data.decode('utf-8')) if request.data else None})
        return self.response


# --- 1 and 2. No walking in place, walk diagnostics ---------------------------------------------

class NoWalkingInPlace(unittest.TestCase):
    CODE = '''
out = {}

# A. A director walk reaches the right wall: 4 clamped frames end it (not the 5.3 s clip).
clock = Clock(); pet = Pet(centre_x=1240)
w = interaction_for(pet, clock)
pet._companion_play_pose('right_walk')
ticks = 0
while w.interact is not None and ticks < 2000:
    w.run(); clock.t += 0.021; ticks += 1
out['director'] = {'interact': w.interact, 'ticks': ticks, 'centre': pet.centre(), 'lines': walk_lines(pet),
                   'resumed': pet.workers['Animation'].resumed, 'all_lines': pet.lines}

# B. Already at the right wall: a director walk to the right turns around and travels.
clock = Clock(); pet = Pet(centre_x=1280)
w = interaction_for(pet, clock)
pet._companion_play_pose('right_walk')
for _ in range(200):
    w.run(); clock.t += 0.021
out['turn'] = {'act': w.act_name, 'centre': pet.centre(), 'lines': walk_lines(pet)}

# C. The random animation's WalkRight gets stuck at the wall: the rest of the clip is skipped.
def animation_for(pet):
    reset_engine()
    anim = Animation_worker(conf)
    clock = Clock()
    anim._clock = clock
    anim._sleep = lambda s: setattr(clock, 't', clock.t + s)
    anim.wall_side = lambda: getattr(pet, '_life_wall', None)
    shown = []
    anim.sig_setimg_anim.connect(lambda: shown.append(1))
    anim.sig_move_anim.connect(pet._move_customized)
    anim.sig_walk_done.connect(lambda: pet._life_walk_end('anim'))
    pet.workers = {'Animation': anim, 'Interaction': SimpleNamespace(interact=None)}
    pet._life_publish_wall()
    return anim, shown

pet = Pet(centre_x=1250)
anim, shown = animation_for(pet)
anim._run_acts([conf.right, conf.default])
out['animation'] = {'frames_shown': len(shown), 'centre': pet.centre(), 'lines': walk_lines(pet),
                    'skip': anim._skip}

# D. At the right wall the random WalkRight never starts toward it: she walks left.
pet = Pet(centre_x=1280)
anim, shown = animation_for(pet)
anim._run_acts([conf.right])
out['animation_turn'] = {'frames_shown': len(shown), 'centre': pet.centre(), 'lines': walk_lines(pet)}

# E. Left wall too, through the real limit_in_screen of a screen that does not start at 0.
pet = Pet(centre_x=-1880, screen=QRect(-1920, 0, 1920, 1080))
anim, shown = animation_for(pet)
anim._run_acts([conf.left])
out['left_wall'] = {'centre': pet.centre(), 'lines': walk_lines(pet)}

# F. The start line.
pet = Pet(centre_x=600)
pet._life_log_screen()
out['screen'] = pet.lines
out['walk_frames'] = len(conf.right.images) * conf.right.act_num
print(json.dumps(out))
'''

    @classmethod
    def setUpClass(cls):
        cls.out = run_pet(cls.CODE)

    def end_lines(self, lines):
        return [l for l in lines if l.startswith('walk end ')]

    def parse(self, line):
        """'walk end right_walk dx=40 frames=20 clamped=4' -> ('right_walk', 40, 20, 4)."""
        parts = line.split()
        values = dict(p.split('=') for p in parts[3:])
        return parts[2], int(values['dx']), int(values['frames']), int(values['clamped'])

    def moving_frames(self, distance):
        """Frames a walk needs to cover `distance` px at her measured step (remainder kept)."""
        step = walk_step()
        n, total = 0, 0.0
        while int(total) < distance:
            total += step
            n += 1
        return n

    def test_director_walk_ends_after_4_clamped_frames_at_the_wall(self):
        d = self.out['director']
        self.assertIsNone(d['interact'], 'the walk interaction ended')
        self.assertEqual(d['centre'], 1280, 'she reached the wall')
        clip_ticks = self.out['walk_frames'] / 12.0 / 0.021
        self.assertLess(d['ticks'], clip_ticks / 2, 'ended at the wall, not after the whole clip: %r' % d)
        ends = self.end_lines(d['lines'])
        self.assertEqual(len(ends), 1, d['lines'])
        pose, dx, frames, clamped = self.parse(ends[0])
        self.assertEqual((pose, dx, clamped), ('right_walk', 40, 4))
        self.assertLessEqual(abs(frames - clamped - self.moving_frames(40)), 1, ends[0])
        self.assertEqual(d['resumed'], 1, 'the random animation resumes; the director decides again')

    def test_walk_diagnostics_are_english(self):
        """Public project: the walk/screen diagnostics are English (no 'camina'/'pantalla')."""
        for line in self.out['director']['all_lines'] + self.out['screen']:
            with self.subTest(line=line):
                self.assertFalse(line.split()[0] in ('camina', 'pantalla'), line)

    def test_walk_toward_the_wall_she_touches_turns_around(self):
        t = self.out['turn']
        self.assertEqual(t['act'], 'left_walk')
        self.assertLess(t['centre'], 1280 - 100, 'and really travels')
        self.assertIn('walk turn right_walk -> left_walk (wall right)', t['lines'])

    def test_random_animation_walk_skips_the_rest_of_its_clip(self):
        a = self.out['animation']
        self.assertEqual(a['centre'], 1280)
        self.assertLess(a['frames_shown'], self.moving_frames(30) + 6,
                        'not %d frames of walking in place: %r' % (self.out['walk_frames'], a))
        self.assertTrue(a['skip'], 'the default after it is skipped too: the director decides')
        ends = self.end_lines(a['lines'])
        self.assertEqual(len(ends), 1, a['lines'])
        pose, dx, frames, clamped = self.parse(ends[0])
        self.assertEqual((pose, dx, clamped), ('right_walk', 30, 4))

    def test_random_animation_walk_never_starts_into_the_wall(self):
        a = self.out['animation_turn']
        total = self.out['walk_frames']
        self.assertEqual(total, 64, 'her walk clip: 16 frames, 4 times')
        self.assertEqual(a['frames_shown'], total)
        distance = int(total * walk_step())
        self.assertEqual(self.end_lines(a['lines']),
                         ['walk end left_walk dx=%d frames=%d clamped=0' % (-distance, total)])
        self.assertEqual(a['centre'], 1280 - distance)

    def test_left_wall_on_a_screen_left_of_the_primary(self):
        a = self.out['left_wall']
        self.assertEqual(a['centre'], -1920)
        ends = self.end_lines(a['lines'])
        self.assertEqual(len(ends), 1, a['lines'])
        pose, dx, _frames, clamped = self.parse(ends[0])
        self.assertEqual((pose, dx, clamped), ('left_walk', -40, 4))

    def test_start_line_has_screen_dpr_and_scale(self):
        self.assertEqual(self.out['screen'], ['screen 0,0 1280x760 dpr=1.50 scale=0.500'])

    def test_walk_tracker_contract(self):
        from DyberPet.modules import WALK_STUCK_FRAMES, WalkTracker, wall_side
        self.assertEqual(WALK_STUCK_FRAMES, 4)
        t = WalkTracker()
        t.begin('right_walk', 'inter')
        self.assertEqual([t.step(10, m) for m in (10, 11, 0, 0, 0, 10, 0, 0, 0)], [False] * 9,
                         'a step that moves resets the run')
        self.assertTrue(t.step(11, 0))
        self.assertEqual(t.end(), 'end right_walk dx=31 frames=10 clamped=7')
        self.assertIsNone(t.end(), 'logged once')
        self.assertEqual(wall_side(1130, 300, 0, 1280), 'right')
        self.assertEqual(wall_side(-150, 300, 0, 1280), 'left')
        self.assertIsNone(wall_side(500, 300, 0, 1280))


# --- 3. Variety --------------------------------------------------------------------------------

class Variety(unittest.TestCase):
    def available(self):
        acts = json.loads((ROLE / 'act_conf.json').read_text(encoding='utf-8'))
        return set(acts) | {'climb_down'}

    def pool(self):
        from DyberPet.companion_director import load_role_idle_poses
        return load_role_idle_poses(ROLE / 'pet_conf.json')

    def director(self, seed, pool, combos=None):
        qt_app()
        from DyberPet.companion_director import CompanionDirector
        played = []
        director = CompanionDirector(get_available_poses=self.available, play_action=played.append,
                               is_busy=lambda: False, rng=random.Random(seed), system_idle_fn=None,
                               idle_pool=pool, combos=combos)
        director.weights = {'idle': 1.0}
        return director, played

    def assert_no_repeat_within_4(self, played):
        for i in range(len(played) - 3):
            self.assertEqual(len(set(played[i:i + 4])), 4, (i, played[i:i + 4]))

    def test_her_idle_pool_is_built_into_the_role(self):
        pool = self.pool()
        self.assertEqual(set(pool), set(IDLE))
        self.assertNotIn('yawn', pool, 'her yawn (D2.2) only comes before sleep')
        self.assertTrue(set(pool) <= self.available(), 'every idle pose is one of her clips')
        self.assertGreater(pool['tea'], pool['doze'], 'tea is a favourite; the doze is short and rare')
        self.assertEqual(max(pool, key=pool.get), 'tea')

    def test_200_idle_picks_use_every_pose_and_never_repeat_within_4(self):
        pool = self.pool()
        for seed in (1, 7, 32):
            director, played = self.director(seed, pool)
            for _ in range(200):
                director._tick_once()                 # the real idle tick, action forced to idle
            with self.subTest(seed=seed):
                self.assertEqual(len(played), 200)
                self.assertEqual(set(played), set(IDLE), 'every listed pose appears')
                self.assertNotIn('default', played)
                self.assertNotIn('yawn', played)
                self.assert_no_repeat_within_4(played)

    def test_her_combos_never_repeat_one_of_the_last_three(self):
        from DyberPet.companion_director import load_combos
        combos = load_combos(ENGINE / 'data' / 'draconia_brain.json')
        self.assertTrue(combos, 'her profile defines character sequences')
        for seed in (2, 11):
            director, played = self.director(seed, self.pool(), combos=combos)
            for _ in range(300):
                director._tick_once()
            with self.subTest(seed=seed):
                self.assertEqual(len(played), 300)
                self.assert_no_repeat_within_4(played)

    def test_a_combo_follow_up_in_the_recent_three_is_not_played(self):
        director, played = self.director(3, self.pool(), combos={'spell': {'hairflip': 1.0}})
        director._recent_idle.extend(['read', 'hairflip', 'sit'])
        director.state.combo_pending = 'hairflip'
        director._tick_once()
        self.assertEqual(len(played), 1)
        self.assertNotIn(played[0], ('read', 'hairflip', 'sit'), 'a fresh idle pose instead')
        director._recent_idle.clear()
        director._recent_idle.extend(['read', 'think', 'sit'])
        director.state.combo_pending = 'hairflip'
        director._tick_once()
        self.assertEqual(played[-1], 'hairflip', 'a fresh follow-up still plays')
        self.assertEqual(director.recent_idle[-1], 'hairflip', 'and counts as a recent idle pose')

    def test_director_weights(self):
        from DyberPet.companion_director import DEFAULT_WEIGHTS, load_director_config
        weights = {'idle': 0.55, 'walk': 0.25, 'follow_cursor': 0.10, 'sleep': 0.05}
        self.assertEqual(DEFAULT_WEIGHTS, weights)
        self.assertEqual(load_director_config('/nonexistent/no_brain.json')['weights'], DEFAULT_WEIGHTS,
                         'without a brain file the defaults apply')
        bundled = load_director_config(ENGINE / 'data' / 'draconia_brain.json')['weights']
        # D2.1: her random naps are rarer (owner: she fell asleep within seconds).
        self.assertEqual(bundled, dict(weights, sleep=0.015), 'her bundled profile: rarer naps')

    def test_older_profile_pose_weights_fold_into_idle(self):
        from DyberPet.companion_director import fold_pose_weights
        old = {'idle': 0.15, 'walk': 0.12, 'follow_cursor': 0.03, 'sleep': 0.0, 'spell': 0.12,
               'tea': 0.1, 'greet': 0.06}
        folded = fold_pose_weights(old)
        self.assertEqual(set(folded), {'idle', 'walk', 'follow_cursor', 'sleep'})
        self.assertAlmostEqual(folded['idle'], 0.15 + 0.12 + 0.1 + 0.06)
        self.assertEqual((folded['walk'], folded['follow_cursor'], folded['sleep']), (0.12, 0.03, 0.0))
        qt_app()
        from DyberPet.companion_director import CompanionDirector
        kwargs = dict(get_available_poses=self.available, play_action=lambda pose: None,
                      is_busy=lambda: False, rng=random.Random(1), system_idle_fn=None, weights=old)
        self.assertAlmostEqual(CompanionDirector(idle_pool=self.pool(), **kwargs).weights['idle'], 0.43)
        self.assertNotIn('spell', CompanionDirector(idle_pool=self.pool(), **kwargs).weights)
        self.assertEqual(CompanionDirector(**kwargs).weights, old, 'without a role pool nothing changes')

    def test_the_random_animation_shares_the_varied_pool(self):
        qt_app()
        from DyberPet.conf import PetConfig
        from DyberPet.frames import FrameStore
        from DyberPet.modules import Animation_worker
        conf = PetConfig.init_config('Draconia', FrameStore(ACTION, scale=0.5))
        director, _ = self.director(5, self.pool())

        class Worker:
            pet_conf = conf
            idle_picker = staticmethod(director.pick_idle_pose)
        worker = Worker()
        happy, default = conf.act_dict['happy'], conf.default
        swapped = [Animation_worker._fresh_idle(worker, [happy, default]) for _ in range(40)]
        names = [acts[0].act_name for acts in swapped]
        self.assertTrue(all(acts[1] is default for acts in swapped), 'the stand after it stays')
        self.assertTrue(set(names) <= set(IDLE))
        self.assertGreaterEqual(len(set(names)), 8, 'not the same 5 or 6')
        self.assertEqual(director.recent_idle, names[-3:], 'one shared no-repeat memory')
        for keep in ([conf.right, default], [default], [conf.act_dict['doze'], conf.act_dict['sleep']]):
            self.assertIs(Animation_worker._fresh_idle(worker, keep), keep)


# --- 4. Her tea --------------------------------------------------------------------------------

class Tea(unittest.TestCase):
    def test_tea_words(self):
        from DyberPet.talk_controller import TEA_POSE, mentions_tea, tea_pose
        self.assertEqual(TEA_POSE, 'tea')
        for text in ('One more sip of my tea.', 'Earl Grey, obviously.', 'Let me finish my drink.',
                     'This cup is research equipment.', 'Sipping. Do not interrupt.', 'TEA.',
                     'The teapot stays with me.', 'Mind the teacup.'):
            with self.subTest(text):
                self.assertTrue(mentions_tea(text))
        for text in ('Drink some water. It is for research.', 'Cupboard? No.', 'The team is late.',
                     'Steam rises from nowhere.', 'Hello.', '', None):
            with self.subTest(text):
                self.assertFalse(mentions_tea(text))
        self.assertEqual(tea_pose('My tea is cold.', 'angry', {'tea', 'angry'}), 'tea')
        self.assertEqual(tea_pose('My tea is cold.', 'angry', {'angry'}), 'angry', 'no clip, no swap')
        self.assertEqual(tea_pose('Hmph.', 'angry', {'tea'}), 'angry')

    def stub(self):
        qt_app()
        from types import SimpleNamespace
        from DyberPet.pet_conversation import ConversationMixin
        from DyberPet.pet_life import PetLifeMixin
        from DyberPet.talk_controller import TalkController
        clock = SimpleNamespace(t=0.0)

        class Pet(PetLifeMixin, ConversationMixin):
            def __init__(self):
                self.poses = []
                self.pet_conf = SimpleNamespace(act_dict={'tea': 1, 'talk': 1, 'angry': 1, 'default': 1})
                self.interaction = SimpleNamespace(interact=None, act_name=None)
                self.workers = {'Interaction': self.interaction}
                self.talk_controller = TalkController(self._play, lambda pose: None, now_fn=lambda: clock.t)

            def _play(self, pose):
                self.poses.append(pose)
                self.interaction.interact, self.interaction.act_name = 'animat', pose

            def _emit_companion_bubble(self, text, voice=None, wav=None):
                # Long enough for the emotion clip and then talk.
                self._life_say_line(text, {'text': text, 'timeout': 10.0}, {'enabled': False})

            def _companion_show_bubble(self, bubble):
                pass

            def _companion_log(self, kind, text):
                pass
        engine_state(self)
        return Pet(), clock

    def run_line(self, text, pose='talk', source='own_key'):
        from DyberPet.brain_client import Reply
        pet, clock = self.stub()
        pet._conv_show_reply(Reply('chatter', text, 'neutral', pose, source))
        while clock.t < 7.0:
            clock.t = round(clock.t + 0.15, 6)
            pet._life_talk_tick()
        return pet.poses

    def test_a_line_about_her_tea_sips_it_then_talks(self):
        self.assertEqual(self.run_line('One sip of my tea and I am brilliant again.'), ['tea', 'talk'])
        self.assertEqual(self.run_line('Earl Grey? Obviously.', pose='angry', source='relay'), ['tea', 'talk'])
        self.assertEqual(self.run_line('This cup stays with me.', source='offline'), ['tea', 'talk'])

    def test_other_lines_keep_their_emotion(self):
        self.assertEqual(self.run_line('Drink some water. It is for research.'), ['talk'])
        self.assertEqual(self.run_line('Hmph.', pose='angry'), ['angry', 'talk'])

    def test_chatter_context_says_she_is_sipping_her_tea(self):
        import datetime
        from DyberPet.companion_director import _POSE_DESC, choose_chatter_prompt, pose_description
        self.assertEqual(_POSE_DESC['tea'], 'you are sipping your tea')
        self.assertEqual(pose_description('tea'), 'you are sipping your tea')
        now = datetime.datetime(2026, 11, 6, 16, 0)
        self.assertIn('Right now you are sipping your tea.', choose_chatter_prompt(random.Random(1), now, 'tea'))

    def test_chatter_is_a_stored_line_in_every_mode(self):
        # D2.1 (supersedes D2's remote chatter): chatter never reaches the relay or an own key.
        from DyberPet.brain_client import ConversationBrain
        for relay, own in (({'base_url': 'https://relay.example', 'token': 'x1'}, None),
                           (None, {'base_url': 'https://api.example/v1', 'api_key': 'k-test', 'model': 'm'})):
            transport = FakeTransport(FakeResponse({'emotion': 'happy', 'text': 'Mm. Tea.'}))
            brain = ConversationBrain(relay_loader=lambda relay=relay: relay, own_key_loader=lambda own=own: own,
                                      transport=transport, lines={'chatter': ['My tea is perfect.']},
                                      prompt_loader=lambda: 'prompt', sleep=lambda s: None)
            self.assertEqual(brain.plan('chatter'), 'offline')
            reply = brain.offline_reply('chatter')
            self.assertEqual((reply.source, reply.text), ('offline', 'My tea is perfect.'))
            self.assertEqual(transport.calls, [])

    CHATTER = '''
import datetime
clock = Clock(); pet = Pet(centre_x=600)
asked = []
pet._conv_brain = object()
pet._conv_event = lambda key, doing=None: asked.append([key, doing])
pet._companion_schedule_chatter = lambda first=False: None
pet.companion_chat_box = None
pet.companion_director = SimpleNamespace(rng=random.Random(4), is_asleep=False)
pet.workers['Interaction'] = SimpleNamespace(interact='animat', act_name='tea')
pet._companion_chatter()
pet.workers['Interaction'] = SimpleNamespace(interact=None, act_name=None)
settings.anim_act = conf.act_dict['tea']
pet._companion_chatter()
print(json.dumps({'asked': asked}))
'''

    def test_pet_chatter_sends_what_she_is_doing(self):
        out = run_pet(self.CHATTER)
        self.assertEqual(out['asked'], [['chatter', 'you are sipping your tea']] * 2,
                         'from a director pose and from the random animation')


# --- 5. Talking is one smooth animation ------------------------------------------------------

class SmoothTalking(unittest.TestCase):
    CODE = '''
from DyberPet.talk_controller import TalkController, wav_mouth_pauses

def pcm(parts, rate=24000):
    data = bytearray()
    for kind, secs in parts:
        for i in range(int(secs * rate)):
            v = int(8000 * math.sin(2 * math.pi * 220 * i / rate)) if kind == 'tone' else 0
            data += struct.pack('<h', v)
    return bytes(data)

def run_line(voiced_pauses=None, poke_at=None):
    clock = Clock(); pet = Pet(centre_x=600)
    w = interaction_for(pet, clock)
    starts, shown = [], []
    original = w.start_interact
    def start(interact, act_name=None, loop=False, **kwargs):
        starts.append([act_name, loop, round(clock.t, 3)])
        original(interact, act_name, loop=loop, **kwargs)
    w.start_interact = start
    w.sig_setimg_inter.connect(lambda: shown.append([round(clock.t, 3), settings.current_act.act_name,
                                                     settings.act_frame_shown]))
    pet.talk_controller = TalkController(play_pose=pet._life_talk_play, stop_pose=pet._life_talk_stop, now_fn=clock)
    if voiced_pauses is None:
        pet.talk_controller.say(12.0, voiced=False)
    else:
        pet.talk_controller.say(0.0, voiced=True)
        pet.talk_controller.voice_started(12.0, voiced_pauses)
    blocked = {}
    tick = 0
    while clock.t < 12.4:
        w.run()
        if tick % 2 == 0:
            pet._life_talk_tick()                        # the 40 ms talk timer
        if poke_at is not None and abs(clock.t - poke_at) < 0.0105:
            before = len(starts)
            pet._companion_play_pose('happy')                  # director idle
            pet._companion_play_pose('blink')                  # micro ticker
            pet.resume_animation()                       # random animation asks to resume
            blocked = {'starts': len(starts) - before, 'resumed': pet.workers['Animation'].resumed,
                       'fall_allowed': pet._life_pose_allowed_while_talking('fall', False),
                       'happy_allowed': pet._life_pose_allowed_while_talking('happy', False)}
        clock.t = round(clock.t + 0.021, 6)
        tick += 1
    return {'starts': starts, 'shown': shown, 'active': pet.talk_controller.active, 'interact': w.interact,
            'blocked': blocked, 'talk_frames': len(conf.act_dict['talk'].images)}

with tempfile.TemporaryDirectory() as tmp:
    path = os.path.join(tmp, 'line.wav')
    with wave.open(path, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
        wav.writeframes(pcm([('tone', 4.0), ('silence', 1.0), ('tone', 7.0)]))
    pauses = wav_mouth_pauses(path)
    short = os.path.join(tmp, 'short.wav')
    with wave.open(short, 'wb') as wav:
        wav.setnchannels(1); wav.setsampwidth(2); wav.setframerate(24000)
        wav.writeframes(pcm([('tone', 3.0), ('silence', 0.5), ('tone', 3.0), ('silence', 0.6), ('tone', 3.0)]))
    short_pauses = wav_mouth_pauses(short)
print(json.dumps({'continuous': run_line(poke_at=3.0), 'pause': run_line(pauses), 'pauses': pauses,
                  'short_pauses': short_pauses}))
'''

    @classmethod
    def setUpClass(cls):
        cls.out = run_pet(cls.CODE)

    def test_continuous_speech_is_one_talk_loop_with_no_restart(self):
        c = self.out['continuous']
        self.assertEqual(c['talk_frames'], FRAMES['talk'])
        self.assertEqual([s[:2] for s in c['starts']], [['talk', True]], '0 extra pose changes')
        during = [s for s in c['shown'] if s[0] < 12.0]
        self.assertEqual({s[1] for s in during}, {'talk'}, 'never passes through default')
        frames = [s[2] for s in during]
        wraps = [i for i in range(1, len(frames)) if frames[i] < frames[i - 1]]
        clip_s = FRAMES['talk'] / 12.0
        self.assertEqual(len(wraps), int(12.0 / clip_s), 'her %.2f s talk clip loops for the 12 s line' % clip_s)
        for i in wraps:
            self.assertEqual((frames[i - 1], frames[i]), (FRAMES['talk'] - 1, 0),
                             'last frame, then frame 0 of the same clip')
        gaps = [b[0] - a[0] for a, b in zip(during, during[1:])]
        self.assertLessEqual(max(gaps), 0.084 + 1e-6, 'no stall at the loop point')
        self.assertFalse(c['active'])
        self.assertIsNone(c['interact'], 'the loop stops when the line ends')

    def test_one_1_s_pause_is_at_most_2_pose_changes(self):
        self.assertEqual(self.out['pauses'], [[4.0, 5.0]])
        p = self.out['pause']
        poses = [s[0] for s in p['starts']]
        self.assertEqual(poses, ['talk', 'default', 'talk'])
        self.assertLessEqual(len(poses) - 1, 2)
        self.assertTrue(all(s[1] for s in p['starts']), 'both mouth clips loop')

    def test_short_silences_do_not_close_her_mouth(self):
        self.assertEqual(self.out['short_pauses'], [], '0.5 s and 0.6 s keep the talk loop')

    def test_nothing_else_changes_the_pose_while_she_talks(self):
        b = self.out['continuous']['blocked']
        self.assertEqual(b['starts'], 0, 'director and micro ticker poses are refused')
        self.assertEqual(b['resumed'], 0, 'the random animation stays paused')
        self.assertTrue(b['fall_allowed'])
        self.assertFalse(b['happy_allowed'])

    def test_hysteresis(self):
        from DyberPet.talk_controller import MIN_PAUSE_S, MOUTH_HOLD_S, TalkController
        self.assertEqual((MIN_PAUSE_S, MOUTH_HOLD_S), (0.8, 0.4))
        clock = [0.0]
        played = []
        talk = TalkController(played.append, lambda pose: None, now_fn=lambda: clock[0])
        talk.say(0.0, voiced=True)
        # A pause that starts 0.1 s after she starts talking waits for the hold; a 0.7 s one is
        # ignored; after reopening at 3.9 s her mouth may only close again at 4.3 s, not at 4.1 s.
        talk.voice_started(6.0, [(0.1, 1.0), (2.0, 2.7), (3.0, 3.9), (4.1, 5.0)])
        changes = []
        while clock[0] < 5.9:
            talk.tick(state='animat')
            if not changes or changes[-1][1] != talk.playing:
                changes.append((round(clock[0], 2), talk.playing))
            clock[0] = round(clock[0] + 0.05, 6)
        self.assertEqual(changes, [(0.0, 'talk'), (0.4, 'default'), (1.0, 'talk'), (3.0, 'default'),
                                   (3.9, 'talk'), (4.3, 'default'), (5.0, 'talk')])


# --- 6. Fluid clips ----------------------------------------------------------------------------

class FluidClips(unittest.TestCase):
    def setUp(self):
        qt_app()

    def test_after_prefetch_a_full_loop_decodes_nothing_on_the_playing_thread(self):
        from DyberPet.frames import FrameStore
        store = FrameStore(ACTION, scale=0.25, dpr=1.0)
        done = store.prefetch(store.group_names('bored'))
        self.assertTrue(done.wait(60))
        self.assertEqual(store.decodes_on(), 0, 'decoded on the prefetch thread')
        self.assertEqual(store.decode_count, FRAMES['bored'])
        for _ in range(2):
            for i in range(FRAMES['bored']):
                store.frame('bored_%d' % i)
        self.assertEqual(store.decodes_on(), 0)

    def test_a_clip_start_prefetches_its_group(self):
        from DyberPet import settings
        from DyberPet.conf import PetConfig
        from DyberPet.frames import FrameStore
        from DyberPet.modules import Interaction_worker
        store = FrameStore(ACTION, scale=0.25, dpr=1.0)
        conf = PetConfig.init_config('Draconia', store)
        engine_state(self)
        now = [0.0]

        class Worker:
            pet_conf = conf
            clock = staticmethod(lambda: now[0])
        act = conf.act_dict['spell']
        self.assertEqual(len(act.images), FRAMES['spell'])
        Interaction_worker.img_from_act(Worker(), act)        # the clip starts: frame 0
        self.assertTrue(store.prefetch(act.images.names).wait(60), 'its group is being prefetched')
        before = store.decodes_on()
        for _ in range(2 * FRAMES['spell'] * 4):               # a full loop and more
            now[0] += 0.021
            Interaction_worker.img_from_act(Worker(), act)
        self.assertGreater(settings.act_frame_shown, -1)
        self.assertEqual(store.decodes_on() - before, 0)

    def test_prefetch_thread_stops_before_exit(self):
        """A prefetch thread still decoding a QImage while Python tears down daemon threads makes
        Qt abort the process: the atexit hook closes every store first."""
        from DyberPet import frames
        from DyberPet.frames import FrameStore
        store = FrameStore(ACTION, scale=0.25, dpr=1.0)
        first = store.prefetch(store.group_names('angry'))
        second = store.prefetch(store.group_names('shy'))
        self.assertIn(store, set(frames._STORES), 'covered by the exit hook')
        thread = store._prefetch_thread
        store.close()
        self.assertFalse(thread.is_alive(), 'stopped and joined')
        self.assertTrue(first.wait(5) and second.wait(5), 'nobody waits on a prefetch that will not run')
        self.assertTrue(store.prefetch(store.group_names('bored')).is_set(), 'no new work after close')
        self.assertEqual(store.frame('bored_0').isNull(), False, 'frames still decode on demand')

    def test_decoding_never_holds_the_store_lock(self):
        from DyberPet.frames import FrameStore
        store = FrameStore(ACTION, scale=0.25, dpr=1.0)
        gate, entered = threading.Event(), threading.Event()
        build = store._build

        def slow_build(name, *args):
            if name == 'shy_0':
                entered.set()
                gate.wait(30)                                  # a very slow decode
            return build(name, *args)
        store._build = slow_build
        other = threading.Thread(target=store.frame, args=('shy_0',), daemon=True)
        other.start()
        self.assertTrue(entered.wait(10))
        start = time.monotonic()
        store.frame('shy_1')                                   # another frame, decoded meanwhile
        store.frame('stand_0')
        self.assertLess(time.monotonic() - start, 5.0)
        self.assertTrue(other.is_alive(), 'the slow decode is still running')
        gate.set()
        other.join(30)
        self.assertEqual(sorted(n for n in store.decode_log), ['shy_0', 'shy_1', 'stand_0'])

    def measure_cache(self, dpr, extra):
        """Play every pinned group and then `extra` groups at Pet Scale 1.0 (her default)."""
        from DyberPet.frames import PINNED_GROUPS, FrameStore
        store = FrameStore(ACTION, scale=1.0, dpr=dpr)
        for group in list(PINNED_GROUPS) + list(extra):
            self.assertTrue(store.prefetch(store.group_names(group)).wait(240), group)
            store.frame(group + '_0')
        return store

    def test_pinned_groups_and_the_measured_budget_at_the_owner_screen(self):
        from DyberPet.frames import MAX_BYTES, PINNED_GROUPS, physical_size
        self.assertEqual(set(PINNED_GROUPS), {'stand', 'walkcycle_right', 'walkcycle_left', 'talk', 'think', 'tea'})
        self.assertEqual(MAX_BYTES, 450 * 2 ** 20)
        w, h = physical_size(SOURCE_W, SOURCE_H, 1.0, 1.5)
        self.assertEqual((w, h), (SOURCE_W, SOURCE_H), 'scale 1.0 at DPR 1.5 is capped at the source size')
        frame_bytes = w * h * 4
        store = self.measure_cache(1.5, ['happy', 'angry', 'shy', 'bored'])
        cached = set(store.cached_groups())
        self.assertTrue(set(PINNED_GROUPS) <= cached, 'pinned once decoded')
        self.assertEqual(cached - set(PINNED_GROUPS), {'shy', 'bored'})
        frames = sum(FRAMES[g] for g in cached)
        measured = store.cached_bytes()
        self.assertEqual(measured, frames * frame_bytes)
        self.assertLess(measured, MAX_BYTES)
        print('\n[engine] frame cache at DPR 1.5, Pet Scale 1.0: %d groups, %d frames, %.1f MB'
              % (len(cached), frames, measured / 2 ** 20))
        store.close()

    def test_her_largest_clips_stay_within_the_byte_budget(self):
        """Her drag/fall/climb clips have 96 frames: two of them after the pinned groups would be
        over 450 MB at full size, so the budget drops the oldest unpinned one (never the newest)."""
        from DyberPet.frames import MAX_BYTES, PINNED_GROUPS
        for dpr in (1.5, 1.0):
            with self.subTest(dpr=dpr):
                store = self.measure_cache(dpr, ['climb', 'drag', 'fall'])
                cached = store.cached_groups()
                self.assertTrue(set(PINNED_GROUPS) <= set(cached))
                self.assertIn('fall', cached, 'the newest group is kept')
                self.assertLessEqual(store.cached_bytes(), MAX_BYTES)
                print('\n[engine] worst case at DPR %.1f, Pet Scale 1.0: %s, %.1f MB'
                      % (dpr, sorted(set(cached) - set(PINNED_GROUPS)), store.cached_bytes() / 2 ** 20))
                store.close()

    def test_byte_budget_drops_the_oldest_unpinned_groups(self):
        from DyberPet.frames import FrameStore
        store = FrameStore(ACTION, scale=0.1, dpr=1.0, keep_recent=10)
        one = None
        for group in ('happy', 'angry', 'shy'):
            for i in range(FRAMES[group]):
                store.frame('%s_%d' % (group, i))
            one = one or store.cached_bytes()
        self.assertEqual(store.cached_groups(), ['happy', 'angry', 'shy'])
        store._max_bytes = 2 * one
        for i in range(FRAMES['bored']):
            store.frame('bored_%d' % i)
        self.assertEqual(store.cached_groups(), ['shy', 'bored'])
        self.assertLessEqual(store.cached_bytes(), 2 * one)

    def test_interaction_pacing_survives_a_late_tick(self):
        from DyberPet import settings
        from DyberPet.conf import PetConfig
        from DyberPet.frames import FrameStore
        from DyberPet.modules import Interaction_worker
        conf = PetConfig.init_config('Draconia', FrameStore(ACTION, scale=0.25))
        engine_state(self)
        now = [0.0]

        class Worker:
            pet_conf = conf
            clock = staticmethod(lambda: now[0])
        act = conf.act_dict['happy']
        frame_s = act.frame_refresh
        rows = []
        for tick in range(120):
            Interaction_worker.img_from_act(Worker(), act, wrap=False)
            rows.append((now[0], settings.act_frame_shown))
            now[0] += 0.021 + (0.150 if tick == 30 else 0.0)   # one tick runs 150 ms late
        for t, shown in rows:
            with self.subTest(t=t):
                self.assertLessEqual(abs(shown - int(t / frame_s + 1e-9)), 1)
        after = [(t, s) for t, s in rows if t > 0.8]
        self.assertTrue(all(s == int(t / frame_s + 1e-9) for t, s in after), 'back on the schedule')

    def test_animation_pacing_survives_a_late_frame_and_keeps_the_distance(self):
        from DyberPet import settings
        from DyberPet.conf import PetConfig
        from DyberPet.frames import FrameStore
        from DyberPet.modules import Animation_worker, frame_step
        conf = PetConfig.init_config('Draconia', FrameStore(ACTION, scale=0.25))
        engine_state(self)

        class Worker:
            pet_conf = conf
            _run_act = Animation_worker._run_act
            _away_from_wall = Animation_worker._away_from_wall
            _move = Animation_worker._move
            is_paused = is_killed = _skip = False
            wall_side = None
        worker = Worker()
        clock = [10.0]
        sleeps = []

        def sleep(s):
            sleeps.append(s)
            clock[0] += s + (0.2 if len(sleeps) == 10 else 0.0)   # the 10th frame runs 200 ms late
        worker._clock, worker._sleep = (lambda: clock[0]), sleep
        act = conf.right
        total = len(act.images) * act.act_num
        self.assertEqual(total, 64)
        index = {img.cacheKey(): i for i, img in enumerate(act.images)}
        rows, moved = [], []
        worker.sig_setimg_anim = unittest.mock.Mock(emit=lambda: rows.append((clock[0], index[settings.current_img.cacheKey()])))
        worker.sig_repaint_anim = unittest.mock.Mock()
        worker.sig_walk_done = unittest.mock.Mock()
        worker.sig_move_anim = unittest.mock.Mock(emit=lambda x, y: moved.append(x))
        worker._run_act(act)
        frame_s = act.frame_refresh
        n = len(act.images)
        for t, i in rows:
            with self.subTest(t=t):
                off = abs(i - ((t - 10.0) / frame_s) % n)
                self.assertLessEqual(min(off, n - off), 1.0 + 1e-6, 'within one frame of schedule')
        self.assertEqual(rows[-1][1], len(act.images) - 1, 'the clip ends on its last frame')
        self.assertLess(len(rows), total, 'the missed frames were skipped, not shown late')
        self.assertAlmostEqual(sum(moved), total * frame_step(act, scale=0.5)[0], places=6,
                               msg='every frame was walked: the speed does not drop')
        self.assertLessEqual(clock[0] - 10.0, total * frame_s + 1e-6, 'the clip is not stretched')
        worker.sig_walk_done.emit.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
