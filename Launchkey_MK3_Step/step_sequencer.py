"""A 16-step drum sequencer on the Launchkey MK3's pads, arrows, ► button and pots.

Pads: one page of 16 steps (top row = steps 1-8, bottom row = 9-16) for the Drum Rack pad
selected in Live. Tap a step to add a hit; tap a hit to remove it. Hold ► (the button right of
the pads) and tap to make a hit accented, TR-909 style, or to make it normal again. Hold one or
more steps and turn a pot to edit just those hits.

Up/Down arrows: previous/next loaded Drum Rack pad.

Pots: Velocity, Accent amount, Swing, Length, Chance, Step size, Page, Bars. Swing is set per
drum, like the per-instrument shuffle on Roland's TR-909: it pushes the drum's 16ths between the
8ths later, and the beat and the "and" stay on the grid. The Launchkey shows a pot's name and
value when it's turned; in step mode those are the step sequencer's.
"""
import Live
from ableton.v2.base import listens, liveobj_changed, liveobj_valid
from ableton.v2.control_surface import Component
from ableton.v2.control_surface.control import ButtonControl, InputControl, control_list, control_matrix
from novation.colors import CLIP_COLOR_TABLE, Color, Rgb

from . import knobs, step_grid
from .pattern import (SWING_TOLERANCE, PatternEditor, hit_velocity, is_accented, sixteenth_position,
                      swing_delay_for)

NUM_STEPS = 16
GRID_WIDTH = 8
EDIT_DELAY_TICKS = 1  # pot edits are applied at most every ~100 ms, so a sweep is a few undo steps

NORMAL, ACCENTED = 'normal', 'accented'

OUTSIDE_LOOP_COLOR = Rgb.BLACK
EMPTY_STEP_COLOR = Rgb.BLACK
BEAT_STEP_COLOR = Rgb.DARK_GREY
ACCENT_HIT_COLOR = Rgb.WHITE
FALLBACK_HIT_COLOR = Rgb.RED
PLAYHEAD_COLOR = Rgb.GREY
PLAYHEAD_ON_HIT_COLOR = Rgb.GREEN
LANE_BUTTON_COLOR = Rgb.WHITE_HALF
LANE_BUTTON_PRESSED_COLOR = Rgb.WHITE
ACCENT_BUTTON_COLOR = Rgb.ORANGE_HALF
ACCENT_BUTTON_PRESSED_COLOR = Rgb.ORANGE

TITLE = 'Step Sequencer'
NOTHING_TO_SWING = ' no 16ths'  # shown after the swing % when the drum has no 16ths between the 8ths
BLANK = ' '  # the Launchkey script never sends empty text, so blank with a space


