"""Where Draconia's lines come from: a self-hosted relay, your own AI, or stored lines.

Owner rule (D2.1): the lines she already has are stored and repeated; only lines an AI has to
write spend quota. So **only typed chat ever goes to a brain**. Every pet event (greet, pat,
pinch, touch_body, drag, fall, idle, chatter, bye) answers from her stored pool in
`data/draconia_lines_en.json`, in every mode, and never sends a request.

Three modes for typed chat, in this priority (`ConversationBrain.mode()`):

1. **Self-hosted relay (advanced)** - only when `minidraconia_relay.json` ({"base_url",
   "token"}) is in the user's data folder. Whoever runs a relay can put it beside the executable
   and the first run copies it into the profile (`seed_relay_config`); the public ZIP never
   contains one. Protocol (docs/SELF-HOSTED-RELAY.md): `GET /v1/health`,
   `POST /v1/chat {text, history}` -> `{emotion, text}`, `POST /v1/tts {text}` -> WAV.
   Typed-chat replies are voiced.
2. **Own AI** - the user chose "Connect your own AI" in Settings and filled in the base URL and
   model of any OpenAI-compatible endpoint (nothing is preset), plus an API key unless the
   endpoint is a server on this computer (localhost, 127.0.0.1, ::1). A key is never sent over
   plain http:// to another computer. Typed messages and the recent typed conversation go to
   that endpoint with her character prompt. Text only. A local daily request cap protects the
   user's money (docs/CONNECT-YOUR-AI.md).
3. **Offline** (default) - typed chat is answered by the stored `chat` lines. No network
   attempt at all.

Stored lines may have a recorded voice from an optional voice pack (`DyberPet/voice_pack.py`):
`offline_reply` attaches the line's WAV and its manifest emotion when the pack has them.

Contract:
  - `ConversationBrain` never raises. Every failure of typed chat (unconfigured, 401, 429, 5xx,
    timeout, network, malformed answer, cap reached) yields a stored `chat` line.
  - `plan(key)` decides at once, without network I/O: typed chat -> 'remote' or 'offline';
    an event -> 'offline' (its stored line) or 'skip' (event rate limit, unchanged since D2:
    with a relay or own key configured, one event line per 20 s and greet/bye always answer;
    offline, or own key past its cap, every event answers). The caller runs `remote_chat` on
    a background thread (`BackgroundCalls`).
  - A stored line repeats none of the last min(3, n-1) lines of its key.
  - Each remote request has a timeout and at most two attempts; only a timeout, a network
    error or a 5xx answer is tried again.
  - The relay token and the API key are never logged, printed or put in an error text.
Standard library only.
"""
from __future__ import annotations

import datetime
import json
import random
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

try:
    from PySide6.QtCore import QObject, Signal
except Exception:  # pragma: no cover - the product always has Qt
    QObject = object  # type: ignore
    Signal = None  # type: ignore


MODE_RELAY, MODE_OWN_KEY, MODE_OFFLINE = 'relay', 'own_key', 'offline'

RELAY_CONFIG_NAME = 'minidraconia_relay.json'
CHAT_TIMEOUT_S = 20
TTS_TIMEOUT_S = 30
HEALTH_TIMEOUT_S = 5
ATTEMPTS = 2                    # a timeout, network error or 5xx is tried once more
RETRY_DELAY_S = 0.5
EVENT_INTERVAL_S = 20.0         # one event line per 20 s when a relay or own key is set
IDLE_EVENT_AFTER_S = 300.0      # "they ignored you for a long time"
MAX_HISTORY = 16                # messages of typed conversation sent back
MAX_TEXT = 500
MAX_CHAT_BYTES = 64 * 1024
MAX_WAV_BYTES = 16 * 1024 * 1024
LINE_LIMIT = 300
OFFLINE_NO_REPEAT = 3           # a stored line is none of the last min(3, n-1) of its key

