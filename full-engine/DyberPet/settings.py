import os
import json
import ctypes
from sys import platform
from collections import defaultdict

from PySide6.QtGui import QImage, QPixmap
from DyberPet.conf import PetData, TaskData, ActData, ItemData
from PySide6 import QtCore

from DyberPet.paths import resource_root, user_root, initialize_user_data
from DyberPet.version import read_version
basedir = str(resource_root())
BASEDIR = basedir
configdir = str(user_root())
CONFIGDIR = configdir

DEFAULT_THEME_COL = "#009faa"

HELP_URL = "https://github.com/ChaozhongLiu/DyberPet/issues"
PROJECT_URL = "https://github.com/ChaozhongLiu/DyberPet"
DEVDOC_URL = "https://github.com/ChaozhongLiu/DyberPet/blob/main/docs/art_dev.md"
# Version comes from the single VERSION file; the label is what users see.
VERSION = read_version(basedir)
VERSION_LABEL = "MiniDraconia " + VERSION
PUBLIC_URL = ""
AUTHOR = "https://github.com/ChaozhongLiu"
CHARCOLLECT_LINK = "https://github.com/ChaozhongLiu/DyberPet/blob/main/docs/collection.md"
ITEMCOLLECT_LINK = "https://github.com/ChaozhongLiu/DyberPet/blob/main/docs/collection.md"
PETCOLLECT_LINK = "https://github.com/ChaozhongLiu/DyberPet/blob/main/docs/collection.md"

# Upstream update check endpoints were removed: they pointed at the upstream
# DyberPet releases, which are not this product's releases. Nothing called them.

HP_TIERS = [0,50,80,100]
TIER_NAMES = ['Starving', 'Hungry', 'Normal', 'Energetic']
HP_INTERVAL = 2
LVL_BAR_V1 = [20, 120, 300, 600, 1200, 1800, 2400, 3200]
LVL_BAR = [20] + [120]*200
PP_HEART = 0.8
PP_COIN = 0.9
COIN_MU = 10
COIN_SIGMA = 5
PP_ITEM = 0.95
PP_AUDIO = 0.8
PP_BUBBLE = 0.15

# Depreciation when sell item to shop
ITEM_DEPRECIATION = 0.75

# Coin reward once a task is checked from Task Panel
SINGLETASK_REWARD = 200
# Coin reward every 5 task
FIVETASK_REWARD = 1500
# Multiply HP and FV effect if item is required by bubble `feed_required`
FACTOR_FEED_REQ = 5

HUNGERSTR = "Satiety"
FAVORSTR = "Favorability"

LINK_PERMIT = {"BiliBili":"https://space.bilibili.com/",
               "微博":"https://m.weibo.cn/profile/",
               "抖音": "https://www.douyin.com/user/",
               "GitHub":"https://github.com/",
               "爱发电":"https://afdian.net/a/",
               "TikTok":"https://www.tiktok.com/",
               "YouTube":"https://www.youtube.com/"}

ITEM_BGC = {'consumable': '#EFEBDF',
            'collection': '#e1eaf4',
            'Empty': '#f0f0ef',
            'dialogue': '#e1eaf4',
            'subpet': '#f6eae9',
            'autofeed': '#e7f1e4'}
ITEM_BGC_DEFAULT = '#EFEBDF'
ITEM_BDC = '#B1C790'

# when falling met the screen boundary, 
# it will be bounced back with this speed decay factor
SPEED_DECAY = 0.5
AUTOFEED_THRESHOLD = 60

