"""What the eight pots do in step mode, and how a pot position (0-127) maps to a value.

The Launchkey MK3's pots are absolute, so a pot's position is the value.
Pure functions with no Live dependencies, so they can be unit-tested outside Live.
"""
from collections import namedtuple

MAX_KNOB_VALUE = 127

VELOCITY, ACCENT, SWING, LENGTH, CHANCE, STEP_SIZE, PAGE, BARS = range(8)
NUM_KNOBS = 8
KNOB_NAMES = ('Velocity', 'Accent', 'Swing', 'Length', 'Chance', 'Steps', 'Page', 'Bars')

Resolution = namedtuple('Resolution', 'name step_length')

RESOLUTIONS = (
    Resolution('1/32', 0.125),
    Resolution('1/16T', 1.0 / 6),
    Resolution('1/16', 0.25),
    Resolution('1/8T', 1.0 / 3),
    Resolution('1/8', 0.5),
    Resolution('1/4', 1.0),
)
DEFAULT_RESOLUTION_INDEX = 2  # 1/16

LENGTH_FACTORS = (0.1, 0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 4.0)  # note length, in steps
BAR_CHOICES = (1, 2, 4, 8)
MIN_SWING, MAX_SWING = 50, 75


def choice_index(knob_value, num_choices):
    """Split the pot's travel into `num_choices` equal zones."""
    return min(num_choices - 1, knob_value * num_choices // (MAX_KNOB_VALUE + 1))


def velocity(knob_value):
    return max(1, knob_value)


def accent(knob_value):
    """How much louder an accented hit is than a normal one (0-127)."""
    return knob_value


def swing(knob_value):
    """Swing percentage: 50 (straight) to 75."""
    return MIN_SWING + int(round(knob_value * (MAX_SWING - MIN_SWING) / MAX_KNOB_VALUE))


def length_factor(knob_value):
    return LENGTH_FACTORS[choice_index(knob_value, len(LENGTH_FACTORS))]


def chance(knob_value):
    """Probability that a hit plays: 1% to 100%."""
    return max(1, int(round(knob_value * 100 / MAX_KNOB_VALUE))) / 100.0


def resolution_index(knob_value):
    return choice_index(knob_value, len(RESOLUTIONS))


def page_index(knob_value, num_pages):
    return choice_index(knob_value, num_pages)


def bars(knob_value):
    return BAR_CHOICES[choice_index(knob_value, len(BAR_CHOICES))]
