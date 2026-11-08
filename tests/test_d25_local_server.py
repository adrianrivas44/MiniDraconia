"""D2.5: a server on this computer is fast, survives a cold start, and weak models' replies are clean.

Behaviour contracts on real code paths (no network: every request goes to a fake transport that
records it):
  1. A base URL whose host is exactly `localhost` connects to 127.0.0.1 (scheme, port and path
     kept); when that connection is refused, [::1] is tried once. The saved preference keeps
     what the user typed. The Settings hint shows http://127.0.0.1:11434/v1.
  2. Local endpoints wait up to LOCAL_CHAT_TIMEOUT_S (chat and Test connection); hosted ones keep
     CHAT_TIMEOUT_S. A local endpoint is warmed up in the background at start and on save: one
     tiny request, never counted, never to another computer, a failure only logged. Test
     connection never blocks the Settings window. While a typed message waits on a local server
     for more than ~3 s, she shows her thinking pose.
  3. parse_reply strips role prefixes (assistant, assistant:, assistant>, Draconia:) before and
     after the emotion tag, and reads a malformed leading tag such as []bored].
"""
import json
import random
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

KEY = 'sk-d25-test-key-0123456789'
HOSTED = 'https://hosted.example/v1'
LOCAL = 'http://localhost:11434/v1'


def bc():
    from DyberPet import brain_client
    return brain_client


def completion(content):
    return {'choices': [{'message': {'role': 'assistant', 'content': content}}]}


class Response:
    status = 200

    def __init__(self, body):
        self._data = json.dumps(body).encode('utf-8')

    def read(self, *args):
        return self._data

    def close(self):
        pass


class Recorder:
    """Records url, timeout and body of every request. `answer(url)` returns a body or raises."""

    def __init__(self, answer=None):
        self.calls = []
        self.answer = answer or (lambda url: completion('[happy] Fine.'))

    def __call__(self, request, timeout):
        self.calls.append({'url': request.full_url, 'timeout': timeout,
                           'auth': request.get_header('Authorization'),
                           'body': json.loads(request.data.decode('utf-8')) if request.data else None})
        return Response(self.answer(request.full_url))

    @property
    def urls(self):
        return [call['url'] for call in self.calls]


def refused():
    raise urllib.error.URLError(ConnectionRefusedError(10061, 'refused'))


def ipv4_refused(url):
    if '//127.0.0.1' in url:
        refused()
    return completion('[happy] Over IPv6.')


def brain(own, transport, counter=None):
    return bc().ConversationBrain(relay_loader=lambda: None, own_key_loader=lambda: dict(own),
                                  transport=transport, lines={}, rng=random.Random(5),
                                  prompt_loader=lambda: 'SOUL', sleep=lambda s: None,
                                  counter=counter)


def own(url, key='', cap=200):
    return {'base_url': url, 'model': 'local/model', 'api_key': key, 'daily_cap': cap}


class XorCodec:
    def protect(self, data):
        return bytes(b ^ 0x5a for b in data)[::-1]

    def unprotect(self, data):
        return bytes(b ^ 0x5a for b in data[::-1])


def pump(app, done, seconds=5.0):
    deadline = time.monotonic() + seconds
    while not done() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()


# --------------------------------------------------------------------------------------------
# 1. Local address
# --------------------------------------------------------------------------------------------

