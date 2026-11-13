"""Timing helpers for the step sequencer.

Pure functions with no Live dependencies, so they can be unit-tested outside Live.
Times are in beats (quarter notes), matching Live's clip time. Grid steps are counted from
clip time 0, so swing always lands on the same (odd-numbered) steps.
"""
import math

EPSILON = 1e-6


def median(values):
    """Middle value (mean of the two middle values for an even count). `values` must not be empty.

    Kept here rather than using the statistics module, which no Ableton script relies on.
    """
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def bar_length(numerator, denominator):
    """Length of one bar in beats for a time signature."""
    return 4.0 * numerator / denominator


def step_start(page_time, step, step_length):
    """Clip time at which `step` of a page starts."""
    return page_time + step * step_length


def step_for_time(time, page_time, step_length, num_steps):
    """Index of the page step containing `time`, or None when `time` is outside the page."""
    offset = time - page_time
    if offset < -EPSILON:
        return None
    step = int((offset + EPSILON) // step_length)
    return step if step < num_steps else None


def active_steps(start_times, page_time, step_length, num_steps):
    """Indices of the steps that contain at least one of the given note start times."""
    steps = (step_for_time(time, page_time, step_length, num_steps) for time in start_times)
    return frozenset(step for step in steps if step is not None)


def grid_step_at(time, step_length):
    """Index of the grid step (counted from clip time 0) containing `time`."""
    return int((time + EPSILON) // step_length)


def is_swung(grid_step):
    """Swing delays every second step: the off-beats."""
    return grid_step % 2 == 1


def swing_delay(swing_percent, step_length):
    """How far swing pushes the off-beat steps, in beats. 50% is straight, 75% the maximum."""
    return (swing_percent / 100.0 - 0.5) * 2.0 * step_length


def swing_percent(delay, step_length):
    """Inverse of swing_delay."""
    return 50.0 + delay / (2.0 * step_length) * 100.0


def page_length(num_steps, step_length):
    return num_steps * step_length


def num_pages(loop_length, page_len):
    """Pages needed to show the whole loop (at least one)."""
    return max(1, int(math.ceil(loop_length / page_len - EPSILON)))


def next_lane(current, delta, loaded_notes):
    """Nearest loaded drum pad note above (delta > 0) or below (delta < 0) `current`.

    Returns the lowest loaded note when nothing is selected yet, and None when there is no
    loaded pad in that direction.
    """
    candidates = sorted(loaded_notes)
    if not candidates:
        return None
    if current is None:
        return candidates[0]
    if delta > 0:
        return next((note for note in candidates if note > current), None)
    return next((note for note in reversed(candidates) if note < current), None)
