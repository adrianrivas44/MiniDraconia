"""Runtime regression: PetWidget._mia_micro_context with its real QRect current_screen.

current_screen is a QRect (availableGeometry at init, screen.geometry() on monitor switch). The method
once called .geometry() on it again and raised AttributeError on every timer tick. Needs the product's
Qt stack; skipped, with the reason, where PySide6 and friends are not importable.
"""
import importlib.util
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / 'full-engine'


def qt_available():
    try:
        return all(importlib.util.find_spec(name) for name in ('PySide6', 'qfluentwidgets', 'tendo', 'apscheduler', 'pynput'))
    except (ImportError, ValueError):
        return False


@unittest.skipUnless(qt_available(), 'NOT RUN: PySide6/qfluentwidgets/tendo/apscheduler/pynput not importable in this interpreter')
class MicroContextScreenGeometry(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        os.environ.setdefault('MINIDRACONIA_MUTE', '1')
        if str(ENGINE) not in sys.path:
            sys.path.insert(0, str(ENGINE))
        from PySide6.QtWidgets import QApplication
        from DyberPet import settings
        from DyberPet.DyberPet import PetWidget
        cls.app = QApplication.instance() or QApplication([])
        cls.settings, cls.PetWidget = settings, PetWidget
        cls.saved = (getattr(settings, 'screens', None), getattr(settings, 'draging', None))
        settings.screens, settings.draging = [], 0
        cls.addClassCleanup(lambda: (setattr(settings, 'screens', cls.saved[0]), setattr(settings, 'draging', cls.saved[1])))

    def test_real_method_accepts_its_qrect_screen_including_offset_monitors(self):
        from PySide6.QtCore import QPoint, QRect
        for rect in (QRect(0, 0, 1920, 1040), QRect(-1920, -200, 1920, 1080)):
            with self.subTest(rect=rect.getRect()):
                widget = SimpleNamespace(
                    workers={}, current_screen=rect, pos=lambda: QPoint(-120, 400), width=lambda: 515,
                    mia_director=SimpleNamespace(is_asleep=False), _mia_available_poses=lambda: [])
                context = self.PetWidget._mia_micro_context(widget)
                self.assertEqual(context['screen_top'], float(rect.y()))
                self.assertEqual(context['screen_height'], float(rect.height()))
                self.assertEqual(context['pos_y'], 400.0)


if __name__ == '__main__':
    unittest.main()