class LocalAddress(unittest.TestCase):
    def test_only_an_exact_localhost_host_is_connected_over_ipv4(self):
        table = [
            ('http://localhost:11434/v1', 'http://127.0.0.1:11434/v1'),
            ('http://LOCALHOST:1234/v1/', 'http://127.0.0.1:1234/v1/'),
            ('https://localhost/api/v1?x=1', 'https://127.0.0.1/api/v1?x=1'),
            ('http://localhost/v1', 'http://127.0.0.1/v1'),
            ('http://127.0.0.1:11434/v1', 'http://127.0.0.1:11434/v1'),
            ('http://[::1]:8000/v1', 'http://[::1]:8000/v1'),
            ('http://localhost.attacker.example/v1', 'http://localhost.attacker.example/v1'),
            ('http://mylocalhost:11434/v1', 'http://mylocalhost:11434/v1'),
            (HOSTED, HOSTED),
        ]
        for typed, connected in table:
            self.assertEqual(bc().connect_url(typed), connected, typed)

    def test_typed_chat_to_localhost_goes_to_127_0_0_1(self):
        spy = Recorder()
        reply = brain(own(LOCAL), spy).remote_chat('hello')
        self.assertEqual((reply.source, reply.text), ('own_key', 'Fine.'))
        self.assertEqual(spy.urls, ['http://127.0.0.1:11434/v1/chat/completions'])
        self.assertIsNone(spy.calls[0]['auth'])

    def test_test_connection_to_localhost_goes_to_127_0_0_1(self):
        spy = Recorder(lambda url: completion('OK'))
        self.assertEqual(bc().test_own_key('http://LocalHost:1234/v1', '', 'local/m', spy), (True, 'OK'))
        self.assertEqual(spy.urls, ['http://127.0.0.1:1234/v1/chat/completions'])

    def test_a_local_key_still_goes_only_to_the_local_server(self):
        spy = Recorder()
        brain(own(LOCAL, KEY), spy).remote_chat('hello')
        self.assertEqual(spy.urls, ['http://127.0.0.1:11434/v1/chat/completions'])
        self.assertEqual(spy.calls[0]['auth'], 'Bearer ' + KEY)

    def test_a_refused_ipv4_connection_tries_ipv6_once(self):
        spy = Recorder(ipv4_refused)
        counter = bc().DailyCounter(None)
        reply = brain(own(LOCAL), spy, counter).remote_chat('hello')
        self.assertEqual((reply.source, reply.text), ('own_key', 'Over IPv6.'))
        self.assertEqual(spy.urls, ['http://127.0.0.1:11434/v1/chat/completions',
                                    'http://[::1]:11434/v1/chat/completions'])
        self.assertEqual(counter.used_today(), 1, 'one request reached a server')

    def test_a_refusal_raised_directly_by_the_socket_also_falls_back(self):
        def answer(url):
            if '//127.0.0.1' in url:
                raise ConnectionRefusedError(111, 'refused')
            return completion('OK')
        spy = Recorder(answer)
        self.assertEqual(bc().test_own_key(LOCAL, '', 'local/m', spy), (True, 'OK'))
        self.assertEqual(len(spy.calls), 2)

    def test_refused_on_both_addresses_tries_ipv6_once_per_attempt_then_a_stored_line(self):
        def answer(url):
            refused()
        spy = Recorder(answer)
        reply = brain(own(LOCAL), spy).remote_chat('hello')
        self.assertEqual(reply.source, 'offline')
        self.assertEqual(reply.error, 'network')
        v4 = 'http://127.0.0.1:11434/v1/chat/completions'
        v6 = 'http://[::1]:11434/v1/chat/completions'
        self.assertEqual(spy.urls, [v4, v6] * bc().ATTEMPTS)

    def test_other_failures_never_fall_back(self):
        def timeout(url):
            raise socket.timeout('slow')
        spy = Recorder(timeout)
        brain(own(LOCAL), spy).remote_chat('hello')
        self.assertTrue(spy.urls)
        self.assertTrue(all('//127.0.0.1' in url for url in spy.urls), spy.urls)

    def test_an_address_typed_as_an_ip_is_used_as_typed(self):
        spy = Recorder(ipv4_refused)
        reply = brain(own('http://127.0.0.1:11434/v1'), spy).remote_chat('hello')
        self.assertEqual(reply.source, 'offline')
        self.assertTrue(all('//127.0.0.1' in url for url in spy.urls), spy.urls)

    def test_hosted_endpoints_are_untouched(self):
        spy = Recorder()
        brain(own(HOSTED, KEY), spy).remote_chat('hello')
        self.assertEqual(spy.urls, [HOSTED + '/chat/completions'])

    def test_plain_words_show_the_ipv4_address(self):
        problem = bc().own_key_problem('http://hosted.example/v1', KEY, 'm')
        self.assertIn('http://127.0.0.1:11434/v1', problem)
        self.assertNotIn('(localhost)', problem)


