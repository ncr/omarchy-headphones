# The bridge contract

A bridge is one process that holds one link to one device and mirrors its
listening mode. Nine exist — `jbl-bridge`, `sony-bridge`, `samsung-bridge`,
`nothing-bridge`, `xiaomi-bridge`, `soundcore-bridge`, `oppo-bridge`, `bose-bridge`, `tozo-bridge` — and the shell does not
care which is running: they all print the same lines, read the same commands
and end the same four ways. This file is that contract, written once. A
bridge's docstring says what is particular to its protocol and points here
for the rest.

Which bridge a device gets, and what it is started with, is the device's row
in `BACKENDS` in `Model.js`. `DeviceFollower.qml` starts it, feeds it stdin,
reads its stdout line by line and acts on its exit code.

## Command line

```
<brand>-bridge <args as the BACKENDS row lists them>
<brand>-bridge -h | --help          # usage on stdout, exit 0
```

The Classic-channel bridges take the device's Bluetooth address. `sony-bridge`
takes the MDR UUID to register after it and the name the headset reports after
that. `nothing-bridge` takes the reported name after the address to select
its model-specific RFCOMM channel; omitting the name retains channel 15.
`jbl-bridge` takes the BLE address the Fast Pair stream announced and the
Fast Pair model id. A bridge validates its arguments before doing anything
else: an address that is not one is exit 4 with an error line, never a string
handed to BlueZ or a child process.

## stdout: one JSON object per line

Every line is the device's whole state as the bridge knows it, and a line goes
out on every change — the first reading, a mode the user set, a mode the
device changed on its own. Flush after every line. Keys:

| key | type | meaning |
|:--|:--|:--|
| `modes` | bool | required. `true`: the device answered and the row is live. `false`: something is wrong, and `error` says what |
| `error` | string | with `modes: false` — the one sentence the panel shows |
| `mode` | string | `off` · `anc` · `ambient` · `talkthru` — `MODE_ORDER` in `Model.js`, the legacy default names. TOZO explicitly adds `wind`, `leisure`, `adaptive` |
| `available` | list | the modes this device has, from the list above. Absent means all four (the JBL protocol has fixed slots); otherwise list exactly what the device offers |
| `level` | int | the Ambient dial — Sony 0-20, Soundcore 1-5; the range is the row's `ambient` in `BACKENDS`. Only on a device that has one |
| `voice` | bool | the switch beside the dial — Focus on voice (Sony), wind noise reduction (Soundcore). Only with `level` |
| `worn` | bool | a wear sensor: on the ears or not. Sent only after the device has said; a device that never says never carries the key |
| `ancLevel` | string | how strong the noise cancelling is: `low` · `mid` · `high` · `adaptive` (Nothing). With `ancLevels` |
| `ancLevels` | list | the strengths this device grades in, from the four above, weakest first |
| `latency` | bool | the low-latency switch (Nothing). Only after the device has answered for it |
| `battery` | object | `{"left", "right", "case", "headset"}` 0-100 for the parts the device reports, `"charging": [names]`, `"caseStale": bool` when the case reading is the last one seen rather than a live one. A fallback for a device with no Fast Pair stream |

Keys a line omits keep their last value in the shell (`applyAncLine` in
`DeviceFollower.qml` carries `available`, `level`, `voice`, `worn`, `ancLevel`,
`ancLevels`, `latency` and `battery` forward), so a bridge that reports only
what changed is read correctly — but a bridge that reports the whole state is
simpler to pin, and every bridge here does.

Report what the device said, not what was asked for: after a set, the
device's own answer or notification is the source of truth, and a bridge does
not print the new mode on the strength of having sent it.

## stdin: one command per line

```
set off | set anc | set ambient | set talkthru
level <n>                        # the Ambient dial (Sony, Soundcore)
level low | mid | high | adaptive  # ANC strength (Nothing); turns ANC on at it
voice on | off
latency on | off
```

