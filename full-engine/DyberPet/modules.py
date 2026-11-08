import sys
from sys import platform
import time
import math
import uuid
import types
import random
import inspect
from typing import List
from datetime import datetime, timedelta

from apscheduler.schedulers.qt import QtScheduler
from apscheduler.triggers import interval, date, cron

from PySide6.QtCore import Qt, QTimer, QObject, QPoint
from PySide6.QtGui import QImage, QPixmap, QIcon, QCursor, QAction, QTransform
from PySide6.QtWidgets import *
from PySide6.QtCore import QObject, QThread, Signal

from DyberPet.utils import *
from DyberPet.conf import *
from DyberPet.frames import prefetch_frames


import DyberPet.settings as settings
basedir = settings.BASEDIR

# system config
sys_hp_tiers = settings.HP_TIERS #[0,50,80,100] #Line 48, 289
sys_nonDefault_prob = [1, 0.125, 0.25, 0.5] #Line 50


def frame_step(act, direction=None, scale=None):
    """(dx, dy) logical pixels the window moves for one displayed frame of `act`.

    `frame_move` is in sprite pixels per frame (the ground speed of the planted foot, see
    scripts/measure_sprite_motion.py); on screen the sprite is drawn at the pet's display
    scale, so the step is scaled the same way or she skates (M3: "she walks in place")."""
    direction = direction or getattr(act, 'direction', None)
    if scale is None:
        scale = getattr(settings, 'pet_display_scale', 1.0)
    step = float(getattr(act, 'frame_move', 0) or 0) * float(scale)
    return {'right': (step, 0.), 'left': (-step, 0.), 'up': (0., -step), 'down': (0., step)}.get(direction, (0., 0.))


FOLLOW_STUCK_FRAMES = 4
# M3.2: any walk (director, follow, the random animation) whose steps the screen edge clamps to
# zero this many frames in a row ends; she never walks in place against a wall.
WALK_STUCK_FRAMES = 4


def follow_blocked(trail, x):
    """True when the last FOLLOW_STUCK_FRAMES walk frames left her at the same x (a wall)."""
    return bool(trail) and len(trail) >= FOLLOW_STUCK_FRAMES and all(v == x for v in trail)


def wall_side(x, width, screen_left, screen_width, margin=1):
    """'left'/'right' when the pet window touches that edge as `PetWidget.limit_in_screen`
    clamps it (window centre on the screen edge), else None."""
    centre = int(x) + int(width) // 2
    if centre <= screen_left + margin:
        return 'left'
    if centre >= screen_left + screen_width - margin:
        return 'right'
    return None


def is_walk(act):
    """A clip that moves her sideways (walk cycles, also while following the cursor)."""
    return bool(getattr(act, 'need_move', False)) and getattr(act, 'direction', None) in ('left', 'right')


def walk_with_room(act, walk_room, pet_conf, idle_picker=None):
    """D2.3: the random animation's walk `act` under the director's rule
    (companion_director.choose_walk_direction). `walk_room()` is the room the pet publishes from the UI
    thread ({'left': px, 'right': px}); this thread never reads the widget. The walk keeps its
    direction if one full walk fits that way, else turns to the other side if a walk fits there;
    with room on neither side it becomes one of her idle clips (`idle_picker`), else her stand."""
    from DyberPet.companion_director import walk_distance, walkable_sides
    try:
        room = walk_room()
    except Exception:
        return act
    if not room:
        return act
    other = pet_conf.right if act.direction == 'left' else pet_conf.left
    other_side = 'right' if act.direction == 'left' else 'left'
    scale = getattr(settings, 'pet_display_scale', 1.0)
    need = {act.direction: walk_distance([act], scale),
            other_side: walk_distance([other], scale) if is_walk(other) else float('inf')}
    sides = walkable_sides(room, need)
    if act.direction in sides:
        return act
    if sides:
        return other
    if idle_picker is not None:
        try:
            idle = getattr(pet_conf, 'act_dict', {}).get(idle_picker())
        except Exception:
            idle = None
        if isinstance(idle, Act):
            return idle
    return pet_conf.default


