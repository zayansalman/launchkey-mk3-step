"""Unit tests for PatternEditor's note edits, run against a fake clip.

Run from the project folder: python3 -m unittest discover tests
"""
import os
import sys
import types
import unittest

ROOT = os.path.join(os.path.dirname(__file__), '..')
sys.path.insert(0, os.path.dirname(__file__))

# Load pattern.py and step_grid.py as a package without the Live-only __init__.py.
package = types.ModuleType('seq')
package.__path__ = [os.path.join(ROOT, 'Launchkey_MK3_Step')]
sys.modules['seq'] = package
from seq import pattern  # noqa: E402
from seq.pattern import ACCENT_RELEASE_VELOCITY, PatternEditor  # noqa: E402
from fake_clip import FakeClip, FakeNote, note_spec  # noqa: E402

KICK, SNARE, HAT = 36, 38, 42
STEP = 0.25


def add(clip, pitch, start, velocity=100, accented=False, duration=STEP):
    note = FakeNote(pitch, start, duration, velocity=velocity,
                    release_velocity=ACCENT_RELEASE_VELOCITY if accented else 64)
    clip._notes.append(note)
    return note


class PatternEditorTestCase(unittest.TestCase):

    def setUp(self):
        self.clip = FakeClip()
        self.editor = PatternEditor(self.clip, note_spec)

    def velocities(self, pitch):
        return [(note.start_time, note.velocity) for note in self.clip.all_notes() if note.pitch == pitch]

    def lengths(self, pitch):
        return [(round(note.start_time, 4), round(note.duration, 4))
                for note in self.clip.all_notes() if note.pitch == pitch]

    def times(self, pitch):
        return [round(note.start_time, 4) for note in self.clip.all_notes() if note.pitch == pitch]


class HitsTest(PatternEditorTestCase):

    def test_add_find_and_remove_a_hit(self):
        self.editor.add_hit(KICK, 1.0, STEP, velocity=90, probability=1.0, accented=False)
        self.assertTrue(self.editor.has_hit(KICK, 1.0, STEP))
        self.assertFalse(self.editor.has_hit(KICK, 1.25, STEP))
        self.assertFalse(self.editor.has_hit(SNARE, 1.0, STEP))
        self.editor.remove_hits(KICK, 1.0, STEP)
        self.assertEqual(self.clip.all_notes(), [])

    def test_accented_hit_is_marked_by_release_velocity(self):
        self.editor.add_hit(KICK, 0.0, STEP, velocity=127, probability=0.5, accented=True)
        note = self.clip.all_notes()[0]
        self.assertTrue(pattern.is_accented(note))
        self.assertEqual(note.probability, 0.5)

    def test_swung_hit_is_found_in_its_step_window(self):
        self.editor.add_hit(KICK, 0.25 + 0.06, STEP, velocity=100, probability=1.0, accented=False)
        self.assertTrue(self.editor.has_hit(KICK, 0.25, STEP))


class VelocityTest(PatternEditorTestCase):

    def test_lane_level_comes_from_normal_hits(self):
        add(self.clip, KICK, 0.0, velocity=80)
        add(self.clip, KICK, 1.0, velocity=80)
        add(self.clip, KICK, 2.0, velocity=110, accented=True)
        self.assertEqual(self.editor.lane_level(KICK, accent_amount=30), 80)

    def test_lane_level_of_an_all_accented_lane(self):
        add(self.clip, KICK, 0.0, velocity=120, accented=True)
        self.assertEqual(self.editor.lane_level(KICK, accent_amount=30), 90)

    def test_lane_level_default(self):
        self.assertEqual(self.editor.lane_level(KICK, accent_amount=30), pattern.DEFAULT_LEVEL)

    def test_set_level_keeps_accents_on_top_and_clamps(self):
        add(self.clip, KICK, 0.0, velocity=100)
        add(self.clip, KICK, 1.0, velocity=127, accented=True)
        add(self.clip, SNARE, 1.0, velocity=50)
        self.editor.set_level(KICK, 110, accent_amount=27)
        self.assertEqual(self.velocities(KICK), [(0.0, 110), (1.0, 127)])
        self.editor.set_level(KICK, 60, accent_amount=27)
        self.assertEqual(self.velocities(KICK), [(0.0, 60), (1.0, 87)])
        self.assertEqual(self.velocities(SNARE), [(1.0, 50)])

    def test_set_level_only_in_windows(self):
        add(self.clip, KICK, 0.0, velocity=100)
        add(self.clip, KICK, 1.0, velocity=100)
        self.editor.set_level(KICK, 40, accent_amount=27, windows=[(1.0, STEP)])
        self.assertEqual(self.velocities(KICK), [(0.0, 100), (1.0, 40)])


