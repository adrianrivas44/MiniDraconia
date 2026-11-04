# coding:utf-8
import os
import json
import random

from qfluentwidgets import (SettingCardGroup, SwitchSettingCard, HyperlinkCard, InfoBar,
                            ComboBoxSettingCard, ScrollArea, ExpandLayout, InfoBarPosition,
                            PushButton, TransparentToolButton, MessageBox, LineEdit, BodyLabel)

from qfluentwidgets import FluentIcon as FIF
from PySide6.QtCore import Qt, Signal, QUrl, QStandardPaths, QLocale, QSize
from PySide6.QtGui import QDesktopServices, QIcon, QImage
from PySide6.QtWidgets import QWidget, QLabel, QApplication, QSpacerItem, QSizePolicy, QHBoxLayout

from .dashboard_widgets import NoteFlowGroup, StatusCard

import DyberPet.settings as settings
import os
from sys import platform
basedir = settings.BASEDIR
module_path = os.path.join(basedir, 'DyberPet/Dashboard/')
'''
if platform == 'win32':
    basedir = ''
    module_path = 'DyberPet/Dashboard/'
else:
    #from pathlib import Path
    basedir = os.path.dirname(__file__) #Path(os.path.dirname(__file__))
    #basedir = basedir.parent
    basedir = basedir.replace('\\','/')
    basedir = '/'.join(basedir.split('/')[:-2])

    module_path = os.path.join(basedir, 'DyberPet/Dashboard/')
'''


