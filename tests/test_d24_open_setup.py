"""D2.4: the connector points at no provider and is open to anyone's own setup; the release
scanner knows only generic private paths plus a maintainer's own markers.

Behaviour contracts on real code paths (no network: every request goes to a spy transport):
  1. No preset provider: empty base URL and model with neutral placeholders; Test connection
     and Save refuse them in plain words; saved values are kept; offline until filled in.
  2. A server on this computer needs no key; any other host needs one, and a key never goes
     over plain http:// to another computer.
  3. scripts/scan_release.py: generic private paths, plus markers from an untracked file.
"""
import contextlib
import importlib.util
import io
import json
import random
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / 'full-engine'
SCAN_SCRIPT = REPO / 'scripts' / 'scan_release.py'
LOCAL_URLS = ('http://localhost:11434/v1', 'http://127.0.0.1:1234/v1', 'http://[::1]:8000/v1',
              'http://LOCALHOST:11434/v1')
HOSTED = 'https://hosted.example/v1'
KEY = 'sk-d24-test-key-0123456789'


class Spy:
    """Records every request; answers an OpenAI-compatible completion or a relay reply."""

    def __init__(self, body=None):
        self.calls = []
        self.body = body or {'choices': [{'message': {'role': 'assistant', 'content': '[happy] Fine.'}}]}

    def __call__(self, request, timeout):
        self.calls.append({'url': request.full_url, 'method': request.get_method(),
                           'auth': request.get_header('Authorization'),
                           'body': json.loads(request.data.decode('utf-8')) if request.data else None})
        body = self.body(request) if callable(self.body) else self.body
        data = body if isinstance(body, bytes) else json.dumps(body).encode('utf-8')

        class Response:
            status = 200

            def read(self, *args):
                return data

            def close(self):
                pass
        return Response()


class XorCodec:
    def protect(self, data):
        return bytes(b ^ 0x33 for b in data)[::-1]

    def unprotect(self, data):
        return bytes(b ^ 0x33 for b in data[::-1])


def bc():
    from DyberPet import brain_client
    return brain_client


def brain(own, transport):
    return bc().ConversationBrain(relay_loader=lambda: None, own_key_loader=lambda: dict(own),
                                  transport=transport, lines={}, rng=random.Random(3),
                                  prompt_loader=lambda: 'SOUL', sleep=lambda s: None)


def wait_for_test(app, view, seconds=5.0):
    """D2.5: Test connection runs in the background; wait until its result is shown."""
    import time
    deadline = time.monotonic() + seconds
    while not view.test.isEnabled() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


