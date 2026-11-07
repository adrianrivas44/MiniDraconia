import sys
from sys import platform
import ctypes

# Mia: onnxruntime (motor de Kokoro, voz en ingles) debe cargar su DLL antes
# que Qt/PySide6 en el mismo proceso; si Qt carga primero, importar
# onnxruntime despues provoca un access violation (orden de carga de DLLs
# en Windows, contrato-voz-en.md). Import defensivo: si Kokoro/onnxruntime
# no estan instalados, se sigue sin voz, sin romper el arranque.
try:
    import DyberPet._msvc_preload  # noqa: F401  Mia: runtime C++ del sistema + onnxruntime antes que Qt
except Exception:
    pass

from tendo import singleton
import os
from DyberPet.utils import read_json
from DyberPet.DyberPet import PetWidget
from DyberPet.Notification import DPNote
from DyberPet.Accessory import DPAccessory

from PySide6.QtWidgets import QApplication
from PySide6 import QtCore
from PySide6.QtCore import Qt, QLocale, QTimer, QDateTime, QDate, Signal, QTime

from qfluentwidgets import  FluentTranslator, setThemeColor
from DyberPet.DyberSettings.DyberControlPanel import ControlMainWindow


try:
    size_factor = 1 #ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100
except:
    size_factor = 1

import DyberPet.settings as settings


# For translation:
# pylupdate5 langs.pro
# lrelease langs.zh_CN.ts

# For .exe:
# Now we use pyinstaller 6.5.0
# pyinstaller --noconsole --icon="000.ico" --hidden-import="pynput.mouse._win32" --hidden-import="pynput.keyboard._win32" run_DyberPet.py

# For Mac:
# pyinstaller --windowed --icon 000.icns --add-data="res:res" --add-data="DyberPet:DyberPet" --hidden-import="pynput.mouse._darwin" --hidden-import="pynput.keyboard._darwin" run_DyberPet.py


class DyberPetApp(QApplication):
    date_changed = Signal(QDate)

    def __init__(self, *args, **kwargs):
        super(DyberPetApp, self).__init__(*args, **kwargs)

        self.setQuitOnLastWindowClosed(False)
        screens = self.screens()
        primary_screen = self.primaryScreen()

        if primary_screen in screens:
            screens.insert(0, screens.pop(screens.index(primary_screen)))
        else:
            screens.insert(0, primary_screen)

        # internationalization
        fluentTranslator = FluentTranslator(QLocale(settings.language_code))
        self.installTranslator(fluentTranslator)
        # MiniDraconia uses English source strings, never the zh_CN catalog.
        self.setApplicationName('MiniDraconia')
        # D2.1: the app icon for every window without its own (res/icons/app.ico / app.png).
        from DyberPet.app_icon import app_icon
        self.setWindowIcon(app_icon(settings.BASEDIR))
        if settings.themeColor:
            setThemeColor(settings.themeColor)
        

        # Pet Object
        self.p = PetWidget(screens=screens)

        # Notification System
        self.note = DPNote()

        # Accessory System
        self.acc = DPAccessory()

        # System Panel
        self.conp = ControlMainWindow()



        # Midnight Timer
        self.current_date = QDate.currentDate()
        self.set_midnight_timer()

        # Signal Links
        self.__connectSignalToSlot()

    def __connectSignalToSlot(self):
        # Main Widget - others
        self.p.setup_notification.connect(self.note.setup_notification)
        self.p.setup_bubbleText.connect(self.note.setup_bubbleText)
        self.p.change_note.connect(self.note.change_pet)

        self.p.close_bubble.connect(self.note.close_bubble)

        self.p.setup_acc.connect(self.acc.setup_accessory)
        self.p.move_sig.connect(self.acc.send_main_movement)
        self.p.move_sig.connect(self.note.send_main_movement)
        self.p.close_all_accs.connect(self.acc.closeAll)

        # System Widgets - others
        self.conp.settingInterface.ontop_changed.connect(self.acc.ontop_changed)
        self.conp.settingInterface.scale_changed.connect(self.acc.reset_size_sig)

        self.conp.settingInterface.ontop_changed.connect(self.p.ontop_update)
        self.conp.settingInterface.scale_changed.connect(self.p.reset_size)
        self.conp.settingInterface.lang_changed.connect(self.p.lang_changed)
        self.p.change_note.connect(self.conp.settingInterface._update_scale)

        self.p.show_controlPanel.connect(self.conp.show_window)

        # Midnight Trigger
        self.date_changed.connect(self.p._mightEventTrigger)
    
    def set_midnight_timer(self):
        now = QDateTime.currentDateTime()
        midnight = QDateTime(QDate.currentDate().addDays(1), QTime(0, 0, 0))  # Next midnight
        msecs_until_midnight = now.msecsTo(midnight)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.check_date)
        self.timer.start(msecs_until_midnight)
    
    def check_date(self):
        new_date = QDate.currentDate()
        if new_date != self.current_date:
            self.current_date = new_date
            self.date_changed.emit(new_date)
        self.set_midnight_timer()  # Reset the timer for the next midnight


        


if platform == 'win32':
    basedir = ''
else:
    basedir = os.path.dirname(__file__)

class InstanceRunning(RuntimeError):
    """Another MiniDraconia already holds the per-session lock."""


def acquire_instance_lock(smoke=False):
    """Avoid multiple processes.

    Mia: candado por sesión de Windows; una copia huérfana en la sesión 0 (workers Kanban) no debe bloquear a User.
    The startup smoke uses its own lock name so an automated check can never
    collide with, or silently pass because of, a copy the user has running.
    """
    try:
        _k32 = __import__("ctypes").windll.kernel32 if os.name == "nt" else None
        _sess = __import__("ctypes").c_ulong(0)
        if _k32:
            _k32.ProcessIdToSessionId(_k32.GetCurrentProcessId(), __import__("ctypes").byref(_sess))
        return singleton.SingleInstance(flavor_id=("minidraconia-smoke-s%d" if smoke else "minidraconia-s%d") % _sess.value)
    except (Exception, SystemExit):
        # tendo exits the process when the lock is taken; turn that into a value.
        raise InstanceRunning('MiniDraconia is already running. Open it from the tray, or close the other instance and restart.')


def main(argv=None, probe=None):
    """The normal startup. `probe` (startup smoke only) is attached right before
    the event loop; construction errors propagate to the caller, never swallowed."""
    argv = list(sys.argv if argv is None else argv)
    try:
        instance_lock = acquire_instance_lock(smoke=probe is not None)
    except InstanceRunning as exc:
        if probe is not None:
            raise
        print(exc)
        return 0

    # Create App
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    #QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    #QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    print('MiniDraconia: Loading Draconia. First startup may take a moment; please wait.')
    app = DyberPetApp(argv)
    app.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings)
    print('MiniDraconia is ready. Open Settings from the tray to adjust size or audio.')

    if probe is not None:
        probe.attach(app)
    code = app.exec()
    if probe is not None:
        probe.shutdown(app)
    del instance_lock
    return code


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception:
        print('MiniDraconia could not start. Check that the extracted files are complete, then restart. If settings are damaged, back up your user settings and restore the defaults.', file=sys.stderr)
        raise