# No provider is preset: the user fills in the endpoint and model their service documents.
DEFAULT_BASE_URL = ''
DEFAULT_MODEL = ''
# Neutral examples shown greyed out in empty Settings fields (never used as values).
PLACEHOLDER_BASE_URL = 'https://your-endpoint.example/v1'
PLACEHOLDER_MODEL = 'provider/model-name'
# A server on this computer (e.g. a local OpenAI-compatible server) may be used without a key.
LOCAL_HOSTS = ('localhost', '127.0.0.1', '::1')
DEFAULT_DAILY_CAP = 200
OWN_KEY_MAX_TOKENS = 140
# The per-turn rule sent after the conversation (the character prompt says the rest).
TURN_RULE = ('Reply now as Draconia, in English: one emotion tag, then 1 or 2 short sentences '
             'under 25 words. No emojis, lists, markdown or narrated actions.')

EMOTIONS = ('neutral', 'happy', 'angry', 'bored', 'flustered', 'shy', 'thinking',
            'proud', 'sarcastic', 'greet', 'bye')
EMOTION_POSES = {
    'flustered': 'shy', 'shy': 'shy', 'happy': 'happy', 'angry': 'angry', 'bored': 'bored',
    'thinking': 'think', 'proud': 'hairflip', 'sarcastic': 'slowclap', 'greet': 'greet',
    'bye': 'bye', 'neutral': 'talk',
}

EVENT_KEYS = ('greet', 'pat', 'pinch', 'touch_body', 'drag', 'fall', 'idle', 'chatter', 'bye')
ALWAYS_ANSWER = ('greet', 'bye')
_RETRY_KINDS = ('timeout', 'network', 'upstream')

CAP_NOTICE = ('I have used today\'s request limit for your AI, so I will answer from my own '
              'notes until tomorrow.')

_BUILTIN_LINES = {
    'greet': ['There you are.'],
    'pat': ['One pat. I counted.'],
    'pinch': ['Those cheeks are not a public amenity.'],
    'touch_body': ['Personal space. Look it up.'],
    'drag': ['I can walk, you know.'],
    'fall': ['Intentional. Entirely intentional.'],
    'idle': ['Still here. Still impeccable.'],
    'chatter': ['Tea would be civilised right now.'],
    'chat': ['That deserves a proper reply. I cannot give one offline.'],
    'bye': ['Until later.'],
}


def emotion_to_pose(emotion) -> str:
    return EMOTION_POSES.get(emotion, 'talk')


# ---------------------------------------------------------------------------
# Replies: emotion tag and voice cues
# ---------------------------------------------------------------------------

_TAG = re.compile(r'^\s*\[\s*([A-Za-z]+)\s*\]\s*')
_INLINE_CUE = re.compile(r'\[\s*[A-Za-z][A-Za-z _-]{0,20}\]')
_WRAP_CUE = re.compile(r'</?\s*(soft|emphasis|whisper)\s*>', re.IGNORECASE)


def parse_reply(text) -> tuple:
    """(emotion, bubble text) of a model reply: the leading emotion tag is taken off (unknown or
    missing -> 'neutral'), and voice cues ([sigh], <soft>...</soft>) never reach the bubble."""
    text = str(text or '')
    emotion = 'neutral'
    match = _TAG.match(text)
    if match:
        word = match.group(1).lower()
        if word in EMOTIONS:
            emotion = word
        text = text[match.end():]
    text = _WRAP_CUE.sub('', text)
    text = _INLINE_CUE.sub('', text)
    text = ' '.join(text.split())
    text = re.sub(r'\s+([,.;:!?])', r'\1', text)
    return emotion, text[:LINE_LIMIT].strip()


@dataclass
class Reply:
    key: str
    text: str
    emotion: str
    pose: Optional[str]
    source: str              # 'relay' | 'own_key' | 'offline' (a stored line)
    error: Optional[str] = None
    notice: Optional[str] = None   # said once with this line (e.g. the daily cap was reached)
    wav: Optional[str] = None      # a stored line's recorded voice from the voice pack, if any


# ---------------------------------------------------------------------------
# Configuration: relay seed (self-hosted relay) and own-AI preferences
# ---------------------------------------------------------------------------

def relay_config_path() -> Path:
    from DyberPet.paths import data_dir
    return data_dir() / RELAY_CONFIG_NAME


