"""Draconia's resting clips keep still, and her walk is measured from her own sprites.

A resting clip that steps from foot to foot reads as walking in place (the owner's report on
the other character's build). Her `stand` (97 frames, on screen most of the time) must keep her
feet planted; her 4-frame `sit` alternates two pictures, so it holds one instead of flickering;
her walk's `frame_move` / `step_ends` are what scripts/measure_sprite_motion.py measures.
Pixel math uses QImage only (no numpy/Pillow).
"""
import importlib.util
import json
import operator
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / 'full-engine' / 'res' / 'role' / 'Draconia'
ACTION = ROLE / 'action'

# Mean absolute RGBA difference of the legs band (bottom 28 %) against frame 0. A stepping
# clip peaks around 19, a planted sway stays under ~7 (Draconia's stand: ~3.4), her walk ~11.
LEGS_LIMIT = 10.0


def qt_app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def legs(name):
    """RGBA bytes of the legs band of a frame."""
    from PySide6.QtGui import QImage
    image = QImage(str(ACTION / name)).convertToFormat(QImage.Format_RGBA8888)
    w, h, stride = image.width(), image.height(), image.bytesPerLine()
    raw = bytes(image.constBits())[:stride * h]
    top = int(h * 0.72)
    return b''.join(raw[y * stride:y * stride + 4 * w] for y in range(top, h))


def mean_diff(a, b):
    return sum(map(abs, map(operator.sub, a, b))) / len(a)


class StandKeepsFeetPlanted(unittest.TestCase):
    def setUp(self):
        qt_app()

    def test_stand_never_steps(self):
        count = len(list(ACTION.glob('stand_*.png')))
        self.assertEqual(count, 97)
        first = legs('stand_0.png')
        worst = max(mean_diff(legs('stand_%d.png' % i), first) for i in range(count))
        self.assertLess(worst, LEGS_LIMIT, 'the resting clip steps like a walk (%.1f)' % worst)

    def test_stand_loops_without_a_jump(self):
        self.assertLess(mean_diff(legs('stand_96.png'), legs('stand_0.png')), 3.0)

    def test_the_limit_tells_a_walk_from_a_stand(self):
        first = legs('walkcycle_right_0.png')
        worst = max(mean_diff(legs('walkcycle_right_%d.png' % i), first) for i in range(16))
        self.assertGreater(worst, LEGS_LIMIT, 'the band and limit really detect stepping')


class SitHoldsItsPose(unittest.TestCase):
    def test_sit_holds_one_frame_instead_of_flickering(self):
        acts = json.loads((ROLE / 'act_conf.json').read_text(encoding='utf-8'))
        self.assertEqual(len(list(ACTION.glob('sit_*.png'))), 4)
        self.assertEqual(acts['sit']['frames'], [0])
        qt_app()
        from DyberPet.conf import PetConfig
        from DyberPet.frames import FrameStore
        conf = PetConfig.init_config('Draconia', FrameStore(ACTION, scale=0.25))
        sit = conf.act_dict['sit']
        self.assertEqual(sit.images.names, ('sit_0',))
        self.assertEqual(len(sit.images) * sit.act_num, 1, 'one picture, held')
        self.assertGreaterEqual(sit.frame_refresh, 2.0, 'held for seconds, not 0.32 s flicker')
        self.assertEqual(len(conf.act_dict['default'].images), 97, 'other clips keep every frame')

    def test_the_frames_option_keeps_valid_indexes_only(self):
        qt_app()
        from DyberPet.conf import Act
        from DyberPet.frames import FrameStore
        store = FrameStore(ACTION, scale=0.25)
        for picked, expected in (([1, 3], ('sit_1', 'sit_3')), ([9, -1], ('sit_0', 'sit_1', 'sit_2', 'sit_3')),
                                 (None, ('sit_0', 'sit_1', 'sit_2', 'sit_3'))):
            param = {'images': 'sit', 'act_num': 1, 'frame_refresh': 1.0}
            if picked is not None:
                param['frames'] = picked
            act = Act.init_act(param, store, 1.0, 'Draconia', act_name='sit')
            with self.subTest(picked=picked):
                self.assertEqual(act.images.names, expected)


class WalkIsMeasured(unittest.TestCase):
    def measure_module(self):
        spec = importlib.util.spec_from_file_location('measure_sprite_motion_under_test',
                                                      REPO / 'scripts' / 'measure_sprite_motion.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_frame_move_and_step_ends_are_the_measured_ones(self):
        qt_app()
        module = self.measure_module()
        acts = json.loads((ROLE / 'act_conf.json').read_text(encoding='utf-8'))
        speeds = module.measure(ROLE)
        steps = module.measure_steps(ROLE)
        for act, images in (('right_walk', 'walkcycle_right'), ('left_walk', 'walkcycle_left')):
            with self.subTest(act=act):
                speed, frames = speeds[images]
                self.assertEqual(frames, 16, 'the whole 16-frame loop')
                self.assertAlmostEqual(acts[act]['frame_move'], speed, delta=0.1 * speed,
                                       msg='window step = planted-foot travel per frame (no skating)')
                self.assertEqual(acts[act]['step_ends'], steps[images])
                self.assertEqual(acts[act]['frame_refresh'], 1 / 12)


if __name__ == '__main__':
    unittest.main()