class statusInterface(ScrollArea):
    """ Character status and logs interface """
    changePet = Signal(name='changePet')
    addBuff2Thread = Signal(dict, name='addBuff2Thread')
    changeStatus = Signal(str, int, str, name='changeStatus')
    addCoins = Signal(int, bool,name='addCoins')
    rmBuffInThread = Signal(str, name='rmBuffInThread')

    def __init__(self, sizeHintdb: tuple[int, int], parent=None):
        super().__init__(parent=parent)
        self.setObjectName("statusInterface")
        self.scrollWidget = QWidget()
        self.expandLayout = ExpandLayout(self.scrollWidget)
        self.buffThread = None

        # setting label
        self.headerWidget = QWidget(self)
        self.headerWidget.setFixedWidth(sizeHintdb[0]-165)
        self.panelLabel = QLabel(self.tr("Status"), self.headerWidget)
        self.panelLabel.setSizePolicy(QSizePolicy.Maximum, self.panelLabel.sizePolicy().verticalPolicy())
        self.panelLabel.adjustSize()
        #self.panelLabel.setFixedWidth(100)
        self.panelHelp = TransparentToolButton(QIcon(os.path.join(basedir, 'res/icons/question.svg')), self.headerWidget)
        self.panelHelp.setFixedSize(25,25)
        self.panelHelp.setIconSize(QSize(25,25))

        self.usertagLabel = BodyLabel(self.tr("User Name"))
        self.usertagLabel.setSizePolicy(QSizePolicy.Maximum, self.usertagLabel.sizePolicy().verticalPolicy())
        self.usertagEdit = LineEdit(self)
        self.usertagEdit.setClearButtonEnabled(True)
        self.usertagEdit.setPlaceholderText("")
        self.usertagEdit.setFixedWidth(150)
        usertag = settings.usertag_dict.get(settings.petname, "")
        self.usertagEdit.setText(usertag)

        self.headerLayout = QHBoxLayout(self.headerWidget)
        self.headerLayout.setContentsMargins(0, 0, 0, 0)
        self.headerLayout.setSpacing(0)

        self.headerLayout.addWidget(self.panelLabel, Qt.AlignLeft | Qt.AlignVCenter)
        spacerItem1 = QSpacerItem(10, 20, QSizePolicy.Fixed, QSizePolicy.Minimum)
        self.headerLayout.addItem(spacerItem1)
        self.headerLayout.addWidget(self.panelHelp, Qt.AlignLeft | Qt.AlignVCenter)
        spacerItem2 = QSpacerItem(10, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.headerLayout.addItem(spacerItem2)
        self.headerLayout.addWidget(self.usertagLabel, Qt.AlignLeft | Qt.AlignVCenter)
        spacerItem3 = QSpacerItem(5, 20, QSizePolicy.Fixed, QSizePolicy.Minimum)
        self.headerLayout.addItem(spacerItem3)
        self.headerLayout.addWidget(self.usertagEdit, Qt.AlignLeft | Qt.AlignVCenter)
        #self.panelLabel = QLabel(self.tr("Status"), self)

        self.StatusCard = StatusCard(self)

        self.noteStream = NoteFlowGroup(self.tr('Status Log'), sizeHintdb, self.scrollWidget)

        self.__initWidget()

    def __initWidget(self):
        #self.resize(1000, 800)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setViewportMargins(0, 270, 0, 20)
        self.setWidget(self.scrollWidget)
        #self.scrollWidget.resize(1000, 800)
        self.setWidgetResizable(True)

        # initialize style sheet
        self.__setQss()

        # initialize layout
        self.__initLayout()
        self.__connectSignalToSlot()

    def __initLayout(self):
        self.headerWidget.move(60, 20)
        self.StatusCard.move(60, 75)


        # add cards to group
        #self.ModeGroup.addSettingCard(self.noteStream)
        #self.ModeGroup.addSettingCard(self.AllowDropCard)

        # add setting card group to layout
        self.expandLayout.setSpacing(28)
        self.expandLayout.setContentsMargins(70, 30, 70, 0)

        self.expandLayout.addWidget(self.noteStream)


    def __setQss(self):
        """ set style sheet """
        self.scrollWidget.setObjectName('scrollWidget')
        self.panelLabel.setObjectName('panelLabel')

        theme = 'light' #if isDarkTheme() else 'light'
        with open(os.path.join(basedir, 'res/icons/Dashboard/qss/', theme, 'status_interface.qss'), encoding='utf-8') as f:
            self.setStyleSheet(f.read())

    def __connectSignalToSlot(self):
        """ connect signal to slot """
        self.panelHelp.clicked.connect(self._showInstruction)
        self.changePet.connect(self.StatusCard._changePet)

        self.usertagEdit.textChanged.connect(self._on_UserTag_changed)
    
    def _changePet(self):
        self.changePet.emit()
        settings.HP_stop = False
        settings.FV_stop = False
        self.stopBuffThread()
        usertag = settings.usertag_dict.get(settings.petname, "")
        self.usertagEdit.setText(usertag)

    def _addNote(self, icon, content):
        '''
        pfpPath = os.path.join(basedir, 'res/icons/unknown.svg')
        icon = QImage()
        icon.load(pfpPath)
        content = "这是一个测试 This is a test " * random.randint(1,10)
        '''
        self.noteStream.addNote(icon, content)

    def _addBuff(self, item_config):
        return  # Removed economy entry point, including signal callers.
    
    def startBuffThread(self):
        return

    def stopBuffThread(self):
        if self.buffThread:
            self.buffThread.terminate()
            self.buffThread.wait()
        self.buffThread = None
    
    def _addBuffUI(self, itemName, item_conf, idx):
        return

    def _takeEffect(self, effect, value):
        return

    def _removeBuffUI(self, itemName, idx):
        return
    
    def _rmBuff(self, itemName):
        self.rmBuffInThread.emit(itemName)

    def _showInstruction(self):
        title = self.tr("Status Guide")
        content = self.tr('Character status and notification log. The log is cleared when the app closes.')
        self.__showMessageBox(title, content)
        return     

    def __showMessageBox(self, title, content, yesText='OK'):

        WarrningMessage = MessageBox(title, content, self)
        if yesText == 'OK':
            WarrningMessage.yesButton.setText(self.tr('OK'))
        else:
            WarrningMessage.yesButton.setText(yesText)
        WarrningMessage.cancelButton.setText(self.tr('Cancel'))
        if WarrningMessage.exec():
            return True
        else:
            #print('Cancel button is pressed')
            return False
        
    def _on_UserTag_changed(self, text):
        settings.usertag_dict[settings.petname] = text
        settings.save_settings()
