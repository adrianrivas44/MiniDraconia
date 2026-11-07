"""The pet's life on the desktop (M3-M3.3 engine behaviour): frames at the screen's size, real
walks, wall climbs, and visibly talking while she says a line.

`PetWidget` inherits `PetLifeMixin`; these methods only use the pet attributes listed below,
so they can be exercised without starting the pet (DyberPet.py itself needs a desktop for
pynput). Where her lines come from (offline, own AI, self-hosted relay) lives in
`DyberPet/pet_conversation.py`.

Pet attributes used: _emit_mia_bubble(text, voice, wav), _mia_show_bubble(bubble_dict),
_mia_play_pose(pose), _mia_log(kind, text) and, when present, talk_controller, mia_voice,
frame_store, pet_conf, workers, label, mia_micro_ticker, current_screen.

Diagnostics written to the pet's local log (data/mia_talk.log), English and compact:
`screen <geometry> dpr=<x> scale=<pet_display_scale>` once at start and
`walk end <pose> dx=<px> frames=<n> clamped=<n>` once per walk.
"""
import logging
from typing import Optional

import DyberPet.settings as settings


def walking_toward(state: str):
    """'left'/'right' while a walk is playing (random animation or interaction), else None."""
    act = getattr(settings, 'anim_act', None) if state == 'default' else getattr(settings, 'current_act', None)
    if not getattr(act, 'need_move', False):
        return None
    direction = getattr(act, 'direction', None)
    return direction if direction in ('left', 'right') else None


