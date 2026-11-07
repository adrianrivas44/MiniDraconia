"""D2.4: the public rc.2 tree names nothing of a private setup, recommends no provider, and its
docs describe the protocol, manifest and settings the code really uses (checked against the
real client with a spy transport, never against hand-copied values).
"""
import hashlib
import json
import random
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


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


def bc():
    from DyberPet import brain_client
    return brain_client


def brain(own, transport):
    return bc().ConversationBrain(relay_loader=lambda: None, own_key_loader=lambda: dict(own),
                                  transport=transport, lines={}, rng=random.Random(3),
                                  prompt_loader=lambda: 'SOUL', sleep=lambda s: None)


PRIVATE_WORDS = re.compile('|'.join([
    'a' 'oi\\b', 'val' 'halla', '\\ba' 'iu\\b', 'hi' 'to0', 'obsi' 'dian', '\\be' 'den\\b',
    '10\\.' '88\\.', 'wire' 'guard', 'open' 'router', 'hai' 'ku', 'eleven' 'labs',
    '87' '66', '87' '67', 'mi' 'ka']), re.IGNORECASE)
# Reviewed false positives: (path, matched text) -> reason.
PRIVATE_WORDS_ALLOWED = {
    ('full-engine/res/icons/tomato.svg', '87' '66'): 'digits inside SVG path coordinates of the inherited DyberPet icon',
    ('full-engine/res/icons/tomato.svg', '87' '67'): 'digits inside SVG path coordinates of the inherited DyberPet icon',
    # The owner asked to publish his recommendation and measurements; nothing is preset in the app.
    ('docs/RECOMMENDED-SETUP.md', 'open' 'router'): 'documented recommendation, never a default',
    ('docs/RECOMMENDED-SETUP.md', 'hai' 'ku'): 'documented recommendation, never a default',
    ('docs/RECOMMENDED-SETUP.md', 'eleven' 'labs'): 'reference voice tool the maintainer used, not included',
}


def tree_files():
    """Tracked files (git work tree) or every file (a source export has only tracked files)."""
    inside = subprocess.run(['git', 'rev-parse', '--is-inside-work-tree'], cwd=str(REPO),
                            capture_output=True, text=True)
    if inside.returncode == 0:
        listed = subprocess.run(['git', 'ls-files', '-z'], cwd=str(REPO), capture_output=True, check=True)
        names = [n for n in listed.stdout.decode('utf-8').split('\0') if n]
    else:
        names = [p.relative_to(REPO).as_posix() for p in REPO.rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts]
    # The git-ignored private markers file lists those words on purpose and is never tracked.
    return [n for n in names if not n.startswith('third_party/') and n != '.release-private-markers']


class PublicTreeNamesNoPrivateSetup(unittest.TestCase):
    def test_no_private_setup_word_in_any_text_file(self):
        hits = []
        for name in tree_files():
            path = REPO / name
            try:
                with open(path, 'rb') as stream:
                    head = stream.read(8000)
                    if b'\0' in head:
                        continue        # binary, as git grep -I
                    data = head + stream.read()
            except OSError:
                continue
            text = data.decode('utf-8', errors='replace')
            for match in PRIVATE_WORDS.finditer(text):
                if (name, match.group(0).lower()) not in PRIVATE_WORDS_ALLOWED:
                    hits.append('%s:%d' % (name, text.count('\n', 0, match.start()) + 1))
        self.assertEqual(hits, [])

    def test_the_recommendation_page_says_nothing_is_preset(self):
        text = (REPO / 'docs' / 'RECOMMENDED-SETUP.md').read_text(encoding='utf-8')
        self.assertIn('Nothing here is preset in the app', text)
        self.assertIn('not tested', text.lower())
        self.assertIn('## Resumen en español', text)

    def test_no_provider_is_a_default_or_a_recommendation(self):
        names = ('anthropic', 'claude', 'grok', 'xai', 'x.ai', 'gemini', 'mistral', 'deepseek')
        for doc in ('README.md', 'README.es.md', 'RELEASE-NOTES.md', 'CHANGELOG.md', 'docs/PRIVACY.md',
                    'docs/ROADMAP.md', 'docs/CONNECT-YOUR-AI.md', 'docs/SELF-HOSTED-RELAY.md',
                    'docs/VOICE-PACK.md', 'docs/DEVELOPMENT.md'):
            text = (REPO / doc).read_text(encoding='utf-8').lower()
            for word in names:
                self.assertIsNone(re.search(r'\b%s\b' % re.escape(word), text), (doc, word))
        for value in (bc().DEFAULT_BASE_URL, bc().DEFAULT_MODEL, bc().PLACEHOLDER_BASE_URL, bc().PLACEHOLDER_MODEL):
            for word in names:
                self.assertNotIn(word, value.lower())


