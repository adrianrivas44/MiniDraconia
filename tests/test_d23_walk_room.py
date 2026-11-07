"""D2.3 behaviour contracts: a random walk never heads into the wall she is already touching.

Windows E2E evidence (1024x768): after a walk reached the left edge the director kept choosing
`walk left` (a coin flip) and each of those walks ended after one frame (`walk end left_walk dx=-5
frames=1`). To the owner she "starts to walk and does nothing". Now a random walk (the director's
and the engine's random animation's) chooses its direction from her window's real position on her
screen: a side with less room than one full walk is not chosen, both sides with room keep the
coin flip; with no full walk either way she takes the roomier side if it holds half a walk (her
515 px window on a 1024 px screen), and on a screen too small even for that the tick is an idle
pose instead.

Standard library unittest + PySide6, no network, injected geometry and clocks. The pet-window
contracts run the real `PetWidget._mia_play_pose`, `_move_customized`, `limit_in_screen`, the
Interaction and Animation workers in a fresh interpreter (the M3.2 stand-in window). No test reads
source text.
"""
import json
import random
import unittest
from pathlib import Path
from types import SimpleNamespace

from test_d21_naps_icon_gates import Clock, POOL, make_director
from test_engine_m32 import run_pet

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / 'full-engine' / 'res' / 'role' / 'Draconia'
WALK_LOG = 'walk (left|right)'


def her_walk(direction):
    """Her walk act as the role defines it (act_conf.json + the frames on disk), duck-typed."""
    conf = json.loads((ROLE / 'act_conf.json').read_text(encoding='utf-8'))['%s_walk' % direction]
    frames = len(list((ROLE / 'action').glob('%s_*.png' % conf['images'])))
    return SimpleNamespace(images=[None] * frames, act_num=conf['act_num'], need_move=True,
                           direction=direction, frame_move=conf['frame_move'])


def full_walk_px(scale):
    """One full walk at `scale`, derived from the role (16 frames x 4 x 5.16 px today)."""
    act = her_walk('left')
    return len(act.images) * act.act_num * act.frame_move * scale


# --------------------------------------------------------------------------------------------
# The pure rule
# --------------------------------------------------------------------------------------------

class WalkRoomRule(unittest.TestCase):
    def test_full_walk_is_derived_from_her_role_at_the_current_scale(self):
        from DyberPet.mia_director import walk_distance
        for scale in (0.5, 2 / 3, 1.0, 1.5):
            with self.subTest(scale=scale):
                self.assertAlmostEqual(walk_distance([her_walk('left')], scale), full_walk_px(scale), places=6)
        self.assertTrue(200 <= walk_distance([her_walk('right')], 1.0) <= 340, 'about 220-330 px today')
        idle = SimpleNamespace(images=[None] * 40, act_num=1, need_move=False, direction=None, frame_move=0)
        self.assertEqual(walk_distance([her_walk('right'), idle], 1.0), walk_distance([her_walk('right')], 1.0),
                         'only the walk part of an act list counts')

    def test_room_is_measured_from_her_window_to_her_screen_edges(self):
        from DyberPet.mia_director import walk_room
        self.assertEqual(walk_room(0, 300, 0, 1024), {'left': 0, 'right': 724})
        self.assertEqual(walk_room(724, 300, 0, 1024), {'left': 724, 'right': 0})
        self.assertEqual(walk_room(-150, 300, 0, 1024), {'left': 0, 'right': 874}, 'clamped past the edge')
        self.assertEqual(walk_room(-1500, 300, -1920, 1920), {'left': 420, 'right': 1200},
                         'a screen left of the primary')

    def test_direction_choice(self):
        from DyberPet.mia_director import choose_walk_direction
        need = {'left': 330.0, 'right': 330.0}
        rng = random.Random(3)
        self.assertEqual({choose_walk_direction(rng, {'left': 0, 'right': 724}, need) for _ in range(50)},
                         {'right'}, 'at the left edge')
        self.assertEqual({choose_walk_direction(rng, {'left': 724, 'right': 0}, need) for _ in range(50)},
                         {'left'}, 'at the right edge')
        self.assertEqual({choose_walk_direction(rng, {'left': 362, 'right': 362}, need) for _ in range(50)},
                         {'left', 'right'}, 'in the middle: still a coin flip')
        self.assertIsNone(choose_walk_direction(rng, {'left': 100, 'right': 160}, need),
                          'too narrow: under half a walk either way')
        self.assertEqual(choose_walk_direction(rng, {'left': 329.9, 'right': 330}, need), 'right',
                         'exactly one full walk is enough room')
        self.assertEqual({choose_walk_direction(rng) for _ in range(50)}, {'left', 'right'},
                         'no geometry known: the coin flip of before')

    def test_no_full_walk_either_way_she_takes_the_roomier_side(self):
        """Her 515 px window at 100 % leaves 509 px of a 1024 px screen: in the middle neither side
        holds a 330 px walk. She is not stuck there: the roomier side, if it holds half a walk."""
        from DyberPet.mia_director import MIN_WALK_FRACTION, choose_walk_direction, walk_room
        need = {'left': full_walk_px(1.0), 'right': full_walk_px(1.0)}
        self.assertEqual(MIN_WALK_FRACTION, 0.5)
        rng = random.Random(5)
        for x in range(0, 1024 - 515 + 1):
            room = walk_room(x, 515, 0, 1024)
            with self.subTest(x=x):
                chosen = {choose_walk_direction(rng, room, need) for _ in range(8)}
                self.assertNotIn(None, chosen, 'never stuck on a 1024 px screen')
                for side in chosen:
                    self.assertGreaterEqual(room[side], need[side] / 2, room)
                    if max(room.values()) >= need[side]:
                        self.assertGreaterEqual(room[side], need[side], 'a full walk wins when one fits')
        self.assertEqual(choose_walk_direction(rng, {'left': 250, 'right': 259}, need), 'right')
        self.assertEqual(choose_walk_direction(rng, {'left': 170, 'right': 90}, need), 'left')
        self.assertIsNone(choose_walk_direction(rng, {'left': 164, 'right': 0}, need))


