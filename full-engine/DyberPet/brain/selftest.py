"""Local offline Qt integration checks, NOT cloud E2E or visual approval.

Offline is the public default: every line comes from the bundled offline lines, and no network
attempt may happen. (Self-hosted relay and own-AI modes are covered by unit tests with fake
transports; they never run here.)
"""


def _offline_brain():
    from DyberPet.brain_client import ConversationBrain
    return ConversationBrain(relay_loader=lambda: None, own_key_loader=lambda: None)


def exercise():
    import socket
    from unittest.mock import patch
    from PySide6.QtWidgets import QApplication, QWidget
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    app = QApplication.instance() or QApplication([])
    attempts = []
    def denied(*a, **k):
        attempts.append(True)
        raise AssertionError('network forbidden')
    with patch.object(socket, 'socket', denied):
        from DyberPet.brain import Brain, load_config
        from DyberPet.mia_chat import ChatBox, ChatHistory
        box = ChatBox()
        sent = []
        box.message_sent.connect(sent.append)
        box.setText('hello')
        QTest.keyClick(box, Qt.Key_Return)
        assert sent == ['hello']
        # The scripted pose-line catalog keeps working offline.
        brain = Brain(config={'provider':'builtin_local'}, environ={})
        assert brain.reply(sent[0]) in brain.lines
        from DyberPet.DyberPet import PetWidget
        from DyberPet.pet_conversation import ConversationMixin
        from DyberPet import settings
        settings.petname = 'Draconia'
        # Exercise the real pet methods with a QWidget receiver, no pet timers,
        # tray, audio or startup. This is not a whole-application visual gate.
        class Receiver(QWidget, ConversationMixin):
            def __init__(self):
                super().__init__()
                self.bubbles = []
                self.mia_chat_history = ChatHistory()
            def _mia_play_pose(self, pose, **kwargs):
                pass
            def _life_begin_talk(self, pose):
                pass
            def _mia_log(self, kind, text):
                pass
            def _mia_note_mood_event(self, kind, **meta):
                pass
            def _emit_mia_bubble(self, text, voice=None, wav=None):
                assert not voice, 'an offline line is never voiced by the relay'
                self.bubbles.append(text)
        pet = Receiver()
        pet._conv_setup(brain=_offline_brain())
        PetWidget._send_mia_greeting(pet)
        pet._conv_chat(sent[0])
        PetWidget._send_mia_bye(pet)
        assert len(pet.bubbles) == 3, pet.bubbles
        assert pet._conv_calls.pending() == 0, 'offline never starts a background call'
        from DyberPet.DyberSettings.AIPrivacyUI import AIPrivacyInterface
        view = AIPrivacyInterface()
        assert 'offline' in view.mode_label.text().lower()
        QTest.mouseClick(view.use_offline, Qt.LeftButton)
        assert load_config()['provider'] == 'offline_phrases'
        view.close(); box.close(); pet.close()
        app.processEvents()
    assert not attempts
    return {'qt_chat_sent':len(sent), 'pet_event_bubbles':len(pet.bubbles), 'network_attempts':len(attempts), 'scope':'local Qt methods, not full pet startup or cloud E2E'}


