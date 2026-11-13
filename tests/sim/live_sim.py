"""A small simulation of Ableton Live for running the real control-surface code offline.

It imports Ableton's own compiled MIDI Remote Scripts from the installed Live app (they need
Python 3.11, Live's version), fakes the `Live` module, and provides fake Song / Track / Clip /
Drum Rack objects with Live-style listeners. Attributes the fakes don't define fall back to
inert stand-ins, so the stock Launchkey MK3 script can start up around them.

Drive it like Live does: create the surface, rebuild its MIDI map, send it MIDI bytes and tick
update_display. Everything it sends to the "Launchkey" is recorded in LiveSim.sent.
"""
import copy
import importlib.abc
import importlib.machinery
import itertools
import os
import re
import sys
import types
from collections import defaultdict

LIVE_APP = '/Applications/Ableton Live 12 Suite.app/Contents/App-Resources'
REMOTE_SCRIPTS = os.path.join(LIVE_APP, 'MIDI Remote Scripts')
SITE_PACKAGES = os.path.join(LIVE_APP, 'Python', 'site-packages')
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

LAUNCHKEY_MK3_37_IDENTITY = (240, 126, 0, 6, 2, 0, 32, 41, 53, 1, 0, 0, 0, 1, 9, 7, 247)
IDENTITY_REQUEST = (240, 126, 127, 6, 1, 247)


def is_available():
    return sys.version_info[:2] == (3, 11) and os.path.isdir(REMOTE_SCRIPTS)


# --- Inert stand-ins for anything the fakes don't model ---

class Inert:
    """Falsy, empty, zero-valued, callable; every attribute is another Inert."""

    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        return Inert()

    def __call__(self, *a, **k):
        return Inert()

    def __bool__(self):
        return False

    def __len__(self):
        return 0

    def __iter__(self):
        return iter(())

    def __int__(self):
        return 0

    __index__ = __int__

    def __float__(self):
        return 0.0

    def __lt__(self, other):
        return False

    __gt__ = __le__ = __ge__ = __lt__

    def __eq__(self, other):
        return self is other

    def __hash__(self):
        return id(self)

    def __str__(self):
        return ''


# --- The fake `Live` module ---

class _StubMeta(type):

    def __getattr__(cls, name):
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        stub = _StubMeta(name, (_StubType,), {})
        setattr(cls, name, stub)
        return stub

    def __iter__(cls):
        return iter(())

    def __len__(cls):
        return 0

    def __int__(cls):
        return 0

    __index__ = __int__

    def __or__(cls, other):
        return cls

    __ror__ = __and__ = __add__ = __radd__ = __sub__ = __mul__ = __or__

    def __lt__(cls, other):
        return False

    __gt__ = __le__ = __ge__ = __lt__


class _StubType(metaclass=_StubMeta):

    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        return Inert()


class _StubModule(types.ModuleType):

    def __getattr__(self, name):
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        stub = _StubMeta(name, (_StubType,), {})
        setattr(self, name, stub)
        return stub


class _LiveFinder(importlib.abc.MetaPathFinder, importlib.abc.Loader):

    def find_spec(self, fullname, path, target=None):
        if fullname == 'Live' or fullname.startswith('Live.') or fullname == 'MidiRemoteScript':
            return importlib.machinery.ModuleSpec(fullname, self, is_package=True)
        return None

    def create_module(self, spec):
        module = _StubModule(spec.name)
        module.__path__ = []
        return module

    def exec_module(self, module):
        pass


class MidiNoteSpecification:
    """Stands in for Live.Clip.MidiNoteSpecification."""

    def __init__(self, pitch, start_time, duration, velocity=100.0, mute=False, probability=1.0,
                 velocity_deviation=0.0, release_velocity=64.0):
        self.pitch = pitch
        self.start_time = start_time
        self.duration = duration
        self.velocity = velocity
        self.mute = mute
        self.probability = probability
        self.velocity_deviation = velocity_deviation
        self.release_velocity = release_velocity


_installed = False


def install():
    """Fake `Live` and make Ableton's scripts and this project importable."""
    global _installed
    if _installed:
        return
    _installed = True
    sys.meta_path.insert(0, _LiveFinder())
    sys.path.insert(0, REMOTE_SCRIPTS)
    sys.path.insert(0, PROJECT_ROOT)
    for name in sorted(os.listdir(SITE_PACKAGES)):
        sys.path.append(os.path.join(SITE_PACKAGES, name))
    import Live
    import Live.Clip
    import Live.Application
    Live.Clip.MidiNoteSpecification = MidiNoteSpecification
    Live.Application.get_application = lambda: LiveSim.current.application


# --- Live objects with listeners ---