def validate_relay_config(data) -> Optional[dict]:
    """{'base_url', 'token'} when `data` is a usable relay seed, else None (missing keys,
    placeholders such as <token>, whitespace, or a URL that is not http(s))."""
    if not isinstance(data, dict):
        return None
    base_url, token = data.get('base_url'), data.get('token')
    if not isinstance(base_url, str) or not isinstance(token, str):
        return None
    base_url, token = base_url.strip().rstrip('/'), token.strip()
    if not base_url.startswith(('http://', 'https://')) or not token:
        return None
    if any(c in base_url + token for c in '<>') or any(c.isspace() for c in base_url + token):
        return None
    return {'base_url': base_url, 'token': token}


def load_relay_config(path=None) -> Optional[dict]:
    try:
        path = Path(path) if path is not None else relay_config_path()
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, RuntimeError):
        return None
    return validate_relay_config(data)


def seed_relay_config(target_dir, install_dir) -> Optional[Path]:
    """First run with a self-hosted relay: copy `minidraconia_relay.json` from beside the executable
    into the profile's data folder. Only that file, only when it is a valid seed, never over an
    existing copy. Returns the source copied, or None."""
    destination = Path(target_dir) / RELAY_CONFIG_NAME
    source = Path(install_dir) / RELAY_CONFIG_NAME
    try:
        if destination.exists() or not source.is_file():
            return None
        data = source.read_bytes()
        if validate_relay_config(json.loads(data.decode('utf-8'))) is None:
            return None
    except (OSError, ValueError):
        return None
    try:
        with open(destination, 'xb') as dst:    # 'x': never overwrite
            dst.write(data)
        return source
    except FileExistsError:
        return None
    except OSError:
        try:
            destination.unlink()
        except OSError:
            pass
        return None


def valid_base_url(url) -> bool:
    try:
        parsed = urllib.parse.urlsplit(str(url or '').strip())
    except ValueError:
        return False
    return parsed.scheme in ('http', 'https') and bool(parsed.netloc) and not any(
        c.isspace() for c in str(url).strip())


def is_local_url(url) -> bool:
    """True when the URL's host is this computer (localhost, 127.0.0.1 or ::1)."""
    try:
        host = urllib.parse.urlsplit(str(url or '').strip()).hostname or ''
    except ValueError:
        return False
    return host.lower() in LOCAL_HOSTS


def own_key_problem(base_url, api_key, model) -> Optional[str]:
    """Why these own-AI settings cannot be used, in plain words; None when they can.

    The base URL and the model are required (nothing is preset). A key is required, except for
    a server on this computer. A key is never sent over plain http:// to another computer."""
    base_url = str(base_url or '').strip()
    if not base_url:
        return 'Enter the base URL of your AI endpoint first.'
    if not valid_base_url(base_url):
        return 'The base URL must start with https:// (or http:// for a server on this computer).'
    if not str(model or '').strip():
        return 'Enter a model name first.'
    if is_local_url(base_url):
        return None
    if urllib.parse.urlsplit(base_url).scheme != 'https':
        return ('Refused: an API key is never sent over plain http:// to another computer. '
                'Use the https:// address, or a server on this computer (localhost).')
    if not str(api_key or '').strip():
        return ('Enter an API key first. Only a server on this computer (localhost, 127.0.0.1 '
                'or ::1) can be used without one.')
    return None


def endpoint_host(url) -> str:
    """The host the own-key mode talks to, for plain-language messages."""
    try:
        return urllib.parse.urlsplit(str(url or '')).hostname or ''
    except ValueError:
        return ''


def soul_prompt_paths():
    """Where the bundled character soul lives: the frozen build's resource root, then the
    repository's docs/identity (source runs)."""
    from DyberPet.paths import resource_root
    root = resource_root()
    return [root / 'docs' / 'identity' / 'SOUL.en.md', root.parent / 'docs' / 'identity' / 'SOUL.en.md']


def system_prompt() -> str:
    """docs/identity/SOUL.en.md + data/draconia_desktop_prompt_en.txt (own-key mode)."""
    from DyberPet.paths import resource_root
    soul = ''
    for path in soul_prompt_paths():
        try:
            soul = path.read_text(encoding='utf-8').strip()
            break
        except OSError:
            continue
    try:
        desktop = (resource_root() / 'data' / 'draconia_desktop_prompt_en.txt').read_text(encoding='utf-8').strip()
    except OSError:
        desktop = ''
    return '\n\n'.join(part for part in (soul, desktop) if part)


