"""D2.2 behaviour contracts: three new Draconia clips (mirror, quill, yawn) and the owner's icon.

Owner: "Haz 2 o 3 animaciones más que vayan con Draconia" and, for the icon, "el primero cuadrado
me gustó más". Each new clip is 73 frames of 515x460 RGBA at 12 fps, starting on and fading back
to her stand_0 pose. mirror and quill join her idle pool; yawn plays once, complete, whenever she
falls asleep (yawn -> doze -> sleep).

The pet contracts run the real `Interaction_worker`, `PetWidget._companion_play_pose`,
`PetWidget._companion_micro_context`, `CompanionDirector`, `CompanionMicroTicker`, the life mixin and the
`TalkController` on the M3.3 stand-in window, in a fresh interpreter with one injected clock.
Standard library unittest + PySide6, no network. No test reads source text.
"""
import json
import os
import random
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path

from test_d21_naps_icon_gates import evaluate_spec, load
from test_engine_m33 import FRAME, RIG, TALK_TICK, TICK, due, first, frames_of, run_pet

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / 'full-engine'
ROLE = ENGINE / 'res' / 'role' / 'Draconia'
ACTION = ROLE / 'action'
BRAIN = ENGINE / 'data' / 'draconia_brain.json'
NEW = ('mirror', 'quill', 'yawn')
N = 73
CLIP_S = N * FRAME            # 6.083 s at 12 fps
SOURCE_W, SOURCE_H = 515, 460


def qt_app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def frame_count(group):
    return len(list(ACTION.glob(group + '_*.png')))


def act_conf():
    return json.loads((ROLE / 'act_conf.json').read_text(encoding='utf-8'))


def pet_conf():
    return json.loads((ROLE / 'pet_conf.json').read_text(encoding='utf-8'))


def in_order(shown, name):
    return [s[2] for s in frames_of(shown, name)]


# --- 1. The three clips are registered in her role, at 12 fps and full length ---------------------

class RegisteredInHerRole(unittest.TestCase):
    def test_73_frames_of_515x460_rgba_each(self):
        for group in NEW:
            with self.subTest(group):
                self.assertEqual(frame_count(group), N)
                for i in range(N):
                    png = (ACTION / ('%s_%d.png' % (group, i))).read_bytes()
                    self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
                    self.assertEqual(struct.unpack('>IIBB', png[16:26]), (SOURCE_W, SOURCE_H, 8, 6),
                                     '%s_%d: 515x460, 8-bit RGBA' % (group, i))

    def test_the_engine_reads_them_at_12_fps_and_full_length(self):
        qt_app()
        from DyberPet.conf import PetConfig
        from DyberPet.frames import FrameStore, LazyFrames
        conf = PetConfig.init_config('Draconia', FrameStore(ACTION, scale=0.25))
        for group in NEW:
            with self.subTest(group):
                spec = act_conf()[group]
                self.assertNotIn('frames', spec, 'no subset: the whole clip')
                act = conf.act_dict[group]
                self.assertAlmostEqual(act.frame_refresh, 1 / 12.0, places=9)
                self.assertEqual(act.act_num, 1, 'plays once')
                self.assertIsInstance(act.images, LazyFrames, 'decoded through the FrameStore')
                self.assertEqual(list(act.images.names), ['%s_%d' % (group, i) for i in range(N)])
                self.assertIn(group, conf.act_name, 'in her action list (the director plays it by name)')

    def test_her_random_sleep_act_opens_with_the_yawn(self):
        sleep = [a for a in pet_conf()['random_act'] if a['name'] == 'Sleep']
        self.assertEqual([a['act_list'] for a in sleep], [['yawn', 'doze', 'sleep']])