# --------------------------------------------------------------------------------------------
# The director, with an injected geometry
# --------------------------------------------------------------------------------------------

class DirectorChoosesTheRoomySide(unittest.TestCase):
    NEED = full_walk_px(1.0)

    def ticks(self, room, seeds=range(40)):
        """One walk-only tick per seed; returns [(played, log lines)]."""
        out = []
        for seed in seeds:
            clock, log = Clock(), []
            director = make_director(clock, weights={'walk': 1.0}, seed=seed, log=log.append,
                                     walk_room=lambda: (dict(room), {'left': self.NEED, 'right': self.NEED}))
            director._tick_once()
            out.append((list(director.played), log))
        return out

    def test_at_the_left_edge_she_walks_right(self):
        for played, log in self.ticks({'left': 0, 'right': 1024 - 300}):
            self.assertEqual(played, ['right_walk'])
            self.assertEqual(log, ['walk right'])

    def test_at_the_right_edge_she_walks_left(self):
        for played, log in self.ticks({'left': 1024 - 300, 'right': 0}):
            self.assertEqual(played, ['left_walk'])
            self.assertEqual(log, ['walk left'])

    def test_near_a_wall_with_less_than_a_walk_of_room_she_walks_away(self):
        """The E2E case: 5 px from the left edge, which a coin flip chose again and again."""
        for played, log in self.ticks({'left': 5, 'right': 700}):
            self.assertEqual((played, log), (['right_walk'], ['walk right']))

    def test_in_the_middle_the_coin_flip_stays(self):
        results = self.ticks({'left': 362, 'right': 362})
        self.assertEqual({p[0] for p, _ in results}, {'left_walk', 'right_walk'})
        for played, log in results:
            self.assertEqual(log, ['walk %s' % played[0].split('_')[0]], 'the log shows the chosen direction')

    def test_on_a_screen_too_narrow_to_walk_the_tick_is_an_idle_pose(self):
        for played, log in self.ticks({'left': 100, 'right': 120}):
            self.assertEqual(len(played), 1, played)
            self.assertIn(played[0], POOL, 'an idle pose from her pool, not a walk')
            self.assertEqual(log, ['walk none (no room)', 'act %s' % played[0]])

    def test_without_geometry_or_if_it_fails_the_coin_flip_of_before(self):
        def broken():
            raise RuntimeError('no screen yet')
        for provider in (None, broken, lambda: None):
            with self.subTest(provider=provider):
                seen = set()
                for seed in range(30):
                    director = make_director(Clock(), weights={'walk': 1.0}, seed=seed, walk_room=provider)
                    director._tick_once()
                    seen.update(director.played)
                self.assertEqual(seen, {'left_walk', 'right_walk'})


# --------------------------------------------------------------------------------------------
# The real pet window: geometry, the director's walk, the random animation's walk
# --------------------------------------------------------------------------------------------