class ProfileCase(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        from DyberPet.key_store import KeyStore
        from DyberPet.paths import user_root
        self.app = QApplication.instance() or QApplication([])
        self.ai = user_root() / 'ai.json'
        if self.ai.exists():
            self.ai.unlink()
        self.folder = tempfile.TemporaryDirectory()
        self.store = KeyStore(Path(self.folder.name) / 'own_key.dpapi', codec=XorCodec())
        self.no_crypto = KeyStore(Path(self.folder.name) / 'none.dpapi', codec=None)
        self.tested, self.warmed = [], []

    def tearDown(self):
        if self.ai.exists():
            self.ai.unlink()
        self.folder.cleanup()

    def view(self, store=None, tester=None, warmer=None):
        from DyberPet.DyberSettings.AIPrivacyUI import AIPrivacyInterface
        return AIPrivacyInterface(
            store=store or self.no_crypto,
            tester=tester or (lambda *a: (self.tested.append(a), (True, 'OK'))[1]),
            warmer=warmer or (lambda settings: self.warmed.append(dict(settings)) or 'ok'))

    def wait_test(self, view):
        pump(self.app, lambda: view.test.isEnabled())


class SettingsLocalAddress(ProfileCase):
    def test_the_hint_shows_the_ipv4_address_and_no_localhost_example(self):
        from PySide6.QtWidgets import QLabel
        view = self.view()
        texts = [label.text() for label in view.body.findChildren(QLabel)]
        self.assertTrue(any('http://127.0.0.1:11434/v1' in text for text in texts), texts)
        for text in texts:
            self.assertNotIn('localhost:', text)
        view.close()

    def test_the_saved_preference_keeps_what_the_user_typed(self):
        from DyberPet.brain import load_config, load_own_key
        view = self.view()
        view.endpoint.setText(LOCAL)
        view.model.setText('local/model')
        view.test.click()
        self.wait_test(view)
        self.assertEqual(self.tested, [(LOCAL, '', 'local/model')])
        view.save.click()
        self.assertTrue(view.status.text().startswith('Saved.'), view.status.text())
        self.assertEqual(load_config()['own_key']['base_url'], LOCAL)
        self.assertEqual(load_own_key(self.no_crypto)['base_url'], LOCAL)
        view.close()


# --------------------------------------------------------------------------------------------
# 2. Cold start of a local server
# --------------------------------------------------------------------------------------------

class LocalTimeouts(unittest.TestCase):
    def test_local_endpoints_wait_longer_for_chat_and_test_connection(self):
        self.assertGreaterEqual(bc().LOCAL_CHAT_TIMEOUT_S, 60)
        self.assertLessEqual(bc().LOCAL_CHAT_TIMEOUT_S, 120)
        for url in (LOCAL, 'http://127.0.0.1:1234/v1', 'http://[::1]:8000/v1'):
            spy = Recorder()
            brain(own(url), spy).remote_chat('hello')
            self.assertEqual(spy.calls[0]['timeout'], bc().LOCAL_CHAT_TIMEOUT_S, url)
            spy = Recorder(lambda u: completion('OK'))
            bc().test_own_key(url, '', 'local/m', spy)
            self.assertEqual(spy.calls[0]['timeout'], bc().LOCAL_CHAT_TIMEOUT_S, url)

    def test_hosted_endpoints_keep_their_timeout(self):
        self.assertEqual(bc().CHAT_TIMEOUT_S, 20)
        spy = Recorder()
        brain(own(HOSTED, KEY), spy).remote_chat('hello')
        self.assertEqual(spy.calls[0]['timeout'], 20)
        spy = Recorder(lambda u: completion('OK'))
        bc().test_own_key(HOSTED, KEY, 'm', spy)
        self.assertEqual(spy.calls[0]['timeout'], 20)


class WarmUp(unittest.TestCase):
    TEST_SHAPE = [{'role': 'user', 'content': 'Reply with the single word OK.'}]

    def test_one_tiny_request_like_test_connection_that_never_counts(self):
        spy = Recorder(lambda url: completion('OK'))
        counter = bc().DailyCounter(None)
        b = brain(own(LOCAL, cap=1), spy, counter)
        self.assertEqual(b.warm_up(), 'ok')
        self.assertEqual(len(spy.calls), 1)
        body = spy.calls[0]['body']
        self.assertEqual(body['messages'], self.TEST_SHAPE)
        self.assertEqual(body['max_tokens'], 5)
        self.assertEqual(spy.calls[0]['url'], 'http://127.0.0.1:11434/v1/chat/completions')
        self.assertEqual(spy.calls[0]['timeout'], bc().LOCAL_CHAT_TIMEOUT_S)
        self.assertEqual(counter.used_today(), 0)
        self.assertEqual(b.plan('chat'), 'remote', 'a cap of 1 is still free after the warm-up')

    def test_never_sent_to_another_computer(self):
        spy = Recorder()
        self.assertIsNone(brain(own(HOSTED, KEY), spy).warm_up())
        self.assertIsNone(bc().warm_up_own_ai(own(HOSTED, KEY), spy))
        self.assertIsNone(bc().warm_up_own_ai(own('http://localhost.attacker.example/v1'), spy))
        self.assertEqual(spy.calls, [])

    def test_not_sent_offline_with_a_relay_or_with_a_daily_limit_of_zero(self):
        spy = Recorder()
        offline = bc().ConversationBrain(relay_loader=lambda: None, own_key_loader=lambda: None,
                                         transport=spy, lines={})
        self.assertIsNone(offline.warm_up())
        relay = bc().ConversationBrain(relay_loader=lambda: {'base_url': 'http://relay.example', 'token': 't'},
                                       own_key_loader=lambda: own(LOCAL), transport=spy, lines={})
        self.assertIsNone(relay.warm_up())
        self.assertIsNone(brain(own(LOCAL, cap=0), spy).warm_up())
        self.assertIsNone(bc().warm_up_own_ai(None, spy))
        self.assertEqual(spy.calls, [])

    def test_a_failure_is_one_attempt_returned_as_its_kind_and_never_raised(self):
        def timeout(url):
            raise socket.timeout('loading')
        spy = Recorder(timeout)
        self.assertEqual(brain(own('http://127.0.0.1:11434/v1'), spy).warm_up(), 'timeout')
        self.assertEqual(len(spy.calls), 1)

        def broken(request, timeout):
            raise RuntimeError('boom')
        self.assertEqual(brain(own(LOCAL), broken).warm_up(), 'RuntimeError')


class PetStub:
    @staticmethod
    def make(brain_):
        from DyberPet.pet_conversation import ConversationMixin
        from DyberPet.brain_client import BackgroundCalls
        from DyberPet.companion_chat import ChatHistory

        class Stub(ConversationMixin):
            def __init__(self):
                self.events, self.poses, self.logs, self.timers = [], [], [], []
                self._conv_calls = BackgroundCalls()
                self.companion_chat_history = ChatHistory()
                self._conv_brain = brain_

            def _conv_later(self, seconds, fn):
                self.timers.append((seconds, fn))

            def run_timers(self):
                timers, self.timers = self.timers, []
                for _, fn in timers:
                    fn()
                return [seconds for seconds, _ in timers]

            def _emit_companion_bubble(self, text, voice=None, wav=None):
                self.events.append(text)

            def _life_begin_talk(self, pose):
                self.poses.append(('talk', pose))

            def _companion_play_pose(self, pose, **kwargs):
                self.poses.append(pose)

            def _companion_note_mood_event(self, kind, **meta):
                pass

            def _companion_log(self, kind, text):
                self.logs.append((kind, text))
        return Stub()


class PetWarmUpAndThinking(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])

    def test_the_app_start_warms_a_local_model_up_in_the_background(self):
        spy = Recorder(lambda url: completion('OK'))
        counter = bc().DailyCounter(None)
        pet = PetStub.make(None)
        pet._conv_setup(brain=brain(own(LOCAL), spy, counter))
        pump(self.app, lambda: ('warmup', 'ok') in pet.logs)
        self.assertIn(('warmup', 'ok'), pet.logs)
        self.assertEqual(len(spy.calls), 1)
        self.assertEqual(counter.used_today(), 0)

    def test_a_failed_warm_up_is_only_logged(self):
        def refused_everywhere(url):
            refused()
        pet = PetStub.make(None)
        pet._conv_setup(brain=brain(own(LOCAL), Recorder(refused_everywhere)))
        pump(self.app, lambda: any(kind == 'warmup' for kind, _ in pet.logs))
        self.assertIn(('warmup', 'network'), pet.logs)
        self.assertEqual(pet.events, [])

    def test_the_app_start_never_warms_up_a_hosted_endpoint(self):
        spy = Recorder()
        pet = PetStub.make(None)
        pet._conv_setup(brain=brain(own(HOSTED, KEY), spy))
        pump(self.app, lambda: False, seconds=0.2)
        self.assertEqual(spy.calls, [])

    def held_brain(self, url, key=''):
        release = threading.Event()

        def answer(u):
            release.wait(5)
            return completion('[happy] At last.')
        return brain(own(url, key), Recorder(answer)), release

    def test_a_long_wait_on_a_local_server_keeps_her_thinking(self):
        b, release = self.held_brain(LOCAL)
        pet = PetStub.make(b)
        pet._conv_chat('hello')
        self.assertEqual(pet.poses, ['think'])
        self.assertEqual([s for s, _ in pet.timers], [pet.THINKING_AFTER_S])
        self.assertAlmostEqual(pet.THINKING_AFTER_S, 3.0, delta=1.0)
        next_checks = pet.run_timers()               # 3 s later, still waiting
        self.assertEqual(next_checks, [pet.THINKING_AFTER_S])
        self.assertEqual(pet.poses, ['think', 'think'])
        self.assertIn(('line', 'thinking'), pet.logs)
        self.assertTrue(pet.timers, 'she keeps checking while the request waits')
        release.set()
        pump(self.app, lambda: bool(pet.events))
        self.assertEqual(pet.events, ['At last.'])
        pet.run_timers()
        self.assertEqual(pet.timers, [], 'no more checks after the reply')
        self.assertEqual(pet.poses.count('think'), 2)

    def test_she_does_not_restart_the_thinking_clip_she_is_playing(self):
        b, release = self.held_brain(LOCAL)
        pet = PetStub.make(b)

        class Interaction:
            interact, act_name = 'customized', 'think'
        pet.workers = {'Interaction': Interaction()}
        pet._conv_chat('hello')
        pet.run_timers()
        self.assertEqual(pet.poses, ['think'])
        release.set()
        pump(self.app, lambda: bool(pet.events))

    def test_a_hosted_endpoint_has_no_thinking_timer(self):
        b, release = self.held_brain(HOSTED, KEY)
        pet = PetStub.make(b)
        pet._conv_chat('hello')
        self.assertEqual(pet.timers, [])
        release.set()
        pump(self.app, lambda: bool(pet.events))


