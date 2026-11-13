"""Unit tests for the step sequencer's timing helpers.

Run from the project folder: python3 -m unittest discover tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'Launchkey_MK3_Step'))

import step_grid  # noqa: E402  (imported directly: the package itself needs Live)


class BarLengthTest(unittest.TestCase):

    def test_common_time_signatures(self):
        self.assertEqual(step_grid.bar_length(4, 4), 4.0)
        self.assertEqual(step_grid.bar_length(3, 4), 3.0)
        self.assertEqual(step_grid.bar_length(7, 8), 3.5)


class StepTimingTest(unittest.TestCase):

    def test_step_start(self):
        self.assertEqual(step_grid.step_start(0.0, 5, 0.25), 1.25)
        self.assertEqual(step_grid.step_start(4.0, 0, 0.25), 4.0)

    def test_step_for_time_inside_page(self):
        self.assertEqual(step_grid.step_for_time(0.0, 0.0, 0.25, 16), 0)
        self.assertEqual(step_grid.step_for_time(0.249, 0.0, 0.25, 16), 0)
        self.assertEqual(step_grid.step_for_time(0.25, 0.0, 0.25, 16), 1)
        self.assertEqual(step_grid.step_for_time(3.99, 0.0, 0.25, 16), 15)
        self.assertEqual(step_grid.step_for_time(5.0, 4.0, 0.25, 16), 4)

    def test_step_for_time_outside_page(self):
        self.assertIsNone(step_grid.step_for_time(4.0, 0.0, 0.25, 16))
        self.assertIsNone(step_grid.step_for_time(-0.1, 0.0, 0.25, 16))
        self.assertIsNone(step_grid.step_for_time(3.9, 4.0, 0.25, 16))

    def test_rounding_error_lands_on_intended_step(self):
        self.assertEqual(step_grid.step_for_time(0.75 - 1e-9, 0.0, 0.25, 16), 3)

    def test_active_steps(self):
        starts = [0.0, 1.0, 1.0, 2.5, 4.0]
        self.assertEqual(step_grid.active_steps(starts, 0.0, 0.25, 16), frozenset({0, 4, 10}))


class NextLaneTest(unittest.TestCase):
    LOADED = [38, 36, 37]

    def test_moves_to_nearest_loaded_pad(self):
        self.assertEqual(step_grid.next_lane(36, 1, self.LOADED), 37)
        self.assertEqual(step_grid.next_lane(37, -1, self.LOADED), 36)

    def test_skips_empty_pads(self):
        self.assertEqual(step_grid.next_lane(40, -1, self.LOADED), 38)
        self.assertEqual(step_grid.next_lane(30, 1, self.LOADED), 36)

    def test_stops_at_the_ends(self):
        self.assertIsNone(step_grid.next_lane(38, 1, self.LOADED))
        self.assertIsNone(step_grid.next_lane(36, -1, self.LOADED))

    def test_no_selection_or_no_pads(self):
        self.assertEqual(step_grid.next_lane(None, 1, self.LOADED), 36)
        self.assertIsNone(step_grid.next_lane(36, 1, []))


if __name__ == '__main__':
    unittest.main()
