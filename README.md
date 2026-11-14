# Launchkey Seq

Ableton Live control surface script for the Novation Launchkey MK3: everything the stock
Launchkey MK3 script does, plus a 16-step drum sequencer on the pads (like the Launchkey MK4's).

## Install

Needs Ableton Live 12 and a Novation Launchkey MK3 (tested with Live 12.4 and the 37-key model).
On macOS:

```bash
./install.sh
```

On Windows, copy the `Launchkey_MK3_Step` folder to `Documents\Ableton\User Library\Remote Scripts`
and rename it `Launchkey_Seq`.

Live lists it as **Launchkey Seq**. In **Settings → Link, Tempo & MIDI**, set the Launchkey's
Control Surface row to *Launchkey Seq*, with Input *Launchkey MK3 37 (LKMK3 DAW Out)* and Output
*Launchkey MK3 37 (LKMK3 DAW In)*.

## Use

Select a track with a Drum Rack, then **hold Shift and press the 5th pad on the bottom row**
(Custom Mode 1). The pads become 16 steps for the selected drum. Press Shift + the 5th pad again,
or pick any other pad mode, to leave.

| Control | In step mode |
| --- | --- |
| Pads | Top row = steps 1–8, bottom row = 9–16. Tap to add a hit, tap a hit to remove it. |
| ► (right of the pads) | Hold it and tap a step to make the hit accented (909 style); again to un-accent. |
| ▲ / ▼ | Next / previous drum (loaded Drum Rack pads only). |
| Hold a step + turn a pot | Edits only the held hit(s). |
| Pot 1 Velocity | The drum's velocity (accents stay on top). |
| Pot 2 Accent | How much louder accented hits are, for the whole clip. |
| Pot 3 Swing | Swing for the selected drum only, 50% (straight) to 75%, like a TR-909's shuffle or an MPC's 16th swing (the groove of "Revolution 909" or UK garage). It pushes that drum's 16ths between the 8ths later (pads 2, 4, 6… at 1/16); hits on the beat and on the "and" stay on the grid. A drum that plays only 8ths has nothing to swing, and the screen says "no 16ths". Swing doesn't depend on Pot 6, and it selects the drum's notes in Live's clip view. Live can't overlap two hits of one drum, so a hit swung into the next one is trimmed; it gets its length back when you turn swing down. |
| Shift + Pot 3 | The same swing for every drum, like the TR-909's master shuffle (the screen says "all drums"). Turning Pot 3 without Shift then changes just the selected drum again. |
| Pot 4 Length | Note length, 10%–400% of a step. |
| Pot 5 Chance | Probability that the drum's hits play. |
| Pot 6 Steps | Step size: 1/32, 1/16T, 1/16, 1/8T, 1/8, 1/4. |
| Pot 7 Page | Which part of a longer clip the pads show. |
| Pot 8 Bars | Loop length 1, 2, 4 or 8 bars (growing copies the pattern). |

Pad colours: track colour = hit, white = accented hit, grey/green = playhead, dim = beat markers.
The first tap on an empty slot creates a one-bar clip there. The screen shows the drum's name and
each pot's value as you turn it.

Notes:
- Accented hits are marked with release velocity 127 (Drum Racks ignore release velocity).
- The pots only work in step mode while the pot mode isn't one of the Custom pot modes.
- Holding Device Select or using the "…" (Navigation) button returns to the sequencer afterwards.
- In step mode the Launchkey already shows its Session layout, so it doesn't tell Live about
  Shift + Session. A Shift press with nothing else in it is taken as Shift + Session.
- Pot 6 (Steps) sets how much time each pad covers. At 1/16 the 16 pads are one bar; at 1/32
  they're half a bar (Pot 7 shows the second half); at 1/8 they're two bars, so with a one-bar
  loop pads 9-16 stay dark.

## Tests

```bash
python3.11 -m unittest discover tests
```

- `tests/test_step_grid.py`, `test_knobs.py`, `test_pattern.py`: timing, pot and note-editing rules.
- `tests/test_surface_sim.py`, `test_dev_bridge_sim.py`: the real Launchkey MK3 script from the
  installed Live app, run in a simulated Live with the Launchkey's exact MIDI. They need Python
  3.11 (Live's version) and Ableton Live 12, and are skipped otherwise.
- `tests/live/run_live_test.py`: the same checks inside a running Live with the Launchkey
  connected. Install with `./install.sh --dev-bridge`, open Live with Launchkey Seq selected, run
  `python3 tests/live/run_live_test.py`, then `./install.sh` again to remove the test hook. It adds
  and removes a test track and mutes the master while it runs.

## License

MIT, see [LICENSE](LICENSE). Issues and pull requests are welcome.

Launchkey Seq builds on the Launchkey MK3 script that comes with Ableton Live: it loads that
script from your Live installation and includes none of Ableton's code. It isn't affiliated with
or endorsed by Novation, Ableton or Roland. Launchkey is a trademark of Focusrite Audio
Engineering, Ableton Live of Ableton AG, and TR-909 of Roland Corporation.
