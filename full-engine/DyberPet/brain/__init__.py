"""Draconia's scripted lines and the AI preferences of the Settings page.

`Brain` is the scripted pose-line catalog (data/draconia_lines.json, plus the offline chat lines);
it never contacts anything. Where conversation lines come from (self-hosted relay, own AI,
offline) is decided in DyberPet/brain_client.py; this module keeps the preference file
`ai.json` in the user's profile: the chosen mode and the own-AI endpoint/model/daily cap.
No endpoint or model is preset: both start empty until the user fills them in, and values a
user already saved are kept. The API key itself is never in this file (DyberPet/key_store.py
keeps it encrypted).
"""
import json
import random
import threading
import time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
SYSTEM_PROMPT = Path(__file__).with_name('alma-draconia-v6-compact-en.md').read_text(encoding='utf-8')
OFFLINE_NOTICE = 'Offline: built-in lines. Connect your own AI in Settings > AI / Privacy.'
PROVIDERS = ('offline_phrases', 'own_key')
# Effective defaults (config/brain.json documents them; tests keep the two equal).
# No provider is preset: the base URL and the model are empty until the user fills them in.
DEFAULT_CONFIG = {'provider': 'offline_phrases',
                  'own_key': {'base_url': '', 'model': '', 'daily_cap': 200}}

def trim_bubble(text, limit=140):
    text = ' '.join(text.split())
    return text if len(text) <= limit else text[:limit-1].rsplit(' ', 1)[0] + '…'

def _atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)

def _own_key_settings(selected):
    defaults = DEFAULT_CONFIG['own_key']
    DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_DAILY_CAP = defaults['base_url'], defaults['model'], defaults['daily_cap']
    own = selected.get('own_key') if isinstance(selected, dict) else None
    own = own if isinstance(own, dict) else {}
    base_url = own.get('base_url') if isinstance(own.get('base_url'), str) and own.get('base_url').strip() else DEFAULT_BASE_URL
    model = own.get('model') if isinstance(own.get('model'), str) and own.get('model').strip() else DEFAULT_MODEL
    try:
        cap = int(own.get('daily_cap', DEFAULT_DAILY_CAP))
    except (TypeError, ValueError):
        cap = DEFAULT_DAILY_CAP
    return {'base_url': base_url.strip(), 'model': model.strip(), 'daily_cap': max(0, cap)}

def load_config(root=APP_ROOT):
    """{'provider', 'own_key': {base_url, model, daily_cap}} (DEFAULT_CONFIG for a new profile).
    An unknown provider of an older build is backed up once and replaced by offline."""
    from DyberPet.paths import user_root
    path = user_root()/'ai.json'
    selected = {}
    if path.is_file():
        try:
            selected = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(selected, dict) and selected.get('provider') not in PROVIDERS:
                backup = path.with_suffix('.s1-backup.json')
                if not backup.exists():
                    backup.write_bytes(path.read_bytes())
                selected['provider'] = 'offline_phrases'
                _atomic(path, selected)
        except (ValueError, TypeError):
            selected = {}  # Preserve malformed files verbatim, but never enable a provider.
    if not isinstance(selected, dict):
        selected = {}
    provider = selected.get('provider') if selected.get('provider') in PROVIDERS else 'offline_phrases'
    return {'provider': provider, 'own_key': _own_key_settings(selected)}

def save_preferences(provider, base_url='', model='', local_model=None, daily_cap=None):
    """Write the chosen mode (and the own-AI endpoint, model and daily cap). Never the key.
    Choosing 'own_key' needs a base URL and a model (given now or saved before)."""
    if provider not in PROVIDERS:
        raise ValueError('That AI provider is not available in this build')
    from DyberPet.paths import user_root
    from DyberPet.brain_client import valid_base_url
    load_config()
    path = user_root()/'ai.json'
    try:
        selected = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    except (ValueError, TypeError):
        raise ValueError('Preserved malformed preferences; repair separately')
    if not isinstance(selected, dict):
        raise ValueError('Preserved malformed preferences; repair separately')
    selected['provider'] = provider
    if provider == 'own_key' or base_url or model or daily_cap is not None:
        own = _own_key_settings(selected)
        if base_url:
            if not valid_base_url(base_url):
                raise ValueError('The base URL must start with https:// or http://')
            own['base_url'] = str(base_url).strip()
        if model:
            own['model'] = str(model).strip()
        if daily_cap is not None:
            own['daily_cap'] = max(0, int(daily_cap))
        if provider == 'own_key' and not own['base_url']:
            raise ValueError('Enter the base URL of your AI endpoint first.')
        if provider == 'own_key' and not own['model']:
            raise ValueError('Enter a model name first.')
        selected['own_key'] = own
    _atomic(path, selected)

def load_own_key(store=None):
    """The own-AI settings with the decrypted key ('' for a server on this computer that
    needs none), when that mode is chosen and the settings are usable (base URL, model, and a
    key unless the endpoint is local); else None. Used by DyberPet/brain_client.py."""
    from DyberPet.brain_client import own_key_problem
    config = load_config()
    if config['provider'] != 'own_key':
        return None
    if store is None:
        from DyberPet.key_store import key_store
        store = key_store()
    own = dict(config['own_key'], api_key=store.load() or '')
    if own_key_problem(own['base_url'], own['api_key'], own['model']) is not None:
        return None
    return own

class Brain:
    def __init__(self, config=None, root=APP_ROOT, user_env=None, transport=None, environ=None, local_server=None, rng=None, state_path=None):
        self.root = Path(root)
        self.config = dict(config or load_config(self.root), provider='offline_phrases')
        self.rng = rng if rng is not None else random.Random()
        self.catalog = json.loads((self.root/'data/draconia_lines.json').read_text(encoding='utf-8'))
        self.lines = json.loads((self.root/'data/draconia_lines_en.json').read_text(encoding='utf-8'))['chat']
        self.catalog['chat'] = self.lines
        self.recent, self.last_time = {}, {}
        self.warning = ''
        self.last_metrics = {}
        self._lock = threading.RLock()
        if state_path and Path(state_path).is_file():
            try:
                value = json.loads(Path(state_path).read_text(encoding='utf-8'))
                self.recent = {k:v for k,v in value.get('recent',{}).items() if isinstance(v,str)}
            except (ValueError, TypeError, AttributeError):
                pass

    def event(self, event, now=None):
        key = {'touch':'patpat', 'head':'patpat', 'cheek':'pinch', 'body':'touch_body', 'drag':'onfloor', 'idle':'think'}.get(event,event)
        now = time.monotonic() if now is None else now
        with self._lock:
            if now - self.last_time.get(key,float('-inf')) < 3 and key != 'chat':
                return ''
            pool = self.catalog.get(key, self.lines)
            choices = [line for line in pool if line != self.recent.get(key)] or pool
            line = self.rng.choice(choices)
            self.recent[key], self.last_time[key] = line, now
            return line

    def save_state(self, path):
        _atomic(path, {'recent':self.recent})  # No chat history or user text.

    def reply(self, text, history=()):
        return self.event('chat')

    def close(self):
        pass

_session = None
_session_lock = threading.RLock()

def session():
    global _session
    with _session_lock:
        if _session is None:
            from DyberPet.paths import user_root
            _session = Brain(state_path=user_root()/'scripted-state.json')
        return _session

def scripted_event(event):
    from DyberPet.paths import user_root
    brain = session()
    line = brain.event(event)
    if line:
        brain.save_state(user_root()/'scripted-state.json')
    return line

def explicit_chat(text, history=()):
    return session().reply(text, history)
