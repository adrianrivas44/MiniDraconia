"""Local offline Qt integration checks, NOT cloud E2E or visual approval."""
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
        from DyberPet.brain import Brain, save_preferences, load_config
        from DyberPet.mia_chat import ChatBox
        box = ChatBox()
        sent = []
        box.message_sent.connect(sent.append)
        box.setText('hello')
        QTest.keyClick(box, Qt.Key_Return)
        assert sent == ['hello']
        import DyberPet.brain as brain_module
        brain_module._session = Brain(config={"provider":"offline_phrases"}, environ={})
        brain = Brain(config={'provider':'builtin_local'}, environ={})
        assert brain.reply(sent[0]) in brain.lines
        from DyberPet.DyberPet import PetWidget
        from DyberPet import settings
        settings.petname = 'Draconia'
        # Exercise the real pet methods with a QWidget receiver, no pet timers,
        # tray, audio or startup. This is not a whole-application visual gate.
        class Receiver(QWidget):
            def __init__(self):
                super().__init__()
                self.bubbles = []
            def _mia_play_pose(self, pose):
                pass
            def _s1_event(self, event):
                PetWidget._s1_event(self,event)
            def _draconia_bubble(self,text):
                self.bubbles.append(text)
        pet = Receiver()
        PetWidget._send_mia_greeting(pet)
        PetWidget._send_mia_bye(pet)
        assert len(pet.bubbles) == 2
        from DyberPet.DyberSettings.AIPrivacyUI import AIPrivacyInterface
        view = AIPrivacyInterface()
        QTest.mouseClick(view.save, Qt.LeftButton)
        assert load_config()['provider'] == 'offline_phrases'
        view.provider.setCurrentIndex(1)
        assert not view.save.isEnabled()
        view.close(); box.close(); pet.close()
        app.processEvents()
    assert not attempts
    return {'qt_chat_sent':len(sent), 'pet_event_bubbles':len(pet.bubbles), 'network_attempts':len(attempts), 'scope':'local Qt methods, not full pet startup or cloud E2E'}


def exercise_product():
    """Actual offscreen PetWidget, Qt mouse events, settings and quit. No chat."""
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
        from DyberPet.paths import user_root
        settings.petname = 'Draconia'
        pet = PetWidget(curr_pet_name='Draconia', screens=app.screens(), audit_mode=True)
        app.processEvents()
        assert isinstance(pet._draconia_reactions.effect, QSoundEffect)
        assert pet._draconia_reactions.effect.isMuted()
        from DyberPet.modules import Animation_worker, Interaction_worker
        from PySide6.QtCore import QThread
        pet.workers = {"Animation": Animation_worker(pet.pet_conf), "Interaction": Interaction_worker(pet.pet_conf)}
        pet.workers["Interaction"].timer.stop()
        pet.workers["Interaction"].sig_setimg_inter.connect(pet.set_img)
        pet.workers["Interaction"].sig_move_inter.connect(pet._move_customized)
        pet.threads = {key: QThread() for key in pet.workers}
        bubbles = []
        pet._draconia_reactions.bubble = bubbles.append
        plays = []
        original_play = pet._draconia_reactions.play
        def record_play(*args):
            plays.append(args)
            raise AssertionError('worker audio must stay muted')
        pet._draconia_reactions.play = record_play
        menu = [a.text() for a in pet.StatMenu.actions() if not a.isSeparator()]
        assert menu == ['Settings', 'Quit'], menu
        panel = ControlMainWindow()
        pet.show_controlPanel.connect(panel.show_window)
        next(a for a in pet.StatMenu.actions() if a.text() == 'Settings').trigger()
        app.processEvents()
        assert panel.isVisible()
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
        # Global cooldown crosses event types, then one drag emission per gesture.
        before=len(bubbles)
        pet._draconia_react('fall')
        assert len(bubbles)==before
        controller=pet._draconia_reactions
        original_busy=controller.is_playing
        controller.last_time=float('-inf'); controller.is_playing=lambda: True
        controller.react('fall')
        assert len(bubbles)==before, 'overlapping audio reaction'
        controller.is_playing=original_busy
        previous=None
        for n in range(8):
            controller.react('body', available=pet._mia_available_poses(), now=100+n*10, muted=True)
            assert bubbles[-1]!=previous, 'immediate phrase repetition'
            previous=bubbles[-1]
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
        pet._open_mia_chat()
        assert pet.mia_chat_box is None
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
        return dict(touch_zones=zones,menu=menu,drag_bubbles=drag_bubbles,
                    audio_play_calls=len(plays),network_attempts=len(attempts),
                    persisted_volume=persisted['volume'],quit_code=code,
                    scope='real offscreen pet audit-mode; human animation/audio/laptop pending')
