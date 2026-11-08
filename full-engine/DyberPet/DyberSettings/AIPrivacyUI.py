"""AI / Privacy: which conversation mode is active, and "Connect your own AI".

No provider is preset: the base URL and the model start empty (with neutral placeholders) and
the user fills in what their service documents. "Test connection" and "Save" refuse an empty base
URL or model in plain words. A server on this computer (localhost, 127.0.0.1, ::1) needs no key;
any other endpoint needs one, and a key is never sent over plain http:// to another computer.

The API key is typed into a masked field, stored encrypted on this device (DyberPet/key_store.py,
Windows DPAPI) and never shown again, logged or written to settings. "Test connection" sends one
tiny request and shows OK or the HTTP error, never the key; it runs in the background, so a
model that a server on this computer is still loading never freezes the window (D2.5).

D2.5: the example for a server on this computer is http://127.0.0.1:11434/v1 (a `localhost` URL
also works: the client connects to 127.0.0.1). Saving your own AI on this computer warms its
model up with one tiny background request (never counted; a failure is only logged).
"""
import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QApplication, QMessageBox, QSpinBox
from qfluentwidgets import ScrollArea, PushButton, LineEdit, PasswordLineEdit
from DyberPet.brain import load_config, save_preferences
from DyberPet.brain_client import (LOCAL_EXAMPLE_URL, PLACEHOLDER_BASE_URL, PLACEHOLDER_MODEL,
                                   is_local_url, own_key_problem)


def mode_text(mode, base_url=''):
    """The active mode in plain words."""
    from DyberPet.brain_client import endpoint_host
    if mode == 'relay':
        return ('Active mode: self-hosted relay (advanced). Draconia answers your typed messages '
                'through the relay configured for this copy (minidraconia_relay.json). Your typed '
                'messages and recent conversation go to that relay; touches and other desktop events '
                'use her stored lines and send nothing.')
    if mode == 'own_key':
        return ('Active mode: your own AI. Only your typed messages and the recent typed conversation '
                'go to %s with her character prompt, and only they count toward the daily limit. '
                'Touches and other desktop events use her stored lines and send nothing. '
                'Text only.' % (endpoint_host(base_url) or 'your endpoint'))
    return 'Active mode: offline. Draconia answers with her built-in lines. Nothing is sent anywhere.'


def active_mode():
    """The mode the pet uses right now (same rule as DyberPet/brain_client.py)."""
    from DyberPet.brain_client import ConversationBrain
    from DyberPet.brain import load_own_key
    try:
        return ConversationBrain(own_key_loader=load_own_key, lines={}).mode()
    except Exception:
        return 'offline'