def load_scanner():
    spec = importlib.util.spec_from_file_location('scan_release_d24', SCAN_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProfileCase(unittest.TestCase):
    def setUp(self):
        from DyberPet.paths import user_root
        self.ai = user_root() / 'ai.json'
        if self.ai.exists():
            self.ai.unlink()
        self.folder = tempfile.TemporaryDirectory()
        from DyberPet.key_store import KeyStore
        self.store = KeyStore(Path(self.folder.name) / 'own_key.dpapi', codec=XorCodec())
        self.no_crypto = KeyStore(Path(self.folder.name) / 'none.dpapi', codec=None)

    def tearDown(self):
        if self.ai.exists():
            self.ai.unlink()
        self.folder.cleanup()

    def write_ai(self, data):
        self.ai.parent.mkdir(parents=True, exist_ok=True)
        self.ai.write_text(json.dumps(data), encoding='utf-8')

    def mode(self, store):
        from DyberPet.brain import load_own_key
        return bc().ConversationBrain(relay_loader=lambda: None, own_key_loader=lambda: load_own_key(store),
                                      lines={}).mode()


# --------------------------------------------------------------------------------------------
# 1. No preset provider
# --------------------------------------------------------------------------------------------

class NoPresetProvider(ProfileCase):
    def test_every_default_source_is_empty(self):
        from DyberPet.brain import DEFAULT_CONFIG, load_config
        self.assertEqual((bc().DEFAULT_BASE_URL, bc().DEFAULT_MODEL), ('', ''))
        self.assertEqual(DEFAULT_CONFIG['own_key'], {'base_url': '', 'model': '', 'daily_cap': 200})
        documented = json.loads((ENGINE / 'config' / 'brain.json').read_text(encoding='utf-8'))
        documented.pop('_status')
        self.assertEqual(documented, DEFAULT_CONFIG)
        self.assertEqual(load_config(), DEFAULT_CONFIG, 'a new profile')

    def test_a_new_profile_is_offline_even_with_a_stored_key(self):
        self.store.save(KEY)
        self.assertEqual(self.mode(self.store), 'offline')
        self.write_ai({'provider': 'own_key'})       # chosen, but nothing filled in
        self.assertEqual(self.mode(self.store), 'offline')
        self.write_ai({'provider': 'own_key', 'own_key': {'base_url': HOSTED, 'model': ''}})
        self.assertEqual(self.mode(self.store), 'offline')
        self.write_ai({'provider': 'own_key', 'own_key': {'base_url': HOSTED, 'model': 'vendor/m'}})
        self.assertEqual(self.mode(self.store), 'own_key')
        self.store.forget()
        self.assertEqual(self.mode(self.store), 'offline', 'a hosted endpoint still needs its key')

    def test_choosing_own_ai_without_base_url_or_model_is_refused(self):
        from DyberPet.brain import load_config, save_preferences
        with self.assertRaisesRegex(ValueError, 'base URL'):
            save_preferences('own_key', '', 'vendor/m')
        with self.assertRaisesRegex(ValueError, 'model'):
            save_preferences('own_key', HOSTED, '')
        self.assertEqual(load_config()['provider'], 'offline_phrases')

    def test_values_a_user_already_saved_are_kept(self):
        from DyberPet.brain import load_config, save_preferences
        saved = {'base_url': 'https://older.example/api/v1', 'model': 'vendor/older-model', 'daily_cap': 30}
        self.write_ai({'provider': 'own_key', 'own_key': dict(saved)})
        self.assertEqual(load_config()['own_key'], saved)
        save_preferences('offline_phrases')
        self.assertEqual(load_config()['own_key'], saved, 'going offline keeps the saved endpoint')
        save_preferences('own_key')                   # re-enable without retyping
        self.assertEqual(load_config(), {'provider': 'own_key', 'own_key': saved})
        from PySide6.QtWidgets import QApplication
        QApplication.instance() or QApplication([])
        from DyberPet.DyberSettings.AIPrivacyUI import AIPrivacyInterface
        view = AIPrivacyInterface(store=self.store, tester=lambda *a: self.fail('no request'))
        self.assertEqual((view.endpoint.text(), view.model.text(), view.daily_cap.value()),
                         (saved['base_url'], saved['model'], 30))
        view.close()


class SettingsRefuseEmptyFields(ProfileCase):
    def setUp(self):
        super().setUp()
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        self.requests = []

    def view(self, store=None):
        from DyberPet.DyberSettings.AIPrivacyUI import AIPrivacyInterface
        return AIPrivacyInterface(store=store or self.store,
                                  tester=lambda *a: (self.requests.append(a), (True, 'OK'))[1],
                                  warmer=lambda settings: self.fail('no warm-up here'))

    def test_fields_start_empty_with_neutral_placeholders(self):
        view = self.view()
        self.assertEqual((view.endpoint.text(), view.model.text()), ('', ''))
        self.assertEqual(view.endpoint.placeholderText(), 'https://your-endpoint.example/v1')
        self.assertEqual(view.model.placeholderText(), 'provider/model-name')
        self.assertIn('offline', view.mode_label.text().lower())
        view.close()

    def test_test_connection_refuses_an_empty_base_url_or_model_without_a_request(self):
        view = self.view()
        view.api_key.setText(KEY)
        view.test.click()
        self.assertIn('base url', view.status.text().lower())
        view.endpoint.setText(HOSTED)
        view.test.click()
        self.assertIn('model', view.status.text().lower())
        self.assertEqual(self.requests, [])
        self.assertNotIn(KEY, view.status.text())
        view.model.setText('vendor/m')
        view.test.click()
        wait_for_test(self.app, view)     # REVISED (D2.5): Test connection runs in the background
        self.assertEqual(self.requests, [(HOSTED, KEY, 'vendor/m')])
        self.assertEqual(view.status.text(), 'Connection OK.')
        view.close()

    def test_save_refuses_an_empty_base_url_or_model_and_stores_nothing(self):
        from DyberPet.brain import load_config
        view = self.view()
        view.api_key.setText(KEY)
        view.model.setText('vendor/m')
        view.save.click()
        self.assertIn('not saved', view.status.text().lower())
        self.assertIn('base url', view.status.text().lower())
        view.endpoint.setText(HOSTED)
        view.model.setText('')
        view.save.click()
        self.assertIn('model', view.status.text().lower())
        self.assertFalse(self.store.has_key(), 'a refused save stores no key')
        self.assertEqual(load_config()['provider'], 'offline_phrases')
        self.assertEqual(load_config()['own_key']['base_url'], '')
        view.close()


# --------------------------------------------------------------------------------------------
# 2. Open to anyone's setup: local servers, keys never over plain http to another computer
# --------------------------------------------------------------------------------------------

class LocalServersAndKeys(unittest.TestCase):
    def test_rules_in_plain_words(self):
        problem = bc().own_key_problem
        for url in LOCAL_URLS:
            self.assertIsNone(problem(url, '', 'local/model'), url)
            self.assertIsNone(problem(url, KEY, 'local/model'), url)
        self.assertIsNone(problem(HOSTED, KEY, 'vendor/m'))
        self.assertIn('api key', problem(HOSTED, '', 'vendor/m').lower())
        for url in ('http://hosted.example/v1', 'http://192.168.1.50:8080/v1'):
            for key in (KEY, ''):
                message = problem(url, key, 'vendor/m')
                self.assertIn('never sent over plain http://', message, (url, key))
                self.assertNotIn(KEY, message)
        # Look-alike hosts are not this computer.
        for url in ('http://localhost.attacker.example/v1', 'http://127.0.0.1.attacker.example/v1'):
            self.assertIsNotNone(problem(url, '', 'm'), url)
            self.assertFalse(bc().is_local_url(url), url)
        self.assertIn('base url', problem('', KEY, 'm').lower())
        self.assertIn('model', problem(HOSTED, KEY, ' ').lower())

    def test_a_local_server_is_used_without_a_key_and_gets_no_authorization_header(self):
        spy = Spy()
        b = brain({'base_url': 'http://localhost:11434/v1', 'model': 'local/model', 'api_key': ''}, spy)
        self.assertEqual(b.mode(), 'own_key')
        self.assertEqual(b.plan('chat'), 'remote')
        reply = b.remote_chat('hello')
        self.assertEqual((reply.source, reply.text), ('own_key', 'Fine.'))
        # REVISED (D2.5): a `localhost` base URL connects to 127.0.0.1 (IPv6 ::1 was slow on Windows).
        self.assertEqual(spy.calls[0]['url'], 'http://127.0.0.1:11434/v1/chat/completions')
        self.assertIsNone(spy.calls[0]['auth'])
        self.assertEqual(spy.calls[0]['body']['model'], 'local/model')

    def test_a_local_server_with_a_key_gets_it(self):
        spy = Spy()
        brain({'base_url': 'http://127.0.0.1:1234/v1', 'model': 'm', 'api_key': KEY}, spy).remote_chat('hi')
        self.assertEqual(spy.calls[0]['auth'], 'Bearer ' + KEY)

    def test_a_key_is_never_sent_over_plain_http_to_another_computer(self):
        spy = Spy()
        own = {'base_url': 'http://hosted.example/v1', 'model': 'm', 'api_key': KEY}
        b = brain(own, spy)
        self.assertEqual(b.mode(), 'offline')
        self.assertEqual(b.remote_chat('hi').source, 'offline')
        # Even the low-level client refuses before any transport call, and does not retry.
        with self.assertRaises(bc().BrainError) as caught:
            bc().OwnKeyClient(own['base_url'], KEY, 'm', spy, sleep=lambda s: None).complete(
                [{'role': 'user', 'content': 'x'}])
        self.assertEqual(caught.exception.kind, 'insecure')
        self.assertNotIn(KEY, str(caught.exception))
        ok, message = bc().test_own_key(own['base_url'], KEY, 'm', spy)
        self.assertFalse(ok)
        self.assertNotIn(KEY, message)
        self.assertEqual(spy.calls, [])

    def test_a_hosted_endpoint_without_a_key_stays_offline(self):
        spy = Spy()
        b = brain({'base_url': HOSTED, 'model': 'm', 'api_key': ''}, spy)
        self.assertEqual(b.mode(), 'offline')
        self.assertEqual(b.remote_chat('hi').source, 'offline')
        self.assertEqual(spy.calls, [])

    def test_test_connection_against_a_local_server_needs_no_key(self):
        spy = Spy({'choices': [{'message': {'content': 'OK'}}]})
        self.assertEqual(bc().test_own_key('http://localhost:1234/v1', '', 'local/m', spy), (True, 'OK'))
        self.assertIsNone(spy.calls[0]['auth'])
        # REVISED (D2.5): a `localhost` base URL connects to 127.0.0.1.
        self.assertEqual(spy.calls[0]['url'], 'http://127.0.0.1:1234/v1/chat/completions')


class SettingsForLocalServers(ProfileCase):
    def setUp(self):
        super().setUp()
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        self.requests = []

    def view(self, store):
        from DyberPet.DyberSettings.AIPrivacyUI import AIPrivacyInterface
        # D2.5: saving a local server warms it up; the spy keeps the tests off the network.
        self.warmed = []
        return AIPrivacyInterface(store=store, tester=lambda *a: (self.requests.append(a), (True, 'OK'))[1],
                                  warmer=lambda settings: self.warmed.append(settings) or 'ok')

    def test_a_local_server_is_saved_without_a_key_even_without_encryption(self):
        from DyberPet.brain import load_config, load_own_key
        view = self.view(self.no_crypto)
        view.endpoint.setText('http://localhost:11434/v1')
        view.model.setText('local/model')
        view.test.click()
        wait_for_test(self.app, view)     # REVISED (D2.5): Test connection runs in the background
        self.assertEqual(self.requests, [('http://localhost:11434/v1', '', 'local/model')])
        with patch('DyberPet.DyberSettings.AIPrivacyUI.active_mode', return_value='own_key'):
            view.save.click()
        self.assertTrue(view.status.text().startswith('Saved.'), view.status.text())
        self.assertEqual(load_config()['provider'], 'own_key')
        own = load_own_key(self.no_crypto)
        self.assertEqual((own['base_url'], own['model'], own['api_key']),
                         ('http://localhost:11434/v1', 'local/model', ''))
        self.assertEqual(self.mode(self.no_crypto), 'own_key')
        self.assertIn('localhost', view.mode_label.text())
        view.close()

    def test_a_key_for_plain_http_to_another_computer_is_refused_and_not_stored(self):
        from DyberPet.brain import load_config
        view = self.view(self.store)
        view.endpoint.setText('http://hosted.example/v1')
        view.model.setText('vendor/m')
        view.api_key.setText(KEY)
        view.test.click()
        self.assertIn('never sent over plain http://', view.status.text())
        view.save.click()
        self.assertIn('never sent over plain http://', view.status.text())
        self.assertNotIn(KEY, view.status.text())
        self.assertEqual(self.requests, [])
        self.assertFalse(self.store.has_key())
        self.assertEqual(load_config()['provider'], 'offline_phrases')
        view.close()

    def test_a_hosted_endpoint_still_needs_a_key(self):
        view = self.view(self.store)
        view.endpoint.setText(HOSTED)
        view.model.setText('vendor/m')
        view.save.click()
        self.assertIn('enter an api key', view.status.text().lower())
        view.test.click()
        self.assertEqual(self.requests, [])
        view.close()


# --------------------------------------------------------------------------------------------
# 3. Release scanner: generic private paths plus a maintainer's own markers
# --------------------------------------------------------------------------------------------

class PrivateMarkers(unittest.TestCase):
    MARKER = 'D:/Lab/Secret/x'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'tree'
        self.root.mkdir()
        self.scan = load_scanner()
        self.markers = self.base / 'markers.txt'
        self.markers.write_text('# my own setup\n\n%s\nSecretBox\n' % self.MARKER.lower(), encoding='utf-8')

    def put(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = self.scan.main(['--root', str(self.root), *argv])
        return code, out.getvalue()

    def test_markers_file_format(self):
        self.assertEqual(self.scan.load_private_markers(self.markers), [b'd:/lab/secret/x', b'secretbox'])
        self.assertEqual(self.scan.load_private_markers(self.base / 'absent'), [])

    def test_a_marker_is_a_blocking_finding_and_is_never_printed(self):
        self.put('notes/a.md', 'line one\nsee %s here\n' % self.MARKER)
        self.put('b.py', '# built on SECRETBOX\n')
        self.put('c.py', 'clean = True\n')
        markers = self.scan.load_private_markers(self.markers)
        report = self.scan.scan_tree(self.root, markers=markers)
        found = {(i['rule'], i['path'], i.get('line')) for i in report['findings']}
        self.assertEqual(found, {('private-marker', 'notes/a.md', 2), ('private-marker', 'b.py', 1)})
        code, output = self.run_main('--private-markers', str(self.markers))
        self.assertEqual(code, 1)
        self.assertIn('private-marker', output)
        for secret in (self.MARKER, self.MARKER.lower(), 'secretbox', 'SECRETBOX'):
            self.assertNotIn(secret, output)

    def test_without_markers_an_invented_folder_is_not_flagged(self):
        self.put('a.md', 'see %s\n' % self.MARKER)
        with patch.object(self.scan, 'DEFAULT_MARKERS_FILE', self.base / 'absent'):
            code, output = self.run_main()
        self.assertEqual(code, 0, output)

    def test_the_default_markers_file_is_read_when_present(self):
        self.put('a.md', 'see %s\n' % self.MARKER)
        with patch.object(self.scan, 'DEFAULT_MARKERS_FILE', self.markers):
            code, output = self.run_main()
        self.assertEqual(code, 1)
        self.assertIn('private-marker', output)

    def test_a_missing_markers_file_is_a_usage_error(self):
        code, _ = self.run_main('--private-markers', str(self.base / 'nope.txt'))
        self.assertEqual(code, 2)

    def test_the_markers_file_at_the_root_is_not_scanned_but_never_ships(self):
        (self.root / '.release-private-markers').write_text(self.MARKER + '\n', encoding='utf-8')
        report = self.scan.scan_tree(self.root, markers=[self.MARKER])
        self.assertEqual(report['findings'], [], 'the list itself is not a leak')
        self.put('sub/.release-private-markers', 'x\n')
        rules = {(i['rule'], i['path']) for i in self.scan.scan_tree(self.root)['findings']}
        self.assertIn(('private-artifact', 'sub/.release-private-markers'), rules)
        archive = self.base / 'p.zip'
        with zipfile.ZipFile(archive, 'w') as z:
            z.writestr('MiniDraconia/.release-private-markers', 'x')
        rules = {i['rule'] for i in self.scan.scan_archive(archive)['findings']}
        self.assertIn('private-artifact', rules)

    def test_the_markers_file_is_git_ignored(self):
        inside = subprocess.run(['git', 'rev-parse', '--is-inside-work-tree'], cwd=str(REPO),
                                capture_output=True, text=True)
        if inside.returncode != 0:
            self.skipTest('source export without a git work tree (the Windows build tree)')
        ignored = subprocess.run(['git', 'check-ignore', '-q', '.release-private-markers'], cwd=str(REPO))
        self.assertEqual(ignored.returncode, 0)


# Words of a private setup that must not appear anywhere in the public tree (split so this
# file does not spell them). Third-party code under third_party/ is out of scope.


if __name__ == '__main__':
    unittest.main()
