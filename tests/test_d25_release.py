"""D2.5: the 1.0.0-rc.3 release documents say what changed, keep rc.2 as published, keep the
measurements as measured on rc.2, and invent no test results. The values that come from the code
(timeouts, the example address) are read from the code, not copied."""
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def read(name):
    return (REPO / name).read_text(encoding='utf-8')


def bc():
    from DyberPet import brain_client
    return brain_client


def section(text, heading):
    start = text.index(heading)
    rest = text[start + len(heading):]
    following = re.search(r'^## ', rest, re.MULTILINE)
    return text[start:start + len(heading) + (following.start() if following else len(rest))]


class Rc3(unittest.TestCase):
    def test_this_cut_ships_rc3(self):
        # The one literal of the cut; every other version test follows VERSION.
        self.assertEqual(read('VERSION').strip(), '1.0.0-rc.3')

    def test_changelog_has_rc3_first_and_keeps_rc2_as_published(self):
        text = read('CHANGELOG.md')
        headings = re.findall(r'^## (\S+)', text, re.MULTILINE)
        self.assertEqual(headings[0], read('VERSION').strip())
        self.assertIn('## 1.0.0-rc.2 — second community prerelease (published 2026-11-07)', text)
        rc3 = section(text, '## 1.0.0-rc.3')
        for needle in ('127.0.0.1', 'localhost', '[::1]', 'warm', 'daily limit', 'assistant>',
                       '[]bored]', 'test_live_endpoints.py', 'MINIDRACONIA_LIVE_LOCAL_URL',
                       '%d s' % bc().LOCAL_CHAT_TIMEOUT_S, '%d s' % bc().CHAT_TIMEOUT_S):
            self.assertIn(needle, rc3, needle)

    def test_release_notes_are_bilingual_signed_and_invent_no_results(self):
        notes = read('RELEASE-NOTES.md')
        self.assertIn('# MiniDraconia 1.0.0-rc.3', notes)
        self.assertIn('## What changed since rc.2', notes)
        self.assertIn('En español', notes)
        self.assertIn('Mejoremos MiniDraconia juntos', notes)
        self.assertIn('— Zero / adrianrivas44', notes)
        # Results are filled in at publication from the acceptance record; a check that was not
        # run must say so instead of claiming a result.
        self.assertIn('a check not reported here has not been run', notes)
        self.assertNotIn('[pending — filled in at publication]', notes)
        self.assertIn('not run', notes.lower())

    def test_known_issues_drop_the_fixed_items_and_keep_honest_limits(self):
        text = read('docs/KNOWN-ISSUES.md')
        self.assertNotIn('Use `127.0.0.1`.', text)
        self.assertNotIn('still shows `localhost`', text)
        self.assertNotIn('Warm the model up first', text)
        for needle in ('release candidate, not a stable product', 'human review', 'clean-machine install'):
            self.assertIn(needle, text.lower() if needle.islower() else text, needle)
        self.assertIn('RELEASE-CHECKLIST.md', text)

    def test_connect_and_setup_docs_say_localhost_works_and_keep_rc2_measurements(self):
        connect = read('docs/CONNECT-YOUR-AI.md')
        setup = read('docs/RECOMMENDED-SETUP.md')
        for text in (connect, setup):
            self.assertIn('works as fast as `127.0.0.1`', text)
            self.assertIn('warms', text)
            self.assertNotIn('Prefer `127.0.0.1` to `localhost`', text)
            self.assertNotIn('Use `127.0.0.1`, not `localhost`', text)
        self.assertIn('Measured on rc.2', connect)
        self.assertIn('%d seconds' % bc().LOCAL_CHAT_TIMEOUT_S, connect)
        self.assertIn('%d seconds' % bc().CHAT_TIMEOUT_S, connect)
        self.assertIn('### Local server: Ollama on Windows (rc.2, 7 November 2026)', setup)
        for measured in ('2.3–2.4 s', '41 s', '0.36 s'):
            self.assertIn(measured, setup)
        self.assertIn('localhost', read('docs/CONNECT-YOUR-AI.md').split('## En español')[1])

    def test_the_settings_hint_and_docs_use_the_same_example_address(self):
        self.assertEqual(bc().LOCAL_EXAMPLE_URL, 'http://127.0.0.1:11434/v1')
        for name in ('README.md', 'README.es.md', 'docs/CONNECT-YOUR-AI.md', 'docs/RECOMMENDED-SETUP.md'):
            self.assertIn(bc().LOCAL_EXAMPLE_URL, read(name), name)
            self.assertNotIn('http://localhost:11434', read(name), name)
        ui = read('full-engine/DyberPet/DyberSettings/AIPrivacyUI.py')
        self.assertNotIn('http://localhost', ui)

    def test_checklist_rc3_gate_list_keeps_human_and_rights_items_open(self):
        rc3 = read('docs/RELEASE-CHECKLIST.md').split('## 1.0.0-rc.3')[1]
        items = [line for line in rc3.splitlines() if line.startswith('- [')]
        self.assertGreaterEqual(len(items), 8)
        # Technical items are checked only with evidence; rights, human and people-on-a-display
        # items stay open until their own evidence exists.
        for line in items:
            if re.search(r'rights|human|provenance|by a person', line, re.IGNORECASE):
                self.assertTrue(line.startswith('- [ ]'), line)
        for needle in ('localhost', 'warm-up', 'test_live_endpoints.py', 'llama3.2:3b'):
            self.assertIn(needle, rc3, needle)

    def test_development_documents_the_opt_in_live_test_without_a_key(self):
        text = read('docs/DEVELOPMENT.md')
        for needle in ('MINIDRACONIA_LIVE_LOCAL_URL', 'MINIDRACONIA_LIVE_LOCAL_MODEL',
                       'test_live_endpoints.py', 'no API key', 'never reads a key from the environment'):
            self.assertIn(needle, text, needle)
        live = read('tests/test_live_endpoints.py')
        self.assertNotRegex(live, r'environ(\.get)?\(?\[?[\'"][A-Z_]*KEY')

    def test_privacy_discloses_the_local_warm_up(self):
        text = read('docs/PRIVACY.md')
        self.assertIn('warm-up request', text)
        self.assertIn('never goes to another computer', text)


if __name__ == '__main__':
    unittest.main()