def load_offline_lines(path) -> dict:
    """Offline line pools; a missing or broken key falls back to one built-in line."""
    lines = {k: list(v) for k, v in _BUILTIN_LINES.items()}
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return lines
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, list):
                clean = [v.strip() for v in value if isinstance(v, str) and v.strip()]
                if clean:
                    lines[key] = clean
    return lines


def relay_voice_enabled(brain_path) -> bool:
    """Relay lines are voiced by default; the menu's "Voice" toggle writes relay_voice=false."""
    try:
        value = json.loads(Path(brain_path).read_text(encoding='utf-8'))['relay_voice']
    except (OSError, ValueError, TypeError, KeyError):
        return True
    return value if isinstance(value, bool) else True


# ---------------------------------------------------------------------------
# Daily request cap (own key)
# ---------------------------------------------------------------------------

class DailyCounter:
    """Requests sent to the user's own endpoint today (local date), kept in the profile."""

    def __init__(self, path, today: Callable[[], datetime.date] = datetime.date.today):
        self._path = Path(path) if path is not None else None
        self._today = today
        self._lock = threading.Lock()
        self._memory = {'date': '', 'count': 0}

    def _read(self) -> dict:
        if self._path is None:
            return dict(self._memory)
        try:
            data = json.loads(self._path.read_text(encoding='utf-8'))
            if isinstance(data, dict) and isinstance(data.get('count'), int):
                return {'date': str(data.get('date', '')), 'count': data['count']}
        except (OSError, ValueError):
            pass
        return {'date': '', 'count': 0}

    def _write(self, data: dict) -> None:
        if self._path is None:
            self._memory = dict(data)
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temp = self._path.with_suffix('.tmp')
            temp.write_text(json.dumps(data), encoding='utf-8')
            temp.replace(self._path)
        except OSError:
            pass

    def used_today(self) -> int:
        with self._lock:
            data = self._read()
            return data['count'] if data['date'] == self._today().isoformat() else 0

    def take(self, cap: int) -> bool:
        """Count one request if today's count is below `cap`; False when the cap is reached."""
        with self._lock:
            today = self._today().isoformat()
            data = self._read()
            count = data['count'] if data['date'] == today else 0
            if count >= max(0, int(cap)):
                return False
            self._write({'date': today, 'count': count + 1})
            return True


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

class BrainError(Exception):
    """kind: auth | rate_limited | upstream | http | timeout | network | malformed | cap | insecure"""

    def __init__(self, kind: str, detail: str = ''):
        super().__init__(('%s %s' % (kind, detail)).strip())
        self.kind = kind
        self.detail = detail


def default_transport(request, timeout):
    # Direct connection: no proxy discovery, no cookies, nothing but this request.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(request, timeout=timeout)


def _is_timeout(exc) -> bool:
    return isinstance(exc, (socket.timeout, TimeoutError))


def _status_error(code: int) -> BrainError:
    if code in (401, 403):
        return BrainError('auth', str(code))
    if code == 429:
        return BrainError('rate_limited', str(code))
    if code >= 500:
        return BrainError('upstream', str(code))
    return BrainError('http', str(code))


def _send(transport, request, timeout: float, limit: int) -> bytes:
    """One HTTP exchange. Errors carry only a kind and a status/exception name."""
    try:
        response = transport(request, timeout)
        try:
            status = int(getattr(response, 'status', 200) or 200)
            body = response.read(limit + 1)
        finally:
            close = getattr(response, 'close', None)
            if close:
                close()
    except urllib.error.HTTPError as exc:
        exc.close()
        raise _status_error(exc.code) from None
    except urllib.error.URLError as exc:
        raise BrainError('timeout' if _is_timeout(exc.reason) else 'network', type(exc.reason).__name__) from None
    except (socket.timeout, TimeoutError):
        raise BrainError('timeout') from None
    except (OSError, ValueError) as exc:
        raise BrainError('network', type(exc).__name__) from None
    if not 200 <= status < 300:
        raise _status_error(status)
    if len(body) > limit:
        raise BrainError('malformed', 'response too large')
    return body