class StepSequencerComponent(Component):
    step_buttons = control_matrix(ButtonControl)
    prev_lane_button = ButtonControl(color=LANE_BUTTON_COLOR, pressed_color=LANE_BUTTON_PRESSED_COLOR)
    next_lane_button = ButtonControl(color=LANE_BUTTON_COLOR, pressed_color=LANE_BUTTON_PRESSED_COLOR)
    accent_button = ButtonControl(color=ACCENT_BUTTON_COLOR, pressed_color=ACCENT_BUTTON_PRESSED_COLOR)
    pots = control_list(InputControl, control_count=knobs.NUM_KNOBS)

    def __init__(self, show_notification=None, schedule=None, note_factory=None, *a, **k):
        self._show_notification = show_notification or (lambda *_: None)
        self._schedule = schedule
        self._note_factory = note_factory
        self._track = None
        self._drum_rack = None
        self._clip = None
        self._page_index = 0
        self._resolution_index = knobs.DEFAULT_RESOLUTION_INDEX
        self._accent_amount = None
        self._accent_amount_in_clip = None
        self._lane_swing = {}  # drum pad note -> swing % dialled in on the swing pot
        self._held_steps = {}  # step -> keep the hit on release (False = tap to remove)
        self._pending_edits = {}
        self._edit_flush_scheduled = False
        self._step_states = {}
        self._pot_name_displays = None
        self._pot_value_displays = None
        self._pot_values = [BLANK] * knobs.NUM_KNOBS  # last value shown for each pot
        self._playhead_step = None
        super().__init__(*a, **k)
        self.__on_detail_clip_changed.subject = self.song.view
        self.__on_selected_scene_changed.subject = self.song.view
        self.__on_is_playing_changed.subject = self.song

    def set_targets(self, track, drum_rack):
        """Point the sequencer at the selected track and its Drum Rack (either may be None)."""
        self._track = track if self._is_clip_track(track) else None
        self._drum_rack = drum_rack if liveobj_valid(drum_rack) else None
        self.__on_playing_slot_index_changed.subject = self._track
        self.__on_track_color_changed.subject = self._track
        self.__on_selected_drum_pad_changed.subject = (
            self._drum_rack.view if self._drum_rack is not None else None)
        self._update_clip()
        if self.is_enabled():
            self._show_lane_name()

    def update(self):
        super().update()
        if self.is_enabled():
            self._refresh()
            self._show_lane_name()
        else:
            self._held_steps.clear()

    def set_pot_name_displays(self, displays):
        """What the Launchkey shows when a pot is turned: its name (and, below, its value)."""
        self._pot_name_displays = list(displays) if displays is not None else None
        self._send_pot_texts(self._pot_name_displays, knobs.KNOB_NAMES)

    def set_pot_value_displays(self, displays):
        self._pot_value_displays = list(displays) if displays is not None else None
        self._send_pot_texts(self._pot_value_displays, self._pot_values)

    @staticmethod
    def _send_pot_texts(displays, texts):
        for display, text in zip(displays or (), texts):
            if display is not None:
                display.display_message(text)

    def _show_pot_value(self, pot, text):
        self._pot_values[pot] = text
        if self._pot_value_displays is not None:
            self._send_pot_texts(self._pot_value_displays[pot:pot + 1], [text])

    def set_step_buttons(self, buttons):
        # The pads arrive (and leave) with the layer, after update(): draw them as they arrive.
        self.step_buttons.set_control_element(buttons)
        self._draw_steps()

    # --- Steps ---

    @step_buttons.pressed
    def step_buttons(self, button):
        step = self._step_index(button)
        pitch = self._lane_pitch()
        if pitch is None:
            self._notify(TITLE, 'Load a Drum Rack')
            return
        if not liveobj_valid(self._clip) and self._create_clip() is None:
            return
        if not self._step_in_loop(step):
            return
        editor = self._editor()
        window = self._step_window(step)
        if editor.has_hit(pitch, *window):
            if self.accent_button.is_pressed:
                self._toggle_accent(editor, pitch, window)
                self._held_steps[step] = True
            else:
                self._held_steps[step] = False
        else:
            self._add_hit(editor, pitch, window, accented=self.accent_button.is_pressed)
            self._held_steps[step] = True
        self._refresh()

    @step_buttons.released
    def step_buttons(self, button):
        step = self._step_index(button)
        keep = self._held_steps.pop(step, True)
        pitch, editor = self._lane_pitch(), self._editor()
        if not keep and pitch is not None and editor is not None:
            editor.remove_hits(pitch, *self._step_window(step))
            self._refresh()

    def _add_hit(self, editor, pitch, window, accented):
        window_start, step_length = window
        accent_amount = self._current_accent_amount(editor)
        level = editor.lane_level(pitch, accent_amount)
        editor.add_hit(
            pitch=pitch,
            start=window_start + self._swing_offset(editor, pitch, window_start),
            duration=editor.lane_duration(pitch, step_length),
            velocity=hit_velocity(level, accent_amount, accented),
            probability=editor.lane_chance(pitch),
            accented=accented)

    def _toggle_accent(self, editor, pitch, window):
        accented = not any(is_accented(note) for note in editor.notes(pitch, *window))
        accent_amount = self._current_accent_amount(editor)
        editor.set_accented(pitch, [window], accented, editor.lane_level(pitch, accent_amount), accent_amount)

    def _swing_offset(self, editor, pitch, window_start):
        """How far after its step a new hit goes: swung like the drum's other hits."""
        position, offset = sixteenth_position(window_start)
        if offset > SWING_TOLERANCE or not step_grid.is_swung(position):
            return 0.0  # the beat, the "and", or a step off the 16th grid (1/32, triplets)
        percent = self._lane_swing.get(pitch)
        if percent is None:
            percent = editor.swing_percent(pitch)
        return swing_delay_for(percent)

    # --- Lanes ---

    @next_lane_button.pressed
    def next_lane_button(self, _):
        self._move_lane(1)

    @prev_lane_button.pressed
    def prev_lane_button(self, _):
        self._move_lane(-1)

    def _move_lane(self, delta):
        rack = self._drum_rack
        if not liveobj_valid(rack):
            return
        pads = rack.drum_pads
        loaded_notes = [pad.note for pad in pads if len(pad.chains) > 0]
        current = self._lane_pad()
        note = step_grid.next_lane(current.note if current is not None else None, delta, loaded_notes)
        if note is not None:
            rack.view.selected_drum_pad = pads[note]

    # --- Pots ---

    @pots.value
    def pots(self, value, pot):
        handlers = (self._set_velocity, self._set_accent_amount, self._set_swing, self._set_length,
                    self._set_chance, self._set_step_size, self._set_page, self._set_bars)
        handlers[pot.index](value)

    def _set_velocity(self, knob_value):
        level = knobs.velocity(knob_value)
        self._show_pot_value(knobs.VELOCITY, str(level))
        self._edit_lane('velocity', lambda editor, pitch, windows: editor.set_level(
            pitch, level, self._current_accent_amount(editor), windows))

    def _set_accent_amount(self, knob_value):
        amount = knobs.accent(knob_value)
        self._show_pot_value(knobs.ACCENT, '+{}'.format(amount))
        editor = self._editor()
        if editor is not None and self._accent_amount_in_clip is None:
            self._accent_amount_in_clip = self._current_accent_amount(editor)
        self._accent_amount = amount
        if editor is not None:
            self._defer('accent', self._apply_accent_amount)

    def _apply_accent_amount(self):
        editor = self._editor()
        if editor is not None and self._accent_amount_in_clip is not None:
            editor.set_accent_amount(self._accent_amount, self._accent_amount_in_clip)
            self._accent_amount_in_clip = self._accent_amount

    def _set_swing(self, knob_value):
        """Swing the selected drum only, like the per-instrument shuffle on Roland's TR-909."""
        percent = knobs.swing(knob_value)
        pitch, editor = self._lane_pitch(), self._editor()
        nothing_to_swing = pitch is not None and editor is not None and not editor.has_16ths_between(pitch)
        self._show_pot_value(knobs.SWING, '{}%{}'.format(percent, NOTHING_TO_SWING if nothing_to_swing else ''))
        if pitch is None:
            return
        self._keep_held_steps()
        self._lane_swing[pitch] = percent
        if editor is not None:
            self._defer(('swing', pitch), lambda: self._apply_swing(pitch))

    def _apply_swing(self, pitch):
        editor = self._editor()
        if editor is None or pitch not in self._lane_swing:
            return
        editor.swing(pitch, self._lane_swing[pitch])
        editor.select_notes(pitch)  # shows in Live's clip view which notes the swing pot moves

    def _set_length(self, knob_value):
        factor = knobs.length_factor(knob_value)
        self._show_pot_value(knobs.LENGTH, '{}%'.format(int(round(factor * 100))))
        duration = factor * self._step_length()
        self._edit_lane('length', lambda editor, pitch, windows: editor.set_duration(pitch, duration, windows))

    def _set_chance(self, knob_value):
        probability = knobs.chance(knob_value)
        self._show_pot_value(knobs.CHANCE, '{}%'.format(int(round(probability * 100))))
        self._edit_lane('chance', lambda editor, pitch, windows: editor.set_chance(pitch, probability, windows))

    def _set_step_size(self, knob_value):
        index = knobs.resolution_index(knob_value)
        self._show_pot_value(knobs.STEP_SIZE, knobs.RESOLUTIONS[index].name)
        if index != self._resolution_index:
            offset = self._page_time() - self._loop_start()
            self._resolution_index = index
            self._page_index = int((offset + step_grid.EPSILON) // self._page_length())
            self._refresh()

    def _set_page(self, knob_value):
        num_pages = self._num_pages()
        index = knobs.page_index(knob_value, num_pages)
        self._show_pot_value(knobs.PAGE, '{}/{}'.format(index + 1, num_pages))
        if index != self._page_index:
            self._page_index = index
            self._refresh()

    def _set_bars(self, knob_value):
        num_bars = knobs.bars(knob_value)
        self._show_pot_value(knobs.BARS, str(num_bars))
        editor = self._editor()
        if editor is not None:
            length = num_bars * self._bar_length()
            self._defer('bars', lambda: editor.set_loop_length(length))

    def _edit_lane(self, key, edit):
        """Apply a pot edit to the held steps, or to the whole lane when no step is held."""
        pitch, editor = self._lane_pitch(), self._editor()
        if pitch is None or editor is None:
            return
        self._keep_held_steps()
        windows = [self._step_window(step) for step in self._held_steps] or None
        self._defer(key, lambda: edit(editor, pitch, windows))

    def _keep_held_steps(self):
        for step in self._held_steps:
            self._held_steps[step] = True  # an edited step keeps its hit when released

    def _defer(self, key, edit):
        self._pending_edits[key] = edit
        if self._schedule is None:
            self._apply_pending_edits()
        elif not self._edit_flush_scheduled:
            self._edit_flush_scheduled = True
            self._schedule(EDIT_DELAY_TICKS, self._apply_pending_edits)

    def _apply_pending_edits(self):
        self._edit_flush_scheduled = False
        edits, self._pending_edits = self._pending_edits, {}
        if liveobj_valid(self._clip):
            for edit in edits.values():
                edit()
        self._refresh()

    def _current_accent_amount(self, editor):
        if self._accent_amount is None:
            self._accent_amount = editor.accent_amount()
        return self._accent_amount

    # --- Track, lane and clip ---

    def _is_clip_track(self, track):
        return liveobj_valid(track) and any(track == candidate for candidate in self.song.tracks)

    def _lane_pad(self):
        if not liveobj_valid(self._drum_rack):
            return None
        pad = self._drum_rack.view.selected_drum_pad
        return pad if liveobj_valid(pad) else None

    def _lane_pitch(self):
        pad = self._lane_pad()
        return pad.note if pad is not None else None

    def _show_lane_name(self):
        pad = self._lane_pad()
        self._notify(TITLE, pad.name if pad is not None else 'Load a Drum Rack')

    def _notify(self, upper_line, lower_line):
        self._show_notification(upper_line, lower_line)

    def _editor(self):
        if not liveobj_valid(self._clip):
            return None
        return PatternEditor(self._clip, self._note_factory or Live.Clip.MidiNoteSpecification)

    def _update_clip(self):
        clip = self._find_clip()
        if liveobj_changed(clip, self._clip):
            if liveobj_valid(self._clip):
                # Settings read from the previous clip don't carry over; ones dialled in before
                # the first clip existed do (they apply to the clip the first tap creates).
                self._accent_amount = None
                self._lane_swing = {}
            self._clip = clip
            self._page_index = 0
            self._accent_amount_in_clip = None
            self._pending_edits.clear()
            self.__on_notes_changed.subject = clip
            self.__on_playing_position_changed.subject = clip
            self.__on_playing_status_changed.subject = clip
            self.__on_loop_start_changed.subject = clip
            self.__on_loop_end_changed.subject = clip
        self._refresh()

    def _find_clip(self):
        """The clip shown in Live's clip view, else the selected scene's clip, else the playing one."""
        if not liveobj_valid(self._track):  # also covers a track that was just deleted
            return None
        candidates = (
            self.song.view.detail_clip,
            self._clip_in_slot(self._selected_clip_slot()),
            self._clip_in_slot(self._playing_clip_slot()))
        return next((clip for clip in candidates if self._is_sequenceable(clip)), None)

    def _is_sequenceable(self, clip):
        return (liveobj_valid(clip) and clip.is_midi_clip and not clip.is_arrangement_clip
                and clip.canonical_parent.canonical_parent == self._track)

    @staticmethod
    def _clip_in_slot(slot):
        return slot.clip if slot is not None and slot.has_clip else None

    def _selected_clip_slot(self):
        selected = self.song.view.selected_scene
        index = next((i for i, scene in enumerate(self.song.scenes) if scene == selected), None)
        return self._clip_slot(index)

    def _playing_clip_slot(self):
        if not liveobj_valid(self._track):
            return None
        return self._clip_slot(self._track.playing_slot_index)

    def _clip_slot(self, index):
        if not liveobj_valid(self._track) or index is None:
            return None
        slots = self._track.clip_slots
        return slots[index] if 0 <= index < len(slots) else None

    def _create_clip(self):
        """Create a one-bar clip in the selected scene's slot of the target track."""
        slot = self._selected_clip_slot()
        if slot is None or slot.has_clip:
            self._notify(TITLE, 'Pick empty slot')
            return None
        song = self.song
        slot.create_clip(step_grid.bar_length(song.signature_numerator, song.signature_denominator))
        if song.is_playing:
            slot.fire(force_legato=True, launch_quantization=Live.Song.Quantization.q_no_q)
        song.view.detail_clip = slot.clip
        self._update_clip()
        return self._clip

    # --- Pages and timing ---

    def _step_length(self):
        return knobs.RESOLUTIONS[self._resolution_index].step_length

    def _page_length(self):
        return step_grid.page_length(NUM_STEPS, self._step_length())

    def _bar_length(self):
        clip = self._clip if liveobj_valid(self._clip) else self.song
        return step_grid.bar_length(clip.signature_numerator, clip.signature_denominator)

    def _loop_start(self):
        return self._clip.loop_start if liveobj_valid(self._clip) else 0.0

    def _loop_length(self):
        return self._clip.loop_end - self._clip.loop_start if liveobj_valid(self._clip) else 0.0

    def _num_pages(self):
        if not liveobj_valid(self._clip):
            return 1
        return step_grid.num_pages(self._loop_length(), self._page_length())

    def _page_time(self):
        index = min(self._page_index, self._num_pages() - 1)
        return self._loop_start() + index * self._page_length()

    def _step_window(self, step):
        return (step_grid.step_start(self._page_time(), step, self._step_length()), self._step_length())

    def _step_in_loop(self, step):
        if not liveobj_valid(self._clip):
            return True
        return self._step_window(step)[0] < self._clip.loop_end - step_grid.EPSILON

    # --- Drawing ---

    def _refresh(self):
        self._step_states = self._read_step_states()
        self._playhead_step = self._read_playhead_step()
        self._draw_steps()

    def _update_playhead(self):
        step = self._read_playhead_step()
        if step != self._playhead_step:
            self._playhead_step = step
            self._draw_steps()

    def _read_step_states(self):
        pitch, editor = self._lane_pitch(), self._editor()
        if pitch is None or editor is None:
            return {}
        page_time, step_length = self._page_time(), self._step_length()
        states = {}
        for note in editor.notes(pitch, page_time, NUM_STEPS * step_length):
            step = step_grid.step_for_time(note.start_time, page_time, step_length, NUM_STEPS)
            if step is not None and states.get(step) != ACCENTED:
                states[step] = ACCENTED if is_accented(note) else NORMAL
        return states

    def _read_playhead_step(self):
        clip = self._clip
        if not liveobj_valid(clip) or not self.song.is_playing or not clip.is_playing:
            return None
        return step_grid.step_for_time(clip.playing_position, self._page_time(), self._step_length(), NUM_STEPS)

    def _draw_steps(self):
        if not self.is_enabled():
            return
        hit_color = self._hit_color()
        for button in self.step_buttons:
            button.color = self._step_color(self._step_index(button), hit_color)

    def _step_color(self, step, hit_color):
        if not self._step_in_loop(step):
            return OUTSIDE_LOOP_COLOR
        state = self._step_states.get(step)
        if step == self._playhead_step:
            return PLAYHEAD_ON_HIT_COLOR if state else PLAYHEAD_COLOR
        if state == ACCENTED:
            return ACCENT_HIT_COLOR
        if state == NORMAL:
            return hit_color
        return BEAT_STEP_COLOR if self._is_beat_step(step) else EMPTY_STEP_COLOR

    def _is_beat_step(self, step):
        time = self._step_window(step)[0]
        return abs(time - round(time)) < step_grid.EPSILON

    def _hit_color(self):
        palette_index = CLIP_COLOR_TABLE.get(self._track.color) if liveobj_valid(self._track) else None
        return Color(palette_index) if palette_index is not None else FALLBACK_HIT_COLOR

    @staticmethod
    def _step_index(button):
        row, column = button.coordinate
        return row * GRID_WIDTH + column

    # --- Live listeners ---

    @listens('detail_clip')
    def __on_detail_clip_changed(self):
        self._update_clip()

    @listens('selected_scene')
    def __on_selected_scene_changed(self):
        self._update_clip()

    @listens('playing_slot_index')
    def __on_playing_slot_index_changed(self):
        self._update_clip()

    @listens('color')
    def __on_track_color_changed(self):
        self._draw_steps()

    @listens('selected_drum_pad')
    def __on_selected_drum_pad_changed(self):
        self._refresh()
        if self.is_enabled():
            self._show_lane_name()

    @listens('notes')
    def __on_notes_changed(self):
        self._refresh()

    @listens('loop_start')
    def __on_loop_start_changed(self):
        self._refresh()

    @listens('loop_end')
    def __on_loop_end_changed(self):
        self._refresh()

    @listens('playing_status')
    def __on_playing_status_changed(self):
        self._update_playhead()

    @listens('is_playing')
    def __on_is_playing_changed(self):
        self._update_playhead()

    @listens('playing_position')
    def __on_playing_position_changed(self):
        self._update_playhead()
