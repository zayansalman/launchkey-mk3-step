"""Unit tests for the pot value mappings and the swing/page timing helpers.

Run from the project folder: python3 -m unittest discover tests
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'Launchkey_MK3_Step'))

import knobs  # noqa: E402
import step_grid  # noqa: E402


class KnobMappingTest(unittest.TestCase):

    def test_ranges_cover_the_whole_pot(self):
        self.assertEqual((knobs.velocity(0), knobs.velocity(127)), (1, 127))
        self.assertEqual((knobs.accent(0), knobs.accent(127)), (0, 127))
        self.assertEqual((knobs.swing(0), knobs.swing(127)), (50, 75))
        self.assertEqual((knobs.chance(0), knobs.chance(127)), (0.01, 1.0))
        self.assertEqual((knobs.length_factor(0), knobs.length_factor(127)), (0.1, 4.0))
        self.assertEqual((knobs.bars(0), knobs.bars(127)), (1, 8))
        self.assertEqual(knobs.RESOLUTIONS[knobs.resolution_index(0)].name, '1/32')
        self.assertEqual(knobs.RESOLUTIONS[knobs.resolution_index(127)].name, '1/4')

    def test_choice_zones_are_even(self):
        indices = [knobs.choice_index(value, 4) for value in range(128)]
        self.assertEqual([indices.count(i) for i in range(4)], [32, 32, 32, 32])

    def test_page_index(self):
        self.assertEqual(knobs.page_index(127, 1), 0)
        self.assertEqual(knobs.page_index(127, 4), 3)
        self.assertEqual(knobs.page_index(0, 4), 0)


class MedianTest(unittest.TestCase):

    def test_median(self):
        self.assertEqual(step_grid.median([3]), 3)
        self.assertEqual(step_grid.median([100, 64, 127]), 100)
        self.assertEqual(step_grid.median([0.5, 1.0]), 0.75)


class SwingTimingTest(unittest.TestCase):

    def test_swing_delay(self):
        self.assertEqual(step_grid.swing_delay(50, 0.25), 0.0)
        self.assertAlmostEqual(step_grid.swing_delay(75, 0.25), 0.125)
        self.assertAlmostEqual(step_grid.swing_percent(step_grid.swing_delay(62, 0.25), 0.25), 62)

    def test_off_beats_are_swung(self):
        self.assertFalse(step_grid.is_swung(step_grid.grid_step_at(0.5, 0.25)))
        self.assertTrue(step_grid.is_swung(step_grid.grid_step_at(0.75 + 0.1, 0.25)))

    def test_num_pages(self):
        self.assertEqual(step_grid.num_pages(4.0, 4.0), 1)
        self.assertEqual(step_grid.num_pages(16.0, 4.0), 4)
        self.assertEqual(step_grid.num_pages(4.0, 8.0), 1)
        self.assertEqual(step_grid.num_pages(6.0, 4.0), 2)


if __name__ == '__main__':
    unittest.main()