class SettingsWarmUpAndTest(ProfileCase):
    def test_saving_a_local_server_warms_it_up_in_the_background(self):
        view = self.view()
        view.endpoint.setText(LOCAL)
        view.model.setText('local/model')
        view.save.click()
        self.assertTrue(view.status.text().startswith('Saved.'), view.status.text())
        pump(self.app, lambda: bool(self.warmed))
        self.assertEqual(len(self.warmed), 1)
        self.assertEqual((self.warmed[0]['base_url'], self.warmed[0]['model']), (LOCAL, 'local/model'))
        view.close()

    def test_saving_a_hosted_endpoint_sends_no_warm_up(self):
        view = self.view(store=self.store)
        view.endpoint.setText(HOSTED)
        view.model.setText('vendor/m')
        view.api_key.setText(KEY)
        view.save.click()
        self.assertTrue(view.status.text().startswith('Saved.'), view.status.text())
        pump(self.app, lambda: False, seconds=0.2)
        self.assertEqual(self.warmed, [])
        view.close()

    def test_a_crashing_warm_up_is_only_logged(self):
        def warmer(settings):
            self.warmed.append(settings)
            raise RuntimeError('boom')
        view = self.view(warmer=warmer)
        view.endpoint.setText('http://127.0.0.1:11434/v1')
        view.model.setText('local/model')
        with self.assertLogs(level='INFO'):
            view.save.click()
            pump(self.app, lambda: bool(self.warmed))
            pump(self.app, lambda: False, seconds=0.2)
        self.assertTrue(view.status.text().startswith('Saved.'), view.status.text())
        view.close()

    def test_test_connection_never_blocks_the_window(self):
        gate, seen = threading.Event(), []

        def tester(url, key, model):
            seen.append(threading.current_thread() is threading.main_thread())
            gate.wait(5)
            return True, 'OK'
        view = self.view(tester=tester)
        view.endpoint.setText(LOCAL)
        view.model.setText('local/model')
        started = time.monotonic()
        view.test.click()
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertFalse(view.test.isEnabled(), 'one test at a time')
        self.assertTrue(view.status.text().startswith('Testing'), view.status.text())
        gate.set()
        self.wait_test(view)
        self.assertEqual(view.status.text(), 'Connection OK.')
        self.assertEqual(seen, [False])
        view.close()


