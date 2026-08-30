# What these headphones say, and how

Notes from probing a **JBL TUNE230NC TWS** (`A0:11:22:33:44:55`, modalias
`bluetooth:v02B0p0000d001F`, Fast Pair model id `71f20a`) on Arch/BlueZ 5.87.
Its *audio* side is BR/EDR only — every profile `bluetoothctl info` lists is
RFCOMM or A2DP, and there is no GATT to read on it. The control protocol is on a
separate LE connection: [further down](#the-control-protocol-lives-on-ble-and-it-is-fully-working).

The [Sony section](#sony-mdr-v2--the-listening-mode-on-the-wh-ch720n) is a
different device and a different protocol: a **Sony WH-CH720N**
(`B0:11:22:33:44:55`), whose listening mode is on an RFCOMM channel of its own.
The [Xiaomi section](#xiaomi-buds-5-pro--compact-gaia-on-spp) is Xiaomi Buds 5
Pro: Compact GAIA on standard SPP. The [Soundcore section](#soundcore-space-2--vendor-rfcomm)
is Soundcore Space 2: vendor RFCOMM (`0cf12d31-…`). Everything before Sony is the JBL.

The tools that produced all of this are in [`tools/`](tools/). The Python
probes each register an `org.bluez.Profile1` for one UUID, so BlueZ does the SDP
lookup and hands over a connected RFCOMM socket; no `sdptool`, no root, nothing
left registered after the process exits. [`tools/jbl-anc`](tools/jbl-anc) is the
odd one out: it drives `btgatt-client` over LE, and shells out to
`tools/gfps_probe.py` only to read the rotating BLE address, and only when there
is no widget running to be asked for it.
[`tools/sony_probe.py`](tools/sony_probe.py),
[`tools/xiaomi_probe.py`](tools/xiaomi_probe.py), and
[`tools/soundcore_probe.py`](tools/soundcore_probe.py) speak framed protocols rather
than dumping bytes: Sony does the MDR handshake and asks each NC/ASM variant;
Xiaomi does Compact GAIA on SPP; Soundcore queries state and sets sound modes.

## The channels

`bluetoothctl info` lists eleven UUIDs. The ones that matter:

| UUID | What it is | Answers? |
|---|---|---|
| `df21fe2c-2515-4fdb-8886-f12c4d67927c` | Google Fast Pair Message Stream | **Yes — battery per earbud** |
| `8a482a08-5507-42ac-b673-a88df48b3fc7` | JBL vendor channel | Yes: a 3-byte heartbeat unprompted, and a 1-byte `00` to every command tried |
| `931c7e8a-540f-4686-b798-e8df0a2ad9f7` | Amazon AMA (Alexa), per Qualcomm ADK `ama_rfcomm.c` | one greeting frame on connect, then silence |
| `66666666-…`, `81c2e72a-…`, `f8d1fbe4-…` | vendor channels | connect, then total silence |
| `00001101-…` | plain SPP | connects, says nothing |

And one that is not on this device at all, listed here because it is the other
half of the widget's listening mode:

| UUID | What it is | Answers? |
|---|---|---|
| `956c7b26-d49a-4ba8-b03f-b17d393cb6e2` | Sony MDR protocol v2 — served by the WH-CH720N and by the current WH/WF range | **Yes — listening mode**, [last section](#sony-mdr-v2--the-listening-mode-on-the-wh-ch720n) |
| `96cc203e-5068-46ad-b32d-e316f5e069ba` | Sony MDR protocol v1, the older headsets | **Yes — listening mode**, [the WH-1000XM4](#wh-1000xm4) |

## Fast Pair Message Stream — this is where the battery lives

A public Google spec, not a JBL protocol:
<https://developers.google.com/nearby/fast-pair/specifications/extensions/messagestream>

Frame: `group u8 | code u8 | length u16 big-endian | payload`.

What this device sends, unprompted, right after the channel opens:

```
0301 0003 71f20a           group 3 code 1  model id
0302 0006 5b66778899aa     group 3 code 2  BLE address
0303 0003 0a0aa2           group 3 code 3  battery
```

Code `0x09` in the same group is the firmware version, an ASCII string;
`gfps-reader` decodes it and passes it through as `firmware` for any device that
sends one, though nothing in the widget draws it.

Battery payload is one byte per component — left, right, case — with the high
bit meaning charging and the low seven bits the percentage. A byte of the form
`0b?1111111` — `0x7F`, or `0xFF` with the charging bit set — means "no reading",
which is what a bud sitting in the case reports:

```
0a 0a a2  ->  left 10%, right 10%, case 34% charging
7f 0a a2  ->  left in the case, right 10%, case 34% charging
```

A one-byte payload means a set with a single battery — an over-ear headset like
the WH-CH720N. `gfps-reader` reports that as `battery` with `single` true, and
leaves left, right and case at -1: a headset with one battery has no left
earbud, and a figure put in `left` reads downstream exactly like one that was
measured there.

The reader's JSON line, key by key:

| Key | Meaning |
|---|---|
| `address` | which device the line is about, uppercase colon-separated. One reader serves every followed device, since BlueZ registers the profile once for the whole system; a line without an address is about the reader itself and is the last thing it writes |
| `stream` | true while the channel is up; the `{address, stream, error}` line is the only place it is false |
| `single` | true when the device reports one battery for the whole set |
| `battery`, `batteryCharging` | that single figure, 0-100 or -1, and its charging bit; -1/false for a three-battery set |
| `left`, `right`, `case` | 0-100, or -1 for "no reading"; all -1 when `single` |
| `leftCharging`, `rightCharging`, `caseCharging` | that component's charging bit |
| `modelId` | Fast Pair model id, hex; sent once per connection, then repeated in every later line |
| `bleAddress` | the rotating BLE address, one-shot and sticky like `modelId` |
| `firmware` | firmware version string, one-shot and sticky too |

Two things worth knowing:

- **It pushes.** The device sends a battery message on connect and again when a
  level changes. There is nothing to poll, and no way to ask for a figure the
  device thinks you already have — hence the widget's `r`, which sends
  `refresh <address>` to the reader's stdin so it drops that one channel and the
  device re-announces. `follow` and `unfollow` are the other two commands, and
  they are how the set of devices changes without the registration going with
  it.
- **It beats BlueZ's number.** `org.bluez.Battery1` on this device comes from
  the HFP battery indicator, which has ten steps: it read `0x14 (20)` while the
  Message Stream reported 10% in both buds. Same hardware, coarser channel.

## The RFCOMM vendor channel — a dead end worth recording

`8a482a08-5507-42ac-b673-a88df48b3fc7` is the only RFCOMM channel that replies
to a command, and it turned out not to be the one the app uses. Recorded because the
framing differs from the BLE transport, and because the refusals below are what
sent the search to BLE in the first place.

Frame, worked out from its own replies:

```
magic u8 | cmd u8 | seq u8 | length u8 | payload[length] | checksum u8
0xAA = request, 0xBE = response or notification
checksum = (~sum(every preceding byte)) & 0xFF
```

Every observed checksum fits: `be 21 01 01 00 1e` sums to `0xe1`, and
`~0xe1 = 0x1e`.

Unprompted, roughly every two seconds:

```
be 50 00 03 000001 ed
be 50 01 03 000001 ec     seq increments, payload never changes
```

Sending the JBL Headphones app's command set — taken from
[GroupXyz2/bluetooth-py](https://github.com/GroupXyz2/bluetooth-py)'s
`JblProtocol.kt`, captured over BLE GATT from the official Android app — with
[`tools/jbl_probe.py`](tools/jbl_probe.py), which produced this table, gets the
cmd echoed with a single `0x00` payload, every time:

| Sent | Got back |
|---|---|
| `aa 9b 00 02 0101 b6` enable notifications | `be 9b 00 01 00 a5` |
| `aa 21 00 01 30 03` version | `be 21 00 01 00 1f` |
| `aa 25 00 01 00 2f` battery | `be 25 00 01 00 1b` |
| `aa 91 00 01 11 b2` ANC state | `be 91 00 01 00 af` |
| `aa 94 00 01 01 bf` model | `be 94 00 01 00 ac` |
| `aa 77 00 02 01ff dc` capabilities | `be 77 00 01 00 c9` |

The framing is right — the device mirrors the `seq` byte, and malformed frames
produced `seq=0x01` instead. So `0x00` is this model answering "no" to each of
those command numbers. That app's numbers came from a GATT-based JBL; a
BR/EDR TUNE-series set evidently uses a different vocabulary on this channel.

### The listening experiment, and its answer

Listening on RFCOMM found nothing. Two rounds with
[`tools/jbl_listen.py`](tools/jbl_listen.py), which writes nothing at all, while
the earbud gesture switched modes repeatedly:

- On `8a482a08`, three minutes of toggling produced 85 frames, every one the same
  heartbeat `be 50 <seq> 03 000001`. The payload never varied.
- A second round listened on `66666666`, `81c2e72a`, `f8d1fbe4` and the AMA
  channel `931c7e8a` **at once** — four registrations, four open channels — through
  another set of toggles. Total frames: one, the greeting `fe 03 01 00…00` that
  AMA sends on connect.

That was the right experiment on the wrong transport.

## The control protocol lives on BLE, and it is fully working

The Message Stream itself gave up the lead. Device information code `0x02` is the
**BLE address**, and it is a resolvable private address, so it rotates and cannot
be written down:

```
0302 0006 4a1122334455     ->  4A:11:22:33:44:55   (was 5B:66:77:88:99:AA an hour earlier)
```

On LE the earbuds advertise as `JBL TUNE230NC TWS-LE` and accept a connection.
Their GATT tree carries a service whose UUID spells its own vendor:

```
65786365-6c70-6f69-6e74-2e636f6d0000
65 78 63 65 = "exce"   6c 70 = "lp"   6f 69 = "oi"   6e 74 = "nt"   2e 63 6f 6d = ".com"
```

| handle | UUID | props | role |
|---|---|---|---|
| `0x000c` | `…2e636f6d0001` | `0x12` read + notify | the device talks here |
| `0x0010` | `…2e636f6d0002` | `0x0c` write + write-without-response | commands go here |

Enumerate it with:

```bash
btgatt-client -d <ble-address> -t random     # then: services
```

The rest of the tree, for the record: `0000fe2c` (Fast Pair, four
notify/write characteristics `1234`-`1237`), `0000fe03` (with `2beea05b…`
read/notify and `f04eb177…` write), `66666666-…`/`77777777-…`,
`86868686-…`/`97979797-…`, plus generic access and attribute services.

### Frames

On this transport there is **no sequence byte and no checksum** — unlike the
RFCOMM channel, which wanted both:

```
AA <cmd> <payload length> <payload…>
```

Confirmed exchanges, every one of them observed:

| sent to `0x0010` | notified on `0x000c` | meaning |
|---|---|---|
| — | `aa 12 25 4a 42 4c 20 54 55 4e 45 32 33 30 4e 43 20 54 00 4b` | device name, `"JBL TUNE230NC T…"`, truncated by the 20-byte default ATT MTU |
| `aa 21 01 30` | `aa 22 0d 30 00 02 00 04 df 01 00 00 01 00 00 00` | version; the one reply here that arrives under a different command byte |
| `aa 9b 02 01 01` | `aa 9b 03 02 01 00` | enable notifications, acknowledged |
| `aa 25 01 00` | `aa 25 0d 01 00 00 0a 1e 00 4e 10 0e 78 0e cc 0c` | battery |
| `aa 91 01 11` | `aa 91 07 12 01 00 02 01 03 00` | listening mode |

**How a reply is addressed.** Only the version exchange answers under `cmd + 1`
(`0x21` → `0x22`). Everything else keeps the command byte and increments the
first payload byte, the opcode: `0x91` `0x11` get is answered by `0x91` `0x12`
report, `0x9b` `0x01` by `0x9b` `0x02`, `0x25` `0x00` by `0x25` `0x01`.

**Battery, cross-checked against Fast Pair.** Byte offsets here are 0-based and
count the leading `aa` as byte 0. Frame bytes 6, 7 and 9 read
`0x0a`, `0x1e`, `0x4e` — 10, 30 and 78 — while the Message Stream reported
left 10%, right 30%, case 78% at the same moment. Two independent channels, same
numbers. Note that byte 8 is `00`: the case level is at **byte 9**, not byte 8 as
[bluetooth-py](https://github.com/GroupXyz2/bluetooth-py) has it for its device.
The tail `10 0e / 78 0e / cc 0c` reads as little-endian 3600, 3704 and 3276,
which look like millivolts — *hypothesis, not verified*.

### The slot order follows the spec, and the levels lag

Google's Battery Notification spec says the three values are ordered *left bud,
right bud, case*, with `0b?1111111` for unknown. This device obeys it. Verified by
docking one known earbud: with the left in the case and the channel re-opened, the
first byte reads `0x7F` and the second still reports.

That test was run because a level appeared to jump between earbuds, which turned
out to be something else: **an earbud's level is only as fresh as the last
announcement.** The earbuds announce on connect and when a level changes, and
docking an earbud is neither, so a bud parked in the case keeps showing its last
level until something asks again. A bud that charged from 20% to 60% in the case
therefore appears to "jump" when it comes back — that is the charged value
arriving, not a slot mix-up.

The widget re-opens the channel when the panel is opened and the last reading is
over thirty seconds old, which is the only moment the freshness matters, and `r`
forces it at any time.

### The case is reported second-hand

The battery frame carries the case like any other component, but the earbud
sending it only knows what the case last told it, and the two disagree for a long
time. Observed over one session on a TUNE230NC:

| moment | case level | charging bit | actually |
|---|---|---|---|
| all afternoon | 78% | clear | on a charger part of that time |
| case plugged in, one earbud inside | 78% | **clear** | charging |
| after an earbud docked and came out | 98% | set | just off the charger |
| case empty, no cable, 90+ seconds | 98% | **set** | charging nothing |

So the level refreshes when an earbud docks and can talk to the case, and the
charging bit is not cleared by anything on that timescale. Both are stale between
those events. The earbuds' own levels, by contrast, track live: the right earbud
read 100% within seconds of coming out of the case.

The widget therefore shows the case's level and not its charging bolt. A level
that lags is a small lie; a bolt that says "charging, now" with the cable out is a
plain one.

An earbud *in* the case reports `0x7F`, no reading, so a charging earbud is never
visible either — and an earbud only charges in the case.

### Listening modes

Command `0x91`, then an opcode and slot/value pairs. Slot 1 is ANC, slot 2 is
Ambient Aware, slot 3 is TalkThru. Opcodes: `0x10` set, `0x11` get, `0x12` report.

| mode | payload | evidence |
|---|---|---|
| Off | `10 01 00 02 00 03 00` | set, reported back, read back |
| ANC | `10 01 01 02 00 03 00` | set, reported back, read back, audibly engaged |
| Ambient Aware | `10 01 00 02 01 03 00` | set, reported back; also the state found on arrival |
| TalkThru | `10 01 00 02 00 03 01` | set, reported back — the slot is real on this model |

Two behaviours worth knowing, both observed:

- **A set is answered by a report.** Writing a mode produces an unsolicited
  `aa 91 07 12 …` immediately, so there is no need to read back.
- **The touch control reports too.** Holding the subscription while pressing the
  earbud produced nine reports tracing the cycle **Off → ANC → Ambient Aware →
  Off → …**. TalkThru is not in the touch cycle, but is settable over the
  protocol. The device does *not* report on subscription alone: with nobody
  touching anything, a fresh subscription stays silent until something changes.

### Fast Pair Hearable Controls: absent

Fast Pair standardised noise control in January 2024 as message group `0x08`
(`0x11` get, `0x12` set, `0x13` notify — per the spec as read, unverified here,
since nothing ever answered). This device predates it and ignores it:
[`tools/gfps_probe.py`](tools/gfps_probe.py) writes `08 11 00 00` on the Message
Stream 1.5 seconds after the channel opens, and that got no reply across three
separate windows of 25, 90 and 12 seconds. Everything above is JBL's own protocol
instead.

### In the widget

[`jbl-bridge`](jbl-bridge) is the same protocol as a long-lived process: it owns
one BLE link, prints a JSON line whenever the mode changes, and takes `set <mode>`
on stdin. The plugin's service spawns it while the earbuds are connected and
writes commands into it — the service, not the panel, so a second monitor's
widget does not mean a second link. That one conversation is why clicking a mode
and hearing about a touch-control change come back the same way; a second
connection would be refused with *Device or resource busy*.

Two details that cost time. On bluez 5.87 `btgatt-client` flushes after every
notification, so it needs no unbuffering of its own — but the stages after it in
a shell pipeline block-buffer, which is why `tools/jbl-anc` pipes through
`sed -u` and a line-buffered `grep`. And the BLE address rotates, so the bridge
is restarted whenever the Message Stream reports a new one.

A third, and it is bluetoothd's rather than the earbuds'. bluez 5.87 as shipped
(Arch 5.87-2) dies with SIGSEGV in `device_found_callback` whenever some D-Bus
client runs discovery with a UUID filter and a device advertises a matching
UUID — the earbuds' Fast Pair `FE2C`, for one. `is_filter_match()` in
`src/adapter.c` hands `queue_find()` its arguments swapped and calls the UUID
string as a function; upstream fixed it six days after the release, in commit
`82af2beaf` (bluez/bluez#2282). Nothing in this plugin scans or sets a filter,
and the crash restarts bluetoothd and drops every headset regardless. Until
a bluez with that commit ships, the one-line patch rebuilt into the distro's
package is the fix.

What the bridge's exit code means, because the answer to "does this model speak
the protocol" is only some of the ways it can end:

- **1, transient** — the link never opened, was refused, or closed under the
  bridge. That says nothing about the device, so nothing is written down and the
  service tries again after 10 seconds, then 20, then 40, up to five minutes.
- **3, linked but silent** — connected, discovered, asked, heard nothing. The
  bridge records one miss against the Fast Pair model id in
  `$XDG_STATE_HOME/omaphones/mode-support.json` and the service leaves that model
  alone for the rest of the session. Three misses, which takes three sessions,
  and the entry reads `"supported": false`: no link is opened for that model
  again, ever. Three rather than one because a stale BLE address makes the
  connection hang with no error at all.
- **4, setup failure** — no `btgatt-client`, or arguments the bridge will not
  take. Nothing is recorded, because that is about this machine; the model is
  parked for the session and the reason is shown where the row would be.
- **0** is a clean stop and means nothing at all.

Delete the file to ask again.

### The tool

[`tools/jbl-anc`](tools/jbl-anc) does all three things from the command line:

```bash
jbl-anc get                              # ambient — answered by the widget
jbl-anc set anc                          # anc — the widget writes the frame
jbl-anc watch                            # the mode, then every change, touch included
jbl-anc watch 60 AA:BB:CC:DD:EE:FF       # the same, with no widget to ask
```

`get` and `set` ask the running Omaphones widget first, over IPC
(`omarchy-shell omaphones mode` and `setMode`), and take the answer when it is a
real mode or a plain `ok`. `pending` and `busy` mean the widget's bridge is still
connecting, so the same question is put again every half second for fifteen
seconds and then given up on: the earbuds accept one ATT link and the widget is
about to be holding it, so opening our own would only be refused. `unsupported`,
`unavailable` and no shell at all fall back to the air, and that path needs the
rotating BLE address: `omarchy-shell omaphones bleAddress` while the widget is up,
because BlueZ allows one holder per profile UUID and a second Message Stream
reader would simply be refused, and `tools/gfps_probe.py` when it is not. That
second route is what the earbuds' *Classic* address is for, as a trailing
argument or in `JBL_MAC`; with neither a widget nor an address `jbl-anc` says so
rather than guessing.

`watch` has no widget equivalent and is always the direct path — but the address
still comes from the widget while one runs, so the trailing MAC is for when there
is none. The earbuds accept one ATT link, so turn the widget's mode control off
first (`useModeControl` false) or `btgatt-client` reports *Failed to connect*.

### What not to do

Do not sweep `cmd` from `0x00` to `0xFF` to see what answers. Somewhere in that
space are the firmware-update, factory-reset and shutdown commands, and a blind
sweep on the only earbuds you own is how you find them. The RFCOMM command
numbers above are frames the official Android app is known to send, by way of
bluetooth-py; the BLE payloads were worked out here, from what the earbuds
reported back to the frames those numbers suggested.

## Sony MDR v2 — the listening mode on the WH-CH720N

A different headset and a different protocol, on a channel Sony serves itself:

```
956c7b26-d49a-4ba8-b03f-b17d393cb6e2   MDR protocol v2   <- WH-CH720N, WH-1000XM5, WF-1000XM5…
96cc203e-5068-46ad-b32d-e316f5e069ba   MDR protocol v1   <- WH-1000XM4, the older range
```

Nothing had to be reverse engineered for this one. The frame format is in
[Gadgetbridge](https://codeberg.org/Freeyourgadget/Gadgetbridge) (its Codeberg
repository — the GitHub mirror is years stale) and the command tables are in
[mos9527/SonyHeadphonesClient](https://github.com/mos9527/SonyHeadphonesClient),
whose `libmdr/include/mdr/ProtocolV2T1.hpp` is generated from Sony's own message
classes. What is written down here is only what this headset was seen to do,
because the two projects disagree about this model and only the hardware
settles it.

**Opening it.** Register an `org.bluez.Profile1` with `UUID` set to the v2 UUID,
`Role` `client`, `Channel` `0`, and BlueZ does the SDP lookup and hands over a
connected socket in `NewConnection` — the same arrangement as the Fast Pair
reader, and the same one-holder consequence. Two details cost an afternoon:

- **`ConnectProfile` must be called asynchronously.** It is a D-Bus method on
  the device object, and calling it blocking stalls the very GLib loop that is
  supposed to deliver `NewConnection`, so the connection completes and the
  callback never arrives. With `reply_handler`/`error_handler` it works.
- **The first attempt usually fails**, with `br-connection-busy`: bluetoothd is
  still doing its own SDP and profile setup. A retry 1.5 seconds later
  connects. Gadgetbridge's equivalent is a flat 500 ms wait before opening the
  socket at all, "connecting too fast fails" — the bridge does both, waiting
  half a second after registering and then retrying patiently.

And then nothing happens: **the channel is silent until the handshake goes out.**
An open socket with no traffic is the normal state, not a fault.

### Frames

```
  3E  <TYPE> <SEQ> <LEN0 LEN1 LEN2 LEN3> <PAYLOAD…> <CKSUM>  3C
  ^   \_______________________________________________________/  ^
start        this whole span is byte-stuffed                     end
```

| field | size | meaning |
|---|---|---|
| start | 1 | `0x3E`, never escaped |
| type | 1 | `0x0C` command, `0x01` ACK (also `0x0E`, a second command table) |
| seq | 1 | one toggling bit, `0x00` or `0x01` |
| length | 4 | big-endian uint32, of the **unescaped** payload, checksum excluded |
| payload | N | byte 0 is the command |
| checksum | 1 | `sum(type, seq, len[0..3], payload) & 0xFF` |
| end | 1 | `0x3C`, never escaped |

Escaping is `0x3D`, applied to `0x3C`, `0x3D` and `0x3E` inside the stuffed span:
the byte becomes `3D` followed by `byte & 0xEF`, and unescaping ORs `0x10` back
in. So `3C → 3D 2C`, `3D → 3D 2D`, `3E → 3D 2E`. Order matters: checksum over the
unescaped bytes, then escape the whole `type|seq|len|payload|cksum` blob, then
wrap it in the markers. Payload `3E 3C 3D` encodes to
`3e 0c 00 00 00 00 03 3d 2e 3d 2c 3d 2d c6 3c`.

The pleasant consequence is that `0x3C` cannot occur inside a frame, so "scan to
the next `0x3C`" is a *correct* framer, not a heuristic. Which is just as well,
because one `recv()` is not one frame: they arrive glued together and split in
half, and both were seen on this headset.

**The ACK carries `1 - seq`, never `seq`.** This is the one rule that is easy to
get wrong and fatal to get wrong, and both reference implementations say the
same thing:

```
device sent seq=0  ->  we send  3e 01 01 00 00 00 00 02 3c
device sent seq=1  ->  we send  3e 01 00 00 00 00 00 01 3c
```

Every received `0x0C`/`0x0E` frame is ACKed, unsolicited notifications included,
and ACKed first thing, before it is acted on. ACKs are never themselves ACKed.
Our own outgoing sequence number is whatever the last received ACK carried, and
only one command may be outstanding at a time: send, wait for the ACK, send the
next.

### The handshake, and what this headset answered

The first frame on the socket is `CONNECT_GET_PROTOCOL_INFO`, payload `00 00`:

```
we send    3e 0c 00 00 00 00 02 00 00 0e 3c
we get     ACK
then       payload  01 00 03 00 10 02 00 00
```

The reply's command is `0x01`, `CONNECT_RET_PROTOCOL_INFO`, and **its length is
the protocol generation**: 4 bytes is v1, 8 bytes is v2. Eight, so v2, which is
what the UUID already implied and is worth confirming anyway. Gadgetbridge sends
this up to three times because headsets sometimes ignore the first one; the
bridge does the same.

### Asking for the listening mode

The NC/ASM block of the v2 command table:

```
0x66 NCASM_GET_PARAM   0x67 NCASM_RET_PARAM   0x68 NCASM_SET_PARAM   0x69 NCASM_NTFY_PARAM
```

Payload byte 1 is the **inquired type**, which selects *which variant* of the
control this model implements and therefore how many bytes follow and what they
mean. It is not derivable from the model name, and the two open implementations
disagree about this one: Gadgetbridge's WH-CH720N profile sends `0x15`, which
its own bug tracker records as not working, while mos9527's client derives the
type from the headset's capability list and only implements `0x17`, `0x19`,
`0x22` and `0x30`.

So ask the headset. A GET is two bytes and costs nothing:

```
3e 0c 00 00 00 00 02 66 17 8b 3c     66 17  ->  answered, RET 67 17 …, 7 bytes
3e 0c 00 00 00 00 02 66 15 89 3c     66 15  ->  ACKed, then nothing, ever
3e 0c 00 00 00 00 02 66 22 96 3c     66 22  ->  ACKed, then nothing, ever
```

**`0x17` it is** — `MODE_NC_ASM_DUAL_NC_MODE_SWITCH_AND_ASM_SEAMLESS`, which is
exactly what the headset offers: three states and a 20-step ambient dial. Note
what a wrong guess looks like: not an error, not a refusal, just an ACK and
silence. That is why the bridge gives each candidate a deadline rather than
waiting for a "no" that never comes.

### The 7-byte block

```
idx: 0    1     2                  3                 4          5                 6
     cmd  0x17  valueChangeStatus  ncAsmTotalEffect  ncAsmMode  ambientSoundMode  level
```

| field | values |
|---|---|
| `valueChangeStatus` | `0x00` under changing — a slider being dragged — `0x01` changed. A SET sends `0x01`. |
| `ncAsmTotalEffect` | the master switch: `0x00` off, `0x01` on |
| `ncAsmMode` | which of the two when on: `0x00` noise cancelling, `0x01` ambient |
| `ambientSoundMode` | `0x00` normal, `0x01` Focus on Voice |
| `level` | ambient sound level, `0x00`-`0x14`, i.e. 0-20 |

So the three states are `effect 0` (off), `effect 1 / mode 0` (noise cancelling)
and `effect 1 / mode 1` (ambient). The last two bytes are carried in every frame
whatever the state, and both directions echo whatever is stored.

The other two layouts, for reference: `0x15` inserts an `ncValue` byte at index 5
and is 8 bytes; `0x22` is ambient-only and drops `ncAsmMode`, 6 bytes. In all
three the focus flag and the level are the last two bytes, which is why a decoder
that reads them off the tail copes with all of them.

### What the headset actually said

Captured on the WH-CH720N, payloads exactly as they went out and came back:

```
->  66 17                       GET
<-  67 17 01 01 00 00 14        RET: changed, on, noise cancelling, normal, level 20

->  68 17 01 01 01 00 0a        SET: ambient, focus off, level 10
<-  ACK
->  66 17                       GET, immediately after
<-  67 17 01 01 00 00 14        …the OLD state, unchanged
<-  69 17 01 01 01 00 0a        NTFY, ~0.3 s later: the new state
```

Two behaviours follow from that, and both are load-bearing:

- **A readback after a SET is stale; the notification is the truth.** The SET is
  ACKed in milliseconds, the headset applies it about a third of a second later,
  and a GET in between answers with the old state in perfect good faith. So
  nothing reads back after a set — `sony-bridge` reports state only from a RET
  or an NTFY, and a click in the panel lands on screen when the headset says it
  has landed. Which is the same behaviour as pressing the button on the headset,
  by construction rather than by effort.
- **The level is applied only by an ambient SET.** Sending `68 17 01 01 00 00 05`
  — noise cancelling, level 5 — leaves the stored level alone, and the headset
  echoes back the level it already had. That is why `setAmbientLevel` puts the
  headset into ambient as part of setting the level: there is no other way to
  store it.

Fully encoded, the two frames above, with the sequence numbers they happened to
carry:

```
SET ambient level 10   3e 0c 01 00 00 00 07 68 17 01 01 01 00 0a a0 3c
NTFY that followed     3e 0c 00 00 00 00 07 69 17 01 01 01 00 0a a0 3c
                       and we must reply    3e 01 01 00 00 00 00 02 3c
```

### In the widget

[`sony-bridge`](sony-bridge) is this protocol as a long-lived process, and the
sibling of [`jbl-bridge`](jbl-bridge): it registers the profile, holds the one
channel, prints a JSON line whenever the state changes and takes commands on
stdin — `set off`, `set anc`, `set ambient`, `level <0-20>`, `voice on|off`. The
plugin's service spawns it while a Sony headset is connected and picks the
backend from the SDP UUID rather than from a probe or a name. Both bridges write
the same line shape, so the rest of the widget does not know which one is
running:

```json
{"modes": true, "mode": "ambient", "available": ["off","anc","ambient"], "level": 10, "voice": false}
```

`available` is what the answering inquired type can do — `0x17` and `0x15` give
Off/ANC/Ambient, `0x22` gives Off/Ambient — and it is what the panel draws
buttons and keys for. There is no TalkThru on this protocol at all. `level` and
`voice` are the Ambient half of the same line, and the panel draws them under
the buttons as a slider and a switch while Ambient is the mode; a line that
reports a level at all is how the widget knows this device has them, since the
JBL bridge never sends one.

What the exit code means, the same four the JBL bridge uses:

- **1, transient** — the profile never connected after ten tries, the handshake
  went unanswered, or the channel closed under the bridge. Says nothing about
  the headset, so the service retries after 10 seconds, then 20, then 40, up to
  five minutes.
- **3, linked but silent** — the handshake worked and every candidate inquired
  type was asked and none answered in its three seconds. This headset speaks the
  protocol but not this part of it, so the address is parked for the session and
  no reason is shown: it is an answer, not a fault.
- **4, setup failure** — bad arguments, or python-dbus/PyGObject missing. About
  this machine and not about the headset; the address is parked for the session
  and the panel says why, where the row would have been.
- **0** is a clean stop — SIGTERM, or the widget closed the pipe — and means
  nothing at all.

Nothing is written to disk on this path, unlike the JBL one. The UUID makes the
next session's decision for free, and a headset that gains the feature in a
firmware update should not have to argue with a cache.

### The probe

[`tools/sony_probe.py`](tools/sony_probe.py) is the reference for all of the
above and the thing every frame here was read off:

```bash
tools/sony_probe.py B0:11:22:33:44:55                  # 25 seconds of everything it says
tools/sony_probe.py B0:11:22:33:44:55 40               # for longer
tools/sony_probe.py B0:11:22:33:44:55 25 set:ambient:10:0   # …and set one mode on the way
```

It registers the profile, waits for BlueZ to connect it, sends the handshake,
ACKs everything, asks `NCASM_GET_PARAM` with each candidate type in turn and
prints every frame in both directions with a timestamp. The reply that echoes
the type you asked for, and its payload length, is the whole answer: that is
what a bridge for that headset must speak. The optional `set:` writes one mode
afterwards using the layout the headset answered with, which is how the
stale-readback and stored-level behaviours above were pinned down.

The widget's own bridge holds the same profile, so turn `useModeControl` off
before running the probe, or BlueZ will refuse the registration to whichever
asks second.

### WH-1000XM5

Confirmed on a **Sony WH-1000XM5** (`AC:80:0A:14:69:53`, modalias
`usb:v054Cp0DF0d0251`). It serves the same MDR v2 UUID (`956c7b26-…`) and the
Fast Pair Message Stream (`df21fe2c-…`). Battery is one figure for the set.
The inquired type and the 7-byte layout are the CH720N's; these are the bytes
it sent.

Handshake, `CONNECT_RET_PROTOCOL_INFO`, 8 bytes so v2:

```
01 00 03 00 20 16 00 00
```

The CH720N's reply was `01 00 03 00 10 02 00 00` — same length, different
capability bytes, same generation.

```
->  66 17                       GET
<-  67 17 01 01 01 00 14        RET: changed, on, ambient, normal, level 20
->  66 15                       GET
<-  ACK, then nothing
->  66 22                       GET
<-  ACK, then nothing
```

SETs built on that `0x17` block were applied: Off, ANC and Ambient each
landed. No other inquired type was answered, and nothing else was sent.

### WH-1000XM4

Confirmed on a **Sony WH-1000XM4** (`94:DB:56:D0:F0:F0`, modalias
`usb:v054Cp0D58d0301`). It serves the MDR v1 UUID (`96cc203e-…`) and the
Fast Pair Message Stream (`df21fe2c-…`). Battery is one figure for the set.
The protocol is v1, not v2 — the handshake answers with 4 bytes, and the NC/ASM
command bytes (`0x66`–`0x69`) are the same but the inquired types and payload
layout differ.

Handshake, `CONNECT_RET_PROTOCOL_INFO`, 4 bytes so v1:

```
01 00 70 00
```

The answering payload is the v1 `NcAsmParam` struct — 7 bytes after the command
byte:

```
idx: 0    1     2             3       4        5       6       7
     cmd  type ncAsmEffect   ncType  ncValue  asmType asmId   asmValue
```

| field | values |
|---|---|
| `ncAsmEffect` | `0x00` off, `0x01` on |
| `ncType` | `0x02` (`DUAL_SINGLE_OFF`) — the v1 enum; the headset always reports this |
| `ncValue` | `0x00` off, `0x01` SINGLE (ambient), `0x02` DUAL (noise cancelling) |
| `asmType` | `0x01` — the only value seen; the bridge writes back what it read |
| `asmId` | `0x00` normal, `0x01` voice |
| `asmValue` | ambient level, `0x00`-`0x14` (0-20) |

What the headset actually said:

```
->  66 02                       GET NC+ASM
<-  67 02 01 02 02 01 00 00     RET: on, DUAL_SINGLE_OFF, nc=NC, asm normal, level 0
```

The SET (`0x68`) is that block written back, with `ncAsmEffect` and `ncValue`
carrying the mode and everything else echoed as the headset reported it:

```
->  68 02 00 02 00 01 00 00     SET off
->  68 02 01 02 02 01 00 00     SET ANC
->  68 02 01 02 01 01 00 00     SET ambient
```

Off / ANC / Ambient each set and were confirmed on the headset; the NTFY
(`0x69`) follows a SET with the new state. The ambient level and Focus on Voice
are in the payload and the headset ACKs them in the SET, but the reply carries
the pre-existing stored values — the headset stores them but does not apply them
from the bridge's writes, the same way the v2 protocol stores the level and only
applies it on an ambient SET.

Sony's v1 table also numbers an NC-only `0x01` and an ambient-only `0x03`. Both
were asked on this headset and neither was answered, so neither is in the
bridge: their block lengths are unconfirmed, and a variant nobody has seen
answered would be a guess sent to somebody's working headphones.

What the bridge does with all this: `sonyUuidFor()` in `Model.js` picks which of
the two UUIDs to hand it, and the bridge registers that one — that is all the
UUID decides. The handshake's length **orders** the questions, `0x02` first on a
4-byte reply and `0x17` first on an 8-byte one, and never shortens the list: a
headset that replies short is still asked `0x17`, `0x15` and `0x22` before it is
given up on, because two models answer `0x17` today and neither may be lost to a
guess about a third. What settles the layout is the type that answers — the
numbers do not collide across the two generations, so a `0x02` block is read as
v1 and a `0x17` block as v2, whatever the UUID and the handshake suggested. Once
a type has answered, a block of any other type is dropped.

`tests/sony_bridge_test.py` pins one session per model — this one, the CH720N
and the WH-1000XM5 — frame for frame.

## WH-1000XM6: NCASM 0x19 notifications and wear status

The WH-1000XM6 answers the regular NCASM query on type `0x17`, but reports
subsequent mode changes with an unsolicited `0x19` notification. Its effect
and ambient-mode bytes occupy the same positions as `0x17`; the wider block
adds trailing bytes. The bridge therefore never probes `0x19`, but accepts and
decodes it when the headset volunteers it.

The wear sensor uses the SYSTEM status class, independently from NCASM:

```text
f2 10          SYSTEM_GET_STATUS, wearing status
f3 10 00       RET: worn
f5 10 01 01    NTFY: not worn
f5 10 01 00    NTFY: worn
```

The reply and notification have different widths, so the final byte is the
state: `0x00` means worn and any other value means not worn. The bridge asks
once after the protocol handshake, then consumes the headset's unsolicited
notifications. This layout and the automatic media pause/resume path are
confirmed on the Sony WH-1000XM6.

## Xiaomi Buds 5 Pro — Compact GAIA on SPP

A third device and a third protocol, confirmed on **Xiaomi Buds 5 Pro**
(`64:8F:DB:87:06:CB`, Qualcomm QCC-7228). There is no Google Fast Pair UUID, so
per-earbud battery over the Message Stream is not available. BlueZ's HFP figure
is the one the widget already shows. Two GATT Battery Service instances
(`0000180f` / `00002a19`) exist on the device object, but ATT reads fail with
*Not connected* while Classic A2DP is up; the GET on this channel that Moondrop
uses for left/right percent (`0x1A01`) answered `01 00` / `02 00` / `03 ff`
against a live BlueZ reading of ~90%, so those bytes are not a usable
percentage. Listening mode is what this section is about.

`bluetoothctl info` lists, among others:

| UUID | What it is | Answers? |
|---|---|---|
| `00001100-d102-11e1-9b23-00025b00a5a5` | CSR GAIA | advertised; `ConnectProfile` returns *not supported* |
| `00001101-0000-1000-8000-00805f9b34fb` | standard SPP | **Yes - handshake, GET/SET listening mode** |
| `00000837-d103-0004-bf7f-2942153d354b` | vendor SPP (vivo uses this) | connects, no replies |
| `2587db3c-ce70-4fc9-935f-777ab4188fd7` | vendor | *not supported* |
| `df21fe2c-2515-4fdb-8886-f12c4d67927c` | Fast Pair Message Stream | **absent** |

The widget picks this backend from the CSR GAIA UUID in the SDP record, then
opens **SPP**. Same Profile1 arrangement as Sony: `Role` `client`, `Channel` `0`,
async `ConnectProfile`, retry on `br-connection-busy`. `AutoConnect` must stay
false: with it on, BlueZ handed a second socket and the probe replayed its plan
on top of itself.

Do not send Xiaomi `FE DC BA …` frames on this socket: they closed it. Do not
send GAIA v1 factory-reset / power-off (`0x0104`, `0x0202`, `0x0204`).

### Frames

Compact GAIA, the same wrapping Moondrop and vivo use:

```
FF <ver> <flags=00> <payloadLen> <vendor u16be> <cmd u16be> <payload>
```

This device replies with **version 3**. Flags stayed 0 (no checksum, no
extended length). Several frames can arrive in one `read()`.

Handshake, vendor `0x000A` (generic GAIA):

```
->  ff 03 00 00  000a 0300
<-  ff 03 00 04  000a 8300  00030301
```

Device commands use vendor `0x001D` (QTIL GAIA v3 / the same vendor Moondrop
uses). GET response = GET + `0x0100`. Error = that value with `0x0080` set,
payload a GAIA status (`05` invalid parameter, `01` not supported).

### Listening mode

| sent | reply | meaning |
|---|---|---|
| `0x1003` empty | `0x1103` 5 bytes | GET |
| `0x1004` 1 byte | `0x1104` empty | SET ack |
| `0x1004` 5 bytes (a copy of GET) | `0x1184` payload `05` | rejected |

GET payloads actually seen, first byte echoing the SET byte:

| SET | GET payload | panel name |
|---|---|---|
| `00` | `00 01 00 00 00` | Off (confirmed: panel Off) |
| `01` | `01 01 01 00 00` | ANC (confirmed: panel ANC; byte 2 is 1 only here) |
| `02` | `02 01 00 01 00` | Ambient / transparency (same extra flags as 0x03/0x04; SET did not drop the link) |
| `03` | `03 01 00 01 00` | accepted, not offered |
| `04` | `04 01 00 01 00` | **reboots the buds** - Moondrop's transparency byte on this vendor; never send |

Off and ANC were confirmed by using the panel. Ambient was first mapped to
`0x04` because that is Moondrop's SET value; the buds reboot when it is sent,
so Ambient is `0x02` instead. `0x03` is still unnamed. Nothing unsolicited
arrived when the GET was left alone; the bridge polls GET every 2.5 s so a
press on the bud still updates the panel.

### In the widget

[`xiaomi-bridge`](xiaomi-bridge) is the sibling of [`sony-bridge`](sony-bridge):
same JSON line, same stdin `set <mode>`, same four exit codes, Classic address,
address parked for the session on exit 3. No `level` / `voice` keys - this
protocol has no ambient dial.

```json
{"modes": true, "mode": "anc", "available": ["off","anc","ambient"]}
```

### The probe

[`tools/xiaomi_probe.py`](tools/xiaomi_probe.py):

```bash
tools/xiaomi_probe.py 64:8F:DB:87:06:CB
tools/xiaomi_probe.py 64:8F:DB:87:06:CB 15 set:ambient
```

Turn `useModeControl` off first: SPP is one holder, like Sony's UUID.


## Nothing NT Link — the Nothing X protocol on RFCOMM channel 15

A fourth channel, and the first one read from other people's work rather than
off a headset on this desk. What follows is what three clients agree on —
[r-witz/omarchy-nothing-ear](https://github.com/r-witz/omarchy-nothing-ear)
(Nothing Ear and Headphone (1), the bridge's battery and latency handling is
theirs), [DaanHessen/earctl](https://github.com/DaanHessen/earctl) (the command
table, many models), and the Ear (a) trace that came with
[pull request #2](https://github.com/ncr/omarchy-headphones/pull/2) by
[@Jenesaispas69](https://github.com/Jenesaispas69), who ran it on the
hardware (the SDP UUID, the frame layout confirmed on the wire, the gallery
screenshot). Where the three differ, both readings are handled below.

```
aeac4a03-dff5-498f-843a-34487cf133eb   NT Link   <- Ear (a); the Ear (2), Ear, Ear (stick) and
                                                    Headphone (1) speak the same protocol
```

**Opening it.** The channel number is fixed at 15, so there is no SDP lookup to
ask BlueZ for: the bridge opens an `AF_BLUETOOTH` / `BTPROTO_RFCOMM` socket
straight to `(address, 15)`. The first connect after the device pairs or
reconnects is often refused; a retry a second and a half later is not. The
Ear (a) trace went through `org.bluez.Profile1` with the UUID and `Channel: 15`
instead and landed on the same socket.

**Activation.** Nothing X asks for device info (`06`) first, and r-witz found
that a fresh session may ignore what follows until it has been asked. The bridge
sends it first and waits up to a second and a half for the answer before the real
queries go out; the answer itself is not used.

### Frames

```
55 60 01 <cmd u16 LE> <len u16 LE> <op u8> <payload…> <crc u16 LE>
^^ ^^^^^
|  ctrl 0x0160: bit 0x20 says a CRC follows the payload
SOF
```

| field | size | meaning |
|---|---|---|
| SOF | 1 | `55` |
| ctrl | 2 | `0160` LE. Bit `0x20` — set on everything seen — means a CRC is appended |
| cmd | 2 | LE. Low byte the command, high byte the direction: `C0` get, `F0` set, `40` answer, `70` ack, `E0` unsolicited |
| len | 2 | payload length, LE (the Ear (a) trace read it as `<len u8> 00`, which is the same bytes) |
| op | 1 | an operation id, echoed in the answer; the bridge always sends 1 |
| payload | len | command-specific |
| crc | 2 | CRC-16/MODBUS (init `FFFF`, poly `A001`, check value `4B37`) over every byte before it, LE |

So `55 60 01 1E C0 00 00 01 B1 1D` asks for the noise-control state.

### Commands

| command | get | answer | set | notes |
|---|---|---|---|---|
| device info | `C0 06` | `40 06` | — | asked first, see Activation |
| battery | `C0 07` | `40 07`, and `E0 01` unsolicited | — | |
| noise control | `C0 1E` | `40 1E`, and `E0 03` unsolicited | `F0 0F` | |
| low latency | `C0 41` | `40 41` | `F0 40` | absent on models without it: the get goes unanswered |
| codec flag | `C0 29` | `40 29` | — | the device's own idea of its codec mode; read-only, see below |

**Battery** answers with a count byte and then `<component> <level>` pairs.
Bit 7 of the level is charging, the low seven bits the percentage:

| component | |
|---|---|
| `02` | left earbud |
| `03` | right earbud |
| `04` | case — present only while the case is open |
| `06` | the one battery of a Headphone (1) |

`03 02 55 03 0F 04 55` is left 85%, right 15%, case 85%, nothing charging.

**Noise control** answers with `01 <mode> 00`; the set payload is the same
three bytes. The mode byte:

| value | Nothing X calls it | the widget calls it |
|---|---|---|
| `01` | Noise Cancelling, High | `anc`, level `high` |
| `02` | Noise Cancelling, Mid | `anc`, level `mid` |
| `03` | Noise Cancelling, Low | `anc`, level `low` |
| `04` | Noise Cancelling, Adaptive | `anc`, level `adaptive` |
| `05` | Off | `off` |
| `07` | Transparency | `ambient` |

r-witz's client reads the payload as `(kind, value, 0)` triplets, with kind `1`
carrying the mode and an optional kind `2` carrying a strength `1`–`4` on its
own; earctl and the Ear (a) trace read the mode byte alone. The bridge reads
`payload[1]` as the mode and lets a `02 <level>` triplet, where one follows,
override the strength — so either firmware is read the same way.

A set is answered with an ack (`70 0F`), not with the new state; the Ear (a)
trace saw the `E0 03` announcement follow it. The bridge asks again half a
second after every set rather than trusting either. Touch controls on the
earbuds are not reliably announced on this channel, so the mode is polled every
three seconds and the battery every fifth poll.

**Low latency**: the answer's first byte is `01` for on; the set payload is
`01` for on and `02` for off.

**The codec flag** (`29`) is the device's own codec mode — `00` standard, `01`
LHDC, `02` LDAC. r-witz reports it and deliberately never writes it: the
firmware acknowledges a value without applying it, and the codec actually used
is whatever the host negotiated. The widget leaves it alone.

### In the widget

[`nothing-bridge`](nothing-bridge) holds the socket and writes the same lines
the other bridges do, in the panel's vocabulary — Transparency is `ambient`,
the four strengths are `anc` with an `ancLevel`:

```json
{"modes": true, "mode": "anc", "available": ["off","anc","ambient"],
 "ancLevel": "high", "ancLevels": ["low","mid","high","adaptive"],
 "latency": false,
 "battery": {"left": 85, "right": 15, "case": 85, "charging": [], "caseStale": false}}
```

Commands on stdin: `set off|anc|ambient`, `level low|mid|high|adaptive`,
`latency on|off`. `set anc` asks for the strength last seen (Adaptive when none
has been), because the device stores the strength with the mode and has no
plain "on".

The battery is a fallback: the Fast Pair stream, where the device serves one,
announces a change the moment it happens and wins while it is up. The case only
reports while open, so the bridge keeps its last reading — on disk, six hours —
and sends it as `caseStale`, which the panel dims.

Exit codes match the other bridges: 0 clean, 1 transient (the socket refused or
closed), 3 silent (open, but the noise-control query went unanswered), 4 setup.

### The probe

[`tools/nothing_probe.py`](tools/nothing_probe.py) — opens the socket, sends
the four gets, prints every frame in both directions decoded, and optionally
writes one setting afterwards:

```bash
tools/nothing_probe.py 3C:B0:ED:AF:7C:30
tools/nothing_probe.py 3C:B0:ED:AF:7C:30 set-anc high
tools/nothing_probe.py 3C:B0:ED:AF:7C:30 set-latency on
```

The widget's bridge holds the same channel, so turn `useModeControl` off, or
disconnect and reconnect the earbuds with the panel closed, before running it —
a second RFCOMM client on channel 15 is refused while the first is up.


## Soundcore Space 2 — vendor RFCOMM

Notes from probing a **Soundcore Space 2** (`84:9D:4B:B0:2D:00`, modalias
`bluetooth:v02B0p0000d001F`).

Like Sony and Xiaomi, its listening mode is over an RFCOMM channel. Soundcore devices
advertise a vendor UUID starting with `0cf12d31-fac3-4553-bd80-d6832e7...`
(`0cf12d31-fac3-4553-bd80-d6832e7d1402` on the Space 2, where `d1402` is the model ID).
Connecting an `org.bluez.Profile1` to this UUID opens the RFCOMM control link.

### Framing

```
outbound:  08 ee 00 00 00 <cmd u8, u8> <len u16le> <payload> <checksum u8>
inbound:   09 ff 00 00 01 <cmd u8, u8> <len u16le> <payload> <checksum u8>
```

- `<len u16le>` is the little-endian total byte length of the packet (including header, command, length, payload, and checksum).
- `<checksum u8>` is the simple 8-bit sum (`sum(packet[:-1]) & 0xFF`).

### Commands

| Command | Direction | Meaning |
|---|---|---|
| `01 01` | Outbound | `RequestState`: ask for full initial state |
| `01 01` | Inbound | `StateUpdate`: 103-byte payload (113-byte packet), sound modes at offset 71..77 |
| `06 81` | Outbound | `SetSoundModes`: 6-byte payload `[mode, custom_anc, transparency_mode, nc_mode, wind_noise, custom_transparency]` |
| `06 81` | Inbound | ACK from headphones |
| `06 01` | Inbound | `SoundModes` notification when mode changes |

### Sound mode byte

- `0x00` — ANC
- `0x01` — Ambient
- `0x02` — Off (Normal)

A mode change is confirmed on the headphones immediately and answered with both an ACK (`06 81`) and an unsolicited notification (`06 01`).

### The probe

[`tools/soundcore_probe.py`](tools/soundcore_probe.py):

```bash
tools/soundcore_probe.py 84:9D:4B:B0:2D:00
tools/soundcore_probe.py 84:9D:4B:B0:2D:00 5 set:ambient
```



### Space One Pro (A3062) — the same protocol, six bytes further left

Notes from a **soundcore Space One Pro** (`7C:E9:13:2C:2B:6D`, firmware
`0.4.3.9`). Same vendor channel as the Space 2, same framing, same commands.
One thing differs, and it is enough to break both reading and writing.

#### The block moves

`0cf12d31-fac3-4553-bd80-d6832e7b3062`, model ID `b3062` in the usual place, and
`01 01` answers with a 95-byte state. The six sound mode bytes are **at offset
69, not 71**:

```
... 04 04 0f 03 02 05 31 01 31 01 31 01 00 00 01 ...
          ^^ ^^ ^^^^^^^^^^^^^^^^^ the block, at 69
          |  ambient sound mode cycle
          press twice
```

Two bytes to the left of where the Space 2 keeps it. Which field accounts for
the difference I have not established — there is no Space 2 here to compare
against — but 69 is not a guess about this one headset. It falls out of
[OpenSCQ30](https://github.com/Oppzippy/OpenSCQ30)'s A3062 parser, which reads
the packet field by field, and every field ahead of the sound modes has a fixed
width:

```
  0..1   battery              23..34  equalizer configuration
  2..6   firmware version     35..36  unknown
  7..22  serial number        37..64  custom hear id, music genre at the end
                              65..66  unknown
                              67      button configuration
                              68      ambient sound mode cycle
                              69      sound modes  <-
```

That layout was derived independently, from a different unit, and it lands on
the same six bytes this one reports. A firmware that moved them would have to
change one of those widths, and would break OpenSCQ30 in the same breath.

Read at 71 the mode comes out as `0x31`, which is no mode at all, and the row
stays on **pending** forever:

```
$ tools/soundcore_probe.py 7C:E9:13:2C:2B:6D 20
<<< STATE: mode=unknown(49) params=310131013101
```

The quieter half of the same bug is the write. `set` takes
`sound_mode_params`, replaces byte 0 and sends the rest back — so with the
offset wrong it posts five of the device's neighbouring settings as if they were
the mode parameters. On this headset that overwrote the custom noise cancelling
and custom transparency levels with `31 01 31 01`, which is not a value anyone
chose.

#### Ask 06 01 and no offset is needed

`06 01` answers with the six bytes and nothing around them — on this model;
whether the Space 2 answers a request is untested, it has only been seen to emit
one unprompted:

```
>>> 08 ee 00 00 00 06 01 0a 00 07
<<< 08 ee 00 00 00 06 01 10 00 02 50 01 01 00 05 ...
                              ^^^^^^^^^^^^^^^^^ exactly body[69:75] above
```

`on_packet` already reads that reply correctly. It was simply never asked for —
the handshake sends `01 01` and waits. Asking as well costs one 10-byte frame at
connect and cannot drift as firmware moves fields about.

Worth saying why the offset is not simply checked instead. The obvious guard is
to take the byte at 71 only when it looks like a mode and ask `06 01` otherwise,
and it does not work: the neighbours are switches, so the byte at 71 reads as a
perfectly plausible `0`, `1` or `2` most of the time. On this headset with the
mode on Ambient it is `01`, and a guard like that reports Ambient for the wrong
reason and then writes the wrong five bytes back, exactly as before. Tried, and
it took a second round of overwritten levels to notice.

So the query goes out after the state packet, and its reply stands over
whatever the offset produced. Which models are asked is a row in `MODELS` at the
top of `soundcore-bridge`: the Space One Pro, and any model the bridge has not
seen. The Space 2's row says not to — its owner has not confirmed a request is
answered, and a headset that works is not sent a frame it has never been seen
to take. `tests/soundcore_bridge_test.py` pins each row's frames, so the next
model cannot change what an earlier one is sent without failing there.

#### And ask again after a set

The Space 2 answers a set with an ACK **and** an unsolicited `06 01`, which is
what carries the row along. The Space One Pro sends the ACK alone. The write
lands — reading back over the vendor channel confirms it, tail intact:

```
$ omarchy-shell omaphones setMode anc
ok
<<< 06 01 body=00 50 01 01 00 05        mode 0, and the five neighbours untouched
```

— but nothing arrives to say so, so the panel goes on showing the mode the
headphones were in a moment ago. One `06 01` after each write settles it.

#### A caution about the vendor channel going missing

Worth writing down because it cost an afternoon. After several hours connected,
and an auto power off in the middle, `ConnectProfile` began refusing the vendor
UUID outright:

```
09:38:40.594 ConnectProfile: br-connection-not-supported
...eleven times, once per retry...
```

[OpenSCQ30](https://github.com/Oppzippy/OpenSCQ30) v2.11.0 failed identically at
the same call, and a scan of RFCOMM channels 1-30 found only HFP, the Message
Stream, and two channels that accept a socket and answer nothing. It reads
exactly like a device that does not serve the channel.

**It is transient.** Power cycling the headphones brought it straight back, and
it has been reliable since. `EXIT_TRANSIENT` and the growing backoff are the
right answer; anything that parks the address on that error would leave the row
disabled until the shell restarts, at the very moment a power cycle would have
fixed it.

In that state the control protocol is also reachable over BLE GATT, on the
rotating Fast Pair address — service `0179f5da-0000-1000-8000-00805f9b34fb`,
write handle `0x001a`, notify handle `0x0016`, requests keeping the `08 ee`
header and replies using `09 ff 00 00 01`. `06 01` works there too and returns
the same six bytes; `06 81` is acknowledged and reads back changed. Recorded in
case it is ever the only way in, though on a healthy device the vendor channel
is simpler and this plugin needs nothing from it. Two notes for anyone who
tries: the address rotates and arrives unprompted as `0b 02` on the same notify
handle, and BlueZ drops the LE link the moment no client holds it.