class WalkTracker:
    """One walk at a time (M3.2): frames moved, real dx and steps the screen edge clamped to zero.

    `step()` returns True when the last WALK_STUCK_FRAMES steps were all clamped (the walk must
    end); `end()` returns the diagnostic line once, then forgets the walk."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.pose = None
        self.source = None
        self.dx = 0
        self.frames = 0
        self.clamped = 0
        self._stuck_run = 0

    @property
    def active(self):
        return self.pose is not None

    def begin(self, pose, source):
        self.reset()
        self.pose, self.source = pose, source

    def step(self, requested_dx, moved_dx):
        self.frames += 1
        self.dx += int(moved_dx)
        if int(requested_dx) != 0 and int(moved_dx) == 0:
            self.clamped += 1
            self._stuck_run += 1
        else:
            self._stuck_run = 0
        return self._stuck_run >= WALK_STUCK_FRAMES

    def end(self):
        if not self.active:
            return None
        line = 'end %s dx=%d frames=%d clamped=%d' % (self.pose, self.dx, self.frames, self.clamped)
        self.reset()
        return line


# Clips the random pool never swaps for an idle pose (M3.2). D2.2: 'yawn' opens her random
# Sleep act (yawn -> doze -> sleep); it is never an idle pose of its own.
NOT_IDLE_CLIPS = ('default', 'yawn', 'doze', 'sleep', 'drag', 'fall', 'onfloor', 'climb', 'climb_down',
                  'patpat')


def due_frame(started_at, now, frame_s, shown=-1):
    """Index of the frame a clip started at `started_at` (monotonic seconds) must show at `now`
    (M3.2): the schedule is `started_at + k * frame_s`, so a late tick neither delays nor
    stretches the frames after it. Never goes back, and never repeats `shown`."""
    if frame_s <= 0:
        return shown + 1
    due = int((now - started_at) / frame_s + 1e-9)
    return max(due, shown + 1)


# M3.3: a line never cuts a clip mid-way. The clip playing when a line arrives goes on to its end
# if that comes within FINISH_CLIP_S; otherwise it stops at its next natural point (the end of a
# step, or of a repetition of its images) within FINISH_CLIP_S, and if there is none, at
# FINISH_CLIP_S. A walk stops at the end of its current step (`step_ends` markers, measured by
# scripts/measure_sprite_motion.py); a walk without step markers stops at once.
FINISH_CLIP_S = 2.5


def natural_points(act, after, upto):
    """Frame indexes b, after < b <= upto, at which `act` may stop without cutting a movement: the
    frame after each step marker (`step_ends`: the last frame of a step, both feet planted) and
    the end of every repetition of its images. Indexes count on across repetitions."""
    images = getattr(act, 'images', None)
    n = len(images) if images is not None else 0
    if n <= 0 or upto <= after:
        return []
    marks = sorted({int(m) + 1 for m in (getattr(act, 'step_ends', None) or ()) if 0 <= int(m) < n} | {n})
    out = []
    lap = max(0, int(after) // n)
    while lap * n < upto:
        for m in marks:
            b = lap * n + m
            if after < b <= upto:
                out.append(b)
        lap += 1
    return out


def yield_time(started, now, frame_s, deadline, total=None, points=()):
    """When a clip that started at `started` (frame k due at started + k * frame_s) lets a line
    take over (M3.3): its end (`total` frames; None for a looping clip) if that comes by
    `deadline`, else the first natural point (frame index in `points`) due from `now` to
    `deadline`, else `deadline`. Never before `now`."""
    if frame_s <= 0:
        return now
    if total is not None:
        end = started + total * frame_s
        if end <= deadline + 1e-9:
            return max(now, end)
    for b in sorted(points):
        t = started + b * frame_s
        if now - 1e-9 <= t <= deadline + 1e-9:
            return t
    return max(now, deadline)


def is_stand(act, pet_conf):
    """Her stand clip (the pet's `default`): a line never waits for it, talk starts from it."""
    default = getattr(pet_conf, 'default', None)
    return act is not None and default is not None and \
        getattr(act, 'act_name', None) == getattr(default, 'act_name', object())


def yields_at_once(act, pet_conf):
    """A line takes over at once from her stand and from a walk with no step markers."""
    return is_stand(act, pet_conf) or (is_walk(act) and not getattr(act, 'step_ends', None))


def scaled_anchor(anchor, scale=None):
    """An action's anchor (sprite pixels) in logical pixels at the pet's on-screen scale
    (`settings.pet_display_scale`: the Pet Scale, capped so frames are never upscaled)."""
    if scale is None:
        scale = getattr(settings, 'pet_display_scale', 1.0)
    return [int(i * float(scale)) for i in anchor]


def ticks_per_frame(frame_refresh, tick_ms):
    """Interaction-timer ticks one frame of a clip stays on screen (whole ticks, at least 1).
    M3.1: a 21 ms tick (pet_conf interact_speed) divides 1/12 s frames into 4 ticks, so
    clips play at about 12 fps instead of 10 (5 ticks of 20 ms)."""
    tick_s = float(tick_ms) / 1000.0
    if tick_s <= 0:
        return 1
    return max(1, math.ceil(round(float(frame_refresh) / tick_s, 6)))


##############################
#       Animation Module
##############################

class Animation_worker(QObject):
    sig_setimg_anim = Signal(name='sig_setimg_anim')
    sig_move_anim = Signal(float, float, name='sig_move_anim')
    sig_repaint_anim = Signal()
    acc_regist = Signal(dict, name='acc_regist')
    sig_walk_done = Signal(name='sig_walk_done')     # M3.2: a walk clip ended (or was cut)
    sig_clip_released = Signal(name='sig_clip_released')   # M3.3: finished its clip for a line

    def __init__(self, pet_conf, parent=None):
        """
        Animation Module
        Display user-defined animations randomly
        :param pet_conf: PetConfig class object in Main Widgets

        """
        super(Animation_worker, self).__init__(parent)
        self.pet_conf = pet_conf
        self.hp_cut_off = sys_hp_tiers #[0,50,80,100]
        self.current_status = [settings.pet_data.hp_tier,settings.pet_data.fv_lvl] #self._cal_status_type()
        self.nonDefault_prob_list = sys_nonDefault_prob #[1, 0.05, 0.125, 0.25]
        self.nonDefault_prob = self.nonDefault_prob_list[self.current_status[0]]
        self.act_cmlt_prob = self._cal_prob(self.current_status)
        self.is_killed = False
        self.is_paused = False
        # M3.2: frame pacing from a monotonic clock; injectable for tests.
        self._clock = time.monotonic
        self._sleep = time.sleep
        self._skip = False
        # M3.2 (set by the pet): which wall she touches ('left'/'right'/None), and the shared
        # idle chooser (her own clips, never one of the last 3) for random idle clips.
        self.wall_side = None
        self.idle_picker = None
        # D2.3 (set by the pet): her room toward each side, {'left': px, 'right': px} or None.
        self.walk_room = None
        # M3.3: a line is waiting for the clip being played (finish_clip): absolute deadline and
        # the time the clip lets the line take over (computed on the playing thread).
        self._finish_deadline = None
        self._yield_at = None


    def run(self):
        """Run animation in a separate thread"""
        print('start running pet %s'%(self.pet_conf.petname))
        time.sleep(5)
        while not self.is_killed:
            #if self.is_hp:
            #    print(self.is_hp, self.is_fv)
            if getattr(self, '_finish_deadline', None) is not None:
                self._release_clip()        # a line arrived between two clips: it goes first
            else:
                self.random_act()

            while self.is_paused:
                time.sleep(0.2)
            if self.is_killed:
                break

            #time.sleep(self.pet_conf.refresh)
    
    def kill(self):
        self.is_paused = False
        self.is_killed = True

    def pause(self):
        self.is_paused = True
        self._finish_deadline = None

    def resume(self):
        self.is_paused = False
        self._finish_deadline = None

    def skip_clip(self):
        """M3.2: end the clip being played now (a walk stuck against a wall); the next random
        decision follows."""
        self._skip = True

    # --- M3.3: a line never cuts the random animation's clip mid-way --------------------------
    @property
    def finishing(self):
        """True while the clip being played finishes for a line (it has not paused yet)."""
        return getattr(self, '_finish_deadline', None) is not None and not self.is_paused \
            and not self.is_killed

    def finish_clip(self, grace_s=FINISH_CLIP_S):
        """A line arrived: play the current clip to its end or natural point (`yield_time`), at
        most `grace_s` from now, then pause and emit `sig_clip_released`. Never extends a
        deadline already running."""
        if self.is_paused or self.is_killed or getattr(self, '_finish_deadline', None) is not None:
            return
        self._yield_at = None
        self._finish_deadline = getattr(self, '_clock', time.monotonic)() + float(grace_s)

    def cancel_finish(self):
        """The line ended before the clip did: the clip and the random life just go on."""
        self._finish_deadline = None
        self._yield_at = None

    def _release_clip(self):
        self._finish_deadline = None
        self._yield_at = None
        self.is_paused = True
        self.sig_clip_released.emit()

    def _clip_yield(self, act, started, now, shown, deadline):
        """When the clip `act` (started at `started`, frame `shown` on screen) lets the line in."""
        if yields_at_once(act, self.pet_conf):
            return now                      # her stand, or a walk with no step markers
        frame_s = float(act.frame_refresh)
        total = len(act.images) * act.act_num
        upto = total if frame_s <= 0 else min(total, int((deadline - started) / frame_s) + 1)
        return yield_time(started, now, frame_s, deadline, total, natural_points(act, shown, upto))

    def update_prob(self):
        self.current_status = [settings.pet_data.hp_tier,settings.pet_data.fv_lvl] #self._cal_status_type()
        self.nonDefault_prob = self.nonDefault_prob_list[self.current_status[0]]
        self.act_cmlt_prob = self._cal_prob(self.current_status)

    def _cal_prob(self, current_status):
        act_conf = settings.act_data.allAct_params[settings.petname]
        act_name = [ k for k,v in act_conf.items() ]
        act_prob = [ act_conf[k]['act_prob'] for k in act_name ] #self.pet_conf.act_prob
        act_type = [ act_conf[k]['status_type'] for k in act_name ]
        act_unlocked = [ act_conf[k]['unlocked'] for k in act_name ]
        act_inlist = [ act_conf[k]['in_playlist'] for k in act_name ]

        #if v['in_playlist'] and v['status_type'][1]<= current_status[1]

        new_prob = []
        for i in range(len(act_name)):
            if not act_unlocked[i]:
                new_prob.append(0)
                continue

            if (current_status[0] == 0) and (act_type[i][0] != 0):
                new_prob.append(0)
                
            elif current_status[1] < act_type[i][1]:
                new_prob.append(0)

            elif act_type[i][0] == 0:
                new_prob.append(act_prob[i] * int(current_status[0] == 0))

            else:
                new_prob.append(act_prob[i] * (1/4)**(abs(act_type[i][0]-current_status[0])) * int(act_inlist[i]))

        if sum(new_prob) != 0:
            new_prob = [i/sum(new_prob) for i in new_prob]
            #print(new_prob)
            total = 0
            act_cmlt_prob = []
            for i in range(len(new_prob)):
                total += new_prob[i]
                act_cmlt_prob.append(total)
            act_cmlt_prob[-1] = 1.0
        else:
            act_cmlt_prob = [0] * len(new_prob)

        act_cmlt_prob = [round(i,3) for i in act_cmlt_prob]
        #print(act_name)
        #print(act_cmlt_prob)
        return act_cmlt_prob

        

    def hpchange(self, hp_tier, direction):
        self.current_status[0] = int(hp_tier)
        self.act_cmlt_prob = self._cal_prob(self.current_status)
        self.nonDefault_prob = self.nonDefault_prob_list[self.current_status[0]]
        #print('animation module is aware of the hp tier change!')

    def fvchange(self, fv_lvl):
        self.current_status[1] = int(fv_lvl)
        settings.act_data._pet_refreshed(fv_lvl)
        self.act_cmlt_prob = self._cal_prob(self.current_status)
        self.nonDefault_prob = self.nonDefault_prob_list[self.current_status[0]]
        #print('animation module is aware of the fv lvl change! %i'%fv_lvl)

    

    def random_act(self) -> None:
        """
        随机执行动作
        :return:
        """
        acts = None
        accs = None
        # If HP type is not starving, this condition also makes sure only starving animation is played

        # If under focus timer, play focus animation
        if settings.focus_timer_on and self.pet_conf.focus:
            acts = [self.pet_conf.focus]

        # If there is only 1 animation, select the default animation mode
        elif set(self.act_cmlt_prob) == set([0,1]):
            act_idx = sum([i < 1.0 for i in self.act_cmlt_prob])
            act_name = list(settings.act_data.allAct_params[settings.petname].keys())[act_idx]
            acts, accs = self._get_acts(act_name)

        # Else random animation mode
        else:
            prob_num_0 = random.uniform(0, 1)
            # Random animation not selected, play default
            if prob_num_0 > self.nonDefault_prob:
                acts = [self.pet_conf.default]
            # Random animation selected
            else:
                prob_num = random.uniform(0, 1)
                act_idx = sum([ i < prob_num for i in self.act_cmlt_prob])
                # In some situation, no animation is selected (e.g., there is no random animation)
                if act_idx >= len(self.act_cmlt_prob):
                    acts = [self.pet_conf.default]
                else:
                    act_name = list(settings.act_data.allAct_params[settings.petname].keys())[act_idx]
                    acts, accs = self._get_acts(act_name)

        acts = Animation_worker._fresh_idle(self, acts)
        self._run_acts(acts, accs)

    def _fresh_idle(self, acts):
        """M3.2: a random idle clip (sit, read, happy...) is replaced by the pet's idle chooser
        (her own clips, none of the last 3), so both pickers share one varied pool."""
        picker = getattr(self, 'idle_picker', None)
        if picker is None or not acts:
            return acts
        first = acts[0]
        if not isinstance(first, Act) or first.need_move or first.act_name in NOT_IDLE_CLIPS:
            return acts
        try:
            pose = picker()
        except Exception:
            return acts
        act = getattr(self.pet_conf, 'act_dict', {}).get(pose)
        if act is None:
            return acts
        return [act] + list(acts[1:])

    
    def _get_acts(self, act_name):
        act_conf = settings.act_data.allAct_params[settings.petname][act_name]
        act_type = act_conf['act_type']
        if act_type == 'random_act':
            act_index = self.pet_conf.act_name.index(act_name)
            acts = self.pet_conf.random_act[act_index]
            accs = None
        
        elif act_type == 'accessory_act':
            acts = self.pet_conf.accessory_act[act_name]['act_list']
            accs = {'acc_list': self.pet_conf.accessory_act[act_name]['acc_list'],
                    'anchor': self.pet_conf.accessory_act[act_name]['anchor'],
                    'follow_main': self.pet_conf.accessory_act[act_name].get('follow_main', False),
                    'speed_follow_main': self.pet_conf.accessory_act[act_name].get('speed_follow_main', 5),
                    'follow_mouse': self.pet_conf.accessory_act[act_name].get('follow_mouse', False)}
        elif act_type == 'customized':
            acts = self.pet_conf.custom_act[act_name]['act_list']
            if self.pet_conf.custom_act[act_name]['acc_list']:
                accs = {'acc_list': self.pet_conf.custom_act[act_name]['acc_list'],
                        'anchor': self.pet_conf.custom_act[act_name]['anchor'],
                        'name': 'customized_acc' # For Accessory module to judge the type
                        }
            else:
                accs = None
        else:
            acts = None
            accs = None

        return acts, accs


    def _run_acts(self, acts: List[Act], accs: List[Act] = None) -> None:
        """
        执行动画, 将一个动作相关的图片循环展示
        :param acts: 一组关联动作
        :return:
        """
        #start = time.time()
        self._skip = False
        if accs:
            self.acc_regist.emit(accs)
        for act in acts:
            if self._skip or self.is_paused or self.is_killed:
                break
            if getattr(self, '_finish_deadline', None) is not None:
                self._release_clip()        # M3.3: the clip a line waited for is over
                break
            self._run_act(act)
        else:
            if getattr(self, '_finish_deadline', None) is not None and not self.is_paused:
                self._release_clip()
        #print('%.2fs'%(time.time()-start))
        #self.is_run_act = False

    def _run_act(self, act: Act) -> None:
        """
        加载图片执行移动
        :param act: 动作
        :return:
        """
        # if this is a skipping act
        if isinstance(act, list):
            for i in range(act[1]):
                if self.is_paused:
                    break
                if self.is_killed:
                    break
                if getattr(self, '_finish_deadline', None) is not None:
                    break                   # M3.3: a pause between clips: the line goes first
                time.sleep(act[0]/1000)
            return

        act = self._away_from_wall(act)
        walking = is_walk(act)
        prefetch_frames(act.images)
        clock = getattr(self, '_clock', time.monotonic)
        sleep = getattr(self, '_sleep', time.sleep)
        n_images = len(act.images)
        total = n_images * act.act_num
        # M3.2: frame k is due at started + k * frame_refresh (monotonic clock). A late frame
        # does not push the later ones back; when a whole frame is missed it is skipped and its
        # step is still walked, so the speed on screen stays the same.
        started, shown = clock(), -1
        try:
            while n_images:
                if self.is_paused or self.is_killed or getattr(self, '_skip', False):
                    break
                now = clock()
                # M3.3: a line is waiting: stop at the clip's end or natural point (yield_time).
                deadline = getattr(self, '_finish_deadline', None)   # set by the UI thread
                if deadline is not None:
                    if getattr(self, '_yield_at', None) is None:
                        self._yield_at = self._clip_yield(act, started, now, shown, deadline)
                    if now >= self._yield_at - 1e-9:
                        break
                index = due_frame(started, now, act.frame_refresh, shown)
                if index >= total:
                    break
                settings.previous_img = settings.current_img
                settings.current_img = act.images[index % n_images]
                settings.previous_anchor = settings.current_anchor
                settings.current_anchor = scaled_anchor(act.anchor)
                # Publicar el acto que pinta Animation_worker (C1 revisión 2: moonwalk).
                settings.anim_act = act
                self.sig_setimg_anim.emit()
                self._move(act, index - shown)
                shown = index
                wait = started + (index + 1) * act.frame_refresh - clock()
                if wait > 0:
                    sleep(wait)
                self.sig_repaint_anim.emit()
        finally:
            if walking:
                self.sig_walk_done.emit()

    def _away_from_wall(self, act):
        """M3.2: a walk toward the wall she already touches never starts: she turns around.
        D2.3: nor a walk toward a side with less room than one full walk; with no room on either
        side the walk becomes an idle clip."""
        if not is_walk(act):
            return act
        if getattr(self, 'wall_side', None) is not None:
            try:
                side = self.wall_side()
            except Exception:
                side = None
            if side == act.direction:
                turned = self.pet_conf.right if side == 'left' else self.pet_conf.left
                act = turned if is_walk(turned) else act
        if getattr(self, 'walk_room', None) is None:
            return act
        return walk_with_room(act, self.walk_room, self.pet_conf, getattr(self, 'idle_picker', None))
    '''
    def _static_act(self, pos: QPoint) -> None:
        """
        静态动作判断位置 - 目前舍弃不用
        :param pos: 位置
        :return:
        """
        screen_geo = QDesktopWidget().screenGeometry()
        screen_width = screen_geo.width()
        screen_height = screen_geo.height()
        border = self.pet_conf.size
        new_x = pos.x()
        new_y = pos.y()
        if pos.x() < border:
            new_x = screen_width - border
        elif pos.x() > screen_width - border:
            new_x = border
        if pos.y() < border:
            new_y = screen_height - border
        elif pos.y() > screen_height - border:
            new_y = border
        self.move(new_x, new_y)
    '''

    def _move(self, act: QAction, frames: int = 1) -> None: #pos: QPoint, act: QAction) -> None:
        """
        移动动作
        :param pos: 当前位置
        :param act: 动作
        :param frames: frames this step covers (M3.2: a skipped late frame still walks)
        :return
        """
        #print(act.direction, act.frame_move)
        plus_x, plus_y = frame_step(act)
        if plus_x == 0 and plus_y == 0:
            pass
        else:
            frames = max(1, int(frames))
            self.sig_move_anim.emit(plus_x * frames, plus_y * frames)




##############################
#      Interaction Module
##############################

class Interaction_worker(QObject):

    sig_setimg_inter = Signal(name='sig_setimg_inter')
    sig_move_inter = Signal(float, float, name='sig_move_inter')
    #sig_repaint_inter = Signal()
    sig_act_finished = Signal()
    sig_interact_note = Signal(str, str, name='sig_interact_note')

    acc_regist = Signal(dict, name='acc_regist')
    query_position = Signal(str, name='query_position')
    stop_trackMouse = Signal(name='stop_trackMouse')

    def __init__(self, pet_conf, parent=None):
        """
        Interaction Module
        Respond immediately to signals and run functions defined
        
        pet_conf: PetConfig class object in Main Widgets

        """
        super(Interaction_worker, self).__init__(parent)
        self.pet_conf = pet_conf
        self.is_killed = False
        self.is_paused = False
        self.interact = None
        self.act_name = None # everytime making act_name to None, don't forget to set settings.playid to 0
        self.interact_altered = False
        # M3.2: a looping clip (talk while she speaks) restarts from frame 0 at its end instead
        # of finishing; frame times come from this monotonic clock.
        self.loop = False
        self.clock = time.monotonic
        # M3.3: a line waits for this clip (finish_clip); a held clip shows its frame and does
        # not advance (hanging on the wall); the next clip may start on a given frame.
        self._finish_deadline = None
        self._yield_at = None
        self.frozen = False
        self._start_frame = 0
        self.hptier = sys_hp_tiers #[0, 50, 80, 100]
        self.pat_idx = None

        self.timer = QTimer()
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.run)
        #print(self.pet_conf.interact_speed)
        self.timer.start(self.pet_conf.interact_speed)
        #self.start = time.time()


    def run(self):
        #print(time.time()-self.start)
        #self.start = time.time()
        #print('start_run')
        if self.interact is None:
            return
        elif self.interact not in dir(self):
            self.interact = None
        else:
            altered = self.interact_altered
            if self.interact_altered:
                self.empty_interact()
                self.interact_altered = False
            if getattr(self, 'frozen', False):
                return                      # M3.3: hanging on the wall, the frame stays
            if not altered:
                self._plan_yield()          # M3.3: a clip already on screen plans at once
            if self._clip_yields():
                return
            getattr(self,self.interact)(self.act_name)
            self._plan_yield()

    # --- M3.3: a line never cuts a clip mid-way ----------------------------------------------
    @property
    def finishing(self):
        """True while the clip being played finishes for a line."""
        return getattr(self, '_finish_deadline', None) is not None and self.interact is not None

    def finish_clip(self, grace_s=FINISH_CLIP_S):
        """A line arrived: play the current clip to its end or natural point (`yield_time`), at
        most `grace_s` from now, then stop it (sig_act_finished). Never extends a deadline."""
        if self.interact is None or getattr(self, '_finish_deadline', None) is not None:
            return
        self._yield_at = None
        self._finish_deadline = self.clock() + float(grace_s)

    def cancel_finish(self):
        self._finish_deadline = None
        self._yield_at = None

    def hold(self):
        """Keep the frame on screen and stop advancing the clip (she hangs on the wall)."""
        self.frozen = True

    def _clip_yields(self):
        deadline = getattr(self, '_finish_deadline', None)
        if deadline is None:
            return False
        due = self._yield_at if getattr(self, '_yield_at', None) is not None else deadline
        if self.clock() + 1e-9 < due:
            return False
        self.stop_interact()
        return True

    def _plan_yield(self):
        """Once the clip is on screen: when it lets the waiting line in (`yield_time`)."""
        deadline = getattr(self, '_finish_deadline', None)
        if deadline is None or getattr(self, '_yield_at', None) is not None or self.interact is None:
            return
        act, started, now = settings.current_act, getattr(settings, 'act_started_at', None), self.clock()
        if not isinstance(act, Act) or started is None or yields_at_once(act, self.pet_conf):
            self._yield_at = now
            return
        frame_s = float(act.frame_refresh)
        wraps = self.loop or self.interact in ('followTarget', 'mousedrag')
        total = None if wraps else len(act.images) * act.act_num
        upto = int((deadline - started) / frame_s) + 1 if frame_s > 0 else 0
        if total is not None:
            upto = min(upto, total)
        shown = getattr(settings, 'act_frame_shown', -1)
        self._yield_at = yield_time(started, now, frame_s, deadline, total,
                                    natural_points(act, shown, upto))

    def _get_animation_type(self, act_name):
        act_conf = settings.act_data.allAct_params[settings.petname]
        if act_name not in act_conf:
            return None
        act_type = act_conf[act_name]['act_type']
        if act_type == 'random_act':
            return 'animat'
    
        elif act_type == 'accessory_act':
            return 'anim_acc'
        
        elif act_type == 'customized':
            return 'customized'

    def start_interact(self, interact, act_name=None, loop=False, start_frame=0):
        self._follow_trail = None
        self.loop = bool(loop)
        self._finish_deadline = self._yield_at = None
        self.frozen = False
        self._start_frame = max(0, int(start_frame or 0))   # M3.3: e.g. climb_down on the held frame
        # If Act selected from menu/panel, judge animation type first
        if interact == "actlist":
            interact = self._get_animation_type(act_name)
            if not interact:
                self.stop_interact()
                return
            #elif interact == 'customized':
            #    print("Not implemented")
            #    self.stop_interact()
            #    return

        sound_list = []
        if interact == 'animat' and act_name in self.pet_conf.act_name:
            sound_list = self.pet_conf.act_sound[self.pet_conf.act_name.index(act_name)]
            hp_lvl = self.pet_conf.act_type[self.pet_conf.act_name.index(act_name)][0]

        elif interact == 'anim_acc' and act_name in self.pet_conf.acc_name:
            sound_list = self.pet_conf.accessory_act[act_name]['sound']
            hp_lvl = self.pet_conf.accessory_act[act_name]['act_type'][0]
        
        # Customized animation currently doesn't have sound

        if len(sound_list) > 0 and settings.pet_data.hp_tier >= hp_lvl:
            sound_name = random.choice(sound_list)
            self.sig_interact_note.emit(sound_name, '')

        self.interact_altered = True
        if interact == 'anim_acc' or interact == 'customized':
            self.first_acc = True

        if self.interact == 'followTarget':
            if self.act_name == 'mouse':
                self.stop_trackMouse.emit()

        # sample pat animation
        if interact == 'patpat':
            self.pat_idx = self.sample_pat_anim()
        self.interact = interact
        self.act_name = act_name
    
    def kill(self):
        self.is_paused = False
        self.is_killed = True
        #self.timer.stop()
        # terminate thread

    def pause(self):
        self.is_paused = True
        #self.timer.stop()

    def resume(self):
        self.is_paused = False

    def stop_interact(self):
        self._follow_trail = None
        self.loop = False
        self._finish_deadline = self._yield_at = None
        self.frozen = False
        self.interact = None
        self.act_name = None
        self.first_acc = False
        settings.playid = 0
        settings.act_id = 0
        self.sig_act_finished.emit()

    def empty_interact(self):
        settings.playid = 0
        settings.act_id = 0
        settings.act_started_at = None      # the next clip starts from frame 0, even the same one

    def sample_pat_anim(self):
        hp_tier = settings.pet_data.hp_tier
        prob = [1*(0.25**(abs(i-hp_tier))) for i in range(len(settings.HP_TIERS))]
        prob = [i/sum(prob) for i in prob]
        act_idx = random.choices([i for i in range(len(settings.HP_TIERS))], weights=prob, k=1)[0]
        return act_idx

    def img_from_act(self, act, wrap=True):
        """Show the frame of `act` due now and return True when the clip has played to its end.

        M3.2: the frame comes from the time since the clip started (monotonic clock, see
        `due_frame`), not from counting ticks, so a late tick does not stretch the later frames.
        With `wrap` the clip goes on from frame 0 at its end (drag, fall, walks while following,
        a looping talk); without it the last frame stays until the caller moves on.
        `settings.act_frames_advanced` is how many frames this call advanced (for movement)."""
        clock = getattr(self, 'clock', None) or time.monotonic
        now = clock()
        if settings.current_act != act or getattr(settings, 'act_started_at', None) is None:
            if settings.current_act != act:
                settings.previous_act = settings.current_act
                settings.current_act = act
                settings.anim_act = None  # La interacción manda; ver set_img
            settings.playid = 0
            settings.act_started_at = now
            settings.act_frame_shown = -1
            start = getattr(self, '_start_frame', 0)
            if start and not isinstance(act, list) and len(act.images):
                # M3.3: start on frame `start` (climb_down on the frame she holds: no jump).
                start %= len(act.images)
                settings.act_started_at = now - start * float(act.frame_refresh)
                settings.act_frame_shown = start - 1
            self._start_frame = 0
            if not isinstance(act, list):
                prefetch_frames(act.images)     # M3.2: decode the rest of the clip in the background
        settings.act_frames_advanced = 0

        # if this is a skipping act
        if isinstance(act, list):
            n_repeat = math.ceil(act[0]/self.pet_conf.interact_speed) * act[1]
            settings.playid += 1
            if settings.playid >= n_repeat:
                settings.playid = 0
                return True
            return False

        n_images = len(act.images)
        total = n_images * act.act_num
        if not total:
            return True
        frame_s = float(act.frame_refresh)
        shown = getattr(settings, 'act_frame_shown', -1)
        index = int((now - settings.act_started_at) / frame_s + 1e-9) if frame_s > 0 else shown + 1
        finished = False
        if index >= total:
            finished = True
            if wrap:
                laps = index // total
                settings.act_started_at += laps * total * frame_s
                index -= laps * total
                shown -= laps * total
            else:
                index = total - 1
        if index > shown:
            settings.act_frames_advanced = index - shown
            settings.act_frame_shown = shown = index
        # Ticks of the interaction timer this clip has run (what playid counted before M3.2).
        tick_s = float(self.pet_conf.interact_speed) / 1000.0
        settings.playid = int((now - settings.act_started_at) / tick_s) if tick_s > 0 else 0
        settings.previous_img = settings.current_img
        settings.current_img = act.images[shown % n_images] if shown >= 0 else act.images[0]
        settings.previous_anchor = settings.current_anchor
        settings.current_anchor = scaled_anchor(act.anchor)
        return finished

    def animat(self, act_name):
        #if act_name == 'on_floor':
        #    print(settings.playid)

        #start = time.time()
        try:
            acts_index = self.pet_conf.act_name.index(act_name)
        except:
            self.stop_interact()
            return
        
        # 判断是否满足动作饱食度要求
        if settings.pet_data.hp_tier < self.pet_conf.act_type[acts_index][0]:
            message = f"[{act_name}]" + " " + self.tr("needs Satiety be larger than") + f" {self.hptier[self.pet_conf.act_type[acts_index][0]-1]}"
            self.sig_interact_note.emit('status_hp', message) #'[%s] 需要饱食度%i以上哦'%(act_name, self.hptier[self.pet_conf.act_type[acts_index][0]-1]))
            self.stop_interact()
            return
        
        acts = self.pet_conf.random_act[acts_index]
        #print(settings.act_id, len(acts))
        if settings.act_id >= len(acts) and getattr(self, 'loop', False) and acts:
            # M3.2: a looping clip (talk) goes on from frame 0 of the same clip.
            settings.act_id = 0
            settings.act_started_at = None
        if settings.act_id >= len(acts):
            #settings.act_id = 0
            #self.interact = None
            self.stop_interact()
            #self.sig_act_finished.emit()
        else:
            act = acts[settings.act_id]
            looping = getattr(self, 'loop', False) and len(acts) == 1
            if self.img_from_act(act, wrap=looping) and not looping:
                settings.act_id += 1

            if act_name == 'onfloor' and settings.fall_right:
                settings.previous_img = settings.current_img
                transform = QTransform()
                transform.scale(-1, 1)
                settings.current_img = settings.current_img.transformed(transform) #.mirrored(True, False)
                settings.current_anchor = scaled_anchor(act.anchor)
                settings.current_anchor = [-settings.current_anchor[0], settings.current_anchor[1]]

            if settings.previous_img != settings.current_img or settings.previous_anchor != settings.current_anchor:
                self.sig_setimg_inter.emit()
                self._move(act)
        #print('%.5fs'%(time.time()-start))
        
    def anim_acc(self, acc_name):

        # 判断是否满足动作饱食度要求
        if settings.pet_data.hp_tier < self.pet_conf.accessory_act[acc_name]['act_type'][0]:
            message = f"[{acc_name}]" + " " + self.tr("needs Satiety be larger than") + f" {self.hptier[self.pet_conf.accessory_act[acc_name]['act_type'][0]-1]}"
            self.sig_interact_note.emit('status_hp', message) #'[%s] 需要饱食度%i以上哦'%(acc_name, self.hptier[self.pet_conf.accessory_act[acc_name]['act_type'][0]-1]))
            self.stop_interact()
            return

        if self.first_acc:
            accs = self.pet_conf.accessory_act[acc_name]
            self.acc_regist.emit(accs)
            self.first_acc = False

        acts = self.pet_conf.accessory_act[acc_name]['act_list']

        if settings.act_id >= len(acts):
            #settings.act_id = 0
            #self.interact = None
            self.stop_interact()
            #self.sig_act_finished.emit()
        else:
            act = acts[settings.act_id]
            if self.img_from_act(act, wrap=False):
                settings.act_id += 1

            if settings.previous_img != settings.current_img or settings.previous_anchor != settings.current_anchor:
                self.sig_setimg_inter.emit()
                self._move(act)

    def customized(self, act_name):

        # 判断是否满足动作饱食度要求
        if settings.pet_data.hp_tier < self.pet_conf.custom_act[act_name]['act_type'][0]:
            message = f"[{act_name}]" + " " + self.tr("needs Satiety be larger than") + f" {self.hptier[self.pet_conf.custom_act[act_name]['act_type'][0]-1]}"
            self.sig_interact_note.emit('status_hp', message)
            self.stop_interact()
            return

        if self.first_acc:
            if self.pet_conf.custom_act[act_name]['acc_list']:
                accs = {'acc_list': self.pet_conf.custom_act[act_name]['acc_list'],
                        'anchor': self.pet_conf.custom_act[act_name]['anchor'],
                        'name': 'customized_acc' # For Accessory module to judge the type
                        }
                self.acc_regist.emit(accs)
            self.first_acc = False

        acts = self.pet_conf.custom_act[act_name]['act_list']

        if settings.act_id >= len(acts):
            #settings.act_id = 0
            #self.interact = None
            self.stop_interact()
            #self.sig_act_finished.emit()
        else:
            act = acts[settings.act_id]
            if self.img_from_act(act, wrap=False):
                settings.act_id += 1

            if settings.previous_img != settings.current_img or settings.previous_anchor != settings.current_anchor:
                self.sig_setimg_inter.emit()
                self._move(act)

    def patpat(self, act_name):
        acts = [self.pet_conf.patpat[self.pat_idx]]
        #print(settings.act_id, len(acts))
        if settings.act_id >= len(acts):
            #settings.act_id = 0
            #self.interact = None
            self.stop_interact()
            #self.sig_act_finished.emit()
        else:
            act = acts[settings.act_id]
            if self.img_from_act(act, wrap=False):
                settings.act_id += 1

            if settings.previous_img != settings.current_img or settings.previous_anchor != settings.current_anchor:
                self.sig_setimg_inter.emit()
                self._move(act)

    def mousedrag(self, act_name):

        # Falling is OFF
        if not settings.set_fall:
            if settings.draging==1:
                acts = self.pet_conf.drag

                self.img_from_act(acts)
                if settings.previous_img != settings.current_img or settings.previous_anchor != settings.current_anchor:
                    self.sig_setimg_inter.emit()
                
            else:
                self.stop_interact()
                #self.interact = None
                #self.act_name = None
                #settings.playid = 0

        # Falling is ON
        elif settings.set_fall==1 and settings.onfloor==0:
            if settings.draging==1:
                acts = self.pet_conf.drag
                self.img_from_act(acts)
                if settings.previous_img != settings.current_img or settings.previous_anchor != settings.current_anchor:
                    self.sig_setimg_inter.emit()

            elif settings.draging==0:
                if settings.prefall == 1:
                    acts = self.pet_conf.prefall
                else:
                    acts = self.pet_conf.fall

                # The pre-fall clip plays once (then the fall loops).
                if self.img_from_act(acts, wrap=settings.prefall != 1):
                    settings.prefall = 0

                #global fall_right
                if settings.fall_right:
                    settings.previous_img = settings.current_img
                    transform = QTransform()
                    transform.scale(-1, 1)
                    settings.current_img = settings.current_img.transformed(transform)
                    settings.current_anchor = scaled_anchor(acts.anchor)
                    settings.current_anchor = [-settings.current_anchor[0], settings.current_anchor[1]]

                if settings.previous_img != settings.current_img or settings.previous_anchor != settings.current_anchor:
                    self.sig_setimg_inter.emit()

                self.drop()

        else:
            #self.stop_interact()
            #self.interact = 'animat' #None
            #self.act_name = 'onfloor' #None
            self.start_interact('animat', 'onfloor')
            #settings.playid = 0
            #settings.act_id = 0

        #self.sig_repaint_inter.emit()


        #elif set_fall==0 and onfloor==0:

    def drop(self):
        #掉落
        #print("Dropping")

        ##print(dragspeedx)
        ##print(dragspeedy)
        #dropnext=pettop+info.gravity*dropa-info.gravity/2
        plus_y = settings.dragspeedy #+ self.pet_conf.dropspeed
        plus_x = settings.dragspeedx
        settings.dragspeedy = settings.dragspeedy + settings.gravity

        self.sig_move_inter.emit(plus_x, plus_y)

    def _move(self, act: QAction, frames=None) -> None: #pos: QPoint, act: QAction) -> None:
        """
        在 Thread 中发出移动Signal
        :param act: 动作
        :param frames: frames this step covers (default: the frames the last img_from_act
                       advanced; M3.2: a skipped late frame still walks)
        :return
        """
        #print(act.direction, act.frame_move)
        plus_x, plus_y = frame_step(act)
        if plus_x == 0 and plus_y == 0:
            pass
        else:
            if frames is None:
                frames = getattr(settings, 'act_frames_advanced', 1)
            frames = max(1, int(frames or 1))
            self.sig_move_inter.emit(plus_x * frames, plus_y * frames)

    def use_item(self, item):
        # 宠物进行 三个等级的喂食动画
        if item in self.pet_conf.item_favorite:
            #print('animation 1 here!')
            self.start_interact('animat','feed_1')
        elif item in self.pet_conf.item_dislike:
            #print('animation 3 here!')
            self.start_interact('animat','feed_3')
        else:
            #print('animation 2 here!')
            self.start_interact('animat','feed_2')

        '''
        self.interact = 'animat' #None
        self.act_name = 'onfloor' #None
        settings.playid = 0
        settings.act_id = 0
        '''
        #self.stop_interact()
        return

    def use_clct(self, item):
        if item in self.pet_conf.act_name:
            self.start_interact('animat', item)
        elif item in self.pet_conf.acc_name:
            self.start_interact('anim_acc', item)
        else:
            self.stop_interact()

        return

    def followTarget(self, act_name):

        self.query_position.emit(act_name)
        distance = abs(self.main_pos[0] - self.target_pos[0])

        if distance < 5*frame_step(self.pet_conf.left, 'right')[0]:
            act = self.pet_conf.default
            self.img_from_act(act)
            if settings.previous_img != settings.current_img or settings.previous_anchor != settings.current_anchor:
                self.sig_setimg_inter.emit()

        else:
            act = [self.pet_conf.left, self.pet_conf.right][int(self.main_pos[0] < self.target_pos[0])]
            # Against a wall the window cannot move; stop instead of walking in place.
            if follow_blocked(getattr(self, '_follow_trail', None), self.main_pos[0]):
                self._follow_trail = None
                self.stop_interact()
                return
            self.img_from_act(act)
            if settings.previous_img != settings.current_img or settings.previous_anchor != settings.current_anchor:
                self.sig_setimg_inter.emit()
                self._move(act)
                self._follow_trail = ((getattr(self, '_follow_trail', None) or [])[-(FOLLOW_STUCK_FRAMES - 1):]
                                      + [self.main_pos[0]])


    def receive_pos(self, main_pos, target_pos):
        self.main_pos = main_pos
        self.target_pos = target_pos