def with_attempts(call: Callable[[], bytes], attempts: int = ATTEMPTS,
                  sleep: Callable[[float], None] = time.sleep, before: Optional[Callable[[], None]] = None):
    """Run `call` up to `attempts` times; only timeouts, network errors and 5xx are retried.
    `before()` runs ahead of every attempt (the daily cap counts each request sent)."""
    last = None
    for attempt in range(max(1, attempts)):
        if attempt:
            sleep(RETRY_DELAY_S)
        if before is not None:
            before()
        try:
            return call()
        except BrainError as exc:
            last = exc
            if exc.kind not in _RETRY_KINDS:
                raise
    raise last


def _clean_history(history) -> list:
    out = []
    for item in list(history or ())[-MAX_HISTORY:]:
        if isinstance(item, dict) and item.get('role') in ('user', 'assistant'):
            out.append({'role': item['role'], 'content': str(item.get('content', ''))[:MAX_TEXT]})
    return out


class RelayClient:
    def __init__(self, config: dict, transport=None, sleep=time.sleep):
        self.base_url = config['base_url']
        self._token = config['token']
        self._transport = transport or default_transport
        self._sleep = sleep

    def __repr__(self):  # never print the token
        return 'RelayClient(%r)' % self.base_url

    def _request(self, path: str, payload=None) -> urllib.request.Request:
        headers = {'Authorization': 'Bearer ' + self._token}
        if payload is None:
            return urllib.request.Request(self.base_url + path, method='GET', headers=headers)
        headers['Content-Type'] = 'application/json'
        return urllib.request.Request(self.base_url + path, data=json.dumps(payload).encode('utf-8'),
                                      method='POST', headers=headers)

    def health(self) -> bool:
        try:
            _send(self._transport, self._request('/v1/health'), HEALTH_TIMEOUT_S, 4096)
            return True
        except BrainError:
            return False

    def chat(self, text: str, history=()) -> dict:
        """Typed chat only: pet events never reach the relay (D2.1)."""
        payload = {'text': str(text or '')[:MAX_TEXT], 'history': _clean_history(history)}
        body = with_attempts(lambda: _send(self._transport, self._request('/v1/chat', payload),
                                           CHAT_TIMEOUT_S, MAX_CHAT_BYTES), sleep=self._sleep)
        try:
            data = json.loads(body.decode('utf-8'))
        except (UnicodeDecodeError, ValueError):
            raise BrainError('malformed', 'not json') from None
        if not isinstance(data, dict) or not isinstance(data.get('text'), str) or not data['text'].strip():
            raise BrainError('malformed', 'no text')
        emotion = data.get('emotion')
        _, text = parse_reply(data['text'])
        if not text:
            raise BrainError('malformed', 'no text')
        return {'emotion': emotion if emotion in EMOTIONS else 'neutral', 'text': text}

    def tts(self, text: str) -> bytes:
        body = with_attempts(lambda: _send(self._transport, self._request('/v1/tts', {'text': str(text)[:MAX_TEXT]}),
                                           TTS_TIMEOUT_S, MAX_WAV_BYTES), sleep=self._sleep)
        if len(body) < 44 or body[:4] != b'RIFF' or body[8:12] != b'WAVE':
            raise BrainError('malformed', 'not a wav')
        return body


