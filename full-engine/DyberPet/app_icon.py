"""MiniDraconia's application icon (D2.1).

One place for the icon of the executable, the pet window, the tray and the Settings window.
The current icon is provisional: changing it means replacing `res/icons/app.png` (1024 px RGBA)
and `res/icons/app.ico` (multi-size) only. The PyInstaller spec uses the same `app.ico`.
"""
import os

APP_ICON_ICO = 'res/icons/app.ico'
APP_ICON_PNG = 'res/icons/app.png'


def app_icon_files(basedir) -> list:
    """The icon files that exist under `basedir` (the resource root), .ico first."""
    found = []
    for relative in (APP_ICON_ICO, APP_ICON_PNG):
        path = os.path.join(basedir or '', relative)
        if os.path.isfile(path):
            found.append(path)
    return found


def app_icon(basedir=None):
    """A QIcon with every app icon file found (the .ico sizes and the large PNG). An empty
    QIcon when none exists: Qt then falls back to its default icon; never raises."""
    from PySide6.QtGui import QIcon
    if basedir is None:
        import DyberPet.settings as settings
        basedir = getattr(settings, 'BASEDIR', '') or ''
    icon = QIcon()
    for path in app_icon_files(basedir):
        try:
            icon.addFile(path)
        except Exception:
            pass
    return icon