A command for a mode or a switch the device does not have is ignored — the
panel does not draw a button the bridge did not list, so such a line is a
caller's mistake, not a reason to send a frame. Nothing is sent before the
device has answered for its mode.

## Exit codes

| code | meaning | what the shell does |
|:--|:--|:--|
| `0` | clean stop: SIGTERM or SIGINT, or the widget closed the pipe | restarts after the current pause (10 s at first) |
| `1` | transient: the channel never opened, the handshake went unanswered, the link dropped. Says nothing about the device | doubles the pause (up to 5 min) and restarts; shows the error line |
| `3` | linked but silent: connected, asked, heard nothing. This device speaks the channel but not this part of it | parks the address for the session — no restart, no error shown. `r` in the panel clears it |
| `4` | setup failure: bad arguments, a missing Python module, a missing helper program. About this machine | doubles the pause and restarts; shows the error line |

A silent device must be exit 3, not 1: exit 1 dials it again every few
seconds all afternoon.

## Lifecycle

- **One holder.** The device's channel carries both the commands and the
  device's own notifications, and BlueZ hands an RFCOMM profile to one
  registrant. One process owns the link; the widget talks to it through the
  pipe.
- **Die with the shell.** `PR_SET_PDEATHSIG` with SIGTERM, armed first thing,
  and `os._exit(0)` if the parent is already gone. An orphaned bridge keeps the
  registration and the channel, and every bridge started afterwards gets
  nothing.
- **A closed pipe is a clean stop.** EOF or EPIPE on stdout is the widget
  going away: exit 0, without a traceback onto the dead pipe.
- **Profile1 registration** (the D-Bus bridges) at
  `/io/github/ncr/omaphones/<brand>`, `Role` `client`, no authorisation,
  `ConnectProfile` made asynchronously with the long timeout BlueZ needs, and
  `br-connection-busy` on the first attempt retried rather than reported.
  `sony-bridge` and `samsung-bridge` are the two to read.
- **Per-model rows.** Where a bridge has to decide something per model — an
  offset, a question to ask — it is a `MODELS` table keyed by something known
  before the first frame goes out (vendor UUID suffix, reported name), with
  `UNKNOWN` for a model nobody has held. A pinned model's row is not edited
  for another model's sake.
- **No outside dependency.** Omarchy ships `python-dbus`, `python-gobject`
  and `bluez-utils`; a missing one is reported on stdout in the shape above
  and exit 4, never installed.

## Tests

Every bridge has `tests/<brand>_bridge_test.py` on `tests/harness.py`, and
at least one pin under `tests/pins/<brand>/` — the frozen session of one
model: what the device answers, what the bridge writes and prints, frame for
frame. The harness's docstring says how a pin is written. The bridge's only
effects on the world are its writes and its stdout, and a Session captures
both; nothing in the tests touches D-Bus, a socket or a child process.

The canonical owner examples are JBL TUNE230NC TWS and Sony WH-CH720N,
prepared by @ncr. `docs/CANONICAL-TESTS.md` maps their captures, pins, fault
cases, shared battery tests and live integration check. Use that coverage
as the reference for new support, with the new device's own observed frames.


### TOZO NC9 Pro extension

`tozo-bridge <classic-address> <reported-name>` uses BlueZ GATT on the earbuds'
public address. It accepts only its owner's model row. Its optional case link
uses the address reported by the earbuds and validates the reverse association.
Case failure preserves modes and earbud battery; a retained case reading has
`caseStale: true`. Charging state is omitted because no encoding was observed.
The six explicit `available` values are `off`, `anc`, `ambient`, `wind`,
`leisure`, `adaptive`. The three additional names are accepted and displayed
only by the TOZO backend; a missing `available` still means the original four.
Their stdin commands are `set wind`, `set leisure`, `set adaptive`, following
the same device-reported-state rule as the existing commands.
