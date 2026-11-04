"""Explicit AI preferences; secrets and chat content never belong in this view."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QComboBox, QApplication, QMessageBox
from qfluentwidgets import ScrollArea, PushButton, LineEdit
from DyberPet.brain import APP_ROOT, load_config, save_preferences



class AIPrivacyInterface(ScrollArea):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('AIPrivacyInterface')
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.body = QWidget()
        self.setWidget(self.body)
        layout = QVBoxLayout(self.body)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(14)

        def label(text):
            item = QLabel(text)
            item.setWordWrap(True)
            item.setTextFormat(Qt.PlainText)
            layout.addWidget(item)
            return item

        label('AI / Privacy').setStyleSheet('font-size: 24px; font-weight: 600; color: #14634b;')
        label('AI is used only for explicit chat. Touch, movement and recorded reactions stay local.')
        self.provider = QComboBox()
        for title, value in [('Scripted offline', 'offline_phrases'),
                             ('Connect my AI', 'connect_my_ai')]:
            self.provider.addItem(title, value)
        label('AI provider').setBuddy(self.provider)
        layout.addWidget(self.provider)
        self.endpoint = LineEdit()
        label('Future provider endpoint (unavailable)').setBuddy(self.endpoint)
        layout.addWidget(self.endpoint)
        self.model = LineEdit()
        label('Model ID').setBuddy(self.model)
        layout.addWidget(self.model)
        self.save = PushButton('Save AI preferences')
        layout.addWidget(self.save)
        self.status = label('')
        self.status.setAccessibleName('AI status')
        self.privacy = label('Scripted offline sends nothing. Chat history stays in memory. Character state and preferences stay in your isolated user profile. Connect my AI is NOT AVAILABLE in this build. Planned providers: Claude / Anthropic and xAI, with separate API protocols and your own API credentials outside the application/ZIP. Chat subscriptions do not grant API access. Before any future connection, explicit consent must cover chat text, recent history and the character prompt; the provider may retain them. No key is requested or read by this build.')
        self.clear_history = PushButton('Clear current chat history...')
        self.clear_history.setAccessibleName('Clear current chat history')
        self.clear_history.setFocusPolicy(Qt.StrongFocus)
        layout.addWidget(self.clear_history)
        self.clear_history.clicked.connect(self.clear_chat_history)
        layout.addStretch()
        for control, name in [(self.provider, 'AI provider'), (self.endpoint, 'Provider base URL'),
                              (self.model, 'Model ID'), (self.save, 'Save AI preferences')]:
            control.setAccessibleName(name)
            control.setFocusPolicy(Qt.StrongFocus)
        config = load_config()
        self.provider.setCurrentIndex(self.provider.findData(config['provider']))
        self.endpoint.setText(config['connect_my_ai']['base_url'])
        self.model.setText(config['connect_my_ai']['model'])
        self.save.clicked.connect(self.save_preferences)
        self.provider.currentIndexChanged.connect(self.update_status)
        self.update_status()

    def clear_chat_history(self):
        answer = QMessageBox.question(self, 'Clear current chat history?',
            'Clear the conversation held in this running app? This does not delete credentials, settings, character state, mood data or other files. An answer already in progress may still arrive.',
            QMessageBox.Yes | QMessageBox.Cancel, QMessageBox.Cancel)
        if answer != QMessageBox.Yes:
            return
        from DyberPet.mia_chat import ChatHistory
        # The pet owns this exact in-memory object. Never glob a profile or
        # delete arbitrary files named history/memory, even if they exist.
        for widget in QApplication.topLevelWidgets():
            history = getattr(widget, 'mia_chat_history', None)
            if isinstance(history, ChatHistory):
                history.clear()
        self.status.setText('Current chat history cleared. No files or credentials were deleted.')

    def update_status(self):
        remote = self.provider.currentData() == 'connect_my_ai'
        self.endpoint.setEnabled(False)
        self.model.setEnabled(False)
        self.save.setEnabled(not remote)
        self.status.setText('Connect my AI is not available in this build. Claude / Anthropic and xAI are planned, not connected.' if remote else 'Scripted offline: no connections, credentials or local models. Select Save to apply.')

    def save_preferences(self):
        try:
            save_preferences(self.provider.currentData())
            self.status.setText('Saved. Scripted offline is active.')
        except (ValueError, OSError):
            self.status.setText('Not saved. Connect my AI is not available, or the isolated profile is not writable.')