class CacheBudget(unittest.TestCase):
    """The D2 method: every pinned group, then the clips she plays, at Pet Scale 1.0 (frames at the
    source size at DPR 1.0 and 1.5). The new clips are on-demand groups, never pinned."""

    def measure(self, dpr, extra):
        from DyberPet.frames import PINNED_GROUPS, FrameStore
        store = FrameStore(ACTION, scale=1.0, dpr=dpr)
        for group in list(PINNED_GROUPS) + list(extra):
            self.assertTrue(store.prefetch(store.group_names(group)).wait(240), group)
            store.frame(group + '_0')
        return store

    def test_the_new_clips_are_on_demand_and_the_budget_holds(self):
        from DyberPet.frames import KEEP_RECENT, MAX_BYTES, PINNED_GROUPS, physical_size
        self.assertTrue(set(NEW).isdisjoint(PINNED_GROUPS), 'on-demand clips, not pinned')
        self.assertEqual(KEEP_RECENT, 2)
        for dpr in (1.5, 1.0):
            with self.subTest(dpr=dpr):
                w, h = physical_size(SOURCE_W, SOURCE_H, 1.0, dpr)
                self.assertEqual((w, h), (SOURCE_W, SOURCE_H))
                store = self.measure(dpr, NEW)
                cached = store.cached_groups()
                self.assertTrue(set(PINNED_GROUPS) <= set(cached))
                self.assertEqual(set(cached) - set(PINNED_GROUPS), {'quill', 'yawn'},
                                 'the oldest on-demand clip (mirror) was dropped')
                self.assertLessEqual(store.cached_bytes(), MAX_BYTES)
                print('\n[d2.2] pinned + mirror, quill, yawn at DPR %.1f, Pet Scale 1.0: %s, %.1f MB'
                      % (dpr, sorted(set(cached) - set(PINNED_GROUPS)), store.cached_bytes() / 2 ** 20))
                store.close()

    def test_her_worst_case_is_unchanged_and_within_the_budget(self):
        """Worst case = the pinned groups + her two largest on-demand groups (KEEP_RECENT), every
        frame at the source size. The new 73-frame clips are smaller than climb/drag/fall (96)."""
        from DyberPet.frames import KEEP_RECENT, MAX_BYTES, PINNED_GROUPS
        groups = {p.name.rsplit('_', 1)[0] for p in ACTION.glob('*.png')}
        counts = {g: frame_count(g) for g in groups}
        on_demand = sorted((counts[g] for g in groups if g not in PINNED_GROUPS), reverse=True)
        worst_frames = sum(counts[g] for g in PINNED_GROUPS) + sum(on_demand[:KEEP_RECENT])
        frame_bytes = SOURCE_W * SOURCE_H * 4
        worst = worst_frames * frame_bytes
        self.assertEqual(on_demand[:KEEP_RECENT], [96, 96])
        self.assertTrue(all(counts[g] < 96 for g in NEW))
        self.assertLessEqual(worst, MAX_BYTES)
        print('\n[d2.2] worst case: %d pinned + %d on-demand frames = %.1f MB (budget %.0f MB)'
              % (sum(counts[g] for g in PINNED_GROUPS), sum(on_demand[:KEEP_RECENT]), worst / 2 ** 20,
                 MAX_BYTES / 2 ** 20))
        store = self.measure(1.0, ['climb', 'drag', 'mirror', 'quill', 'yawn', 'fall'])
        self.assertLessEqual(store.cached_bytes(), MAX_BYTES)
        self.assertIn('fall', store.cached_groups(), 'the newest group is kept')
        store.close()


