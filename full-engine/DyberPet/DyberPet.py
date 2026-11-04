import sys
from sys import platform
import time
import math
import types
import random
import inspect
import logging
import webbrowser
from typing import List, Optional
from pathlib import Path
import pynput.mouse as mouse

from PySide6.QtWidgets import *
from PySide6.QtCore import Qt, QTimer, QObject, QPoint, QEvent, QElapsedTimer
from PySide6.QtCore import QObject, QThread, Signal, QRectF, QRect, QSize, QPropertyAnimation, QAbstractAnimation
from PySide6.QtGui import QImage, QPixmap, QIcon, QCursor, QPainter, QFont, QFontMetrics, QAction, QBrush, QPen, QColor, QFontDatabase, QPainterPath, QRegion, QIntValidator, QDoubleValidator, QTransform

from qfluentwidgets import CaptionLabel, setFont, Action #,RoundMenu
from qfluentwidgets import FluentIcon as FIF
from DyberPet.custom_widgets import SystemTray
from .custom_roundmenu import RoundMenu

from DyberPet.conf import *
from DyberPet.utils import *
from DyberPet.modules import *
from DyberPet.Accessory import MouseMoveManager
from DyberPet.custom_widgets import RoundBarBase, LevelBadge
from DyberPet.bubbleManager import BubbleManager
from DyberPet.local_brain import LocalBrain, save_default_config, chat_with_messages
from DyberPet.throw import throw_velocity  # lanzamiento: calculo puro compartido
from DyberPet.mia_chat import ChatBox, ChatHistory, ask_mia, load_chat_config, bubble_duration_s, build_mia_chat_bubble

# initialize settings
import DyberPet.settings as settings
settings.init()

basedir = settings.BASEDIR
configdir = settings.CONFIGDIR


# version
dyberpet_version = settings.VERSION_LABEL
vf = open(os.path.join(configdir,'data/version'), 'w')
vf.write(dyberpet_version)
vf.close()

# some UI size parameters
status_margin = int(3)
statbar_h = int(20)
icons_wh = 20

# system config
sys_hp_tiers = settings.HP_TIERS 
sys_hp_interval = settings.HP_INTERVAL
sys_lvl_bar = settings.LVL_BAR
sys_pp_heart = settings.PP_HEART
sys_pp_item = settings.PP_ITEM
sys_pp_audio = settings.PP_AUDIO


