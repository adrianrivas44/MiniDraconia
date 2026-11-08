"""The release scanner judges a clean tree as clean: running it never leaves its own bytecode behind."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ScannerLeavesNoBytecode(unittest.TestCase):
    def test_a_second_scan_of_a_clean_copy_is_still_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / 'tree'
            (copy / 'scripts').mkdir(parents=True)
            (copy / 'full-engine' / 'packaging').mkdir(parents=True)
            shutil.copy2(ROOT / 'scripts' / 'scan_release.py', copy / 'scripts')
            shutil.copy2(ROOT / 'full-engine' / 'packaging' / 'asset_policy.py', copy / 'full-engine' / 'packaging')
            (copy / 'README.md').write_text('A clean tree.\n', encoding='utf-8')
            # A user runs the scanner with Python's defaults, which write bytecode.
            env = {k: v for k, v in os.environ.items() if k != 'PYTHONDONTWRITEBYTECODE'}
            for _ in range(2):
                run = subprocess.run([sys.executable, str(copy / 'scripts' / 'scan_release.py'), '--root', str(copy)],
                                     capture_output=True, text=True, env=env)
                self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual(list(copy.rglob('*.pyc')), [])


if __name__ == '__main__':
    unittest.main()
