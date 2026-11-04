"""Offscreen audit of the production pet widget; no animation or voice startup."""
import json
import os


def audit(root, profile):
    if os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
        raise RuntimeError('UI audit requires offscreen Qt')
    import DyberPet._msvc_preload
    from PySide6.QtWidgets import QApplication
    from DyberPet.DyberPet import PetWidget
    app = QApplication.instance() or QApplication(['MiniDraconia', '-platform', 'offscreen'])
    pet = PetWidget(screens=app.screens(), audit_mode=True)
    image = pet.label.grab().toImage()
    pixels = sum(image.pixelColor(x, y).alpha() > 0
                 for y in range(image.height()) for x in range(image.width()))
    menu = [action.text() for action in pet.StatMenu.actions() if not action.isSeparator()]
    chat_action = next(action for action in pet.StatMenu.actions() if action.text() == 'Chat')
    chat_action.trigger()
    app.processEvents()
    chat_event = {'widget_class': type(pet.mia_chat_box).__name__,
                  'visible_offscreen': pet.mia_chat_box.isVisible() and app.platformName() == 'offscreen'}
    assert chat_event['visible_offscreen'], chat_event
    report = {'menu': menu, 'pet_class': type(pet).__name__, 'sprite_pixels': pixels,
              'chat_event': chat_event,
              'image_width': image.width(), 'image_height': image.height(),
              'platform': app.platformName()}
    (profile / 'ui-audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    assert menu == ['Chat', 'Settings', 'Quit'], report
    assert pixels > 0, report
    pet.close()
    print(json.dumps(report))
    return 0