# Pet HP progress bar
class DP_HpBar(QProgressBar):
    hptier_changed = Signal(int, str, name='hptier_changed')
    hp_updated = Signal(int, name='hp_updated')

    def __init__(self, *args, **kwargs):

        super(DP_HpBar, self).__init__(*args, **kwargs)

        self.setFormat('0/100')
        self.setValue(0)
        self.setAlignment(Qt.AlignCenter)
        self.hp_tiers = sys_hp_tiers #[0,50,80,100]

        self.hp_max = 100
        self.interval = 1
        self.hp_inner = 0
        self.hp_perct = 0

        # Custom colors and sizes
        self.bar_color = QColor("#FAC486")  # Fill color
        self.border_color = QColor(0, 0, 0) # Border color
        self.border_width = 1               # Border width in pixels
    
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Full widget rect minus border width to avoid overlap
        full_rect = QRectF(self.border_width / 2.0, self.border_width / 2.0,
                           self.width() - self.border_width, self.height() - self.border_width)
        radius = (self.height() - self.border_width) / 2.0

        # Draw the background rounded rectangle
        painter.setBrush(QBrush(QColor(240, 240, 240)))  # Light gray background
        painter.setPen(QPen(self.border_color, self.border_width))
        painter.drawRoundedRect(full_rect, radius, radius)

        # Create a clipping path for the filled progress that is inset by the border width
        clip_path = QPainterPath()
        inner_rect = full_rect.adjusted(self.border_width, self.border_width, -self.border_width, -self.border_width)
        clip_path.addRoundedRect(inner_rect, radius - self.border_width, radius - self.border_width)
        painter.setClipPath(clip_path)

        # Calculate progress rect and draw it within the clipping region
        progress_width = (self.width() - 2 * self.border_width) * self.value() / self.maximum()
        progress_rect = QRectF(self.border_width, self.border_width,
                               progress_width, self.height() - 2 * self.border_width)

        painter.setBrush(QBrush(self.bar_color))
        painter.setPen(Qt.NoPen)
        painter.drawRect(progress_rect)
        
        # Text drawing
        painter.setClipping(False)  # Disable clipping to draw text over entire bar
        text = self.format()  # Use the format string directly
        painter.setPen(QColor(0, 0, 0))  # Set text color
        font = QFont("Segoe UI", 9, QFont.Normal)
        painter.setFont(font)
        #painter.drawText(full_rect, Qt.AlignCenter, text)
        font_metrics = QFontMetrics(font)
        text_height = font_metrics.height()
        # Draw text in the calculated position
        painter.drawText(full_rect.adjusted(0, -font_metrics.descent()//2, 0, 0), Qt.AlignCenter, text)

    def init_HP(self, change_value, interval_time):
        self.hp_max = int(100*interval_time)
        self.interval = interval_time
        if change_value == -1:
            self.hp_inner = self.hp_max
            settings.pet_data.change_hp(self.hp_inner)
        else:
            self.hp_inner = change_value
        self.hp_perct = math.ceil(round(self.hp_inner/self.interval, 1))
        self.setFormat('%i/100'%self.hp_perct)
        self.setValue(self.hp_perct)
        self._onTierChanged()
        self.hp_updated.emit(self.hp_perct)

    def updateValue(self, change_value, from_mod):
        return 0  # Historical satiety is inert, including scheduler timers.

        before_value = self.value()

        if from_mod == 'Scheduler':
            # Mia: Mia no es un tamagotchi; el hambre no baja con el tiempo (con hambre deja de moverse).
            if settings.HP_stop or getattr(settings, "petname", "") == "Mia":
                return
            new_hp_inner = max(self.hp_inner + change_value, 0)

        else:

            if change_value > 0:
                new_hp_inner = min(self.hp_inner + change_value*self.interval, self.hp_max)

            elif change_value < 0:
                new_hp_inner = max(self.hp_inner + change_value*self.interval, 0)

            else:
                return 0


        if new_hp_inner == self.hp_inner:
            return 0
        else:
            self.hp_inner = new_hp_inner

        new_hp_perct = math.ceil(round(self.hp_inner/self.interval, 1))
            
        if new_hp_perct == self.hp_perct:
            settings.pet_data.change_hp(self.hp_inner)
            return 0
        else:
            self.hp_perct = new_hp_perct
            self.setFormat('%i/100'%self.hp_perct)
            self.setValue(self.hp_perct)
        
        after_value = self.value()

        hp_tier = sum([int(after_value>i) for i in self.hp_tiers])

        #告知动画模块、通知模块
        if hp_tier > settings.pet_data.hp_tier:
            self.hptier_changed.emit(hp_tier,'up')
            settings.pet_data.change_hp(self.hp_inner, hp_tier)
            self._onTierChanged()

        elif hp_tier < settings.pet_data.hp_tier:
            self.hptier_changed.emit(hp_tier,'down')
            settings.pet_data.change_hp(self.hp_inner, hp_tier)
            self._onTierChanged()
            
        else:
            settings.pet_data.change_hp(self.hp_inner) #.hp = current_value

        self.hp_updated.emit(self.hp_perct)
        return int(after_value - before_value)

    def _onTierChanged(self):
        colors = ["#f8595f", "#f8595f", "#FAC486", "#abf1b7"]
        self.bar_color = QColor(colors[settings.pet_data.hp_tier])  # Fill color
        self.update()
        



# Favorability Progress Bar
class DP_FvBar(QProgressBar):
    fvlvl_changed = Signal(int, name='fvlvl_changed')
    fv_updated = Signal(int, int, name='fv_updated')

    def __init__(self, *args, **kwargs):

        super(DP_FvBar, self).__init__(*args, **kwargs)

        # Custom colors and sizes
        self.bar_color = QColor("#F4665C")  # Fill color
        self.border_color = QColor(0, 0, 0) # Border color
        self.border_width = 1               # Border width in pixels

        self.fvlvl = 0
        self.lvl_bar = sys_lvl_bar #[20, 120, 300, 600, 1200]
        self.points_to_lvlup = self.lvl_bar[self.fvlvl]
        self.setMinimum(0)
        self.setMaximum(self.points_to_lvlup)
        self.setFormat('lv%s: 0/%s'%(int(self.fvlvl), self.points_to_lvlup))
        self.setValue(0)
        self.setAlignment(Qt.AlignCenter)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Full widget rect minus border width to avoid overlap
        full_rect = QRectF(self.border_width / 2.0, self.border_width / 2.0,
                           self.width() - self.border_width, self.height() - self.border_width)
        radius = (self.height() - self.border_width) / 2.0

        # Draw the background rounded rectangle
        painter.setBrush(QBrush(QColor(240, 240, 240)))  # Light gray background
        painter.setPen(QPen(self.border_color, self.border_width))
        painter.drawRoundedRect(full_rect, radius, radius)

        # Create a clipping path for the filled progress that is inset by the border width
        clip_path = QPainterPath()
        inner_rect = full_rect.adjusted(self.border_width, self.border_width, -self.border_width, -self.border_width)
        clip_path.addRoundedRect(inner_rect, radius - self.border_width, radius - self.border_width)
        painter.setClipPath(clip_path)

        # Calculate progress rect and draw it within the clipping region
        progress_width = (self.width() - 2 * self.border_width) * self.value() / self.maximum()
        progress_rect = QRectF(self.border_width, self.border_width,
                               progress_width, self.height() - 2 * self.border_width)

        painter.setBrush(QBrush(self.bar_color))
        painter.setPen(Qt.NoPen)
        painter.drawRect(progress_rect)
        
        # Text drawing
        painter.setClipping(False)  # Disable clipping to draw text over entire bar
        text = self.format()  # Use the format string directly
        painter.setPen(QColor(0, 0, 0))  # Set text color
        font = QFont("Segoe UI", 9, QFont.Normal)
        painter.setFont(font)
        #painter.drawText(full_rect, Qt.AlignCenter, text)
        font_metrics = QFontMetrics(font)
        text_height = font_metrics.height()
        # Draw text in the calculated position
        painter.drawText(full_rect.adjusted(0, -font_metrics.descent()//2, 0, 0), Qt.AlignCenter, text)

    def init_FV(self, fv_value, fv_lvl):
        self.fvlvl = fv_lvl
        self.points_to_lvlup = self.lvl_bar[self.fvlvl]
        self.setMinimum(0)
        self.setMaximum(self.points_to_lvlup)
        self.setFormat('lv%s: %i/%s'%(int(self.fvlvl), fv_value, self.points_to_lvlup))
        self.setValue(fv_value)
        self.fv_updated.emit(self.value(), self.fvlvl)

    def updateValue(self, change_value, from_mod):

        before_value = self.value()

        if from_mod == 'Scheduler':
            if settings.pet_data.hp_tier > 1:
                prev_value = self.value()
                current_value = self.value() + change_value #, self.maximum())
            elif settings.pet_data.hp_tier == 0 and not settings.FV_stop:
                prev_value = self.value()
                current_value = self.value() - 1
            else:
                return 0

        elif change_value != 0:
            prev_value = self.value()
            current_value = self.value() + change_value

        else:
            return 0


        if current_value < self.maximum():
            self.setValue(current_value)

            current_value = self.value()
            if current_value == prev_value:
                return 0
            else:
                self.setFormat('lv%s: %s/%s'%(int(self.fvlvl), int(current_value), int(self.maximum())))
                settings.pet_data.change_fv(current_value)
            after_value = self.value()

            self.fv_updated.emit(self.value(), self.fvlvl)
            return int(after_value - before_value)

        else: #好感度升级
            addedValue = self._level_up(current_value, prev_value)
            self.fv_updated.emit(self.value(), self.fvlvl)
            return addedValue

    def _level_up(self, newValue, oldValue, added=0):
        if self.fvlvl == (len(self.lvl_bar)-1):
            current_value = self.maximum()
            if current_value == oldValue:
                return 0
            self.setFormat('lv%s: %s/%s'%(int(self.fvlvl),int(current_value),self.points_to_lvlup))
            self.setValue(current_value)
            settings.pet_data.change_fv(current_value, self.fvlvl)
            #告知动画模块、通知模块
            self.fvlvl_changed.emit(-1)
            return current_value - oldValue + added

        else:
            #after_value = newValue
            added_tmp = self.maximum() - oldValue
            newValue -= self.maximum()
            self.fvlvl += 1
            self.points_to_lvlup = self.lvl_bar[self.fvlvl]
            self.setMinimum(0)
            self.setMaximum(self.points_to_lvlup)
            self.setFormat('lv%s: %s/%s'%(int(self.fvlvl),int(newValue),self.points_to_lvlup))
            self.setValue(newValue)
            settings.pet_data.change_fv(newValue, self.fvlvl)
            #告知动画模块、通知模块
            self.fvlvl_changed.emit(self.fvlvl)

            if newValue < self.maximum():
                return newValue + added_tmp + added
            else:
                return self._level_up(newValue, 0, added_tmp)




# Pet Object

class _MiaChatWorker(QObject):
    """Corre `fn()` (la llamada a Ollama) en un QThread aparte, nunca en el
    hilo de UI (contrato-chat.txt)."""
    finished = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self):
        self.finished.emit(self._fn())


class PetWidget(QWidget):
    setup_notification = Signal(str, str, name='setup_notification')
    setup_bubbleText = Signal(dict, int, int, name="setup_bubbleText")
    close_bubble = Signal(str, name="close_bubble")
    addItem_toInven = Signal(int, list, name='addItem_toInven')
    fvlvl_changed_main_note = Signal(int, name='fvlvl_changed_main_note')
    fvlvl_changed_main_inve = Signal(int, name='fvlvl_changed_main_inve')
    hptier_changed_main_note = Signal(int, str, name='hptier_changed_main_note')

    setup_acc = Signal(dict, int, int, name='setup_acc')
    change_note = Signal(name='change_note')
    close_all_accs = Signal(name='close_all_accs')

    move_sig = Signal(int, int, name='move_sig')
    #acc_withdrawed = Signal(str, name='acc_withdrawed')
    send_positions = Signal(list, list, name='send_positions')

    lang_changed = Signal(name='lang_changed')
    show_controlPanel = Signal(name='show_controlPanel')

    show_dashboard = Signal(name='show_dashboard')
    hp_updated = Signal(int, name='hp_updated')
    fv_updated = Signal(int, int, name='fv_updated')

    compensate_rewards = Signal(name="compensate_rewards")
    refresh_bag = Signal(name="refresh_bag")
    addCoins = Signal(int, name='addCoins')
    autofeed = Signal(name='autofeed')

    stopAllThread = Signal(name='stopAllThread')

    taskUI_Timer_update = Signal(name="taskUI_Timer_update")
    taskUI_task_end = Signal(name="taskUI_task_end")
    single_pomo_done = Signal(name="single_pomo_done")

    refresh_acts = Signal(name='refresh_acts')

    def __init__(self, parent=None, curr_pet_name=None, pets=(), screens=[], audit_mode=False):
        """
        宠物组件
        :param parent: 父窗口
        :param curr_pet_name: 当前宠物名称
        :param pets: 全部宠物列表
        """
        super(PetWidget, self).__init__(parent) #, flags=Qt.WindowFlags())
        self.audit_mode = audit_mode
        self.pets = settings.pets
        if curr_pet_name is None:
            self.curr_pet_name = settings.default_pet
        else:
            self.curr_pet_name = curr_pet_name
        #self.pet_conf = PetConfig()

        self.image = None
        self.tray = None

        # 鼠标拖拽初始属性
        self.is_follow_mouse = False
        self.mouse_moving = False
        self.mouse_drag_pos = self.pos()
        self.mouse_pos = [0, 0]

        # Record too frequent mouse clicking
        self.click_timer = QElapsedTimer()
        self.click_interval = 1000  # Max interval in ms to consider consecutive clicks
        self.click_count = 0
        # Mia: ultimo punto de clic (relativo al sprite), para elegir zona de
        # toque en patpat() (comportamiento 6/B2).
        self._mia_last_click_pos = None

        # Screen info
        settings.screens = screens #[i.geometry() for i in screens]
        # Mia: usa QGuiApplication.primaryScreen() de verdad (no solo el
        # orden recibido) para no depender de que quien arme `screens` haya
        # puesto la primaria primero.
        from PySide6.QtGui import QGuiApplication
        from DyberPet.mia_director import pick_primary_screen
        primary = pick_primary_screen(screens, QGuiApplication.primaryScreen())
        self.current_screen = primary.availableGeometry() #geometry()
        settings.current_screen = primary
        #self.screen_geo = QDesktopWidget().availableGeometry() #screenGeometry()
        self.screen_width = self.current_screen.width() #self.screen_geo.width()
        self.screen_height = self.current_screen.height() #self.screen_geo.height()

        self._init_ui()
        self._init_widget()
        self.init_conf(self.curr_pet_name) # if curr_pet_name else self.pets[0])

        #self._set_menu(pets)
        #self._set_tray()
        self.show()

        self._setup_ui()

        # 开始动画模块和交互模块
        self.threads = {}
        self.workers = {}
        if self.audit_mode:
            for timer in self.findChildren(QTimer):
                timer.stop()
            return
        self.runAnimation()
        self.runInteraction()
        self.runScheduler()

        # Mia: saluda al arrancar (greet si existe la pose, si no happy).
        # Movido aqui (no a init_conf) porque necesita self.workers, que se
        # crea justo arriba; init_conf corre antes de que existan.
        self._send_mia_greeting()
        

        # 初始化重复提醒任务 - feature deleted
        #self.remind_window.initial_task()

        # 启动完毕10s后检查好感度等级奖励补偿
        self.compensate_timer = None
        self._setup_compensate()

    def _setup_compensate(self):
        self._stop_compensate()
        self.compensate_timer = QTimer(singleShot=True, timeout=self._compensate_rewards)
        self.compensate_timer.start(10000)

    def _stop_compensate(self):
        if self.compensate_timer:
            self.compensate_timer.stop()

    def moveEvent(self, event):
        self.move_sig.emit(self.pos().x()+self.width()//2, self.pos().y()+self.height())

    def enterEvent(self, event):
        # Change the cursor when it enters the window
        self.setCursor(self.cursor_default)
        # Mia: el raton pasando por encima del pet tambien cuenta como
        # interaccion (comportamiento 4, B1b).
        self.mia_director.note_interaction()
        super().enterEvent(event)

    def leaveEvent(self, event):
        # Restore the original cursor when it leaves the window
        self.setCursor(self.cursor_user)
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event):
        # Mia: doble clic abre el chat escrito (contrato-chat.txt punto 1).
        if event.button() == Qt.LeftButton:
            self._open_mia_chat()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        """
        鼠标点击事件
        :param event: 事件
        :return:
        """
        
        if event.button() == Qt.RightButton:
            # 打开右键菜单
            if settings.draging:
                return
            #self.setContextMenuPolicy(Qt.CustomContextMenu)
            #self.customContextMenuRequested.connect(self._show_Staus_menu)
            self._show_Staus_menu()
            
        if event.button() == Qt.LeftButton:
            # lanzamiento: cada gesto empieza limpio y usa un reloj monotono.
            self._throw_samples = [(event.globalPos().x(), event.globalPos().y(), time.monotonic())]
            # 左键绑定拖拽
            self.is_follow_mouse = True
            self.mouse_drag_pos = event.globalPos() - self.pos()
            # Mia: cualquier clic cuenta como interaccion (comportamiento 4,
            # evita que el sueno llegue mientras User esta usando el pet) y
            # guardamos el punto de clic relativo al sprite para la zona de
            # toque (comportamiento 6, ver patpat()).
            self.mia_director.note_interaction()
            self._mia_last_click_pos = event.pos()
            if settings.petname == 'Draconia':
                self._draconia_reactions.begin_gesture()
            
            if settings.onfloor == 0:
            # Left press activates Drag interaction
                if settings.set_fall:              
                    settings.onfloor=0
                settings.draging=1
                self.workers['Animation'].pause()
                self.workers['Interaction'].start_interact('mousedrag')
            
            # Record click
            if self.click_timer.isValid() and self.click_timer.elapsed() <= self.click_interval:
                self.click_count += 1
            else:
                self.click_count = 1
                self.click_timer.restart()
                
            event.accept()
            #self.setCursor(QCursor(Qt.ArrowCursor))
            self.setCursor(self.cursor_clicked)

        # Mia: clic central abre el chat escrito (contrato-chat.txt punto 1:
        # separar doble-clic de patpat es fragil con este motor de clics, asi
        # que usamos el menu + este atajo de clic central en su lugar).
        if event.button() == Qt.MiddleButton:
            self._open_mia_chat()
            event.accept()

    def mouseMoveEvent(self, event):
        """
        鼠标移动事件, 左键且绑定跟随, 移动窗体
        :param event:
        :return:
        """
        
        if Qt.LeftButton and self.is_follow_mouse:
            self.move(event.globalPos() - self.mouse_drag_pos)

            self.mouse_moving = True
            self.setCursor(self.cursor_dragged)
            # Mia: seguir arrastrando tambien cuenta como interaccion.
            self.mia_director.note_interaction()
            if settings.petname == 'Draconia':
                self._draconia_react('drag')

            # lanzamiento: conservar 80 ms y una muestra anterior para interpolar.
            now = time.monotonic()
            self._throw_samples.append((event.globalPos().x(), event.globalPos().y(), now))
            while len(self._throw_samples) > 2 and self._throw_samples[1][2] <= now - 0.080:
                del self._throw_samples[0]

            if settings.onfloor == 1:
                if settings.set_fall:
                    settings.onfloor=0
                settings.draging=1
                self.workers['Animation'].pause()
                self.workers['Interaction'].start_interact('mousedrag')
                # Mia: animo (contrato mia-mood punto 2) -- la arrastran.
                self._mia_note_mood_event("drag")
            

            event.accept()
            #print(self.pos().x(), self.pos().y())

    def mouseReleaseEvent(self, event):
        """
        松开鼠标操作
        :param event:
        :return:
        """
        if event.button()==Qt.LeftButton:

            self.is_follow_mouse = False
            #self.setCursor(QCursor(Qt.ArrowCursor))
            self.setCursor(self.cursor_default)

            #print(self.mouse_moving, settings.onfloor)
            if settings.onfloor == 1 and not self.mouse_moving:
                self.patpat()

            else:

                anim_area = QRect(self.pos() + QPoint(self.width()//2-self.label.width()//2, 
                                                      self.height()-self.label.height()), 
                                  QSize(self.label.width(), self.label.height()))
                intersected = self.current_screen.intersected(anim_area)
                area = intersected.width() * intersected.height() / self.label.width() / self.label.height()
                if area > 0.5:
                    pass
                else:
                    for screen in settings.screens:
                        if screen.geometry() == self.current_screen:
                            continue
                        intersected = screen.geometry().intersected(anim_area)
                        area_tmp = intersected.width() * intersected.height() / self.label.width() / self.label.height()
                        if area_tmp > 0.5:
                            self.switch_screen(screen)
                    

                if settings.set_fall:
                    settings.onfloor=0
                    settings.draging=0
                    settings.prefall=1

                    # lanzamiento: sensibilidad antes del tope; intervalo del QTimer de caida.
                    samples = [(x * settings.fixdragspeedx, y * settings.fixdragspeedy, t)
                               for x, y, t in getattr(self, '_throw_samples', [])]
                    settings.dragspeedx, settings.dragspeedy = throw_velocity(
                        samples, time.monotonic(),
                        self.workers['Interaction'].timer.interval() / 1000.0,
                        settings.max_throw_speed)
                    self._throw_samples = []

                    if settings.dragspeedx > 0:
                        settings.fall_right = True
                    else:
                        settings.fall_right = False
                    # Mia: animo (contrato mia-mood punto 2) -- la sueltan y cae.
                    self._mia_note_mood_event("fall")
                    if settings.petname == 'Draconia':
                        self._draconia_react('fall')

                else:
                    settings.draging=0
                    self._move_customized(0,0)
                    settings.current_img = self.pet_conf.default.images[0]
                    self.set_img()
                    self.workers['Animation'].resume()
            self.mouse_moving = False


    def _init_widget(self) -> None:
        """
        初始化窗体, 无边框半透明窗口
        :return:
        """
        if settings.on_top_hint:
            if platform == 'win32':
                self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SubWindow | Qt.NoDropShadowWindowHint)
            else:
                # SubWindow not work in MacOS
                self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint)
        else:
            if platform == 'win32':
                self.setWindowFlags(Qt.FramelessWindowHint | Qt.SubWindow | Qt.NoDropShadowWindowHint)
            else:
                # SubWindow not work in MacOS
                self.setWindowFlags(Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)

        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.repaint()
        # 是否跟随鼠标
        self.is_follow_mouse = False
        self.mouse_drag_pos = self.pos()

    def ontop_update(self):
        if settings.on_top_hint:
            if platform == 'win32':
                self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SubWindow | Qt.NoDropShadowWindowHint)
            else:
                # SubWindow not work in MacOS
                self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint)
        else:
            if platform == 'win32':
                self.setWindowFlags(Qt.FramelessWindowHint | Qt.SubWindow | Qt.NoDropShadowWindowHint)
            else:
                # SubWindow not work in MacOS
                self.setWindowFlags(Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
                
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.show()


    def _init_ui(self):
        # The Character ----------------------------------------------------------------------------
        self.label = QLabel(self)
        self.label.setScaledContents(True)
        self.label.setAlignment(Qt.AlignBottom | Qt.AlignHCenter)
        self.label.installEventFilter(self)
        #self.label.setStyleSheet("border : 2px solid blue")

        # system animations
        self.sys_src = _load_all_pic('sys')
        self.sys_conf = PetConfig.init_sys(self.sys_src) 
        # ------------------------------------------------------------------------------------------

        # Hover Timer --------------------------------------------------------
        self.status_frame = QFrame()
        vbox = QVBoxLayout()
        vbox.setContentsMargins(0,0,0,0)
        vbox.setSpacing(0)

        # 番茄时钟
        h_box3 = QHBoxLayout()
        h_box3.setContentsMargins(0,0,0,0)
        h_box3.setAlignment(Qt.AlignBottom | Qt.AlignHCenter)
        self.tomatoicon = QLabel(self)
        self.tomatoicon.setFixedSize(statbar_h,statbar_h)
        image = QPixmap()
        image.load(os.path.join(basedir, 'res/icons/Tomato_icon.png'))
        self.tomatoicon.setScaledContents(True)
        self.tomatoicon.setPixmap(image)
        self.tomatoicon.setAlignment(Qt.AlignBottom | Qt.AlignRight)
        h_box3.addWidget(self.tomatoicon)
        self.tomato_time = RoundBarBase(fill_color="#ef4e50", parent=self) #QProgressBar(self, minimum=0, maximum=25, objectName='PetTM')
        self.tomato_time.setFormat('')
        self.tomato_time.setValue(25)
        self.tomato_time.setAlignment(Qt.AlignCenter)
        self.tomato_time.hide()
        self.tomatoicon.hide()
        h_box3.addWidget(self.tomato_time)

        # 专注时间
        h_box4 = QHBoxLayout()
        h_box4.setContentsMargins(0,status_margin,0,0)
        h_box4.setAlignment(Qt.AlignBottom | Qt.AlignHCenter)
        self.focusicon = QLabel(self)
        self.focusicon.setFixedSize(statbar_h,statbar_h)
        image = QPixmap()
        image.load(os.path.join(basedir, 'res/icons/Timer_icon.png'))
        self.focusicon.setScaledContents(True)
        self.focusicon.setPixmap(image)
        self.focusicon.setAlignment(Qt.AlignBottom | Qt.AlignRight)
        h_box4.addWidget(self.focusicon)
        self.focus_time = RoundBarBase(fill_color="#47c0d2", parent=self) #QProgressBar(self, minimum=0, maximum=0, objectName='PetFC')
        self.focus_time.setFormat('')
        self.focus_time.setValue(0)
        self.focus_time.setAlignment(Qt.AlignCenter)
        self.focus_time.hide()
        self.focusicon.hide()
        h_box4.addWidget(self.focus_time)

        vbox.addStretch()
        vbox.addLayout(h_box3)
        vbox.addLayout(h_box4)

        self.status_frame.setLayout(vbox)
        #self.status_frame.setStyleSheet("border : 2px solid blue")
        self.status_frame.setContentsMargins(0,0,0,0)
        #self.status_box.addWidget(self.status_frame)
        #self.status_frame.hide()
        # ------------------------------------------------------------

        #Layout_1 ----------------------------------------------------
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(0,0,0,0)

        self.petlayout = QVBoxLayout()
        self.petlayout.addWidget(self.status_frame)

        image_hbox = QHBoxLayout()
        image_hbox.setContentsMargins(0,0,0,0)
        image_hbox.addStretch()
        image_hbox.addWidget(self.label, Qt.AlignBottom | Qt.AlignHCenter)
        image_hbox.addStretch()

        self.petlayout.addLayout(image_hbox, Qt.AlignBottom | Qt.AlignHCenter)
        self.petlayout.setAlignment(Qt.AlignBottom | Qt.AlignHCenter)
        self.petlayout.setContentsMargins(0,0,0,0)
        self.layout.addLayout(self.petlayout, Qt.AlignBottom | Qt.AlignHCenter)
        # ------------------------------------------------------------

        self.setLayout(self.layout)
        # ------------------------------------------------------------


        # 初始化背包
        #self.items_data = ItemData(HUNGERSTR=settings.HUNGERSTR, FAVORSTR=settings.FAVORSTR)
        settings.items_data = ItemData(HUNGERSTR=settings.HUNGERSTR, FAVORSTR=settings.FAVORSTR)
        #self._init_Inventory()
        #self.showing_comp = 0

        # 客制化光标
        self.cursor_user = self.cursor()
        system_cursor_size = 32
        if os.path.exists(os.path.join(basedir, 'res/icons/cursor_default.png')):
            self.cursor_default = QCursor(QPixmap("res/icons/cursor_default.png").scaled(system_cursor_size, system_cursor_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.cursor_default = self.cursor_user
        if os.path.exists(os.path.join(basedir, 'res/icons/cursor_clicked.png')):
            self.cursor_clicked = QCursor(QPixmap("res/icons/cursor_clicked.png").scaled(system_cursor_size, system_cursor_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.cursor_clicked = self.cursor_user
        if os.path.exists(os.path.join(basedir, 'res/icons/cursor_dragged.png')):
            self.cursor_dragged = QCursor(QPixmap("res/icons/cursor_dragged.png").scaled(system_cursor_size, system_cursor_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.cursor_dragged = self.cursor_user

    '''
    def _init_Inventory(self):
        self.items_data = ItemData(HUNGERSTR=settings.HUNGERSTR, FAVORSTR=settings.FAVORSTR)
        self.inventory_window = Inventory(self.items_data)
        self.inventory_window.close_inventory.connect(self.show_inventory)
        self.inventory_window.use_item_inven.connect(self.use_item)
        self.inventory_window.item_note.connect(self.register_notification)
        self.inventory_window.item_anim.connect(self.item_drop_anim)
        self.addItem_toInven.connect(self.inventory_window.add_items)
        self.acc_withdrawed.connect(self.inventory_window.acc_withdrawed)
        self.fvlvl_changed_main_inve.connect(self.inventory_window.fvchange)
    '''


    def _set_menu(self, pets=()):
        """
        Option Menu
        """
        #menu = RoundMenu(self.tr("More Options"), self)
        #menu.setIcon(FIF.MENU)

        # Select action
        self.act_menu = RoundMenu(self.tr("Select Action"))
        self.act_menu.setIcon(QIcon(os.path.join(basedir,'res/icons/jump.svg')))

        if platform == 'win32':
            self.start_follow_mouse = Action(QIcon(os.path.join(basedir,'res/icons/cursor.svg')),
                                            self.tr('Follow Cursor'),
                                            triggered = self.follow_mouse_act)
            self.act_menu.addAction(self.start_follow_mouse)
            self.act_menu.addSeparator()

        acts_config = settings.act_data.allAct_params[settings.petname]
        self.select_acts = [ _build_act(k, self.act_menu, self._show_act) for k,v in acts_config.items() if v['unlocked']]
        if self.select_acts:
            self.act_menu.addActions(self.select_acts)

        #menu.addMenu(self.act_menu)




        # Drop on/off
        '''
        if settings.set_fall == 1:
            self.switch_fall = Action(QIcon(os.path.join(basedir,'res/icons/on.svg')),
                                      self.tr('Allow Drop'), menu)
        else:
            self.switch_fall = Action(QIcon(os.path.join(basedir,'res/icons/off.svg')),
                                      self.tr("Don't Drop"), menu)
        self.switch_fall.triggered.connect(self.fall_onoff)
        '''
        #menu.addAction(self.switch_fall)

        
        # Visit website - feature deprecated
        '''
        web_file = os.path.join(basedir, 'res/role/sys/webs.json')
        if os.path.isfile(web_file):
            web_dict = json.load(open(web_file, 'r', encoding='UTF-8'))

            self.web_menu = RoundMenu(self.tr("Website"), menu)
            self.web_menu.setIcon(QIcon(os.path.join(basedir,'res/icons/website.svg')))

            web_acts = [_build_act_param(name, web_dict[name], self.web_menu, self.open_web) for name in web_dict]
            self.web_menu.addActions(web_acts)
            menu.addMenu(self.web_menu)
        '''
            
        #menu.addSeparator()
        #self.menu = menu
        #self.menu.addAction(Action(FIF.POWER_BUTTON, self.tr('Exit'), triggered=self.quit))


    def _update_fvlock(self):

        # Update selectable animations
        acts_config = settings.act_data.allAct_params[settings.petname]
        for act_name, act_conf in acts_config.items():
            if act_conf['unlocked']:
                if act_name not in [acti.text() for acti in self.select_acts]:
                    new_act = _build_act(act_name, self.act_menu, self._show_act)
                    self.act_menu.addAction(new_act)
                    self.select_acts.append(new_act)
            else:
                if act_name in [acti.text() for acti in self.select_acts]:
                    act_index = [acti.text() for acti in self.select_acts].index(act_name)
                    self.act_menu.removeAction(self.select_acts[act_index])
                    self.select_acts.remove(self.select_acts[act_index])


    def _set_Statusmenu(self):
        self.setWindowTitle(self.tr('MiniDraconia'))

        # Character Name
        self.statusTitle = QWidget()
        hboxTitle = QHBoxLayout(self.statusTitle)
        hboxTitle.setContentsMargins(0,0,0,0)
        self.nameLabel = CaptionLabel(self.tr('MiniDraconia'), self)
        setFont(self.nameLabel, 14, QFont.DemiBold)
        #self.nameLabel.setFixedWidth(75)

        self.daysLabel = CaptionLabel('', self)
        setFont(self.daysLabel, 14, QFont.Normal)

        hboxTitle.addStretch(1)
        hboxTitle.addWidget(self.nameLabel, Qt.AlignLeft | Qt.AlignVCenter)
        hboxTitle.addStretch(1)
        self.daysLabel.hide()
        #hboxTitle.addStretch(1)
        self.statusTitle.setFixedSize(225, 25)

        # # Status Title
        # hp_tier = settings.pet_data.hp_tier
        # statusText = self.tr("Status: ") + f"{settings.TIER_NAMES[hp_tier]}"
        # self.statLabel = CaptionLabel(statusText, self)
        # setFont(self.statLabel, 14, QFont.Normal)

        # Level Badge
        lvlWidget = QWidget()
        h_box0 = QHBoxLayout(lvlWidget)
        h_box0.setContentsMargins(0,0,0,0)
        h_box0.setSpacing(5)
        h_box0.setAlignment(Qt.AlignCenter)
        lvlLable = CaptionLabel(self.tr("Level"))
        setFont(lvlLable, 13, QFont.Normal)
        lvlLable.adjustSize()
        lvlLable.setFixedSize(43, lvlLable.height())
        self.lvl_badge = LevelBadge(settings.pet_data.fv_lvl)
        h_box0.addWidget(lvlLable)
        #h_box0.addStretch(1)
        h_box0.addWidget(self.lvl_badge)
        h_box0.addStretch(1)
        lvlWidget.setFixedSize(250, 25)

        # Hunger status
        hpWidget = QWidget()
        h_box1 = QHBoxLayout(hpWidget)
        h_box1.setContentsMargins(0,0,0,0) #status_margin,0,0)
        h_box1.setSpacing(5)
        h_box1.setAlignment(Qt.AlignCenter) #AlignBottom | Qt.AlignHCenter)
        hpLable = CaptionLabel('')
        setFont(hpLable, 13, QFont.Normal)
        hpLable.adjustSize()
        hpLable.setFixedSize(43, hpLable.height())
        self.hpicon = QLabel(self)
        self.hpicon.setFixedSize(icons_wh,icons_wh)
        image = QPixmap()
        image.load(os.path.join(basedir, 'res/icons/HP_icon.png'))
        self.hpicon.setScaledContents(True)
        self.hpicon.setPixmap(image)
        self.hpicon.setAlignment(Qt.AlignCenter) #AlignBottom | Qt.AlignRight)
        h_box1.addWidget(hpLable)
        h_box1.addStretch(1)
        h_box1.addWidget(self.hpicon)
        #h_box1.addStretch(1)
        self.pet_hp = DP_HpBar(self, minimum=0, maximum=100, objectName='PetHP')
        self.pet_hp.hp_updated.connect(self._hp_updated)
        h_box1.addWidget(self.pet_hp)
        h_box1.addStretch(1)

        # favor status
        fvWidget = QWidget()
        h_box2 = QHBoxLayout(fvWidget)
        h_box2.setContentsMargins(0,0,0,0) #status_margin,0,0)
        h_box2.setSpacing(5)
        h_box2.setAlignment(Qt.AlignCenter) #Qt.AlignBottom | Qt.AlignHCenter)
        fvLable = CaptionLabel(self.tr("Favor"))
        setFont(fvLable, 13, QFont.Normal)
        fvLable.adjustSize()
        fvLable.setFixedSize(43, fvLable.height())
        self.emicon = QLabel(self)
        self.emicon.setFixedSize(icons_wh,icons_wh)
        image = QPixmap()
        image.load(os.path.join(basedir, 'res/icons/Fv_icon.png'))
        self.emicon.setScaledContents(True)
        self.emicon.setPixmap(image)
        #self.emicon.setAlignment(Qt.AlignBottom | Qt.AlignRight)
        h_box2.addWidget(fvLable, Qt.AlignHCenter | Qt.AlignTop)
        h_box2.addStretch(1)
        h_box2.addWidget(self.emicon)
        self.pet_fv = DP_FvBar(self, minimum=0, maximum=100, objectName='PetEM')
        self.pet_fv.fv_updated.connect(self._fv_updated)

        self.pet_hp.hptier_changed.connect(self.hpchange)
        self.pet_fv.fvlvl_changed.connect(self.fvchange)
        h_box2.addWidget(self.pet_fv)
        h_box2.addStretch(1)

        self.pet_hp.init_HP(settings.pet_data.hp, sys_hp_interval) #2)
        self.pet_fv.init_FV(settings.pet_data.fv, settings.pet_data.fv_lvl)
        self.pet_hp.setFixedSize(145, 15)
        self.pet_fv.setFixedSize(145, 15)

        # Status Widget
        self.statusWidget = QWidget()
        StatVbox = QVBoxLayout(self.statusWidget)
        StatVbox.setContentsMargins(0,5,30,10)
        StatVbox.setSpacing(5)
        
        #StatVbox.addWidget(self.statusTitle, Qt.AlignVCenter)
        StatVbox.addStretch(1)
        #StatVbox.addWidget(self.daysLabel)
        hpWidget.hide()
        self.pet_hp.hide()
        self.hpicon.hide()
        StatVbox.addWidget(fvWidget, Qt.AlignLeft | Qt.AlignVCenter)
        StatVbox.addStretch(1)
        #statusWidget.setLayout(StatVbox)
        #statusWidget.setContentsMargins(0,0,0,0)
        self.statusWidget.setFixedSize(250, 70)
        
        self.StatMenu = RoundMenu(parent=self)
        self.StatMenu.addWidget(self.statusTitle, selectable=False)
        self.StatMenu.addSeparator()
        #self.StatMenu.addWidget(self.statLabel, selectable=False)
        # Keep engine status objects alive, but never expose the economy UI.
        lvlWidget.hide()
        self.statusWidget.hide()
        #self.StatMenu.addWidget(fvbar, selectable=False)
        self.StatMenu.addSeparator()

        #self.StatMenu.addMenu(self.menu)
        self.StatMenu.addActions([
            Action(QIcon(os.path.join(basedir,'res/icons/SystemPanel.png')), 'Settings', triggered=self._show_controlPanel),
        ])
        self.StatMenu.addSeparator()

        self.StatMenu.addMenu(self.act_menu)
        self.switch_fall = Action(FIF.MOVE, self.tr('Allow Drop') if settings.set_fall else self.tr("Don't Drop"))
        self.switch_fall.triggered.connect(self.fall_onoff)
        self.StatMenu.addAction(self.switch_fall)
        self.following_action = Action(FIF.MOVE, self.tr('Following'))
        self.following_action.setCheckable(True)
        self.following_action.triggered.connect(lambda: self.start_follow_mouse.trigger())
        self.StatMenu.addAction(self.following_action)
        self.StatMenu.addSeparator()
        
        # Mia: chat escrito (comportamiento 12, docs/contrato-chat.txt).
        self.StatMenu.addActions([
        ])
        self.StatMenu.addSeparator()

        # Mia: voz en ingles (contrato-voz-en.md). Toggle checkeable que
        # lee/escribe voice.enabled en mia_brain.json; "Status report" y
        # "Today's briefing" piden sus datos/archivo al vuelo.
        from DyberPet.mia_voice import load_voice_config
        # perfil: voz/idioma del personaje activo (contrato punto 7).
        _voice_cfg = load_voice_config(self._mia_brain_path())
        self.mia_voice_toggle = Action(FIF.VOLUME, self.tr("Voice (English)"))
        self.mia_voice_toggle.setCheckable(True)
        self.mia_voice_toggle.setChecked(bool(_voice_cfg.get("enabled", False)))
        self.mia_voice_toggle.triggered.connect(self._toggle_mia_voice)
        self.StatMenu.addActions([
            self.mia_voice_toggle,
            Action(FIF.CALENDAR, self.tr("Status report"), triggered=self._mia_show_status_report),
            Action(FIF.DOCUMENT, self.tr("Today's briefing"), triggered=self._mia_show_briefing),
        ])
        self.StatMenu.addSeparator()

        # Mia: trepar paredes (contrato trepar-paredes). Toggle checkeable
        # que lee/escribe climb.enabled en mia_brain.json.
        from DyberPet.mia_director import load_climb_config
        _climb_cfg = load_climb_config(self._mia_brain_path())
        self.mia_climb_toggle = Action(FIF.UP, self.tr("Climb walls"))
        self.mia_climb_toggle.setCheckable(True)
        self.mia_climb_toggle.setChecked(bool(_climb_cfg.get("enabled", False)))
        self.mia_climb_toggle.triggered.connect(self._toggle_mia_climb)
        self.StatMenu.addActions([self.mia_climb_toggle])
        self.StatMenu.addSeparator()

        # Mia: animo con continuidad (contrato mia-mood punto 7). Entrada de
        # solo lectura; se actualiza cuando cambia la emocion dominante
        # (_mia_note_mood_event).
        self.mia_mood_menu_entry = Action(
            FIF.HEART, self.tr("Mood: ") + getattr(getattr(self, "mia_mood", None), "dominant", "content"))
        self.mia_mood_menu_entry.setEnabled(False)
        self.StatMenu.addActions([self.mia_mood_menu_entry])
        self.StatMenu.addSeparator()

        self.StatMenu.clear()
        self.StatMenu.addActions([
            Action(FIF.SETTING, 'Settings', triggered=self._show_controlPanel),
            Action(FIF.POWER_BUTTON, 'Quit', triggered=self.quit),
        ])


    # def _update_statusTitle(self, hp_tier):
    #     statusText = self.tr("Status: ") + f"{settings.TIER_NAMES[hp_tier]}"
    #     self.statLabel.setText(statusText)


    def _show_Staus_menu(self):
        """
        展示右键菜单
        :return:
        """
        # 光标位置弹出菜单
        self.StatMenu.popup(QCursor.pos()-QPoint(0, self.StatMenu.height()-20))

    def _add_pet(self, pet_name: str):
        pet_acc = {'name':'pet', 'pet_name':pet_name}
        #self.setup_acc.emit(pet_acc, int(self.current_screen.topLeft().x() + random.uniform(0.4,0.7)*self.screen_width), self.pos().y())
        # To accomodate any subpet that always follows main, change the position to top middle pos of pet
        self.setup_acc.emit(pet_acc, int( self.pos().x() + self.width()/2 ), self.pos().y())

    def open_web(self, web_address):
        try:
            webbrowser.open(web_address)
        except:
            return
    '''
    def freeze_pet(self):
        """stop all thread, function for save import"""
        self.stop_thread('Animation')
        self.stop_thread('Interaction')
        self.stop_thread('Scheduler')
        #del self.threads, self.workers
    '''
    
    def refresh_pet(self):
        # stop animation thread and start again
        self.stop_thread('Animation')
        self.stop_thread('Interaction')

        # Change status
        self.pet_hp.init_HP(settings.pet_data.hp, sys_hp_interval) #2)
        self.pet_fv.init_FV(settings.pet_data.fv, settings.pet_data.fv_lvl)

        # Change status related behavior
        #self.workers['Animation'].hpchange(settings.pet_data.hp_tier, None)
        #self.workers['Animation'].fvchange(settings.pet_data.fv_lvl)

        # Animation config data update
        settings.act_data._pet_refreshed(settings.pet_data.fv_lvl)
        self.refresh_acts.emit()

        # cancel default animation if any
        '''
        defaul_act = settings.defaultAct[self.curr_pet_name]
        if defaul_act is not None:
            self._set_defaultAct(self, defaul_act)
        self._update_fvlock()
        # add default animation back
        if defaul_act in [acti.text() for acti in self.defaultAct_menu.actions()]:
            self._set_defaultAct(self, defaul_act)
        '''

        # Update BackPack
        #self._init_Inventory()
        self.refresh_bag.emit()
        self._set_menu(self.pets)
        self._set_Statusmenu()
        self._set_tray()

        # restart animation and interaction
        self.runAnimation()
        self.runInteraction()
        
        # restore data system
        settings.pet_data.frozen_data = False

        # Compensate items if any
        self._setup_compensate()
    

    def _change_pet(self, pet_name: str) -> None:
        """
        改变宠物
        :param pet_name: 宠物名称
        :return:
        """
        if self.curr_pet_name == pet_name:
            return
        
        # close all accessory widgets (subpet, accessory animation, etc.)
        self.close_all_accs.emit()

        # stop animation thread and start again
        self.stop_thread('Animation')
        self.stop_thread('Interaction')

        # reload pet data
        settings.pet_data._change_pet(pet_name)

        # reload new pet
        self.init_conf(pet_name)

        # Change status
        self.pet_hp.init_HP(settings.pet_data.hp, sys_hp_interval) #2)
        self.pet_fv.init_FV(settings.pet_data.fv, settings.pet_data.fv_lvl)

        # Change status related behavior
        #self.workers['Animation'].hpchange(settings.pet_data.hp_tier, None)
        #self.workers['Animation'].fvchange(settings.pet_data.fv_lvl)

        # Update Backpack
        #self._init_Inventory()
        self.refresh_bag.emit()
        self.refresh_acts.emit()

        self.change_note.emit()
        self.repaint()
        self._setup_ui()

        self.runAnimation()
        self.runInteraction()

        self.workers['Scheduler'].send_greeting()
        # Compensate items if any
        self._setup_compensate()
        # Due to Qt internal behavior, sometimes has to manually correct the position back
        pos_x, pos_y = self.pos().x(), self.pos().y()
        QTimer.singleShot(10, lambda: self.move(pos_x, pos_y))

    def init_conf(self, pet_name: str) -> None:
        """
        初始化宠物窗口配置
        :param pet_name: 宠物名称
        :return:
        """
        self.curr_pet_name = pet_name
        settings.petname = pet_name
        settings.tunable_scale = settings.scale_dict.get(pet_name, 1.0)
        old_reactions = getattr(self, '_draconia_reactions', None)
        if old_reactions is not None:
            old_reactions.stop()
        self._draconia_reactions = None
        pic_dict = _load_all_pic(pet_name)
        self.pet_conf = PetConfig.init_config(self.curr_pet_name, pic_dict) #settings.size_factor)
        if pet_name == 'Draconia':
            from DyberPet.draconia_reactions import install_broom, make_qt_reactions
            install_broom(self.pet_conf)
            self._draconia_reactions = make_qt_reactions(
                self, Path(settings.BASEDIR or '.') / 'res/role/Draconia/note')
        
        self.margin_value = 0 #0.1 * max(self.pet_conf.width, self.pet_conf.height) # 用于将widgets调整到合适的大小
        # Add customized animation
        settings.act_data.init_actData(pet_name, settings.pet_data.hp_tier, settings.pet_data.fv_lvl)
        self._load_custom_anim()
        settings.pet_conf = self.pet_conf

        # Update coin name and image according to the pet config
        if self.pet_conf.coin_config:
            coin_config = self.pet_conf.coin_config.copy()
            if not coin_config['image']:
                coin_config['image'] = settings.items_data.default_coin['image']
            settings.items_data.coin = coin_config
        else:
            settings.items_data.coin = settings.items_data.default_coin.copy()

        # Init bubble behavior manager
        self.bubble_manager = BubbleManager()
        self.bubble_manager.register_bubble.connect(self.register_bubbleText)

        # Mia: cerebro local (Ollama). Si no está, el pet sigue con globos fijos.
        save_default_config()
        self.local_brain = LocalBrain(self)
        self.local_brain.reply.connect(self._on_mia_reply)
        self.local_brain.unavailable.connect(self._on_mia_brain_unavailable)
        self._mia_fallback_text = None

        # Mia: chat escrito (comportamiento 12). Memoria corta en proceso,
        # nunca se persiste a disco (contrato-chat.txt punto 6).
        self.mia_chat_history = ChatHistory()
        self.mia_chat_box = None

        # Mia: director de conducta (saluda/camina/mira al cursor/duerme...).
        from DyberPet.mia_director import (
            MiaDirector, load_director_config, load_mood_table, load_own_idle_poses,
        )
        director_cfg = load_director_config(self._mia_brain_path())
        # Mia: animo con continuidad (contrato mia-mood). Estado puro en
        # mia_mood.py, persistido en data/mia_mood.json; sin ese archivo
        # arranca en el estado default de siempre.
        from DyberPet.mia_mood import MoodEngine
        self.mia_mood = MoodEngine.load(self._mia_mood_path())
        self._mia_mood_dominant_seen = self.mia_mood.dominant
        self._mia_mood_table = load_mood_table(self._mia_brain_path())
        # perfil: pool de idle propio del personaje activo (contrato
        # MiniDraconia parte B punto 7); vacio para Mia/Kitty/ChrisKitty.
        self._mia_own_idle_poses = load_own_idle_poses(self._mia_brain_path())
        self._mia_director_profile_options = self._mia_profile_director_options()
        self.mia_director = MiaDirector(
            get_available_poses=self._mia_available_poses,
            play_action=self._mia_play_pose,
            # Mia: ni duerme ni cambia de pose mientras trepa (contrato trepar-paredes).
            is_busy=lambda: settings.draging == 1 or getattr(getattr(self, "mia_micro_ticker", None), "is_climbing", False) or (
                bool(self._mia_director_profile_options) and bool(getattr(self.workers.get('Interaction'), 'interact', None))),
            weights=director_cfg["weights"],
            sleep_after_s=director_cfg["sleep_after_s"],
            mood_table=self._mia_mood_table,
            get_dominant_mood=lambda: self.mia_mood.dominant,
            on_absence_return=lambda absence_s: self._mia_note_mood_event("zero_returns", absence_s=absence_s),
            on_mood_tick=self._mia_mood_tick,
            own_idle_poses=self._mia_own_idle_poses,
            **self._mia_director_profile_options,
        )
        self.mia_director.start()

        # Mia: guarda data/mia_mood.json cada minuto (contrato punto 6);
        # tambien se guarda al cerrar (quit()).
        self.mia_mood_save_timer = QTimer(self)
        self.mia_mood_save_timer.timeout.connect(self._mia_save_mood)
        self.mia_mood_save_timer.start(60_000)

        # Mia: microticker (parpadeo, mirar al cursor, patalear al cargarla,
        # bordes, hablar; comportamientos 5/7/8/9/10, B2 del informe revisor).
        from DyberPet.mia_director import MiaMicroTicker
        self._mia_chat_bubble_visible = False
        self._mia_cursor_flip = False
        self.mia_micro_ticker = MiaMicroTicker(
            get_context=self._mia_micro_context,
            play_action=self._mia_play_pose,
            apply_cursor_flip=self._mia_apply_cursor_flip,
            on_edge=self._mia_on_edge,
            rng=self.mia_director.rng,
            # Mia: trepar paredes (contrato trepar-paredes).
            climb_cfg=director_cfg.get("climb"),
            set_pos_y=lambda y: self.move(self.pos().x(), int(round(y))),
            on_climb_log=lambda msg: self._mia_log("climb", msg),
            allow_fall=lambda: bool(settings.set_fall),
            start_fall=self._mia_start_climb_fall,
            on_climb_top=lambda: self._mia_note_mood_event("climb_top"),
        )
        self.mia_micro_timer = QTimer(self)
        self.mia_micro_timer.timeout.connect(self.mia_micro_ticker.tick)
        self.mia_micro_timer.start(150)

        # Mia: charla espontánea con el modelo local cada 1.5–4 min (User: "no habla, solo saluda").
        self._mia_chatter_cfg = director_cfg.get("chatter", {}) if isinstance(director_cfg, dict) else {}
        self.mia_chatter_timer = QTimer(self)
        self.mia_chatter_timer.setSingleShot(True)
        self.mia_chatter_timer.timeout.connect(self._mia_chatter)
        self._mia_schedule_chatter(first=True)

        # Mia: voz en ingles (Kokoro bf_emma), apagada por defecto
        # (contrato-voz-en.md). Carga perezosa del modelo onnx: si Kokoro/
        # onnxruntime no estan instalados o el modelo no esta en disco,
        # MiaVoice.speak() es un no-op silencioso.
        from DyberPet.mia_voice import MiaVoice, KokoroEngine
        _kokoro_dir = Path(settings.BASEDIR or '.') / 'res' / 'voice' / 'kokoro'
        self._mia_voice_engine = KokoroEngine(
            model_path=_kokoro_dir / 'kokoro-v1.0.onnx',
            voices_path=_kokoro_dir / 'voices-v1.0.bin',
        )
        self.mia_voice = MiaVoice(
            engine=self._mia_voice_engine,
            tmp_dir=Path(settings.CONFIGDIR) / 'data' / 'tmp',
        )
        self.mia_voice._log_cb = self._mia_log  # Mia: bitácora de voz (suena / falla)

        self._set_menu(self.pets)
        self._set_Statusmenu()
        self._set_tray()


    def _load_custom_anim(self):
        acts_conf = settings.act_data.allAct_params[settings.petname]
        for act_name, act_conf in acts_conf.items():
            if act_conf['act_type'] == 'customized' and act_name not in self.pet_conf.custom_act:
                # generate new Act objects for cutomized animation
                acts = []
                for act in act_conf.get('act_list', []):
                    acts.append(self._prepare_act_obj(act))
                accs = []
                for act in act_conf.get('acc_list', []):
                    accs.append(self._prepare_act_obj(act))
                # save the new animation config with same format as self.pet_conf.accessory_act
                self.pet_conf.custom_act[act_name] = {"act_list": acts,
                                                      "acc_list": accs,
                                                      "anchor": act_conf.get('anchor_list',[]),
                                                      "act_type": act_conf['status_type']}

    def _prepare_act_obj(self, actobj):
        
        # if this act is a skipping act e.g. [60, 20]
        if len(actobj) == 2:
            return actobj
        else:
            act_conf_name = actobj[0]
            act_idx_start = actobj[1]
            act_idx_end = actobj[2]+1
            act_repeat_num = actobj[3]
            new_actobj = self.pet_conf.act_dict[act_conf_name].customized_copy(act_idx_start, act_idx_end, act_repeat_num)
            return new_actobj

    def updateList(self):
        self.workers['Animation'].update_prob()

    def _addNewAct(self, act_name):
        acts_config = settings.act_data.allAct_params[settings.petname]
        act_conf = acts_config[act_name]

        # Add to pet_conf
        acts = []
        for act in act_conf.get('act_list', []):
            acts.append(self._prepare_act_obj(act))
        accs = []
        for act in act_conf.get('acc_list', []):
            accs.append(self._prepare_act_obj(act))
        self.pet_conf.custom_act[act_name] = {"act_list": acts,
                                                "acc_list": accs,
                                                "anchor": act_conf.get('anchor_list',[]),
                                                "act_type": act_conf['status_type']}
        # update random action prob
        self.updateList()
        # Add to menu
        if act_conf['unlocked']:
            select_act = _build_act(act_name, self.act_menu, self._show_act)
            self.select_acts.append(select_act)
            self.act_menu.addAction(select_act)
    
    def _deleteAct(self, act_name):
        # delete from self.pet_config
        self.pet_conf.custom_act.pop(act_name)
        # update random action prob
        self.updateList()

        # delete from menu
        act_index = [acti.text() for acti in self.select_acts].index(act_name)
        self.act_menu.removeAction(self.select_acts[act_index])
        self.select_acts.remove(self.select_acts[act_index])


    def _setup_ui(self):

        #bar_width = int(max(100*settings.size_factor, 0.5*self.pet_conf.width))
        bar_width = int(max(100, 0.5*self.pet_conf.width))
        bar_width = int(min(200, bar_width))
        self.tomato_time.setFixedSize(bar_width, statbar_h-5)
        self.focus_time.setFixedSize(bar_width, statbar_h-5)

        self.reset_size(setImg=False)

        settings.previous_img = settings.current_img
        settings.current_img = self.pet_conf.default.images[0] #list(pic_dict.values())[0]
        settings.previous_anchor = [0, 0] #settings.current_anchor
        settings.current_anchor = [int(i*settings.tunable_scale) for i in self.pet_conf.default.anchor]
        self.set_img()
        self.border = self.pet_conf.width/2

        
        # 初始位置
        #screen_geo = QDesktopWidget().availableGeometry() #QDesktopWidget().screenGeometry()
        # Mia: posicion inicial centrada al 30% de la pantalla PRIMARIA real
        # (current_screen ya viene de QGuiApplication.primaryScreen(), ver
        # __init__), apoyada en el suelo de esa pantalla.
        from DyberPet.mia_director import primary_screen_start_pos, start_screen_and_frac
        # Mia (multimonitor): nace en cualquier pantalla y en cualquier punto (15-85 %),
        # no siempre al 30 % de la principal (User: "se queda a la izquierda").
        try:
            _scr, _frac = start_screen_and_frac(random.Random(), list(settings.screens), settings.current_screen)
            self.switch_screen(_scr)
            _area = _scr.availableGeometry()
        except Exception:
            _frac, _area = 0.3, self.current_screen
        x, y = primary_screen_start_pos(_area, self.width(), self.height(), width_frac=_frac)
        self.move(x,y)
        if settings.previous_anchor != settings.current_anchor:
            self.move(self.pos().x() - settings.previous_anchor[0] + settings.current_anchor[0],
                      self.pos().y() - settings.previous_anchor[1] + settings.current_anchor[1])
            #self.move(self.pos().x()-settings.previous_anchor[0]*settings.tunable_scale+settings.current_anchor[0]*settings.tunable_scale,
            #          self.pos().y()-settings.previous_anchor[1]*settings.tunable_scale+settings.current_anchor[1]*settings.tunable_scale)

    '''
    def eventFilter(self, object, event):
        return
    
        if event.type() == QEvent.Enter:
            self.status_frame.show()
            return True
        elif event.type() == QEvent.Leave:
            self.status_frame.hide()
        return False
    '''

    def _set_tray(self) -> None:
        """
        设置最小化托盘
        :return:
        """
        if self.audit_mode:
            return
        if self.tray is None:
            self.tray = SystemTray(self.StatMenu, self) #QSystemTrayIcon(self)
            self.tray.setIcon(QIcon(os.path.join(basedir, 'res/icons/icon.png')))
            self.tray.show()
        else:
            self.tray.setMenu(self.StatMenu)
            self.tray.show()

    def reset_size(self, setImg=True):
        #self.setFixedSize((max(self.pet_hp.width()+statbar_h,self.pet_conf.width)+self.margin_value)*max(1.0,settings.tunable_scale),
        #                  (self.margin_value+4*statbar_h+self.pet_conf.height)*max(1.0, settings.tunable_scale))
        self.setFixedSize( int(max(self.tomato_time.width()+statbar_h,self.pet_conf.width*settings.tunable_scale)),
                           int(2*statbar_h+self.pet_conf.height*settings.tunable_scale)
                         )

        #self.label.setFixedWidth(self.width())

        # 初始位置
        #screen_geo = QDesktopWidget().availableGeometry() #QDesktopWidget().screenGeometry()
        screen_width = self.screen_width #screen_geo.width()
        work_height = self.screen_height #screen_geo.height()
        x = self.pos().x() + settings.current_anchor[0]
        if settings.set_fall:
            y = self.current_screen.topLeft().y() + work_height-self.height()+settings.current_anchor[1]
        else:
            y = self.pos().y() + settings.current_anchor[1]
        # make sure that for all stand png, png bottom is the ground
        #self.floor_pos = work_height-self.height()
        self.floor_pos = self.current_screen.topLeft().y() + work_height - self.height()
        self.move(x,y)
        self.move_sig.emit(self.pos().x()+self.width()//2, self.pos().y()+self.height())

        if setImg:
            self.set_img()

    def set_img(self): #, img: QImage) -> None:
        """
        为窗体设置图片
        :param img: 图片
        :return:
        """
        #print(settings.previous_anchor, settings.current_anchor)
        if settings.previous_anchor != settings.current_anchor:
            self.move(self.pos().x()-settings.previous_anchor[0]+settings.current_anchor[0],
                      self.pos().y()-settings.previous_anchor[1]+settings.current_anchor[1])

        width_tmp = int(settings.current_img.width()*settings.tunable_scale)
        height_tmp = int(settings.current_img.height()*settings.tunable_scale)

        # HighDPI-compatible scaling solution
        # self.label.setScaledContents(True)
        self.label.setFixedSize(width_tmp, height_tmp)
        # Mia: mirar al cursor (comportamiento 5) - espejo horizontal del
        # frame default cuando el cursor esta cerca y el pet no esta
        # caminando (should_flip_to_cursor ya decide cuando aplica).
        img_to_show = settings.current_img
        # Mia: nunca espejar acciones con dirección propia (caminar, trepar, asomarse, seguir cursor):
        # el espejo pegado producía moonwalk (dibujo hacia un lado, desplazamiento hacia el otro).
        from DyberPet.mia_director import should_mirror_frame
        if should_mirror_frame(getattr(self, "_mia_cursor_flip", False),
                               getattr(settings, "anim_act", None), getattr(settings, "current_act", None)):
            img_to_show = img_to_show.transformed(QTransform().scale(-1, 1))
        self.label.setPixmap(img_to_show) #QPixmap.fromImage(settings.current_img))
        # previous scaling soluton
        #self.label.resize(width_tmp, height_tmp)
        #self.label.setPixmap(QPixmap.fromImage(settings.current_img.scaled(width_tmp, height_tmp,
        #                                                                 aspectMode=Qt.KeepAspectRatio,
        #                                                                 mode=Qt.SmoothTransformation)))
        self.image = img_to_show

    def _compensate_rewards(self):
        self.compensate_rewards.emit()
        # Mia: no notificar actualizaciones de upstream.

    def register_notification(self, note_type, message):
        self.setup_notification.emit(note_type, message)


    def register_bubbleText(self, bubble_dict:dict):
        self.setup_bubbleText.emit(bubble_dict, self.pos().x()+self.width()//2, self.pos().y()+self.height())

    def _mia_log(self, kind: str, text: str) -> None:
        """Bitácora local de lo que Mia pide y dice (data/mia_talk.log), para verificar."""
        try:
            import datetime
            with open(Path(settings.CONFIGDIR) / 'data' / 'mia_talk.log', 'a', encoding='utf-8') as fh:
                fh.write("%s %s %s\n" % (datetime.datetime.now().strftime("%H:%M:%S"), kind, text))
        except OSError:
            pass

    def _on_mia_brain_unavailable(self) -> None:
        """C3 revisión 2: si Ollama no responde, el saludo y los toques usan su globo fijo;
        la charla espontánea simplemente calla."""
        self._mia_log("falla", "Local model did not respond")
        text, self._mia_fallback_text = self._mia_fallback_text, None
        if text:
            self._emit_mia_bubble(text)

    def _mia_ask(self, prompt: str, fallback: Optional[str] = None) -> bool:
        self._mia_fallback_text = fallback
        # Mia: contrato-voz-en.md punto 2 -- con la voz activada se fuerza
        # el idioma a ingles (system_prompt_for_language ya cae al default
        # en ingles si no hay override en mia_brain.json).
        from DyberPet.mia_voice import load_voice_config, effective_language
        from DyberPet.local_brain import system_prompt_for_language
        voice_cfg = load_voice_config(self._mia_brain_path())
        lang = effective_language(self.local_brain.cfg.get("language", "en"),
                                   voice_cfg.get("enabled", False), voice_cfg.get("lang"))
        system_override = system_prompt_for_language(self.local_brain.cfg, lang)
        queued = self.local_brain.ask(prompt, system_override=system_override)
        if not queued:
            self._mia_fallback_text = None
        return queued

    def _on_mia_reply(self, text: str):
        self._mia_fallback_text = None
        from DyberPet.mia_director import clean_reply
        text = clean_reply(text)
        self._mia_log("dice", text or "(empty)")
        if text:
            self._emit_mia_bubble(text)
            # Mia: animo (contrato mia-mood punto 2) -- User chatea con ella.
            self._mia_note_mood_event("chat")

    # --- Mia: charla espontánea -------------------------------------------
    def _mia_schedule_chatter(self, first: bool = False) -> None:
        from DyberPet.mia_director import next_chatter_delay
        delay = 45.0 if first else next_chatter_delay(self.mia_director.rng, getattr(self, "_mia_chatter_cfg", {}))
        self.mia_chatter_timer.start(int(delay * 1000))

    def _mia_chatter(self) -> None:
        try:
            import datetime
            from DyberPet.mia_director import may_chatter, choose_chatter_prompt
            chat_open = self.mia_chat_box is not None and self.mia_chat_box.isVisible()
            inter = getattr(self.workers.get('Interaction'), 'interact', None)
            act_name = getattr(self.workers.get('Interaction'), 'act_name', None)
            asleep = (act_name == 'sleep') or getattr(self.mia_director, "is_asleep", False)
            if may_chatter(settings.onfloor, settings.draging, chat_open,
                           getattr(self, "_mia_chat_bubble_visible", False), asleep):
                pose = act_name if inter in ('actlist', 'customized') else None
                prompt = choose_chatter_prompt(self.mia_director.rng, datetime.datetime.now(), pose=pose)
                # Mia: animo (contrato mia-mood punto 5) -- si el globo lleva
                # >12s libre, el prompt lleva emocion/affection/eventos para
                # que la charla espontanea tenga continuidad.
                bubble_freed_at = getattr(self, "_mia_bubble_freed_at", 0.0)
                if time.time() - bubble_freed_at > 12.0:
                    mood_cfg = getattr(self, "mia_mood", None)
                    if mood_cfg is not None:
                        prompt = mood_cfg.mood_context_prompt() + " " + prompt
                queued = self._mia_ask(prompt)
                self._mia_log("pide" if queued else "ocupado", prompt)
            else:
                self._mia_log("calla", "not available")
        except Exception:
            logging.getLogger(__name__).exception("_mia_chatter fallo (silenciado)")
        finally:
            self._mia_schedule_chatter()

    def _emit_mia_bubble(self, text: str) -> None:
        """Emite un globo mia_chat ya con wrap_text + bubble_duration_s
        aplicados (contrato-chat.txt punto 4 / M1 del informe del revisor:
        antes ambas funciones se importaban pero nunca se usaban aqui)."""
        metrics = QFontMetrics(self.font())
        bubble_dict = build_mia_chat_bubble(text, metrics.horizontalAdvance)
        self.bubble_manager.register_bubble.emit(bubble_dict)
        # Mia: mientras el globo mia_chat esta en pantalla, el microticker
        # alterna 'talk'/'default' (comportamiento 9, B2 del informe revisor).
        self._mia_chat_bubble_visible = True
        # Mia: animo (contrato mia-mood punto 5) -- hora en que el globo
        # quedo libre, para saber si lleva >12s sin hablar.
        self._mia_bubble_freed_at = time.time() + bubble_dict["timeout"]
        QTimer.singleShot(int(bubble_dict["timeout"] * 1000), self._mia_clear_chat_bubble_flag)
        # Mia: voz en ingles (contrato-voz-en.md punto 1). Config se relee
        # en cada frase; si esta apagada, MiaVoice.speak() es un no-op.
        from DyberPet.mia_voice import load_voice_config
        voice_cfg = load_voice_config(self._mia_brain_path())
        if settings.petname != 'Draconia':
            self.mia_voice.speak(text, cfg=voice_cfg)
        if voice_cfg.get("enabled"):
            self._mia_log("voz", "pide Emma")

    def _draconia_bubble(self, text):
        # Local bubble only: bypass _emit_mia_bubble and its TTS.
        metrics = QFontMetrics(self.font())
        bubble = build_mia_chat_bubble(text, metrics.horizontalAdvance)
        self.bubble_manager.register_bubble.emit(bubble)

    def _draconia_react(self, event):
        if settings.petname != 'Draconia':
            return
        from DyberPet.mia_director import pose_allowed
        interaction = getattr(self.workers.get('Interaction'), 'interact', None)
        if event in {'head', 'cheek', 'body'} and not pose_allowed(
                'patpat', interaction, settings.onfloor, settings.draging):
            return
        controller = self._draconia_reactions
        kwargs = {'volume': settings.volume,
                  'muted': os.environ.get('MINIDRACONIA_MUTE') == '1' or settings.volume == 0}
        if event == 'drag':
            controller.drag(**kwargs)
            return
        pose = controller.react(event, getattr(self.mia_mood, 'dominant', 'content'),
                                self._mia_available_poses(), **kwargs)
        if pose:
            self._mia_play_pose(pose)

    def _s1_event(self, event):
        from DyberPet.brain import scripted_event
        line = scripted_event(event)
        if line:
            controller = getattr(self, '_draconia_reactions', None)
            now = time.monotonic()
            if controller is not None:
                if now - controller.last_time < controller.cooldown or controller.is_playing():
                    return
                controller.last_time = now
            self._draconia_bubble(line)

    def _mia_clear_chat_bubble_flag(self) -> None:
        self._mia_chat_bubble_visible = False

    # --- Mia: director de conducta (ganchos de pocas lineas) -----------------

    def _mia_available_poses(self) -> set:
        """Poses/acciones disponibles para el pet actual (claves de
        act_conf.json via pet_conf.act_dict), para que el director pueda
        caer a happy/default cuando falte una (comportamiento 11)."""
        return set(getattr(self.pet_conf, "act_dict", {}).keys())

    def _mia_profile_director_options(self) -> dict:
        """Opt-in estricto: Mia y perfiles heredados no cambian."""
        from DyberPet import char_profile
        from DyberPet.mia_director import load_combos
        data = Path(settings.CONFIGDIR) / 'data'
        if not char_profile.has_own_profile(data, settings.petname):
            return {}
        path = self._mia_brain_path()
        combos = load_combos(path)
        if not combos:
            return {}
        cfg = json.loads(path.read_text(encoding='utf-8'))
        return {'combos': combos, 'tick_range_s': cfg.get('director_tick_s', [8, 20])}

    def _mia_play_pose(self, pose_name: str) -> None:
        """Dispara una pose/accion por nombre si el motor la reconoce como
        accion random (act_data) o personalizada; si no la reconoce, no
        rompe nada (el director ya resolvio el fallback antes de llamar).

        B1 (informe revisor): nunca debe reventar ni entrar en bucle de
        error; cualquier excepcion se registra (log) y se descarta."""
        try:
            # Mia: nunca pisar arrastre/caída del motor (User: "se queda flotando").
            from DyberPet.mia_director import pose_allowed
            _inter = getattr(self.workers.get('Interaction'), 'interact', None) if hasattr(self, 'workers') else None
            if not pose_allowed(pose_name, _inter, settings.onfloor, settings.draging):
                return
            if pose_name == "follow_cursor":
                self._mia_start_follow_cursor()
                return
            acts_config = settings.act_data.allAct_params.get(settings.petname, {})
            if pose_name in acts_config:
                self.workers['Animation'].pause()
                self.workers['Interaction'].start_interact('actlist', pose_name)
            elif pose_name in getattr(self.pet_conf, "act_dict", {}):
                self.workers['Animation'].pause()
                self.workers['Interaction'].start_interact('customized', pose_name)
            else:
                return
            # Mia: platica por clip (contrato mia-mood punto 5) -- frase
            # instantanea de data/mia_lines.json al arrancar una pose "con
            # significado"; nunca pisa el globo de _mia_ask (zonas de toque
            # ya piden su propia frase al LLM con fallback fijo).
            self._mia_maybe_say_pose_line(pose_name)
            director = getattr(self, 'mia_director', None)
            if director is not None and director._combos:
                director.note_action(pose_name)
        except Exception:
            logging.getLogger(__name__).exception(
                "_mia_play_pose fallo (silenciado) para pose=%r", pose_name)

    _MIA_TOUCH_REACTION_POSES = ("patpat", "pinch", "touch_body")

    def _mia_maybe_say_pose_line(self, pose_name: str) -> None:
        """Contrato mia-mood punto 5: probabilidad (config, default 0.5;
        1.0 en reacciones a toques) de frase instantanea al arrancar una
        pose con significado. Nunca rompe nada si falta mia_lines.json."""
        if settings.petname == 'Draconia':
            return  # Reaction controller owns balloons, no duplicate pose emission.
        try:
            from DyberPet.mia_director import (
                MEANINGFUL_POSES, load_lines, pick_line, should_say_line,
            )
            if pose_name not in MEANINGFUL_POSES:
                return
            if getattr(self, "_mia_chat_bubble_visible", False):
                return  # no pisa un globo que ya esta en pantalla
            cfg = getattr(self, "_mia_mood_table", None)
            prob = 0.5
            try:
                brain_data = json.loads(self._mia_brain_path().read_text(encoding="utf-8"))
                prob = float(brain_data.get("mood_lines", {}).get("prob", 0.5))
            except Exception:
                pass
            is_touch = pose_name in self._MIA_TOUCH_REACTION_POSES
            if not should_say_line(self.mia_director.rng, is_touch, prob):
                return
            lines = load_lines(self._mia_lines_path())
            recent = getattr(self, "_mia_recent_lines", [])
            dominant = getattr(self.mia_mood, "dominant", "content")
            line = pick_line(lines, pose_name, dominant, recent, self.mia_director.rng)
            if not line:
                return
            self._mia_recent_lines = (recent + [line])[-5:]
            self._emit_mia_bubble(line)
        except Exception:
            logging.getLogger(__name__).exception("_mia_maybe_say_pose_line fallo (silenciado)")

    def _mia_start_follow_cursor(self) -> None:
        """Comportamiento 4: seguir el cursor 5-10s y parar solo
        (contrato-motor.md). Reusa MouseMoveManager/followTarget existente
        (follow_mouse_act, atado antes solo al menu)."""
        if settings.onfloor == 0 or settings.draging == 1:
            return
        from DyberPet.mia_director import choose_follow_duration
        self.MouseTracker = MouseMoveManager()
        self.MouseTracker.moved.connect(self.update_mouse_position)
        self.get_positions('mouse')
        self.workers['Animation'].pause()
        self.workers['Interaction'].start_interact('followTarget', 'mouse')
        duration_s = choose_follow_duration(self.mia_director.rng)
        QTimer.singleShot(int(duration_s * 1000), self._mia_stop_follow_cursor)

    def _mia_stop_follow_cursor(self) -> None:
        try:
            if getattr(self, "MouseTracker", None) is not None:
                self.MouseTracker._listener.stop()
            self.workers['Interaction'].stop_interact()
        except Exception:
            logging.getLogger(__name__).exception("_mia_stop_follow_cursor fallo (silenciado)")

    def _mia_micro_context(self) -> dict:
        """Contexto que lee MiaMicroTicker en cada tick corto (comportamientos
        5/7/8/9/10: mirar al cursor, patalear, bordes, hablar, parpadeo)."""
        interaction = self.workers.get('Interaction') if hasattr(self, 'workers') else None
        state = getattr(interaction, 'interact', None) or 'default'
        pet_center_x = self.pos().x() + self.width() // 2

        at_edge = None
        if getattr(self, 'current_screen', None) is not None:
            # Mia (multimonitor): solo cuentan los bordes de fuera del escritorio.
            from DyberPet.mia_director import outer_edge
            at_edge = outer_edge(list(settings.screens) if settings.screens else [self.current_screen],
                                 self.current_screen, self.pos().x(), self.width())

        # Mia: trepar paredes (contrato trepar-paredes). screen_top/height en
        # coordenadas logicas Qt de SU pantalla actual; pos_y/floor_y es el
        # tope del sprite hoy (si no esta trepando, floor_y == pos_y).
        # current_screen is already a QRect (availableGeometry at init, screen.geometry() on monitor switch).
        screen_rect = self.current_screen if getattr(self, 'current_screen', None) is not None else None
        screen_top = screen_rect.y() if screen_rect is not None else 0.0
        screen_height = screen_rect.height() if screen_rect is not None else 0.0

        return {
            "state": state,
            "pet_center_x": pet_center_x,
            "cursor_x": QCursor.pos().x(),
            "dragging": settings.draging == 1,
            "at_edge": at_edge,
            "chat_bubble_visible": getattr(self, "_mia_chat_bubble_visible", False),
            "chat_bubble_text": "",
            # Mia: gancho C2 (sueno de verdad) y C4 (peek con clip dedicado si existe).
            "sleeping": bool(getattr(self.mia_director, "is_asleep", False)),
            "available_poses": self._mia_available_poses(),
            "pos_y": float(self.pos().y()),
            "floor_y": float(self.pos().y()),
            "screen_top": float(screen_top),
            "screen_height": float(screen_height),
        }

    def _mia_apply_cursor_flip(self, flip: bool) -> None:
        """Comportamiento 5: voltea el frame default hacia el cursor. El
        flip real se aplica en set_img() (ganchos de pocas lineas) leyendo
        este flag."""
        self._mia_cursor_flip = flip

    def _mia_on_edge(self, side: str) -> None:
        """Comportamiento 8 (C4 informe revisor 2): notifica el toque de
        borde para bitacora. turn/peek ya los decide y dispara
        MiaMicroTicker._tick_edge (play_action/apply_cursor_flip), que es
        quien conoce el reloj inyectado y peek_duration(); duplicar la
        decision aqui con otro rng.uniform() desincronizaria la secuencia
        determinista que usan los tests."""
        self._mia_log("borde", side)

    # --- Mia: voz en ingles (contrato-voz-en.md) ----------------------------

    def _mia_brain_path(self) -> Path:
        # perfil: cada personaje activo busca su propio brain primero
        # (contrato MiniDraconia parte B, char_profile.py); Mia conserva
        # exactamente la ruta de siempre.
        from DyberPet import char_profile
        return char_profile.brain_path(Path(settings.CONFIGDIR) / 'data', settings.petname)

    # --- Mia: animo con continuidad (contrato mia-mood) ---------------------

    def _mia_mood_path(self) -> Path:
        # perfil: animo propio por personaje (contrato MiniDraconia parte B
        # punto 6); Mia conserva exactamente la ruta de siempre.
        from DyberPet import char_profile
        return char_profile.mood_path(Path(settings.CONFIGDIR) / 'data', settings.petname)

    def _mia_lines_path(self) -> Path:
        # perfil: frases instantaneas propias por personaje.
        from DyberPet import char_profile
        return char_profile.lines_path(Path(settings.CONFIGDIR) / 'data', settings.petname)

    def _mia_own_lines_or_none(self) -> Optional[dict]:
        """Lines del perfil propio del personaje activo, o None si no tiene
        uno (Mia/Kitty/ChrisKitty, contrato punto 8: sin cambios de
        comportamiento para ellos)."""
        from DyberPet import char_profile
        from DyberPet.mia_director import load_lines
        data_dir = Path(settings.CONFIGDIR) / 'data'
        if not char_profile.has_own_profile(data_dir, settings.petname):
            return None
        return load_lines(char_profile.lines_path(data_dir, settings.petname))

    def _mia_fallback_line(self, key: str) -> str:
        """LINES[key] (ingles) salvo que el personaje activo tenga sus
        propias frases (contrato punto 7: nunca en ingles para Draconia)."""
        from DyberPet.mia_director import fallback_line
        return fallback_line(key, self._mia_own_lines_or_none())

    def _mia_mood_touch_fallback(self, mood_pose: str) -> str:
        """Respaldo del toque con animo (B2, FAIL t_ea577267): antes
        DyberPet.py usaba MOOD_TOUCH_LINES (ingles fijo) sin mirar el
        perfil activo, asi que Draconia enojada/timida/aburrida con
        Ollama caido salia en ingles. Ahora prueba primero las lineas
        propias del perfil (p.ej. draconia_lines.json ya trae angry,
        shy, bored, peek, pinch); sin perfil propio (Mia/Kitty/
        ChrisKitty) cae exactamente a MOOD_TOUCH_LINES de siempre."""
        from DyberPet.mia_director import mood_touch_fallback_line
        return mood_touch_fallback_line(mood_pose, self._mia_own_lines_or_none())

    def _mia_save_mood(self) -> None:
        """Guarda data/mia_mood.json (contrato punto 6: cada minuto y al
        cerrar). Nunca rompe nada si el disco falla."""
        try:
            self.mia_mood.save(self._mia_mood_path())
        except Exception:
            logging.getLogger(__name__).exception("_mia_save_mood fallo (silenciado)")

    def _mia_note_mood_event(self, kind: str, **meta) -> None:
        """Registra un evento de animo (pat/touch_body/pinch/drag/fall/chat/
        climb_top/zero_returns) y deja constancia en mia_talk.log si cambia
        la emocion dominante (contrato punto 7: \"animo <emocion>\")."""
        try:
            new_dominant = self.mia_mood.record(kind, **meta)
            self._mia_handle_dominant_change(new_dominant)
        except Exception:
            logging.getLogger(__name__).exception("_mia_note_mood_event fallo (silenciado)")

    def _mia_mood_tick(self) -> None:
        """Aplica el decaimiento de MoodEngine con el paso del tiempo real
        (contrato mia-mood punto 1/2: aburrimiento por inactividad, energia
        de noche, decaimiento hacia la base), enganchado a MiaDirector.tick()
        (8-20 s, corre aunque el pet este dormido/ocupado/arrastrandose; a
        diferencia de un timer de 60 s, este sigue el mismo reloj que ya usa
        el director y no depende de un QTimer adicional). Deja constancia
        en mia_talk.log y en el menu igual que los eventos discretos."""
        try:
            new_dominant = self.mia_mood.tick()
            self._mia_handle_dominant_change(new_dominant)
        except Exception:
            logging.getLogger(__name__).exception("_mia_mood_tick fallo (silenciado)")

    def _mia_handle_dominant_change(self, new_dominant) -> None:
        """Bitacora + menu + clip visible cuando CAMBIA la dominante (fix
        B1, t_a82d63b9: \"cuando la dominante cambia a angry/shy/bored, el
        director reproduce ese clip una vez (con frase)\"); compartido por
        _mia_note_mood_event y _mia_mood_tick."""
        if not new_dominant or new_dominant == self._mia_mood_dominant_seen:
            return
        self._mia_mood_dominant_seen = new_dominant
        self._mia_log("animo", new_dominant)
        if getattr(self, "mia_mood_menu_entry", None) is not None:
            self.mia_mood_menu_entry.setText(self.tr("Mood: ") + new_dominant)
        from DyberPet.mia_director import should_play_mood_clip
        if should_play_mood_clip(new_dominant):
            self._mia_play_mood_clip(new_dominant)

    def _mia_play_mood_clip(self, dominant: str) -> None:
        """Reproduce el clip de `dominant` una vez, con frase garantizada
        (no al azar): si _mia_play_pose ya mostro una linea instantanea por
        probabilidad, no se duplica (fix B1, t_a82d63b9)."""
        try:
            self._mia_play_pose(dominant)
            if not getattr(self, "_mia_chat_bubble_visible", False):
                from DyberPet.mia_director import load_lines, pick_line
                lines = load_lines(self._mia_lines_path())
                recent = getattr(self, "_mia_recent_lines", [])
                line = pick_line(lines, dominant, dominant, recent, self.mia_director.rng)
                if line:
                    self._mia_recent_lines = (recent + [line])[-5:]
                    self._emit_mia_bubble(line)
        except Exception:
            logging.getLogger(__name__).exception("_mia_play_mood_clip fallo (silenciado)")

    def _toggle_mia_voice(self, checked: bool) -> None:
        """Menu del pet -> toggle de voz. Lee/escribe `voice.enabled` en
        mia_brain.json (la config se relee en cada frase, no hace falta
        reiniciar)."""
        from DyberPet.mia_voice import load_voice_config
        path = self._mia_brain_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        voice_cfg = load_voice_config(path)
        voice_cfg["enabled"] = bool(checked)
        data["voice"] = voice_cfg
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass
        if not checked:
            self.mia_voice.shutdown()

    def _mia_start_climb_fall(self) -> None:
        """Mia: se suelta de la pared y cae con la física de soltarla con el ratón
        (mismo camino que mouseReleaseEvent con set_fall), con un empujoncito
        hacia fuera de la pared."""
        side = getattr(getattr(self.mia_micro_ticker, "_climb", None), "side", None)
        settings.onfloor = 0
        settings.draging = 0
        settings.prefall = 1
        settings.dragspeedy = 0
        settings.dragspeedx = 1.5 if side == "left" else -1.5
        settings.fall_right = settings.dragspeedx > 0
        self.workers['Animation'].pause()
        self.workers['Interaction'].start_interact('mousedrag')

    def _toggle_mia_climb(self, checked: bool) -> None:
        """Menu del pet -> toggle "Climb walls" (contrato trepar-paredes).
        Lee/escribe `climb.enabled` en mia_brain.json y actualiza el
        MicroTicker en caliente (no hace falta reiniciar)."""
        from DyberPet.mia_director import load_climb_config
        path = self._mia_brain_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except (OSError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        climb_cfg = load_climb_config(path)
        climb_cfg["enabled"] = bool(checked)
        data["climb"] = climb_cfg
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass
        if hasattr(self, "mia_micro_ticker"):
            self.mia_micro_ticker._climb_cfg = climb_cfg

    def _mia_show_status_report(self) -> None:
        """Menu -> "Status report" (contrato-voz-en.md punto 3). Los datos
        se recogen en un hilo de fondo; el LLM solo redacta a partir de
        ese JSON exacto (nunca inventa cifras)."""
        from DyberPet.mia_status import collect_status_data, build_status_prompt
        from DyberPet.mia_voice import load_voice_config, effective_language

        def worker():
            data = collect_status_data()
            voice_cfg = load_voice_config(self._mia_brain_path())
            lang = effective_language(self.local_brain.cfg.get("language", "en"),
                                       voice_cfg.get("enabled", False), voice_cfg.get("lang"))
            return build_status_prompt(data, language=lang)

        thread = QThread(self)
        runner = _MiaChatWorker(worker)
        self._mia_status_runner = runner  # Mia: referencia viva, igual que en el chat escrito.
        runner.moveToThread(thread)
        thread.started.connect(runner.run)
        runner.finished.connect(self._mia_on_status_prompt_ready)
        runner.finished.connect(thread.quit)
        thread.finished.connect(runner.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._mia_status_thread = thread
        thread.start()

    def _mia_on_status_prompt_ready(self, prompt: str) -> None:
        greet_line = self._mia_fallback_line("greet")
        if not self._mia_ask(prompt, fallback=greet_line):
            self._emit_mia_bubble(greet_line)

    def _mia_show_briefing(self) -> None:
        """Menu -> "Today's briefing" (contrato-voz-en.md punto 4). Solo
        lectura de archivo local, sin red; un globo por parrafo."""
        from DyberPet.mia_status import read_briefing
        briefing_dir = Path(r"provided-assets")
        paragraphs = read_briefing(briefing_dir)
        self._mia_briefing_queue = list(paragraphs[1:])
        self._emit_mia_bubble(paragraphs[0])
        self._mia_briefing_last_text = paragraphs[0]
        self._mia_show_next_briefing_paragraph()

    def _mia_show_next_briefing_paragraph(self) -> None:
        queue = getattr(self, "_mia_briefing_queue", [])
        if not queue:
            return
        next_text = queue.pop(0)
        delay_ms = int(bubble_duration_s(self._mia_briefing_last_text) * 1000)

        def _show_it():
            self._emit_mia_bubble(next_text)
            self._mia_briefing_last_text = next_text
            self._mia_show_next_briefing_paragraph()

        QTimer.singleShot(delay_ms, _show_it)

    def _send_mia_greeting(self) -> None:
        """Comportamiento 2: anima greet/happy y pide a Ollama una frase de
        saludo; si Ollama no responde, globo fijo en espanol.

        Mia: contrato-voz-en.md punto 3 -- si `reports.morning` esta activo
        en mia_brain.json, el saludo dispara el status report en vez del
        saludo fijo de siempre."""
        if settings.petname == 'Draconia':
            self._mia_play_pose('greet')
            self._s1_event('greet')
            return
        self._mia_play_pose('greet')
        from DyberPet.mia_status import load_reports_config, mia_greeting_flow
        reports_cfg = load_reports_config(self._mia_brain_path())
        if mia_greeting_flow(reports_cfg) == "status":
            self._mia_show_status_report()
            return
        from DyberPet.mia_director import greeting_prompt
        from datetime import datetime as _dt
        greet_line = self._mia_fallback_line("greet")
        if not self._mia_ask(greeting_prompt(_dt.now()),
                             fallback=greet_line):
            self._emit_mia_bubble(greet_line)

    def _send_mia_bye(self) -> None:
        """Comportamiento 3: despedida al cerrar, globo fijo corto, no
        bloquea el cierre mas de 2.5 s (no llamamos a Ollama aqui: no hay
        tiempo garantizado de responder dentro del limite)."""
        if settings.petname == 'Draconia':
            self._mia_play_pose('bye')
            self._s1_event('bye')
            return
        self._mia_play_pose('bye')
        self._emit_mia_bubble(self._mia_fallback_line("bye"))

    # --- Mia: chat escrito (comportamiento 12, docs/contrato-chat.txt) ------

    def _open_mia_chat(self) -> None:
        if settings.petname == 'Draconia':
            return  # Scripted interactions only; no free-text UI.
        # Mia: abrir el chat cuenta como interaccion (comportamiento 4/12).
        self.mia_director.note_interaction()
        if self.mia_chat_box is not None and self.mia_chat_box.isVisible():
            self.mia_chat_box.setFocus()
            return
        self.mia_chat_box = ChatBox(self)
        self.mia_chat_box.message_sent.connect(self._on_mia_chat_sent)
        self.mia_chat_box.setFixedWidth(220)
        x = self.pos().x() + self.width() // 2 - self.mia_chat_box.width() // 2
        y = self.pos().y() - 40
        self.mia_chat_box.move(x, y)
        self.mia_chat_box.show()
        self.mia_chat_box.setFocus()

    def _on_mia_chat_sent(self, text: str) -> None:
        self._mia_play_pose('think')
        chat_cfg = load_chat_config(self._mia_brain_path())
        brain_cfg = self.local_brain.cfg
        # Mia: contrato-voz-en.md punto 2 -- con la voz activada se fuerza
        # el idioma a ingles tambien en el chat escrito.
        from DyberPet.mia_voice import load_voice_config, effective_language
        from DyberPet.local_brain import system_prompt_for_language
        voice_cfg = load_voice_config(self._mia_brain_path())
        lang = effective_language(brain_cfg.get("language", "en"),
                                   voice_cfg.get("enabled", False), voice_cfg.get("lang"))
        system_prompt = system_prompt_for_language(brain_cfg, lang)
        # Mia: el primer mensaje del chat puede pillar el modelo en frio
        # (keep_alive expirado); usa 45s de timeout esa vez, luego 20s.
        is_first_call = not getattr(self, "_mia_chat_had_first_reply", False)
        self._mia_chat_had_first_reply = True

        def worker():
            # brain: only explicit chat uses the configurable MiniDraconia provider.
            from DyberPet.brain import explicit_chat
            return explicit_chat(text, self.mia_chat_history.as_list())

        thread = QThread(self)
        runner = _MiaChatWorker(worker)
        self._mia_chat_runner = runner  # Mia: referencia viva (si no, Python lo recoge y el chat nunca responde)
        runner.moveToThread(thread)
        thread.started.connect(runner.run)
        runner.finished.connect(lambda reply: self._on_mia_chat_reply(text, reply))
        runner.finished.connect(thread.quit)
        thread.finished.connect(runner.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._mia_chat_thread = thread
        thread.start()

    def _on_mia_chat_reply(self, user_text: str, reply: str) -> None:
        self.mia_chat_history.add_turn(user_text, reply)
        self._emit_mia_bubble(reply)

    def _process_greeting_mssg(self, bubble_dict:dict):
        self.bubble_manager.add_usertag(bubble_dict, 'end', send=True)

    def register_accessory(self, accs):
        self.setup_acc.emit(accs, self.pos().x()+self.width()//2, self.pos().y()+self.height())


    def _change_status(self, status, change_value, from_mod='Scheduler', send_note=False):
        if status == 'hp' or from_mod in ('inventory', 'Buff'):
            return
        # Check system status
        if from_mod == 'Scheduler' and is_system_locked() and settings.auto_lock:
            print("System locked, skip HP and FV changes")
            return
        if status not in ['hp','fv']:
            return
        elif status == 'hp':
            
            diff = self.pet_hp.updateValue(change_value, from_mod)

        elif status == 'fv':
            
            diff = self.pet_fv.updateValue(change_value, from_mod)

        if send_note:

            if diff > 0:
                diff = '+%s'%diff
            elif diff < 0:
                diff = str(diff)
            else:
                return
            if status == 'hp':
                message = self.tr('Satiety') + " " f'{diff}'
            else:
                message = self.tr('Favorability') + " " f'{diff}' #'好感度 %s'%diff
            self.register_notification('status_%s'%status, message)
        
        # Periodically triggered events
        if status == 'hp' and from_mod == 'Scheduler': # avoid being called in both hp and fv
            # Random Bubble
            if random.uniform(0, 1) < settings.PP_BUBBLE:
                self.bubble_manager.trigger_scheduled()

            # Auto-Feed
            if settings.pet_data.hp <= settings.AUTOFEED_THRESHOLD*settings.HP_INTERVAL:
                self.autofeed.emit()

    def _hp_updated(self, hp):
        self.hp_updated.emit(hp)

    def _fv_updated(self, fv, fv_lvl):
        self.fv_updated.emit(fv, fv_lvl)


    def _change_time(self, status, timeleft):
        if status not in ['tomato','tomato_start','tomato_rest','tomato_end',
                          'focus_start','focus','focus_end','tomato_cencel','focus_cancel']:
            return

        if status in ['tomato','tomato_rest','tomato_end','focus','focus_end']:
            self.taskUI_Timer_update.emit()

        if status == 'tomato_start':
            self.tomato_time.setMaximum(25)
            self.tomato_time.setValue(timeleft)
            self.tomato_time.setFormat('%s min'%(int(timeleft)))
            #self.tomato_window.newTomato()
        elif status == 'tomato_rest':
            self.tomato_time.setMaximum(5)
            self.tomato_time.setValue(timeleft)
            self.tomato_time.setFormat('%s min'%(int(timeleft)))
            self.single_pomo_done.emit()
        elif status == 'tomato':
            self.tomato_time.setValue(timeleft)
            self.tomato_time.setFormat('%s min'%(int(timeleft)))
        elif status == 'tomato_end':
            self.tomato_time.setValue(0)
            self.tomato_time.setFormat('')
            #self.tomato_window.endTomato()
            self.taskUI_task_end.emit()
        elif status == 'tomato_cencel':
            self.tomato_time.setValue(0)
            self.tomato_time.setFormat('')

        elif status == 'focus_start':
            if timeleft == 0:
                self.focus_time.setMaximum(1)
                self.focus_time.setValue(0)
                self.focus_time.setFormat('%s min'%(int(timeleft)))
            else:
                self.focus_time.setMaximum(timeleft)
                self.focus_time.setValue(timeleft)
                self.focus_time.setFormat('%s min'%(int(timeleft)))
        elif status == 'focus':
            self.focus_time.setValue(timeleft)
            self.focus_time.setFormat('%s min'%(int(timeleft)))
        elif status == 'focus_end':
            self.focus_time.setValue(0)
            self.focus_time.setMaximum(0)
            self.focus_time.setFormat('')
            #self.focus_window.endFocus()
            self.taskUI_task_end.emit()
        elif status == 'focus_cancel':
            self.focus_time.setValue(0)
            self.focus_time.setMaximum(0)
            self.focus_time.setFormat('')

    def use_item(self, item_name):
        return  # Removed inventory/feeding signal entry point.
        # Check if it's pet-required item
        if item_name == settings.required_item:
            reward_factor = settings.FACTOR_FEED_REQ
            self.close_bubble.emit('feed_required')
        else:
            reward_factor = 1

        # 食物
        if settings.items_data.item_dict[item_name]['item_type']=='consumable':
            self.workers['Animation'].pause()
            self.workers['Interaction'].start_interact('use_item', item_name)
            self.bubble_manager.trigger_bubble('feed_done')

        # 附件物品
        elif item_name in self.pet_conf.act_name or item_name in self.pet_conf.acc_name:
            self.workers['Animation'].pause()
            self.workers['Interaction'].start_interact('use_clct', item_name)

        # 对话物品
        elif settings.items_data.item_dict[item_name]['item_type']=='dialogue':
            if item_name in self.pet_conf.msg_dict:
                accs = {'name':'dialogue', 'msg_dict':self.pet_conf.msg_dict[item_name]}
                x = self.pos().x() #+self.width()//2
                y = self.pos().y() #+self.height()
                self.setup_acc.emit(accs, x, y)
                return

        # 系统附件物品
        elif item_name in self.sys_conf.acc_name:
            accs = self.sys_conf.accessory_act[item_name]
            x = self.pos().x()+self.width()//2
            y = self.pos().y()+self.height()
            self.setup_acc.emit(accs, x, y)
        
        # Subpet
        elif settings.items_data.item_dict[item_name]['item_type']=='subpet':
            pet_acc = {'name':'subpet', 'pet_name':item_name}
            x = self.pos().x()+self.width()//2
            y = self.pos().y()+self.height()
            self.setup_acc.emit(pet_acc, x, y)
            return

        else:
            pass

        # 鼠标挂件 - currently gave up :(
        '''
        elif item_name in self.sys_conf.mouseDecor:
            accs = {'name':'mouseDecor', 'config':self.sys_conf.mouseDecor[item_name]}
            x = self.pos().x()+self.width()//2
            y = self.pos().y()+self.height()
            self.setup_acc.emit(accs, x, y)
        '''
        
        # 使用物品 改变数值
        self._change_status('hp', 
                            int(settings.items_data.item_dict[item_name]['effect_HP']*reward_factor),
                            from_mod='inventory', send_note=True)
        
        if item_name in self.pet_conf.item_favorite:
            self._change_status('fv',
                                int(settings.items_data.item_dict[item_name]['effect_FV']*self.pet_conf.item_favorite[item_name]*reward_factor),
                                from_mod='inventory', send_note=True)

        elif item_name in self.pet_conf.item_dislike:
            self._change_status('fv', 
                                int(settings.items_data.item_dict[item_name]['effect_FV']*self.pet_conf.item_dislike[item_name]*reward_factor),
                                from_mod='inventory', send_note=True)

        else:
            self._change_status('fv', 
                                int(settings.items_data.item_dict[item_name]['effect_FV']*reward_factor),
                                from_mod='inventory', send_note=True)

    def add_item(self, n_items, item_names=[]):
        return

    def patpat(self):
        if settings.petname == 'Draconia':
            from DyberPet.mia_director import detect_touch_zone
            point = getattr(self, '_mia_last_click_pos', None)
            point = self.label.mapFrom(self, point) if point is not None else None
            zone = detect_touch_zone(self.label.width(), self.label.height(),
                                     point.x(), point.y()) if point is not None else 'head'
            self._draconia_react(zone)
            return
        # 摸摸动画
        # Mia: zona de toque segun donde cayo el clic (comportamiento 6/B2):
        # cabeza -> patpat (igual que antes), mejilla/cuerpo -> pinch/touch_body
        # si la pose existe (si no, cae al comportamiento de cabeza de siempre).
        from DyberPet.mia_director import detect_touch_zone, TOUCH_ZONE_ACTIONS
        click_pos = getattr(self, "_mia_last_click_pos", None)
        zone = "head"
        if click_pos is not None and self.label.width() and self.label.height():
            zone = detect_touch_zone(self.label.width(), self.label.height(),
                                      click_pos.x(), click_pos.y())
        zone_info = TOUCH_ZONE_ACTIONS.get(zone, TOUCH_ZONE_ACTIONS["head"])
        zone_pose = zone_info["anim"]
        zone_prompt = zone_info["prompt"]

        if self.click_count >= 7:
            self.bubble_manager.trigger_bubble("pat_frequent")
        elif self.workers['Interaction'].interact != 'patpat':
            if settings.focus_timer_on:
                self.bubble_manager.trigger_bubble("pat_focus")
            else:
                # Mia: animo (fix B1, t_a82d63b9) -- se registra el evento
                # PRIMERO para que la pose y la frase de este mismo toque
                # reflejen el animo ya actualizado (asi la caricia que
                # ablanda angry se nota de inmediato, no un toque despues).
                mood_kind = "pinch" if zone == "cheek" else ("touch_body" if zone == "body" else "pat")
                self._mia_note_mood_event(mood_kind)
                mood_pose = self.mia_director.touch_mood_pose(zone)
                if mood_pose:
                    from DyberPet.mia_director import resolve_pose, MOOD_TOUCH_PROMPTS, MOOD_TOUCH_LINES
                    available = self._mia_available_poses() | set(
                        settings.act_data.allAct_params.get(settings.petname, {}).keys())
                    self._mia_play_pose(resolve_pose(mood_pose, available))
                    self._mia_ask(MOOD_TOUCH_PROMPTS.get(mood_pose, zone_prompt),
                                  fallback=self._mia_mood_touch_fallback(mood_pose))
                elif zone != "head" and zone_pose in getattr(self.pet_conf, "act_dict", {}).keys() | \
                        set(settings.act_data.allAct_params.get(settings.petname, {}).keys()):
                    self._mia_play_pose(zone_pose)
                    self._mia_ask(zone_prompt, fallback=self._mia_fallback_line("touch"))
                else:
                    self.workers['Animation'].pause()
                    self.workers['Interaction'].start_interact('patpat')
                    # Mia habla si Ollama está vivo; si no, el globo aleatorio de siempre.
                    self._mia_ask(zone_prompt, fallback=self._mia_fallback_line("pat"))

        # 概率触发浮动的心心
        prob_num_0 = random.uniform(0, 1)
        if prob_num_0 < sys_pp_heart:
            try:
                accs = self.sys_conf.accessory_act['heart']
            except:
                return
            x = QCursor.pos().x() #self.pos().x()+self.width()//2 + random.uniform(-0.25, 0.25) * self.label.width()
            y = QCursor.pos().y() #self.pos().y()+self.height()-0.8*self.label.height() + random.uniform(0, 1) * 10
            self.setup_acc.emit(accs, x, y)

        elif prob_num_0 < settings.PP_COIN:
            # Drop random amount of coins
            self.addCoins.emit(0)

        elif prob_num_0 > sys_pp_item:
            self.addItem_toInven.emit(1, [])
            #print('物品掉落！')

        if prob_num_0 > sys_pp_audio:
            #随机语音
            if random.uniform(0, 1) > 0.5:
                # This will be deprecated soon
                self.register_notification('random', '')
            else:
                self.bubble_manager.trigger_patpat_random()

    def item_drop_anim(self, item_name):
        return  # No reward icons, even through legacy signal callers.
        if item_name == 'coin':
            accs = {"name":"item_drop", "item_image":[settings.items_data.coin['image']]}
        else:
            item = settings.items_data.item_dict[item_name]
            accs = {"name":"item_drop", "item_image":[item['image']]}
        x = self.pos().x()+self.width()//2 + random.uniform(-0.25, 0.25) * self.label.width()
        y = self.pos().y()+self.height()-self.label.height()
        self.setup_acc.emit(accs, x, y)



    def quit(self) -> None:
        """
        关闭窗口, 系统退出
        :return:
        """
        # Mia: animo con continuidad (contrato mia-mood punto 6) -- guarda
        # data/mia_mood.json al cerrar, ademas del guardado cada minuto.
        self._mia_save_mood()
        # Mia: despedida corta (comportamiento 3). processEvents con tope de
        # 2.5 s para que el globo/anim alcancen a mostrarse sin bloquear el
        # cierre mas de eso.
        try:
            self._send_mia_bye()
            deadline = QElapsedTimer()
            deadline.start()
            while deadline.elapsed() < 1500:
                QApplication.processEvents()
                time.sleep(0.05)
        except Exception:
            pass
        settings.pet_data.save_data()
        settings.pet_data.frozen()
        self.stop_thread('Animation')
        self.stop_thread('Interaction')
        self.stop_thread("Scheduler")
        self.stopAllThread.emit()
        self.close()
        sys.exit()

    def stop_thread(self, module_name):
        if module_name not in self.workers:
            return
        self.workers[module_name].kill()
        self.threads[module_name].terminate()
        self.threads[module_name].wait()
        #self.threads[module_name].wait()

    def follow_mouse_act(self):
        sender = self.sender()
        if settings.onfloor == 0:
            return
        if sender.text()==self.tr("Follow Cursor"):
            sender.setText(self.tr("Stop Follow"))
            self.MouseTracker = MouseMoveManager()
            self.MouseTracker.moved.connect(self.update_mouse_position)
            self.get_positions('mouse')
            self.workers['Animation'].pause()
            self.workers['Interaction'].start_interact('followTarget', 'mouse')
        else:
            sender.setText(self.tr("Follow Cursor"))
            self.MouseTracker._listener.stop()
            self.workers['Interaction'].stop_interact()

    def get_positions(self, object_name):

        main_pos = [int(self.pos().x() + self.width()//2), int(self.pos().y() + self.height() - self.label.height())]

        if object_name == 'mouse':
            self.send_positions.emit(main_pos, self.mouse_pos)

    def update_mouse_position(self, x, y):
        self.mouse_pos = [x, y]

    def stop_trackMouse(self):
        self.start_follow_mouse.setText(self.tr("Follow Cursor"))
        self.MouseTracker._listener.stop()

    '''
    def fall_onoff(self):
        #global set_fall
        sender = self.sender()
        if settings.set_fall==1:
            sender.setText(self.tr("Don't Drop"))
            sender.setIcon(QIcon(os.path.join(basedir,'res/icons/off.svg')))
            settings.set_fall=0
        else:
            sender.setText(self.tr("Allow Drop"))
            sender.setIcon(QIcon(os.path.join(basedir,'res/icons/on.svg')))
            settings.set_fall=1
    '''

    def _show_controlPanel(self):
        self.show_controlPanel.emit()

    def fall_onoff(self):
        settings.set_fall = not settings.set_fall
        self.switch_fall.setText(self.tr('Allow Drop') if settings.set_fall else self.tr("Don't Drop"))
        settings.save_settings()

    def _show_dashboard(self):
        self.show_dashboard.emit()

    '''
    def show_compday(self):
        sender = self.sender()
        if sender.text()=="显示陪伴天数":
            acc = {'name':'compdays', 
                   'height':self.label.height(),
                   'message': "这是%s陪伴你的第 %i 天"%(settings.petname,settings.pet_data.days)}
            sender.setText("关闭陪伴天数")
            x = self.pos().x() + self.width()//2
            y = self.pos().y() + self.height() - self.label.height() - 20 #*settings.size_factor
            self.setup_acc.emit(acc, x, y)
            self.showing_comp = 1
        else:
            sender.setText("显示陪伴天数")
            self.setup_acc.emit({'name':'compdays'}, 0, 0)
            self.showing_comp = 0
    '''

    def show_tomato(self):
        if self.tomato_window.isVisible():
            self.tomato_window.hide()

        else:
            self.tomato_window.move(max(self.current_screen.topLeft().y(),self.pos().x()-self.tomato_window.width()//2),
                                    max(self.current_screen.topLeft().y(),self.pos().y()-self.tomato_window.height()))
            self.tomato_window.show()

        '''
        elif self.tomato_clock.text()=="取消番茄时钟":
            self.tomato_clock.setText("番茄时钟")
            self.workers['Scheduler'].cancel_tomato()
            self.tomatoicon.hide()
            self.tomato_time.hide()
        '''

    def run_tomato(self, nt):
        self.workers['Scheduler'].add_tomato(n_tomato=int(nt))
        self.tomatoicon.show()
        self.tomato_time.show()
        settings.focus_timer_on = True

    def cancel_tomato(self):
        self.workers['Scheduler'].cancel_tomato()

    def change_tomato_menu(self):
        self.tomatoicon.hide()
        self.tomato_time.hide()
        settings.focus_timer_on = False

    
    def show_focus(self):
        if self.focus_window.isVisible():
            self.focus_window.hide()
        
        else:
            self.focus_window.move(max(self.current_screen.topLeft().y(),self.pos().x()-self.focus_window.width()//2),
                                   max(self.current_screen.topLeft().y(),self.pos().y()-self.focus_window.height()))
            self.focus_window.show()


    def run_focus(self, task, hs, ms):
        if task == 'range':
            if hs<=0 and ms<=0:
                return
            self.workers['Scheduler'].add_focus(time_range=[hs,ms])
        elif task == 'point':
            self.workers['Scheduler'].add_focus(time_point=[hs,ms])
        self.focusicon.show()
        self.focus_time.show()
        settings.focus_timer_on = True

    def pause_focus(self, state):
        if state: # 暂停
            self.workers['Scheduler'].pause_focus()
        else: # 继续
            self.workers['Scheduler'].resume_focus(int(self.focus_time.value()), int(self.focus_time.maximum()))


    def cancel_focus(self):
        self.workers['Scheduler'].cancel_focus(int(self.focus_time.maximum()-self.focus_time.value()))

    def change_focus_menu(self):
        self.focusicon.hide()
        self.focus_time.hide()
        settings.focus_timer_on = False


    def show_remind(self):
        if self.remind_window.isVisible():
            self.remind_window.hide()
        else:
            self.remind_window.move(max(self.current_screen.topLeft().y(),self.pos().x()-self.remind_window.width()//2),
                                    max(self.current_screen.topLeft().y(),self.pos().y()-self.remind_window.height()))
            self.remind_window.show()

    ''' Reminder function deleted from v0.3.7
    def run_remind(self, task_type, hs=0, ms=0, texts=''):
        if task_type == 'range':
            self.workers['Scheduler'].add_remind(texts=texts, time_range=[hs,ms])
        elif task_type == 'point':
            self.workers['Scheduler'].add_remind(texts=texts, time_point=[hs,ms])
        elif task_type == 'repeat_interval':
            self.workers['Scheduler'].add_remind(texts=texts, time_range=[hs,ms], repeat=True)
        elif task_type == 'repeat_point':
            self.workers['Scheduler'].add_remind(texts=texts, time_point=[hs,ms], repeat=True)
    '''

    def show_inventory(self):
        if self.inventory_window.isVisible():
            self.inventory_window.hide()
        else:
            self.inventory_window.move(max(self.current_screen.topLeft().y(), self.pos().x()-self.inventory_window.width()//2),
                                    max(self.current_screen.topLeft().y(), self.pos().y()-self.inventory_window.height()))
            self.inventory_window.show()
            #print(self.inventory_window.size())

    '''
    def show_settings(self):
        if self.setting_window.isVisible():
            self.setting_window.hide()
        else:
            #self.setting_window.move(max(self.current_screen.topLeft().y(), self.pos().x()-self.setting_window.width()//2),
            #                        max(self.current_screen.topLeft().y(), self.pos().y()-self.setting_window.height()))
            #self.setting_window.resize(800,800)
            self.setting_window.show()
    '''

    '''
    def show_settingstest(self):
        self.settingUI = SettingMainWindow()
        
        if sys.platform == 'win32':
            self.settingUI.setWindowFlags(
                Qt.FramelessWindowHint | Qt.SubWindow | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint)
        else:
            self.settingUI.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint)
        self.settingUI.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        cardShadowSE = QtWidgets.QGraphicsDropShadowEffect(self.settingUI)
        cardShadowSE.setColor(QColor(189, 167, 165))
        cardShadowSE.setOffset(0, 0)
        cardShadowSE.setBlurRadius(20)
        self.settingUI.setGraphicsEffect(cardShadowSE)
        
        self.settingUI.show()
    '''

    def runAnimation(self):
        # Create thread for Animation Module
        self.threads['Animation'] = QThread()
        self.workers['Animation'] = Animation_worker(self.pet_conf)
        self.workers['Animation'].moveToThread(self.threads['Animation'])

        # Connect signals and slots
        self.threads['Animation'].started.connect(self.workers['Animation'].run)
        self.workers['Animation'].sig_setimg_anim.connect(self.set_img)
        self.workers['Animation'].sig_move_anim.connect(self._move_customized)
        self.workers['Animation'].sig_repaint_anim.connect(self.repaint)
        self.workers['Animation'].acc_regist.connect(self.register_accessory)

        # Start the thread
        self.threads['Animation'].start()
        self.threads['Animation'].setTerminationEnabled()


    def hpchange(self, hp_tier, direction):
        return  # No native animation or notification may react to hunger.

    def fvchange(self, fv_lvl):
        if fv_lvl == -1:
            self.fvlvl_changed_main_note.emit(fv_lvl)
        else:
            self.workers['Animation'].fvchange(fv_lvl)
            self.fvlvl_changed_main_note.emit(fv_lvl)
            self.fvlvl_changed_main_inve.emit(fv_lvl)
            self._update_fvlock()
            self.lvl_badge.set_level(fv_lvl)
        self.refresh_acts.emit()
        self.bubble_manager.trigger_bubble(bb_type="fv_lvlup")

    def runInteraction(self):
        # Create thread for Interaction Module
        self.threads['Interaction'] = QThread()
        self.workers['Interaction'] = Interaction_worker(self.pet_conf)
        self.workers['Interaction'].moveToThread(self.threads['Interaction'])

        # Connect signals and slots
        self.workers['Interaction'].sig_setimg_inter.connect(self.set_img)
        self.workers['Interaction'].sig_move_inter.connect(self._move_customized)
        self.workers['Interaction'].sig_act_finished.connect(self.resume_animation)
        self.workers['Interaction'].sig_interact_note.connect(self.register_notification)
        self.workers['Interaction'].acc_regist.connect(self.register_accessory)
        self.workers['Interaction'].query_position.connect(self.get_positions)
        self.workers['Interaction'].stop_trackMouse.connect(self.stop_trackMouse)
        self.send_positions.connect(self.workers['Interaction'].receive_pos)

        # Start the thread
        self.threads['Interaction'].start()
        self.threads['Interaction'].setTerminationEnabled()

    def runScheduler(self):
        # Create thread for Scheduler Module
        self.threads['Scheduler'] = QThread()
        self.workers['Scheduler'] = Scheduler_worker()
        self.workers['Scheduler'].moveToThread(self.threads['Interaction'])

        # Connect signals and slots
        self.threads['Scheduler'].started.connect(self.workers['Scheduler'].run)
        self.workers['Scheduler'].sig_settext_sche.connect(self.register_notification) #_set_dialogue_dp)
        self.workers['Scheduler'].sig_setact_sche.connect(self._show_act)
        self.workers['Scheduler'].sig_setstat_sche.connect(self._change_status)
        self.workers['Scheduler'].sig_focus_end.connect(self.change_focus_menu)
        self.workers['Scheduler'].sig_tomato_end.connect(self.change_tomato_menu)
        self.workers['Scheduler'].sig_settime_sche.connect(self._change_time)
        self.workers['Scheduler'].sig_addItem_sche.connect(self.add_item)
        self.workers['Scheduler'].sig_setup_bubble.connect(self._process_greeting_mssg)

        # Start the thread
        self.threads['Scheduler'].start()
        self.threads['Scheduler'].setTerminationEnabled()



    def _move_customized(self, plus_x, plus_y):

        #print(act_list)
        #direction, frame_move = str(act_list[0]), float(act_list[1])
        pos = self.pos()
        new_x = pos.x() + plus_x
        new_y = pos.y() + plus_y

        # 正在下落的情况，可以切换屏幕
        if settings.onfloor == 0:
            # 落地情况
            if new_y > self.floor_pos+settings.current_anchor[1]:
                settings.onfloor = 1
                new_x, new_y = self.limit_in_screen(new_x, new_y)
            # 在空中
            else:
                anim_area = QRect(self.pos() + QPoint(self.width()//2-self.label.width()//2, 
                                                      self.height()-self.label.height()), 
                                  QSize(self.label.width(), self.label.height()))
                intersected = self.current_screen.intersected(anim_area)
                area = intersected.width() * intersected.height() / self.label.width() / self.label.height()
                if area > 0.5:
                    pass
                    #new_x, new_y = self.limit_in_screen(new_x, new_y)
                else:
                    switched = False
                    for screen in settings.screens:
                        if screen.geometry() == self.current_screen:
                            continue
                        intersected = screen.geometry().intersected(anim_area)
                        area_tmp = intersected.width() * intersected.height() / self.label.width() / self.label.height()
                        if area_tmp > 0.5:
                            self.switch_screen(screen)
                            switched = True
                    if not switched:
                        new_x, new_y = self.limit_in_screen(new_x, new_y)

        # 正在做动作的情况，局限在当前屏幕内
        else:
            # Mia (multimonitor): si al caminar el centro pasa a otra pantalla, cambia de
            # pantalla en vez de chocar contra la costura y quedarse en la principal.
            from DyberPet.mia_director import neighbor_screen
            _nb = neighbor_screen(list(settings.screens) if settings.screens else [],
                                  self.current_screen, new_x + self.width() // 2, new_y + self.height() - 5)
            if _nb is not None:
                from DyberPet.mia_director import entry_center_x
                _from = self.current_screen
                self.switch_screen(_nb)
                new_x = entry_center_x(_from, self.current_screen) - self.width() // 2
                new_y = self.floor_pos + settings.current_anchor[1]
                self._mia_log("pantalla", "cruza a %s" % _nb.name())
            new_x, new_y = self.limit_in_screen(new_x, new_y, on_action=True)

        self.move(new_x, new_y)


    def switch_screen(self, screen):
        self.current_screen = screen.geometry()
        settings.current_screen = screen
        self.screen_geo = screen.availableGeometry() #screenGeometry()
        self.screen_width = self.screen_geo.width()
        self.screen_height = self.screen_geo.height()
        self.floor_pos = self.current_screen.topLeft().y() + self.screen_height -self.height()


    def limit_in_screen(self, new_x, new_y, on_action=False):
        # 超出当前屏幕左边界
        if new_x+self.width()//2 < self.current_screen.topLeft().x():
            #surpass_x = 'Left'
            new_x = self.current_screen.topLeft().x()-self.width()//2
            if not on_action:
                settings.dragspeedx = -settings.dragspeedx * settings.SPEED_DECAY
                settings.fall_right = not settings.fall_right

        # 超出当前屏幕右边界
        elif new_x+self.width()//2 > self.current_screen.topLeft().x() + self.screen_width:
            #surpass_x = 'Right'
            new_x = self.current_screen.topLeft().x() + self.screen_width-self.width()//2
            if not on_action:
                settings.dragspeedx = -settings.dragspeedx * settings.SPEED_DECAY
                settings.fall_right = not settings.fall_right

        # 超出当前屏幕上边界
        if new_y+self.height()-self.label.height()//2 < self.current_screen.topLeft().y():
            #surpass_y = 'Top'
            new_y = self.current_screen.topLeft().y() + self.label.height()//2 - self.height()
            if not on_action:
                settings.dragspeedy = abs(settings.dragspeedy) * settings.SPEED_DECAY

        # 超出当前屏幕下边界
        elif new_y > self.floor_pos+settings.current_anchor[1]:
            #surpass_y = 'Bottom'
            new_y = self.floor_pos+settings.current_anchor[1]

        return new_x, new_y


    def _show_act(self, act_name):
        self.workers['Animation'].pause()
        self.workers['Interaction'].start_interact('actlist', act_name)
    '''
    def _show_acc(self, acc_name):
        self.workers['Animation'].pause()
        self.workers['Interaction'].start_interact('anim_acc', acc_name)
    '''
    def _set_defaultAct(self, act_name):

        if act_name == settings.defaultAct[self.curr_pet_name]:
            settings.defaultAct[self.curr_pet_name] = None
            settings.save_settings()
            for action in self.defaultAct_menu.menuActions():
                if action.text() == act_name:
                    action.setIcon(QIcon(os.path.join(basedir, 'res/icons/dot.png')))
        else:
            for action in self.defaultAct_menu.menuActions():
                if action.text() == settings.defaultAct[self.curr_pet_name]:
                    action.setIcon(QIcon(os.path.join(basedir, 'res/icons/dot.png')))
                elif action.text() == act_name:
                    action.setIcon(QIcon(os.path.join(basedir, 'res/icons/dotfill.png'))) #os.path.join(basedir, 'res/icons/check_icon.png')))

            settings.defaultAct[self.curr_pet_name] = act_name
            settings.save_settings()


    def resume_animation(self):
        self.workers['Animation'].resume()
    
    def _mightEventTrigger(self):
        # Update date
        settings.pet_data.update_date()
        # Update companion days
        daysText = self.tr(" (Fed for ") + str(settings.pet_data.days) +\
                   self.tr(" days)")
        self.daysLabel.setText(daysText)




def _load_all_pic(pet_name: str) -> dict:
    """
    加载宠物所有动作图片
    :param pet_name: 宠物名称
    :return: {动作编码: 动作图片}
    """
    img_dir = os.path.join(basedir, 'res/role/{}/action/'.format(pet_name))
    images = os.listdir(img_dir)
    return {image.split('.')[0]: _get_q_img(img_dir + image) for image in images}

def _get_q_img(img_path: str) -> QPixmap:
    """
    将图片路径加载为 QPixmap
    :param img_path: 图片路径
    :return: QPixmap
    """
    #image = QImage()
    image = QPixmap()
    image.load(img_path)
    return image

def _build_act(name: str, parent: QObject, act_func, icon=None) -> Action:
    """
    构建改变菜单动作
    :param pet_name: 菜单动作名称
    :param parent 父级菜单
    :param act_func: 菜单动作函数
    :return:
    """
    if icon:
        act = Action(icon, name, parent)
    else:
        act = Action(name, parent)
    act.triggered.connect(lambda: act_func(name))
    return act

def _build_act_param(name: str, param: str, parent: QObject, act_func) -> Action:
    """
    构建改变菜单动作
    :param pet_name: 菜单动作名称
    :param parent 父级菜单
    :param act_func: 菜单动作函数
    :return:
    """
    act = Action(name, parent)
    act.triggered.connect(lambda: act_func(param))
    return act