class PetWalksWithRoom(unittest.TestCase):
    """A 1024 px screen. Stand-in window 300 px wide, display scale 0.5 (full walk 165 px)."""
    CODE = '''
from DyberPet.mia_director import MiaDirector
out = {'need': None}
SCREEN = QRect(0, 0, 1024, 760)

def pet_at(x, screen=SCREEN):
    pet = Pet(centre_x=x + 150, screen=screen)
    pet._life_publish_wall()
    return pet

def director_for(pet, clock, seed):
    poses = set(conf.act_dict) | set(conf.act_name)
    return MiaDirector(get_available_poses=lambda: poses, play_action=pet._mia_play_pose,
                       is_busy=lambda: False, weights={'walk': 1.0}, rng=random.Random(seed),
                       system_idle_fn=lambda: 1.0, now_fn=clock, idle_pool={'tea': 1.0, 'read': 1.0},
                       on_log=lambda m: pet.lines.append('director ' + m), walk_room=pet._life_walk_room)

def run_interaction(pet, w, clock):
    ticks = 0
    while w.interact is not None and ticks < 4000:
        w.run(); clock.t += 0.021; ticks += 1

# 1. Geometry the pet publishes.
out['room'] = {str(x): pet_at(x)._life_walk_room()[0] for x in (0, 5, 362, 724)}
out['need'] = pet_at(362)._life_walk_room()[1]
out['published'] = pet_at(5)._life_room

# 2. The E2E case: 5 px from the left edge, the director walks (several seeds).
out['director'] = []
for seed in range(6):
    clock = Clock(); pet = pet_at(5)
    w = interaction_for(pet, clock)
    d = director_for(pet, clock, seed)
    d._tick_once()
    run_interaction(pet, w, clock)
    out['director'].append({'lines': [l for l in pet.lines if l.startswith(('walk', 'director'))],
                            'x': pet.pos().x()})

# 3. Same at the right edge.
clock = Clock(); pet = pet_at(724 - 5)
w = interaction_for(pet, clock)
director_for(pet, clock, 0)._tick_once()
run_interaction(pet, w, clock)
out['director_right'] = [l for l in pet.lines if l.startswith(('walk', 'director'))]

# 4. Too narrow (450 px screen, 300 px window: 150 px of room in all): no walk at all.
clock = Clock(); pet = pet_at(75, QRect(0, 0, 450, 760))
w = interaction_for(pet, clock)
director_for(pet, clock, 0)._tick_once()
out['narrow'] = {'lines': pet.lines, 'act': w.act_name, 'x': pet.pos().x()}

# 5. The random animation's walks.
def animation_for(pet):
    reset_engine()
    anim = Animation_worker(conf)
    clock = Clock()
    anim._clock = clock
    anim._sleep = lambda s: setattr(clock, 't', clock.t + s)
    anim.wall_side = lambda: getattr(pet, '_life_wall', None)
    anim.walk_room = lambda: getattr(pet, '_life_room', None)
    shown = []
    anim.sig_setimg_anim.connect(lambda: shown.append(settings.anim_act.act_name))
    anim.sig_move_anim.connect(pet._move_customized)
    anim.sig_walk_done.connect(lambda: pet._life_walk_end('anim'))
    pet.workers = {'Animation': anim, 'Interaction': SimpleNamespace(interact=None)}
    pet._life_publish_wall()
    return anim, shown

pet = pet_at(5)
anim, shown = animation_for(pet)
anim._run_acts([conf.left, conf.default])
out['anim_left_edge'] = {'lines': pet.lines, 'acts': sorted(set(shown)), 'x': pet.pos().x()}

pet = pet_at(724 - 5)
anim, shown = animation_for(pet)
anim._run_acts([conf.right])
out['anim_right_edge'] = {'lines': pet.lines, 'x': pet.pos().x()}

pet = pet_at(362)
anim, shown = animation_for(pet)
anim._run_acts([conf.left])
out['anim_middle'] = {'lines': pet.lines, 'x': pet.pos().x()}

pet = pet_at(75, QRect(0, 0, 450, 760))
picked = []
anim, shown = animation_for(pet)
anim.idle_picker = lambda: picked.append('tea') or 'tea'
anim._run_acts([conf.right, conf.default])
out['anim_narrow'] = {'lines': pet.lines, 'acts': sorted(set(shown)), 'x': pet.pos().x(), 'picked': picked}

# 6. Unchanged guards: a walk the micro ticker or follow asks for by name is not redirected by room.
clock = Clock(); pet = pet_at(1024 - 150 - 30)      # her centre 30 px from the right wall
w = interaction_for(pet, clock)
pet._mia_play_pose('right_walk')
run_interaction(pet, w, clock)
out['by_name'] = [l for l in pet.lines if l.startswith('walk end')]
print(json.dumps(out))
'''

    @classmethod
    def setUpClass(cls):
        cls.out = run_pet(cls.CODE)
        cls.need = full_walk_px(0.5)

    def ends(self, lines):
        return [l for l in lines if l.startswith('walk end')]

    def parse(self, line):
        parts = line.split()
        values = dict(p.split('=') for p in parts[3:])
        return parts[2], int(values['dx']), int(values['frames']), int(values['clamped'])

    def test_the_pet_publishes_its_room_and_one_full_walk(self):
        room = self.out['room']
        self.assertEqual(room['0'], {'left': 0, 'right': 724})
        self.assertEqual(room['5'], {'left': 5, 'right': 719})
        self.assertEqual(room['362'], {'left': 362, 'right': 362})
        self.assertEqual(room['724'], {'left': 724, 'right': 0})
        for side in ('left', 'right'):
            self.assertAlmostEqual(self.out['need'][side], self.need, places=3)
        self.assertEqual(self.out['published'], {'left': 5, 'right': 719}, 'for the animation thread')

    def assert_full_walk(self, line, pose):
        name, dx, frames, clamped = self.parse(line)
        self.assertEqual(name, pose, line)
        self.assertEqual(frames, 64, 'the whole clip: %s' % line)
        self.assertEqual(clamped, 0, line)
        self.assertGreaterEqual(abs(dx), int(self.need) - 1, line)

    def test_the_e2e_case_walks_away_from_the_left_wall_and_travels(self):
        for run in self.out['director']:
            with self.subTest(run=run):
                self.assertIn('director walk right', run['lines'])
                self.assertNotIn('director walk left', run['lines'])
                ends = self.ends(run['lines'])
                self.assertEqual(len(ends), 1, run['lines'])
                self.assert_full_walk(ends[0], 'right_walk')
                self.assertGreaterEqual(run['x'], 5 + int(self.need) - 1)

    def test_at_the_right_wall_the_director_walks_left(self):
        lines = self.out['director_right']
        self.assertIn('director walk left', lines)
        ends = self.ends(lines)
        self.assertEqual(len(ends), 1, lines)
        self.assert_full_walk(ends[0], 'left_walk')

    def test_on_a_narrow_screen_the_director_does_not_walk(self):
        n = self.out['narrow']
        self.assertIn('director walk none (no room)', n['lines'])
        self.assertFalse([l for l in n['lines'] if l.startswith('walk ')], n['lines'])
        self.assertIn(n['act'], ('tea', 'read'), 'an idle pose plays instead')
        self.assertEqual(n['x'], 75, 'she did not move')

    def test_random_animation_walk_at_the_left_edge_turns_and_travels(self):
        a = self.out['anim_left_edge']
        ends = self.ends(a['lines'])
        self.assertEqual(len(ends), 1, a['lines'])
        self.assert_full_walk(ends[0], 'right_walk')
        self.assertNotIn('left_walk', a['acts'])

    def test_random_animation_walk_at_the_right_edge_turns_and_travels(self):
        a = self.out['anim_right_edge']
        ends = self.ends(a['lines'])
        self.assertEqual(len(ends), 1, a['lines'])
        self.assert_full_walk(ends[0], 'left_walk')

    def test_random_animation_walk_in_the_middle_keeps_its_direction(self):
        a = self.out['anim_middle']
        ends = self.ends(a['lines'])
        self.assertEqual(len(ends), 1, a['lines'])
        self.assert_full_walk(ends[0], 'left_walk')

    def test_random_animation_on_a_narrow_screen_plays_an_idle_pose(self):
        a = self.out['anim_narrow']
        self.assertEqual(self.ends(a['lines']), [], a['lines'])
        self.assertEqual(a['x'], 75, 'she did not move')
        self.assertEqual(a['picked'], ['tea'], 'her shared idle chooser was asked')
        self.assertIn('tea', a['acts'])
        self.assertFalse({'left_walk', 'right_walk'} & set(a['acts']), a['acts'])

    def test_walks_asked_for_by_name_keep_the_wall_guard(self):
        """Edge turns, follow-cursor and drags do not go through the room rule: a walk requested by
        name toward a wall (her centre 30 px from it) still ends by the stuck guard (4 clamped
        frames), as in M3.2."""
        ends = self.out['by_name']
        self.assertEqual(len(ends), 1, ends)
        pose, dx, _frames, clamped = self.parse(ends[0])
        self.assertEqual((pose, clamped), ('right_walk', 4))
        self.assertEqual(dx, 30, 'up to the wall, where the clamp holds her centre')


if __name__ == '__main__':
    unittest.main()