# --------------------------------------------------------------------------------------------
# 3. Clean replies from weaker models (real strings from the Windows run, then variants)
# --------------------------------------------------------------------------------------------

REPLIES = [
    # (model reply, emotion, bubble text)
    ("assistant> It's a delicate matter…", 'neutral', "It's a delicate matter…"),
    ('[]bored] Must we do this now?', 'bored', 'Must we do this now?'),
    ('assistant\n\n[happy] There you are.', 'happy', 'There you are.'),
    ('assistant\n[]bored] Again?', 'bored', 'Again?'),
    ('assistant: [shy] Stop that.', 'shy', 'Stop that.'),
    ('Assistant> [proud] Naturally.', 'proud', 'Naturally.'),
    ('  assistant >  [bored] Fine.', 'bored', 'Fine.'),
    ('ASSISTANT:Hello.', 'neutral', 'Hello.'),
    ('Draconia: [sarcastic] How novel.', 'sarcastic', 'How novel.'),
    ('DRACONIA:[angry] No.', 'angry', 'No.'),
    ('[happy] assistant> Fine, then.', 'happy', 'Fine, then.'),
    ('[thinking] Draconia: Let me see.', 'thinking', 'Let me see.'),
    ('[ bored ] Again?', 'bored', 'Again?'),
    ('[[thinking]] Hm.', 'thinking', 'Hm.'),
    ('[bored]] Yes.', 'bored', 'Yes.'),
    ('[]smirks] Hm.', 'neutral', 'Hm.'),
    ('[] Hello.', 'neutral', 'Hello.'),
    ('[ ] Hello.', 'neutral', 'Hello.'),
    ('[Happy] Well.', 'happy', 'Well.'),
    # Real strings from llama3.2:3b on Windows (rc.3 acceptance run).
    ("assistantassistant *)[shy] I'm glad I'm feeling somewhat presentable.", 'shy',
     "I'm glad I'm feeling somewhat presentable."),
    ("assistant)[thinking] I'm not your girlfriend.", 'thinking', "I'm not your girlfriend."),
    ('assistant\n\n[neutral] I remember our last conversation.', 'neutral', 'I remember our last conversation.'),
    # Ordinary text that only looks like a prefix stays as it is.
    ('Assistant managers bore me.', 'neutral', 'Assistant managers bore me.'),
    ('[happy] Draconia is my name.', 'happy', 'Draconia is my name.'),
    ('[proud] I need no assistant.', 'proud', 'I need no assistant.'),
]


