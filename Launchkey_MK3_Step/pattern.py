"""Note edits for the step sequencer, written against Live's clip note API.

PatternEditor never imports Live: the note factory (Live.Clip.MidiNoteSpecification) is passed
in, so the editing rules can be unit-tested with a fake clip. Times are clip times in beats, and
whole-lane edits cover the clip's loop.

Accents work like a TR-909's strong steps: an accented hit plays at its lane's velocity plus
the clip-wide accent amount. A hit is marked as accented through its release velocity, which
Drum Racks ignore, so the mark survives saving the set and editing the clip in Live.

Swing is set per drum and works like a TR-909's shuffle or an MPC's 16th swing (the groove of
"Revolution 909" or UK garage): it pushes the 16ths between the 8ths later and leaves the beat
and the "and" on the grid. It works on the 16th-note grid whatever step size the pads show, and
lives in the hits' positions, so it is read back from them.
"""
from collections import Counter, defaultdict

from . import step_grid
from .step_grid import median

DEFAULT_LEVEL = 100
DEFAULT_ACCENT_AMOUNT = 27
MAX_VELOCITY = 127
NORMAL_RELEASE_VELOCITY = 64  # Live's default
ACCENT_RELEASE_VELOCITY = 127
SWING_TOLERANCE = 1e-3  # beats
SIXTEENTH = 0.25  # beats
MAX_SWING_DELAY = SIXTEENTH / 2  # 75%

def is_accented(note):
    return note.release_velocity == ACCENT_RELEASE_VELOCITY


def hit_velocity(level, accent_amount, accented):
    return min(MAX_VELOCITY, level + accent_amount) if accented else level


def in_windows(time, windows):
    return any(start - step_grid.EPSILON <= time < start + length - step_grid.EPSILON
               for start, length in windows)


def sixteenth_position(time):
    """The 16th-note grid position a hit belongs to, and how far after it the hit sits."""
    position = step_grid.grid_step_at(time, SIXTEENTH)
    return position, time - position * SIXTEENTH


def swing_delay_for(percent):
    """How far swing pushes the 16ths between the 8ths: 0 at 50% (straight), half a 16th at 75%."""
    return step_grid.swing_delay(percent, SIXTEENTH)


def swing_percent_for(delay):
    """Inverse of swing_delay_for, as the whole percent the swing pot shows."""
    return int(round(step_grid.swing_percent(delay, SIXTEENTH)))


def majority_delay(notes):
    """The delay shared by most of the hits swing moves; 0 when they're mostly straight."""
    offsets = Counter()
    for note in notes:
        position, offset = sixteenth_position(note.start_time)
        if step_grid.is_swung(position):
            offsets[round(offset, 4)] += 1
    if not offsets:
        return 0.0
    offset = offsets.most_common(1)[0][0]
    return offset if 0 < offset <= MAX_SWING_DELAY + SWING_TOLERANCE else 0.0


def cut_short(note, lane_starts):
    """Whether Live has cut a swung hit short.

    Live doesn't let two hits of one drum overlap, so a hit that swing pushes into the drum's next
    hit ends where that one starts: it sits off the 16th grid and ends right at the next hit.
    `lane_starts` are the start times of the drum's hits, sorted.
    """
    if sixteenth_position(note.start_time)[1] <= SWING_TOLERANCE:
        return False  # on the grid, so not swung
    next_start = next((start for start in lane_starts if start > note.start_time + step_grid.EPSILON), None)
    return next_start is not None and abs(note.start_time + note.duration - next_start) <= SWING_TOLERANCE