class AccentTest(PatternEditorTestCase):

    def test_set_accented_and_back(self):
        add(self.clip, KICK, 0.0, velocity=100)
        self.editor.set_accented(KICK, [(0.0, STEP)], True, level=100, accent_amount=20)
        note = self.clip.all_notes()[0]
        self.assertTrue(pattern.is_accented(note))
        self.assertEqual(note.velocity, 120)
        self.editor.set_accented(KICK, [(0.0, STEP)], False, level=100, accent_amount=20)
        note = self.clip.all_notes()[0]
        self.assertFalse(pattern.is_accented(note))
        self.assertEqual(note.velocity, 100)

    def test_accent_amount_is_read_from_lanes_with_both_kinds(self):
        add(self.clip, KICK, 0.0, velocity=90)
        add(self.clip, KICK, 1.0, velocity=110, accented=True)
        add(self.clip, SNARE, 1.0, velocity=70)
        add(self.clip, SNARE, 2.0, velocity=90, accented=True)
        self.assertEqual(self.editor.accent_amount(), 20)

    def test_accent_amount_default(self):
        add(self.clip, KICK, 0.0, velocity=90)
        self.assertEqual(self.editor.accent_amount(), pattern.DEFAULT_ACCENT_AMOUNT)

    def test_set_accent_amount_moves_every_accented_hit(self):
        add(self.clip, KICK, 0.0, velocity=90)
        add(self.clip, KICK, 1.0, velocity=110, accented=True)
        add(self.clip, SNARE, 1.0, velocity=120, accented=True)  # only accented: level = 120 - 20
        self.editor.set_accent_amount(35, previous_amount=20)
        self.assertEqual(self.velocities(KICK), [(0.0, 90), (1.0, 125)])
        self.assertEqual(self.velocities(SNARE), [(1.0, 127)])


