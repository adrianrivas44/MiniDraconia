"""Qt 6.5.3 notice collection (standard library only, no network).

The wheel metadata of PySide6/Essentials/Addons/shiboken6 6.5.3 lists only
LicenseRef-Qt-Commercial.txt. Copying that alone is NOT open-source notice coverage, so the build
also collects the version-matched upstream LICENSES texts committed in third_party/qt-6.5.3 and
verifies each one against PROVENANCE.json (and the pinned upstream commits) before use. These
tests prove the verification, not any license compatibility.
"""
import hashlib
import importlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REFERENCE = REPO / 'third_party' / 'qt-6.5.3'


def load_builder():
    spec = importlib.util.spec_from_file_location('package_scripted_qt_notices', REPO / 'package_scripted.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_distribution(site, name, version, files):
    info = site / ('%s-%s.dist-info' % (name, version))
    info.mkdir(parents=True)
    (info / 'METADATA').write_text('Metadata-Version: 2.1\nName: %s\nVersion: %s\n' % (name, version), encoding='utf-8')
    records = []
    for relative, content in files.items():
        target = site / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')
        records.append('%s,,' % relative)
    (info / 'RECORD').write_text('\n'.join(records) + '\n', encoding='utf-8')
    importlib.invalidate_caches()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.pkg = load_builder()

    def copy_reference(self):
        target = Path(tempfile.mkdtemp(dir=str(self.base))) / 'ref'
        shutil.copytree(REFERENCE, target)
        return target

    def provenance(self, ref):
        return json.loads((ref / 'PROVENANCE.json').read_text(encoding='utf-8'))

    def write_provenance(self, ref, data):
        (ref / 'PROVENANCE.json').write_text(json.dumps(data, indent=2), encoding='utf-8')


class SpdxLicenseRefNames(Base):
    def setUp(self):
        super().setUp()
        self.site = self.base / 'site'
        self.site.mkdir()
        sys.path.insert(0, str(self.site))
        self.addCleanup(sys.path.remove, str(self.site))

    def test_real_wheel_layout_licenseref_commercial_is_found(self):
        # Exactly the layout read from the Windows environment: dist-info/LicenseRef-Qt-Commercial.txt
        make_distribution(self.site, 'PySide6', '6.5.3', {
            'PySide6/code.py': 'x', 'PySide6-6.5.3.dist-info/LicenseRef-Qt-Commercial.txt': 'commercial reference'})
        _, found = self.pkg._notice_entries('PySide6')
        self.assertEqual([e.as_posix() for e, _ in found], ['PySide6-6.5.3.dist-info/LicenseRef-Qt-Commercial.txt'])

    def test_licenseref_files_are_collected_and_hashed_like_other_wheel_notices(self):
        make_distribution(self.site, 'shiboken6', '6.5.3', {
            'shiboken6-6.5.3.dist-info/LicenseRef-Qt-Commercial.txt': 'commercial reference'})
        found = self.pkg.collect_license_notices(['shiboken6'], self.base / 'out')
        self.assertEqual(len(found['shiboken6']), 1)
        item = found['shiboken6'][0]
        self.assertEqual(hashlib.sha256((self.base / 'out' / item['dest']).read_bytes()).hexdigest(), item['sha256'])

    def test_name_pattern_accepts_spdx_licenseref_and_not_code_or_lookalikes(self):
        for name in ('LicenseRef-Qt-Commercial.txt', 'LICENSEREF-Foo', 'licenseref-bar.txt', 'LICENSE', 'COPYING.txt', 'NOTICE'):
            self.assertTrue(self.pkg._NOTICE_NAME.match(name), name)
        for name in ('LicenseRefs.txt', 'licensee.txt', 'licenseref', 'Licenseref.', 'readme.txt'):
            self.assertFalse(self.pkg._NOTICE_NAME.match(name), name)

    def test_commercial_reference_alone_is_not_enough_for_the_qt_gate(self):
        for name in self.pkg.QT_NOTICE_DISTRIBUTIONS:
            make_distribution(self.site, name, '6.5.3', {'%s-6.5.3.dist-info/LicenseRef-Qt-Commercial.txt' % name: 'c'})
        empty = self.base / 'no-reference'
        empty.mkdir()
        problems = self.pkg.qt_notice_problems(reference_dir=empty)
        self.assertTrue(problems)
        self.assertIn('reference', ' '.join(problems).lower())
        self.assertEqual(self.pkg.qt_notice_problems(reference_dir=REFERENCE), [])


class ReferenceVerification(Base):
    def test_real_reference_set_verifies_and_matches_the_pinned_upstream(self):
        items = self.pkg.verify_qt_reference(REFERENCE)
        self.assertEqual(len(items), 22)
        self.assertEqual({i['version'] for i in items}, {'6.5.3'})
        self.assertEqual({i['project'] for i in items}, {'pyside/pyside-setup', 'qt/qtbase'})
        for item in items:
            self.assertEqual(hashlib.sha256(Path(item['source']).read_bytes()).hexdigest(), item['sha256'])
            self.assertTrue(item['url'].startswith('https://raw.githubusercontent.com/%s/%s/LICENSES/' % (item['project'], item['commit'])))
        self.assertIn('qtbase/LGPL-3.0-only.txt', {i['name'] for i in items})
        self.assertIn('pyside-setup/LGPL-3.0-only.txt', {i['name'] for i in items})

    def test_tampered_content_is_rejected(self):
        ref = self.copy_reference()
        target = ref / 'qtbase' / 'LGPL-3.0-only.txt'
        data = target.read_bytes()
        target.write_bytes(data[:-1] + (b'X' if data[-1:] != b'X' else b'Y'))  # same size, different hash
        with self.assertRaisesRegex(RuntimeError, 'sha256|hash'):
            self.pkg.verify_qt_reference(ref)

    def test_wrong_size_is_rejected(self):
        ref = self.copy_reference()
        target = ref / 'qtbase' / 'MIT.txt'
        target.write_bytes(target.read_bytes() + b'\n')
        with self.assertRaisesRegex(RuntimeError, 'size|bytes'):
            self.pkg.verify_qt_reference(ref)

    def test_unlisted_extra_file_is_rejected_no_blanket_whitelist(self):
        ref = self.copy_reference()
        (ref / 'qtbase' / 'Evil-License.txt').write_text('x', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'not listed|unlisted'):
            self.pkg.verify_qt_reference(ref)
        ref2 = self.base / 'ref2'
        shutil.copytree(REFERENCE, ref2)
        (ref2 / 'other').mkdir()
        (ref2 / 'other' / 'x.txt').write_text('x', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'not listed|unlisted'):
            self.pkg.verify_qt_reference(ref2)

    def test_missing_listed_file_is_rejected(self):
        ref = self.copy_reference()
        (ref / 'pyside-setup' / 'GPL-2.0-only.txt').unlink()
        with self.assertRaisesRegex(RuntimeError, 'missing|not a file'):
            self.pkg.verify_qt_reference(ref)

    def edit_first(self, ref, **changes):
        data = self.provenance(ref)
        data[0].update(changes)
        self.write_provenance(ref, data)

    def test_traversal_absolute_and_backslash_names_are_rejected(self):
        for bad in ('../outside.txt', '/etc/passwd', 'qtbase/../../x.txt', 'qtbase\\x.txt', 'C:/x.txt', 'qtbase/sub/x.txt', 'other/x.txt'):
            with self.subTest(bad=bad):
                ref = self.copy_reference()
                self.edit_first(ref, file=bad)
                with self.assertRaisesRegex(RuntimeError, 'unsafe|invalid|outside'):
                    self.pkg.verify_qt_reference(ref)

    def test_wrong_version_commit_url_or_project_is_rejected(self):
        cases = {'version': '6.5.4', 'commit': '0' * 40, 'project': 'evil/qtbase',
                 'url': 'https://example.com/LICENSES/BSD-3-Clause.txt'}
        for key, value in cases.items():
            with self.subTest(key=key):
                ref = self.copy_reference()
                self.edit_first(ref, **{key: value})
                with self.assertRaises(RuntimeError):
                    self.pkg.verify_qt_reference(ref)

    def test_malformed_provenance_is_rejected(self):
        ref = self.copy_reference()
        (ref / 'PROVENANCE.json').write_text('{not json', encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError, 'PROVENANCE'):
            self.pkg.verify_qt_reference(ref)
        self.write_provenance(ref, [])
        with self.assertRaisesRegex(RuntimeError, 'PROVENANCE|empty'):
            self.pkg.verify_qt_reference(ref)

    def test_duplicate_entries_and_missing_required_open_source_texts_are_rejected(self):
        ref = self.copy_reference()
        data = self.provenance(ref)
        self.write_provenance(ref, data + [data[0]])
        with self.assertRaisesRegex(RuntimeError, 'duplicate'):
            self.pkg.verify_qt_reference(ref)
        ref = self.base / 'ref3'
        shutil.copytree(REFERENCE, ref)
        data = [e for e in self.provenance(ref) if e['file'] != 'qtbase/LGPL-3.0-only.txt']
        (ref / 'qtbase' / 'LGPL-3.0-only.txt').unlink()
        self.write_provenance(ref, data)
        with self.assertRaisesRegex(RuntimeError, 'required'):
            self.pkg.verify_qt_reference(ref)

    def test_symlinked_file_dir_or_provenance_is_rejected(self):
        ref = self.copy_reference()
        target = ref / 'qtbase' / 'MIT.txt'
        real = self.base / 'real-mit.txt'
        real.write_bytes(target.read_bytes())
        target.unlink()
        try:
            os.symlink(real, target)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks not creatable here')
        with self.assertRaisesRegex(RuntimeError, '(?i)symlink'):
            self.pkg.verify_qt_reference(ref)
        ref2 = self.base / 'ref4'
        shutil.copytree(REFERENCE, ref2)
        moved = self.base / 'moved-qtbase'
        shutil.move(str(ref2 / 'qtbase'), str(moved))
        os.symlink(moved, ref2 / 'qtbase', target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, '(?i)symlink'):
            self.pkg.verify_qt_reference(ref2)
        ref3 = self.base / 'ref5'
        shutil.copytree(REFERENCE, ref3)
        prov = ref3 / 'PROVENANCE.json'
        real_prov = self.base / 'prov.json'
        real_prov.write_bytes(prov.read_bytes())
        prov.unlink()
        os.symlink(real_prov, prov)
        with self.assertRaisesRegex(RuntimeError, '(?i)symlink'):
            self.pkg.verify_qt_reference(ref3)

    def test_installed_qt_version_must_match_the_reference_version(self):
        with self.assertRaisesRegex(RuntimeError, '6.5.4'):
            self.pkg.verify_qt_reference(REFERENCE, installed_versions={'PySide6': '6.5.4'})
        self.assertTrue(self.pkg.verify_qt_reference(REFERENCE, installed_versions={'PySide6': '6.5.3'}))

    def test_missing_reference_folder_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'reference'):
            self.pkg.verify_qt_reference(self.base / 'absent')


