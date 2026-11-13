"""In-Live test: drives the installed script inside a running Ableton Live through the dev bridge.

Needs: `./install.sh --dev-bridge`, the script selected as a control surface on the Launchkey's
DAW ports, and Live running. The real Launchkey takes part (identity handshake, layout changes
and their echoes, lights); pad presses, buttons and pot turns are fed to the
script exactly as the Launchkey sends them, and the test checks the notes Live ends up with.

The test adds one MIDI track with a drum kit, mutes the master while it runs, and removes the
track and restores the master volume at the end.

Run: python3 tests/live/run_live_test.py
"""
import json
import os
import socket
import sys
import time

PORT = 9890
SETTLE = 0.5  # seconds for Live to apply deferred edits and for the Launchkey to echo

HELPERS = r'''
import types
PADS = list(range(0x60, 0x68)) + list(range(0x70, 0x78))

def pad_leds(since=0):
    leds = {}
    for message in bridge.sent[since:]:
        if len(message) == 3 and message[0] == 0x90 and message[1] in PADS:
            leds[message[1]] = message[2]
    return [leds.get(note) for note in PADS]

def screen():
    lines = {}
    for message in bridge.sent:
        if message[0] == 0xF0 and len(message) > 8 and message[6] == 4:
            lines[message[7]] = bytes(message[8:-1]).decode('latin1')
    return [lines.get(0), lines.get(1)]

def screen_texts(since=0):
    """Text written to the Launchkey's screen since message `since`, leaving out blanking (a
    message clears itself after a few seconds)."""
    return [bytes(m[8:-1]).decode('latin1') for m in bridge.sent[since:]
            if m[0] == 0xF0 and len(m) > 8 and m[6] == 4 and bytes(m[8:-1]).strip()]

def pot_display(pot):
    """The name and value the Launchkey shows when the pot is turned."""
    texts = {}
    for message in bridge.sent:
        if message[0] == 0xF0 and len(message) > 8 and message[6] in (7, 8) and message[7] == 0x38 + pot:
            texts[message[6]] = bytes(message[8:-1]).decode('latin1')
    return [texts.get(7), texts.get(8)]

def clip():
    slot = bridge.test_track.clip_slots[0]
    return slot.clip if slot.has_clip else None

def notes(pitch=None):
    c = clip()
    if c is None:
        return []
    low, span = (0, 128) if pitch is None else (pitch, 1)
    found = c.get_notes_extended(from_pitch=low, pitch_span=span, from_time=0.0, time_span=10000.0)
    return sorted((round(n.start_time, 4), n.pitch, round(n.velocity), round(n.release_velocity),
                   round(n.duration, 4), round(n.probability, 2)) for n in found)

def tap(*steps):
    for step in steps:
        inject((0x90, PADS[step], 100), (0x90, PADS[step], 0))

def state():
    return {'step_mode': surface._is_step_mode_active(), 'pad_mode': surface._pad_modes.selected_mode}

bridge.h = types.SimpleNamespace(PADS=PADS, pad_leds=pad_leds, screen=screen, screen_texts=screen_texts,
                                 pot_display=pot_display,
                                 clip=clip, notes=notes, tap=tap, state=state)
result = 'ok'
'''

SETUP = r'''
song.stop_playing()
volume = song.master_track.mixer_device.volume
bridge.saved_master_volume = volume.value
volume.value = volume.min
song.create_midi_track(-1)
track = song.tracks[-1]
track.name = 'Launchkey Seq test'
song.view.selected_track = track
song.view.selected_scene = song.scenes[0]
bridge.test_track = track

def first_kit(item, depth=0):
    for child in item.children:
        if child.is_loadable and child.name.lower().endswith('.adg'):
            return child
    if depth < 2:
        for child in item.children:
            if child.is_folder:
                found = first_kit(child, depth + 1)
                if found is not None:
                    return found
    return None

kit = first_kit(app.browser.drums)
app.browser.load_item(kit)
result = kit.name
'''


class LiveConnection:

    def __init__(self, port=PORT, wait=180):
        deadline = time.time() + wait
        while True:
            try:
                self._socket = socket.create_connection(('127.0.0.1', port), timeout=30)
                break
            except OSError:
                if time.time() > deadline:
                    raise
                time.sleep(2)
        self._stream = self._socket.makefile('rw')

    def run(self, code):
        self._stream.write(json.dumps({'code': code}) + '\n')
        self._stream.flush()
        reply = json.loads(self._stream.readline())
        if 'error' in reply:
            raise RuntimeError(reply['error'])
        return reply['result']


