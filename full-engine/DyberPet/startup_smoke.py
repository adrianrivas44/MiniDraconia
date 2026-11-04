"""Startup smoke probe: evidence taken from the REAL normal startup.

`portable_entry.py --startup-smoke --report <abs path>` runs the same startup
branch as a normal launch (real DyberPetApp, PetWidget, tray menu, control
panel, midnight timer) and attaches this probe just before the event loop. The
probe never builds or replaces widgets: it counts real event-loop ticks, reads
the real windows/controls/timers, then quits through QTimer + app.quit().
Qt is imported lazily so the pure parts (evaluate, build_report) run anywhere.
"""
import datetime
import sys
import traceback
from pathlib import Path

SCHEMA = 1
REQUIRED_ACTIONS = ('Settings', 'Quit')
MIN_LOOP_TICKS = 3


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def evaluate(evidence):
    """Return the list of reasons the evidence is not proof of a working start."""
    if not isinstance(evidence, dict) or not evidence:
        return ['no evidence recorded from the running application']
    failures = []
    app = evidence.get('application')
    if not isinstance(app, dict) or not app.get('class'):
        failures.append('application evidence missing')
    elif app.get('platform') != 'offscreen':
        failures.append('smoke must run on the offscreen platform')
    windows = evidence.get('windows')
    pets = [w for w in windows if isinstance(w, dict) and w.get('class') == 'PetWidget'] if isinstance(windows, list) else []
    if not pets:
        failures.append('no PetWidget window recorded')
    else:
        pet = pets[0]
        if pet.get('visible') is not True:
            failures.append('pet window is not visible')
        if not (_number(pet.get('width')) and _number(pet.get('height')) and pet['width'] > 0 and pet['height'] > 0):
            failures.append('pet window has an empty size')
    if not (_number(evidence.get('sprite_pixels')) and evidence['sprite_pixels'] > 0):
        failures.append('pet sprite rendered no visible pixels')
    controls = evidence.get('controls')
    actions = controls.get('menu_actions') if isinstance(controls, dict) else None
    if not isinstance(actions, list) or not all(name in actions for name in REQUIRED_ACTIONS):
        failures.append('pet menu does not expose ' + ' and '.join(REQUIRED_ACTIONS))
    if not (isinstance(controls, dict) and controls.get('settings_panel_opened') is True):
        failures.append('Settings action did not open the control panel')
    timers = evidence.get('timers')
    if not isinstance(timers, dict):
        failures.append('timer evidence missing')
    else:
        if not (_number(timers.get('event_loop_ticks')) and timers['event_loop_ticks'] >= MIN_LOOP_TICKS):
            failures.append('event loop produced fewer than %d timer ticks' % MIN_LOOP_TICKS)
        if timers.get('midnight_timer_active') is not True:
            failures.append('application midnight timer is not active')
    return failures


def collect(app, ticks):
    """Read real evidence from the running application (call inside the event loop)."""
    from PySide6.QtWidgets import QApplication
    pet = app.p
    windows = [{'class': type(w).__name__, 'visible': bool(w.isVisible()), 'width': int(w.width()), 'height': int(w.height())}
               for w in app.topLevelWidgets()]
    image = pet.label.grab().toImage()
    sprite_pixels = sum(1 for y in range(image.height()) for x in range(image.width())
                        if image.pixelColor(x, y).alpha() > 0)
    actions = [a.text() for a in pet.StatMenu.actions() if not a.isSeparator()]
    opened = False
    settings_action = next((a for a in pet.StatMenu.actions() if a.text() == 'Settings'), None)
    if settings_action is not None:
        settings_action.trigger()
        QApplication.processEvents()
        opened = bool(app.conp.isVisible())
        app.conp.hide()
    return {
        'application': {'class': type(app).__name__, 'name': app.applicationName(), 'platform': app.platformName()},
        'windows': windows,
        'sprite_pixels': sprite_pixels,
        'controls': {'menu_actions': actions, 'settings_panel_opened': opened,
                     'control_panel_class': type(app.conp).__name__},
        'timers': {'event_loop_ticks': ticks, 'midnight_timer_active': bool(app.timer.isActive()),
                   'midnight_timer_remaining_ms': int(app.timer.remainingTime())},
        'threads': {name: bool(thread.isRunning()) for name, thread in getattr(pet, 'threads', {}).items()},
    }


