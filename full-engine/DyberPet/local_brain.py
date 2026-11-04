"""S1 compatibility adapter: no local model, ping, HTTP, threads or inference."""
import json
from pathlib import Path
from PySide6.QtCore import QObject, Signal
from DyberPet.brain import SYSTEM_PROMPT

def load_config():
    return {'enabled':False, 'language':'en', 'system':SYSTEM_PROMPT, 'system_en':SYSTEM_PROMPT}

def save_default_config():
    from DyberPet.paths import data_dir
    return data_dir()/'draconia_brain.json'

def system_prompt_for_language(cfg, language):
    return SYSTEM_PROMPT

def ping(base_url, timeout_s=2.0):
    return False

def chat(prompt, cfg=None):
    return None

def chat_with_messages(messages, cfg=None, is_first_call=False):
    return None

class LocalBrain(QObject):
    reply = Signal(str)
    unavailable = Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.cfg = load_config()
        self._busy = False
        self._thread = None
    def refresh(self):
        self.cfg = load_config()
    @property
    def enabled(self):
        return False
    def ready(self):
        return False
    def ask(self, prompt, system_override=None):
        return False
