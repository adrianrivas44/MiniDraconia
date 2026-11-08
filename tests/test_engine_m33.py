"""Cut M3.3 engine contracts on Draconia: no animation is cut.

Ported from the M3.3 behaviour contracts of the shared engine and adapted to Draconia's own
sprites: every "73 frames / about 6 s" is now that clip's real length, read from her role
(shy, the blush, 43 frames; happy 49; read and tea 73; talk 39; climb, her broom ride, 96;
stand 97; each walk 16 frames x 4 with measured step markers [7, 15]). All her clips play at
12 fps. Standard library unittest + PySide6, no network, fake clocks.

The pet contracts run the real `Interaction_worker`, `Animation_worker`, `PetWidget._companion_play_pose`,
`resume_animation`, `_move_customized`, the life mixin (`_life_say_line`, `_life_talk_stop`, ...),
`TalkController` and, for the climb, the real `CompanionMicroTicker` with its `ClimbSession`, in a fresh
interpreter on a stand-in window (pynput, which needs an X display only to be imported, is
stubbed there). The talk timer (40 ms in the pet) is a tick every 2 interaction ticks (42 ms);
the micro timer (150 ms) every 7.
"""
import json
import os
import random
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / 'full-engine'
ROLE = ENGINE / 'res' / 'role' / 'Draconia'
ACTION = ROLE / 'action'

FRAME = 1 / 12.0           # every Draconia clip plays at 12 fps
TICK = 0.021               # interaction tick (pet_conf interact_speed)
TALK_TICK = 2 * TICK       # the talk timer, as driven here
STEP_ENDS = [7, 15]        # last frame of each step of her 16-frame walks (both feet planted)
WALK_N = 16


def frame_count(group):
    return len(list(ACTION.glob(group + '_*.png')))


def clip_seconds(action):
    """One full clip of an act_conf action from the role files: frames x act_num x frame_refresh."""
    conf = json.loads((ROLE / 'act_conf.json').read_text(encoding='utf-8'))[action]
    n = len(conf['frames']) if conf.get('frames') else frame_count(conf['images'])
    return n * conf.get('act_num', 1) * conf.get('frame_refresh', 0.5)


SHY_N, READ_N, CLIMB_N = frame_count('shy'), frame_count('read'), frame_count('climb')
SHY_S, READ_S = SHY_N * FRAME, READ_N * FRAME


def due(t):
    """The engine tick (k * 21 ms) at which an event scheduled for `t` fires in the rig."""
    k = 0
    while round(k * TICK, 6) < t - 1e-9:
        k += 1
    return round(k * TICK, 6)


