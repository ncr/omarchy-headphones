# Bose QC35 support — where this stopped

Branch `bose-qc35`, off `948bfb2` (v1.3.10). Nothing here is pushed.

## The naming, settled

The owner ranked the three values by ear on 2026-09-23 — unnamed during the
test, 12 s each, two rounds. 0x00 was the loudest, 0x03 the quietest:

    0x00  off
    0x01  low       the weaker strength
    0x03  high      the stronger strength

**This is the reverse of the published third-party tables**, which claim
0x01 is High. Do not "correct" `NOISE_LEVELS` in `bose-bridge` to match
them: it would put the panel's High button on the weaker setting. The raw
run is `wip/rank-run3.txt`; the live bridge run with the settled names is
`wip/raw-live-bridge-2.txt`.

## Still untested, and recorded as such

Whether the headset announces a change made on the headset itself. Three
watch windows recorded zero unsolicited [1.6] frames, but the owner
confirmed he did not operate the control during them, so this is untested
rather than a negative result. The bridge polls every 4 s, which covers it
either way.

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
