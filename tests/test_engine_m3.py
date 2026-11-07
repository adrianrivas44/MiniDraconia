"""Engine M3 for Draconia: crisp frames, frames on demand, real walking, climbing, visibly talking.

Behaviour contracts, standard library unittest + Qt, no network. Owner feedback on the shared
engine (Windows 11, 1920x1200 at 150 %): "the quality must improve", "when she walks she stays
in the same place", "she only stays on the bottom", "when she talks it must show that she is
talking". Every clip length is read from Draconia's own sprites, never assumed.
"""
import json
import os
import random
import re
import inspect
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
import wave
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / 'full-engine'
ROLE = ENGINE / 'res' / 'role' / 'Draconia'
ACTION = ROLE / 'action'
SOURCE_W, SOURCE_H = 515, 460
OWNER_DPR = 1.5


def qt_app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def frame_count(group):
    """Frames of one clip in Draconia's sprite folder (e.g. 'angry' -> 49)."""
    pattern = re.compile(r'^%s_(\d+)\.png$' % re.escape(group))
    return sum(1 for p in ACTION.iterdir() if pattern.match(p.name))


def act_conf():
    return json.loads((ROLE / 'act_conf.json').read_text(encoding='utf-8'))


def pet_conf_json():
    return json.loads((ROLE / 'pet_conf.json').read_text(encoding='utf-8'))


def clip_seconds(act_name):
    """One full clip of an action as the engine plays it: its frames x act_num x frame_refresh."""
    conf = act_conf()[act_name]
    frames = len(conf['frames']) if conf.get('frames') else frame_count(conf['images'])
    return frames * conf.get('act_num', 1) * conf['frame_refresh']