class OwnKeyClient:
    """OpenAI-compatible `POST <base_url>/chat/completions` with the user's own API key."""

    def __init__(self, base_url: str, api_key: str, model: str, transport=None, sleep=time.sleep):
        self.base_url = str(base_url).strip().rstrip('/')
        self._key = str(api_key).strip()
        self.model = str(model).strip()
        self._transport = transport or default_transport
        self._sleep = sleep

    def __repr__(self):  # never print the key
        return 'OwnKeyClient(%r, %r)' % (self.base_url, self.model)

    def _request(self, payload: dict) -> urllib.request.Request:
        if self._key and not is_local_url(self.base_url) and \
                urllib.parse.urlsplit(self.base_url).scheme != 'https':
            raise BrainError('insecure', 'key over plain http')   # never sent, never retried
        headers = {'Content-Type': 'application/json'}
        if self._key:                       # a local server may need no key
            headers['Authorization'] = 'Bearer ' + self._key
        return urllib.request.Request(
            self.base_url + '/chat/completions', data=json.dumps(payload).encode('utf-8'), method='POST',
            headers=headers)

    def payload(self, messages: list, max_tokens: int = OWN_KEY_MAX_TOKENS) -> dict:
        return {'model': self.model, 'messages': messages, 'max_tokens': int(max_tokens),
                'reasoning': {'enabled': False}}

    def complete(self, messages: list, max_tokens: int = OWN_KEY_MAX_TOKENS,
                 before: Optional[Callable[[], None]] = None) -> str:
        request = self._request(self.payload(messages, max_tokens))
        body = with_attempts(lambda: _send(self._transport, request, CHAT_TIMEOUT_S, MAX_CHAT_BYTES),
                             sleep=self._sleep, before=before)
        try:
            data = json.loads(body.decode('utf-8'))
            content = data['choices'][0]['message']['content']
        except (UnicodeDecodeError, ValueError, KeyError, IndexError, TypeError):
            raise BrainError('malformed', 'no message') from None
        if isinstance(content, list):     # some endpoints return content parts
            content = ''.join(part.get('text', '') for part in content if isinstance(part, dict))
        if not isinstance(content, str) or not content.strip():
            raise BrainError('malformed', 'empty message')
        return content

    def test(self) -> None:
        """One tiny request; raises BrainError (kind and HTTP status only) when it fails."""
        self.complete([{'role': 'user', 'content': 'Reply with the single word OK.'}], max_tokens=5)


def own_key_messages(prompt: str, history=(), text: str = '') -> list:
    """Typed chat only: pet events never reach the user's endpoint (D2.1)."""
    messages = [{'role': 'system', 'content': prompt}] if prompt else []
    messages += _clean_history(history)
    messages.append({'role': 'user', 'content': str(text or '')[:MAX_TEXT]})
    messages.append({'role': 'system', 'content': TURN_RULE})
    return messages


# ---------------------------------------------------------------------------
# The brain: mode choice, offline fallback, event rate limit, daily cap
# ---------------------------------------------------------------------------

