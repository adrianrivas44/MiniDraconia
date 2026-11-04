"""Standard-library test runner for MiniDraconia.

Run it with the interpreter that has the product's Qt environment (on Windows
the Python 3.11 with requirements-dev.txt installed):

    python scripts/run_tests.py [--start-dir DIR] [--pattern test_*.py] [--keep-profile]

It sets a fresh isolated profile/temp, offscreen Qt and muted audio BEFORE any
test module is imported, then runs unittest and prints one SUMMARY line with the
counts. Skipped tests are listed with their reasons: a skip is "not run", never a pass.
"""
import argparse
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def prepare_environment(base):
    """Fresh state for this run; must happen before any product import."""
    profile = base/'profile'
    profile.mkdir()
    for name in ('temp', 'appdata', 'local'):
        (base/name).mkdir()
    os.environ['MINIDRACONIA_TEST_PROFILE'] = str(profile)
    os.environ['APPDATA'] = str(base/'appdata')
    os.environ['LOCALAPPDATA'] = str(base/'local')
    os.environ['TEMP'] = os.environ['TMP'] = os.environ['TMPDIR'] = str(base/'temp')
    tempfile.tempdir = str(base/'temp')
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    os.environ['MINIDRACONIA_MUTE'] = '1'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True
    engine = str(REPO/'full-engine')
    if engine not in sys.path:
        sys.path.insert(0, engine)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--start-dir', default=str(REPO/'tests'))
    parser.add_argument('--pattern', default='test*.py')
    parser.add_argument('--keep-profile', action='store_true', help='keep the temporary profile folder for inspection')
    args = parser.parse_args(argv)

    base = Path(tempfile.mkdtemp(prefix='minidraconia-tests-')).resolve()
    prepare_environment(base)
    if Path(args.start_dir).resolve() == (REPO/'tests').resolve():
        # Legacy package-gate tests create scratch folders under <repo>/work/s1 (git-ignored).
        (REPO/'work'/'s1').mkdir(parents=True, exist_ok=True)
    try:
        suite = unittest.defaultTestLoader.discover(args.start_dir, pattern=args.pattern)
        result = unittest.TextTestRunner(verbosity=2, stream=sys.stdout).run(suite)
    finally:
        if not args.keep_profile:
            shutil.rmtree(base, ignore_errors=True)
    for test, reason in result.skipped:
        print('SKIPPED (not run): %s -- %s' % (test.id(), reason))
    print('SUMMARY ran=%d failures=%d errors=%d skipped=%d expected_failures=%d unexpected_successes=%d' % (
        result.testsRun, len(result.failures), len(result.errors), len(result.skipped),
        len(result.expectedFailures), len(result.unexpectedSuccesses)))
    if result.testsRun == 0:
        print('NO TESTS WERE RUN')
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    sys.exit(main())
