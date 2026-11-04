"""S1 scripted Draconia. No inference, credential discovery or network transport.
BYO Anthropic/xAI is a reserved interface, unavailable in this test cut.
"""
import json
import random
import threading
import time
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[2]
SYSTEM_PROMPT = Path(__file__).with_name('alma-draconia-v6-compact-en.md').read_text(encoding='utf-8')
OFFLINE_NOTICE = 'Scripted offline. Connect my AI is not available in this build.'

def trim_bubble(text, limit=140):
    text = ' '.join(text.split())
    return text if len(text) <= limit else text[:limit-1].rsplit(' ', 1)[0] + '…'

def _atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)

def load_config(root=APP_ROOT):
    from DyberPet.paths import user_root
    path = user_root()/'ai.json'
    if path.is_file():
        try:
            selected = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(selected, dict) and selected.get('provider') != 'offline_phrases':
                backup = path.with_suffix('.s1-backup.json')
                if not backup.exists():
                    backup.write_bytes(path.read_bytes())
                selected['provider'] = 'offline_phrases'
                _atomic(path, selected)
        except (ValueError, TypeError):
            pass  # Preserve malformed files verbatim, but never enable a provider.
    return {'provider':'offline_phrases', 'connect_my_ai': {'provider':'', 'model':'', 'base_url':'', 'available':False}}

def save_preferences(provider, base_url='', model='', local_model=None):
    if provider != 'offline_phrases':
        raise ValueError('Connect my AI is not available in this build')
    from DyberPet.paths import user_root
    load_config()
    path = user_root()/'ai.json'
    try:
        selected = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    except (ValueError, TypeError):
        raise ValueError('Preserved malformed preferences; repair separately')
    selected['provider'] = provider
    _atomic(path, selected)

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
