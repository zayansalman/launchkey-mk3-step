"""A stand-in for Live's MIDI clip note API, faithful enough to test note edits.

Like Live, get_notes_extended returns copies: changes only stick after
apply_note_modifications, matched by note_id. Also like Live, two notes of the same pitch never
overlap: the earlier one is cut where the next one starts.
"""
import copy
import itertools

_note_ids = itertools.count(1)


class FakeNote:

    def __init__(self, pitch, start_time, duration, velocity=100.0, mute=False, probability=1.0,
                 velocity_deviation=0.0, release_velocity=64.0):
        self.note_id = next(_note_ids)
        self.pitch = pitch
        self.start_time = start_time
        self.duration = duration
        self.velocity = velocity
        self.mute = mute
        self.probability = probability
        self.velocity_deviation = velocity_deviation
        self.release_velocity = release_velocity

    def __repr__(self):
        return 'Note(p={} t={} v={} rel={})'.format(self.pitch, self.start_time, self.velocity, self.release_velocity)


def note_spec(**properties):
    """Test replacement for Live.Clip.MidiNoteSpecification."""
    return properties


class FakeClip:
    is_midi_clip = True
    is_arrangement_clip = False

    def __init__(self, loop_start=0.0, loop_end=4.0):
        self.loop_start = loop_start
        self.loop_end = loop_end
        self.end_marker = loop_end
        self._notes = []
        self.selected_ids = set()

    # Live's note API

    def get_notes_extended(self, from_pitch, pitch_span, from_time, time_span):
        return [copy.copy(note) for note in self._notes
                if from_pitch <= note.pitch < from_pitch + pitch_span
                and from_time <= note.start_time < from_time + time_span]

    def add_new_notes(self, specifications):
        for spec in specifications:
            self._notes.append(FakeNote(**spec))
        self._cut_overlaps()

    def remove_notes_extended(self, from_pitch, pitch_span, from_time, time_span):
        doomed = {note.note_id for note in self.get_notes_extended(from_pitch, pitch_span, from_time, time_span)}
        self._notes = [note for note in self._notes if note.note_id not in doomed]

    def apply_note_modifications(self, notes):
        by_id = {note.note_id: note for note in notes}
        self._notes = [copy.copy(by_id.get(note.note_id, note)) for note in self._notes]
        self._cut_overlaps()

    def deselect_all_notes(self):
        self.selected_ids = set()

    def select_notes_by_id(self, note_ids):
        self.selected_ids.update(note_ids)

    def duplicate_loop(self):
        length = self.loop_end - self.loop_start
        for note in self.get_notes_extended(0, 128, self.loop_start, length):
            self._notes.append(FakeNote(note.pitch, note.start_time + length, note.duration, note.velocity,
                                        note.mute, note.probability, note.velocity_deviation,
                                        note.release_velocity))
        self.loop_end += length
        self.end_marker = self.loop_end
        self._cut_overlaps()

    def _cut_overlaps(self):
        """Like Live: two notes of the same pitch never overlap; the earlier one ends where the next starts."""
        last = {}
        for note in sorted(self._notes, key=lambda note: note.start_time):
            previous = last.get(note.pitch)
            if previous is not None and previous.start_time + previous.duration > note.start_time + 1e-9:
                previous.duration = note.start_time - previous.start_time
            last[note.pitch] = note

    # Test helpers

    def all_notes(self):
        return sorted(self._notes, key=lambda note: (note.start_time, note.pitch))
