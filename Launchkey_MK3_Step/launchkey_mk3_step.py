"""Ableton's stock Launchkey MK3 script with a drum step sequencer on the 5th pad-mode pad.

Hold Shift and press the 5th pad on the bottom row ("Custom Mode 1") to turn the pads into a
16-step grid for the selected Drum Rack pad (see step_sequencer.py for the controls). Pick any
other pad mode, or press Shift + the 5th pad again, to leave it. Everything else behaves
exactly like the stock script.

In step mode the Launchkey shows its session layout, so it doesn't report Shift + Session (to
the Launchkey that changes nothing): only Shift reaches the script. A Shift press with nothing
else in it is therefore taken as Shift + Session.
"""
import logging
import time

from ableton.v2.base import listens
from ableton.v2.control_surface import Layer
from Launchkey_MK3 import midi
from Launchkey_MK3.launchkey_mk3 import Launchkey_MK3

from .step_sequencer import StepSequencerComponent

logger = logging.getLogger(__name__)

# The stock script names its pad modes after the Launchkey's pad-mode bytes (CC 3, channel 16).
# Byte 5 is the hardware's "Custom Mode 1" pad, which the stock script calls "custom2".
STEP_PAD_MODE = 'custom2'
STEP_PAD_MODE_BYTE = 5
SESSION_PAD_MODE = 'session'
DEVICE_SELECT_PAD_MODE = 'device_select'
# Holding Device Select, or the "..." (Navigation) button, borrows the pads for a moment; the
# Launchkey then reports the layout it returns to, which in step mode is the session layout.
DEVICE_SELECT_PAD_MODE_BYTE = 9
NAVIGATION_PAD_MODE_BYTE = 10

PAD_LAYOUT_STATUS_BYTE = 0xBF  # Control Change on channel 16
PAD_LAYOUT_CC = 3
SHIFT_STATUS_BYTE = 0xB0  # Control Change on channel 1
SHIFT_CC = 108
PAD_LAYOUT_ECHO_TIMEOUT = 1.0  # seconds

STEP_SEQUENCER_LAYER_PRIORITY = 1  # above the session grid and the stock custom-mode background


def is_pad_layout_message(midi_bytes):
    return (len(midi_bytes) == 3 and midi_bytes[0] == PAD_LAYOUT_STATUS_BYTE
            and midi_bytes[1] == PAD_LAYOUT_CC)


def is_shift_message(midi_bytes):
    return len(midi_bytes) == 3 and midi_bytes[0] == SHIFT_STATUS_BYTE and midi_bytes[1] == SHIFT_CC


