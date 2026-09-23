# Bose QC35 support — where this stopped

Branch `bose-qc35`, off `948bfb2` (v1.3.10). Nothing here is pushed.

## The one thing that is blocked

**Which of the [1.6] values 0x01 and 0x03 is High and which is Low.** The
headset reports numbers; only a person wearing it can name them. The tables
in the code currently read `0x03 low, 0x01 high`, which is what third-party
clients claim — it is NOT confirmed on this headset and must not ship until
it is. If the owner's ranking comes back the other way, flip `NOISE_LEVELS`
in `bose-bridge` and the names in the pin, the capture and PROTOCOL.md.

`wip/qc35_rank.py` is the test to run: three unnamed states, 12 s each, two
rounds. The owner says which was quietest and which was loudest.
State 1 = 0x00, state 2 = 0x01, state 3 = 0x03.

A second, smaller gap: whether the headset announces a change made on the
headset itself. Two watch windows recorded zero unsolicited [1.6] frames,
but it is not established that the owner operated the control during either,
so this is untested rather than a negative result. The bridge polls anyway.

## Done

- `bose-bridge`: the [1.6] path, reached only when a headset answers the
  QC45's [31.3] GET with an ERROR. The QC45's wire is unchanged — its pin
  passes untouched, which is the proof.
- `tests/pins/bose/qc35.json`: the frozen session. 23 bridge tests pass.
- Hardware: the real bridge drove the real headset end to end — first
  reading, set off, set anc, level low, level high, five unsupported
  commands ignored, restored, exit 0. `wip/raw-live-bridge.txt`.

## Left to do

- Extend `tests/bose_bridge_test.py` for the [1.6] path to the coverage
  `.agents/skills/add-new-bridge/SKILL.md` requires: timeout driven through
  the run loop, disconnect through `on_socket`, partial and coalesced reads,
  shutdown during connect, readback driven through scheduling, isolation.
- `docs/captures/bose-qc35.txt` from the raw logs in this directory.
- `PROTOCOL.md` subsection, README row and gallery cell, `tools/gallery-shot`
  screenshot, `manifest.json` if it names models.
- Consolidate the four probes here into one `tools/bose_qc35_session.py`
  in the shape `tools/bose_session.py` has, and delete `wip/`.
- `tools/check`, then the PR.

## The headset

`04:52:C7:C2:A9:3E`, named "pedro qc35" — a name its owner typed into the
Bose app, which is exactly why no MODELS table is keyed on it.