class ConversationBrain:
    def __init__(self, relay_loader: Optional[Callable[[], Optional[dict]]] = None,
                 own_key_loader: Optional[Callable[[], Optional[dict]]] = None,
                 transport=None, lines: Optional[dict] = None, lines_path=None,
                 clock: Callable[[], float] = time.monotonic, rng: Optional[random.Random] = None,
                 event_interval_s: float = EVENT_INTERVAL_S, counter: Optional[DailyCounter] = None,
                 prompt_loader: Callable[[], str] = system_prompt, sleep=time.sleep,
                 voice_pack=None):
        self._relay_loader = relay_loader or load_relay_config
        self._own_key_loader = own_key_loader or (lambda: None)
        self._transport = transport
        if lines is None:
            from DyberPet.paths import resource_root
            lines = load_offline_lines(lines_path or resource_root() / 'data' / 'draconia_lines_en.json')
        self._lines = lines
        if voice_pack is None:
            from DyberPet.voice_pack import VoicePack
            voice_pack = VoicePack()
        self._voice_pack = voice_pack
        self._clock = clock
        self._rng = rng or random.Random()
        self._interval = event_interval_s
        self._counter = counter if counter is not None else DailyCounter(None)
        self._prompt_loader = prompt_loader
        self._prompt = None
        self._sleep = sleep
        self._lock = threading.Lock()
        self._last_event_line = float('-inf')
        self._recent = {}
        self._cap_notice_day = None

    # -- configuration ---------------------------------------------------------------------
    def _relay(self) -> Optional[dict]:
        try:
            return self._relay_loader()
        except Exception:
            return None

    def _own_key(self) -> Optional[dict]:
        try:
            settings = self._own_key_loader()
        except Exception:
            return None
        if not isinstance(settings, dict) or own_key_problem(
                settings.get('base_url'), settings.get('api_key'), settings.get('model')) is not None:
            return None
        return settings

    def mode(self) -> str:
        if self._relay() is not None:
            return MODE_RELAY
        if self._own_key() is not None:
            return MODE_OWN_KEY
        return MODE_OFFLINE

    def has_voice_pack(self) -> bool:
        try:
            return bool(self._voice_pack.present)
        except Exception:
            return False

    def _cap(self, own: dict) -> int:
        try:
            return max(0, int(own.get('daily_cap', DEFAULT_DAILY_CAP)))
        except (TypeError, ValueError):
            return DEFAULT_DAILY_CAP

    def cap_reached(self) -> bool:
        own = self._own_key()
        return own is not None and self._counter.used_today() >= self._cap(own)

    # -- planning --------------------------------------------------------------------------
    def plan(self, key: str) -> str:
        """Typed chat: 'remote', or 'offline' (offline mode, own key past its cap). An event is
        never remote: 'offline' (its stored line) or 'skip'. The skip rule is D2's, unchanged:
        offline (or own key past its cap) every event answers; with a relay or own key, one
        event line per 20 s (this reserves the slot) and greet/bye always answer. No I/O
        beyond re-reading the configuration."""
        mode = self.mode()
        if mode == MODE_OFFLINE:
            return 'offline'
        if mode == MODE_OWN_KEY and self.cap_reached():
            return 'offline'
        if key == 'chat':
            return 'remote'
        with self._lock:
            now = self._clock()
            if now - self._last_event_line < self._interval:
                return 'offline' if key in ALWAYS_ANSWER else 'skip'
            self._last_event_line = now
            return 'offline'

    def offline_reply(self, key: str, error: Optional[str] = None) -> Reply:
        """A stored line of `key` that repeats none of the last min(3, n-1) lines of that key,
        with its voice-pack emotion and WAV when the pack has them (else unvoiced, as in D2)."""
        pool = self._lines.get(key) or _BUILTIN_LINES.get(key) or _BUILTIN_LINES['chat']
        with self._lock:
            recent = self._recent.setdefault(key, [])
            window = min(OFFLINE_NO_REPEAT, len(pool) - 1)
            blocked = recent[-window:] if window > 0 else []
            choices = [line for line in pool if line not in blocked] or list(pool)
            text = self._rng.choice(choices)
            recent.append(text)
            del recent[:-OFFLINE_NO_REPEAT]
            notice = None
            if error == 'cap':
                today = datetime.date.today().isoformat()
                if self._cap_notice_day != today:
                    self._cap_notice_day = today
                    notice = CAP_NOTICE
        emotion, wav = None, None
        try:
            emotion = self._voice_pack.emotion(key, text)
            wav = self._voice_pack.wav_for(key, text)
        except Exception:
            emotion, wav = None, None
        if emotion is None:
            return Reply(key, text, 'neutral', 'talk' if key == 'chat' else None, 'offline', error, notice, wav)
        emotion = emotion if emotion in EMOTIONS else 'neutral'
        return Reply(key, text, emotion, emotion_to_pose(emotion), 'offline', error, notice, wav)

    def offline_or_cap_reply(self, key: str) -> Reply:
        """The stored line for typed chat planned 'offline' (says once a day that the cap was reached)."""
        return self.offline_reply(key, 'cap' if self.mode() == MODE_OWN_KEY and self.cap_reached() else None)

    # -- typed chat: the only remote request ------------------------------------------------
    def remote_chat(self, text: str, history=()) -> Reply:
        """Typed chat to the self-hosted relay or the user's own endpoint; any failure -> a stored `chat` line."""
        relay = self._relay()
        try:
            if relay is not None:
                data = RelayClient(relay, self._transport, self._sleep).chat(text=text, history=history)
                source = MODE_RELAY
            else:
                own = self._own_key()
                if own is None:
                    return self.offline_reply('chat', 'unconfigured')
                cap = self._cap(own)

                def count():
                    if not self._counter.take(cap):
                        raise BrainError('cap')
                if self._prompt is None:
                    self._prompt = self._prompt_loader()
                client = OwnKeyClient(own['base_url'], own.get('api_key') or '', own['model'],
                                      self._transport, self._sleep)
                emotion, line = parse_reply(client.complete(
                    own_key_messages(self._prompt, history, text=text), before=count))
                if not line:
                    raise BrainError('malformed', 'empty line')
                data = {'emotion': emotion, 'text': line}
                source = MODE_OWN_KEY
        except BrainError as exc:
            return self.offline_reply('chat', exc.kind)
        except Exception as exc:  # never let the connection break the pet
            return self.offline_reply('chat', type(exc).__name__)
        return Reply('chat', data['text'], data['emotion'], emotion_to_pose(data['emotion']), source)

    def check_relay(self) -> Optional[bool]:
        """GET /v1/health of the relay (None when there is no relay); only logged."""
        relay = self._relay()
        if relay is None:
            return None
        return RelayClient(relay, self._transport, self._sleep).health()