def init():
    initialize_user_data()
    # computer system ==================================================
    global platform
    platform = platform

    # check if data directory exists ===================================
    newpath = os.path.join(configdir, 'data')
    if not os.path.exists(newpath):
        os.makedirs(newpath)
    
    global pet_conf
    pet_conf = None

    # Image and animation related variable =============================
    global current_img, previous_img
    # Make img-to-show a global variable for multi-thread behaviors
    current_img = None #QPixmap()
    previous_img = None #Pixmap()
    global current_anchor, previous_anchor
    current_anchor = [0,0]
    previous_anchor = [0,0]

    global onfloor, draging, set_fall, playid
    global mouseposx1,mouseposx2,mouseposx3,mouseposx4,mouseposx5
    global mouseposy1,mouseposy2,mouseposy3,mouseposy4,mouseposy5
    global dragspeedx,dragspeedy,fixdragspeedx, fixdragspeedy, fall_right, gravity, prefall
    # Drag and fall related global variable
    onfloor = 1
    draging = 0
    set_fall = True # default is allow drag
    playid = 0
    mouseposx1,mouseposx2,mouseposx3,mouseposx4,mouseposx5=0,0,0,0,0
    mouseposy1,mouseposy2,mouseposy3,mouseposy4,mouseposy5=0,0,0,0,0
    dragspeedx,dragspeedy=0,0
    fixdragspeedx, fixdragspeedy = 1.0, 1.0
    fall_right = False
    gravity = 0.1
    prefall = 0

    global act_id, current_act, previous_act
    # Select animation to show
    act_id = 0
    current_act, previous_act = None, None
    global anim_act
    anim_act = None  # Mia: acto que pinta Animation_worker (para no espejar caminatas)

    global showing_dialogue_now
    showing_dialogue_now = False

    # size settings
    global size_factor, screen_scale, font_factor, status_margin, statbar_h, tunable_scale
    try:
        size_factor = 1.0 #ctypes.windll.shcore.GetScaleFactorForDevice(0) / 100
    except:
        size_factor = 1.0
    tunable_scale = 1.0

    # buff related arguments
    global HP_stop, FV_stop
    HP_stop = False
    FV_stop = False

    # sound volumn =====================================================
    global volume
    volume = 0.4

    # pet name =========================================================
    global petname
    petname = ''

    # which screen =====================================================
    global screens, current_screen
    screens = []
    current_screen = None

    # Always on top ====================================================
    global on_top_hint, pets
    on_top_hint = True

    # Translations ====================================================
    global lang_dict
    lang_dict = json.load(open(os.path.join(basedir, 'res/language/language.json'), 'r', encoding='UTF-8'))

    # Settings =========================================================
    pets = get_petlist(os.path.join(basedir, 'res/role'))
    init_settings()
    global default_pet
    if default_pet not in pets:
        default_pet = pets[0]
    else:
        pets.remove(default_pet)
        pets.sort()
        pets = [default_pet] + pets
    save_settings()

    # Focus Timer
    global focus_timer_on
    focus_timer_on = False

    # Load in pet data ================================================
    global pet_data 
    pet_data = PetData(pets)

    # Load in task data ================================================
    global task_data 
    task_data = TaskData()

    # Init animation config data ================================================
    global act_data 
    act_data = ActData(pets)

    # Load in Language Choice ==========================================
    global language_code, translator
    change_translator(language_code)

    # Load in items data ==========================================
    global items_data, required_item
    items_data = None
    required_item = None



'''
def init_pet():
    global pet_data 
    pet_data = PetData()
    init_settings()
    save_settings()
'''