# --------------------------------------------------------------------------------------------
# 4. Docs describe what the code really does
# --------------------------------------------------------------------------------------------

def read(name):
    return (REPO / name).read_text(encoding='utf-8')


def json_blocks(text):
    return [json.loads(block) for block in re.findall(r'```json\n(.*?)```', text, re.DOTALL)]


class ConnectYourAiDoc(unittest.TestCase):
    def test_covers_any_endpoint_local_servers_cap_key_and_what_is_sent(self):
        text = read('docs/CONNECT-YOUR-AI.md')
        low = text.lower()
        for needle in ('openai-compatible', '/chat/completions', 'http://localhost:11434/v1',
                       'http://localhost:1234/v1', bc().PLACEHOLDER_BASE_URL, bc().PLACEHOLDER_MODEL,
                       'daily request limit', 'dpapi', 'forget key', 'what is sent', 'no key',
                       'never sent over plain http://', '## en español'):
            self.assertIn(needle.lower(), low, needle)
        self.assertIn(str(bc().DEFAULT_DAILY_CAP), text)

    def test_names_no_paid_provider_and_no_costs(self):
        low = read('docs/CONNECT-YOUR-AI.md').lower()
        for word in ('$', 'usd', 'eur', 'per million', 'price', 'pricing', 'cheap', 'free tier',
                     'we recommend', 'recomendamos'):
            self.assertNotIn(word, low, word)

    def test_the_request_shown_is_the_request_sent(self):
        spy = Spy()
        brain({'base_url': 'http://localhost:11434/v1', 'model': 'local/model', 'api_key': ''}, spy).remote_chat('hi')
        text = read('docs/CONNECT-YOUR-AI.md')
        for key in spy.calls[0]['body']:
            self.assertIn('"%s"' % key, text, key)


class SelfHostedRelayDoc(unittest.TestCase):
    def test_documents_the_protocol_the_client_speaks(self):
        def answer(request):
            if request.full_url.endswith('/v1/tts'):
                return b'RIFF\x24\x00\x00\x00WAVEfmt ' + b'\x00' * 32
            return {'emotion': 'happy', 'text': 'Fine.'}
        spy = Spy(answer)
        config = {'base_url': 'http://192.168.1.50:8080', 'token': 'relay-token'}
        client = bc().RelayClient(config, spy, sleep=lambda s: None)
        self.assertTrue(client.health())
        client.chat('hi', [{'role': 'user', 'content': 'earlier'}])
        client.tts('Fine.')
        text = read('docs/SELF-HOSTED-RELAY.md')
        for call in spy.calls:
            path = call['url'][len(config['base_url']):]
            self.assertIn('%s %s' % (call['method'], path), text)
            self.assertEqual(call['auth'], 'Bearer relay-token')
            for key in (call['body'] or {}):
                self.assertIn('"%s"' % key, text, key)
        self.assertIn('Authorization: Bearer', text)
        for emotion in bc().EMOTIONS:
            self.assertIn(emotion, text)
        for needle in ('minidraconia_relay.json', 'self-hosted relay (advanced)', 'never contains'):
            self.assertIn(needle, text.lower() if needle.islower() else text)

    def test_the_seed_example_is_a_valid_seed_on_an_example_host(self):
        text = read('docs/SELF-HOSTED-RELAY.md')
        seeds = [b for b in json_blocks(text) if set(b) == {'base_url', 'token'}]
        self.assertTrue(seeds)
        for seed in seeds:
            self.assertIsNotNone(bc().validate_relay_config(seed), seed)
        for host in re.findall(r'https?://([^/\s:`"\]\)]+)', text):
            self.assertIn(host, ('192.168.1.50', 'relay.example'), host)


