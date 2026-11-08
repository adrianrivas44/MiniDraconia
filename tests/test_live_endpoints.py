"""Opt-in live test against a real OpenAI-compatible server on your own computer (D2.5).

Skipped unless both are set:

    MINIDRACONIA_LIVE_LOCAL_URL    e.g. http://127.0.0.1:11434/v1 (or http://localhost:11434/v1)
    MINIDRACONIA_LIVE_LOCAL_MODEL  the model name exactly as the server lists it

No API key is used, and none is ever read from the environment. The test runs the real client and
the real Settings view (offscreen Qt) in the isolated test profile, and checks:

  - Test connection shows "Connection OK.";
  - saving makes the mode "your own AI";
  - the warm-up reaches the server and does not count toward the daily limit;
  - one typed chat goes through ConversationBrain with source own_key, a known emotion and a
    bubble text without a role prefix or bracket junk;
  - the daily counter increases by exactly 1.

See docs/DEVELOPMENT.md ("Live test against your own local server").
"""
import os
import tempfile
import time
import unittest
from pathlib import Path

URL = os.environ.get('MINIDRACONIA_LIVE_LOCAL_URL', '').strip()
MODEL = os.environ.get('MINIDRACONIA_LIVE_LOCAL_MODEL', '').strip()
# Generous: the first request after the server starts may have to load the model.
WAIT_S = 200.0


@unittest.skipUnless(URL and MODEL, 'set MINIDRACONIA_LIVE_LOCAL_URL and MINIDRACONIA_LIVE_LOCAL_MODEL '
                                    'to run the live test against your own local server')
class LiveLocalServer(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        from DyberPet import brain_client
        from DyberPet.key_store import KeyStore
        from DyberPet.paths import user_root
        self.bc = brain_client
        self.assertTrue(brain_client.is_local_url(URL),
                        'the live test only talks to a server on this computer (localhost, 127.0.0.1, ::1)')
        self.app = QApplication.instance() or QApplication([])
        self.ai = user_root() / 'ai.json'
        if self.ai.exists():
            self.ai.unlink()
        self.folder = tempfile.TemporaryDirectory()
        # No key at all: a store that cannot hold one.
        self.store = KeyStore(Path(self.folder.name) / 'none.dpapi', codec=None)

    def tearDown(self):
        if self.ai.exists():
            self.ai.unlink()
        self.folder.cleanup()

    def pump_until(self, done, seconds=WAIT_S):
        deadline = time.monotonic() + seconds
        while not done() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.05)
        self.app.processEvents()

    def test_settings_warm_up_and_one_typed_chat(self):
        from DyberPet.DyberSettings.AIPrivacyUI import AIPrivacyInterface, active_mode
        from DyberPet.brain import load_own_key

        warmed = []

        def warmer(settings):          # the real warm-up, recorded
            result = self.bc.warm_up_own_ai(settings)
            warmed.append(result)
            return result

        view = AIPrivacyInterface(store=self.store, warmer=warmer)
        try:
            view.endpoint.setText(URL)
            view.model.setText(MODEL)
            view.test.click()
            self.pump_until(view.test.isEnabled)
            self.assertEqual(view.status.text(), 'Connection OK.')

            view.save.click()
            self.assertTrue(view.status.text().startswith('Saved.'), view.status.text())
            self.assertEqual(active_mode(), 'own_key')
            self.assertIn('your own ai', view.mode_label.text().lower())
            self.pump_until(lambda: bool(warmed))
            self.assertEqual(warmed, ['ok'])
        finally:
            view.close()

        counter = self.bc.DailyCounter(Path(self.folder.name) / 'own_key_usage.json')
        brain = self.bc.ConversationBrain(own_key_loader=lambda: load_own_key(self.store),
                                          counter=counter)
        self.assertEqual(brain.mode(), 'own_key')
        self.assertTrue(brain.waits_on_local_server())

        before = counter.used_today()
        self.assertEqual(brain.warm_up(), 'ok')
        self.assertEqual(counter.used_today(), before, 'the warm-up never counts')

        reply = brain.remote_chat('Good evening, Draconia. How was your tea?')
        self.assertEqual(reply.source, 'own_key', 'error: %s' % reply.error)
        self.assertIn(reply.emotion, self.bc.EMOTIONS)
        self.assertTrue(reply.text.strip())
        self.assertNotRegex(reply.text, r'^(?i:\s*(assistant|draconia)\s*[:>])')
        self.assertNotRegex(reply.text, r'^\s*(?i:assistant)\s*$')
        self.assertNotIn('[', reply.text)
        self.assertNotIn(']', reply.text)
        self.assertEqual(counter.used_today(), before + 1)


if __name__ == '__main__':
    unittest.main()
