"""End-to-end tests: the real Launchkey MK3 script plus the step sequencer, in a simulated Live.

The control surface runs on Ableton's own compiled framework (from the installed Live app), so
these need Python 3.11 (Live's version) and Ableton Live 12 in /Applications. The tests talk to
it with the exact MIDI the Launchkey MK3 sends, and check what it sends back and what it writes
into the clip.

Run from the project folder: python3.11 -m unittest discover tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'sim'))
import live_sim  # noqa: E402

PAD_NOTES = list(range(0x60, 0x68)) + list(range(0x70, 0x78))  # session-layout pads, steps 1-16
CC_CH1, CC_CH16, NOTE_CH1 = 0xB0, 0xBF, 0x90
PAD_LAYOUT, CUSTOM_MODE_1, SESSION, DRUM, DEVICE_SELECT, NAVIGATION = 3, 5, 2, 1, 9, 10
ACCENT_BUTTON, UP, DOWN = 104, 106, 107
SHIFT = 108  # on channel 1
FIRST_POT = 21
VELOCITY_POT, ACCENT_POT, SWING_POT, LENGTH_POT, CHANCE_POT, STEPS_POT, PAGE_POT, BARS_POT = range(8)

OFF, DARK_GREY, GREY, WHITE, RED, GREEN = 0, 1, 2, 3, 5, 21
# The Launchkey shows a pot's name and value when the pot is turned, from these system-exclusive
# messages (byte 6 = name or value, byte 7 = pot).
POT_NAME, POT_VALUE, FIRST_POT_DISPLAY = 7, 8, 0x38
STEP_MODE_POT_NAMES = ['Velocity', 'Accent', 'Swing', 'Length', 'Chance', 'Steps', 'Page', 'Bars']
BLANK = ' '  # the Launchkey script never sends empty text
KICK, RIM, SNARE = 36, 37, 38


@unittest.skipUnless(live_sim.is_available(), 'needs Python 3.11 and Ableton Live 12')
class SurfaceTestCase(unittest.TestCase):

    def setUp(self):
        self.sim = live_sim.LiveSim()
        from Launchkey_MK3_Step import create_instance
        self.surface = self.sim.start_surface(create_instance)
        self.leds = {}
        self.screen = {}
        self.pot_texts = {}
        self.read_output()

    def tearDown(self):
        self.surface.disconnect()

    # --- What the Launchkey sends ---

    def select_pad_mode(self, mode_byte):
        """The Launchkey reports a pad mode (picked, or held like Device Select)."""
        self.sim.receive(CC_CH16, PAD_LAYOUT, mode_byte, ticks=2)
        return self.read_output()

    def shift_and_pad(self, mode_byte=None):
        """Shift + a pad-mode pad. Like the real Launchkey, the mode is reported only when it
        changes: Shift + Session in step mode (already the session layout) sends just Shift."""
        self.button(CC_CH1, SHIFT, True)
        if mode_byte is not None:
            self.sim.receive(CC_CH16, PAD_LAYOUT, mode_byte, ticks=2)
        self.button(CC_CH1, SHIFT, False)
        self.sim.pump(ticks=2)
        return self.read_output()

    def enter_step_mode(self):
        return self.shift_and_pad(CUSTOM_MODE_1)

    def press(self, step):
        self.sim.receive(NOTE_CH1, PAD_NOTES[step], 100)

    def release(self, step):
        self.sim.receive(NOTE_CH1, PAD_NOTES[step], 0)

    def tap(self, *steps):
        for step in steps:
            self.press(step)
            self.release(step)
        self.read_output()

    def button(self, status, cc, pressed):
        self.sim.receive(status, cc, 127 if pressed else 0)

    def press_arrow(self, cc):
        self.button(CC_CH16, cc, True)
        self.button(CC_CH16, cc, False)
        self.sim.pump(ticks=2)
        self.read_output()

    def turn(self, pot, value):
        self.sim.receive(CC_CH16, FIRST_POT + pot, value, ticks=2)
        self.read_output()

    # --- What the script sends back, and the set ---

    def read_output(self):
        sent = self.sim.take_sent()
        for message in sent:
            if message[0] == 0xF0 and len(message) > 8 and message[6] == 4:
                self.screen[message[7]] = bytes(message[8:-1]).decode('latin1')
            elif message[0] == 0xF0 and len(message) > 8 and message[6] in (POT_NAME, POT_VALUE):
                self.pot_texts[message[6], message[7]] = bytes(message[8:-1]).decode('latin1')
            elif len(message) == 3:
                self.leds[message[:2]] = message[2]
        return sent

    def pad_leds(self):
        return [self.leds.get((NOTE_CH1, note)) for note in PAD_NOTES]

    def screen_text(self):
        return (self.screen.get(0), self.screen.get(1))

    def pot_display(self, pot):
        """The name and value the Launchkey shows when the pot is turned."""
        index = FIRST_POT_DISPLAY + pot
        return (self.pot_texts.get((POT_NAME, index)), self.pot_texts.get((POT_VALUE, index)))

    @property
    def step_mode(self):
        return self.surface._is_step_mode_active()

    @property
    def pad_mode(self):
        return self.surface._pad_modes.selected_mode

    def clip(self, scene=0):
        return self.sim.drums.clip_slots[scene].clip

    def make_clip(self, bars=1, scene=0):
        slot = self.sim.drums.clip_slots[scene]
        slot.create_clip(4.0 * bars)
        self.sim.song.view.detail_clip = slot.clip
        return slot.clip

    def hits(self, pitch=KICK):
        return [(note.start_time, note.velocity) for note in self.clip().notes(pitch)]


class EnteringAndLeavingTest(SurfaceTestCase):

    def test_shift_and_fifth_pad_turns_the_pads_into_a_step_grid(self):
        sent = self.enter_step_mode()
        self.assertTrue(self.step_mode)
        self.assertEqual(self.pad_mode, 'custom2')
        self.assertIn((CC_CH16, PAD_LAYOUT, SESSION), sent)  # pads switched to a layout we can light
        self.assertEqual(self.pad_leds(), [DARK_GREY, OFF, OFF, OFF] * 4)  # empty grid, beats marked
        self.assertEqual(self.screen_text(), ('Step Sequencer', 'Kick'))

    def test_shift_and_session_leaves_step_mode(self):
        self.enter_step_mode()  # the simulated Launchkey echoes our layout change; that is ignored
        self.assertTrue(self.step_mode)
        self.shift_and_pad()  # Shift + Session: the Launchkey sends only Shift, found in Live
        self.assertFalse(self.step_mode)
        self.assertEqual(self.pad_mode, 'session')

    def test_shift_with_another_control_stays_in_step_mode(self):
        self.enter_step_mode()
        self.button(CC_CH1, SHIFT, True)
        self.turn(VELOCITY_POT, 64)
        self.button(CC_CH1, SHIFT, False)
        self.assertTrue(self.step_mode)
        self.assertEqual(self.pad_mode, 'custom2')

    def test_shift_and_fifth_pad_again_goes_back_to_session(self):
        self.enter_step_mode()
        sent = self.select_pad_mode(CUSTOM_MODE_1)
        self.assertFalse(self.step_mode)
        self.assertEqual(self.pad_mode, 'session')
        self.assertIn((CC_CH16, PAD_LAYOUT, SESSION), sent)

    def test_picking_another_pad_mode_leaves_step_mode(self):
        self.enter_step_mode()
        self.select_pad_mode(DRUM)
        self.assertFalse(self.step_mode)
        self.assertEqual(self.pad_mode, 'drum')

    def test_session_pads_come_back_after_leaving(self):
        clip = self.make_clip()
        clip.color = 0xFF3636
        self.enter_step_mode()
        self.shift_and_pad()
        self.assertEqual(self.pad_mode, 'session')
        self.assertNotEqual(self.pad_leds()[0], DARK_GREY)  # the session view redrew the clip slot

    def test_pots_are_named_for_step_mode_on_the_launchkey(self):
        stock_names = [self.pot_display(pot)[0] for pot in range(8)]
        self.enter_step_mode()
        self.assertEqual([self.pot_display(pot)[0] for pot in range(8)], STEP_MODE_POT_NAMES)
        self.assertEqual({self.pot_display(pot)[1] for pot in range(8)}, {BLANK})  # no stale values
        self.turn(VELOCITY_POT, 64)
        self.assertEqual(self.pot_display(VELOCITY_POT), ('Velocity', '64'))
        self.assertEqual(self.screen_text(), ('Step Sequencer', 'Kick'))  # nothing else writes over it
        self.shift_and_pad()
        self.assertEqual([self.pot_display(pot)[0] for pot in range(8)], stock_names)

    def test_pots_go_back_to_the_stock_controls_after_leaving(self):
        self.enter_step_mode()
        self.tap(0)
        self.select_pad_mode(DRUM)
        self.turn(VELOCITY_POT, 10)
        self.assertEqual(self.hits(), [(0.0, 100)])

    def test_holding_device_select_comes_back_to_the_sequencer(self):
        self.enter_step_mode()
        self.select_pad_mode(DEVICE_SELECT)  # Device Select held down
        self.assertFalse(self.step_mode)
        self.assertEqual(self.pad_mode, 'device_select')
        self.select_pad_mode(SESSION)  # released: the Launchkey goes back to the session layout
        self.assertTrue(self.step_mode)
        self.assertEqual(self.pad_mode, 'custom2')
        self.tap(0)
        self.assertEqual(self.hits(), [(0.0, 100)])
        self.shift_and_pad()  # a later Shift + Session still leaves
        self.assertFalse(self.step_mode)

    def test_navigation_button_pauses_the_sequencer(self):
        self.enter_step_mode()
        self.select_pad_mode(NAVIGATION)
        self.assertFalse(self.step_mode)
        self.tap(0)  # navigation presses don't add hits
        self.assertIsNone(self.clip())
        self.select_pad_mode(SESSION)
        self.assertTrue(self.step_mode)

    def test_drum_mode_after_device_select_does_not_resume(self):
        self.enter_step_mode()
        self.select_pad_mode(DEVICE_SELECT)
        self.select_pad_mode(DRUM)
        self.select_pad_mode(SESSION)
        self.assertFalse(self.step_mode)
        self.assertEqual(self.pad_mode, 'session')

    def test_deleting_the_track_being_sequenced(self):
        # Found by the in-Live test: Live clears the clip view before the track selection moves.
        self.enter_step_mode()
        self.tap(0)
        self.sim.song.delete_track(0)
        self.sim.pump(ticks=2)
        self.read_output()
        self.assertTrue(self.step_mode)
        self.assertEqual(self.screen_text(), ('Step Sequencer', 'Load a Drum Rack'))
        self.assertEqual(self.pad_leds(), [DARK_GREY, OFF, OFF, OFF] * 4)
        self.tap(0)  # no drum rack on the remaining track: nothing happens
        self.assertIsNone(self.sim.keys.clip_slots[0].clip)

    def test_reconnecting_while_sequencing_keeps_the_pads_usable(self):
        self.enter_step_mode()
        self.surface.port_settings_changed()
        self.sim.pump(ticks=2)
        self.sim.receive(*live_sim.LAUNCHKEY_MK3_37_IDENTITY, ticks=2)
        sent = self.read_output()
        self.assertIn((CC_CH16, PAD_LAYOUT, SESSION), sent)
        self.assertNotIn((CC_CH16, PAD_LAYOUT, CUSTOM_MODE_1), sent)
        self.assertTrue(self.step_mode)


class StepsTest(SurfaceTestCase):

    def test_tap_adds_then_removes_a_hit(self):
        self.enter_step_mode()
        self.tap(0)
        self.assertEqual(self.hits(), [(0.0, 100)])
        self.assertEqual(self.clip().notes()[0].duration, 0.25)
        self.assertEqual(self.pad_leds()[0], RED)  # the track colour
        self.tap(0)
        self.assertEqual(self.hits(), [])
        self.assertEqual(self.pad_leds()[0], DARK_GREY)

    def test_first_tap_creates_a_one_bar_clip_in_the_selected_slot(self):
        self.sim.song.view.selected_scene = self.sim.song.scenes[2]
        self.enter_step_mode()
        self.tap(12)
        clip = self.clip(scene=2)
        self.assertEqual((clip.loop_start, clip.loop_end), (0.0, 4.0))
        self.assertEqual(self.sim.song.view.detail_clip, clip)
        self.assertEqual([(note.start_time, note.pitch) for note in clip.notes()], [(3.0, KICK)])

    def test_hits_go_into_the_clip_being_viewed(self):
        self.make_clip(bars=2)
        self.enter_step_mode()
        self.tap(8, 15)
        self.assertEqual(self.hits(), [(2.0, 100), (3.75, 100)])

    def test_steps_beyond_the_loop_are_dark_and_ignored(self):
        clip = self.make_clip()
        clip.loop_end = 2.0
        self.enter_step_mode()
        self.assertEqual(self.pad_leds()[8:], [OFF] * 8)
        self.tap(9)
        self.assertEqual(self.hits(), [])

    def test_swing_and_accent_dialled_in_before_the_first_hit_apply(self):
        self.enter_step_mode()
        self.turn(SWING_POT, 127)
        self.turn(ACCENT_POT, 10)
        self.tap(1)
        self.button(CC_CH1, ACCENT_BUTTON, True)
        self.tap(2)
        self.button(CC_CH1, ACCENT_BUTTON, False)
        self.assertEqual(self.hits(), [(0.375, 100), (0.5, 110)])

    def test_no_drum_rack(self):
        self.sim.song.view.selected_track = self.sim.keys
        self.enter_step_mode()
        self.assertEqual(self.screen_text(), ('Step Sequencer', 'Load a Drum Rack'))
        self.tap(0)
        self.assertIsNone(self.sim.keys.clip_slots[0].clip)

    def test_playhead(self):
        clip = self.make_clip()
        self.enter_step_mode()
        self.tap(4)
        self.sim.song.is_playing = True
        clip.is_playing = True
        clip.playing_position = 0.5
        self.read_output()
        self.assertEqual(self.pad_leds()[2], GREY)
        clip.playing_position = 1.1
        self.read_output()
        self.assertEqual(self.pad_leds()[2], OFF)
        self.assertEqual(self.pad_leds()[4], GREEN)  # playhead over a hit
        self.sim.song.is_playing = False
        self.read_output()
        self.assertEqual(self.pad_leds()[4], RED)


class AccentTest(SurfaceTestCase):

    def test_hold_accent_button_and_tap_adds_an_accented_hit(self):
        self.enter_step_mode()
        self.button(CC_CH1, ACCENT_BUTTON, True)
        self.tap(4)
        self.button(CC_CH1, ACCENT_BUTTON, False)
        note = self.clip().notes()[0]
        self.assertEqual((note.start_time, note.velocity, note.release_velocity), (1.0, 127, 127))
        self.assertEqual(self.pad_leds()[4], WHITE)

    def test_accent_button_toggles_accent_on_an_existing_hit(self):
        self.enter_step_mode()
        self.tap(4)
        self.button(CC_CH1, ACCENT_BUTTON, True)
        self.tap(4)
        self.assertEqual(self.hits(), [(1.0, 127)])
        self.tap(4)
        self.button(CC_CH1, ACCENT_BUTTON, False)
        self.assertEqual(self.hits(), [(1.0, 100)])  # back to normal, still there
        self.assertEqual(self.pad_leds()[4], RED)

    def test_accent_button_lights_while_in_step_mode(self):
        from Launchkey_MK3_Step.step_sequencer import ACCENT_BUTTON_COLOR
        self.enter_step_mode()
        self.assertEqual(self.leds.get((CC_CH1, ACCENT_BUTTON)), ACCENT_BUTTON_COLOR.midi_value)
        self.select_pad_mode(DRUM)
        self.assertNotEqual(self.leds.get((CC_CH1, ACCENT_BUTTON)), ACCENT_BUTTON_COLOR.midi_value)


class PotsTest(SurfaceTestCase):

    def setUp(self):
        super().setUp()
        self.enter_step_mode()
        self.tap(0, 2)
        self.button(CC_CH1, ACCENT_BUTTON, True)
        self.tap(4)
        self.button(CC_CH1, ACCENT_BUTTON, False)

    def test_velocity_pot_sets_the_lanes_level_and_keeps_accents_on_top(self):
        self.turn(VELOCITY_POT, 64)
        self.assertEqual(self.hits(), [(0.0, 64), (0.5, 64), (1.0, 91)])
        self.assertEqual(self.pot_display(VELOCITY_POT), ('Velocity', '64'))

    def test_accent_pot_sets_how_much_louder_accents_are(self):
        self.turn(VELOCITY_POT, 60)
        self.turn(ACCENT_POT, 50)
        self.assertEqual(self.hits(), [(0.0, 60), (0.5, 60), (1.0, 110)])
        self.assertEqual(self.pot_display(ACCENT_POT), ('Accent', '+50'))
        self.tap(6)  # new hits follow the lane's level
        self.assertEqual(self.hits()[-1], (1.5, 60))

    def test_swing_pot_delays_the_off_beats(self):
        self.tap(1, 3)
        self.turn(SWING_POT, 127)
        self.assertEqual([time for time, _ in self.hits()], [0.0, 0.375, 0.5, 0.875, 1.0])
        self.assertEqual(self.pot_display(SWING_POT), ('Swing', '75%'))
        self.tap(5)  # new off-beat hits are swung too
        self.assertIn(1.375, [time for time, _ in self.hits()])
        self.assertEqual(self.pad_leds()[1], RED)  # a swung hit still shows on its step
        self.turn(SWING_POT, 0)
        self.assertEqual([time for time, _ in self.hits()], [0.0, 0.25, 0.5, 0.75, 1.0, 1.25])

    def test_swing_leaves_8th_notes_on_the_grid_and_says_so(self):
        self.turn(SWING_POT, 127)  # the kick plays 8ths only: steps 1, 3 and 5
        self.assertEqual([time for time, _ in self.hits()], [0.0, 0.5, 1.0])
        self.assertEqual(self.pot_display(SWING_POT), ('Swing', '75% no 16ths'))
        self.tap(1)  # a 16th in between gets the swing dialled in
        self.assertIn(0.375, [time for time, _ in self.hits()])
        self.turn(SWING_POT, 100)
        self.assertEqual(self.pot_display(SWING_POT), ('Swing', '70%'))

    def test_swing_gives_back_lengths_live_cut_short(self):
        self.tap(1, 3)  # hits on steps 1-5; swung, steps 2 and 4 run into the next hit
        self.turn(SWING_POT, 127)
        lengths = lambda: [(round(note.start_time, 4), round(note.duration, 4)) for note in self.clip().notes()]
        self.assertEqual(lengths(), [(0.0, 0.25), (0.375, 0.125), (0.5, 0.25), (0.875, 0.125), (1.0, 0.25)])
        self.turn(SWING_POT, 0)
        self.assertEqual(lengths(), [(0.0, 0.25), (0.25, 0.25), (0.5, 0.25), (0.75, 0.25), (1.0, 0.25)])

    def test_swing_pot_swings_only_the_selected_drum_and_selects_its_notes(self):
        self.tap(1, 3)
        self.press_arrow(UP)  # the rim, on the same off-beats
        self.tap(1, 3)
        self.turn(SWING_POT, 127)
        self.assertEqual([time for time, _ in self.hits(RIM)], [0.375, 0.875])
        self.assertEqual([time for time, _ in self.hits(KICK)], [0.0, 0.25, 0.5, 0.75, 1.0])
        self.assertEqual([note.pitch for note in self.clip().selected_notes()], [RIM, RIM])
        self.assertEqual({note.duration for note in self.clip().notes()}, {0.25})  # lengths untouched
        self.press_arrow(DOWN)
        self.tap(5)  # a new kick off-beat stays straight
        self.assertIn(1.25, [time for time, _ in self.hits(KICK)])
        self.press_arrow(UP)
        self.tap(5)  # a new rim off-beat gets the rim's swing
        self.assertIn(1.375, [time for time, _ in self.hits(RIM)])

    def test_holding_a_hit_while_turning_swing_keeps_it(self):
        self.press(2)
        self.turn(SWING_POT, 100)
        self.release(2)
        self.read_output()
        self.assertEqual([time for time, _ in self.hits()], [0.0, 0.5, 1.0])  # kept

    def test_length_and_chance_pots(self):
        self.turn(LENGTH_POT, 0)
        self.turn(CHANCE_POT, 64)
        notes = self.clip().notes()
        self.assertEqual({round(note.duration, 4) for note in notes}, {0.025})
        self.assertEqual({note.probability for note in notes}, {0.5})
        self.assertEqual(self.pot_display(CHANCE_POT), ('Chance', '50%'))

    def test_holding_a_step_edits_only_that_hit_and_keeps_it(self):
        self.press(2)
        self.turn(VELOCITY_POT, 30)
        self.release(2)
        self.read_output()
        self.assertEqual(self.hits(), [(0.0, 100), (0.5, 30), (1.0, 127)])

    def test_a_pot_sweep_is_applied_in_a_few_edits(self):
        applied = []
        clip = self.clip()
        original = clip.apply_note_modifications
        clip.apply_note_modifications = lambda notes: (applied.append(1), original(notes))
        for value in range(40, 80):
            self.sim.receive(CC_CH16, FIRST_POT + VELOCITY_POT, value)
        self.sim.pump(ticks=2)
        self.assertEqual(len(applied), 1)
        self.assertEqual(self.hits()[0], (0.0, 79))

    def test_bars_pot_grows_the_loop_by_copying_and_page_pot_shows_later_bars(self):
        self.turn(BARS_POT, 127)
        clip = self.clip()
        self.assertEqual(clip.loop_end, 32.0)
        self.assertEqual(len(clip.notes()), 24)
        self.turn(PAGE_POT, 20)
        self.assertEqual(self.pot_display(PAGE_POT), ('Page', '2/8'))
        self.tap(1)
        self.assertIn((4.25, 100), self.hits())

    def test_step_size_pot(self):
        self.turn(STEPS_POT, 127)
        self.assertEqual(self.pot_display(STEPS_POT), ('Steps', '1/4'))
        # Each pad is now a beat: beat 1 holds two hits, beat 2 the accent, the rest is past the loop.
        self.assertEqual(self.pad_leds()[:5], [RED, WHITE, DARK_GREY, DARK_GREY, OFF])
        self.tap(3)
        self.assertIn((3.0, 100), self.hits())


class LanesTest(SurfaceTestCase):

    def test_arrows_move_between_loaded_drum_pads(self):
        self.enter_step_mode()
        self.press_arrow(UP)
        self.assertEqual(self.sim.rack.view.selected_drum_pad.note, RIM)
        self.assertEqual(self.screen_text(), ('Step Sequencer', 'Rim'))
        self.press_arrow(UP)
        self.assertEqual(self.sim.rack.view.selected_drum_pad.note, SNARE)
        self.press_arrow(DOWN)
        self.press_arrow(DOWN)
        self.press_arrow(DOWN)
        self.assertEqual(self.sim.rack.view.selected_drum_pad.note, KICK)

    def test_each_lane_shows_its_own_hits(self):
        self.enter_step_mode()
        self.tap(0)
        self.sim.rack.view.selected_drum_pad = self.sim.rack.drum_pads[SNARE]
        self.read_output()
        self.assertEqual(self.pad_leds()[0], DARK_GREY)
        self.tap(4)
        self.assertEqual([(n.start_time, n.pitch) for n in self.clip().notes()], [(0.0, KICK), (1.0, SNARE)])


if __name__ == '__main__':
    unittest.main()