class AIPrivacyInterface(ScrollArea):
    def __init__(self, parent=None, store=None, tester=None, warmer=None):
        super().__init__(parent)
        self.setObjectName('AIPrivacyInterface')
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        if store is None:
            from DyberPet.key_store import key_store
            store = key_store()
        self.store = store
        if tester is None:
            from DyberPet.brain_client import test_own_key
            tester = test_own_key
        self._tester = tester
        if warmer is None:
            from DyberPet.brain_client import warm_up_own_ai
            warmer = warm_up_own_ai
        self._warmer = warmer
        from DyberPet.brain_client import BackgroundCalls
        self._calls = BackgroundCalls(self)
        self.body = QWidget()
        self.setWidget(self.body)
        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(12)

        def label(text, buddy=None):
            item = QLabel(text)
            item.setWordWrap(True)
            item.setTextFormat(Qt.PlainText)
            layout.addWidget(item)
            if buddy is not None:
                item.setBuddy(buddy)
            return item

        label('AI / Privacy').setStyleSheet('font-size: 24px; font-weight: 600; color: #14634b;')
        self.mode_label = label('')
        self.mode_label.setAccessibleName('Active conversation mode')

        label('Connect your own AI').setStyleSheet('font-size: 18px; font-weight: 600;')
        label('Optional. Any OpenAI-compatible chat completions endpoint works: a hosted service '
              '(paste the base URL and model name it documents, and your API key) or a server on '
              'this computer such as %s, which needs no key. Nothing is '
              'preset. A chat subscription does not include an API key. A hosted service may charge '
              'your account; the daily limit below stops her from sending more than that many a day.'
              % LOCAL_EXAMPLE_URL)

        self.endpoint = LineEdit()
        self.endpoint.setPlaceholderText(PLACEHOLDER_BASE_URL)
        label('Base URL', self.endpoint)
        layout.addWidget(self.endpoint)

        self.api_key = PasswordLineEdit()
        self.api_key.setPlaceholderText('Paste your API key (not needed for a server on this computer)')
        label('API key (stored encrypted on this device, never shown again)', self.api_key)
        key_row = QHBoxLayout()
        key_row.addWidget(self.api_key, 1)
        self.forget = PushButton('Forget key')
        key_row.addWidget(self.forget)
        layout.addLayout(key_row)
        self.key_state = label('')
        self.key_state.setAccessibleName('Stored key state')

        self.model = LineEdit()
        self.model.setPlaceholderText(PLACEHOLDER_MODEL)
        label('Model', self.model)
        layout.addWidget(self.model)

        self.daily_cap = QSpinBox()
        self.daily_cap.setRange(0, 100000)
        label('Daily request limit (after it she answers from offline lines until tomorrow)', self.daily_cap)
        layout.addWidget(self.daily_cap)

        buttons = QHBoxLayout()
        self.test = PushButton('Test connection')
        self.save = PushButton('Save and use my AI')
        self.use_offline = PushButton('Use offline lines')
        for button in (self.test, self.save, self.use_offline):
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.status = label('')
        self.status.setAccessibleName('AI status')

        self.privacy = label(
            'What is sent and to whom: in offline mode, nothing. With your own AI, only when you '
            'send a typed message: that message and the recent typed conversation (kept in memory '
            'only) go to the base URL above, with her character prompt. Nothing else: no desktop '
            'events, files, screenshots, keystrokes or other conversations. That service may keep '
            'what it receives under its own terms. Touches, greetings, chatter, movement and mood '
            'use her stored lines and stay on this computer.')
        self.clear_history = PushButton('Clear current chat history...')
        self.clear_history.setAccessibleName('Clear current chat history')
        self.clear_history.setFocusPolicy(Qt.StrongFocus)
        layout.addWidget(self.clear_history)
        self.clear_history.clicked.connect(self.clear_chat_history)
        layout.addStretch()
        for control, name in [(self.endpoint, 'Provider base URL'), (self.api_key, 'API key'),
                              (self.forget, 'Forget key'), (self.model, 'Model ID'),
                              (self.daily_cap, 'Daily request limit'), (self.test, 'Test connection'),
                              (self.save, 'Save and use my AI'), (self.use_offline, 'Use offline lines')]:
            control.setAccessibleName(name)
            control.setFocusPolicy(Qt.StrongFocus)

        config = load_config()
        self.endpoint.setText(config['own_key']['base_url'])
        self.model.setText(config['own_key']['model'])
        self.daily_cap.setValue(int(config['own_key']['daily_cap']))
        self.test.clicked.connect(self.test_connection)
        self.save.clicked.connect(self.save_preferences)
        self.use_offline.clicked.connect(self.choose_offline)
        self.forget.clicked.connect(self.forget_key)
        self.update_status()

    # -- state --------------------------------------------------------------------------------
    def update_status(self):
        config = load_config()
        self.mode_label.setText(mode_text(active_mode(), config['own_key']['base_url']))
        if not self.store.available:
            self.key_state.setText('A key cannot be stored on this system (Windows encryption is '
                                   'not available). Only a server on this computer, which needs '
                                   'no key, can be used here.')
        elif self.store.has_key():
            self.key_state.setText('A key is stored (encrypted). Type a new one to replace it.')
        else:
            self.key_state.setText('No key stored.')
        self.forget.setEnabled(self.store.has_key())

    def _typed_key(self):
        """The key typed now, else the stored one (only for a test request, never displayed)."""
        typed = self.api_key.text().strip()
        return typed or (self.store.load() or '')

    # -- actions ------------------------------------------------------------------------------
    def test_connection(self):
        url, key, model = self.endpoint.text().strip(), self._typed_key(), self.model.text().strip()
        problem = own_key_problem(url, key, model)
        if problem is not None:             # nothing is sent
            self.status.setText('Not tested: ' + problem)
            return
        # In the background: a server on this computer may take a minute to load its model.
        self.test.setEnabled(False)
        self.status.setText('Testing... (a model on this computer may need a minute to load)'
                            if is_local_url(url) else 'Testing...')
        tester = self._tester
        self._calls.submit(lambda: tester(url, key, model), self._test_done)

    def _test_done(self, result):
        self.test.setEnabled(True)
        ok, message = result if isinstance(result, tuple) and len(result) == 2 else (False, 'Failed.')
        self.status.setText('Connection OK.' if ok else 'Connection failed: ' + str(message))

    def _warm_up(self):
        """Your own AI on this computer: load its model now, in the background (never counted)."""
        from DyberPet.brain import load_own_key
        settings = load_own_key(self.store)
        if not settings or not is_local_url(settings.get('base_url')):
            return
        warmer, log = self._warmer, logging.getLogger(__name__)

        def run():
            try:
                return warmer(settings)
            except Exception as exc:
                return type(exc).__name__
        self._calls.submit(run, lambda result: log.info('own AI warm-up: %s', result or 'skipped'))

    def save_preferences(self):
        typed = self.api_key.text().strip()
        url, model = self.endpoint.text().strip(), self.model.text().strip()
        has_key = bool(typed) or self.store.has_key()
        problem = own_key_problem(url, 'stored' if has_key else '', model)
        if problem is None and typed and not self.store.available:
            problem = ('This system cannot encrypt the key (Windows DPAPI is not available), so it '
                       'is not stored. Only a server on this computer, which needs no key, can be used here.')
        if problem is not None:             # nothing is stored or changed
            self.status.setText('Not saved: ' + problem)
            return
        try:
            if typed:
                self.store.save(typed)
            save_preferences('own_key', url, model, daily_cap=self.daily_cap.value())
        except (ValueError, OSError, RuntimeError) as exc:
            self.status.setText('Not saved: %s' % (str(exc) if isinstance(exc, ValueError) else type(exc).__name__))
            return
        finally:
            self.api_key.clear()      # never keep the key in the field
        self.status.setText('Saved. Draconia uses your own AI from her next line.')
        self.update_status()
        self._warm_up()

    def choose_offline(self):
        try:
            save_preferences('offline_phrases')
        except (ValueError, OSError) as exc:
            self.status.setText('Not saved: %s' % type(exc).__name__)
            return
        self.status.setText('Saved. Offline lines are used; your key (if any) stays stored until you forget it.')
        self.update_status()

    def forget_key(self):
        self.api_key.clear()
        removed = self.store.forget()
        try:
            save_preferences('offline_phrases')
        except (ValueError, OSError):
            pass
        self.status.setText('Key forgotten. Offline lines are used.' if removed else 'No key was stored.')
        self.update_status()

    def clear_chat_history(self):
        answer = QMessageBox.question(self, 'Clear current chat history?',
            'Clear the conversation held in this running app? This does not delete your key, settings, character state, mood data or other files. An answer already in progress may still arrive.',
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer != QMessageBox.Yes:
            return
        from DyberPet.companion_chat import ChatHistory
        # The pet owns this exact in-memory object. Never glob a profile or
        # delete arbitrary files named history/memory, even if they exist.
        for widget in QApplication.topLevelWidgets():
            history = getattr(widget, 'companion_chat_history', None)
            if isinstance(history, ChatHistory):
                history.clear()
        self.status.setText('Current chat history cleared. No files or keys were deleted.')
