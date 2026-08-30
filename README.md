# Omaphones for Omarchy

<p align="center"><b>JBL</b> &nbsp;·&nbsp; <b>Sony</b> &nbsp;·&nbsp; <b>Nothing</b> &nbsp;·&nbsp; <b>Soundcore</b> &nbsp;·&nbsp; <b>Xiaomi</b></p>

<p align="center"><b>Battery levels and noise-cancellation control for Bluetooth headphones, in the Omarchy bar.</b></p>

**Install** — copy into a terminal and run:

```bash
omarchy plugin add https://github.com/ncr/omarchy-headphones --enable
```

**Update** an installed copy:

```bash
omarchy plugin update io.github.ncr.omaphones --yes && omarchy restart shell
```

Headphones not on the list? [Add yours](#add-your-own-headphones).

<p align="center"><a href="#what-it-does">What it does</a> · <a href="#supported-headphones">Supported headphones</a> · <a href="#in-the-panel">In the panel</a> · <a href="#settings">Settings</a> · <a href="#gallery">Gallery</a> · <a href="#add-your-own-headphones">Add your headphones</a></p>

## Gallery

<table>
<tr>
<td width="50%"><img src="docs/gallery/jbl-tune230nc-tws.png" alt="JBL TUNE230NC TWS: left, right and case, and noise control" width="100%"></td>
<td width="50%"><img src="docs/gallery/sony-wh-ch720n.png" alt="Sony WH-CH720N: one battery, Off / ANC / Ambient, the ambient level slider and the Focus on voice switch" width="100%"></td>
</tr>
<tr>
<td align="center">JBL TUNE230NC TWS — <a href="https://github.com/ncr">@ncr</a></td>
<td align="center">Sony WH-CH720N — <a href="https://github.com/ncr">@ncr</a></td>
</tr>
<tr>
<td width="50%"><img src="docs/gallery/soundcore-space-2.png" alt="Soundcore Space 2: one battery, Off / ANC / Ambient" width="100%"></td>
<td width="50%"><img src="docs/gallery/nothing-ear-a.png" alt="Nothing Ear (a): left, right and case, and the mode row" width="100%"></td>
</tr>
<tr>
<td align="center">Soundcore Space 2 — <a href="https://github.com/Sovego">@Sovego</a></td>
<td align="center">Nothing Ear (a) — <a href="https://github.com/Jenesaispas69">@Jenesaispas69</a></td>
</tr>
<tr>
<td width="50%"><img src="docs/gallery/sony-wh-1000xm5.png" alt="Sony WH-1000XM5: one battery, Off / ANC / Ambient, the ambient level slider and the Focus on voice switch" width="100%"></td>
<td width="50%"><img src="docs/gallery/soundcore-space-one-pro.png" alt="soundcore Space One Pro: one battery, Off / ANC / Ambient, the ambient level slider and the Wind noise reduction switch" width="100%"></td>
</tr>
<tr>
<td align="center">Sony WH-1000XM5 — <a href="https://github.com/huynguyendinhquang">@huynguyendinhquang</a></td>
<td align="center">soundcore Space One Pro — <a href="https://github.com/sasiruLK">@sasiruLK</a></td>
</tr>
<tr>
<td width="50%"><img src="docs/gallery/sony-wh-1000xm4.png" alt="Sony WH-1000XM4: one battery, Off / ANC / Ambient" width="100%"></td>
<td width="50%"><img src="docs/gallery/sony-wh-1000xm6.png" alt="Sony WH-1000XM6: one battery, Off / ANC / Ambient, wear detection" width="100%"></td>
</tr>
<tr>
<td align="center">Sony WH-1000XM4 — <a href="https://github.com/seth-reee">@seth-reee</a></td>
<td align="center">Sony WH-1000XM6 — <a href="https://github.com/f-iacono">@f-iacono</a></td>
</tr>
</table>

## What it does

- **Battery level** — per earbud and the case, or the single battery of
  over-ear headphones.
- **The bar icon is the meter** — earbuds are drawn as a pair, a headset as
  headphones, filling up as they charge. Readable from the bar without opening
  anything.
- **Noise control** — Off / ANC / Ambient / TalkThru, from the panel or a key.
  JBL, Sony, Nothing, Soundcore and Xiaomi Buds 5 Pro today; built to learn
  your brand. Sony and Soundcore add the ambient level with Focus on Voice or
  wind noise reduction; Nothing the ANC strength (Low / Mid / High / Adaptive)
  and a low-latency switch.
- **Pause when you take them off, resume when you put them back on** — on a
  headset with a wear sensor (confirmed on the Sony WH-1000XM6). Only the
  players the sensor paused are resumed. Any headphones pause what is playing
  when they disconnect.
- **Several headphones at once** — one icon per connected set, each with its own
  panel.
- **Low-battery notification** that names the earbud.
- **Scriptable** — `omarchy-shell omaphones status`, `omarchy-shell omaphones setMode anc`, and so on.

For AirPods use [omapods](https://github.com/thisisgm/omarchy-pods) instead: the
same idea, built for Apple's own protocol, and the plugin this one is modelled on.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/hero-dark.webp">
  <img src="docs/hero-light.webp" alt="The Omarchy bar with two sets connected — one icon each — and the JBL panel open: left, right and case, and noise control; the picture cycles through a few Omarchy themes" width="100%">
</picture>

## Supported headphones

| Device                      | Battery                                                               | Noise control                                                                                   | Confirmed by                   |
|:----------------------------|:----------------------------------------------------------------------|:------------------------------------------------------------------------------------------------|:-------------------------------|
| JBL TUNE230NC TWS (earbuds) | <img src="docs/icons/yes.svg" width="14" alt="yes"> left, right, case | <img src="docs/icons/yes.svg" width="14" alt="yes"> Off · ANC · Ambient · TalkThru              | [@ncr](https://github.com/ncr) |
| Sony WH-CH720N (over-ear)   | <img src="docs/icons/yes.svg" width="14" alt="yes"> one figure        | <img src="docs/icons/yes.svg" width="14" alt="yes"> Off · ANC · Ambient (level, Focus on Voice) | [@ncr](https://github.com/ncr) |
| Sony WH-1000XM5 (over-ear)  | <img src="docs/icons/yes.svg" width="14" alt="yes"> one figure        | <img src="docs/icons/yes.svg" width="14" alt="yes"> Off · ANC · Ambient (level, Focus on Voice) | [@huynguyendinhquang](https://github.com/huynguyendinhquang) |
| Sony WH-1000XM6 (over-ear)  | <img src="docs/icons/yes.svg" width="14" alt="yes"> one figure        | <img src="docs/icons/yes.svg" width="14" alt="yes"> Off · ANC · Ambient (level, Focus on Voice) · wear pause/resume | [@f-iacono](https://github.com/f-iacono) |
| Sony WH-1000XM4 (over-ear)  | <img src="docs/icons/yes.svg" width="14" alt="yes"> one figure        | <img src="docs/icons/yes.svg" width="14" alt="yes"> Off · ANC · Ambient                          | [@seth-reee](https://github.com/seth-reee) |
| Soundcore Space 2 (over-ear)| <img src="docs/icons/yes.svg" width="14" alt="yes"> one figure        | <img src="docs/icons/yes.svg" width="14" alt="yes"> Off · ANC · Ambient (level, wind noise reduction) | [@Sovego](https://github.com/Sovego) |
| Xiaomi Buds 5 Pro (earbuds) | <img src="docs/icons/yes.svg" width="14" alt="yes"> one figure        | <img src="docs/icons/yes.svg" width="14" alt="yes"> Off · ANC · Ambient                          | [@KentoNion](https://github.com/KentoNion)|
| Nothing Ear (a) (earbuds)   | <img src="docs/icons/yes.svg" width="14" alt="yes"> left, right, case | <img src="docs/icons/yes.svg" width="14" alt="yes"> Off · ANC (Low / Mid / High / Adaptive) · Ambient · low latency | [@Jenesaispas69](https://github.com/Jenesaispas69) |
| Nothing Ear · Headphone (1) | <img src="docs/icons/yes.svg" width="14" alt="yes"> expected (one figure on Headphone (1)) | <img src="docs/icons/yes.svg" width="14" alt="yes"> expected — same protocol, per [omarchy-nothing-ear](https://github.com/r-witz/omarchy-nothing-ear) | — |
| soundcore Space One Pro (A3062, over-ear) | <img src="docs/icons/yes.svg" width="14" alt="yes"> one figure | <img src="docs/icons/yes.svg" width="14" alt="yes"> Off · ANC · Ambient (level, wind noise reduction) | [@sasiruLK](https://github.com/sasiruLK) |
| other Fast Pair headphones  | <img src="docs/icons/yes.svg" width="14" alt="yes"> expected          | <img src="docs/icons/unknown.svg" width="14" alt="untested">                                    | —                              |

## Add your own headphones

Paste the text below into your AI coding agent (Claude Code, Codex, OpenCode…).
It adds support for your headphones and opens a pull request here. How the
existing protocols were found is written down in [PROTOCOL.md](PROTOCOL.md).

```text
Add support for my Bluetooth headphones to the Omaphones plugin for Omarchy and
open a pull request against `github.com/ncr/omarchy-headphones` with the result.
0. If it is not installed yet: `omarchy plugin add
   https://github.com/ncr/omarchy-headphones --enable --yes` (`--yes` because you
   have no terminal to confirm in). It lands in
   `~/.config/omarchy/plugins/io.github.ncr.omaphones`.
1. Connect the headphones and check `omarchy-shell omaphones status`. Find out
   what they serve: `bluetoothctl devices` for the address, `bluetoothctl info
   <address>` for the UUIDs — `df21fe2c-2515-4fdb-8886-f12c4d67927c` is the
   Google Fast Pair Message Stream (battery), `956c7b26-d49a-4ba8-b03f-b17d393cb6e2`
   is Sony MDR v2 and `96cc203e-5068-46ad-b32d-e316f5e069ba` Sony MDR v1 (both
   noise control), `aeac4a03-dff5-498f-843a-34487cf133eb` is Nothing NT Link;
   JBL earbuds are probed over BLE by the plugin itself.
2. If battery and the mode row both already work, nothing needs
   writing: the pull request is my device's row in the table in `README.md` —
   device, two ticks, my GitHub handle — plus the screenshot from step 4.
3. Otherwise extend the plugin. Read `PROTOCOL.md` and the docstrings of
   `sony-bridge`, `nothing-bridge` and `jbl-bridge` first — they show how the
   existing channels were found and what the bridge contract is. Find the
   channel the vendor's own app uses (the probes in `tools/`, an open-source
   client for the brand, an HCI snoop), write a `brand-bridge` modelled on
   `sony-bridge` with the same stdout/stdin/exit-code contract, add its UUID to
   `controlBackend()` in `Model.js` and its path to `classicBridgePath` in
   `DeviceFollower.qml`, test it on my headphones with `omarchy restart shell`,
   and add my device to the table, noting what the device answered in
   `PROTOCOL.md`.

   One fact shapes how this plugin is written: nobody has more than their own
   headphones. The maintainer cannot test yours, you cannot test anybody
   else's, and every model in the table works today on frames that only its
   owner can retest. So two rules hold whatever brand this is, and a pull
   request that breaks either will be sent back:

   **A new model may not change what an existing one is sent.** Somebody else's
   headphones work today on frames nobody here can retest. So a
   model gets its own row — `MODELS` in `soundcore-bridge` and in `sony-bridge`, an
   inquired type in `sony-bridge` — and adding it adds a row; it does not edit another one, and
   it does not turn a value that was always sent into one that is now decided.
   Where something must be decided, let it widen rather than narrow: prefer
   asking one more question to asking one fewer.

   **Ship only what you saw the headphones answer — no guessed bytes.** A
   variant from a vendor table that your headset never answered stays out, in
   the code and in `PROTOCOL.md` both.

   Pin it with a test, which is how the two rules survive the next pull request:
   `python -m unittest tests/sony_bridge_test.py` if you touched `sony-bridge`,
   `tests/soundcore_bridge_test.py` for `soundcore-bridge`, `deno test
   --allow-read tests/model.test.js` if you touched `Model.js`. Each bridge test
   scripts one session per model and asserts the exact frames — add your model's
   case, leave the others' bytes alone, and run the lot. A bridge with no test
   file yet is the moment to write one, modelled on those two.

   Mind that any file written inside the plugin directory reloads the plugin at
   once — edit elsewhere and move files in, as the tools in `tools/` do.
4. Take the screenshot: `tools/gallery-shot <which>` — the `gallery-screenshot`
   skill in `.claude/skills/` has the steps — and add it to the Gallery at the
   bottom of `README.md` with the device name and my handle. The screenshot is
   part of the pull request.
5. Commit, push to a fork, and open the pull request.
```

Negative results are welcome too — a row saying what does not work saves the
next person the afternoon.

## In the panel

The icon is the meter:

<table>
<tr>
<td width="96"><img src="docs/mark-legend-earbuds.png" width="80" alt="Earbuds: left bud 40%, right bud 75%"></td>
<td><b>Earbuds</b> — each bud fills with its own level. Here left 40%, right 75%.</td>
</tr>
<tr>
<td width="96"><img src="docs/mark-legend-headset.png" width="80" alt="Headset: whole mark 60%"></td>
<td><b>Headset</b> — one battery, whole mark. Here 60%.</td>
</tr>
<tr>
<td width="96"><img src="docs/mark-legend-low.png" width="80" alt="Low battery: the earbuds in the theme's alert colour, 12% and 8%"></td>
<td><b>Low</b> — under the threshold (20% by default) the icon turns the theme's alert colour and a notification fires. Here 12% and 8%.</td>
</tr>
</table>

Keys, while the panel is open (the panel lists them itself, bottom rows):

<img src="docs/panel-keys.png" width="520" alt="The panel's hint rows: o Off · n ANC · a Ambient · [ ] Level · f Voice — r Refresh · , . Device · b Bluetooth · v Volume · tab Next panel">

| Key | Does |
|:--|:--|
| `o` `n` `a` `t` | Off · ANC · Ambient · TalkThru — only the modes this device has |
| `[` `]` | Ambient level down / up (Sony 0-20, Soundcore 1-5) |
| `f` | Focus on voice (Sony) / wind noise reduction (Soundcore) on / off |
| `1` `2` `3` `4` | ANC strength: Low · Mid · High · Adaptive (Nothing) — turns ANC on at it |
| `g` | Low latency on / off (Nothing) |
| `r` | Ask the device again |
| `,` `.` | Previous / next connected set |
| `b` `v` | Bluetooth panel / Audio panel |
| `tab` `esc` | Next panel / close |

Click an icon to open its panel; with two sets connected, click the one you mean.

Everything is reachable over IPC — `omarchy-shell omaphones <method>`:

| Method | Answers |
|:--|:--|
| `status` | one line per device it follows, e.g. `JBL TUNE230NC TWS · L 90% · R 100% · case 78%` |
| `battery` · `left` · `right` · `batteryCase` | a level 0-100, or `-1` |
| `charging` | which parts say they are charging |
| `mode` · `setMode <m>` | `off` `anc` `ambient` `talkthru`, or `pending` / `unsupported` · `ok` / `busy` / `unavailable` |
| `ambientLevel` · `setAmbientLevel <n>` | 0-20 (Sony), 1-5 (Soundcore) |
| `ambientVoice` · `setAmbientVoice on\|off` | `on` / `off` — Focus on voice (Sony), wind noise reduction (Soundcore) |
| `ancLevel` · `setAncLevel <l>` | `low` `mid` `high` `adaptive` (Nothing); setting one turns ANC on |
| `latency` · `setLatency on\|off` | `on` / `off` (Nothing) |
| `worn` | `worn` / `not worn`, or `unsupported` for a device with no wear sensor |
| `refresh` | ask the device again |
| `open` · `close` · `toggle` | the panel |

With more than one set connected, every method that reads or writes a device
has a `…For <which>` twin that names a device by a piece of its name, address or brand: `modeFor sony`,
`setModeFor anc jbl`, `openFor jbl`.

The table is the useful subset — `Service.qml` answers a few more
introspection calls (`bleAddress`, `panelRect`) for the tools in `tools/`.

What it deliberately does not do — connect, volume, MAC addresses, equalisers —
lives in the stock panels a keypress away (`b`, `v`).

## Settings

`omarchy bar set io.github.ncr.omaphones <key> <value>` (add `--json` for numbers
and booleans), or the widget's entry in `~/.config/omarchy/shell.json`.

| Key                    | Default | Meaning                                                                                                                  |
|:-----------------------|:--------|:-------------------------------------------------------------------------------------------------------------------------|
| `deviceMatch`          | `""`    | Substring of name or address; empty shows every connected audio device, set it to follow only the matching ones.         |
| `useFastPair`          | `true`  | Battery over Fast Pair. Off: BlueZ's single figure, no reader, and no JBL mode row (its BLE address is announced there). |
| `useModeControl`       | `true`  | The mode row (noise control) and the link behind it.                                                                           |
| `lowBatteryThreshold`  | `20`    | Urgent icon and notification from here down (5-50).                                                                      |
| `showPercentage`       | `false` | A written percentage instead of the drawn meter; costs a bar slot.                                                       |
| `hideWhenDisconnected` | `true`  | Drop the widget while nothing is connected.                                                                              |
| `notifyLowBattery`     | `true`  | Send the notification.                                                                                                   |
| `pauseMediaOnDisconnect` | `true` | Pause playing media players when a device disconnects or comes off the ears, and resume the same players when it goes back on. |

## Credits

- [omapods](https://github.com/thisisgm/omarchy-pods) — the idea and the shape.
- [Bluetooth-Battery-Meter](https://github.com/maniacx/Bluetooth-Battery-Meter) — the clearest reading of the Fast Pair battery bytes.
- [bluetooth-py](https://github.com/GroupXyz2/bluetooth-py) — the JBL command numbers.
- [Gadgetbridge](https://codeberg.org/Freeyourgadget/Gadgetbridge) and [mos9527/SonyHeadphonesClient](https://github.com/mos9527/SonyHeadphonesClient) — the Sony frame format; the two disagree about the WH-CH720N, and the hardware settled it here.
- [@f-iacono](https://github.com/f-iacono) — WH-1000XM6 protocol capture and wear-sensor support.
- [r-witz/omarchy-nothing-ear](https://github.com/r-witz/omarchy-nothing-ear) — the Nothing protocol as a working Omarchy widget: battery components, the latency switch and the case cache; [DaanHessen/earctl](https://github.com/DaanHessen/earctl) — the command table; [@Jenesaispas69](https://github.com/Jenesaispas69)'s [PR #2](https://github.com/ncr/omarchy-headphones/pull/2) — the NT Link UUID and the frame layout from an Ear (a).

## Licence

MIT. See [LICENSE](LICENSE).