class SwingTest(PatternEditorTestCase):

    def test_swing_pushes_the_16ths_between_the_8ths_like_a_909(self):
        # Like a TR-909's shuffle or an MPC's 16th swing: the beat and the "and" stay on the grid.
        for step in range(5):
            add(self.clip, KICK, step * STEP)
        self.editor.swing(KICK, 75)
        self.assertEqual(self.times(KICK), [0.0, 0.375, 0.5, 0.875, 1.0])
        self.assertEqual(self.editor.swing_percent(KICK), 75)
        self.assertTrue(self.editor.has_16ths_between(KICK))

    def test_8th_notes_stay_on_the_grid(self):
        for start in (0.0, 0.5, 1.0, 1.5):
            add(self.clip, HAT, start)
        self.editor.swing(HAT, 75)
        self.assertEqual(self.times(HAT), [0.0, 0.5, 1.0, 1.5])
        self.assertFalse(self.editor.has_16ths_between(HAT))

    def test_hits_on_the_beat_never_swing(self):
        for start in (0.0, 1.0, 2.0, 3.0):
            add(self.clip, KICK, start)
        self.editor.swing(KICK, 75)
        self.assertEqual(self.times(KICK), [0.0, 1.0, 2.0, 3.0])
        self.assertEqual(self.editor.swing_percent(KICK), 50)

    def test_swing_back_to_straight(self):
        add(self.clip, KICK, 0.0)
        add(self.clip, KICK, 0.25 + 1.0 / 12)  # a triplet feel: 67%
        self.assertEqual(self.editor.swing_percent(KICK), 67)
        self.editor.swing(KICK, 50)
        self.assertEqual(self.times(KICK), [0.0, 0.25])
        self.assertEqual(self.editor.swing_percent(KICK), 50)

    def test_hand_placed_hits_are_left_alone(self):
        for step in range(4):
            add(self.clip, KICK, step * STEP)
        add(self.clip, KICK, 1.25 + 0.01)  # nudged by hand in Live
        self.editor.swing(KICK, 75)
        self.assertEqual(self.times(KICK), [0.0, 0.375, 0.5, 0.875, 1.26])

    def test_swinging_one_drum_leaves_the_others_straight(self):
        for start in (0.25, 0.75):
            add(self.clip, KICK, start)
            add(self.clip, SNARE, start)
        self.editor.swing(SNARE, 70)
        self.assertEqual(self.times(SNARE), [0.35, 0.85])
        self.assertEqual(self.times(KICK), [0.25, 0.75])
        self.assertEqual(self.editor.swing_percent(SNARE), 70)
        self.assertEqual(self.editor.swing_percent(KICK), 50)

    def test_swing_gives_back_the_length_live_cut_short(self):
        # Live doesn't let two hits of one drum overlap: a hit swung into the next one is cut short.
        for start in (0.0, 0.25, 0.5, 1.25):
            add(self.clip, KICK, start)
        self.editor.swing(KICK, 75)
        self.assertEqual(self.lengths(KICK), [(0.0, 0.25), (0.375, 0.125), (0.5, 0.25), (1.375, 0.25)])
        self.editor.swing(KICK, 62)
        self.assertEqual(self.lengths(KICK), [(0.0, 0.25), (0.31, 0.19), (0.5, 0.25), (1.31, 0.25)])
        self.editor.swing(KICK, 50)
        self.assertEqual(self.lengths(KICK), [(0.0, 0.25), (0.25, 0.25), (0.5, 0.25), (1.25, 0.25)])

    def test_hits_cut_short_by_swing_dont_change_the_drums_length(self):
        add(self.clip, KICK, 0.25)
        add(self.clip, KICK, 0.5)
        self.editor.swing(KICK, 75)
        self.assertEqual(self.lengths(KICK), [(0.375, 0.125), (0.5, 0.25)])
        self.assertEqual(self.editor.lane_duration(KICK, STEP), 0.25)  # new hits keep the drum's length


class SelectionTest(PatternEditorTestCase):

    def test_select_notes_selects_one_drum_only(self):
        kick = add(self.clip, KICK, 0.0)
        add(self.clip, SNARE, 0.5)
        self.clip.selected_ids = {12345}  # an earlier selection is replaced
        self.editor.select_notes(KICK)
        self.assertEqual(self.clip.selected_ids, {kick.note_id})


class LaneEditsTest(PatternEditorTestCase):

    def test_duration_and_chance(self):
        add(self.clip, KICK, 0.0)
        add(self.clip, KICK, 1.0)
        self.editor.set_duration(KICK, 0.1)
        self.editor.set_chance(KICK, 0.5, windows=[(1.0, STEP)])
        notes = self.clip.all_notes()
        self.assertEqual([note.duration for note in notes], [0.1, 0.1])
        self.assertEqual([note.probability for note in notes], [1.0, 0.5])
        self.assertAlmostEqual(self.editor.lane_duration(KICK, STEP), 0.1)
        self.assertAlmostEqual(self.editor.lane_chance(KICK), 0.75)

    def test_loop_length_grows_by_copying_and_shrinks(self):
        add(self.clip, KICK, 0.0)
        add(self.clip, SNARE, 1.0)
        self.editor.set_loop_length(16.0)
        self.assertEqual((self.clip.loop_end, self.clip.end_marker), (16.0, 16.0))
        self.assertEqual(len(self.clip.all_notes()), 8)
        self.editor.set_loop_length(8.0)
        self.assertEqual((self.clip.loop_end, self.clip.end_marker), (8.0, 8.0))


if __name__ == '__main__':
    unittest.main()