_LISTENER = re.compile(r'^(add|remove)_(\w+)_listener$|^(\w+)_has_listener$')


class LiveObject:
    """Live-style object: add_X_listener / remove_X_listener / X_has_listener for any X.

    Setting an attribute named in NOTIFYING fires its listeners, like Live does.
    """
    NOTIFYING = ()

    def __init__(self):
        object.__setattr__(self, '_listeners', defaultdict(list))
        object.__setattr__(self, '_deleted', False)

    # A deleted Live object compares equal to None and fails on any use, like in Live.

    def delete(self):
        object.__setattr__(self, '_deleted', True)

    def __getattribute__(self, name):
        if not name.startswith('_') and object.__getattribute__(self, '_deleted'):
            raise RuntimeError('Live object was deleted (used .{})'.format(name))
        return object.__getattribute__(self, name)

    def __eq__(self, other):
        if other is None:
            return object.__getattribute__(self, '_deleted')
        return self is other

    def __ne__(self, other):
        return not self.__eq__(other)

    def __hash__(self):
        return id(self)

    def __getattr__(self, name):
        match = _LISTENER.match(name)
        if match:
            # Some Live listeners take a key before the callback, e.g.
            # add_is_view_visible_listener('Session', callback).
            action, prop, has_prop = match.groups()
            prop = prop or has_prop

            def listeners(args):
                return self._listeners[(prop,) + tuple(args[:-1]) if len(args) > 1 else prop]

            if action == 'add':
                return lambda *args: listeners(args).append(args[-1])
            if action == 'remove':
                return lambda *args: listeners(args).remove(args[-1])
            return lambda *args: args[-1] in listeners(args)
        if name.startswith('__') and name.endswith('__'):
            raise AttributeError(name)
        return Inert()

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)
        if name in self.NOTIFYING:
            self.notify(name)

    def notify(self, prop):
        for callback in list(self._listeners[prop]):
            callback()


class Note:
    _ids = itertools.count(1)

    def __init__(self, spec):
        self.note_id = next(self._ids)
        for name in ('pitch', 'start_time', 'duration', 'velocity', 'mute', 'probability',
                     'velocity_deviation', 'release_velocity'):
            setattr(self, name, getattr(spec, name))

    def __repr__(self):
        return 'Note(p={} t={:g} d={:g} v={:g} rel={:g} prob={:g})'.format(
            self.pitch, self.start_time, self.duration, self.velocity, self.release_velocity, self.probability)


class Clip(LiveObject):
    NOTIFYING = ('loop_start', 'loop_end', 'playing_position', 'is_playing', 'name', 'color')
    is_midi_clip = True
    is_audio_clip = False
    is_arrangement_clip = False
    is_recording = False
    is_triggered = False
    is_overdubbing = False
    looping = True
    muted = False
    signature_numerator = 4
    signature_denominator = 4

    def __init__(self, slot, length):
        super().__init__()
        self.canonical_parent = slot
        self.name = ''
        self.color = slot.canonical_parent.color
        self.color_index = 0
        self._notes = []
        self._selected_ids = set()
        self.loop_start = 0.0
        self.start_marker = 0.0
        self.loop_end = length
        self.end_marker = length
        self.is_playing = False
        self.playing_position = 0.0

    @property
    def length(self):
        return self.loop_end - self.loop_start

    @property
    def playing_status(self):
        return int(self.is_playing)

    def get_notes_extended(self, from_pitch, pitch_span, from_time, time_span):
        return [copy.copy(note) for note in self._notes
                if from_pitch <= note.pitch < from_pitch + pitch_span
                and from_time <= note.start_time < from_time + time_span]

    def add_new_notes(self, specifications):
        self._notes.extend(Note(spec) for spec in specifications)
        self._cut_overlaps()
        self.notify('notes')

    def remove_notes_extended(self, from_pitch, pitch_span, from_time, time_span):
        doomed = {note.note_id for note in self.get_notes_extended(from_pitch, pitch_span, from_time, time_span)}
        self._notes = [note for note in self._notes if note.note_id not in doomed]
        self.notify('notes')

    def apply_note_modifications(self, notes):
        by_id = {note.note_id: note for note in notes}
        self._notes = [copy.copy(by_id.get(note.note_id, note)) for note in self._notes]
        self._cut_overlaps()
        self.notify('notes')

    def deselect_all_notes(self):
        self._selected_ids = set()

    def select_notes_by_id(self, note_ids):
        self._selected_ids.update(note_ids)

    def duplicate_loop(self):
        length = self.length
        copies = [copy.copy(note) for note in self.get_notes_extended(0, 128, self.loop_start, length)]
        for note in copies:
            note.note_id = next(Note._ids)
            note.start_time += length
        self._notes.extend(copies)
        self.end_marker = self.loop_end + length
        self.loop_end = self.loop_end + length
        self._cut_overlaps()
        self.notify('notes')

    def _cut_overlaps(self):
        """Like Live: two notes of the same pitch never overlap; the earlier one ends where the next starts."""
        last = {}
        for note in sorted(self._notes, key=lambda note: note.start_time):
            previous = last.get(note.pitch)
            if previous is not None and previous.start_time + previous.duration > note.start_time + 1e-9:
                previous.duration = note.start_time - previous.start_time
            last[note.pitch] = note

    def notes(self, pitch=None):
        """Test helper: the clip's notes, sorted by time."""
        return sorted((note for note in self._notes if pitch is None or note.pitch == pitch),
                      key=lambda note: (note.start_time, note.pitch))

    def selected_notes(self):
        """Test helper: the notes selected in Live's clip view, sorted by time."""
        return [note for note in self.notes() if note.note_id in self._selected_ids]