class PetLifeMixin:
    # --- M3: visibly talking ----------------------------------------------------------------
    def _life_say_line(self, text: str, bubble_dict: dict, voice_cfg: dict,
                       wav: Optional[str] = None) -> None:
        """M3.1: a voiced line waits for its voice (she thinks, the bubble is held) at most
        talk_controller.VOICE_WAIT_S, then `_life_release_line` shows it; an unvoiced line shows at
        once. `bubble_dict["timeout"]` is in seconds. `wav`: the line's recorded WAV (voice
        pack, D2.1), played instead of asking the relay for a voice; same wait and sync."""
        talk = getattr(self, 'talk_controller', None)
        voiced = bool(voice_cfg.get('enabled'))
        if talk is not None:
            self._life_finish_clip()     # M3.3: the clip playing now ends first, not mid-way
        if voiced and talk is not None:
            self._life_held_bubble = bubble_dict
            self._mia_chat_bubble_visible = True        # a line is in progress
            talk.wait_for_voice(bubble_dict['timeout'])
            self._life_speak(text, voice_cfg, wav)
            return
        if getattr(self, '_life_held_bubble', None) is not None:
            # This line replaces one still waiting for its voice: that voice must not play now.
            self._life_held_bubble = None
            self._life_cancel_voice()
        self._mia_show_bubble(bubble_dict)
        if talk is not None:
            talk.say(bubble_dict['timeout'], voiced=False)
        elif voiced:
            self._life_speak(text, voice_cfg, wav)

    def _life_speak(self, text: str, voice_cfg: dict, wav: Optional[str] = None) -> None:
        """The line's voice, both through MiaVoice: its recorded pack WAV, or the relay's."""
        if wav:
            import os
            self._mia_log('voice', 'stored ' + os.path.basename(str(wav)))
            self.mia_voice.play_stored(wav, cfg=voice_cfg)
        else:
            self.mia_voice.speak(text, cfg=voice_cfg)
            self._mia_log('voice', 'requested')

    def _life_release_line(self, voiced: bool) -> None:
        """TalkController: the wait for the voice is over (it started, failed or took too long)."""
        bubble = getattr(self, '_life_held_bubble', None)
        self._life_held_bubble = None
        if not voiced:
            self._life_cancel_voice()                   # a late voice would be out of sync
            self._mia_log('voice', 'not in time')
        if bubble is not None:
            self._mia_show_bubble(bubble)

    def _life_cancel_voice(self) -> None:
        voice = getattr(self, 'mia_voice', None)
        cancel = getattr(voice, 'cancel', None)
        if cancel is not None:
            try:
                cancel()
            except Exception:
                logging.getLogger(__name__).exception('voice cancel failed (ignored)')

    def _life_voice_started(self, duration_s: float) -> None:
        """MiaVoice: the WAV started playing. Mouth pauses come from its RMS envelope."""
        talk = getattr(self, 'talk_controller', None)
        if talk is None:
            return
        from DyberPet.talk_controller import wav_mouth_pauses
        wav = getattr(getattr(self, 'mia_voice', None), 'current_wav', None)
        pauses = wav_mouth_pauses(wav) if wav else []
        was_active = talk.active
        if not was_active:
            self._life_finish_clip()     # M3.3: a late voice brings the line back: same rule
        talk.voice_started(duration_s, pauses)
        if not was_active and not talk.active:
            self._life_cancel_finish()

    def _life_begin_talk(self, pose) -> None:
        """The line's emotion pose. With the talk controller (the real pet) it is shown briefly
        and then `talk` loops for the line (DyberPet/talk_controller.py); without it, played once."""
        talk = getattr(self, 'talk_controller', None)
        if talk is not None and talk.active:
            talk.set_pose(pose)
        elif pose:
            self._mia_play_pose(pose)

    def _life_talk_play(self, pose: str) -> None:
        """TalkController's clips. `talk` and the closed-mouth pause loop in the engine for as long as
        the line lasts (M3.2: one seamless animation, never restarted at the clip's end)."""
        from DyberPet.talk_controller import LOOP_POSES
        self._mia_play_pose(pose, loop=pose in LOOP_POSES, from_talk=True)

    def _life_line_active(self) -> bool:
        return bool(getattr(getattr(self, 'talk_controller', None), 'active', False))

    # Clips that may replace her talk clip while a line is active (M3.2): drag, fall, climb;
    # M3.3: touch reactions too (they still interrupt at once).
    TALK_OVERRIDES = ('drag', 'fall', 'onfloor', 'climb', 'climb_down',
                      'patpat', 'pinch', 'touch_body')

    def _life_pose_allowed_while_talking(self, pose: str, from_talk: bool,
                                         from_touch: bool = False) -> bool:
        if from_talk or from_touch or not self._life_line_active():
            return True
        return pose in self.TALK_OVERRIDES or pose.startswith('climb')

    def _life_talk_blocked(self) -> bool:
        """Never interrupt drag, fall or a wall climb."""
        interaction = getattr(self, 'workers', {}).get('Interaction')
        climbing = bool(getattr(getattr(self, 'mia_micro_ticker', None), 'is_climbing', False))
        return (settings.draging == 1 or not settings.onfloor or climbing
                or getattr(interaction, 'interact', None) == 'mousedrag')

    def _life_talk_tick(self) -> None:
        talk = getattr(self, 'talk_controller', None)
        if talk is None:
            return
        try:
            interaction = getattr(self, 'workers', {}).get('Interaction')
            state = getattr(interaction, 'interact', None) or 'default'
            talk.tick(state=state, blocked=self._life_talk_blocked())
        except Exception:
            logging.getLogger(__name__).exception('_life_talk_tick failed (ignored)')

    def _life_talk_stop(self, pose) -> None:
        """The line ended: stop the talk clip at once and show her stand (M3.3: the mouth never
        moves without voice); an emotion clip has played to its end. Then normal life resumes.
        A clip the line was still waiting for just goes on (its end resumes normal life)."""
        from DyberPet.talk_controller import LOOP_POSES, THINK_POSE
        self._life_cancel_finish()
        workers = getattr(self, 'workers', {})
        interaction = workers.get('Interaction')
        interact = getattr(interaction, 'interact', None)
        if interaction is not None and pose and getattr(interaction, 'act_name', None) == pose \
                and interact not in (None, 'mousedrag'):
            interaction.stop_interact()      # emits sig_act_finished -> resume_animation
            if pose in LOOP_POSES or pose == THINK_POSE:
                self._life_show_stand()
        elif 'Animation' in workers and interact is None and not self._life_holds_animation():
            workers['Animation'].resume()

    def _life_show_stand(self) -> None:
        """Her stand, at once: the first frame of the pet's default clip (M3.3)."""
        from DyberPet.modules import scaled_anchor
        default = getattr(getattr(self, 'pet_conf', None), 'default', None)
        images = getattr(default, 'images', None)
        if default is None or images is None or not len(images):
            return
        try:
            settings.previous_img = settings.current_img
            settings.current_img = images[0]
            settings.previous_anchor = settings.current_anchor
            settings.current_anchor = scaled_anchor(default.anchor)
            settings.current_act = default
            settings.anim_act = None
            settings.act_started_at = None
            set_img = getattr(self, 'set_img', None)
            if set_img is not None:
                set_img()
        except Exception:
            logging.getLogger(__name__).exception('_life_show_stand failed (ignored)')

    # --- M3.3: a line never cuts a clip mid-way --------------------------------------------
    def _life_finish_clip(self) -> None:
        """A line arrives: the clip playing now (director/idle/emotion/touch clip, a walk, the
        random animation's clip) finishes by the modules.FINISH_CLIP_S rule before the line's
        poses. Talk, its pause and think of a line in progress, her stand, drag, fall and climb
        are not waited for."""
        from DyberPet.talk_controller import LOOP_POSES, THINK_POSE
        if self._life_talk_blocked():
            return
        workers = getattr(self, 'workers', {})
        interaction = workers.get('Interaction')
        interact = getattr(interaction, 'interact', None)
        try:
            if interact is not None:
                talk = getattr(self, 'talk_controller', None)
                act_name = getattr(interaction, 'act_name', None)
                own = bool(getattr(talk, 'active', False)) and act_name == getattr(talk, 'playing', None) \
                    and act_name in LOOP_POSES + (THINK_POSE,)
                if interact != 'mousedrag' and not own and hasattr(interaction, 'finish_clip'):
                    interaction.finish_clip()
                return
            animation = workers.get('Animation')
            if animation is not None and not getattr(animation, 'is_paused', True) \
                    and hasattr(animation, 'finish_clip'):
                animation.finish_clip()
        except Exception:
            logging.getLogger(__name__).exception('_life_finish_clip failed (ignored)')

    def _life_body_busy(self) -> bool:
        """A clip is still finishing before the line's poses."""
        workers = getattr(self, 'workers', {})
        return any(bool(getattr(workers.get(name), 'finishing', False))
                   for name in ('Interaction', 'Animation'))

    def _life_cancel_finish(self) -> None:
        for worker in getattr(self, 'workers', {}).values():
            cancel = getattr(worker, 'cancel_finish', None)
            if cancel is not None:
                cancel()

    def _life_touch_reaction(self) -> None:
        """A touch reaction interrupted her at once; during a line its clip finishes like any
        other before the line's poses come back."""
        talk = getattr(self, 'talk_controller', None)
        if talk is not None and talk.active:
            self._life_finish_clip()
            talk.hold_body()

    def _life_clip_s(self, pose: str):
        """Seconds of one full clip of `pose` as the engine plays it (all its acts)."""
        from DyberPet.conf import Act
        conf = getattr(self, 'pet_conf', None)
        if conf is None:
            return None
        names = getattr(conf, 'act_name', [])
        if pose in names:
            acts = conf.random_act[names.index(pose)]
        elif pose in getattr(conf, 'act_dict', {}):
            acts = [conf.act_dict[pose]]
        else:
            return None
        seconds = sum(len(a.images) * a.act_num * float(a.frame_refresh)
                      for a in acts if isinstance(a, Act))
        return seconds or None

    # --- M3.3: climb never shows a non-climb frame -----------------------------------------
    @staticmethod
    def _life_loops_clip(pose: str) -> bool:
        """Climb clips loop in the engine for the whole climb: no gap at the clip's end."""
        return str(pose).startswith('climb')

    def _life_clip_start_frame(self, pose: str) -> int:
        """climb_down starts on the frame she holds (it is the climb clip backwards): no jump."""
        from DyberPet.mia_director import CLIMB_DOWN_POSE
        act = getattr(settings, 'current_act', None)
        if pose != CLIMB_DOWN_POSE or getattr(act, 'act_name', None) != 'climb':
            return 0
        n, shown = len(act.images), getattr(settings, 'act_frame_shown', -1)
        if not n or shown is None or shown < 0:
            return 0
        return (n - 1 - shown % n) % n

    def _life_cursor_target(self):
        """Where 'follow the cursor' walks to, in the same logical pixels as self.pos().

        The pynput listener reports physical pixels (1.5x at 150 % scaling) and only after the
        mouse moves, so with it she walked toward [0, 0] or past the screen edge and walked in
        place against the wall. Qt's cursor position is current and already logical."""
        from PySide6.QtGui import QCursor
        cursor = QCursor.pos()
        self.mouse_pos = [cursor.x(), cursor.y()]
        return list(self.mouse_pos)

    # --- M3.2: no walking in place, walk diagnostics ----------------------------------------
    def _life_wall_side(self):
        """'left'/'right' when she touches that screen edge (where limit_in_screen clamps her)."""
        from DyberPet.modules import wall_side
        screen = getattr(self, 'current_screen', None)
        if screen is None:
            return None
        width = getattr(self, 'screen_width', None) or screen.width()
        return wall_side(self.pos().x(), self.width(), screen.topLeft().x(), width)

    def _life_publish_wall(self) -> None:
        """For the random animation thread, which must not read the widget itself: the wall she
        touches and (D2.3) her room toward each side."""
        try:
            self._life_wall = self._life_wall_side()
        except Exception:
            self._life_wall = None
        try:
            self._life_room = self._life_room_now()
        except Exception:
            self._life_room = None

    # --- D2.3: a random walk never heads into the wall she is already touching ----------------
    def _life_room_now(self):
        """{'left': px, 'right': px} she can walk on her current screen from where she stands."""
        from DyberPet.mia_director import walk_room
        screen = getattr(self, 'current_screen', None)
        if screen is None:
            return None
        width = getattr(self, 'screen_width', None) or screen.width()
        return walk_room(self.pos().x(), self.width(), screen.topLeft().x(), width)

    def _life_walk_acts(self, pose: str):
        """The acts a walk `pose` ('left_walk'/'right_walk') plays, as the engine plays it."""
        conf = getattr(self, 'pet_conf', None)
        names = getattr(conf, 'act_name', [])
        if pose in names:
            return conf.random_act[names.index(pose)]
        act = getattr(conf, 'act_dict', {}).get(pose)
        return [act] if act is not None else []

    def _life_walk_room(self):
        """(room, need) for the director's random walk: her room toward each side and one full
        walk that way at the current display scale. None if her screen is not known yet."""
        from DyberPet.mia_director import walk_distance
        room = self._life_room_now()
        if room is None:
            return None
        scale = float(getattr(settings, 'pet_display_scale', 1.0))
        need = {side: walk_distance(self._life_walk_acts(side + '_walk'), scale) for side in ('left', 'right')}
        return room, need

    def _life_turn_from_wall(self, pose: str) -> str:
        """A walk toward the wall she touches never starts: she walks the other way."""
        if pose not in ('left_walk', 'right_walk'):
            return pose
        side = self._life_wall_side()
        if side and pose.startswith(side):
            turned = ('right' if side == 'left' else 'left') + '_walk'
            self._mia_log('walk', 'turn %s -> %s (wall %s)' % (pose, turned, side))
            return turned
        return pose

    def _life_walk_identity(self):
        """(pose, source) of the walk that is moving her now: source 'inter' for the director /
        follow (interaction), 'anim' for the random animation; (None, None) if not walking."""
        from DyberPet.modules import is_walk
        interaction = getattr(self, 'workers', {}).get('Interaction')
        interact = getattr(interaction, 'interact', None)
        if interact == 'followTarget':
            return 'follow_cursor', 'inter'
        if interact in ('animat', 'customized', 'anim_acc'):
            if is_walk(getattr(settings, 'current_act', None)):
                return getattr(interaction, 'act_name', None) or 'walk', 'inter'
            return None, None
        act = getattr(settings, 'anim_act', None)
        if interact is None and is_walk(act):
            return getattr(act, 'act_name', None) or 'walk', 'anim'
        return None, None

    def _life_track_walk(self, requested_dx: int, moved_dx: int) -> None:
        """One walk step went through limit_in_screen (`_move_customized`). After
        WALK_STUCK_FRAMES steps clamped to zero in a row the walk ends, whoever started it."""
        from DyberPet.modules import WalkTracker
        pose, source = self._life_walk_identity()
        if pose is None:
            return
        tracker = getattr(self, '_life_walk', None)
        if tracker is None:
            tracker = self._life_walk = WalkTracker()
        if (tracker.pose, tracker.source) != (pose, source):
            self._life_walk_end()
            tracker.begin(pose, source)
        if tracker.step(requested_dx, moved_dx):
            self._life_stop_stuck_walk(source)

    def _life_walk_end(self, source: Optional[str] = None) -> None:
        """Log `walk end <pose> dx=<px> frames=<n> clamped=<n>` once for the walk that ended
        (only if it came from `source`, when given)."""
        tracker = getattr(self, '_life_walk', None)
        if tracker is None or not tracker.active or (source is not None and tracker.source != source):
            return
        line = tracker.end()
        if line:
            self._mia_log('walk', line)

    def _life_anim_walk_done(self) -> None:
        """The random animation's walk clip ended (or was cut)."""
        self._life_walk_end('anim')

    def _life_stop_stuck_walk(self, source: str) -> None:
        """Against a wall the window cannot move: end the walk so the director decides again."""
        self._life_walk_end()
        workers = getattr(self, 'workers', {})
        try:
            if source == 'inter':
                interaction = workers.get('Interaction')
                if getattr(interaction, 'interact', None) == 'followTarget' \
                        and hasattr(self, '_mia_stop_follow_cursor'):
                    self._mia_stop_follow_cursor()
                elif interaction is not None:
                    interaction.stop_interact()
            elif 'Animation' in workers:
                workers['Animation'].skip_clip()
        except Exception:
            logging.getLogger(__name__).exception('_life_stop_stuck_walk failed (ignored)')

    def _life_log_screen(self) -> None:
        """One start line: `screen <geometry> dpr=<x> scale=<pet_display_scale>`."""
        try:
            screen = self.current_screen
            self._mia_log('screen', '%d,%d %dx%d dpr=%.2f scale=%.3f' % (
                screen.x(), screen.y(), screen.width(), screen.height(), self.devicePixelRatioF(),
                float(getattr(settings, 'pet_display_scale', 1.0))))
        except Exception:
            logging.getLogger(__name__).exception('_life_log_screen failed (ignored)')

    def _life_holds_animation(self) -> bool:
        climbing = bool(getattr(getattr(self, 'mia_micro_ticker', None), 'is_climbing', False))
        talking = bool(getattr(getattr(self, 'talk_controller', None), 'active', False))
        return climbing or talking

    # --- M3: frames at display size --------------------------------------------------------
    def _life_sync_frames(self) -> bool:
        """Point the frame store at the current Pet Scale and screen devicePixelRatio and
        publish the resulting on-screen scale for per-frame movement. True when it changed."""
        store = getattr(self, 'frame_store', None)
        if store is None:
            # Legacy pixmaps are stretched by the Pet Scale itself.
            settings.pet_display_scale = settings.tunable_scale
            return False
        role_scale = float(getattr(getattr(self, 'pet_conf', None), 'scale', 1.0) or 1.0)
        changed = store.configure(settings.tunable_scale * role_scale, self.devicePixelRatioF())
        settings.pet_display_scale = store.display_scale() / role_scale
        return changed

    def _life_frame_size(self):
        """Logical (width, height) of the pet's frames on screen (the shown size)."""
        store = getattr(self, 'frame_store', None)
        if store is not None:
            return store.logical_frame_size()
        scale = settings.pet_display_scale
        return self.pet_conf.width * scale, self.pet_conf.height * scale

    # --- M3.1: one geometry for window, floor, drag and screen checks ----------------------
    def _life_window_size(self, bar_w: int, statbar_h: int):
        """Pet window (width, height): the shown frame plus the two status bars above it.
        Rounded like the label (frames.label_size), so the feet sit on the window bottom."""
        from DyberPet.frames import logical_px
        frame_w, frame_h = self._life_frame_size()
        return int(max(bar_w + statbar_h, logical_px(frame_w))), int(2 * statbar_h + logical_px(frame_h))

    def _life_floor_y(self) -> int:
        """Window y at which her feet (the window bottom) rest on the work area's bottom."""
        return self.current_screen.topLeft().y() + self.screen_height - self.height()

    def _life_sprite_rect(self):
        """Global rect of the frame she shows: bottom-centred label in the pet window."""
        from PySide6.QtCore import QPoint, QRect, QSize
        label_w, label_h = self.label.width(), self.label.height()
        return QRect(self.pos() + QPoint(self.width() // 2 - label_w // 2, self.height() - label_h),
                     QSize(label_w, label_h))

    def _life_fit_window(self, bar_w: int, statbar_h: int) -> None:
        """The shown size changed (Pet Scale or another screen's devicePixelRatio): resize the
        window around her feet (bottom centre stays) and move the floor with it."""
        width, height = self._life_window_size(bar_w, statbar_h)
        if (width, height) == (self.width(), self.height()):
            return
        x = self.pos().x() + (self.width() - width) // 2
        y = self.pos().y() + self.height() - height
        self.setFixedSize(width, height)
        self.move(x, y)
        if getattr(self, 'current_screen', None) is not None and hasattr(self, 'screen_height'):
            self.floor_pos = self._life_floor_y()

    def _life_add_climb_down(self) -> None:
        """'climb_down': the climb clip backwards, so climbing down does not look like
        reaching up while sliding down. Runtime-only action (act_conf keeps its 29).

        Every parallel list of the pet config gets its entry (M3.1, audit 2.6), with weight 0:
        the random pool (settings.act_data, from pet_conf.json) never lists it; only the
        climb director plays it, by name."""
        from DyberPet.conf import Act
        from DyberPet.mia_director import CLIMB_DOWN_POSE
        conf = self.pet_conf
        climb = conf.act_dict.get('climb')
        if climb is None or CLIMB_DOWN_POSE in conf.act_dict:
            return
        down = Act(climb.images[::-1], CLIMB_DOWN_POSE, climb.act_num, False, None,
                   climb.frame_move, climb.frame_refresh, climb.anchor)
        conf.act_dict[CLIMB_DOWN_POSE] = down
        conf.random_act.append([down])
        conf.act_name.append(CLIMB_DOWN_POSE)
        conf.act_type.append([0, 0])
        conf.act_sound.append([])
        conf.act_prob.append(0.0)

    def _life_climb_speed(self) -> float:
        from DyberPet.mia_director import climb_speed_px_s
        climb = self.pet_conf.act_dict.get('climb')
        if climb is None:
            return 0.0
        return climb_speed_px_s(climb.frame_move, settings.pet_display_scale, climb.frame_refresh,
                                self.pet_conf.interact_speed / 1000.0)

    def _life_hold_climb_pose(self) -> None:
        """Hanging on the wall: the climb clip stays on its current frame. M3.3: it is held, not
        stopped, so the engine never falls back to another clip while she hangs."""
        interaction = getattr(self, 'workers', {}).get('Interaction')
        if interaction is not None and getattr(interaction, 'interact', None) not in (None, 'mousedrag'):
            if hasattr(interaction, 'hold'):
                interaction.hold()
            else:
                interaction.stop_interact()

    def _life_snap_to_wall(self, side: str) -> None:
        """Put her hands on the screen edge she climbs (the sprite is centred in a wider window
        and has transparent margins)."""
        try:
            climb = self.pet_conf.act_dict.get('climb')
            if climb is None or not len(climb.images):
                return
            left, right = self._life_climb_span(climb)
            label_w = self.label.width()
            label_x = self.pos().x() + (self.width() - label_w) // 2
            screen = self.current_screen
            if side == 'right':
                new_label_x = screen.x() + screen.width() - right
            else:
                # Mirrored for the left wall: her reaching side becomes the label's left.
                new_label_x = screen.x() - (label_w - right)
            self.move(int(self.pos().x() + new_label_x - label_x), self.pos().y())
        except Exception:
            logging.getLogger(__name__).exception('_life_snap_to_wall failed (ignored)')

    @staticmethod
    def _life_climb_span(climb):
        """Opaque span of the climb's first frame: computed once per action group and display
        configuration (FrameStore cache), not on every climb start (M3.1, audit 2.13)."""
        from DyberPet.frames import opaque_span
        images = climb.images
        store, names = getattr(images, 'store', None), getattr(images, 'names', None)
        if store is not None and names:
            return store.opaque_span(names[0])
        return opaque_span(images[0])
