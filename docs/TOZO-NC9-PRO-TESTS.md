# TOZO NC9 Pro owner test

Owner: @seth-reee. Hardware session: 2026-09-24 local / 2026-09-25 UTC.

The owner supplied an Android HCI capture and timestamped TOZO app screenshots.
The app showed left 100%, right 100%, case 100%, and each of the six selected
modes. Selected ATT packets, preserving packet identifiers, are in
[capture](captures/tozo-nc9-pro-phone.txt); the complete phone log and screenshots
remain private in the owner's checkout. The selected capture records the
original file hash and time-display offset.

Linux GATT queries then independently confirmed left/right/case 100%, the
case's association in both directions, and all six modes. The first fast
experiment demonstrated transitional readback. A second experiment waited
1.5 seconds after each SET ACK and confirmed modes 0/1/2/3/4/6. Both restored
owner-confirmed ANC. See [raw live capture](captures/tozo-nc9-pro-live.txt).

The implemented bridge subsequently cycled Normal, ANC, Transparency, Reduce
Wind Noise, Leisure and Adaptive. Each was confirmed by a fresh mode query,
and the observed initial Transparency state was restored. All three batteries
were reported by the bridge. See [bridge capture](captures/tozo-nc9-pro-bridge-live.txt).
A physical change to Transparency was also observed while the bridge ran.

Automated coverage uses the model's own full GATT values: exact startup,
all six SETs, ACK versus readback, delayed scheduling, queued commands,
repeated and unsolicited reports, malformed/partial/combined notifications,
checksum errors, unknown modes, battery boundaries, optional case loss and
retry, bidirectional association, two-device isolation, silent versus failed
links, subscription failure, early notifications, shutdown during discovery,
stdin EOF/read errors, stdout closure and cleanup. Probe tests exercise the
full control queue, unknown initial state, interruption, failed sends and
unconfirmed restoration. Fault injection is synthetic, not captured evidence.

Limits: no physical charging capture, unknown battery encoding, low-battery
sample, acoustic measurement, second physical headset, or firmware variation
has been tested. Peer isolation is deterministic simulation. The initial
battery values were all 100%, so left/right ordering uses the owner's app
protocol interpretation and awaits an unequal-level physical sample. No EQ,
case display configuration, firmware update or other unobserved control is
exposed. Case firmware V1.1.5 is visible in the owner's app screenshot.

`CHECK_BASE=upstream/main tools/check` passed with 215 Python tests and the
Model.js tests. `qmllint` is unavailable; the script reports that check skipped.
Final installed-widget validation and gallery capture are recorded below.