def run_python(code, env_extra, timeout=120):
    """Run `code` in a fresh interpreter (Qt scale factor / settings must be set before start)."""
    env = dict(os.environ)
    env.update(env_extra)
    env['PYTHONPATH'] = str(ENGINE) + os.pathsep + env.get('PYTHONPATH', '')
    proc = subprocess.run([sys.executable, '-c', inspect.cleandoc(code)], env=env, cwd=str(ENGINE),
                          capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise AssertionError('subprocess failed (%d):\n%s\n%s' % (proc.returncode, proc.stdout, proc.stderr))
    lines = [l for l in proc.stdout.splitlines() if l.startswith('{')]
    return json.loads(lines[-1])


class MeasuredClipLengths(unittest.TestCase):
    def test_her_clips_are_not_73_frames(self):
        expected = {'angry': 49, 'bored': 49, 'bye': 45, 'climb': 96, 'doze': 60, 'drag': 96, 'fall': 96,
                    'greet': 47, 'hairflip': 41, 'happy': 49, 'onfloor': 44, 'patpat': 38, 'peek_right': 49,
                    'pinch': 50, 'read': 73, 'shy': 43, 'sit': 4, 'sleep': 26, 'slowclap': 49, 'spell': 69,
                    'stand': 97, 'stretch': 50, 'talk': 39, 'tea': 73, 'think': 49, 'touch_body': 32,
                    'wake': 36, 'walkcycle_right': 16, 'walkcycle_left': 16,
                    'mirror': 73, 'quill': 73, 'yawn': 73}                      # D2.2
        self.assertEqual({group: frame_count(group) for group in expected}, expected)


class CrispOnHighDpi(unittest.TestCase):
    """Frames are built at logical size x devicePixelRatio and never upscaled by Qt."""

    CODE = '''
        import json, os
        from PySide6.QtWidgets import QApplication, QLabel
        from PySide6.QtGui import QImageReader
        app = QApplication([])
        from DyberPet import frames
        out = {'screen_dpr': app.primaryScreen().devicePixelRatio(), 'cases': []}
        for scale in (0.5, 1.0, 0.3):
            label = QLabel()
            store = frames.FrameStore(os.environ['ACTION'], scale=scale, dpr=label.devicePixelRatioF())
            frames.present(label, store.frame('stand_0'))
            pix = label.pixmap()
            out['cases'].append({'scale': scale, 'pix_dpr': pix.devicePixelRatio(),
                                 'physical': [pix.width(), pix.height()],
                                 'label': [label.width(), label.height()],
                                 'scaled_contents': label.hasScaledContents(),
                                 'source': [QImageReader(os.environ['ACTION'] + '/stand_0.png').size().width(),
                                            QImageReader(os.environ['ACTION'] + '/stand_0.png').size().height()]})
        print(json.dumps(out))
    '''

    def test_label_pixmap_matches_screen_dpr_and_is_never_upscaled_at_150_percent(self):
        result = run_python(self.CODE, {'QT_QPA_PLATFORM': 'offscreen', 'QT_SCALE_FACTOR': '1.5',
                                        'ACTION': str(ACTION)})
        self.assertAlmostEqual(result['screen_dpr'], 1.5)
        for case in result['cases']:
            with self.subTest(scale=case['scale']):
                self.assertAlmostEqual(case['pix_dpr'], result['screen_dpr'])
                self.assertFalse(case['scaled_contents'])
                pw, ph = case['physical']
                sw, sh = case['source']
                self.assertLessEqual(pw, sw)
                self.assertLessEqual(ph, sh)
                # The label shows the pixmap 1:1: its logical size is the pixmap's physical / DPR.
                self.assertAlmostEqual(case['label'][1], ph / 1.5, delta=1)
        half = result['cases'][0]
        self.assertEqual(half['physical'], [386, 345])        # 460 x 0.5 x 1.5 physical rows
        self.assertAlmostEqual(half['label'][1], 230, delta=1)
        capped = result['cases'][1]
        self.assertEqual(capped['physical'], [515, 460], 'scale 1.0 at 150 %: capped at the source, not upscaled')
        self.assertAlmostEqual(capped['label'][1], 307, delta=1)

    def test_display_scale_and_physical_size(self):
        from DyberPet.frames import display_scale, physical_size
        self.assertEqual(physical_size(515, 460, 0.5, 1.5), (386, 345))
        self.assertEqual(physical_size(515, 460, 0.5, 1.0), (258, 230))
        self.assertEqual(physical_size(515, 460, 1.0, 2.0), (515, 460))
        self.assertAlmostEqual(display_scale(0.5, 1.5), 0.5)
        self.assertAlmostEqual(display_scale(1.0, 1.5), 1 / 1.5)
        self.assertAlmostEqual(display_scale(1.0, 1.0), 1.0)

    def test_pet_window_uses_the_exact_frames_without_scaled_contents(self):
        source = (ENGINE / 'DyberPet' / 'DyberPet.py').read_text(encoding='utf-8')
        self.assertIn('self.label.setScaledContents(False)', source)
        self.assertIn('pet_frames.present(self.label, img_to_show, mirror,', source)
        self.assertNotIn('_load_all_pic(pet_name)', source, 'the role is no longer decoded up front')
        self.assertIn('pet_frames.FrameStore(', source)


class FramesOnDemand(unittest.TestCase):
    def setUp(self):
        qt_app()
        from DyberPet.frames import FrameStore
        from DyberPet.conf import PetConfig
        self.store = FrameStore(ACTION, scale=0.5, dpr=1.0)
        self.conf = PetConfig.init_config('Draconia', self.store)

    def test_loading_the_role_decodes_nothing(self):
        self.assertEqual(list(self.store.decode_log), [])
        acts = act_conf()
        self.assertEqual(set(self.conf.act_dict), set(acts))
        for name, act in self.conf.act_dict.items():
            with self.subTest(name):
                conf = acts[name]
                expected = len(conf['frames']) if conf.get('frames') else frame_count(conf['images'])
                self.assertEqual(len(act.images), expected)
        self.assertEqual(list(self.store.decode_log), [], 'counting frames decodes nothing either')

    def test_playing_an_action_decodes_only_its_frames(self):
        frames = list(self.conf.act_dict['happy'].images)
        self.assertEqual(len(frames), frame_count('happy'))
        self.assertEqual(self.store.decoded_groups(), {'happy'})
        self.assertEqual(len(self.store.decode_log), frame_count('happy'))
        list(self.conf.act_dict['happy'].images)
        self.assertEqual(len(self.store.decode_log), frame_count('happy'), 'cached: a second loop decodes nothing')

    def test_engine_tick_reads_one_frame_not_the_whole_action(self):
        from DyberPet import settings
        from DyberPet.modules import Interaction_worker
        saved = {k: getattr(settings, k, None) for k in ('current_act', 'previous_act', 'anim_act', 'playid',
                                                          'current_img', 'previous_img', 'current_anchor',
                                                          'previous_anchor', 'tunable_scale', 'act_started_at',
                                                          'act_frame_shown')}
        self.addCleanup(lambda: [setattr(settings, k, v) for k, v in saved.items()])
        settings.current_act = settings.previous_act = settings.anim_act = None
        settings.current_img = settings.previous_img = None
        settings.current_anchor = settings.previous_anchor = [0, 0]
        settings.playid, settings.tunable_scale = 0, 0.5

        now = [0.0]

        class Worker:
            pet_conf = self.conf
            clock = staticmethod(lambda: now[0])
        act = self.conf.act_dict['angry']
        shown = []
        for _ in range(12):
            Interaction_worker.img_from_act(Worker(), act)
            shown.append(settings.act_frame_shown)
            now[0] += 0.021
        # 12 ticks of 21 ms at 1/12 s per frame (4 ticks per frame): frames 0, 1 and 2 only.
        self.assertEqual(shown, [0] * 4 + [1] * 4 + [2] * 4)
        # The rest of the clip is prefetched on the store's own thread; the tick itself decodes
        # at most the frames it shows.
        self.assertLessEqual(self.store.decodes_on(), 3)

    def test_idle_walk_and_talk_stay_warm_others_are_evicted(self):
        for name in ('default', 'right_walk', 'left_walk', 'talk', 'happy', 'angry', 'shy', 'bored'):
            self.conf.act_dict[name].images[0]
        cached = set(self.store.cached_groups())
        pinned = {'stand', 'walkcycle_right', 'walkcycle_left', 'talk'}
        self.assertTrue(pinned <= cached)
        self.assertEqual(cached - pinned, {'shy', 'bored'})

    def test_working_set_bound_at_the_owner_screen(self):
        """Owner: 150 % (DPR 1.5) at her default Pet Scale 1.0, capped to the source size. Pinned
        clips plus the two largest other clips, fully decoded, stay below 600 MB."""
        from DyberPet.frames import FrameStore, PINNED_GROUPS, physical_size
        w, h = physical_size(SOURCE_W, SOURCE_H, 1.0, OWNER_DPR)
        self.assertEqual((w, h), (SOURCE_W, SOURCE_H))
        frame_bytes = w * h * 4
        pinned = sum(frame_count(g) for g in PINNED_GROUPS)
        others = sorted((frame_count(g) for g in {p.stem.rsplit('_', 1)[0] for p in ACTION.glob('*.png')}
                         if g not in PINNED_GROUPS), reverse=True)
        bound = (pinned + others[0] + others[1]) * frame_bytes
        self.assertLess(bound, 600 * 2 ** 20)
        store = FrameStore(ACTION, scale=1.0, dpr=OWNER_DPR)
        for group in ('stand', 'talk', 'happy'):
            for i in range(frame_count(group)):
                store.frame('%s_%d' % (group, i))
        expected = sum(frame_count(g) for g in ('stand', 'talk', 'happy')) * frame_bytes
        self.assertEqual(store.cached_bytes(), expected)

    def test_rescale_or_new_dpr_drops_old_frames(self):
        first = self.store.frame('stand_0')
        self.assertTrue(self.store.configure(0.5, 1.5))
        second = self.store.frame('stand_0')
        self.assertAlmostEqual(second.devicePixelRatio(), 1.5)
        self.assertGreater(second.width(), first.width())
        self.assertFalse(self.store.configure(0.5, 1.5))

    def test_plain_pixmap_dicts_still_load(self):
        from PySide6.QtGui import QPixmap
        from DyberPet.conf import PetConfig
        pixel = QPixmap(1, 1)
        conf = PetConfig.init_config('Draconia', {p.stem: pixel for p in ACTION.glob('*.png')})
        self.assertEqual(len(conf.act_dict['default'].images), frame_count('stand'))

    def test_sit_holds_one_picture_instead_of_flickering(self):
        """Her sit clip has 4 frames that alternate two pictures (0 = 2, 1 = 3); played as a loop
        it flickered. The role holds frame 0 for the whole clip."""
        sit = self.conf.act_dict['sit']
        self.assertEqual(frame_count('sit'), 4)
        self.assertEqual(list(sit.images.names), ['sit_0'])
        self.assertGreaterEqual(sit.frame_refresh * sit.act_num, 2.0)


def measure_module():
    sys.path.insert(0, str(REPO / 'scripts'))
    try:
        import measure_sprite_motion
    finally:
        sys.path.remove(str(REPO / 'scripts'))
    return measure_sprite_motion


class RealWalking(unittest.TestCase):
    def test_walk_speed_is_the_measured_sprite_motion(self):
        """frame_move is the planted foot's travel over the whole 16-frame loop (held frames
        count as 0): the window travels exactly as far as her feet every loop."""
        measured = measure_module().measure(ROLE)
        acts = act_conf()
        for act, images in (('right_walk', 'walkcycle_right'), ('left_walk', 'walkcycle_left')):
            with self.subTest(act):
                speed, frames = measured[images]
                self.assertEqual(frames, frame_count(images))
                self.assertAlmostEqual(acts[act]['frame_move'], speed, delta=0.05 * speed)
                self.assertAlmostEqual(acts[act]['frame_move'], 5.16)
                self.assertEqual(acts[act]['step_ends'], [7, 15])

    def test_climb_is_her_broom_ride_at_12_fps(self):
        """Her climb clip is a broom ride (no hand holds that could slide), so its speed is a
        design choice, not a measurement: 7.0 sprite px per 1/12 s frame."""
        climb = act_conf()['climb']
        self.assertEqual(climb['images'], 'climb')
        self.assertAlmostEqual(climb['frame_move'], 7.0)
        self.assertAlmostEqual(climb['frame_refresh'], 1 / 12)

    def test_per_frame_move_scales_with_the_pet(self):
        from DyberPet.conf import Act
        from DyberPet.modules import frame_step
        walk = Act(images=[], need_move=True, direction='right', frame_move=5.16)
        self.assertEqual(frame_step(walk, scale=0.5), (2.58, 0.0))
        self.assertEqual(frame_step(walk, scale=1.0), (5.16, 0.0))
        self.assertEqual(frame_step(walk, 'left', scale=0.5), (-2.58, 0.0))
        self.assertEqual(frame_step(Act(images=[]), scale=0.5), (0.0, 0.0))

    def test_a_walk_travels_visibly(self):
        """One walk clip (16 frames x act_num) on the owner's screen at her default size (shown
        at 1/1.5) travels more than 200 logical px, about two thirds of her own width."""
        from DyberPet.modules import frame_step
        from DyberPet.conf import Act
        conf = act_conf()['right_walk']
        frames = frame_count(conf['images']) * conf['act_num']
        walk = Act(images=[None] * frames, need_move=True, direction='right', frame_move=conf['frame_move'])
        travelled = sum(frame_step(walk, scale=1 / OWNER_DPR)[0] for _ in walk.images)
        self.assertGreater(travelled, 200)

    def test_both_workers_and_the_window_use_the_scaled_step(self):
        modules = (ENGINE / 'DyberPet' / 'modules.py').read_text(encoding='utf-8')
        self.assertEqual(modules.count('plus_x, plus_y = frame_step(act)'), 2)
        pet = (ENGINE / 'DyberPet' / 'DyberPet.py').read_text(encoding='utf-8')
        self.assertIn('_move_remainder', pet, 'fractional steps are kept, not truncated away')


class ClimbingAndEdges(unittest.TestCase):
    def ticker(self, ctx, **kwargs):
        from DyberPet.mia_director import MiaMicroTicker
        self.clock = [100.0]
        self.played, self.events = [], []
        played = self.played
        kwargs.setdefault('climb_cfg', {'enabled': True, 'prob': 1.0, 'speed': 40.0, 'hold_s': [5.0, 5.0]})
        return MiaMicroTicker(
            get_context=lambda: dict(ctx),
            play_action=lambda pose: pose == 'blink' or played.append(pose),  # the role has no blink clip
            apply_cursor_flip=lambda flip: self.events.append(('flip', flip)),
            on_edge=lambda side: self.events.append(('edge', side)),
            now_fn=lambda: self.clock[0], rng=random.Random(1),
            set_pos_y=lambda y: self.events.append(('y', round(y, 2))),
            start_fall=lambda: self.events.append(('fall',)),
            hold_pose=lambda: self.events.append(('hold',)),
            on_climb_start=lambda side: self.events.append(('snap', side)),
            get_climb_speed=lambda: 22.5, handle_talk=False, **kwargs)

    def test_climbing_is_on_by_default_and_the_toggle_still_exists(self):
        from DyberPet.mia_director import DEFAULT_CLIMB_CFG, load_climb_config
        self.assertTrue(DEFAULT_CLIMB_CFG['enabled'])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(load_climb_config(Path(tmp) / 'missing.json')['enabled'])
            off = Path(tmp) / 'brain.json'
            off.write_text(json.dumps({'climb': {'enabled': False}}), encoding='utf-8')
            self.assertFalse(load_climb_config(off)['enabled'], "the user's toggle wins")
        self.assertTrue(load_climb_config(ENGINE / 'data' / 'draconia_brain.json')['enabled'])
        pet = (ENGINE / 'DyberPet' / 'DyberPet.py').read_text(encoding='utf-8')
        visible = pet.split('self.StatMenu = RoundMenu(parent=self)', 1)[1].split('\n    def ', 1)[0]
        self.assertIn('self.StatMenu.addActions([self.mia_climb_toggle])', visible,
                      'the Climb walls toggle is in the visible menu')

    def test_climb_speed_matches_the_frame_period(self):
        from DyberPet.mia_director import climb_speed_px_s, frame_period_s
        self.assertAlmostEqual(frame_period_s(1 / 12, 0.02), 0.1)    # a 20 ms tick shows 5 ticks
        self.assertAlmostEqual(frame_period_s(1 / 12, 0.021), 0.084)  # the 21 ms tick shows 4
        self.assertAlmostEqual(frame_period_s(1 / 24, 0.021), 0.042)
        self.assertAlmostEqual(climb_speed_px_s(7.0, 1 / 1.5, 1 / 12, 0.021), 7.0 / 1.5 / 0.084)
        self.assertAlmostEqual(climb_speed_px_s(7.0, 1.0, 1 / 12, 0.021), 7.0 / 0.084)

    def test_edge_climb_loops_the_clip_holds_still_and_climbs_down_backwards(self):
        ctx = {'state': 'default', 'at_edge': 'right', 'pos_y': 500.0, 'floor_y': 500.0,
               'screen_top': 0.0, 'screen_height': 800.0,
               'available_poses': {'climb', 'climb_down', 'peek', 'fall', 'default'}}
        ticker = self.ticker(ctx)
        with unittest.mock.patch('DyberPet.mia_director.climb_release_outcome', return_value='walk_down'), \
                unittest.mock.patch('DyberPet.mia_director.climb_target_frac', return_value=0.2):
            ticker.tick()
            self.assertEqual(self.played, ['climb'])
            self.assertIn(('snap', 'right'), self.events)
            self.assertTrue(ticker.is_climbing)
            ctx['state'] = 'animat'
            self.clock[0] += 1.0
            ticker.tick()
            self.assertEqual(self.played, ['climb'], 'clip still running: not restarted')
            self.assertIn(('y', 477.5), self.events, '22.5 px/s up')
            ctx['state'] = 'default'                 # the clip was stopped from outside mid-climb
            self.clock[0] += 0.15
            ticker.tick()
            self.assertEqual(self.played, ['climb', 'climb'], 'played again while still moving')
            self.clock[0] += 10.0                    # reaches the target (160 px up): hangs
            ticker.tick()
            self.assertIn(('hold',), self.events)
            n = len(self.played)
            self.clock[0] += 1.0
            ticker.tick()
            self.assertEqual(len(self.played), n, 'hanging still: no clip restarted')
            self.clock[0] += 5.0                     # hold over -> climbs down
            ticker.tick()
            self.assertEqual(self.played[-1], 'climb_down')

    def test_reaching_the_top_falls(self):
        ctx = {'state': 'default', 'at_edge': 'left', 'pos_y': 300.0, 'floor_y': 300.0,
               'screen_top': 0.0, 'screen_height': 800.0, 'available_poses': {'climb', 'fall'}}
        ticker = self.ticker(ctx)
        with unittest.mock.patch('DyberPet.mia_director.climb_target_frac', return_value=0.85):
            ticker.tick()
            self.assertEqual(self.played, ['climb'])
            self.assertIn(('flip', True), self.events, 'left wall: her climb art is mirrored')
            self.clock[0] += 60.0
            ticker.tick()
        self.assertEqual(self.played[-1], 'fall')
        self.assertIn(('fall',), self.events)
        self.assertFalse(ticker.is_climbing)

    def test_peek_with_her_sprites(self):
        from DyberPet.mia_director import peek_pose_for_side
        acts = act_conf()
        self.assertEqual(acts['peek']['images'], 'peek_right')
        self.assertEqual(peek_pose_for_side('right', set(acts)), ('peek', False))
        self.assertEqual(peek_pose_for_side('left', set(acts)), ('peek', True))
        self.assertEqual(acts[pet_conf_json()['fall']]['images'], 'fall')

    def test_a_later_walk_into_the_same_wall_decides_again(self):
        ctx = {'state': 'default', 'at_edge': 'right', 'walking_toward': None, 'available_poses': {'peek'}}
        ticker = self.ticker(ctx, climb_cfg={'enabled': False})
        ticker.tick()
        first = len([e for e in self.events if e[0] == 'edge'])
        self.assertEqual(first, 1)
        ticker._peek_until = None
        self.clock[0] += 0.15
        ticker.tick()
        self.assertEqual(len([e for e in self.events if e[0] == 'edge']), 1, 'standing at the wall: once')
        ctx['walking_toward'] = 'right'
        self.clock[0] += 2.0
        ticker.tick()
        self.assertEqual(len([e for e in self.events if e[0] == 'edge']), 2, 'walking into it: decide again')


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class VisiblyTalking(unittest.TestCase):
    def talk(self, **kwargs):
        from DyberPet.talk_controller import TalkController
        self.clock = FakeClock()
        self.played, self.stopped = [], []
        return TalkController(self.played.append, self.stopped.append, now_fn=self.clock, **kwargs)

    def run_for(self, talk, seconds, state=lambda: 'default', blocked=lambda: False, step=0.15):
        end = self.clock.t + seconds
        while self.clock.t < end - 1e-9:
            self.clock.t = round(self.clock.t + step, 6)
            talk.tick(state=state(), blocked=blocked())

    def test_emotion_full_clip_then_talk_loops_while_the_bubble_shows_then_stops(self):
        # The emotion plays one full clip (its length from the pet, here 1.8 s), not a cut.
        talk = self.talk(clip_s=lambda pose: 1.8)
        talk.say(bubble_s=6.0, voiced=False, pose='angry')
        talk.tick(state='default')
        self.assertEqual(self.played, ['angry'])
        self.run_for(talk, 1.5, state=lambda: 'animat')
        self.assertEqual(self.played, ['angry'], 'the emotion clip plays to its end')
        self.run_for(talk, 0.45, state=lambda: 'animat')
        self.assertEqual(self.played, ['angry', 'talk'])
        self.run_for(talk, 1.0, state=lambda: 'animat')
        self.run_for(talk, 0.15, state=lambda: 'default')     # talk clip ended, line still on
        self.assertEqual(self.played, ['angry', 'talk', 'talk'])
        self.run_for(talk, 3.0, state=lambda: 'animat')
        self.assertFalse(talk.active)
        self.assertEqual(self.stopped, ['talk'])
        self.run_for(talk, 2.0)
        self.assertEqual(self.played, ['angry', 'talk', 'talk'], 'normal behaviour after the line')

    def test_with_voice_she_talks_until_the_wav_ends_not_the_bubble(self):
        talk = self.talk()
        talk.say(bubble_s=3.0, voiced=True, pose=None)
        talk.tick()
        self.assertEqual(self.played, ['talk'])
        self.clock.t = 1.0
        talk.voice_started(6.5)
        self.run_for(talk, 6.0, state=lambda: 'animat')
        self.assertTrue(talk.active, 'bubble gone at 3 s, voice plays until 7.5 s')
        self.run_for(talk, 0.6, state=lambda: 'animat')
        self.assertFalse(talk.active)
        self.assertAlmostEqual(self.clock.t, 7.5, delta=0.16)

    def test_short_voice_ends_the_talk_early_and_a_failed_voice_uses_the_bubble(self):
        talk = self.talk()
        talk.say(bubble_s=8.0, voiced=True)
        talk.tick()
        talk.voice_started(1.2)
        self.run_for(talk, 1.5, state=lambda: 'animat')
        self.assertFalse(talk.active)
        talk.say(bubble_s=2.0, voiced=True)
        talk.voice_failed()
        self.run_for(talk, 1.8, state=lambda: 'animat')
        self.assertTrue(talk.active)
        self.run_for(talk, 0.3, state=lambda: 'animat')
        self.assertFalse(talk.active)

    def test_a_voice_that_starts_after_the_bubble_still_shows_talking(self):
        talk = self.talk()
        talk.say(bubble_s=1.0, voiced=True)
        self.run_for(talk, 1.2, state=lambda: 'animat')
        self.assertFalse(talk.active)
        talk.voice_started(2.0)
        talk.tick(state='default')
        self.assertTrue(talk.active)
        self.assertEqual(self.played[-1], 'talk')

    def test_never_interrupts_drag_or_fall(self):
        talk = self.talk()
        dragging = [True]
        talk.say(bubble_s=4.0, voiced=False, pose='shy')
        self.run_for(talk, 1.0, blocked=lambda: dragging[0])
        self.assertEqual(self.played, [], 'nothing played while dragged')
        dragging[0] = False
        self.run_for(talk, 0.15)
        self.assertEqual(self.played, ['shy'], 'free again with time left: she still says it')
        dragging[0] = True
        self.run_for(talk, 4.0, blocked=lambda: dragging[0])
        self.assertFalse(talk.active)
        self.assertEqual(self.stopped, [], 'ended during a drag: the drag animation is left alone')

    def test_talk_is_not_an_emotion_pose(self):
        talk = self.talk()
        talk.say(bubble_s=3.0, pose='talk')
        talk.tick()
        self.assertEqual(self.played, ['talk'])


class TalkWiring(unittest.TestCase):
    """The pet's life/conversation methods on a stub: every line (chat, events, chatter) goes
    through `_emit_mia_bubble` -> `talk_controller.say` and the reply's emotion becomes the
    talk's pose."""

    def setUp(self):
        qt_app()
        from DyberPet import settings
        self.settings = settings
        self.saved = {k: getattr(settings, k, None) for k in ('petname', 'draging', 'onfloor')}
        settings.petname, settings.draging, settings.onfloor = 'Draconia', 0, 1

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(self.settings, k, v)

    def stub(self, line_s=3.0):
        from DyberPet.pet_conversation import ConversationMixin
        from DyberPet.pet_life import PetLifeMixin
        from DyberPet.talk_controller import TalkController
        clock = FakeClock()

        class Interaction:
            interact, act_name = None, None
            stops = 0

            def stop_interact(self):
                Interaction.stops += 1
                self.interact = self.act_name = None

        class Animation:
            resumed = 0

            def resume(self):
                Animation.resumed += 1

        class Stub(PetLifeMixin, ConversationMixin):
            def __init__(self):
                self.poses, self.bubbles = [], []
                self.workers = {'Interaction': Interaction(), 'Animation': Animation()}
                # The emotion clip's real length comes from the role (angry: 49 frames at 12 fps).
                self.talk_controller = TalkController(self._mia_play_pose, self._life_talk_stop, now_fn=clock,
                                                      clip_s=clip_seconds)

            def _emit_mia_bubble(self, text, voice=None, wav=None):
                self.bubbles.append((text, voice))
                self.talk_controller.say(line_s, voiced=bool(voice))

            def _mia_play_pose(self, pose, **kwargs):
                self.poses.append(pose)
                self.workers['Interaction'].interact, self.workers['Interaction'].act_name = 'animat', pose

            def _mia_log(self, kind, text):
                pass
        return Stub(), clock

    def test_reply_emotion_full_clip_then_back_to_normal(self):
        # A 3 s line is shorter than her angry clip (49 frames, 4.08 s): the clip covers the whole
        # line, no talk is forced, and the line's end does not cut the clip.
        from DyberPet.brain_client import Reply
        angry_s = clip_seconds('angry')
        self.assertAlmostEqual(angry_s, 49 / 12)
        pet, clock = self.stub(line_s=3.0)
        pet._conv_show_reply(Reply('chat', 'Hmph. Fine.', 'angry', 'angry', 'relay'))
        self.assertEqual(pet.bubbles, [('Hmph. Fine.', True)])
        self.assertTrue(pet._life_holds_animation(), 'random walks stay paused while she talks')
        pet._life_talk_tick()
        self.assertEqual(pet.poses, ['angry'])
        clock.t = 2.0
        pet._life_talk_tick()
        self.assertEqual(pet.poses, ['angry'])
        clock.t = 3.1
        pet._life_talk_tick()
        self.assertTrue(pet._life_holds_animation(), 'the emotion clip finishes after the line')
        self.assertEqual(pet.workers['Interaction'].stops, 0)
        clock.t = angry_s + 0.05
        pet._life_talk_tick()
        self.assertFalse(pet._life_holds_animation())
        self.assertEqual(pet.poses, ['angry'], 'no talk was forced')

    def test_offline_and_own_key_replies_are_never_voiced(self):
        from DyberPet.brain_client import Reply
        for source in ('offline', 'own_key'):
            pet, clock = self.stub()
            pet._conv_show_reply(Reply('pat', 'One pat. I counted.', 'neutral', None, source))
            self.assertEqual(pet.bubbles, [('One pat. I counted.', False)], source)

    def test_drag_blocks_the_talk_poses(self):
        from DyberPet.brain_client import Reply
        pet, clock = self.stub()
        self.settings.draging = 1
        pet._conv_show_reply(Reply('drag', 'Put me down.', 'angry', 'angry', 'relay'))
        pet._life_talk_tick()
        self.assertEqual(pet.poses, [])

    def test_pet_window_feeds_the_controller(self):
        pet = (ENGINE / 'DyberPet' / 'DyberPet.py').read_text(encoding='utf-8')
        self.assertIn('self._life_say_line(text, bubble_dict, voice_cfg, wav=wav if pack_voice else None)', pet)
        self.assertIn('self.mia_voice.on_started = self._life_voice_started', pet)
        self.assertIn('on_release=self._life_release_line', pet)
        self.assertIn('clip_s=self._life_clip_s', pet)
        self.assertIn('self.talk_timer.timeout.connect(self._life_talk_tick)', pet)   # 40 ms
        self.assertIn('if self._life_holds_animation():', pet)


class VoiceDurationHook(unittest.TestCase):
    def test_voice_reports_the_wav_duration_when_playback_starts(self):
        qt_app()
        from DyberPet.mia_voice import MiaVoice, wav_seconds

        class Player:
            def __init__(self):
                self.played = []

            def play_file(self, path, volume):
                self.played.append(path)

            def stop(self):
                pass

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'line.wav'
            with wave.open(str(path), 'wb') as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(24000)
                w.writeframes(b'\x00\x00' * 24000 * 2 + b'\x00\x00' * 12000)
            self.assertAlmostEqual(wav_seconds(path), 2.5)
            self.assertEqual(wav_seconds(Path(tmp) / 'missing.wav'), 0.0)
            started, failed = [], []
            voice = MiaVoice(engine=None, player=Player(), tmp_dir=tmp)
            voice.on_started, voice.on_failed = started.append, lambda: failed.append(True)
            voice._volume = 0.5
            voice._token = 3
            voice._on_synth_done(str(path), 3)
            self.assertEqual(started, [2.5])
            voice._token = 4
            voice._on_synth_done('', 4)
            self.assertEqual(failed, [True])


if __name__ == '__main__':
    unittest.main()