def qt_app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def run_python(code, env_extra, timeout=180):
    env = dict(os.environ)
    env.update(env_extra)
    env['PYTHONPATH'] = str(ENGINE) + os.pathsep + env.get('PYTHONPATH', '')
    proc = subprocess.run([sys.executable, '-c', code], env=env, cwd=str(ENGINE),
                          capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise AssertionError('subprocess failed (%d):\n%s\n%s' % (proc.returncode, proc.stdout[-3000:], proc.stderr[-6000:]))
    lines = [l for l in proc.stdout.splitlines() if l.startswith('{')]
    return json.loads(lines[-1])


PRELUDE = """
import json, math, os, random, sys, types
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
from DyberPet.draconia_reactions import install_broom

settings.petname = 'Draconia'
settings.onfloor, settings.draging, settings.set_fall = 1, 0, 1
settings.screens = []
settings.focus_timer_on = False
settings.pet_display_scale = settings.tunable_scale = 0.5
settings.pet_data = SimpleNamespace(hp_tier=3, fv_lvl=0)
store = frames.FrameStore(os.environ['ACTION'], scale=0.5, dpr=1.0)
conf = PetConfig.init_config('Draconia', store)
install_broom(conf)                     # the real pet: her fall/prefall is the broom (climb) clip
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
        self.is_paused = True
    def pause(self): pass
    def resume(self): self.resumed += 1
    def skip_clip(self): self.skipped += 1

class Pet(PetLifeMixin):
    \"\"\"A stand-in window running the real PetWidget move path and pose entry point.\"\"\"
    _move_customized = PetWidget._move_customized
    limit_in_screen = PetWidget.limit_in_screen
    _companion_play_pose = PetWidget._companion_play_pose
    resume_animation = PetWidget.resume_animation
    _companion_stop_follow_cursor = PetWidget._companion_stop_follow_cursor

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
"""


def run_pet(code, timeout=180):
    return run_python(PRELUDE + code, {
        'QT_QPA_PLATFORM': 'offscreen', 'ACTION': str(ACTION), 'ROLE': str(ROLE),
        'MINIDRACONIA_TEST_PROFILE': os.environ['MINIDRACONIA_TEST_PROFILE']}, timeout=timeout)


RIG = '''
from DyberPet.talk_controller import TalkController
from DyberPet.modules import FINISH_CLIP_S
Pet(centre_x=600)._life_add_climb_down()        # the real pet adds this runtime clip at start

class TimedAnimation(FakeAnimation):
    def __init__(self, clock):
        FakeAnimation.__init__(self)
        self.clock, self.resumes = clock, []
    def resume(self):
        FakeAnimation.resume(self)
        self.resumes.append(round(self.clock.t, 3))

class Rig:
    """The real pet path on the stand-in window with one fake clock."""
    def __init__(self, centre_x=600):
        self.clock = clock = Clock()
        self.pet = pet = Pet(centre_x=centre_x)
        self.w = w = interaction_for(pet, clock)
        pet.workers['Animation'] = self.anim = TimedAnimation(clock)
        self.shown, self.starts, self.bubbles, self.events = [], [], [], []
        w.sig_setimg_inter.connect(lambda: self.shown.append(
            [round(clock.t, 3), settings.current_act.act_name, settings.act_frame_shown]))
        pet.set_img = lambda: self.shown.append([round(clock.t, 3), 'STAND', 0])
        original = w.start_interact
        def start(interact, act_name=None, loop=False, start_frame=0):
            self.starts.append([act_name, round(clock.t, 3)])
            original(interact, act_name, loop=loop, start_frame=start_frame)
        w.start_interact = start
        pet._companion_show_bubble = lambda bubble: self.bubbles.append(round(clock.t, 3))
        pet.companion_voice = SimpleNamespace(speak=lambda text, cfg=None: None, cancel=lambda: None,
                                        current_wav=None)
        pet.talk_controller = TalkController(play_pose=pet._life_talk_play, stop_pose=pet._life_talk_stop,
                                             now_fn=clock, on_release=pet._life_release_line,
                                             clip_s=pet._life_clip_s, body_busy=pet._life_body_busy)

    def line(self, seconds, pose=None, voiced=False):
        """What _conv_show_reply does: the bubble (held for a voiced line), then the emotion."""
        self.pet._life_say_line('line', {'text': 'line', 'timeout': seconds}, {'enabled': voiced})
        self.pet._life_begin_talk(pose)

    def run(self, until, at=()):
        """Tick the engine until `until`; `at`: [(time, callable)] fired once when due."""
        pending = sorted(at, key=lambda e: e[0])
        tick = 0
        while self.clock.t < until - 1e-9:
            while pending and self.clock.t >= pending[0][0] - 1e-9:
                pending.pop(0)[1]()
            self.w.run()
            if tick % 2 == 0:
                self.pet._life_talk_tick()
            self.clock.t = round(self.clock.t + 0.021, 6)
            tick += 1

    def result(self):
        return {'shown': self.shown, 'starts': self.starts, 'bubbles': self.bubbles,
                'active': self.pet.talk_controller.active, 'interact': self.w.interact,
                'resumes': self.anim.resumes, 'events': self.events}
'''



def frames_of(shown, name, start=None, end=None):
    return [s for s in shown if s[1] == name and (start is None or s[0] >= start - 1e-9)
            and (end is None or s[0] < end - 1e-9)]


def first(starts, name, after=-1.0):
    times = [s[1] for s in starts if s[0] == name and s[1] > after]
    return times[0] if times else None


# --- 1 and 3. Emotion clips play complete; talk stops at once at the line's end ------------------

class EmotionClipsPlayComplete(unittest.TestCase):
    CODE = RIG + '''
out = {}
r = Rig(); r.line(12.0, 'shy'); r.run(13.0); out['long'] = r.result()
r = Rig(); r.line(3.0, 'shy'); r.run(7.0); out['short'] = r.result()
r = Rig()
r.line(8.0, 'happy', voiced=True)
r.run(9.5, at=[(0.5, lambda: r.pet._life_voice_started(8.0))])
out['voiced'] = r.result()
out['clip_s'] = {p: Rig().pet._life_clip_s(p) for p in ('shy', 'happy', 'tea', 'read', 'climb', 'right_walk')}
out['broom'] = conf.fall is conf.act_dict['climb'] and conf.prefall is conf.act_dict['climb']
print(json.dumps(out))
'''

    @classmethod
    def setUpClass(cls):
        cls.out = run_pet(cls.CODE)

    def assert_complete(self, shown, name):
        frames = [s[2] for s in frames_of(shown, name)]
        self.assertEqual(frames, list(range(frame_count(name))), '%s: every frame once, in order' % name)

    def test_the_pet_reports_the_real_clip_length(self):
        c = self.out['clip_s']
        for pose in ('shy', 'happy', 'tea', 'read', 'climb', 'right_walk'):
            self.assertAlmostEqual(c[pose], clip_seconds(pose), places=6, msg=pose)
        self.assertAlmostEqual(c['shy'], 43 * FRAME, places=6, msg='the blush is 43 frames')
        self.assertAlmostEqual(c['climb'], 96 * FRAME, places=6, msg='the broom ride, 12 fps')
        self.assertAlmostEqual(c['right_walk'], 16 * 4 * FRAME, places=6)
        self.assertTrue(self.out['broom'], 'v1: her fall is the broom clip')

    def test_blush_plays_one_full_clip_then_talk_for_the_rest_of_the_line(self):
        o = self.out['long']
        self.assertEqual([s[0] for s in o['starts']], ['shy', 'talk'])
        self.assert_complete(o['shown'], 'shy')
        talk_at = first(o['starts'], 'talk')
        self.assertGreaterEqual(talk_at, SHY_S - 1e-6, 'not cut at 1.8 s any more')
        self.assertLessEqual(talk_at, SHY_S + TALK_TICK + 1e-6)
        self.assertGreater(len(frames_of(o['shown'], 'talk')), 60, 'talk for the rest of the line')

    def test_talk_stops_at_once_when_the_line_ends_and_she_stands(self):
        o = self.out['long']
        talk = frames_of(o['shown'], 'talk')
        self.assertLessEqual(talk[-1][0], 12.0 + TALK_TICK + 1e-6,
                             'no talk frame later than one talk tick after the line')
        stand = [s for s in o['shown'] if s[1] == 'STAND']
        self.assertEqual(len(stand), 1)
        self.assertLessEqual(stand[0][0] - 12.0, TALK_TICK + 1e-6, 'stops within one talk tick')
        self.assertIsNone(o['interact'])
        self.assertFalse(o['active'])
        self.assertTrue(o['resumes'], 'normal life resumes')

    def test_a_line_shorter_than_the_clip_is_all_emotion_and_the_clip_still_finishes(self):
        o = self.out['short']
        self.assertEqual([s[0] for s in o['starts']], ['shy'], 'no talk forced')
        self.assert_complete(o['shown'], 'shy')
        self.assertNotIn('talk', [s[1] for s in o['shown']])
        self.assertFalse(o['active'])
        self.assertTrue(o['resumes'])
        self.assertGreaterEqual(min(o['resumes']), SHY_S - 1e-6, 'normal life only after the clip')
        self.assertNotIn('STAND', [s[1] for s in o['shown']], 'an emotion clip is not cut to stand')

    def test_voiced_line_emotion_complete_then_talk_until_the_voice_ends(self):
        o = self.out['voiced']
        self.assertEqual(o['bubbles'], [due(0.5)], 'bubble with the voice (M3.1 sync)')
        self.assertEqual([s[0] for s in o['starts']], ['think', 'happy', 'talk'],
                         'nothing was playing: she thinks while the voice is synthesised')
        self.assert_complete(o['shown'], 'happy')
        voice_end = due(0.5) + 8.0
        self.assertLessEqual(frames_of(o['shown'], 'talk')[-1][0], voice_end + TALK_TICK + 1e-6)
        stand = [s for s in o['shown'] if s[1] == 'STAND']
        self.assertLessEqual(stand[0][0] - voice_end, TALK_TICK + 1e-6)

    def test_shy_has_a_good_weight_in_her_idle_pool_and_flustered_is_the_blush(self):
        # Draconia's rule: the blush is in her role's idle pool with weight >= 1.5.
        from DyberPet.companion_director import load_role_idle_poses
        from DyberPet.brain_client import EMOTION_POSES
        pool = load_role_idle_poses(ROLE / 'pet_conf.json')
        self.assertIn('shy', pool)
        self.assertGreaterEqual(pool['shy'], 1.5)
        self.assertEqual(EMOTION_POSES['flustered'], 'shy')
        self.assertEqual(EMOTION_POSES['shy'], 'shy')

    def test_emote_fallback_is_only_used_when_the_clip_length_is_unknown(self):
        from DyberPet.talk_controller import EMOTE_S, TalkController
        lengths = [clip_seconds(p) for p in ('shy', 'happy', 'angry', 'bored', 'tea')]
        self.assertTrue(min(lengths) <= EMOTE_S <= max(lengths), 'a length of one of her clips')
        clock = [0.0]
        for clip_s, expected in ((lambda pose: 3.0, 3.0), (lambda pose: None, EMOTE_S)):
            talk = TalkController(lambda p: None, lambda p: None, now_fn=lambda: clock[0], clip_s=clip_s)
            talk.say(30.0, pose='shy')
            talk.tick(state='animat')
            self.assertAlmostEqual(talk._emote_until - clock[0], expected, places=6)


# --- 2. A line never cuts a clip mid-way ---------------------------------------------------------

class LinesNeverCutAClip(unittest.TestCase):
    CODE = RIG + '''
out = {}
def idle_then(line_at, seconds=12.0, pose=None, voiced=False, voice_at=None, until=9.0, extra=()):
    r = Rig()
    r.pet._companion_play_pose('read')                         # a director idle clip
    events = [(line_at, lambda: r.line(seconds, pose, voiced))]
    if voice_at is not None:
        events.append((voice_at, lambda: r.pet._life_voice_started(6.0)))
    r.run(until, at=events + list(extra))
    return r, r.result()

_, out['ends_soon'] = idle_then(5.0)
_, out['ends_late'] = idle_then(1.0)
_, out['voiced'] = idle_then(5.0, voiced=True, voice_at=5.4, until=12.0)

r = Rig()
def drag():
    settings.draging, settings.onfloor = 1, 0            # what a real press does
    r.w.start_interact('mousedrag')
    r.events.append(['finishing', r.pet._life_body_busy()])
r.pet._companion_play_pose('read')
r.run(2.0, at=[(1.0, lambda: r.line(12.0)), (1.5, drag)])
out['drag'] = r.result()
settings.draging, settings.onfloor = 0, 1

r = Rig()
def touch():
    r.pet._companion_play_pose('happy')                        # director: refused during a line
    r.pet._companion_play_pose('pinch', from_touch=True)       # touch reaction: at once
r.line(12.0)
r.run(6.0, at=[(2.0, touch)])
out['touch'] = r.result()

# The random animation's clip: it finishes, pauses and hands over (sig_clip_released).
def animation_case(acts, line_at):
    r = Rig()
    anim = Animation_worker(conf)
    anim._clock = r.clock
    shown, released = [], []
    said = []
    def sleep(s):
        r.clock.t = round(r.clock.t + s, 6)
        if not said and r.clock.t >= line_at:
            said.append(1)
            r.line(12.0)
    anim._sleep = sleep
    anim.sig_setimg_anim.connect(lambda: shown.append(
        [round(r.clock.t, 3), settings.anim_act.act_name, settings.current_img is not None]))
    anim.sig_clip_released.connect(lambda: released.append(round(r.clock.t, 3)))
    anim.sig_clip_released.connect(r.pet._life_talk_tick)
    anim.sig_move_anim.connect(r.pet._move_customized)
    r.pet.workers['Animation'] = anim
    centre0 = r.pet.centre()
    anim._run_acts(acts)
    return {'shown': shown, 'released': released, 'paused': anim.is_paused, 'starts': r.starts,
            'moved': r.pet.centre() - centre0}
out['anim_idle'] = animation_case([conf.act_dict['read']], 4.0)
out['anim_walk'] = animation_case([conf.right, conf.default], 1.6)
out['anim_stand'] = animation_case([conf.default], 1.0)
print(json.dumps(out))
'''

    @classmethod
    def setUpClass(cls):
        cls.out = run_pet(cls.CODE)

    def test_a_clip_ending_within_2_5_s_plays_to_its_end_first(self):
        o = self.out['ends_soon']
        self.assertEqual([s[2] for s in frames_of(o['shown'], 'read')], list(range(READ_N)))
        self.assertEqual([s[0] for s in o['starts']], ['read', 'talk'], 'no think, no cut')
        talk_at = first(o['starts'], 'talk')
        self.assertGreaterEqual(talk_at, READ_S - 1e-6)
        self.assertLessEqual(talk_at, READ_S + TICK + 1e-6, 'talk starts at the clip end')
        self.assertEqual(o['bubbles'], [due(5.0)], 'the bubble is not delayed')

    def test_a_long_clip_hands_over_no_later_than_2_5_s_after_the_line(self):
        from DyberPet.modules import FINISH_CLIP_S
        self.assertEqual(FINISH_CLIP_S, 2.5)
        o = self.out['ends_late']
        talk_at = first(o['starts'], 'talk')
        line_at = due(1.0)
        self.assertGreaterEqual(talk_at - line_at, 2.5 - TICK)
        self.assertLessEqual(talk_at - line_at, 2.5 + TICK + 1e-6)
        read = [s[2] for s in frames_of(o['shown'], 'read')]
        self.assertEqual(read, list(range(len(read))), 'the clip ran on, frame by frame, until then')

    def test_the_voice_wait_overlaps_the_clip_and_think_only_shows_when_nothing_plays(self):
        o = self.out['voiced']
        self.assertNotIn('think', [s[0] for s in o['starts']], 'a clip was playing: no think')
        self.assertEqual(o['bubbles'], [due(5.4)], 'bubble and voice start together (M3.1)')
        self.assertEqual([s[2] for s in frames_of(o['shown'], 'read')], list(range(READ_N)))
        self.assertAlmostEqual(first(o['starts'], 'talk'), READ_S, delta=TICK + 1e-6)
        self.assertLessEqual(frames_of(o['shown'], 'talk')[-1][0], due(5.4) + 6.0 + TALK_TICK + 1e-6)

    def test_drag_still_interrupts_at_once(self):
        o = self.out['drag']
        self.assertEqual(o['events'], [['finishing', False]], 'drag cancels the finishing clip')
        drag = frames_of(o['shown'], 'drag')
        self.assertTrue(drag)
        self.assertEqual(drag[0][0], due(1.5), 'the drag frame shows on the same tick')
        self.assertFalse(frames_of(o['shown'], 'read', start=due(1.5)), 'the idle clip is gone')
        self.assertNotIn('talk', [s[0] for s in o['starts']], 'never talks over the drag')

    def test_touch_reactions_interrupt_at_once_and_their_clip_finishes_too(self):
        o = self.out['touch']
        names = [s[0] for s in o['starts']]
        self.assertEqual(names, ['talk', 'pinch', 'talk'], 'the director pose was refused')
        pinch_at = first(o['starts'], 'pinch')
        self.assertEqual(pinch_at, due(2.0))
        self.assertTrue(frames_of(o['shown'], 'pinch'))
        back = first(o['starts'], 'talk', after=pinch_at)
        self.assertAlmostEqual(back - pinch_at, 2.5, delta=2 * TICK + 1e-6,
                               msg='talk comes back after the touch clip, by the 2.5 s rule')

    def test_the_random_animation_finishes_its_clip_then_pauses_for_the_line(self):
        o = self.out['anim_idle']
        self.assertEqual(len(o['shown']), READ_N, 'every frame of the random idle clip')
        self.assertEqual(len(o['released']), 1)
        self.assertAlmostEqual(o['released'][0], READ_S, delta=FRAME)
        self.assertTrue(o['paused'])
        self.assertEqual([s[0] for s in o['starts']], ['talk'])
        self.assertAlmostEqual(o['starts'][0][1], o['released'][0], delta=1e-6)

    def test_a_random_walk_finishes_its_step_and_skips_the_rest_of_its_list(self):
        o = self.out['anim_walk']
        self.assertEqual({s[1] for s in o['shown']}, {'right_walk'}, 'its default never starts')
        # 1.6 s is frame 19 (second loop, frame 3): that step ends on loop frame 7 = frame 23.
        self.assertEqual(len(o['shown']), 24, 'frames 0..23: the step under way at 1.6 s')
        self.assertAlmostEqual(o['released'][0], 24 * FRAME, delta=FRAME)
        self.assertGreater(o['moved'], 0)
        self.assertEqual([s[0] for s in o['starts']], ['talk'])

    def test_the_random_animation_stand_hands_over_at_once(self):
        o = self.out['anim_stand']
        self.assertEqual(len(o['released']), 1)
        self.assertLessEqual(o['released'][0] - 1.0, FRAME + 1e-6)
        self.assertEqual([s[0] for s in o['starts']], ['talk'])


# --- 4. Walks and follow finish their step ----------------------------------------------------------

class WalksFinishTheirStep(unittest.TestCase):
    CODE = RIG + '''
out = {}
r = Rig(centre_x=300)
r.pet._companion_play_pose('right_walk')
moves = []
r.run(4.0, at=[(1.6, lambda: moves.append(r.pet.centre())),
               (1.6, lambda: r.line(12.0))])
out['walk'] = dict(r.result(), centre_at_line=moves[0], centre_end=r.pet.centre())

r = Rig(centre_x=300)
r.w.query_position.connect(lambda name: r.w.receive_pos([r.pet.centre(), 0], [1250, 0]))
r.w.start_interact('followTarget', 'mouse')
r.run(4.0, at=[(1.0, lambda: r.line(12.0))])
out['follow'] = r.result()

# A walk without step markers hands over at once (documented rule).
from DyberPet.conf import Act
r = Rig(centre_x=300)
walks = [conf.right, conf.act_dict['right_walk']] + [a for acts in conf.random_act for a in acts
                                                     if getattr(a, 'act_name', None) == 'right_walk']
saved = [(a, a.step_ends) for a in walks]
for a in walks:
    a.step_ends = ()
r.pet._companion_play_pose('right_walk')
r.run(3.0, at=[(1.6, lambda: r.line(12.0))])
for a, ends in saved:
    a.step_ends = ends
out['plain'] = r.result()

out['steps'] = {'right': list(conf.right.step_ends), 'left': list(conf.left.step_ends)}
print(json.dumps(out))
'''

    @classmethod
    def setUpClass(cls):
        cls.out = run_pet(cls.CODE)

    def test_her_walks_carry_measured_step_markers(self):
        self.assertEqual(self.out['steps'], {'right': STEP_ENDS, 'left': STEP_ENDS})

    def test_a_director_walk_finishes_its_step_and_keeps_moving_until_then(self):
        o = self.out['walk']
        walk = frames_of(o['shown'], 'right_walk')
        self.assertEqual([s[2] for s in walk], list(range(len(walk))), 'no frozen frame')
        last = walk[-1][2]
        self.assertIn(last % WALK_N, STEP_ENDS, 'stops between two steps')
        self.assertEqual(last, 23, 'the step under way at 1.6 s (frame 19) ends on frame 23 (loop 2, frame 7)')
        talk_at = first(o['starts'], 'talk')
        self.assertGreaterEqual(talk_at, 24 * FRAME - 1e-6, 'frame 23 is shown in full')
        self.assertLessEqual(talk_at, 24 * FRAME + TICK + 1e-6)
        step = 5.16 * 0.5                     # frame_move x display scale, per frame
        self.assertGreaterEqual(o['centre_end'] - o['centre_at_line'], 3 * step,
                                'she kept walking to the step end')

    def test_follow_the_cursor_finishes_its_step(self):
        o = self.out['follow']
        walk = [s for s in o['shown'] if s[1] == 'right_walk' and s[0] < first(o['starts'], 'talk')]
        self.assertIn(walk[-1][2] % WALK_N, STEP_ENDS)
        self.assertLessEqual(first(o['starts'], 'talk') - due(1.0), 1.0, 'within one step')

    def test_a_walk_without_step_markers_stops_at_once(self):
        o = self.out['plain']
        self.assertEqual(first(o['starts'], 'talk'), due(1.6), 'on the tick the line arrives')

    def test_the_measurement_script_finds_those_steps(self):
        qt_app()
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            'measure_sprite_motion', REPO / 'scripts' / 'measure_sprite_motion.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.measure_steps(ROLE),
                         {'walkcycle_right': STEP_ENDS, 'walkcycle_left': STEP_ENDS})
        conf = json.loads((ROLE / 'act_conf.json').read_text(encoding='utf-8'))
        for walk in ('right_walk', 'left_walk'):
            self.assertEqual(conf[walk]['step_ends'], STEP_ENDS)
            self.assertEqual(conf[walk]['act_num'], 4)
        self.assertEqual(frame_count('walkcycle_right'), WALK_N)


