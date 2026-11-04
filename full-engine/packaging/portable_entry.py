"""MiniDraconia portable entry: normal start, --startup-smoke and --selftest-scripted.

Three separate branches:
  * normal            -> hands over to run_DyberPet.main() (the real UI start-up).
  * --startup-smoke   -> the SAME normal branch with a probe attached; needs
                         --report <absolute path> and a fresh explicit profile.
  * --selftest-scripted -> the existing offline product self-test (not a start-up).
Scripted offline: no inference, no cloud provider, no network.
"""
import json
import os
import sys
import traceback
from pathlib import Path

NORMAL_MODULE = 'run_DyberPet'  # the frozen spec MUST collect this module
EXIT_OK, EXIT_FAILURE, EXIT_USAGE = 0, 1, 2
DEFAULT_PROFILE_NAME = 'MiniDraconia-Scripted'
DIAGNOSTIC_NAME = 'startup-diagnostic.txt'
_SECRET_WORDS = ('KEY', 'TOKEN', 'SECRET', 'PASSWORD', 'CREDENTIAL')


class UsageError(Exception):
    """Invalid command line or profile; reported with exit code 2, never a crash."""


class Options:
    def __init__(self, mode, report):
        self.mode, self.report = mode, report


def install_root():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))


def parse_args(argv):
    smoke, selftest = '--startup-smoke' in argv, '--selftest-scripted' in argv
    if smoke and selftest:
        raise UsageError('--startup-smoke and --selftest-scripted cannot be used together')
    report = None
    if '--report' in argv:
        index = argv.index('--report')
        if index + 1 >= len(argv) or argv[index + 1].startswith('--'):
            raise UsageError('--report needs an absolute file path')
        report = Path(argv[index + 1])
        if not report.is_absolute():
            raise UsageError('--report must be an absolute path')
    mode = 'smoke' if smoke else 'selftest' if selftest else 'normal'
    if mode != 'normal' and report is None:
        raise UsageError('--report <absolute path> is required with --startup-smoke and --selftest-scripted')
    if mode == 'normal' and report is not None:
        raise UsageError('--report is only valid with --startup-smoke or --selftest-scripted')
    return Options(mode, report)


def is_automated(argv):
    """True when an automation flag is present, even if the rest of argv is malformed.

    Decided from argv alone so that a parse failure (which happens before Options exists)
    can never turn an automated invocation into one that opens a modal dialog.
    """
    return '--startup-smoke' in argv or '--selftest-scripted' in argv


def resolve_profile(options, environ, root):
    explicit = environ.get('MINIDRACONIA_TEST_PROFILE', '')
    if not explicit:
        if options.mode != 'normal':
            raise UsageError('An explicit absolute MINIDRACONIA_TEST_PROFILE is required (fresh profile directory)')
        local = environ.get('LOCALAPPDATA', '')
        if not local:
            raise UsageError('No profile available: set LOCALAPPDATA or an absolute MINIDRACONIA_TEST_PROFILE')
        explicit = str(Path(local) / DEFAULT_PROFILE_NAME)
    profile = Path(explicit)
    if not profile.is_absolute():
        raise UsageError('The profile must be an absolute path')
    profile = profile.resolve()
    if profile.is_relative_to(root.resolve()):
        raise UsageError('The profile must be outside the install directory')
    if options.mode == 'smoke':
        if profile.exists() and (not profile.is_dir() or any(profile.iterdir())):
            raise UsageError('The smoke profile must be fresh (missing or an empty directory)')
    return profile


def check_report(options, profile, root):
    report = options.report.resolve(strict=False)
    if report.is_relative_to(root.resolve()):
        raise UsageError('The report must be outside the install directory')
    if report.is_relative_to(profile):
        raise UsageError('The report must not be inside the profile directory')
    if report.exists():
        raise UsageError('The report file already exists; refusing to overwrite stale evidence')
    if not report.parent.is_dir():
        raise UsageError('The report directory does not exist')


def redact(text, environ):
    """Never let environment secrets reach a diagnostic or report."""
    for name, value in dict(environ).items():
        if len(str(value)) >= 6 and any(word in name.upper() for word in _SECRET_WORDS):
            text = text.replace(str(value), '<redacted>')
    return text