class AssetGates(unittest.TestCase):
    def names(self):
        return ['res/role/Draconia/action/%s_%d.png' % (g, i) for g in NEW for i in range(N)]

    def test_the_asset_policy_accepts_them(self):
        policy = load('asset_policy_d22', ENGINE / 'packaging' / 'asset_policy.py')
        for name in self.names():
            for prefix in ('', 'full-engine/', 'MiniDraconia/_internal/'):
                self.assertIsNone(policy.violation(prefix + name), prefix + name)

    def test_the_spec_bundles_them(self):
        work = Path(tempfile.mkdtemp(prefix='d22-spec-'))
        self.addCleanup(shutil.rmtree, work, True)
        datas = evaluate_spec(ENGINE, work)['Analysis'][0]['datas']
        bundled = {(Path(src), dest) for src, dest in datas}
        for name in self.names():
            self.assertIn((ENGINE / name, str(Path(name).parent)), bundled, name)

    def test_the_release_scan_has_no_finding_for_them(self):
        scan = load('scan_release_d22', REPO / 'scripts' / 'scan_release.py')
        root = Path(tempfile.mkdtemp(prefix='d22-scan-'))
        self.addCleanup(shutil.rmtree, root, True)
        target = root / 'full-engine' / 'res' / 'role' / 'Draconia' / 'action'
        target.mkdir(parents=True)
        for name in self.names():
            shutil.copyfile(ENGINE / name, target / Path(name).name)
        for name in ('act_conf.json', 'pet_conf.json'):
            shutil.copyfile(ROLE / name, target.parent / name)
        report = scan.scan_tree(root)
        self.assertEqual(report['findings'], [])
        self.assertEqual(report['review'], [])
        self.assertEqual(report['stats']['files'], 3 * N + 2)


# --- 2. Idle variety: mirror and quill join her pool, weighted by mood ------------------------------

class IdleVariety(unittest.TestCase):
    def available(self):
        return set(act_conf()) | {'climb_down'}

    def pool(self):
        from DyberPet.companion_director import load_role_idle_poses
        return load_role_idle_poses(ROLE / 'pet_conf.json')

    def moods(self):
        from DyberPet.companion_director import load_mood_table
        return load_mood_table(BRAIN)

    def director(self, seed, dominant=None):
        qt_app()
        from DyberPet.companion_director import CompanionDirector
        played = []
        director = CompanionDirector(get_available_poses=self.available, play_action=played.append,
                               is_busy=lambda: False, rng=random.Random(seed), system_idle_fn=None,
                               idle_pool=self.pool(), mood_table=self.moods() if dominant else None,
                               get_dominant_mood=(lambda: dominant) if dominant else None)
        director.weights = {'idle': 1.0}
        return director, played

    def test_the_weights(self):
        pool = self.pool()
        self.assertEqual((pool['mirror'], pool['quill']), (1.5, 1.5))
        self.assertNotIn('yawn', pool, 'the yawn only comes before sleep')
        self.assertEqual(max(pool, key=pool.get), 'tea', 'tea is still her favourite')
        self.assertTrue(set(pool) <= self.available())

    def test_her_idle_ticks_play_them_and_never_repeat_one_of_the_last_three(self):
        for seed in (1, 7, 32):
            director, played = self.director(seed)
            for _ in range(300):
                director._tick_once()                   # the real idle tick, action forced to idle
            with self.subTest(seed=seed):
                self.assertEqual(len(played), 300)
                self.assertIn('mirror', played)
                self.assertIn('quill', played)
                self.assertNotIn('yawn', played)
                for i in range(len(played) - 3):
                    self.assertEqual(len(set(played[i:i + 4])), 4, (i, played[i:i + 4]))

    def share(self, dominant, pose, draws=3000):
        director, played = self.director(11, dominant)
        for _ in range(draws):
            director._tick_once()
        return played.count(pose) / float(draws)

    def pick_share(self, dominant, pose, draws=6000):
        """The mood weighting alone: her pool and mood table, no recent poses."""
        from DyberPet.companion_director import choose_fresh_idle_pose
        rng, pool, table, available = random.Random(3), self.pool(), self.moods(), self.available()
        picks = [choose_fresh_idle_pose(rng, pool, (), available, dominant, table) for _ in range(draws)]
        return picks.count(pose) / float(draws)

    def test_mirror_suits_the_happy_moods_and_quill_the_content_one(self):
        table = self.moods()
        self.assertEqual(table['mirror'], {'happy': 1.8, 'excited': 1.8, 'sleepy': 0.5})
        self.assertEqual(table['quill'], {'content': 1.8, 'excited': 0.6})
        mirror = {m: self.pick_share(m, 'mirror') for m in ('happy', 'excited', 'content', 'sleepy')}
        quill = {m: self.pick_share(m, 'quill') for m in ('content', 'happy', 'excited')}
        self.assertGreater(mirror['happy'], 1.3 * mirror['content'])
        self.assertGreater(mirror['excited'], 1.3 * mirror['content'])
        self.assertLess(mirror['sleepy'], 0.75 * mirror['content'])
        self.assertGreater(quill['content'], 1.3 * quill['happy'])
        self.assertLess(quill['excited'], 0.8 * quill['happy'])
        # The real idle tick (with the no-repeat rule) keeps the direction.
        self.assertGreater(self.share('happy', 'mirror'), self.share('content', 'mirror'))
        self.assertGreater(self.share('content', 'quill'), self.share('happy', 'quill'))

    def test_an_older_profile_gets_the_bundled_mood_entries_for_the_new_clips(self):
        from DyberPet.companion_director import merge_mood_tables
        bundled = self.moods()
        old = {k: v for k, v in bundled.items() if k not in ('mirror', 'quill')}
        old['tea'] = {'content': 9.0}                    # the user's own edit
        merged = merge_mood_tables(old, bundled)
        self.assertEqual(merged['mirror'], bundled['mirror'])
        self.assertEqual(merged['quill'], bundled['quill'])
        self.assertEqual(merged['tea'], {'content': 9.0}, "the profile's entries win")
        self.assertEqual(merge_mood_tables(None, bundled), bundled)
        self.assertEqual(merge_mood_tables(old, None), old)
        self.assertEqual(merge_mood_tables('broken', bundled), bundled)

    def test_the_random_animation_shares_them_and_keeps_the_sleep_act(self):
        qt_app()
        from DyberPet.conf import PetConfig
        from DyberPet.frames import FrameStore
        from DyberPet.modules import NOT_IDLE_CLIPS, Animation_worker
        conf = PetConfig.init_config('Draconia', FrameStore(ACTION, scale=0.25))
        director, _ = self.director(5)

        class Worker:
            pet_conf = conf
            idle_picker = staticmethod(director.pick_idle_pose)
        names = [Animation_worker._fresh_idle(Worker(), [conf.act_dict['happy'], conf.default])[0].act_name
                 for _ in range(120)]
        self.assertIn('mirror', names)
        self.assertIn('quill', names)
        self.assertIn('yawn', NOT_IDLE_CLIPS)
        sleep_act = conf.random_act[conf.act_name.index('Sleep')]
        self.assertEqual([a.act_name for a in sleep_act], ['yawn', 'doze', 'sleep'])
        self.assertIs(Animation_worker._fresh_idle(Worker(), sleep_act), sleep_act,
                      'the yawn that opens her Sleep act is never swapped for an idle pose')