class SmokeProbe:
    MAX_RECORDED_CALLBACK_FAILURES = 20

    def __init__(self, report_path, settle_ms=700, timeout_ms=60000, tick_ms=50, sys_module=sys):
        self.report_path = Path(report_path)
        self._sys = sys_module  # seam: tests inject a stand-in with an `excepthook` attribute
        self.callback_failures = []
        self.callback_failure_count = 0
        self._previous_hook = None
        self._hook = None
        self.settle_ms, self.timeout_ms, self.tick_ms = settle_ms, timeout_ms, tick_ms
        self.evidence = None
        self.error = None
        self._ticks = 0
        self._app = None

    def install_excepthook(self):
        """Smoke only: note every exception that escapes a Qt timer/signal callback.

        Qt prints such exceptions through sys.excepthook and keeps running, so a start that
        spams callback errors would otherwise still exit 0 with a green report. The previous
        hook is still called (the traceback keeps reaching stderr) and is restored by
        restore_excepthook(). Never installed in normal-user mode.
        """
        if self._hook is not None:
            return
        previous = self._sys.excepthook
        self._previous_hook = previous

        def hook(exc_type, exc, tb):
            self.callback_failure_count += 1
            if len(self.callback_failures) < self.MAX_RECORDED_CALLBACK_FAILURES:
                text = str(exc).splitlines()[0][:300] if str(exc) else ''
                self.callback_failures.append('%s: %s' % (getattr(exc_type, '__name__', str(exc_type)), text))
            try:
                previous(exc_type, exc, tb)
            except Exception:
                pass
        self._hook = hook
        self._sys.excepthook = hook

    def restore_excepthook(self):
        if self._hook is None:
            return
        self._sys.excepthook = self._previous_hook
        self._hook = None

    def record(self, evidence):
        self.evidence = evidence

    def attach(self, app):
        """Schedule evidence collection and a QTimer-driven quit; call before app.exec()."""
        from PySide6.QtCore import QTimer
        self._app = app
        self._ticker = QTimer(app)
        self._ticker.setInterval(self.tick_ms)
        self._ticker.timeout.connect(self._tick)
        self._ticker.start()
        self._settle = QTimer(app)
        self._settle.setSingleShot(True)
        self._settle.timeout.connect(self._finish)
        self._settle.start(self.settle_ms)
        self._deadline = QTimer(app)
        self._deadline.setSingleShot(True)
        self._deadline.timeout.connect(self._expired)
        self._deadline.start(self.timeout_ms)

    def _tick(self):
        self._ticks += 1

    def _finish(self):
        try:
            self.record(collect(self._app, self._ticks))
        except Exception:
            self.error = 'evidence collection failed: ' + traceback.format_exc(limit=3).strip().splitlines()[-1]
        finally:
            self._app.quit()

    def _expired(self):
        self.error = 'startup smoke timed out after %d ms' % self.timeout_ms
        self._app.exit(3)

    def shutdown(self, app):
        """After exec(): stop the pet worker threads the way Quit does, without sys.exit."""
        pet = getattr(app, 'p', None)
        if pet is None:
            return
        try:
            for name in ('Animation', 'Interaction', 'Scheduler'):
                pet.stop_thread(name)
            pet.stopAllThread.emit()
            pet.close()
        except Exception:
            self.error = self.error or 'shutdown failed: ' + traceback.format_exc(limit=3).strip().splitlines()[-1]

    def build_report(self, exit_code, error=None):
        failures = evaluate(self.evidence)
        if exit_code != 0:
            failures.append('application exit code %s' % exit_code)
        error = error or self.error
        if error:
            failures.append(error)
        if self.callback_failure_count:
            failures.append('%d exception(s) escaped Qt callbacks, first: %s' % (self.callback_failure_count, self.callback_failures[0]))
        try:
            from DyberPet.version import read_version
            version = read_version()
        except Exception:
            version = None
        return {'schema': SCHEMA, 'mode': 'startup-smoke', 'ok': not failures, 'exit_code': exit_code,
                'failures': failures, 'error': error, 'version': version, 'evidence': self.evidence,
                'callback_exceptions': {'count': self.callback_failure_count, 'recorded': list(self.callback_failures)},
                'created_utc': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