# --- 5. Climb never shows a non-climb frame -----------------------------------------------------

class ClimbNeverShowsAnotherFrame(unittest.TestCase):
    CODE = RIG + '''
import DyberPet.companion_director as md
from DyberPet.companion_director import CompanionMicroTicker
outcomes = []
_release = md.climb_release_outcome
md.climb_release_outcome = lambda rng, *a: outcomes.append(_release(rng, *a)) or outcomes[-1]

def climb(seed, allow_fall=False):
    r = Rig(centre_x=1250)
    pet, w, clock = r.pet, r.w, r.clock
    anim = Animation_worker(conf)                        # the real random animation, paused
    anim.sig_setimg_anim.connect(lambda: r.shown.append([round(clock.t, 3), 'ANIM', -1]))
    pet.workers['Animation'] = anim
    floor = pet._y
    def ctx():
        return {'state': w.interact or 'default', 'dragging': False, 'at_edge': None,
                'pet_center_x': pet.centre(), 'cursor_x': 0, 'available_poses': set(conf.act_dict),
                'pos_y': float(pet._y), 'floor_y': float(floor), 'screen_top': 0.0,
                'screen_height': 760.0, 'walking_toward': None}
    log = []
    ticker = CompanionMicroTicker(get_context=ctx, play_action=pet._companion_play_pose,
                            apply_cursor_flip=lambda flip: None, on_edge=lambda side: None,
                            now_fn=clock, rng=random.Random(seed),
                            set_pos_y=lambda y: pet.move(pet._x, int(round(y))),
                            on_climb_log=log.append, allow_fall=lambda: allow_fall,
                            start_fall=lambda: None, get_climb_speed=pet._life_climb_speed,
                            hold_pose=pet._life_hold_climb_pose, handle_talk=False,
                            is_talking=lambda: False)
    pet.companion_micro_ticker = ticker
    del outcomes[:]
    ticker._start_climb('right', ctx(), clock.t)         # the edge decision, as on a wall touch
    samples, tick = [], 0
    while ticker.is_climbing and clock.t < 60:
        w.run()
        if tick % 7 == 0:
            ticker.tick()
        samples.append([round(clock.t, 3), ticker._climb.phase if ticker._climb else None,
                        w.interact, w.act_name])
        clock.t = round(clock.t + 0.021, 6)
        tick += 1
    climbing_until = clock.t
    for _ in range(20):
        w.run(); clock.t = round(clock.t + 0.021, 6)
    return {'shown': r.shown, 'samples': samples, 'until': climbing_until, 'log': log,
            'outcomes': list(outcomes), 'anim_paused': anim.is_paused, 'starts': r.starts,
            'y_end': pet._y, 'floor': floor}

out = {'runs': [climb(seed) for seed in range(6)],
       'climb': [len(conf.act_dict['climb'].images), conf.act_dict['climb'].frame_refresh,
                 conf.act_dict['climb'].frame_move],
       'down_is_reversed': list(conf.act_dict['climb_down'].images.names)
                           == list(conf.act_dict['climb'].images.names)[::-1]}
print(json.dumps(out))
'''

    @classmethod
    def setUpClass(cls):
        cls.out = run_pet(cls.CODE, timeout=300)
        cls.runs = cls.out['runs']

    def test_her_climb_is_the_broom_ride_and_climb_down_plays_it_backwards(self):
        n, refresh, move = self.out['climb']
        self.assertEqual(n, 96)
        self.assertAlmostEqual(refresh, FRAME, places=9)
        self.assertEqual(move, 7.0)
        self.assertTrue(self.out['down_is_reversed'])

    def climb_frames(self, run):
        return [s for s in run['shown'] if s[0] < run['until'] - 1e-9]

    def test_both_descents_are_driven(self):
        outcomes = {o for run in self.runs for o in run['outcomes']}
        self.assertEqual(outcomes, {'fall', 'walk_down'},
                         'released (Allow Drop off: climbs down) and walks down both covered')
        for run in self.runs:
            self.assertEqual(run['log'][0], 'trepa right')
            self.assertIn('baja', run['log'])
            self.assertEqual(run['y_end'], run['floor'], 'the descent ended on the floor')

    def test_every_frame_shown_while_climbing_is_a_climb_frame(self):
        for run in self.runs:
            names = {s[1] for s in self.climb_frames(run)}
            self.assertEqual(names, {'climb', 'climb_down'}, run['log'])

    def test_the_engine_never_falls_back_to_another_clip_while_climbing(self):
        for run in self.runs:
            for t, phase, interact, act_name in run['samples']:
                if phase is None:
                    continue                             # the tick she landed: climb over
                self.assertEqual(interact, 'animat', (t, phase))
                self.assertIn(act_name, ('climb', 'climb_down'), (t, phase))
            self.assertTrue(run['anim_paused'], 'the random animation stays paused')
            names = [s[0] for s in run['starts']]
            self.assertEqual(names[:2], ['climb', 'climb_down'],
                             'one climb clip up, one climb_down clip down: they loop')
            self.assertIn(names[2:], ([], ['default']), 'stand once she is back on the floor')

    def test_the_clip_loops_without_a_gap_while_she_moves(self):
        wraps = 0
        for run in self.runs:
            moving = {round(t, 3) for t, phase, _, _ in run['samples'] if phase in ('up', 'down')}
            frames = [s for s in self.climb_frames(run) if s[0] in moving]
            for a, b in zip(frames, frames[1:]):
                if a[1] != b[1]:
                    continue
                self.assertIn(b[2], ((a[2] + 1) % CLIMB_N, a[2] + 1), (a, b))
                self.assertLessEqual(b[0] - a[0], FRAME + TICK + 1e-6, (a, b))
                wraps += b[2] < a[2]
        self.assertGreater(wraps, 0, 'some climbs are longer than the 8 s clip: it wrapped')

    def test_hanging_holds_the_frame_and_climb_down_starts_on_it(self):
        self.assertTrue(any(phase == 'hold' for run in self.runs for _, phase, _, _ in run['samples']),
                        'at least one climb hangs on the wall')
        for run in self.runs:
            hold = [t for t, phase, _, _ in run['samples'] if phase == 'hold']
            if not hold:
                continue                                 # hit the ceiling: no hold
            during = [s for s in run['shown'] if hold[0] + TICK < s[0] < hold[-1]]
            self.assertEqual(during, [], 'nothing is drawn while she hangs')
            up = [s for s in run['shown'] if s[1] == 'climb']
            down = [s for s in run['shown'] if s[1] == 'climb_down']
            # climb_down starts on frame 95 - held, the very picture on screen (the clip is the
            # climb backwards), so the first redraw is the frame after it: no jump.
            held = up[-1][2] % CLIMB_N
            self.assertEqual(down[0][2] % CLIMB_N, (CLIMB_N - held) % CLIMB_N,
                             'continues from the held picture')