class VoicePackDoc(unittest.TestCase):
    def test_the_documented_manifest_voices_a_line(self):
        from DyberPet.voice_pack import VoicePack
        manifests = [b for b in json_blocks(read('docs/VOICE-PACK.md')) if 'lines' in b]
        self.assertTrue(manifests)
        with tempfile.TemporaryDirectory() as folder:
            manifest = manifests[0]
            for entry in manifest['lines']:
                data = b'RIFF' + entry['file'].encode('utf-8')
                Path(folder, entry['file']).write_bytes(data)
                entry['sha256'] = hashlib.sha256(data).hexdigest()
            Path(folder, 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            pack = VoicePack(folder)
            for entry in manifest['lines']:
                self.assertEqual(pack.wav_for(entry['key'], entry['text']), str(Path(folder, entry['file'])))
                self.assertEqual(pack.emotion(entry['key'], entry['text']), entry['emotion'])

    def test_says_where_it_goes_and_that_it_never_ships(self):
        low = read('docs/VOICE-PACK.md').lower()
        for needle in ('voice_pack/', 'full-engine/voice_pack/', 'sha256', 'draconia_lines_en.json',
                       'never', 'public zip', 'git-ignored', 'anyone'):
            self.assertIn(needle, low, needle)


class ReleaseDocsForRc2(unittest.TestCase):
    def test_readmes_name_rc2_the_latest_prerelease_and_the_three_modes(self):
        en, es = read('README.md'), read('README.es.md')
        for text in (en, es):
            self.assertIn('1.0.0-rc.2', text)
            self.assertNotIn('1.0.0-rc.1 until', text)
            self.assertNotIn('1.0.0-rc.1 hasta', text)
            for link in ('docs/CONNECT-YOUR-AI.md', 'docs/SELF-HOSTED-RELAY.md', 'docs/VOICE-PACK.md'):
                self.assertIn(link, text)
            for clip in ('mirror', 'quill', 'yawn'):
                self.assertIn(clip, text)
        self.assertIn('self-hosted relay (advanced)', en.lower())
        self.assertIn('relay propio (avanzado)', es.lower())
        self.assertIn('latest prerelease', en.lower())
        self.assertIn('icon', en.lower())
        self.assertIn('icono', es.lower())

    def test_release_notes_are_signed_and_bilingual(self):
        notes = read('RELEASE-NOTES.md')
        self.assertIn('# MiniDraconia 1.0.0-rc.2', notes)
        self.assertGreaterEqual(notes.count('— Zero / adrianrivas44'), 1)
        self.assertIn('Mejoremos MiniDraconia juntos', notes)
        self.assertIn('self-hosted relay (advanced)', notes.lower())

    def test_checklist_keeps_rights_and_human_items_unchecked(self):
        text = read('docs/RELEASE-CHECKLIST.md')
        rc2 = text[text.index('## 1.0.0-rc.2'):]
        items = [line for line in rc2.splitlines() if line.startswith('- [')]
        self.assertTrue(items)
        for line in items:
            if re.search(r'rights|human|provenance', line, re.IGNORECASE):
                self.assertTrue(line.startswith('- [ ]'), line)


if __name__ == '__main__':
    unittest.main()