class LiveTest:

    def __init__(self, live):
        self.live = live
        self.failures = []

    def run(self, code):
        return self.live.run(code)

    def ask(self, expression):
        return self.run('h = bridge.h\nresult = ' + expression)

    def act(self, code, settle=SETTLE):
        self.run('h = bridge.h\n' + code)
        time.sleep(settle)

    def check(self, name, actual, expected):
        # Values come back from Live as JSON, so compare both sides in that form (tuples -> lists).
        actual, expected = json.loads(json.dumps(actual)), json.loads(json.dumps(expected))
        ok = actual == expected
        print('{} {}{}'.format('PASS' if ok else 'FAIL', name, '' if ok else
                               '\n     expected {!r}\n     got      {!r}'.format(expected, actual)))
        if not ok:
            self.failures.append(name)

    def check_true(self, name, condition):
        self.check(name, bool(condition), True)


CLEAN_UP = r'''
song.stop_playing()
if getattr(bridge, 'test_track', None) is not None and bridge.test_track in list(song.tracks):
    song.delete_track(list(song.tracks).index(bridge.test_track))
bridge.test_track = None
if getattr(bridge, 'saved_master_volume', None) is not None:
    song.master_track.mixer_device.volume.value = bridge.saved_master_volume
if surface._pad_modes.selected_mode != 'session':
    inject((0xBF, 3, 2))
result = None
'''


LIVE_LOG = os.path.expanduser('~/Library/Preferences/Ableton/Live {}/Log.txt')


def script_errors_since(log_path, offset):
    with open(log_path, 'rb') as log:
        log.seek(offset)
        text = log.read().decode('utf-8', 'replace')
    return [line for line in text.splitlines() if 'RemoteScriptError' in line and 'Launchkey_Seq' in line]


def main():
    live = LiveConnection()
    t = LiveTest(live)
    t.run(HELPERS)
    log_path = LIVE_LOG.format(t.run("result = '{}.{}.{}'.format(app.get_major_version(), "
                                     "app.get_minor_version(), app.get_bugfix_version())"))
    log_offset = os.path.getsize(log_path)
    try:
        run_checks(t)
    finally:
        t.run(CLEAN_UP)
        time.sleep(SETTLE)
    t.check('cleaned up and back on the session grid', t.ask("h.state()"), {'step_mode': False, 'pad_mode': 'session'})
    t.check('no script errors in Live\'s log (including deleting the test track)',
            script_errors_since(log_path, log_offset), [])
    print('\n{} failed'.format(len(t.failures)) if t.failures else '\nall checks passed')
    return 1 if t.failures else 0


