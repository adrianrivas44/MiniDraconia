"""Single VERSION file is the only source of the product version."""
import importlib.util
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / 'full-engine'
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

SEMVER = re.compile(r'^\d+\.\d+\.\d+(-[0-9A-Za-z.]+)?$')
RELEASE_CANDIDATE = re.compile(r'^\d+\.\d+\.\d+-rc\.\d+$')


def version_file():
    return (REPO / 'VERSION').read_text(encoding='utf-8').strip()


class VersionFile(unittest.TestCase):
    # REVISED (D2.5): VERSION-driven consistency instead of a literal in every test; the one
    # literal of the cut lives in its release test (tests/test_d25_release.py).
    def test_version_file_is_a_release_candidate(self):
        self.assertRegex(version_file(), RELEASE_CANDIDATE)

    def test_reader_returns_the_file_content(self):
        from DyberPet.version import read_version
        self.assertEqual(read_version(), version_file())

    def test_reader_prefers_resource_root_then_parent(self):
        from DyberPet.version import read_version
        with tempfile.TemporaryDirectory() as base:
            base = Path(base)
            (base / 'engine').mkdir()
            (base / 'VERSION').write_text('2.0.0\n', encoding='utf-8')
            self.assertEqual(read_version(base / 'engine'), '2.0.0')
            (base / 'engine' / 'VERSION').write_text('3.1.4-rc.2\n', encoding='utf-8')
            self.assertEqual(read_version(base / 'engine'), '3.1.4-rc.2')

    def test_reader_fails_clearly_instead_of_inventing_a_version(self):
        from DyberPet.version import read_version
        with tempfile.TemporaryDirectory() as base:
            with self.assertRaisesRegex(RuntimeError, 'VERSION'):
                read_version(Path(base) / 'engine')

    def test_reader_rejects_malformed_versions(self):
        from DyberPet.version import read_version
        with tempfile.TemporaryDirectory() as base:
            base = Path(base)
            (base / 'engine').mkdir()
            for bad in ('', 'MiniDraconia C2', '1.0', '1.0.0 beta', '../1.0.0'):
                (base / 'VERSION').write_text(bad, encoding='utf-8')
                with self.assertRaises(RuntimeError, msg=bad):
                    read_version(base / 'engine')

    def test_package_builder_reads_the_same_file(self):
        spec = importlib.util.spec_from_file_location('package_scripted_version', REPO / 'package_scripted.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.read_version(), version_file())
        self.assertRegex(module.read_version(), SEMVER)

    def test_settings_exposes_version_without_hardcoding_it(self):
        text = (ENGINE / 'DyberPet' / 'settings.py').read_text(encoding='utf-8')
        self.assertNotIn('MiniDraconia C2', text)
        self.assertIn('read_version', text)
        about = (ENGINE / 'DyberPet' / 'DyberSettings' / 'BasicSettingUI.py').read_text(encoding='utf-8')
        self.assertIn('settings.VERSION', about)
        self.assertIn('ChaozhongLiu', about, 'upstream attribution must stay')


if __name__ == '__main__':
    unittest.main()