class Launchkey_MK3_Step(Launchkey_MK3):

    def __init__(self, *a, **k):
        self._step_sequencer = None
        self._pending_pad_layout_echoes = []
        self._entering_step_mode = False
        self._resume_step_mode = False
        self._shift_alone = False  # Shift is down and nothing else has come in since
        super().__init__(*a, **k)

    def _create_components(self):
        super()._create_components()
        self._step_sequencer = StepSequencerComponent(
            name='Step_Sequencer',
            is_enabled=False,
            show_notification=self._notification_component.show_notification,
            schedule=self.schedule_message,
            layer=Layer(priority=STEP_SEQUENCER_LAYER_PRIORITY,
                        step_buttons='clip_launch_matrix',
                        next_lane_button='up_button',
                        prev_lane_button='down_button',
                        accent_button=self._elements.scene_launch_buttons_raw[0],
                        pots='pots',
                        pot_name_displays='pot_parameter_name_displays',
                        pot_value_displays='pot_parameter_value_displays'))
        self.__on_pad_mode_selected.subject = self._pad_modes
        self.__on_pad_mode_byte.subject = self._pad_modes
        self._update_step_sequencer_targets()

    def on_identified(self, midi_bytes):
        step_mode = self._is_step_mode_active()
        if step_mode:
            # Live re-sends the last pad layout when it reconnects; keep the pads in the layout
            # the sequencer draws on.
            self._last_pad_layout_byte = midi.PAD_SESSION_LAYOUT
        super().on_identified(midi_bytes)
        if step_mode:
            self._send_pad_layout(midi.PAD_SESSION_LAYOUT)

    def _target_track_changed(self):
        super()._target_track_changed()
        self._update_step_sequencer_targets()

    def _drum_group_changed(self):
        super()._drum_group_changed()
        self._update_step_sequencer_targets()

    def _update_step_sequencer_targets(self):
        if self._step_sequencer is not None:
            self._step_sequencer.set_targets(self._target_track.target_track,
                                             self._drum_group_finder.drum_group)

    # --- Entering and leaving step mode ---

    def _is_step_mode_active(self):
        return self._step_sequencer is not None and self._step_sequencer.is_enabled()

    @listens('selected_mode')
    def __on_pad_mode_selected(self, mode):
        if mode == STEP_PAD_MODE and not self._is_step_mode_active():
            self._entering_step_mode = True
            self._resume_step_mode = False
            self._step_sequencer.set_enabled(True)
            # In Custom Mode 1 the pads play notes on the keyboard port. Switch the hardware to
            # the session layout so the pads report to this script and can be lit by it.
            self._send_pad_layout(midi.PAD_SESSION_LAYOUT)
        elif mode != STEP_PAD_MODE and self._is_step_mode_active():
            self._entering_step_mode = False
            self._resume_step_mode = mode == DEVICE_SELECT_PAD_MODE
            self._step_sequencer.set_enabled(False)

    @listens('mode_byte')
    def __on_pad_mode_byte(self, mode_byte):
        logger.info('Pad mode byte %s, step mode active: %s', mode_byte, self._is_step_mode_active())
        if mode_byte == STEP_PAD_MODE_BYTE:
            self._on_step_mode_pad_pressed()
        elif mode_byte == midi.PAD_SESSION_LAYOUT and self._resume_step_mode:
            self._resume_after_borrowed_pads()
        elif mode_byte != DEVICE_SELECT_PAD_MODE_BYTE:
            self._resume_step_mode = False  # another mode was picked meanwhile
        if self._is_step_mode_active():
            self._last_pad_layout_byte = midi.PAD_SESSION_LAYOUT

    def _on_step_mode_pad_pressed(self):
        if not self._is_step_mode_active():
            return
        if self._entering_step_mode:
            self._entering_step_mode = False
        else:
            self._go_to_session()  # Shift + the 5th pad again

    def _go_to_session(self):
        self._pad_modes.selected_mode = SESSION_PAD_MODE
        self._send_pad_layout(midi.PAD_SESSION_LAYOUT)

    def _watch_shift(self, midi_bytes):
        """Take a Shift press with nothing else in it as Shift + Session (see the module notes)."""
        if not is_shift_message(midi_bytes):
            self._shift_alone = False
        elif midi_bytes[2]:
            self._shift_alone = True
        elif self._shift_alone:
            self._shift_alone = False
            if self._is_step_mode_active():
                self._go_to_session()

    def _pause_for_navigation(self):
        # The stock script ignores Navigation mode (it never reaches its pad modes), so it's
        # caught on the way in: pause the grid while Navigation has the pads.
        if self._is_step_mode_active():
            self._resume_step_mode = True
            self._step_sequencer.set_enabled(False)

    def _resume_after_borrowed_pads(self):
        # Back from Device Select or Navigation: return to the sequencer, not the session grid.
        self._resume_step_mode = False
        self._pad_modes.selected_mode = STEP_PAD_MODE
        self._entering_step_mode = False

    def _send_pad_layout(self, layout_byte):
        self._elements.pad_layout_switch.send_value(layout_byte, force=True)

    # --- The Launchkey echoes back every pad-layout change it is sent; drop those echoes ---

    def _send_midi(self, midi_event_bytes, optimized=True):
        if is_pad_layout_message(midi_event_bytes):
            self._pending_pad_layout_echoes.append((midi_event_bytes[2], time.monotonic()))
        return super()._send_midi(midi_event_bytes, optimized=optimized)

    def process_midi_bytes(self, midi_bytes, midi_processor):
        self._watch_shift(midi_bytes)
        if is_pad_layout_message(midi_bytes):
            if self._consume_pad_layout_echo(midi_bytes[2]):
                return
            if midi_bytes[2] == NAVIGATION_PAD_MODE_BYTE:
                self._pause_for_navigation()
        super().process_midi_bytes(midi_bytes, midi_processor)

    def _consume_pad_layout_echo(self, layout_byte):
        now = time.monotonic()
        self._pending_pad_layout_echoes = [
            (byte, sent_at) for byte, sent_at in self._pending_pad_layout_echoes
            if now - sent_at < PAD_LAYOUT_ECHO_TIMEOUT]
        for index, (byte, _) in enumerate(self._pending_pad_layout_echoes):
            if byte == layout_byte:
                del self._pending_pad_layout_echoes[index]
                return True
        return False
