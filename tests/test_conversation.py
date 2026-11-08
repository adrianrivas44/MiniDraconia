"""D2: Draconia talks in three modes (self-hosted relay > own AI > offline).

Behaviour contracts, standard library unittest. No real network: every remote call goes through
a fake transport; the default transport would fail the test (socket is patched where it matters).
"""
import datetime
import io
import json
import os
import random
import socket
import tempfile
import threading
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
ENGINE = REPO / 'full-engine'
RELAY = {'base_url': 'https://relay.invalid', 'token': 'relay-test-token'}
OWN = {'base_url': 'https://llm.invalid/api/v1', 'model': 'test/model', 'daily_cap': 200,
       'api_key': 'sk-test-secret-key-123'}
WAV = b'RIFF\x24\x00\x00\x00WAVEfmt ' + b'\x10\x00\x00\x00\x01\x00\x01\x00\xc0]\x00\x00\x80\xbb\x00\x00\x02\x00\x10\x00' \
      + b'data\x00\x00\x00\x00'


class FakeResponse:
    def __init__(self, body, status=200):
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode('utf-8')
        self.status = status

    def read(self, *args):
        return self._body

    def close(self):
        pass


class FakeTransport:
    """Records every request; answers from a script of responses or exceptions."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = []

    def __call__(self, request, timeout):
        body = json.loads(request.data.decode('utf-8')) if request.data else None
        self.calls.append({'url': request.full_url, 'method': request.get_method(), 'timeout': timeout,
                           'auth': request.get_header('Authorization'), 'body': body})
        item = self.script.pop(0) if self.script else FakeResponse({'emotion': 'neutral', 'text': 'Noted.'})
        if isinstance(item, BaseException):
            raise item
        return item


def http_error(code):
    return urllib.error.HTTPError('https://x.invalid/', code, 'error', {}, io.BytesIO(b'{}'))


def completion(text):
    return FakeResponse({'choices': [{'message': {'role': 'assistant', 'content': text}}]})


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


class XorCodec:
    """Test stand-in for DPAPI (reversible, never returns the plain key)."""

    def protect(self, data):
        return bytes(b ^ 0x5A for b in data)[::-1]

    def unprotect(self, data):
        return bytes(b ^ 0x5A for b in data[::-1])


def mod():
    from DyberPet import brain_client
    return brain_client


def make_brain(transport=None, relay=None, own=None, clock=None, counter=None, **kwargs):
    bc = mod()
    return bc.ConversationBrain(relay_loader=lambda: dict(relay) if relay else None,
                                own_key_loader=lambda: dict(own) if own else None,
                                transport=transport, clock=clock or Clock(), rng=random.Random(7),
                                counter=counter, prompt_loader=lambda: 'SOUL+DESKTOP', sleep=lambda s: None,
                                **kwargs)


class ModePriority(unittest.TestCase):
    def test_relay_beats_own_key_beats_offline(self):
        self.assertEqual(make_brain(relay=RELAY, own=OWN).mode(), 'relay')
        self.assertEqual(make_brain(own=OWN).mode(), 'own_key')
        self.assertEqual(make_brain().mode(), 'offline')

    def test_incomplete_own_key_settings_are_offline(self):
        for broken in (dict(OWN, api_key=''), dict(OWN, model=''), dict(OWN, base_url='ftp://x'),
                       dict(OWN, base_url='not a url')):
            self.assertEqual(make_brain(own=broken).mode(), 'offline', broken)

    def test_offline_never_attempts_the_network(self):
        transport = FakeTransport()
        brain = make_brain(transport)
        with patch.object(socket, 'socket', side_effect=AssertionError('network forbidden')):
            for key in mod().EVENT_KEYS + ('chat',):
                self.assertEqual(brain.plan(key), 'offline')
                reply = brain.offline_or_cap_reply(key)
                self.assertEqual(reply.source, 'offline')
                self.assertTrue(reply.text)
            self.assertEqual(brain.remote_chat('hi').source, 'offline')
        self.assertEqual(transport.calls, [])


class OfflineLines(unittest.TestCase):
    def test_the_bundled_lines_cover_every_event_key_and_chat(self):
        data = json.loads((ENGINE / 'data' / 'draconia_lines_en.json').read_text(encoding='utf-8'))
        for key in mod().EVENT_KEYS + ('chat',):
            self.assertGreaterEqual(len(data.get(key, [])), 3, key)

    def test_no_line_repeats_any_of_the_last_three_of_its_key(self):
        brain = make_brain()
        for key in ('greet', 'pat', 'chatter', 'chat', 'bye'):
            recent = []
            for _ in range(40):
                text = brain.offline_reply(key).text
                self.assertNotIn(text, recent, key)
                recent = (recent + [text])[-3:]

    def test_offline_lines_are_unvoiced_and_chat_talks(self):
        reply = make_brain().offline_reply('chat')
        self.assertEqual((reply.source, reply.pose), ('offline', 'talk'))
        self.assertIsNone(make_brain().offline_reply('pat').pose)

    def test_missing_or_broken_pool_still_answers(self):
        bc = mod()
        with tempfile.TemporaryDirectory() as folder:
            broken = Path(folder) / 'lines.json'
            broken.write_text('{not json', encoding='utf-8')
            lines = bc.load_offline_lines(broken)
        brain = bc.ConversationBrain(relay_loader=lambda: None, own_key_loader=lambda: None, lines=lines)
        for key in bc.EVENT_KEYS + ('chat',):
            self.assertTrue(brain.offline_reply(key).text)

    def test_pose_lines_catalog_keeps_working(self):
        from DyberPet.brain import Brain
        brain = Brain(config={'provider': 'offline_phrases'}, environ={}, rng=random.Random(1))
        for key in ('greet', 'bye', 'tea', 'spell', 'patpat'):
            self.assertTrue(brain.event(key, now=100.0 + len(key)), key)
        self.assertIn(brain.reply('hello'), brain.lines)


class ReplyParsing(unittest.TestCase):
    def test_leading_emotion_tag_and_voice_cues_never_reach_the_bubble(self):
        parse = mod().parse_reply
        self.assertEqual(parse('[flustered] I was not <soft>blushing</soft>. [sigh] Obviously.'),
                         ('flustered', 'I was not blushing. Obviously.'))
        self.assertEqual(parse('[proud]Naturally.'), ('proud', 'Naturally.'))
        self.assertEqual(parse('No tag at all [pause] here'), ('neutral', 'No tag at all here'))
        self.assertEqual(parse('[unknowntag] Fine.'), ('neutral', 'Fine.'))
        self.assertEqual(parse('<whisper>[chuckle] quiet</whisper>'), ('neutral', 'quiet'))

    def test_emotions_map_to_her_poses(self):
        bc = mod()
        self.assertEqual(bc.emotion_to_pose('flustered'), 'shy')
        self.assertEqual(bc.emotion_to_pose('thinking'), 'think')
        self.assertEqual(bc.emotion_to_pose('whatever'), 'talk')
        role = json.loads((ENGINE / 'res/role/Draconia/act_conf.json').read_text(encoding='utf-8'))
        for pose in set(bc.EMOTION_POSES.values()):
            self.assertIn(pose, role, pose)


class RelayProtocol(unittest.TestCase):
    def test_chat_sends_text_history_and_bearer_and_parses_emotion(self):
        transport = FakeTransport(FakeResponse({'emotion': 'sarcastic', 'text': 'Groundbreaking.'}))
        brain = make_brain(transport, relay=RELAY)
        history = [{'role': 'user', 'content': 'hi'}, {'role': 'assistant', 'content': 'Hello.'}]
        reply = brain.remote_chat('I fixed a typo', history)
        self.assertEqual((reply.source, reply.emotion, reply.pose, reply.text),
                         ('relay', 'sarcastic', 'slowclap', 'Groundbreaking.'))
        call = transport.calls[0]
        self.assertEqual((call['method'], call['url']), ('POST', 'https://relay.invalid/v1/chat'))
        self.assertEqual(call['auth'], 'Bearer relay-test-token')
        self.assertEqual(call['body'], {'text': 'I fixed a typo', 'history': history})
        self.assertEqual(call['timeout'], mod().CHAT_TIMEOUT_S)

    def test_events_are_stored_lines_and_never_a_relay_request(self):
        # D2.1 (supersedes D2's event payload): an event is answered from the stored pool.
        transport = FakeTransport()
        brain = make_brain(transport, relay=RELAY)
        self.assertEqual(brain.plan('pat'), 'offline')
        reply = brain.offline_reply('pat')
        self.assertEqual((reply.source, reply.key), ('offline', 'pat'))
        self.assertEqual(transport.calls, [])

    def test_health_and_tts(self):
        bc = mod()
        transport = FakeTransport(FakeResponse({'ok': True}), FakeResponse(WAV))
        client = bc.RelayClient(RELAY, transport, sleep=lambda s: None)
        self.assertTrue(client.health())
        self.assertEqual(client.tts('Hello.'), WAV)
        self.assertEqual([(c['method'], c['url']) for c in transport.calls],
                         [('GET', 'https://relay.invalid/v1/health'), ('POST', 'https://relay.invalid/v1/tts')])
        self.assertEqual(transport.calls[1]['body'], {'text': 'Hello.'})
        self.assertEqual(transport.calls[1]['timeout'], bc.TTS_TIMEOUT_S)

    def test_a_relay_that_is_down_pauses_events(self):
        clock = Clock()
        brain = make_brain(FakeTransport(http_error(503)), relay=RELAY, clock=clock)
        self.assertFalse(brain.check_relay())
        self.assertEqual(brain.plan('pat'), 'offline')
        self.assertIsNone(make_brain().check_relay())

    def test_relay_voice_writes_the_wav_and_fails_quietly(self):
        bc = mod()
        with tempfile.TemporaryDirectory() as folder:
            path = bc.RelayVoiceEngine(lambda: RELAY, FakeTransport(FakeResponse(WAV))).synth('Hi', out_dir=folder)
            self.assertEqual(Path(path).read_bytes(), WAV)
            self.assertIsNone(bc.RelayVoiceEngine(lambda: RELAY, FakeTransport(http_error(500), http_error(500))).synth('Hi', out_dir=folder))
            self.assertIsNone(bc.RelayVoiceEngine(lambda: None, FakeTransport()).synth('Hi', out_dir=folder))

    def test_relay_voice_is_on_by_default_and_the_toggle_turns_it_off(self):
        bc = mod()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'draconia_brain.json'
            self.assertTrue(bc.relay_voice_enabled(path))
            path.write_text(json.dumps({'relay_voice': False}), encoding='utf-8')
            self.assertFalse(bc.relay_voice_enabled(path))

    def test_token_and_key_never_appear_in_repr_or_errors(self):
        bc = mod()
        client = bc.RelayClient(RELAY, FakeTransport(http_error(401)), sleep=lambda s: None)
        own = bc.OwnKeyClient(OWN['base_url'], OWN['api_key'], OWN['model'], FakeTransport(http_error(401)), sleep=lambda s: None)
        self.assertNotIn('relay-test-token', repr(client))
        self.assertNotIn(OWN['api_key'], repr(own))
        for call in (lambda: client.chat(text='x'), lambda: own.complete([])):
            with self.assertRaises(bc.BrainError) as caught:
                call()
            self.assertNotIn('relay-test-token', str(caught.exception))
            self.assertNotIn(OWN['api_key'], str(caught.exception))


class RelaySeed(unittest.TestCase):
    def test_seed_beside_the_executable_is_copied_once_and_never_overwrites(self):
        bc = mod()
        with tempfile.TemporaryDirectory() as folder:
            install, data = Path(folder) / 'app', Path(folder) / 'profile' / 'data'
            install.mkdir(); data.mkdir(parents=True)
            seed = install / bc.RELAY_CONFIG_NAME
            seed.write_text(json.dumps(RELAY), encoding='utf-8')
            self.assertEqual(bc.seed_relay_config(data, install), seed)
            self.assertEqual(bc.load_relay_config(data / bc.RELAY_CONFIG_NAME), RELAY)
            (data / bc.RELAY_CONFIG_NAME).write_text(json.dumps(dict(RELAY, token='mine')), encoding='utf-8')
            self.assertIsNone(bc.seed_relay_config(data, install))
            self.assertEqual(bc.load_relay_config(data / bc.RELAY_CONFIG_NAME)['token'], 'mine')

    def test_no_seed_or_an_invalid_seed_means_no_relay(self):
        bc = mod()
        with tempfile.TemporaryDirectory() as folder:
            install, data = Path(folder) / 'app', Path(folder) / 'data'
            install.mkdir(); data.mkdir()
            self.assertIsNone(bc.seed_relay_config(data, install))
            (install / bc.RELAY_CONFIG_NAME).write_text(json.dumps({'base_url': 'https://x', 'token': '<token>'}), encoding='utf-8')
            self.assertIsNone(bc.seed_relay_config(data, install))
            self.assertFalse((data / bc.RELAY_CONFIG_NAME).exists())

    def test_seed_validation_like_the_relay_client(self):
        validate = mod().validate_relay_config
        self.assertEqual(validate({'base_url': ' https://r.invalid/ ', 'token': ' t '}), {'base_url': 'https://r.invalid', 'token': 't'})
        for bad in (None, [], {}, {'base_url': 'https://r'}, {'base_url': 'ftp://r', 'token': 't'},
                    {'base_url': 'https://r', 'token': ''}, {'base_url': 'https://r', 'token': 'a b'},
                    {'base_url': '<url>', 'token': 't'}, {'base_url': 'https://r', 'token': 5}):
            self.assertIsNone(validate(bad), bad)

    def test_profile_initialisation_seeds_from_the_install_folder(self):
        from DyberPet import paths
        bc = mod()
        with tempfile.TemporaryDirectory() as folder:
            install = Path(folder)
            (install / bc.RELAY_CONFIG_NAME).write_text(json.dumps(RELAY), encoding='utf-8')
            target = paths.data_dir() / bc.RELAY_CONFIG_NAME
            if target.exists():
                target.unlink()
            try:
                with patch.object(paths, 'install_dir', return_value=install):
                    paths.initialize_user_data()
                self.assertEqual(bc.load_relay_config(target), RELAY)
            finally:
                if target.exists():
                    target.unlink()

    def test_the_repository_ships_no_seed(self):
        name = mod().RELAY_CONFIG_NAME
        found = [p for p in REPO.rglob(name) if '.git' not in p.parts]
        self.assertEqual(found, [])


class OwnKeyRequests(unittest.TestCase):
    def test_request_shape_prompt_turn_rule_and_reasoning_off(self):
        transport = FakeTransport(completion('[happy] Splendid.'))
        brain = make_brain(transport, own=OWN)
        history = [{'role': 'user', 'content': 'hi'}, {'role': 'assistant', 'content': 'Hello.'}]
        reply = brain.remote_chat('How are you?', history)
        self.assertEqual((reply.source, reply.emotion, reply.pose, reply.text), ('own_key', 'happy', 'happy', 'Splendid.'))
        call = transport.calls[0]
        self.assertEqual((call['method'], call['url']), ('POST', 'https://llm.invalid/api/v1/chat/completions'))
        self.assertEqual(call['auth'], 'Bearer ' + OWN['api_key'])
        body = call['body']
        self.assertEqual(body['model'], 'test/model')
        self.assertEqual(body['max_tokens'], 140)
        self.assertEqual(body['reasoning'], {'enabled': False})
        roles = [m['role'] for m in body['messages']]
        self.assertEqual(roles, ['system', 'user', 'assistant', 'user', 'system'])
        self.assertEqual(body['messages'][0]['content'], 'SOUL+DESKTOP')
        self.assertEqual(body['messages'][3]['content'], 'How are you?')
        self.assertEqual(body['messages'][-1]['content'], mod().TURN_RULE)

    def test_only_typed_text_is_sent_as_the_user_message(self):
        transport = FakeTransport(completion('[proud] Of course you did.'))
        make_brain(transport, own=OWN).remote_chat('I made tea')
        messages = transport.calls[0]['body']['messages']
        self.assertEqual(messages[-2], {'role': 'user', 'content': 'I made tea'})
        self.assertFalse(any('[event]' in m['content'] for m in messages))

    def test_system_prompt_is_the_bundled_soul_plus_the_desktop_addendum(self):
        prompt = mod().system_prompt()
        soul = (REPO / 'docs/identity/SOUL.en.md').read_text(encoding='utf-8').strip()
        desktop = (ENGINE / 'data/draconia_desktop_prompt_en.txt').read_text(encoding='utf-8').strip()
        self.assertEqual(prompt, soul + '\n\n' + desktop)

    def test_two_attempts_only_for_transient_failures(self):
        bc = mod()
        for first in (socket.timeout(), urllib.error.URLError(ConnectionRefusedError()), http_error(502)):
            transport = FakeTransport(first, completion('[neutral] Second time lucky.'))
            reply = make_brain(transport, own=OWN).remote_chat('x')
            self.assertEqual((reply.source, len(transport.calls)), ('own_key', 2), first)
        for final in (http_error(401), http_error(429), http_error(400)):
            transport = FakeTransport(final, completion('[neutral] never'))
            reply = make_brain(transport, own=OWN).remote_chat('x')
            self.assertEqual((reply.source, len(transport.calls)), ('offline', 1), final)
        transport = FakeTransport(socket.timeout(), socket.timeout(), completion('never'))
        reply = make_brain(transport, own=OWN).remote_chat('x')
        self.assertEqual((reply.source, reply.error, len(transport.calls)), ('offline', 'timeout', 2))
        self.assertEqual(bc.ATTEMPTS, 2)

    def test_relay_also_tries_twice(self):
        transport = FakeTransport(http_error(503), FakeResponse({'emotion': 'happy', 'text': 'Back.'}))
        self.assertEqual(make_brain(transport, relay=RELAY).remote_chat('x').source, 'relay')
        self.assertEqual(len(transport.calls), 2)

    def test_malformed_answers_fall_back_offline(self):
        for bad in (FakeResponse(b'not json'), FakeResponse({'choices': []}), completion(''), completion('[happy]')):
            reply = make_brain(FakeTransport(bad), own=OWN).remote_chat('x')
            self.assertEqual(reply.source, 'offline')
            self.assertTrue(reply.text)

    def test_failed_chat_falls_back_and_the_next_chat_still_tries(self):
        clock = Clock()
        transport = FakeTransport(http_error(500), http_error(500))
        brain = make_brain(transport, own=OWN, clock=clock)
        self.assertEqual(brain.remote_chat('x').source, 'offline')
        clock.now += 30
        self.assertEqual(brain.plan('pinch'), 'offline')
        self.assertEqual(brain.plan('chat'), 'remote')

    def test_one_event_line_per_20_seconds_greet_and_bye_still_answer(self):
        # The D2 rate limit, unchanged; the line itself is now always a stored one (D2.1).
        clock = Clock()
        transport = FakeTransport()
        brain = make_brain(transport, own=OWN, clock=clock)
        self.assertEqual(brain.plan('pat'), 'offline')
        clock.now += 5
        self.assertEqual(brain.plan('pinch'), 'skip')
        self.assertEqual(brain.plan('bye'), 'offline')
        self.assertEqual(brain.plan('chat'), 'remote')
        clock.now += 20
        self.assertEqual(brain.plan('drag'), 'offline')
        self.assertEqual(transport.calls, [])

    def test_test_connection_reports_ok_or_the_http_error_without_the_key(self):
        bc = mod()
        ok = bc.test_own_key(OWN['base_url'], OWN['api_key'], OWN['model'], FakeTransport(completion('OK')))
        self.assertEqual(ok, (True, 'OK'))
        failed, message = bc.test_own_key(OWN['base_url'], OWN['api_key'], OWN['model'], FakeTransport(http_error(401)))
        self.assertFalse(failed)
        self.assertIn('401', message)
        self.assertIn('llm.invalid', message)
        self.assertNotIn(OWN['api_key'], message)
        transport = FakeTransport(completion('OK'))
        bc.test_own_key(OWN['base_url'], OWN['api_key'], OWN['model'], transport)
        self.assertEqual(len(transport.calls), 1, 'one tiny request')
        self.assertLessEqual(transport.calls[0]['body']['max_tokens'], 8)
        self.assertFalse(bc.test_own_key('', OWN['api_key'], OWN['model'], FakeTransport())[0])
        self.assertFalse(bc.test_own_key(OWN['base_url'], '', OWN['model'], FakeTransport())[0])


class DailyCap(unittest.TestCase):
    def test_counter_resets_each_local_day_and_persists(self):
        bc = mod()
        day = [datetime.date(2026, 11, 7)]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'usage.json'
            counter = bc.DailyCounter(path, today=lambda: day[0])
            self.assertTrue(counter.take(2)); self.assertTrue(counter.take(2))
            self.assertFalse(counter.take(2))
            self.assertEqual(bc.DailyCounter(path, today=lambda: day[0]).used_today(), 2)
            day[0] = datetime.date(2026, 11, 8)
            self.assertTrue(counter.take(2))

    def test_past_the_cap_she_answers_offline_and_says_so_once(self):
        bc = mod()
        counter = bc.DailyCounter(None)
        transport = FakeTransport(completion('[happy] One.'), completion('[happy] Two.'))
        brain = make_brain(transport, own=dict(OWN, daily_cap=2), counter=counter)
        self.assertEqual(brain.remote_chat('a').source, 'own_key')
        self.assertEqual(brain.remote_chat('b').source, 'own_key')
        self.assertEqual(brain.plan('chat'), 'offline')
        first = brain.offline_or_cap_reply('chat')
        second = brain.offline_or_cap_reply('chat')
        self.assertEqual(first.source, 'offline')
        self.assertEqual(first.notice, bc.CAP_NOTICE)
        self.assertIsNone(second.notice, 'the cap is announced once')
        self.assertEqual(len(transport.calls), 2, 'no request past the cap')

    def test_every_attempt_counts_and_a_remote_call_at_the_cap_never_sends(self):
        bc = mod()
        counter = bc.DailyCounter(None)
        transport = FakeTransport(socket.timeout(), completion('[happy] ok'))
        brain = make_brain(transport, own=dict(OWN, daily_cap=1), counter=counter)
        reply = brain.remote_chat('x')
        self.assertEqual((reply.source, reply.error, len(transport.calls)), ('offline', 'cap', 1))
        self.assertEqual(counter.used_today(), 1)


class KeyStoreContract(unittest.TestCase):
    def test_saved_key_is_encrypted_and_round_trips(self):
        from DyberPet.key_store import KeyStore
        with tempfile.TemporaryDirectory() as folder:
            store = KeyStore(Path(folder) / 'own_key.dpapi', codec=XorCodec())
            store.save(OWN['api_key'])
            raw = (Path(folder) / 'own_key.dpapi').read_bytes()
            self.assertNotIn(OWN['api_key'].encode(), raw)
            self.assertEqual(store.load(), OWN['api_key'])
            self.assertNotIn(OWN['api_key'], repr(store))
            self.assertTrue(store.forget())
            self.assertIsNone(store.load())
            self.assertFalse(store.forget())

    def test_without_encryption_no_key_is_ever_written(self):
        from DyberPet.key_store import KeyStore, KeyStoreUnavailable
        with tempfile.TemporaryDirectory() as folder:
            store = KeyStore(Path(folder) / 'own_key.dpapi', codec=None)
            with self.assertRaises(KeyStoreUnavailable):
                store.save(OWN['api_key'])
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_a_codec_that_returns_the_plain_key_is_refused(self):
        from DyberPet.key_store import KeyStore, KeyStoreUnavailable

        class Identity:
            def protect(self, data):
                return data

            def unprotect(self, data):
                return data
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(KeyStoreUnavailable):
                KeyStore(Path(folder) / 'k', codec=Identity()).save(OWN['api_key'])
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_dpapi_codec_uses_current_user_crypt_protect_data_via_ctypes(self):
        source = (ENGINE / 'DyberPet' / 'key_store.py').read_text(encoding='utf-8')
        for needle in ('CryptProtectData', 'CryptUnprotectData', 'ctypes', 'LocalFree', 'CRYPTPROTECT_UI_FORBIDDEN'):
            self.assertIn(needle, source)
        self.assertNotIn('CRYPTPROTECT_LOCAL_MACHINE', source)
        from DyberPet.key_store import default_codec
        if os.name != 'nt':
            self.assertIsNone(default_codec())

    @unittest.skipUnless(os.name == 'nt', 'DPAPI exists only on Windows')
    def test_real_dpapi_round_trip(self):
        from DyberPet.key_store import DpapiCodec
        codec = DpapiCodec()
        blob = codec.protect(b'sk-windows-test')
        self.assertNotIn(b'sk-windows-test', blob)
        self.assertEqual(codec.unprotect(blob), b'sk-windows-test')


class Preferences(unittest.TestCase):
    def setUp(self):
        from DyberPet.paths import user_root
        self.path = user_root() / 'ai.json'
        if self.path.exists():
            self.path.unlink()

    tearDown = setUp

    def test_defaults_and_saving_never_store_the_key(self):
        from DyberPet.brain import load_config, save_preferences, DEFAULT_CONFIG
        self.assertEqual(load_config(), DEFAULT_CONFIG)
        save_preferences('own_key', 'https://example.invalid/v1', 'x/model', daily_cap=5)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        self.assertEqual(data, {'provider': 'own_key', 'own_key': {'base_url': 'https://example.invalid/v1', 'model': 'x/model', 'daily_cap': 5}})
        with self.assertRaises(ValueError):
            save_preferences('own_key', 'not-a-url', 'm')

    def test_own_key_loader_needs_the_mode_and_a_stored_key(self):
        from DyberPet.brain import load_own_key, save_preferences
        from DyberPet.key_store import KeyStore
        with tempfile.TemporaryDirectory() as folder:
            store = KeyStore(Path(folder) / 'k.dpapi', codec=XorCodec())
            save_preferences('own_key', 'https://example.invalid/v1', 'x/model')
            self.assertIsNone(load_own_key(store))
            store.save('sk-abc')
            self.assertEqual(load_own_key(store)['api_key'], 'sk-abc')
            save_preferences('offline_phrases')
            self.assertIsNone(load_own_key(store))

    def test_defaults_match_the_brain_client_and_the_package(self):
        from DyberPet.brain import DEFAULT_CONFIG
        bc = mod()
        self.assertEqual(DEFAULT_CONFIG['own_key'], {'base_url': bc.DEFAULT_BASE_URL, 'model': bc.DEFAULT_MODEL,
                                                     'daily_cap': bc.DEFAULT_DAILY_CAP})
        # REVISED (D2.4): no provider is preset; the base URL and model start empty.
        self.assertEqual((bc.DEFAULT_BASE_URL, bc.DEFAULT_MODEL, bc.DEFAULT_DAILY_CAP), ('', '', 200))


class PetWiring(unittest.TestCase):
    """ConversationMixin on a stub pet: no pet startup, timers, tray or audio."""

    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])

    def stub(self, brain):
        from DyberPet.pet_conversation import ConversationMixin
        from DyberPet.brain_client import BackgroundCalls
        from DyberPet.companion_chat import ChatHistory

        class Stub(ConversationMixin):
            def __init__(self):
                self.events, self.poses, self.logs, self.wavs = [], [], [], []
                self._conv_brain = brain
                self._conv_calls = BackgroundCalls()
                self.companion_chat_history = ChatHistory()

            def _emit_companion_bubble(self, text, voice=None, wav=None):
                self.events.append(('bubble', text, voice))
                self.wavs.append(wav)

            def _life_begin_talk(self, pose):
                self.poses.append(pose)

            def _companion_play_pose(self, pose, **kwargs):
                self.poses.append(pose)

            def _companion_note_mood_event(self, kind, **meta):
                pass

            def _companion_log(self, kind, text):
                self.logs.append((kind, text))
        return Stub()

    def pump(self, stub, count):
        deadline = time.monotonic() + 5
        while len(stub.events) < count and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)

    def test_relay_chat_is_voiced_and_kept_as_history(self):
        stub = self.stub(make_brain(FakeTransport(FakeResponse({'emotion': 'happy', 'text': 'Splendid.'})), relay=RELAY))
        stub._conv_chat('hello')
        self.pump(stub, 1)
        self.assertEqual(stub.events, [('bubble', 'Splendid.', True)])
        self.assertEqual(stub.poses, ['think', 'happy'])
        self.assertEqual(len(stub.companion_chat_history.as_list()), 2)

    def test_own_key_chat_is_text_only(self):
        stub = self.stub(make_brain(FakeTransport(completion('[shy] Stop it.')), own=OWN))
        stub._conv_chat('you are lovely')
        self.pump(stub, 1)
        self.assertEqual(stub.events, [('bubble', 'Stop it.', False)])
        self.assertEqual(stub.poses[-1], 'shy')
        self.assertEqual(len(stub.companion_chat_history.as_list()), 2)

    def test_offline_chat_is_unvoiced_and_not_history(self):
        stub = self.stub(make_brain())
        stub._conv_chat('hello')
        self.assertEqual(len(stub.events), 1)
        self.assertFalse(stub.events[0][2])
        self.assertEqual(stub.companion_chat_history.as_list(), [])
        self.assertEqual(stub._conv_calls.pending(), 0)

    def test_a_failure_always_shows_an_offline_line(self):
        stub = self.stub(make_brain(FakeTransport(http_error(500), http_error(500)), own=OWN))
        stub._conv_chat('hello')
        self.pump(stub, 1)
        self.assertEqual(len(stub.events), 1)
        self.assertTrue(stub.events[0][1])
        self.assertFalse(stub.events[0][2])

    def test_cap_notice_is_shown_once_in_the_bubble(self):
        bc = mod()
        counter = bc.DailyCounter(None)
        counter.take(1)
        stub = self.stub(make_brain(FakeTransport(), own=dict(OWN, daily_cap=1), counter=counter))
        stub._conv_chat('a')
        stub._conv_chat('b')
        self.assertTrue(stub.events[0][1].startswith(bc.CAP_NOTICE))
        self.assertFalse(stub.events[1][1].startswith(bc.CAP_NOTICE))

    def test_a_line_about_her_tea_shows_the_tea_clip(self):
        stub = self.stub(make_brain(FakeTransport(completion('[happy] My tea is getting cold.')), own=OWN))
        stub.pet_conf = type('Conf', (), {'act_dict': {'tea': 1, 'happy': 1}})()
        stub._conv_chat('hi')
        self.pump(stub, 1)
        self.assertEqual(stub.poses[-1], 'tea')

    def test_goodbye_offline_is_shown_once_and_late_remote_bye_is_dropped(self):
        stub = self.stub(make_brain())
        stub._conv_send_bye()
        self.assertFalse(stub._conv_finish_bye())
        self.assertEqual(len(stub.events), 1)
        stub._conv_on_bye_reply(mod().Reply('bye', 'late', 'neutral', None, 'relay'))
        self.assertEqual(len(stub.events), 1)

    def test_long_absence_triggers_the_idle_event(self):
        stub = self.stub(make_brain())
        stub._companion_on_absence_return(60)
        self.assertEqual(stub.events, [])
        stub._companion_on_absence_return(400)
        self.assertEqual(len(stub.events), 1)

    def test_logs_never_hold_the_text_the_key_or_the_token(self):
        stub = self.stub(make_brain(FakeTransport(completion('[happy] secret reply text')), own=OWN))
        stub._conv_chat('my private message')
        self.pump(stub, 1)
        joined = ' '.join(text for _, text in stub.logs)
        for secret in ('my private message', 'secret reply text', OWN['api_key']):
            self.assertNotIn(secret, joined)

    def test_reaction_lines_route_by_mode_and_approved_clips_keep_their_text(self):
        played = []

        class Controller:
            def play(self, path, volume):
                played.append(path)
        stub = self.stub(make_brain())
        stub._draconia_reactions = Controller()
        entry = {'text': 'One pat. Since you asked so nicely.'}
        stub._conv_reaction_line('head', entry, '/x/head-01.wav')
        self.assertEqual(stub.events[-1], ('bubble', entry['text'], False))
        self.assertEqual(played, ['/x/head-01.wav'])
        stub._conv_reaction_line('cheek', {'text': 'manifest'}, None)
        self.assertNotEqual(stub.events[-1][1], 'manifest', 'without an approved clip her stored line answers')
        # Relay mode: her stored line answers (D2.1: no request), never the v1 clip's other voice.
        transport = FakeTransport(FakeResponse({'emotion': 'happy', 'text': 'Relay line.'}))
        brain = make_brain(transport, relay=RELAY)
        relay = self.stub(brain)
        relay._draconia_reactions = Controller()
        relay._conv_reaction_line('head', entry, '/x/head-01.wav')
        self.assertEqual(len(relay.events), 1)
        self.assertIn(relay.events[-1][1], brain._lines['pat'])
        self.assertFalse(relay.events[-1][2])
        self.assertEqual(transport.calls, [])
        self.assertEqual(played, ['/x/head-01.wav'], 'in relay mode the approved v1 clip stays silent, as in D2')

    def test_reactions_controller_speak_hook_gets_audio_only_when_audible(self):
        from DyberPet.draconia_reactions import Reactions
        note = ENGINE / 'res/role/Draconia/note'
        heard = []
        controller = Reactions(note, speak=lambda event, entry, path: heard.append((event, entry['id'], path)))
        controller.react('head', available=('patpat',), now=100.0, volume=0.5, muted=False)
        controller.react('head', available=('patpat',), now=200.0, volume=0.5, muted=True)
        controller.react('head', available=('patpat',), now=300.0, volume=0.0, muted=False)
        self.assertEqual(heard[0][:2], ('head', 'head-01'))
        self.assertTrue(str(heard[0][2]).endswith('head-01.wav'))
        self.assertEqual([h[2] for h in heard[1:]], [None, None])


class SettingsPage(unittest.TestCase):
    def setUp(self):
        from PySide6.QtWidgets import QApplication
        self.app = QApplication.instance() or QApplication([])
        from DyberPet.paths import user_root
        self.ai = user_root() / 'ai.json'
        if self.ai.exists():
            self.ai.unlink()
        self.folder = tempfile.TemporaryDirectory()
        from DyberPet.key_store import KeyStore
        self.store = KeyStore(Path(self.folder.name) / 'own_key.dpapi', codec=XorCodec())

    def tearDown(self):
        if self.ai.exists():
            self.ai.unlink()
        self.folder.cleanup()

    def view(self, tester=None):
        from DyberPet.DyberSettings.AIPrivacyUI import AIPrivacyInterface
        return AIPrivacyInterface(store=self.store, tester=tester or (lambda *a: (True, 'OK')),
                                  warmer=lambda settings: None)

    def wait_for_test(self, view):
        deadline = time.monotonic() + 5
        while not view.test.isEnabled() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.01)
        self.app.processEvents()

    def test_save_stores_the_key_encrypted_clears_the_field_and_shows_the_mode(self):
        from PySide6.QtWidgets import QLineEdit
        from DyberPet.brain import load_config
        view = self.view()
        self.assertEqual(view.api_key.echoMode(), QLineEdit.Password)
        view.api_key.setText(OWN['api_key'])
        view.endpoint.setText(OWN['base_url'])
        view.model.setText('test/model')
        view.daily_cap.setValue(50)
        with patch('DyberPet.DyberSettings.AIPrivacyUI.active_mode', return_value='own_key'):
            view.save.click()
        self.assertEqual(view.api_key.text(), '')
        self.assertEqual(self.store.load(), OWN['api_key'])
        self.assertEqual(load_config()['provider'], 'own_key')
        self.assertEqual(load_config()['own_key']['daily_cap'], 50)
        self.assertNotIn(OWN['api_key'], self.ai.read_text(encoding='utf-8'))
        self.assertIn('your own ai', view.mode_label.text().lower())
        self.assertIn('llm.invalid', view.mode_label.text())
        self.assertTrue(view.forget.isEnabled())
        view.close()

    def test_test_connection_uses_the_typed_key_and_shows_ok_or_the_error_without_the_key(self):
        seen = []

        def tester(url, key, model):
            seen.append((url, key, model))
            return (False, 'HTTP error 401 from llm.invalid.') if len(seen) > 1 else (True, 'OK')
        view = self.view(tester)
        view.endpoint.setText(OWN['base_url'])
        view.model.setText(OWN['model'])
        view.api_key.setText(OWN['api_key'])
        view.test.click()
        self.wait_for_test(view)          # REVISED (D2.5): Test connection runs in the background
        self.assertEqual(view.status.text(), 'Connection OK.')
        view.test.click()
        self.wait_for_test(view)
        self.assertIn('401', view.status.text())
        self.assertNotIn(OWN['api_key'], view.status.text())
        self.assertEqual(seen[0][1], OWN['api_key'])
        view.close()

    def test_forget_key_deletes_it_and_goes_offline(self):
        from DyberPet.brain import load_config, save_preferences
        self.store.save(OWN['api_key'])
        save_preferences('own_key', 'https://llm.invalid/api/v1', 'x/y')
        view = self.view()
        view.forget.click()
        self.assertFalse(self.store.has_key())
        self.assertEqual(load_config()['provider'], 'offline_phrases')
        self.assertIn('offline', view.mode_label.text().lower())
        view.close()

    def test_saving_without_any_key_is_refused(self):
        from DyberPet.brain import load_config
        view = self.view()
        view.endpoint.setText(OWN['base_url'])
        view.model.setText(OWN['model'])
        view.save.click()
        self.assertIn('enter an api key', view.status.text().lower())
        self.assertEqual(load_config()['provider'], 'offline_phrases')
        view.close()

    def test_mode_texts_say_what_is_sent_and_to_whom(self):
        from DyberPet.DyberSettings.AIPrivacyUI import mode_text
        self.assertIn('nothing is sent', mode_text('offline').lower())
        self.assertIn('example.invalid', mode_text('own_key', 'https://example.invalid/v1'))
        self.assertIn('self-hosted relay (advanced)', mode_text('relay').lower())


class BackgroundCallsDoNotBlock(unittest.TestCase):
    def test_slow_call_returns_immediately_and_delivers_on_the_ui_thread(self):
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        calls = mod().BackgroundCalls()
        delivered = []
        started = time.monotonic()
        calls.submit(lambda: (time.sleep(0.3), 'done')[1],
                     lambda result: delivered.append((result, threading.current_thread() is threading.main_thread())))
        calls.submit(lambda: 1 / 0, lambda result: delivered.append((result, True)))
        self.assertLess(time.monotonic() - started, 0.1)
        deadline = time.monotonic() + 5
        while len(delivered) < 2 and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        self.assertIn(('done', True), delivered)
        self.assertIn((None, True), delivered)


if __name__ == '__main__':
    unittest.main()