class CollectReference(Base):
    def test_files_provenance_and_hashes_are_copied_into_the_notice_folder(self):
        dest = self.base / 'notices'
        result = self.pkg.collect_qt_reference_notices(dest)
        self.assertEqual(len(result['files']), 22)
        self.assertEqual(result['version'], '6.5.3')
        for item in result['files']:
            copied = dest / item['dest']
            self.assertTrue(copied.is_file(), item['dest'])
            self.assertEqual(hashlib.sha256(copied.read_bytes()).hexdigest(), item['sha256'])
            self.assertEqual(copied.stat().st_size, item['bytes'])
            self.assertTrue(item['url'].startswith('https://raw.githubusercontent.com/'))
            self.assertEqual(len(item['commit']), 40)
        prov = dest / result['provenance']['dest']
        self.assertEqual(prov.read_bytes(), (REFERENCE / 'PROVENANCE.json').read_bytes())
        self.assertEqual(result['provenance']['sha256'], hashlib.sha256(prov.read_bytes()).hexdigest())
        self.assertIn('not a finding', result['note'].lower())

    def test_tampered_reference_stops_collection_before_anything_is_copied(self):
        ref = self.base / 'ref'
        shutil.copytree(REFERENCE, ref)
        target = ref / 'pyside-setup' / 'BSD-3-Clause.txt'
        target.write_bytes(target.read_bytes()[:-1] + b'Z')
        dest = self.base / 'notices'
        with self.assertRaises(RuntimeError):
            self.pkg.collect_qt_reference_notices(dest, reference_dir=ref)
        self.assertFalse(dest.exists() and any(dest.rglob('*')))

    def test_the_reference_source_is_not_modified(self):
        before = {p.relative_to(REFERENCE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in REFERENCE.rglob('*') if p.is_file()}
        self.pkg.collect_qt_reference_notices(self.base / 'notices')
        after = {p.relative_to(REFERENCE).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in REFERENCE.rglob('*') if p.is_file()}
        self.assertEqual(before, after)


class LegalNoteAndBuildWiring(Base):
    def test_legal_note_keeps_the_explicit_non_determination_wording(self):
        note = self.pkg.LEGAL_NOTE.lower()
        for phrase in ('actual', 'not a legal determination', 'compatib', 'franchise', 'completeness'):
            self.assertIn(phrase, note, phrase)

    def test_reference_note_states_what_it_is_not(self):
        note = self.pkg.QT_REFERENCE_NOTE.lower()
        for phrase in ('not a finding', 'compatibility', 'all qt modules', 'third-party', 'franchise'):
            self.assertIn(phrase, note, phrase)

    def test_source_inputs_cover_third_party_and_build_records_the_reference(self):
        root = self.base / 'repo'
        (root / 'third_party' / 'qt-6.5.3' / 'qtbase').mkdir(parents=True)
        (root / 'third_party' / 'qt-6.5.3' / 'qtbase' / 'MIT.txt').write_text('mit', encoding='utf-8')
        self.assertIn('third_party/qt-6.5.3/qtbase/MIT.txt', self.pkg.source_inputs(root))
        text = (REPO / 'package_scripted.py').read_text(encoding='utf-8')
        self.assertIn("'qt_reference_notices'", text)
        self.assertIn('collect_qt_reference_notices(', text)
        self.assertIn('qt_notice_problems(', text)


if __name__ == '__main__':
    unittest.main()
