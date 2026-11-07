"""Follow-the-cursor walks really travel (owner report on a 150 % screen: she did not move).

The pynput listener reports physical pixels and only after the mouse moves, so at 150 %
scaling she walked toward [0, 0] or past the screen edge and kept walking in place against
the wall. Behaviour contracts, standard library unittest + PySide6, no network.
"""
import os
import unittest

from test_engine_m32 import ACTION, run_python


class CursorTargetIsLogical(unittest.TestCase):
    CODE = '''
        import json
        from unittest import mock
        from PySide6.QtCore import QPoint
        from PySide6.QtWidgets import QApplication, QWidget
        app = QApplication([])
        from DyberPet.pet_life import PetLifeMixin

        class Pet(QWidget, PetLifeMixin):
            pass

        pet = Pet()
        pet.mouse_pos = [0, 0]                       # never moved / stale listener value
        with mock.patch('PySide6.QtGui.QCursor.pos', return_value=QPoint(900, 640)):
            target = pet._life_cursor_target()
        print(json.dumps({'target': target, 'mouse_pos': pet.mouse_pos}))
    '''

    def test_follow_target_is_the_current_qt_cursor(self):
        out = run_python(self.CODE, {'QT_QPA_PLATFORM': 'offscreen', 'QT_SCALE_FACTOR': '1.5',
                                     'MINIDRACONIA_TEST_PROFILE': os.environ['MINIDRACONIA_TEST_PROFILE']})
        self.assertEqual(out['target'], [900, 640])
        self.assertEqual(out['mouse_pos'], [900, 640])


class FollowStopsAtAWall(unittest.TestCase):
    def test_blocked_only_after_several_frames_at_the_same_x(self):
        from DyberPet.modules import FOLLOW_STUCK_FRAMES, follow_blocked
        self.assertFalse(follow_blocked(None, 10))
        self.assertFalse(follow_blocked([10] * (FOLLOW_STUCK_FRAMES - 1), 10))
        self.assertTrue(follow_blocked([10] * FOLLOW_STUCK_FRAMES, 10))
        self.assertFalse(follow_blocked([10, 21, 31, 42], 42), 'walking: x changes every frame')

    CODE = '''
        import json
        from PySide6.QtCore import QCoreApplication
        app = QCoreApplication([])
        from DyberPet import settings, frames
        from DyberPet.conf import PetConfig
        from DyberPet.modules import Interaction_worker
        import os
        settings.tunable_scale = 0.5
        settings.pet_display_scale = 0.5
        settings.current_act = settings.previous_act = settings.anim_act = None
        settings.current_img = settings.previous_img = None
        settings.current_anchor = settings.previous_anchor = [0, 0]
        settings.playid = settings.act_id = 0
        store = frames.FrameStore(os.environ['ACTION'], scale=0.5, dpr=1.0)
        conf = PetConfig.init_config('Draconia', store)
        w = Interaction_worker(conf)
        w.timer.stop()
        now = [0.0]
        w.clock = lambda: now[0]                     # M3.2: frames follow the clock
        moves, finished = [], []
        w.sig_move_inter.connect(lambda x, y: moves.append(x))
        w.sig_act_finished.connect(lambda: finished.append(1))
        w.interact, w.act_name = 'followTarget', 'mouse'
        w.receive_pos([1270, 700], [1900, 700])      # at the right wall, cursor beyond it
        ticks = 0
        while not finished and ticks < 400:
            w.run(); ticks += 1; now[0] += 0.021
        print(json.dumps({'finished': bool(finished), 'frames_walked': len(moves), 'ticks': ticks,
                          'interact': w.interact}))
    '''

    def test_follow_ends_instead_of_walking_in_place(self):
        out = run_python(self.CODE, {'QT_QPA_PLATFORM': 'offscreen', 'ACTION': str(ACTION),
                                     'MINIDRACONIA_TEST_PROFILE': os.environ['MINIDRACONIA_TEST_PROFILE']})
        self.assertTrue(out['finished'], out)
        self.assertIsNone(out['interact'])
        self.assertLessEqual(out['frames_walked'], 6, out)


if __name__ == '__main__':
    unittest.main()