def run_checks(t):

    # --- The real Launchkey identified the script, and nothing is lit ---
    t.check('real Launchkey answered the identity request',
            t.ask("any(m[:5] == (240, 126, 0, 6, 2) and not injected for m, injected in bridge.received)"), True)
    t.check('script is the step sequencer build', t.ask("type(surface).__name__"), 'Launchkey_MK3_Step')

    kit = t.run(SETUP)
    print('     loaded kit:', kit)
    time.sleep(1.5)
    t.check('drum rack found on the test track',
            t.ask("surface._step_sequencer._drum_rack is not None and surface._step_sequencer._track == bridge.test_track"), True)
    lane = t.ask("surface._step_sequencer._lane_pitch()")
    lane_name = t.ask("surface._step_sequencer._lane_pad().name")
    loaded = t.ask("sorted(p.note for p in bridge.test_track.devices[0].drum_pads if len(p.chains))")
    print('     first lane:', lane, lane_name, '| loaded pads:', loaded)

    # --- Entering step mode, with the real Launchkey echoing the layout change ---
    # A real Shift + 5th pad switches the Launchkey to Custom Mode 1 and reports it; the script then
    # switches it to the session layout, which the Launchkey echoes. Do the switch on the real
    # hardware, then report it.
    t.act("surface._send_pad_layout(5)")
    mark = t.ask("len(bridge.received)")
    t.act("inject((0xBF, 3, 5))", settle=1.0)
    t.check('Shift + 5th pad enters step mode', t.ask("h.state()"), {'step_mode': True, 'pad_mode': 'custom2'})
    t.check('pads switched to the session layout', t.ask("(0xBF, 3, 2) in bridge.sent"), True)
    t.check('real Launchkey echoed the layout change (and it was ignored)',
            t.ask("((0xBF, 3, 2), False) in bridge.received[{}:]".format(mark)), True)
    t.check('empty grid with beat markers', t.ask("h.pad_leds()"), [1, 0, 0, 0] * 4)
    t.check('screen shows the drum', t.ask("h.screen()"), ['Step Sequencer', lane_name])
    t.check('knobs are named for step mode on the Launchkey', t.ask("[h.pot_display(i)[0] for i in range(8)]"),
            ['Velocity', 'Accent', 'Swing', 'Length', 'Chance', 'Steps', 'Page', 'Bars'])

    # The accent and swing amounts carry over from earlier clips: start from known values.
    t.act("inject((0xBF, 22, 27), (0xBF, 23, 0))")

    # --- Steps ---
    t.act("h.tap(0)")
    t.check('tap adds a hit in a new one-bar clip', t.ask("h.notes()"), [(0.0, lane, 100, 64, 0.25, 1.0)])
    t.check('the new clip loops one bar', t.ask("(h.clip().loop_start, h.clip().loop_end)"), [0.0, 4.0])
    hit_color = t.ask("h.pad_leds()[0]")
    t.check_true('hit lights the step in the track colour', hit_color not in (None, 0, 1))
    t.act("h.tap(0)")
    t.check('tapping the hit removes it', t.ask("h.notes()"), [])

    # --- Accents ---
    t.act("inject((0xB0, 104, 127)); h.tap(4); inject((0xB0, 104, 0))")
    t.check('► + tap adds an accented hit', t.ask("h.notes()"), [(1.0, lane, 127, 127, 0.25, 1.0)])
    t.check('accented step is white', t.ask("h.pad_leds()[4]"), 3)

    # --- Pots ---
    t.act("h.tap(0, 2)")
    mark = t.ask("len(bridge.sent)")
    t.act("inject((0xBF, 21, 64))")
    t.check('velocity pot sets the lane, accents stay on top',
            [n[2] for n in t.ask("h.notes()")], [64, 64, 91])
    t.check('turning a knob shows its step mode name and value', t.ask("h.pot_display(0)"), ['Velocity', '64'])
    t.check('nothing else writes over it', t.ask("h.screen_texts({})".format(mark)), [])
    t.act("inject((0xBF, 22, 50))")
    t.check('accent pot sets the accent amount', [n[2] for n in t.ask("h.notes()")], [64, 64, 114])
    t.act("h.tap(1, 3)")
    t.act("inject((0xBF, 23, 127))")
    t.check('swing pot delays the off-beats', [n[0] for n in t.ask("h.notes()")], [0.0, 0.375, 0.5, 0.875, 1.0])
    t.check('the screen shows the swing', t.ask("h.pot_display(2)"), ['Swing', '75%'])
    t.check('swing trims hits only where they run into the next one (Live allows no overlap)',
            [[n[0], n[4]] for n in t.ask("h.notes()")],
            [[0.0, 0.25], [0.375, 0.125], [0.5, 0.25], [0.875, 0.125], [1.0, 0.25]])
    t.check("swing selects the drum's notes in the clip view",
            t.ask("sorted(n.pitch for n in h.clip().get_selected_notes_extended())"), [lane] * 5)
    t.act("inject((0xBF, 23, 0))")
    t.check('swing back to straight', [n[0] for n in t.ask("h.notes()")], [0.0, 0.25, 0.5, 0.75, 1.0])
    t.check('swing back gives the lengths back', sorted({n[4] for n in t.ask("h.notes()")}), [0.25])
    t.act("inject((0xBF, 24, 0)); inject((0xBF, 25, 64))")
    t.check('length and chance pots', sorted({(n[4], n[5]) for n in t.ask("h.notes()")}), [(0.025, 0.5)])
    t.act("inject((0xBF, 24, 80)); inject((0xBF, 25, 127))")

    # --- Holding a step ---
    t.act("inject((0x90, h.PADS[6], 100))", settle=0.2)
    t.act("inject((0xBF, 21, 30))")
    t.act("inject((0x90, h.PADS[6], 0))")
    held = [n for n in t.ask("h.notes()") if n[0] == 1.5]
    t.check('holding a new step and turning velocity edits only it', [n[2] for n in held], [30])
    t.check('other hits untouched', [n[2] for n in t.ask("h.notes()") if n[0] != 1.5], [64, 64, 64, 64, 114])

    # --- Lanes ---
    if len(loaded) > 1:
        next_lane = min(note for note in loaded if note > lane) if any(note > lane for note in loaded) else None
        t.act("inject((0xBF, 106, 127), (0xBF, 106, 0))")
        if next_lane is not None:
            t.check('up arrow moves to the next loaded pad',
                    t.ask("bridge.test_track.devices[0].view.selected_drum_pad.note"), next_lane)
            t.check('screen shows the new drum', t.ask("h.screen()")[1],
                    t.ask("bridge.test_track.devices[0].view.selected_drum_pad.name"))
            t.check('the new lane shows its own (empty) steps', t.ask("h.pad_leds()"), [1, 0, 0, 0] * 4)
            t.act("h.tap(2)")
            t.check('hits go to the new lane', [n[1] for n in t.ask("h.notes()") if n[0] == 0.5], sorted([lane, next_lane]))
            t.act("h.tap(3)")
            t.act("inject((0xBF, 23, 127))")
            t.check('swing moves only the selected drum',
                    [n[:2] for n in t.ask("h.notes()") if n[0] in (0.75, 0.875)], [[0.75, lane], [0.875, next_lane]])
            t.act("inject((0xBF, 23, 0))")
            t.check('and back', [n[:2] for n in t.ask("h.notes()") if n[0] == 0.75], sorted([[0.75, lane], [0.75, next_lane]]))
            t.act("h.tap(3)")  # remove it: the new lane now plays only an off-beat 8th
            t.act("inject((0xBF, 23, 127))")
            t.check('an off-beat 8th stays on the grid, like on a 909',
                    [n[:2] for n in t.ask("h.notes()") if n[1] == next_lane], [[0.5, next_lane]])
            t.check('the screen says there are no 16ths to swing', t.ask("h.pot_display(2)"), ['Swing', '75% no 16ths'])
            t.act("inject((0xBF, 23, 0))")
        t.act("inject((0xBF, 107, 127), (0xBF, 107, 0))")
        t.check('down arrow goes back', t.ask("bridge.test_track.devices[0].view.selected_drum_pad.note"), lane)

    # --- Pages, bars and step size ---
    count = len(t.ask("h.notes()"))
    t.act("inject((0xBF, 28, 127))")
    t.check('bars pot grows the loop to 8 bars', t.ask("h.clip().loop_end"), 32.0)
    t.check('growing copies the pattern', len(t.ask("h.notes()")), count * 8)
    t.act("inject((0xBF, 27, 20))")
    t.check('page pot shows page 2', t.ask("h.pot_display(6)"), ['Page', '2/8'])
    t.act("inject((0xBF, 28, 0)); inject((0xBF, 27, 0))")
    t.check('bars pot shrinks the loop back', t.ask("h.clip().loop_end"), 4.0)
    t.act("inject((0xBF, 26, 127))")
    t.check('step size pot', t.ask("h.pot_display(5)"), ['Steps', '1/4'])
    t.act("inject((0xBF, 26, 50))")
    t.check('step size back to 1/16', t.ask("h.pot_display(5)"), ['Steps', '1/16'])

    # --- Playhead (master muted) ---
    mark = t.ask("len(bridge.sent)")
    t.act("bridge.test_track.clip_slots[0].fire()", settle=2.0)
    t.check_true('playhead moves across the pads while playing',
                 t.ask("any(v in (2, 21) for v in h.pad_leds({}))".format(mark)))
    t.act("song.stop_playing(); song.stop_all_clips()", settle=0.5)

    # --- Leaving and coming back ---
    t.act("inject((0xBF, 3, 5))")
    t.check('Shift + 5th pad again goes back to session', t.ask("h.state()"), {'step_mode': False, 'pad_mode': 'session'})
    t.act("inject((0xBF, 3, 5))")
    t.act("inject((0xBF, 3, 9))")
    t.check('holding Device Select borrows the pads', t.ask("h.state()"), {'step_mode': False, 'pad_mode': 'device_select'})
    t.act("inject((0xBF, 3, 2))")
    t.check('releasing Device Select returns to the sequencer', t.ask("h.state()"), {'step_mode': True, 'pad_mode': 'custom2'})
    t.act("inject((0xBF, 3, 10))")
    t.check('Navigation pauses the sequencer', t.ask("h.state()['step_mode']"), False)
    t.act("inject((0xBF, 3, 2))")
    t.check('leaving Navigation returns to the sequencer', t.ask("h.state()"), {'step_mode': True, 'pad_mode': 'custom2'})
    t.act("inject((0xB0, 108, 127), (0xB0, 108, 0))")  # Shift + Session: only Shift reaches Live
    t.check('Shift + Session goes back to session', t.ask("h.state()"), {'step_mode': False, 'pad_mode': 'session'})
    t.act("inject((0xBF, 3, 5))")
    t.act("inject((0xBF, 3, 1))")
    t.check('Drum mode leaves the sequencer', t.ask("h.state()"), {'step_mode': False, 'pad_mode': 'drum'})
    t.check_true('the stock knob names are back', t.ask("h.pot_display(0)[0]") != 'Velocity')


if __name__ == '__main__':
    sys.exit(main())