def write_atomic(path, text):
    path = Path(path)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(text, encoding='utf-8')
    os.replace(temp, path)


def show_error_dialog(title, message):
    """Windows-only visible error for a GUI app that otherwise exits silently."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    except Exception:
        pass


def run_selftest(options):
    from DyberPet.brain.selftest import exercise_product
    result = exercise_product()
    write_atomic(options.report, json.dumps(result, indent=2))
    return EXIT_OK


def run_smoke(options, probe):
    import importlib
    app_module = importlib.import_module(NORMAL_MODULE)
    # Installed before the app is built, restored in finally: callback exceptions Qt would only print
    # must turn the report red. Smoke branch only; the normal branch never touches sys.excepthook.
    probe.install_excepthook()
    try:
        code = app_module.main([sys.argv[0]], probe=probe)
    except SystemExit as exc:  # a quit path that exits the process is still an outcome to report
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    finally:
        probe.restore_excepthook()
    code = 0 if code is None else int(code)
    report = probe.build_report(code)
    write_atomic(options.report, json.dumps(report, indent=2))
    return EXIT_OK if report['ok'] else EXIT_FAILURE


def run_normal(argv):
    import importlib
    app_module = importlib.import_module(NORMAL_MODULE)
    code = app_module.main([sys.argv[0]] + list(argv))
    return EXIT_OK if code is None else int(code)


def main(argv=None, environ=None, root=None, notify=None):
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    environ = os.environ if environ is None else environ
    root = install_root() if root is None else Path(root)
    notify = show_error_dialog if notify is None else notify
    options = None
    automated = is_automated(argv)
    try:
        options = parse_args(argv)
        profile = resolve_profile(options, environ, root)
        if options.mode != 'normal':
            check_report(options, profile, root)
    except UsageError as exc:
        print('MiniDraconia: ' + str(exc), file=sys.stderr)
        if not automated and (options is None or options.mode == 'normal'):
            notify('MiniDraconia', 'MiniDraconia could not start.\n\n' + str(exc))
        return EXIT_USAGE

    profile.mkdir(parents=True, exist_ok=True)
    environ['MINIDRACONIA_TEST_PROFILE'] = str(profile)
    if options.mode == 'smoke':
        # Before ANY Qt import: no audio and no real display for the automated check.
        environ['QT_QPA_PLATFORM'] = 'offscreen'
        environ['MINIDRACONIA_MUTE'] = '1'
    elif options.mode == 'selftest':
        environ['QT_QPA_PLATFORM'] = 'offscreen'
    os.chdir(root)
    if not hasattr(sys, 'frozen') and (root / 'DyberPet').is_dir() and str(root) not in sys.path:
        sys.path.insert(0, str(root))

    probe = None
    try:
        if options.mode == 'selftest':
            return run_selftest(options)
        if options.mode == 'smoke':
            from DyberPet.startup_smoke import SmokeProbe
            probe = SmokeProbe(options.report)
            return run_smoke(options, probe)
        return run_normal(argv)
    except Exception as exc:
        trace = redact(traceback.format_exc(), environ)
        summary = redact('%s: %s' % (type(exc).__name__, exc), environ)
        diagnostic = profile / DIAGNOSTIC_NAME
        try:
            write_atomic(diagnostic, 'MiniDraconia startup diagnostic (no environment values are recorded)\n\n' + trace)
        except OSError:
            diagnostic = None
        if options.mode == 'smoke':
            try:
                report = probe.build_report(EXIT_FAILURE, error=summary) if probe is not None else {
                    'schema': 1, 'mode': 'startup-smoke', 'ok': False, 'exit_code': EXIT_FAILURE,
                    'failures': [summary], 'error': summary, 'evidence': None}
                report['diagnostic'] = str(diagnostic) if diagnostic else None
                write_atomic(options.report, json.dumps(report, indent=2))
            except OSError:
                pass
        elif options.mode == 'normal':
            where = ('\n\nDetails were saved to:\n' + str(diagnostic)) if diagnostic else ''
            notify('MiniDraconia', 'MiniDraconia could not start.\n\n' + summary + where)
        print('MiniDraconia failed: ' + summary, file=sys.stderr)
        return EXIT_FAILURE


if __name__ == '__main__':
    sys.exit(main())