# --- 3. Yawn before sleep, proven on the injected clock ---------------------------------------------

SLEEP_RIG = RIG + '''
from DyberPet.companion_director import CompanionDirector, CompanionMicroTicker

class SleepPet(Pet):
    _companion_micro_context = PetWidget._companion_micro_context
    _companion_available_poses = PetWidget._companion_available_poses

def sleep_rig(weights, sleep_after_s=300.0):
    """The real pet path, director and micro ticker on one clock. The director ticks only when a
    test asks (`at`), the micro ticker every 150 ms (7 engine ticks), as in the pet."""
    global Pet
    plain, Pet = Pet, SleepPet          # the whole rig (talk controller included) on SleepPet
    try:
        r = Rig()
    finally:
        Pet = plain
    pet = r.pet
    r.log = []
    r.director = CompanionDirector(
        get_available_poses=pet._companion_available_poses, play_action=pet._companion_play_pose,
        is_busy=lambda: settings.draging == 1 or pet._life_holds_animation(),
        weights=weights, sleep_after_s=sleep_after_s, rng=random.Random(4), system_idle_fn=None,
        now_fn=r.clock, on_log=r.log.append, nap_warmup_s=0.0, nap_quiet_s=0.0,
        nap_min_mean_interval_s=1e-6)
    pet.companion_director = r.director
    r.ticker = CompanionMicroTicker(get_context=pet._companion_micro_context, play_action=pet._companion_play_pose,
                              apply_cursor_flip=lambda flip: None, on_edge=lambda side: None,
                              now_fn=r.clock, rng=random.Random(5), climb_cfg={'enabled': False},
                              handle_talk=False,
                              is_talking=lambda: bool(pet.talk_controller.active))
    return r

def run_sleep(r, until, at=()):
    pending = sorted(at, key=lambda e: e[0])
    tick = 0
    while r.clock.t < until - 1e-9:
        while pending and r.clock.t >= pending[0][0] - 1e-9:
            pending.pop(0)[1]()
        r.w.run()
        if tick % 7 == 0:
            r.ticker.tick()
        r.clock.t = round(r.clock.t + 0.021, 6)
        tick += 1
    out = r.result()
    out['log'] = r.log
    out['asleep'] = r.director.is_asleep
    out['stage'] = r.ticker._sleep_stage
    return out

out = {}

# A random nap: one director tick decides it at 0.5 s.
r = sleep_rig({'idle': 1e-9, 'sleep': 1.0})
out['nap'] = run_sleep(r, 30.0, at=[(0.5, r.director._tick_once)])
out['nap_wake_at'] = r.director.state.wake_at

# The same nap, followed to her waking: the director ticks every 6.5 s as in her role.
r = sleep_rig({'idle': 1e-9, 'sleep': 1.0})
woke = []
def director_tick():
    if not woke:
        r.director._tick_once()
        if r.log and r.log[-1] == 'wake':
            woke.append(round(r.clock.t, 3))
out['nap_wake'] = run_sleep(r, 140.0, at=[(0.5 + 6.5 * k, director_tick) for k in range(22)])
out['nap_wake']['woke'] = woke

# Away sleep: nobody touched her for sleep_after_s.
r = sleep_rig({'idle': 1.0}, sleep_after_s=1.0)
out['away'] = run_sleep(r, 22.0, at=[(1.5, r.director._tick_once),
                                     (20.0, r.director.note_interaction)])

# Sleep starts while she is dragged: no yawn; once she is back on the floor, doze/sleep as today.
r = sleep_rig({'idle': 1.0})
def grabbed():
    settings.draging, settings.onfloor = 1, 0
    r.w.start_interact('mousedrag')
    r.director._go_to_sleep('nap')
def dropped():
    settings.draging, settings.onfloor = 0, 1
    r.w.stop_interact()
out['dragged'] = run_sleep(r, 6.0, at=[(0.5, grabbed), (2.0, dropped)])
settings.draging, settings.onfloor = 0, 1

# Sleep starts while she is falling (not on the floor, not dragged): no yawn either.
r = sleep_rig({'idle': 1.0})
def falling():
    settings.onfloor = 0
    r.director._go_to_sleep('nap')
def landed():
    settings.onfloor = 1
out['falling'] = run_sleep(r, 6.0, at=[(0.5, falling), (2.0, landed)])
settings.draging, settings.onfloor = 0, 1

# A yawn interrupted by an interaction (a click or the cursor over her) wakes her as today.
r = sleep_rig({'idle': 1e-9, 'sleep': 1.0})
out['interrupted'] = run_sleep(r, 12.0, at=[(0.5, r.director._tick_once),
                                            (2.0, r.director.note_interaction)])
print(json.dumps(out))
'''