# --- The rule itself ------------------------------------------------------------------------------

class FinishRule(unittest.TestCase):
    def test_yield_time(self):
        from DyberPet.modules import yield_time
        f = FRAME
        # The end comes within the grace: wait for it.
        self.assertAlmostEqual(yield_time(0.0, 5.0, f, 7.5, total=73), 73 * f)
        # Too far: the first natural point due by the deadline, else the deadline.
        self.assertAlmostEqual(yield_time(0.0, 1.0, f, 3.5, total=73, points=[20, 30, 73]), 20 * f)
        self.assertAlmostEqual(yield_time(0.0, 1.0, f, 3.5, total=73, points=[73]), 3.5)
        # A looping clip has no end; never before now.
        self.assertAlmostEqual(yield_time(0.0, 1.0, f, 3.5, total=None, points=[5]), 3.5)
        self.assertAlmostEqual(yield_time(0.0, 9.0, f, 11.5, total=73), 9.0)

    def test_natural_points(self):
        from types import SimpleNamespace
        from DyberPet.modules import natural_points
        walk = SimpleNamespace(images=[0] * 73, step_ends=(1, 9, 70))
        self.assertEqual(natural_points(walk, 5, 80), [10, 71, 73, 75])
        idle = SimpleNamespace(images=[0] * 73, step_ends=())
        self.assertEqual(natural_points(idle, 5, 72), [])
        self.assertEqual(natural_points(idle, 5, 146), [73, 146])

    def test_natural_points_of_her_walk_count_on_across_its_4_loops(self):
        from types import SimpleNamespace
        from DyberPet.modules import natural_points
        walk = SimpleNamespace(images=[0] * WALK_N, step_ends=tuple(STEP_ENDS))
        self.assertEqual(natural_points(walk, 0, 4 * WALK_N), [8, 16, 24, 32, 40, 48, 56, 64])
        self.assertEqual(natural_points(walk, 19, 30), [24])

    def test_trail_and_a_late_voice(self):
        """The line ends during the emotion clip: no talk, the clip is not stopped; a voice that
        starts meanwhile still gets her talking when the clip ends."""
        from DyberPet.talk_controller import TalkController
        clock = [0.0]
        played, stopped = [], []
        talk = TalkController(played.append, stopped.append, now_fn=lambda: clock[0],
                        clip_s=lambda pose: 4.0)
        talk.say(2.0, pose='shy')
        talk.tick(state='animat')
        clock[0] = 2.1
        talk.tick(state='animat')
        self.assertEqual((talk.phase, stopped), ('trail', []))
        self.assertTrue(talk.active, 'the clip is still the line\'s: nothing else replaces it')
        talk.voice_started(3.0)
        clock[0] = 4.0
        talk.tick(state='animat')
        self.assertEqual(played, ['shy', 'talk'])
        clock[0] = 5.2
        talk.tick(state='animat')
        self.assertFalse(talk.active)
        self.assertEqual(stopped, ['talk'])


if __name__ == '__main__':
    unittest.main()
