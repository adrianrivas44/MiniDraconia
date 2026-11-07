"""D2 public docs: version rc.2, "Talking to Draconia", what is sent and to whom, no stale claims."""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


class PublicDocs(unittest.TestCase):
    def read(self, name):
        return (REPO / name).read_text(encoding='utf-8')

    def test_version_is_rc2(self):
        self.assertEqual(self.read('VERSION').strip(), '1.0.0-rc.2')
        self.assertIn('1.0.0-rc.2', self.read('CHANGELOG.md'))
        self.assertIn('1.0.0-rc.2', self.read('RELEASE-NOTES.md'))

    def test_talking_sections_say_offline_default_own_key_and_what_is_sent(self):
        en, es = self.read('README.md'), self.read('README.es.md')
        self.assertIn('## Talking to Draconia', en)
        self.assertIn('## Hablar con Draconia', es)
        for text in (en.lower(), es.lower()):
            # REVISED (D2.4): no provider is named as a default; any OpenAI-compatible endpoint.
            self.assertIn('openai', text)
            self.assertIn('docs/connect-your-ai.md', text)
            self.assertIn('dpapi', text)
        self.assertIn('nothing is sent anywhere', en.lower())
        self.assertIn('what is sent, and to whom', en.lower())

    def test_privacy_describes_the_own_key_data_and_key_storage(self):
        privacy = self.read('docs/PRIVACY.md').lower()
        for needle in ('typed messages', 'recent typed conversation', 'nothing else', 'encrypted', 'dpapi',
                       'daily request limit', 'forget key'):
            self.assertIn(needle, privacy)

    def test_no_stale_not_implemented_statement_remains(self):
        for name in ('README.md', 'README.es.md', 'RELEASE-NOTES.md', 'docs/PRIVACY.md', 'docs/KNOWN-ISSUES.md',
                     'docs/ROADMAP.md'):
            text = self.read(name).lower()
            for stale in ('this is not an ai chat application yet', 'todavía no conversa con ia',
                          'connectors are not implemented', 'future, not implemented',
                          'connect my ai is not available'):
                self.assertNotIn(stale, text, name)

    def test_no_new_dependencies(self):
        requirements = self.read('requirements.txt')
        for name in ('openai', 'requests', 'httpx', 'keyring', 'cryptography', 'pywin32-ctypes'):
            self.assertNotIn(name + '=', requirements.lower())


if __name__ == '__main__':
    unittest.main()