class ClipSlot(LiveObject):
    NOTIFYING = ('clip',)
    has_stop_button = True
    is_playing = False
    is_triggered = False
    is_recording = False
    controls_other_clips = False
    will_record_on_start = False
    playing_status = 0
    color = None

    def __init__(self, track):
        super().__init__()
        self.canonical_parent = track
        self.clip = None

    @property
    def has_clip(self):
        return self.clip is not None

    def create_clip(self, length):
        self.clip = Clip(self, length)
        self.notify('has_clip')

    def fire(self, *a, **k):
        LiveSim.current.fired.append(self)


class DrumPad(LiveObject):
    mute = False
    solo = False

    def __init__(self, rack, note, name=None):
        super().__init__()
        self.canonical_parent = rack
        self.note = note
        self.name = name or 'Pad {}'.format(note)
        self.chains = [LiveObject()] if name else []


class RackView(LiveObject):
    NOTIFYING = ('selected_drum_pad', 'drum_pads_scroll_position')

    def __init__(self):
        super().__init__()
        self.selected_drum_pad = None
        self.drum_pads_scroll_position = 9
        self.is_showing_chain_devices = False


class DrumRack(LiveObject):
    can_have_drum_pads = True
    can_have_chains = True
    has_drum_pads = True
    is_active = True
    class_name = 'DrumGroupDevice'
    name = 'Drum Rack'
    parameters = ()
    return_chains = ()

    @property
    def type(self):
        return sys.modules['Live'].Device.DeviceType.instrument

    def __init__(self, track, pads):
        super().__init__()
        self.canonical_parent = track
        self.drum_pads = [DrumPad(self, note, pads.get(note)) for note in range(128)]
        self.visible_drum_pads = self.drum_pads[36:52]
        self.chains = [pad.chains[0] for pad in self.drum_pads if pad.chains]
        self.view = RackView()
        self.view.selected_drum_pad = self.drum_pads[min(pads)]


class Track(LiveObject):
    NOTIFYING = ('playing_slot_index', 'color', 'arm', 'devices')
    has_midi_input = True
    has_audio_output = True
    can_be_armed = True
    is_foldable = False
    is_grouped = False
    is_visible = True
    mute = False
    solo = False
    implicit_arm = False
    fired_slot_index = -1

    def __init__(self, song, name, color, num_scenes, pads=None):
        super().__init__()
        self.canonical_parent = song
        self.name = name
        self.color = color
        self.arm = False
        self.playing_slot_index = -1
        self.clip_slots = [ClipSlot(self) for _ in range(num_scenes)]
        self.devices = [DrumRack(self, pads)] if pads else []
        self.view = LiveObject()
        self.view.selected_device = self.devices[0] if self.devices else None


class Scene(LiveObject):
    is_triggered = False
    color = 0

    def __init__(self, song, index):
        super().__init__()
        self.canonical_parent = song
        self.name = 'Scene {}'.format(index + 1)


class SongView(LiveObject):
    NOTIFYING = ('selected_track', 'selected_scene', 'detail_clip', 'highlighted_clip_slot')

    def __init__(self):
        super().__init__()
        self.selected_track = None
        self.selected_scene = None
        self.detail_clip = None
        self.highlighted_clip_slot = None