class YawnBeforeSleep(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = run_pet(SLEEP_RIG, timeout=300)

    def names(self, o):
        return [s[0] for s in o['starts']]

    def assert_yawn_then_doze_then_sleep(self, o, decided_at):
        names = self.names(o)
        self.assertEqual(names[:3], ['yawn', 'doze', 'sleep'])
        self.assertEqual(in_order(o['shown'], 'yawn'), list(range(N)), 'the whole yawn, once, in order')
        yawn_at, doze_at = first(o['starts'], 'yawn'), first(o['starts'], 'doze')
        self.assertGreaterEqual(yawn_at, decided_at - 1e-6)
        self.assertLessEqual(yawn_at - decided_at, 0.15 + TICK + 1e-6, 'within one micro tick')
        last_yawn = frames_of(o['shown'], 'yawn')[-1][0]
        self.assertGreaterEqual(doze_at, yawn_at + CLIP_S - TICK - 1e-6, 'doze only after the yawn')
        self.assertGreater(doze_at, last_yawn)
        self.assertLessEqual(doze_at - (yawn_at + CLIP_S), 0.15 + 2 * TICK + 1e-6)
        self.assertEqual(in_order(o['shown'], 'doze')[:frame_count('doze')], list(range(frame_count('doze'))))
        sleep_at = first(o['starts'], 'sleep')
        self.assertGreaterEqual(sleep_at, doze_at + frame_count('doze') * FRAME - TICK - 1e-6)

    def test_a_random_nap_yawns_once_complete_then_doze_then_sleep(self):
        o = self.out['nap']
        self.assertEqual(len(o['log']), 1)
        self.assertRegex(o['log'][0], r'^nap \d+$')
        self.assert_yawn_then_doze_then_sleep(o, due(0.5))
        self.assertEqual(self.names(o).count('yawn'), 1, 'one yawn, not one per sleep loop')
        self.assertEqual(set(self.names(o)[2:]), {'sleep'}, 'then she sleeps on')
        self.assertTrue(o['asleep'])

    def test_waking_from_the_nap_is_unchanged(self):
        o = self.out['nap_wake']
        self.assertEqual(o['log'][0].split()[0], 'nap')
        self.assertEqual(o['log'][1:], ['wake'])
        self.assertEqual(len(o['woke']), 1)
        names = self.names(o)
        self.assertEqual(names[:3], ['yawn', 'doze', 'sleep'])
        self.assertEqual(names[-1], 'wake', 'the wake clip, as before')
        self.assertEqual(names.count('yawn'), 1, 'no yawn on waking')
        self.assertEqual(first(o['starts'], 'wake'), o['woke'][0])
        self.assertFalse(o['asleep'])
        self.assertIsNone(o['stage'])

    def test_away_sleep_yawns_too_and_an_interaction_wakes_her(self):
        o = self.out['away']
        self.assertEqual(o['log'], ['away sleep', 'wake'])
        self.assert_yawn_then_doze_then_sleep(o, due(1.5))
        self.assertEqual(self.names(o)[-1], 'wake')
        self.assertEqual(first(o['starts'], 'wake'), due(20.0))

    def test_no_yawn_when_sleep_starts_while_she_is_dragged(self):
        o = self.out['dragged']
        names = self.names(o)
        self.assertNotIn('yawn', names)
        self.assertNotIn('yawn', [s[1] for s in o['shown']])
        self.assertIn('sleep', names, 'back on the floor she sleeps as today')
        self.assertGreaterEqual(first(o['starts'], 'sleep'), due(2.0))

    def test_no_yawn_when_sleep_starts_while_she_is_falling(self):
        o = self.out['falling']
        names = self.names(o)
        self.assertNotIn('yawn', names)
        self.assertIn('sleep', names)
        self.assertGreaterEqual(first(o['starts'], 'sleep'), due(2.0))

    def test_an_interaction_during_the_yawn_wakes_her_as_today(self):
        o = self.out['interrupted']
        self.assertEqual(o['log'][1:], ['wake'])
        names = self.names(o)
        self.assertEqual(names, ['yawn', 'wake'], 'no doze or sleep after she woke')
        self.assertEqual(first(o['starts'], 'wake'), due(2.0), 'at once')
        yawn = frames_of(o['shown'], 'yawn')
        self.assertLess(yawn[-1][0], due(2.0) + 1e-6, 'the yawn stops there')
        self.assertLess(len(yawn), N)
        self.assertFalse(o['asleep'])
        self.assertIsNone(o['stage'])


class SleepStages(unittest.TestCase):
    def test_first_and_next_stage(self):
        from DyberPet.companion_director import first_sleep_stage, next_sleep_stage
        hers = {'yawn', 'doze', 'sleep'}
        self.assertEqual(first_sleep_stage(hers), 'yawn')
        self.assertEqual(first_sleep_stage(hers, dragging=True), 'doze')
        self.assertEqual(first_sleep_stage(hers, on_floor=False), 'doze')
        self.assertEqual(first_sleep_stage({'doze', 'sleep'}), 'doze', 'a role without a yawn: as before')
        self.assertEqual(first_sleep_stage({'sleep'}), 'sleep')
        self.assertEqual(first_sleep_stage({'yawn', 'sleep'}, dragging=True), 'sleep')
        self.assertEqual(next_sleep_stage('yawn', hers), 'doze')
        self.assertEqual(next_sleep_stage('yawn', {'yawn', 'sleep'}), 'sleep')
        self.assertEqual(next_sleep_stage('doze', hers), 'sleep')
        self.assertEqual(next_sleep_stage('sleep', hers), 'sleep')


# --- 4. A stored line over the new clips follows the M3.3 rules -------------------------------------

LINES_RIG = RIG + '''
out = {}
def clip_then(pose, line_at, until):
    r = Rig()
    r.pet._companion_play_pose(pose)
    r.run(until, at=[(line_at, lambda: r.line(12.0))])
    return r.result()

for pose in ('mirror', 'quill', 'yawn'):
    out[pose + '_ends_soon'] = clip_then(pose, SOON_AT, 9.0)
    out[pose + '_ends_late'] = clip_then(pose, 1.0, 6.0)

# Plain playback: 12 fps from the start of the clip.
r = Rig()
r.pet._companion_play_pose('quill')
r.run(7.0)
out['plain'] = r.result()

# The random animation's clip (the shared idle pool picked mirror): it finishes, then the line.
r = Rig()
anim = Animation_worker(conf)
anim._clock = r.clock
shown, released, said = [], [], []
def sleep(s):
    r.clock.t = round(r.clock.t + s, 6)
    if not said and r.clock.t >= 4.5:
        said.append(1)
        r.line(12.0)
anim._sleep = sleep
anim.sig_setimg_anim.connect(lambda: shown.append([round(r.clock.t, 3), settings.anim_act.act_name]))
anim.sig_clip_released.connect(lambda: released.append(round(r.clock.t, 3)))
anim.sig_clip_released.connect(r.pet._life_talk_tick)
r.pet.workers['Animation'] = anim
anim._run_acts([conf.act_dict['mirror']])
out['anim'] = {'shown': shown, 'released': released, 'starts': r.starts}
print(json.dumps(out))
'''.replace('SOON_AT', repr(round(CLIP_S - 1.0, 3)))


class LinesOverTheNewClips(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = run_pet(LINES_RIG, timeout=300)

    def test_the_clips_play_at_12_fps(self):
        o = self.out['plain']
        quill = frames_of(o['shown'], 'quill')
        self.assertEqual([s[2] for s in quill], list(range(N)))
        start = quill[0][0]
        for t, _, k in quill:
            self.assertLessEqual(abs(t - (start + k * FRAME)), TICK + 1e-6, (t, k))

    def test_a_clip_ending_within_2_5_s_plays_to_its_end_before_the_line(self):
        for pose in NEW:
            with self.subTest(pose):
                o = self.out[pose + '_ends_soon']
                self.assertEqual(in_order(o['shown'], pose), list(range(N)), 'never cut mid-way')
                self.assertEqual([s[0] for s in o['starts']], [pose, 'talk'])
                talk_at = first(o['starts'], 'talk')
                self.assertGreaterEqual(talk_at, CLIP_S - 1e-6)
                self.assertLessEqual(talk_at, CLIP_S + TICK + 1e-6, 'talk starts at the clip end')
                self.assertEqual(o['bubbles'], [due(round(CLIP_S - 1.0, 3))], 'the bubble is not delayed')

    def test_a_longer_remainder_hands_over_at_the_next_natural_point_within_2_5_s(self):
        """These clips have no step markers: their only natural point is their end, 5 s away, so
        the line takes over at the 2.5 s limit, the clip running on frame by frame until then."""
        for pose in NEW:
            with self.subTest(pose):
                o = self.out[pose + '_ends_late']
                talk_at = first(o['starts'], 'talk')
                line_at = due(1.0)
                self.assertGreaterEqual(talk_at - line_at, 2.5 - TICK)
                self.assertLessEqual(talk_at - line_at, 2.5 + TICK + 1e-6)
                shown = in_order(o['shown'], pose)
                self.assertEqual(shown, list(range(len(shown))), 'in order until then, no frame skipped')
                self.assertGreater(len(shown), int(3.4 / FRAME))

    def test_the_random_animation_finishes_mirror_then_hands_over(self):
        o = self.out['anim']
        self.assertEqual(len(o['shown']), N, 'every frame of mirror')
        self.assertEqual({s[1] for s in o['shown']}, {'mirror'})
        self.assertEqual(len(o['released']), 1)
        self.assertAlmostEqual(o['released'][0], CLIP_S, delta=FRAME)
        self.assertEqual([s[0] for s in o['starts']], ['talk'])


# --- The owner's icon -------------------------------------------------------------------------------

class OwnersIcon(unittest.TestCase):
    """Provenance contract, not a hash pin: the icon is the square portrait from her own stand_0
    frame, the rights review and the changelog say so, and the exe/windows/tray use these files."""

    def test_square_portrait_png_and_multi_size_ico(self):
        png = (ENGINE / 'res' / 'icons' / 'app.png').read_bytes()
        self.assertEqual(struct.unpack('>IIBB', png[16:26]), (1024, 1024, 8, 6))
        ico = (ENGINE / 'res' / 'icons' / 'app.ico').read_bytes()
        count = struct.unpack('<HHH', ico[:6])[2]
        self.assertEqual([ico[6 + 16 * k] or 256 for k in range(count)], [16, 24, 32, 48, 64, 128, 256])
        import importlib.util
        spec = importlib.util.spec_from_file_location('policy_d22', ENGINE / 'packaging' / 'asset_policy.py')
        policy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(policy)
        for data in (png, ico):      # no private name (git-ignored markers file) in the icon bytes
            low = data.lower()
            for name in policy.OTHER_PRODUCT_NAMES:
                self.assertNotIn(name.encode('utf-8'), low)

    def test_the_provenance_is_recorded(self):
        rights = (REPO / 'docs' / 'RIGHTS-REVIEW.md').read_text(encoding='utf-8')
        for needle in ('app.png', 'app.ico', 'stand_0', 'square portrait', 'chosen by the maintainer'):
            self.assertIn(needle, rights)
        self.assertNotIn('provisional choice', rights)
        changelog = (REPO / 'CHANGELOG.md').read_text(encoding='utf-8')
        self.assertIn('square portrait', changelog)


class Docs(unittest.TestCase):
    def test_changelog_and_rights_review_record_the_clips(self):
        changelog = (REPO / 'CHANGELOG.md').read_text(encoding='utf-8')
        for needle in ('mirror', 'quill', 'yawn', 'yawn → doze → sleep'):
            self.assertIn(needle, changelog)
        rights = (REPO / 'docs' / 'RIGHTS-REVIEW.md').read_text(encoding='utf-8')
        for needle in ('mirror_', 'quill_', 'yawn_', 'Grok Imagine', '2026-11-07', 'stand_0',
                       'admires her reflection', 'writes a quick note', 'covers a big elegant yawn'):
            self.assertIn(needle, rights)
        self.assertNotIn('request_id', rights)
        for request_id in ('1b8bd6bb', '1004051b', '8ce97c80'):
            self.assertNotIn(request_id, rights, 'prompts are recorded, request IDs are not')


if __name__ == '__main__':
    unittest.main()