class PatternEditor:

    def __init__(self, clip, note_factory):
        self._clip = clip
        self._note_factory = note_factory

    # --- Reading ---

    def loop_length(self):
        return self._clip.loop_end - self._clip.loop_start

    def notes(self, pitch=None, start=None, length=None):
        """Notes of one pitch (or every pitch) that start in a time range (default: the loop)."""
        if start is None:
            start, length = self._clip.loop_start, self.loop_length()
        from_pitch, pitch_span = (0, 128) if pitch is None else (pitch, 1)
        return self._clip.get_notes_extended(
            from_pitch=from_pitch, pitch_span=pitch_span, from_time=start, time_span=length)

    def has_hit(self, pitch, window_start, window_length):
        return len(self.notes(pitch, window_start, window_length)) > 0

    def lane_level(self, pitch, accent_amount):
        """Velocity of the lane's normal hits (or of its accented hits minus the accent)."""
        return self._level_of(self.notes(pitch), accent_amount)

    def lane_duration(self, pitch, step_length):
        """The drum's hit length (one step when it has no hits); hits Live cut short don't count."""
        return self._usual_length(self.notes(pitch), default=step_length)

    def lane_chance(self, pitch):
        notes = self.notes(pitch)
        return median([note.probability for note in notes]) if len(notes) else 1.0

    def accent_amount(self):
        """How much louder accented hits are than normal ones, read from lanes with both kinds."""
        differences = []
        for lane in self._lanes(self.notes()).values():
            normal = [note.velocity for note in lane if not is_accented(note)]
            accented = [note.velocity for note in lane if is_accented(note)]
            if normal and accented:
                differences.append(median(accented) - median(normal))
        return int(round(median(differences))) if differences else DEFAULT_ACCENT_AMOUNT

    def has_16ths_between(self, pitch):
        """Whether one drum (or any drum) has hits that swing moves: 16ths between the 8ths."""
        return any(step_grid.is_swung(sixteenth_position(note.start_time)[0]) for note in self.notes(pitch))

    def swing_percent(self, pitch):
        """One drum's swing, read from its hits: 50 when straight."""
        return swing_percent_for(majority_delay(self.notes(pitch)))

    # --- Adding and removing hits ---

    def add_hit(self, pitch, start, duration, velocity, probability, accented):
        self._clip.add_new_notes((self._note_factory(
            pitch=pitch,
            start_time=start,
            duration=duration,
            velocity=velocity,
            mute=False,
            probability=probability,
            release_velocity=ACCENT_RELEASE_VELOCITY if accented else NORMAL_RELEASE_VELOCITY),))
        self._clip.deselect_all_notes()

    def remove_hits(self, pitch, window_start, window_length):
        self._clip.remove_notes_extended(
            from_pitch=pitch, pitch_span=1, from_time=window_start, time_span=window_length)

    # --- Changing hits (a whole lane, or only the hits inside `windows`) ---

    def set_level(self, pitch, level, accent_amount, windows=None):
        def change(note):
            note.velocity = hit_velocity(level, accent_amount, is_accented(note))
        self._modify_lane(pitch, change, windows)

    def set_accented(self, pitch, windows, accented, level, accent_amount):
        def change(note):
            note.release_velocity = ACCENT_RELEASE_VELOCITY if accented else NORMAL_RELEASE_VELOCITY
            note.velocity = hit_velocity(level, accent_amount, accented)
        self._modify_lane(pitch, change, windows)

    def set_duration(self, pitch, duration, windows=None):
        def change(note):
            note.duration = duration
        self._modify_lane(pitch, change, windows)

    def set_chance(self, pitch, probability, windows=None):
        def change(note):
            note.probability = probability
        self._modify_lane(pitch, change, windows)

    # --- Clip-wide changes ---

    def set_accent_amount(self, accent_amount, previous_amount):
        notes = self.notes()
        levels = {pitch: self._level_of(lane, previous_amount)
                  for pitch, lane in self._lanes(notes).items()}
        for note in notes:
            if is_accented(note):
                note.velocity = hit_velocity(levels[note.pitch], accent_amount, True)
        self._clip.apply_note_modifications(notes)

    def swing(self, pitch, percent):
        """Swing one drum like a TR-909's shuffle or an MPC's 16th swing: push its 16ths between
        the 8ths later. Hits on the beat and on the "and" stay on the grid.

        Only hits on the grid or at the old swing move, so hand-placed timing is kept. A moved hit
        that Live had cut short gets its drum's length back (Live cuts it again where it still runs
        into the next hit), so turning swing down restores the lengths.
        """
        self._swing(self.notes(pitch), percent)

    def swing_kit(self, percent):
        """Give every drum in the clip the same swing, like a TR-909's master shuffle."""
        self._swing(self.notes(), percent)

    def _swing(self, notes, percent):
        new = swing_delay_for(percent)
        for lane in self._lanes(notes).values():
            old = majority_delay(lane)
            starts = sorted(note.start_time for note in lane)
            length = self._usual_length(lane, default=SIXTEENTH)
            for note in lane:
                position, offset = sixteenth_position(note.start_time)
                if not step_grid.is_swung(position):
                    continue
                if abs(offset - old) <= SWING_TOLERANCE or abs(offset) <= SWING_TOLERANCE:
                    if cut_short(note, starts):
                        note.duration = max(note.duration, length)
                    note.start_time = position * SIXTEENTH + new
        self._clip.apply_note_modifications(notes)

    def select_notes(self, pitch):
        """Select one drum's notes (and only those), or every drum's, as shown in Live's clip view."""
        self._clip.deselect_all_notes()
        self._clip.select_notes_by_id([note.note_id for note in self.notes(pitch)])

    def set_loop_length(self, length):
        """Change the loop length; growing by doubling copies the pattern, like Live's Duplicate."""
        clip = self._clip
        current = self.loop_length()
        if current <= 0 or abs(length - current) < step_grid.EPSILON:
            return
        while current * 2 <= length + step_grid.EPSILON:
            clip.duplicate_loop()
            doubled = self.loop_length()
            if doubled <= current + step_grid.EPSILON:
                break
            current = doubled
        if abs(length - current) >= step_grid.EPSILON:
            clip.loop_end = clip.loop_start + length
            clip.end_marker = clip.loop_end

    # --- Helpers ---

    def _modify_lane(self, pitch, change, windows):
        notes = self.notes(pitch)
        for note in notes:
            if windows is None or in_windows(note.start_time, windows):
                change(note)
        self._clip.apply_note_modifications(notes)

    @staticmethod
    def _lanes(notes):
        lanes = defaultdict(list)
        for note in notes:
            lanes[note.pitch].append(note)
        return lanes

    @staticmethod
    def _usual_length(lane_notes, default):
        """Median length of one drum's hits, leaving out hits Live cut short (see cut_short)."""
        starts = sorted(note.start_time for note in lane_notes)
        lengths = ([note.duration for note in lane_notes if not cut_short(note, starts)]
                   or [note.duration for note in lane_notes])
        return median(lengths) if lengths else default

    @staticmethod
    def _level_of(lane_notes, accent_amount):
        normal = [note.velocity for note in lane_notes if not is_accented(note)]
        if normal:
            return int(round(median(normal)))
        accented = [note.velocity for note in lane_notes if is_accented(note)]
        if accented:
            return max(1, int(round(median(accented))) - accent_amount)
        return DEFAULT_LEVEL