class Song(LiveObject):
    NOTIFYING = ('is_playing', 'tracks', 'visible_tracks', 'scenes', 'session_record', 'record_mode')
    signature_numerator = 4
    signature_denominator = 4
    tempo = 120.0
    overdub = False
    metronome = False
    loop = False
    can_undo = False
    can_redo = False
    current_song_time = 0.0

    def __init__(self):
        super().__init__()
        self.view = SongView()
        self.is_playing = False
        self.session_record = False
        self.record_mode = False
        self.return_tracks = []
        self.master_track = None
        self.scenes = []
        self.tracks = []
        self.visible_tracks = []

    def delete_track(self, index):
        """Like Live: the track is gone before anyone hears about it; then the clip view empties
        and a neighbouring track is selected."""
        track = self.tracks[index]
        detail_clip = self.view.detail_clip
        clears_detail_clip = detail_clip is not None and detail_clip.canonical_parent.canonical_parent is track
        for slot in track.clip_slots:
            if slot.clip is not None:
                slot.clip.delete()
            slot.delete()
        for device in track.devices:
            device.view.delete()
            device.delete()
        track.delete()
        self.tracks = [t for t in self.tracks if t is not track]
        self.visible_tracks = list(self.tracks)
        if clears_detail_clip:
            self.view.detail_clip = None
        if self.tracks:
            self.view.selected_track = self.tracks[min(index, len(self.tracks) - 1)]


class AppView(LiveObject):
    focused_document_view = 'Session'

    def is_view_visible(self, name, *a):
        return name == 'Session'


class Application(LiveObject):

    def __init__(self, song):
        super().__init__()
        self.view = AppView()
        self._song = song

    def get_document(self):
        return self._song


class CInstance(LiveObject):
    """What Live hands a control surface: song access and its MIDI output."""

    def __init__(self, sim):
        super().__init__()
        self._sim = sim
        self.instance_identifier = 0

    def song(self):
        return self._sim.song

    def application(self):
        return self._sim.application

    def send_midi(self, midi_bytes):
        self._sim.sent.append(tuple(midi_bytes))

    def request_rebuild_midi_map(self):
        self._sim.rebuild_requested = True

    def log_message(self, message):
        self._sim.log.append(str(message))

    def show_message(self, message):
        self._sim.log.append('message: {}'.format(message))

    def handle(self):
        return 1


# --- The simulation ---

DRUM_KIT = {36: 'Kick', 37: 'Rim', 38: 'Snare', 42: 'Closed Hat', 46: 'Open Hat'}


class LiveSim:
    """One Live set with a drum track (selected) and a second, empty MIDI track."""
    current = None

    def __init__(self, num_scenes=8):
        LiveSim.current = self
        install()
        self.sent = []
        self._echoed = 0
        self.answer_identity_requests = False  # tests that start the surface answer by hand
        self.log = []
        self.fired = []
        self.rebuild_requested = False
        self.song = Song()
        self.application = Application(self.song)
        self.song.scenes = [Scene(self.song, index) for index in range(num_scenes)]
        self.drums = Track(self.song, 'Drums', 0xFF3636, num_scenes, pads=DRUM_KIT)
        self.keys = Track(self.song, 'Keys', 0x3DC300, num_scenes)
        self.song.tracks = [self.drums, self.keys]
        self.song.visible_tracks = list(self.song.tracks)
        self.song.master_track = Track(self.song, 'Master', 0, 0)
        self.song.view.selected_track = self.drums
        self.song.view.selected_scene = self.song.scenes[0]
        self.surface = None

    @property
    def rack(self):
        return self.drums.devices[0]

    def start_surface(self, create_instance, identity=LAUNCHKEY_MK3_37_IDENTITY):
        """Create the surface, connect its ports and answer its identity request, like Live."""
        self.surface = create_instance(CInstance(self))
        self.surface.port_settings_changed()
        self.pump(ticks=2)
        if identity:
            self.receive(*identity, ticks=2)
        return self.surface

    def pump(self, ticks=0):
        """Let the script do what Live would: rebuild its MIDI map and run its timers.

        Like the real Launchkey, the simulated device echoes back every pad-layout change and
        DAW-mode switch it is sent.
        """
        for _ in range(ticks + 1):
            if self.rebuild_requested:
                self.rebuild_requested = False
                self.surface.build_midi_map(1)
            if ticks:
                self.surface.update_display()
            self._echo_mode_changes()

    def _echo_mode_changes(self):
        while self._echoed < len(self.sent):
            message = self.sent[self._echoed]
            self._echoed += 1
            if message[:2] in ((0xBF, 3), (0x9F, 12)):
                self.surface.receive_midi(message)
            elif message == IDENTITY_REQUEST and self.answer_identity_requests:
                self.surface.receive_midi(LAUNCHKEY_MK3_37_IDENTITY)

    def receive(self, *midi_bytes, ticks=0):
        self.surface.receive_midi(tuple(midi_bytes))
        self.pump(ticks)

    def take_sent(self):
        self._echo_mode_changes()
        sent, self.sent = self.sent, []
        self._echoed = 0
        return sent