class CleanReplies(unittest.TestCase):
    def test_table(self):
        for raw, emotion, text in REPLIES:
            self.assertEqual(bc().parse_reply(raw), (emotion, text), repr(raw))

    def test_no_role_prefix_or_bracket_junk_ever_reaches_the_bubble(self):
        for raw, _, _ in REPLIES:
            _, text = bc().parse_reply(raw)
            self.assertNotRegex(text, r'^(?i:assistant|draconia)\s*[:>]', raw)
            self.assertNotIn('[', text, raw)
            self.assertNotIn(']', text, raw)

    def test_a_reply_that_is_only_a_prefix_falls_back_to_a_stored_line(self):
        reply = brain(own(LOCAL), Recorder(lambda url: completion('assistant> []bored]'))).remote_chat('hi')
        self.assertEqual((reply.source, reply.error), ('offline', 'malformed'))

    def test_through_the_brain_a_weak_models_reply_is_clean(self):
        spy = Recorder(lambda url: completion("assistant> []bored] It's a delicate matter…"))
        reply = brain(own(LOCAL), spy).remote_chat('tell me')
        self.assertEqual((reply.source, reply.emotion, reply.text),
                         ('own_key', 'bored', "It's a delicate matter…"))


if __name__ == '__main__':
    unittest.main()