def test_own_key(base_url: str, api_key: str, model: str, transport=None) -> tuple:
    """Settings' "Test connection": (True, 'OK') or (False, message without the key)."""
    problem = own_key_problem(base_url, api_key, model)
    if problem is not None:
        return False, problem
    try:
        OwnKeyClient(base_url, api_key, model, transport, sleep=lambda s: None).test()
    except BrainError as exc:
        if exc.detail.isdigit():
            return False, 'HTTP error %s from %s.' % (exc.detail, endpoint_host(base_url))
        names = {'timeout': 'No answer in time', 'network': 'Could not connect',
                 'malformed': 'Unexpected answer'}
        return False, '%s (%s).' % (names.get(exc.kind, 'Failed'), endpoint_host(base_url))
    except Exception as exc:
        return False, 'Failed: %s.' % type(exc).__name__
    return True, 'OK'


# ---------------------------------------------------------------------------
# Relay voice: same contract as mia_voice.KokoroEngine.synth()
# ---------------------------------------------------------------------------

class RelayVoiceEngine:
    def __init__(self, config_loader: Optional[Callable[[], Optional[dict]]] = None, transport=None):
        self._config_loader = config_loader or load_relay_config
        self._transport = transport

    def synth(self, text: str, voice=None, lang=None, speed=None, out_dir=None) -> Optional[str]:
        """WAV from the relay written to `out_dir`; the path, or None on any failure."""
        try:
            config = self._config_loader()
            if config is None or not str(text or '').strip():
                return None
            wav = RelayClient(config, self._transport).tts(text)
            out_dir = Path(out_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / ('voice-%s.wav' % uuid.uuid4().hex)
            path.write_bytes(wav)
            return str(path)
        except Exception:
            return None


# ---------------------------------------------------------------------------
# Background calls: blocking network calls off the UI thread
# ---------------------------------------------------------------------------

class BackgroundCalls(QObject):
    """Runs `fn()` on a daemon thread and delivers `on_done(result)` on the UI thread.

    Daemon threads instead of QThread on purpose: a call can block up to its timeout, and a
    QThread still running when the app quits aborts the process. A crashing `fn` delivers None.
    """

    _finished = Signal(int, object) if Signal is not None else None

    def __init__(self, parent=None):
        super().__init__(parent)
        self._callbacks = {}
        self._next_id = 0
        self._finished.connect(self._deliver)

    def submit(self, fn: Callable[[], object], on_done: Callable[[object], None]) -> None:
        self._next_id += 1
        job = self._next_id
        self._callbacks[job] = on_done
        threading.Thread(target=self._run, args=(job, fn), name='brain-call', daemon=True).start()

    def pending(self) -> int:
        return len(self._callbacks)

    def _run(self, job: int, fn) -> None:
        try:
            result = fn()
        except Exception:
            result = None
        try:
            self._finished.emit(job, result)
        except RuntimeError:  # the receiver was destroyed while quitting
            pass

    def _deliver(self, job: int, result) -> None:
        callback = self._callbacks.pop(job, None)
        if callback is None:
            return
        try:
            callback(result)
        except Exception:
            import logging
            logging.getLogger(__name__).exception('brain callback failed (ignored)')
