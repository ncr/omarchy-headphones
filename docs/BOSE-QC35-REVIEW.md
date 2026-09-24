# QC35 review evidence

Bose QC35, address `04:52:C7:C2:A9:3E`, firmware `1.0.4`, owned and tested by
[@pedrohfp](https://github.com/pedrohfp). The reviewed change adds a second
question to `bose-bridge` and nothing else: a headset that answers the QC45's
`[31.3]` GET with an ERROR is asked `[1.6]` and polled on it. The QC45's own
path is untouched.

## What protects the QC45

The QC45 answers `[31.3]` with a STATUS, so it never reaches the fallback and
its wire gains no frame. `tests/pins/bose/qc45.json` passes unchanged, and
`tools/check` reports pins unchanged since `origin/main`. No MODELS table was
added: keying one on the reported name would need a QC45 row, and the QC45
capture carries no SDP listing to write it from — the headset decides instead.

## Hardware runs

All on `3aa8974`, with the plugin installed from that revision and nothing else
holding channel 8. Sections of `captures/bose-qc35.txt`:

| Run | Result |
|:--|:--|
| Read-only discovery | init `1.0.4`, battery `02 02 03 01 46` (70%, matching BlueZ), `[31.3]` ERROR, `[1.6]` `01 0b` |
| Driven session | values 0, 1 and 3 accepted and read back; 2 refused with `01 06 04 01 06` and the setting did not move; initial value restored and the restoration verified |
| Bridge over its own pipe | first reading, `set off`, `set anc`, `level low`, `level high`, seven unsupported commands that sent nothing, restoration, exit 0 |
| Reconnect | `bluetoothctl disconnect` showed `not connected`; after reconnect mode, strength and battery all returned. A strength set before the cycle survived it |
| Panel, by the owner | Off, ANC, Low and High all responded, and the owner reports the three states are audibly distinct — High is the stronger cancelling |

## Naming the strengths

The wire reports 0, 1 and 3 and does not say which cancels more. The owner
ranked the three by ear with the values unnamed during the test, twelve
seconds each, two rounds: 3 quietest, 0 loudest. He then confirmed the same
ordering through the panel's own Low and High buttons. Published third-party
tables for this protocol say the reverse; they are not used, and
`tests/bose_qc35_test.py` asserts the hardware's ordering so that a
well-meaning correction toward those tables fails the suite.

## Limits

- **Unsolicited changes are untested.** Three windows totalling 110 seconds
  recorded no `[1.6]` frame the bridge had not asked for, but the owner
  confirmed he did not operate the headset's own controls during any of them.
  Whether this headset announces a change made on the headset itself is
  therefore unknown. The bridge polls every four seconds either way. The
  owner's panel testing does not close this: a panel change travels through
  the bridge, so it is not an unsolicited announcement.
- **Channels 2 and 9 are untried on this headset**, because 8 answered the
  probe first. Untried, not refused.
- **Charging is not established.** The battery read 70% throughout; no
  charging state was observed, and `charging` is always empty here.
- **The support mask is an inference from four observations.** Values 0, 1
  and 3 were accepted and 2 refused, matching mask `0x0b` exactly. No other
  mask has been seen from any Bose.
- **Peer isolation is simulated**, in `tests/bose_qc35_test.py`. No second
  headset was connected alongside this one.
- The `[5.1]` and `[4.2]` frames this headset emits after the init are
  recorded in the capture and stepped over by the framer. Their meaning is
  not established.