##############################
#          计划任务
##############################
class Scheduler_worker(QObject):
    sig_settext_sche = Signal(str, str, name='sig_settext_sche')
    sig_setact_sche = Signal(str, name='sig_setact_sche')
    sig_setstat_sche = Signal(str, int, name='sig_setstat_sche')
    sig_focus_end = Signal(name='sig_focus_end')
    sig_tomato_end = Signal(name='sig_tomato_end')
    sig_settime_sche = Signal(str, int, name='sig_settime_sche')
    sig_addItem_sche = Signal(int, name='sig_addItem_sche')
    sig_setup_bubble = Signal(dict, name='sig_setup_bubble')


    def __init__(self, parent=None):
        """
        Scheduler Module
        Time-related processor

        """
        super(Scheduler_worker, self).__init__(parent)
        #self.pet_conf = pet_conf
        self.is_killed = False
        self.is_paused = False
        #self.activated_times = 0
        self.new_task = False
        self.task_name = None
        self.n_tomato = None
        self.n_tomato_now = None
        self.focus_on = False
        self.tomato_list = []
        self.focus_time = 0
        self.tm_interval = 25
        self.tm_break = 5

        ''' Customized Pomodoro function deleted from v0.3.7
        pomodoro_conf = os.path.join(basedir, 'res/icons/Pomodoro.json')
        if os.path.isfile(pomodoro_conf):
            self.tm_config = json.load(open(pomodoro_conf, 'r', encoding='UTF-8'))
        else:
            self.tm_config = {"title":"番茄钟",
                        "Description": "番茄工作法是一种时间管理方法，该方法使用一个定时器来分割出25分钟的工作时间和5分钟的休息时间，提高效率。",
                        "option_text": "想要执行",
                        "options":{"pomodoro": {
                                             "note_start":"新的番茄时钟开始了哦！加油！",
                                             "note_first":"个番茄时钟设定完毕！开始了哦！",
                                             "note_end":"叮叮~ 番茄时间到啦！休息5分钟！",
                                             "note_last":"叮叮~ 番茄时间全部结束啦！"
                                             }
                                  }
                        }
        '''
        self.pomodoro_text = {"name": self.tr("Pomodoro"),
                              "note_start": self.tr("The new Pomodoro has started! Let's go!"),
                              "note_first": self.tr(" Pomodoros have been set! Let's dive in!"),
                              "note_end": self.tr("Ding ding~ Pomodoro finished! Time for a 5-minute break!"),
                              "note_last": self.tr("Ding ding~ All Pomodoros completed! Great job!"),
                              "note_cancel": self.tr("Your Pomodoros have all been canceled!")}

        self.focus_text = {"name": self.tr("Focus Session"),
                           "note_start": self.tr("Your focus session has started!"),
                           "note_end": self.tr("Your focus session has completed!"),
                           "note_cancel": self.tr("Your focus session has been canceled!")}

        self.scheduler = QtScheduler()
        #self.scheduler.add_job(self.change_hp, 'interval', minutes=self.pet_conf.hp_interval)
        self.scheduler.add_job(self.change_hp, interval.IntervalTrigger(minutes=1)) #self.pet_conf.hp_interval))
        #self.scheduler.add_job(self.change_em, 'interval', minutes=self.pet_conf.em_interval)
        self.scheduler.add_job(self.change_fv, interval.IntervalTrigger(minutes=1)) #self.pet_conf.fv_interval))
        self.scheduler.start()


    def run(self):
        """Run Scheduler in a separate thread"""
        #time.sleep(10)
        now_time = datetime.now().hour
        greet_type, greet_text = self.greeting(now_time)
        #comp_days = '这是陪伴你的第 %i 天 <3'%(settings.pet_data.days)
        if not settings.settingGood:
            settingBrokeNote = self.tr("*Setting config file broken. Setting is re-initialized.")
            self.show_dialogue('system', settingBrokeNote)
        else:
            settingBrokeNote = ""
        if not settings.pet_data.saveGood:
            saveBrokeNote = self.tr("*Game save file broken. Data is re-initialized.\nPlease load previous saved data to recover.")
            self.show_dialogue('system', saveBrokeNote)
        else:
            saveBrokeNote = ""
        #self.show_dialogue(greet_type, f'{greet_text}')
        self.sig_setup_bubble.emit({'message':greet_text, 'start_audio':greet_type, 'icon':None})
        
    
    def kill(self):
        self.is_paused = False
        self.is_killed = True
        self.scheduler.shutdown()


    def pause(self):
        self.is_paused = True
        self.scheduler.pause()


    def resume(self):
        self.is_paused = False
        self.scheduler.resume()

    def send_greeting(self):
        now_time = datetime.now().hour
        greet_type, greet_text = self.greeting(now_time)
        #comp_days = '这是陪伴你的第 %i 天 <3'%(settings.pet_data.days)
        #self.show_dialogue(greet_type, '%s'%(greet_text))
        self.sig_setup_bubble.emit({'message':greet_text, 'start_audio':greet_type, 'icon':None})


    def greeting(self, time):
        if 11 >= time >= 6:
            return 'greeting_1', self.tr("Good Morning!") #'早上好!'
        elif 13 >= time >= 12:
            return 'greeting_2', self.tr("Good Afternoon!") #'中午好!'
        elif 18 >= time >= 14:
            return 'greeting_3', self.tr("Good Afternoon!") #'下午好！'
        elif 22 >= time >= 19:
            return 'greeting_4', self.tr("Good Evening!") #'晚上好!'
        elif 24 >= time >= 23:
            return 'greeting_5', self.tr("Time to sleep!") #'该睡觉啦!'
        elif 5 >= time >= 0:
            return 'greeting_5', self.tr("Time to sleep!") #'该睡觉啦!'
        else:
            return 'None','None'


    def show_dialogue(self, note_type, texts_toshow):
        # 排队 避免对话显示冲突
        while settings.showing_dialogue_now:
            time.sleep(1)
        settings.showing_dialogue_now = True
        #print('show_dialogue check')

        #for text_toshow in texts_toshow:
        self.sig_settext_sche.emit(note_type, texts_toshow) #text_toshow)
        #    time.sleep(3)
        #self.sig_settext_sche.emit('None')
        settings.showing_dialogue_now = False

    '''
    def item_drop(self, n_minutes):
        #print(n_minutes)
        nitems = n_minutes // 5
        remains = max(0, n_minutes % 5 - 1)
        chance_drop = random.choices([0,1], weights=(1-remains/5, remains/5))
        #print(chance_drop)
        nitems += chance_drop[0]
        #for test -----
        #nitems = 4
        #---------------
        if nitems > 0:
            self.sig_addItem_sche.emit(nitems)
    '''

    def add_tomato(self, n_tomato=None):

        if self.focus_on == False and self.n_tomato_now is None:
            self.n_tomato_now = n_tomato
            time_plus = 0 #25

            # 1-start
            task_text = 'tomato_first'
            time_torun = datetime.now() + timedelta(seconds=1)
            #self.scheduler.add_job(self.run_task, run_date=time_torun, args=[task_text])
            self.scheduler.add_job(self.run_tomato, date.DateTrigger(run_date=time_torun), args=[task_text])
            
            time_plus += self.tm_interval #25
            #1-end
            if n_tomato == 1:
                task_text = 'tomato_last'
            else:
                task_text = 'tomato_end'
            time_torun = datetime.now() + timedelta(minutes=time_plus) #minutes=time_plus)
            #self.scheduler.add_job(self.run_task, run_date=time_torun, args=[task_text])
            self.scheduler.add_job(self.run_tomato, date.DateTrigger(run_date=time_torun), args=[task_text], id='tomato_0_end')
            self.tomato_list.append('tomato_0_end')
            time_plus += self.tm_break #5

            # others start and end
            if n_tomato > 1:
                for i in range(1, n_tomato):
                    #start
                    task_text = 'tomato_start'
                    time_torun = datetime.now() + timedelta(minutes=time_plus) #minutes=time_plus)
                    #self.scheduler.add_job(self.run_task, run_date=time_torun, args=[task_text])
                    self.scheduler.add_job(self.run_tomato, date.DateTrigger(run_date=time_torun), args=[task_text], id='tomato_%s_start'%i)
                    time_plus += self.tm_interval #25
                    #end
                    if i == (n_tomato-1):
                        task_text = 'tomato_last'
                    else:
                        task_text = 'tomato_end'
                    time_torun = datetime.now() + timedelta(minutes=time_plus) #minutes=time_plus)
                    #self.scheduler.add_job(self.run_task, run_date=time_torun, args=[task_text])
                    self.scheduler.add_job(self.run_tomato, date.DateTrigger(run_date=time_torun), args=[task_text], id='tomato_%s_end'%i)
                    time_plus += self.tm_break #5
                    self.tomato_list.append('tomato_%s_start'%i)
                    self.tomato_list.append('tomato_%s_end'%i)

        ''' From v0.3.7, situations below won't happen
        elif self.focus_on:
            task_text = "focus_on"
            time_torun = datetime.now() + timedelta(seconds=1)
            self.scheduler.add_job(self.run_tomato, date.DateTrigger(run_date=time_torun), args=[task_text])
        else:
            task_text = "tomato_exist"
            time_torun = datetime.now() + timedelta(seconds=1)
            #self.scheduler.add_job(self.run_task, run_date=time_torun, args=[task_text])
            self.scheduler.add_job(self.run_tomato, date.DateTrigger(run_date=time_torun), args=[task_text])
        '''



    def run_tomato(self, task_text):
        text_toshow = ''
        #finished = False

        if task_text == 'tomato_start':
            self.tomato_timeleft = self.tm_interval #25
            self.scheduler.add_job(self.change_tomato, interval.IntervalTrigger(minutes=1), id='tomato_timer', replace_existing=True)
            self.sig_settime_sche.emit('tomato_start', self.tomato_timeleft)
            self.tomato_list = self.tomato_list[1:]
            text_toshow = self.pomodoro_text['note_start']

        elif task_text == 'tomato_first':
            self.scheduler.add_job(self.change_tomato, interval.IntervalTrigger(minutes=1), id='tomato_timer', replace_existing=True)
            self.tomato_timeleft = self.tm_interval #25
            self.sig_settime_sche.emit('tomato_start', self.tomato_timeleft)
            text_toshow = "%s%s"%(int(self.n_tomato_now), self.pomodoro_text['note_first'])

        elif task_text == 'tomato_end':
            self.tomato_timeleft = self.tm_break #5
            self.scheduler.add_job(self.change_tomato, interval.IntervalTrigger(minutes=1), id='tomato_timer', replace_existing=True)
            self.sig_settime_sche.emit('tomato_rest', self.tomato_timeleft)
            self.tomato_list = self.tomato_list[1:]
            text_toshow = self.pomodoro_text['note_end'] #'叮叮~ 番茄时间到啦！休息5分钟！'
            #finished = True

        elif task_text == 'tomato_last':
            try:
                self.scheduler.remove_job('tomato_timer')
            except:
                pass
            self.tomato_timeleft = 0
            self.n_tomato_now=None
            self.tomato_list = []
            self.sig_tomato_end.emit()
            self.sig_settime_sche.emit('tomato_end', self.tomato_timeleft)
            text_toshow = self.pomodoro_text['note_last']
            #finished = True

        elif task_text == 'tomato_cancel':
            self.n_tomato_now=None
            for iidd in self.tomato_list:
                self.scheduler.remove_job(iidd)
            self.tomato_list = []
            try:
                self.scheduler.remove_job('tomato_timer')
            except:
                pass
            self.tomato_timeleft = 0
            self.sig_settime_sche.emit('tomato_cencel', self.tomato_timeleft)
            self.sig_tomato_end.emit()
            text_toshow = self.pomodoro_text['note_cancel']

        ''' Theoretically, such situation won't exist from v0.3.7 on.
        elif task_text == 'tomato_exist':
            self.sig_tomato_end.emit()
            self.sig_settime_sche.emit('tomato_end', 0)
            text_toshow = "不行！还有 [%s] 在进行哦~"%(settings.current_tm_option)

        elif task_text == 'focus_on':
            self.sig_tomato_end.emit()
            self.sig_settime_sche.emit('tomato_end', 0)
            text_toshow = "不行！还有专注任务在进行哦~"
        '''
        if text_toshow:
            if task_text in ['tomato_start', 'tomato_first']:
                self.show_dialogue('start_tomato', text_toshow)

            elif task_text in ['tomato_end', 'tomato_last']:
                self.show_dialogue('end_tomato', text_toshow)

            elif task_text == 'tomato_cancel':
                self.show_dialogue('cancel_tomato', text_toshow)
        '''
        if finished:
            time.sleep(1)
            self.item_drop(n_minutes=30)
        '''
        #else:
        #    text_toshow = '叮叮~ 你的任务 [%s] 到时间啦！'%(task_text)

    def cancel_tomato(self):
        task_text = "tomato_cancel"
        time_torun_2 = datetime.now() + timedelta(seconds=1)
        self.scheduler.add_job(self.run_tomato, date.DateTrigger(run_date=time_torun_2), args=[task_text])

    def change_hp(self):
        self.sig_setstat_sche.emit('hp', -1)

    def change_fv(self):
        self.sig_setstat_sche.emit('fv', 1)

    def change_tomato(self):
        self.tomato_timeleft += -1
        if self.tomato_timeleft <= 1:
            self.scheduler.remove_job('tomato_timer')
        self.sig_settime_sche.emit('tomato', self.tomato_timeleft)

    def change_focus(self):
        self.focus_time += -1
        if self.focus_time <= 1:
            self.scheduler.remove_job('focus_timer')
        self.sig_settime_sche.emit('focus', self.focus_time)


    def add_focus(self, time_range=None, time_point=None):
        ''' From v0.3.7, situations below won't happen
        if self.n_tomato_now is not None:
            task_text = "tomato_exist"
            time_torun = datetime.now() + timedelta(seconds=1)
            self.scheduler.add_job(self.run_focus, date.DateTrigger(run_date=time_torun), args=[task_text])

        elif self.focus_on:
            task_text = "focus_exist"
            time_torun = datetime.now() + timedelta(seconds=1)
            self.scheduler.add_job(self.run_focus, date.DateTrigger(run_date=time_torun), args=[task_text])
        '''

        if time_range is not None:
            if sum(time_range) == 0:
                return
            else:
                self.focus_on = True
                task_text = "focus_start"
                time_torun = datetime.now() + timedelta(seconds=1)
                self.focus_time = int(time_range[0]*60 + time_range[1])
                self.scheduler.add_job(self.run_focus, date.DateTrigger(run_date=time_torun), args=[task_text])

                task_text = "focus_end"
                time_torun = datetime.now() + timedelta(hours=time_range[0], minutes=time_range[1])
                self.scheduler.add_job(self.run_focus, date.DateTrigger(run_date=time_torun), args=[task_text,self.focus_time], id='focus')

        ''' From v0.3.7, setting up by time_point has been deleted from UI
        elif time_point is not None:
            now = datetime.now()
            time_torun = datetime(year=now.year, month=now.month, day=now.day,
                                  hour=time_point[0], minute=time_point[1], second=0) #now.second)
            time_diff = time_torun - now
            self.focus_time = time_diff.total_seconds() // 60

            if time_diff <= timedelta(0):
                time_torun = time_torun + timedelta(days=1)
                self.focus_time += 24*60

                self.focus_on = True
                task_text = "focus_start_tomorrow"
                time_torun_2 = datetime.now() + timedelta(seconds=1)
                self.scheduler.add_job(self.run_focus, date.DateTrigger(run_date=time_torun_2), args=[task_text])

                task_text = "focus_end"
                self.scheduler.add_job(self.run_focus, date.DateTrigger(run_date=time_torun), args=[task_text,self.focus_time], id='focus')
            else:
                self.focus_on = True
                task_text = "focus_start"
                time_torun_2 = datetime.now() + timedelta(seconds=1)
                self.scheduler.add_job(self.run_focus, date.DateTrigger(run_date=time_torun_2), args=[task_text])

                task_text = "focus_end"
                self.scheduler.add_job(self.run_focus, date.DateTrigger(run_date=time_torun), args=[task_text,self.focus_time], id='focus')
        '''

    def run_focus(self, task_text, n_minutes=0):
        text_toshow = ''
        #finished = False
        ''' From v0.3.7, situations below won't happen
        if task_text == 'tomato_exist':
            self.sig_focus_end.emit()
            self.sig_settime_sche.emit('focus_end', 0)
            text_toshow = '不行！还有 [%s] 在进行哦~'%(settings.current_tm_option)

        elif task_text == 'focus_exist':
            self.sig_focus_end.emit()
            self.sig_settime_sche.emit('focus_end', 0)
            text_toshow = "不行！还有专注任务在进行哦~"
        '''
        if task_text == 'focus_start':
            if self.focus_time > 1:
                self.scheduler.add_job(self.change_focus, interval.IntervalTrigger(minutes=1), id='focus_timer', replace_existing=True)
            #elif self.focus_time < 1:
            #    print(self.focus_time)
                #focus_time_sec = int()
            self.sig_settime_sche.emit('focus_start', self.focus_time)
            text_toshow = self.focus_text['note_start'] #"你的专注任务开始啦！"


        elif task_text == 'focus_end':
            self.focus_time = 0
            try:
                self.scheduler.remove_job('focus_timer')
            except:
                pass
            self.sig_settime_sche.emit('focus_end', self.focus_time)
            self.focus_on = False
            self.sig_focus_end.emit()
            text_toshow = self.focus_text['note_end'] #"你的专注任务结束啦！"
            #finished = True


        elif task_text == 'focus_cancel':
            self.focus_time = 0
            try:
                self.scheduler.remove_job('focus_timer')
            except:
                pass
            self.sig_settime_sche.emit('focus_cancel', self.focus_time)
            self.sig_focus_end.emit()
            self.focus_on = False
            text_toshow = self.focus_text['note_cancel'] #"你的专注任务取消啦！"
            #finished = True
        
        if text_toshow:
            if task_text == 'focus_start':
                self.show_dialogue('start_focus', text_toshow)

            elif task_text == 'focus_end':
                self.show_dialogue('end_focus', text_toshow)

            elif task_text == 'focus_cancel':
                self.show_dialogue('cancel_focus', text_toshow)

        ''' From v0.3.7, situations below won't happen
        elif task_text == 'focus_start_tomorrow':
            if self.focus_time > 1:
                self.scheduler.add_job(self.change_focus, interval.IntervalTrigger(minutes=1), id='focus_timer', replace_existing=True)
            self.sig_settime_sche.emit('focus_start', self.focus_time)
            text_toshow = "专注任务开始啦！\n但设定在明天，请确认无误哦~"

        elif task_text == 'focus_pause':
            try:
                self.scheduler.remove_job('focus_timer')
            except:
                pass
            #self.sig_settime_sche.emit('focus_end', self.focus_time)
            #self.sig_focus_end.emit()
            #self.focus_on = False
            text_toshow = "你的专注任务暂停啦！"

        elif task_text == 'focus_resume':
            if self.focus_time > 1:
                self.scheduler.add_job(self.change_focus, interval.IntervalTrigger(minutes=1), id='focus_timer', replace_existing=True)

            self.sig_settime_sche.emit('focus', self.focus_time)
            text_toshow = "你的专注任务继续进行啦！"
        '''

    ''' Pause function deleted from v0.3.7
    def pause_focus(self):
        try:
            self.scheduler.remove_job('focus')
        except:
            pass
        task_text = "focus_pause"
        time_torun_2 = datetime.now() + timedelta(seconds=1)
        self.scheduler.add_job(self.run_focus, date.DateTrigger(run_date=time_torun_2), args=[task_text])

    def resume_focus(self, remains, total):
        task_text = "focus_resume"
        self.focus_time = remains
        time_torun = datetime.now() + timedelta(seconds=1)
        self.scheduler.add_job(self.run_focus, date.DateTrigger(run_date=time_torun), args=[task_text])

        task_text = "focus_end"
        time_torun = datetime.now() + timedelta(minutes=remains)
        self.scheduler.add_job(self.run_focus, date.DateTrigger(run_date=time_torun), args=[task_text,total], id='focus')
    '''
    def cancel_focus(self, time_past):
        try:
            self.scheduler.remove_job('focus')
        except:
            pass
        task_text = "focus_cancel"
        time_torun_2 = datetime.now() + timedelta(seconds=1)
        self.scheduler.add_job(self.run_focus, date.DateTrigger(run_date=time_torun_2), args=[task_text,time_past])

    ''' Reminder function deleted from v0.3.7
    def add_remind(self, texts, time_range=None, time_point=None, repeat=False):
        if time_point is not None:
            if repeat:
                certain_minute = int(time_point[1])
                self.scheduler.add_job(self.run_remind,
                                       cron.CronTrigger(minute=certain_minute),
                                       args=[texts])
            else:
                certain_day = datetime.now().day
                certain_hour = int(time_point[0])
                certain_minute = int(time_point[1])
                if certain_hour < datetime.now().hour:
                    certain_day = (datetime.now() + timedelta(days=1)).day
                self.scheduler.add_job(self.run_remind,
                                       cron.CronTrigger(day=certain_day,
                                                        hour=certain_hour,
                                                        minute=certain_minute),
                                       args=[texts])

        elif time_range is not None:
            if repeat:
                interval_minute = int(time_range[1])
                self.scheduler.add_job(self.run_remind,
                                       interval.IntervalTrigger(minutes=interval_minute),
                                       args=[texts])
            else:
                if sum(time_range) == 0:
                    return
                else:
                    time_torun = datetime.now() + timedelta(hours=time_range[0], minutes=time_range[1])
                    self.scheduler.add_job(self.run_remind,
                                           date.DateTrigger(run_date=time_torun),
                                           args=[texts])

        time_torun_2 = datetime.now() + timedelta(seconds=1)
        self.scheduler.add_job(self.run_remind,
                               date.DateTrigger(run_date=time_torun_2),
                               args=['remind_start'])

    def run_remind(self, task_text):
        if task_text == 'remind_start':
            text_toshow = "提醒事项设定完成！"
        else:
            text_toshow = '叮叮~ 时间到啦\n[ %s ]'%task_text
        
        self.show_dialogue('clock_remind',text_toshow)
    '''

        





