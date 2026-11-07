# coding:utf-8
import sys
import os
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QIcon, QDesktopServices
from PySide6.QtWidgets import QApplication
from qfluentwidgets import (NavigationItemPosition, MessageBox, setTheme, Theme, FluentWindow,
                            NavigationAvatarWidget,  SplitFluentWindow, FluentTranslator)
from qfluentwidgets import FluentIcon as FIF

from .BasicSettingUI import SettingInterface
from .AIPrivacyUI import AIPrivacyInterface
from .GameSaveUI import SaveInterface
from .CharCardUI import CharInterface
from .ItemCardUI import ItemInterface
from .PetCardUI import PetInterface
from sys import platform
import DyberPet.settings as settings
basedir = settings.BASEDIR

module_path = os.path.join(basedir, 'DyberPet/DyberSettings/')


class ControlMainWindow(FluentWindow):

    def __init__(self, minWidth=800, minHeight=800):
        super().__init__()

        # create sub interface
        self.settingInterface = SettingInterface(self)
        self.aiPrivacyInterface = AIPrivacyInterface(self)


        self.initNavigation()
        self.setMinimumSize(minWidth, minHeight)
        self.initWindow()

    def initNavigation(self):
        # add sub interface
        self.addSubInterface(self.settingInterface, FIF.SETTING, self.tr('Settings'))
        self.addSubInterface(self.aiPrivacyInterface, FIF.SETTING, 'AI / Privacy')



        self.navigationInterface.setExpandWidth(200)

    def initWindow(self):
        #self.setMinimumSize(minWidth, minHeight)
        #self.resize(1000, 800)
        from DyberPet.app_icon import app_icon
        self.setWindowIcon(app_icon(basedir))         # D2.1: the app icon (Settings window)
        self.setWindowTitle(self.tr('MiniDraconia'))

        desktop = QApplication.primaryScreen().availableGeometry() #QApplication.desktop().availableGeometry()
        w, h = desktop.width(), desktop.height()
        self.move(w//2 - self.width()//2, h//2 - self.height()//2)

    def show_window(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()

    def closeEvent(self, event):
        event.ignore()  # Ignore the close event
        self.hide()

    #def _onCharChange(self, char):
    #    self.hide()


if __name__ == '__main__':
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

    # setTheme(Theme.DARK)

    app = QApplication(sys.argv)

    # install translator
    translator = FluentTranslator()
    app.installTranslator(translator)

    w = ControlMainWindow()
    w.show()
    app.exec_()



