def exercise_product():
    """Actual offscreen PetWidget, Qt mouse events, typed chat, settings and quit (offline)."""
    import json, socket, time
    from pathlib import Path
    from unittest.mock import patch
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import Qt, QPoint, QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtTest import QTest
    from PySide6.QtMultimedia import QSoundEffect
    app = QApplication.instance() or QApplication([])
    attempts = []
    def denied(*args, **kwargs):
        attempts.append(True)
        raise AssertionError('network forbidden')
    with patch.object(socket, 'socket', denied):
        from DyberPet.DyberPet import PetWidget
        from DyberPet import settings
        from DyberPet.DyberSettings.DyberControlPanel import ControlMainWindow
        settings.petname = 'Draconia'
        pet = PetWidget(curr_pet_name='Draconia', screens=app.screens(), audit_mode=True)
        app.processEvents()
        assert pet._conv_mode() == 'offline', pet._conv_mode()
        assert isinstance(pet._draconia_reactions.effect, QSoundEffect)
        assert pet._draconia_reactions.effect.isMuted()
        # Frames are decoded per clip on demand, not all at start.
        assert len(pet.frame_store.decoded_groups()) <= 2, pet.frame_store.decoded_groups()
        from DyberPet.modules import Animation_worker, Interaction_worker
        from PySide6.QtCore import QThread
        pet.workers = {"Animation": Animation_worker(pet.pet_conf), "Interaction": Interaction_worker(pet.pet_conf)}
        pet.workers["Interaction"].timer.stop()
        pet.workers["Interaction"].sig_setimg_inter.connect(pet.set_img)
        pet.workers["Interaction"].sig_move_inter.connect(pet._move_customized)
        pet.threads = {key: QThread() for key in pet.workers}
        bubbles = []
        original_show = pet._mia_show_bubble
        def record_bubble(bubble_dict):
            bubbles.append(bubble_dict.get('message', ''))
            original_show(bubble_dict)
        pet._mia_show_bubble = record_bubble
        plays = []
        def record_play(*args):
            plays.append(args)
            raise AssertionError('worker audio must stay muted')
        pet._draconia_reactions.play = record_play
        menu = [a.text() for a in pet.StatMenu.actions() if not a.isSeparator()]
        assert menu == ['Settings', 'Talk to Draconia', 'Climb walls', 'Quit'], menu
        panel = ControlMainWindow()
        pet.show_controlPanel.connect(panel.show_window)
        next(a for a in pet.StatMenu.actions() if a.text() == 'Settings').trigger()
        app.processEvents()
        assert panel.isVisible()
        assert 'offline' in panel.aiPrivacyInterface.mode_label.text().lower()
        view = panel.settingInterface
        view.VolumnCard.slider.setValue(4)
        assert settings.volume == 0.4
        QTest.mouseClick(view.MuteCard.switchButton, Qt.LeftButton)
        assert settings.volume == 0
        QTest.mouseClick(view.MuteCard.switchButton, Qt.LeftButton)
        assert settings.volume == 0.4
        settings_path = Path(settings.CONFIGDIR)/'data/settings.json'
        persisted = json.loads(settings_path.read_text(encoding='utf-8'))
        assert persisted['volume'] == 0.4, persisted
        settings.onfloor = 1; settings.draging = 0
        zones = []
        from DyberPet.mia_director import detect_touch_zone
        for zone in ['head', 'cheek', 'body']:
            candidates = [QPoint(x,y) for y in range(0,pet.label.height(),max(1,pet.label.height()//20)) for x in range(0,pet.label.width(),max(1,pet.label.width()//20)) if detect_touch_zone(pet.label.width(),pet.label.height(),x,y)==zone]
            assert candidates, zone
            point = pet.label.mapTo(pet, candidates[len(candidates)//2])
            pet._draconia_reactions.last_time = float('-inf')
            before = len(bubbles)
            pet.workers["Interaction"].stop_interact()
            QTest.mouseClick(pet, Qt.LeftButton, pos=point)
            assert len(bubbles) == before+1, (zone,bubbles)
            zones.append(zone)
        # Global cooldown crosses event types, then one drag line per gesture.
        before=len(bubbles)
        pet._draconia_react('fall')
        assert len(bubbles)==before
        controller=pet._draconia_reactions
        original_busy=controller.is_playing
        controller.last_time=float('-inf'); controller.is_playing=lambda: True
        controller.react('fall')
        assert len(bubbles)==before, 'overlapping audio reaction'
        controller.is_playing=original_busy
        recent=[]
        for n in range(8):
            controller.react('body', available=pet._mia_available_poses(), now=100+n*10, muted=True)
            assert bubbles[-1] not in recent, 'offline line repeated one of the last three'
            recent=(recent+[bubbles[-1]])[-3:]
        before=len(bubbles)
        pet._draconia_reactions.last_time=float('-inf')
        pet._draconia_reactions.begin_gesture()
        pet.is_follow_mouse=True; pet.mouse_drag_pos=QPoint(0,0)
        for n in range(4):
            if n: pet._draconia_reactions.last_time=float('-inf')
            e=QMouseEvent(QEvent.MouseMove,QPointF(10+n,10),QPointF(100+n,100),Qt.NoButton,Qt.LeftButton,Qt.NoModifier)
            QApplication.sendEvent(pet,e)
        drag_bubbles=len(bubbles)-before
        assert drag_bubbles==1, drag_bubbles
        assert pet.pet_conf.fall is pet.pet_conf.act_dict['climb']
        # Typed chat opens and is answered from the offline lines (no network).
        pet.is_follow_mouse=False; settings.draging=0; settings.onfloor=1
        pet._open_mia_chat()
        assert pet.mia_chat_box is not None and pet.mia_chat_box.isVisible()
        before=len(bubbles)
        pet.mia_chat_box.setText('hello')
        QTest.keyClick(pet.mia_chat_box, Qt.Key_Return)
        app.processEvents()
        chat_bubbles=len(bubbles)-before
        assert chat_bubbles==1, chat_bubbles
        assert pet.talk_controller.active, 'she visibly talks while the line is on screen'
        assert pet._conv_calls.pending()==0
        # Real quit, including save/shutdown, caught only at process exit boundary.
        code=None
        try:
            pet.quit()
        except SystemExit as exc:
            code=exc.code or 0
        assert code==0
        panel.hide(); pet.close(); app.processEvents()
        assert not plays
        assert not attempts
        return dict(touch_zones=zones,menu=menu,drag_bubbles=drag_bubbles,chat_bubbles=chat_bubbles,
                    audio_play_calls=len(plays),network_attempts=len(attempts),
                    persisted_volume=persisted['volume'],quit_code=code,
                    scope='real offscreen pet audit-mode; human animation/audio/laptop pending')