def init_settings():
    global file_path, settingGood
    file_path = os.path.join(configdir, 'data/settings.json')

    global gravity, fixdragspeedx, fixdragspeedy, tunable_scale, scale_dict, volume, \
           language_code, on_top_hint, default_pet, defaultAct, themeColor, minipet_scale, \
           toaster_on, usertag_dict, auto_lock, bubble_on, max_throw_speed

    # check json file integrity
    try:
        json.load(open(file_path, 'r', encoding='UTF-8'))
        settingGood = True
    except:
        if os.path.isfile(file_path):
            settingGood = False
        else:
            settingGood = True

    if os.path.isfile(file_path) and settingGood:
        data_params = json.load(open(file_path, 'r', encoding='UTF-8'))

        fixdragspeedx, fixdragspeedy = data_params['fixdragspeedx'], data_params['fixdragspeedy']
        gravity = data_params['gravity']
        max_throw_speed = data_params.get('max_throw_speed', 2.0)
        #tunable_scale = data_params['tunable_scale']
        volume = data_params['volume']
        language_code = data_params.get('language_code', QtCore.QLocale().name())
        on_top_hint = data_params.get('on_top_hint', True)
        default_pet = data_params.get('default_pet', pets[0])
        defaultAct = data_params.get('defaultAct', {})
        themeColor = data_params.get('themeColor', None)

        # Fix a bug version distributed to users =============
        if defaultAct is None:
            defaultAct = {}
        elif type(defaultAct) == str:
            defaultAct = {}

        for pet in pets:
            defaultAct[pet] = defaultAct.get(pet, None)
        #=====================================================

        # update for app <= v0.2.2 ===========================
        if language_code == 'CN':
            language_code = QtCore.QLocale().name()
        #=====================================================

        # v0.4.8 update ======================================
        global set_fall
        set_fall = data_params.get('set_fall', True)
        #=====================================================

        # v0.5.0 update ======================================
        # First time open v0.5.0, get the original 
        # tunable_scale as all default
        tunable_scale = data_params.get('tunable_scale', 1.0)
        # v0.5.0 tunable_scales are specified for each character
        scale_dict_tmp = data_params.get('scale_dict', {})
        scale_dict = {}
        for pet in pets:
            pet_scale = scale_dict_tmp.get(pet, tunable_scale)
            # Ensure type is int
            try:
                pet_scale = float(pet_scale)
            except:
                pet_scale = 1.0
            pet_scale = max( 0, min(5, pet_scale) )
            scale_dict[pet] = pet_scale
        tunable_scale = scale_dict[default_pet]

        # mini-pet scale settings
        minipet_scale = data_params.get('minipet_scale', defaultdict(dict))
        minipet_scale = check_dict_datatype(minipet_scale, dict, {})
        minipet_scale = defaultdict(dict, minipet_scale)
        for minipet, sdict in minipet_scale.items():
            minipet_scale[minipet] = check_dict_datatype(sdict, float, 1.0)
        #=====================================================

        # v0.5.3 Toaster can be turned off
        toaster_on = data_params.get('toaster_on', True)
        #=====================================================

        # v0.6.1 User Tag (how pet will call the user)
        usertag_dict_tmp = data_params.get('usertag_dict', {})
        usertag_dict = {}
        for pet in pets:
            usertag = usertag_dict_tmp.get(pet, '')
            usertag_dict[pet] = usertag

        # v0.6.5 stop HP & FV changes when screen locked
        auto_lock = data_params.get('auto_lock', False)
        #=====================================================

        # v0.6.7 Bubble can be turned off
        bubble_on = data_params.get('bubble_on', True)
        #=====================================================

    else:
        fixdragspeedx, fixdragspeedy = 1.0, 1.0
        gravity = 0.1
        # lanzamiento: 2 px/tick (100 px/s a 20 ms). Con gravedad 0.1 y
        # caida de 1080 px, incluso tirando hacia arriba recorre <340 px:
        # menos de 1/3 de una pantalla de 1280 px. Gravedades menores o
        # pantallas atipicas requieren ajustar esta clave en settings.json.
        max_throw_speed = 2.0
        volume = 0.5
        language_code = QtCore.QLocale().name()
        on_top_hint = True
        default_pet = pets[0]
        defaultAct = {}
        themeColor = None
        for pet in pets:
            defaultAct[pet] = defaultAct.get(pet, None)
        scale_dict = {}
        for pet in pets:
            scale_dict[pet] = 1.0
        tunable_scale = 1.0
        minipet_scale = defaultdict(dict)
        toaster_on = True
        bubble_on = True
        usertag_dict = {}
        auto_lock = False
    check_locale()
    save_settings()

def save_settings():
    global file_path, set_fall, gravity, fixdragspeedx, fixdragspeedy, scale_dict, volume, \
           language_code, on_top_hint, default_pet, defaultAct, themeColor, minipet_scale, \
           toaster_on, usertag_dict, auto_lock, bubble_on, max_throw_speed

    data_js = {'gravity':gravity,
               'max_throw_speed':max_throw_speed,
               'set_fall': set_fall,
               'fixdragspeedx':fixdragspeedx,
               'fixdragspeedy':fixdragspeedy,
               'usertag_dict':usertag_dict,
               'scale_dict':scale_dict,
               'minipet_scale':minipet_scale,
               'volume':volume,
               'on_top_hint':on_top_hint,
               'toaster_on':toaster_on,
               'bubble_on':bubble_on,
               'default_pet':default_pet,
               'defaultAct':defaultAct,
               'language_code':language_code,
               'themeColor':themeColor,
               'auto_lock':auto_lock
               }

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data_js, f, ensure_ascii=False, indent=4)

def get_petlist(dirname):
    folders = os.listdir(dirname)
    pets = []
    # subpets = []
    # v0.3.3 subpet now moved to folder: res/pet/
    for folder in folders:
        folder_path = os.path.join(dirname, folder)
        if folder != 'sys' and os.path.isdir(folder_path):
            pets.append(folder)
            #conf_path = os.path.join(folder_path, 'pet_conf.json')
            #conf = dict(json.load(open(conf_path, 'r', encoding='UTF-8')))
            #subpets += [i for i in conf.get('subpet',{}).keys()]
    pets = list(set(pets))
    #subpets = list(set(subpets))
    #for subpet in subpets:
    #    pets.remove(subpet)
    return pets

def change_translator(language_code):
    global translator
    translator = None

def check_locale():
    global language_code
    language_code = 'en_US'
            

def check_dict_datatype(raw_dict:dict, dtype, default_value):
    """
    Checks the datatype of values in a dictionary. If a value does not match the specified datatype, it is replaced with a default value.

    Parameters:
    raw_dict (dict): The dictionary to check.
    dtype (type): The expected datatype for the values.
    default_value: The value to replace if the datatype does not match.

    Returns:
    dict: A new dictionary with corrected datatypes.
    """
    return {k: (v if isinstance(v, dtype) else default_value) for k, v in raw_dict.items()}

