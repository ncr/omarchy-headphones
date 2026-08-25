// Pure helpers for the Buds widget: which BlueZ device the widget follows, and
// how its battery level turns into text and glyphs. Kept out of Panel.qml so
// the picking rules can be read (and reasoned about) on their own.

var LEVEL_GLYPHS = [
  "\u{f007a}", "\u{f007b}", "\u{f007c}", "\u{f007d}", "\u{f007e}",
  "\u{f007f}", "\u{f0080}", "\u{f0081}", "\u{f0082}", "\u{f0079}"
]

var CHARGING_GLYPHS = [
  "\u{f089c}", "\u{f0086}", "\u{f0087}", "\u{f0088}", "\u{f089d}",
  "\u{f0089}", "\u{f089e}", "\u{f008a}", "\u{f008b}", "\u{f0085}"
]

var HEADPHONES_GLYPH = "\u{f02cb}"

// battery-unknown, a battery with a question mark. Not battery-alert, which is a
// battery with an exclamation mark and says "act on this"; a component that has
// stopped reporting is unknown, not urgent. Not the empty outline either, which
// would claim a level of zero.
var UNKNOWN_GLYPH = "\u{f0091}"

function str(value) {
  return String(value === undefined || value === null ? "" : value)
}

// `omarchy bar set <id> <key> <value>` writes a JSON string unless it is given
// --json, so a widget setting can arrive as "false" or "20" rather than as false
// or 20. A non-empty string is truthy in QML, which would silently invert a
// boolean setting; coerce instead of trusting the type.
function asBool(value, fallback) {
  if (value === undefined || value === null || value === "") return fallback
  if (typeof value === "boolean") return value
  if (typeof value === "number") return value !== 0
  var text = str(value).trim().toLowerCase()
  if (text === "false" || text === "0" || text === "no" || text === "off") return false
  if (text === "true" || text === "1" || text === "yes" || text === "on") return true
  return fallback
}

// Same string-shaped settings as asBool, so a value padded with spaces by hand
// must not read as 0: Number(" ") is 0, which would silently mean "never warn".
function asInt(value, fallback) {
  if (value === undefined || value === null) return fallback
  if (typeof value === "number") return isFinite(value) ? Math.round(value) : fallback
  var text = str(value).trim()
  if (text === "") return fallback
  var number = Number(text)
  return isFinite(number) ? Math.round(number) : fallback
}

// Qt Text defaults to AutoText, which renders anything tag-shaped as rich
// text — and a device names itself, so a crafted name could smuggle <img>
// markup into the panel title, the tooltip or a notification and make the
// shell load a resource of the attacker's choosing. Every string a device
// authored passes through here on its way to a Text; the angle brackets are
// swapped for lookalikes so the string can never read as markup.
function plainText(value) {
  return str(value).replace(/</g, "\u2039").replace(/>/g, "\u203a")
}

// device.name is the writable BlueZ Alias and device.deviceName the read-only
// name the device reports; the user-set alias is preferred deliberately, so
// renaming the buds in the Bluetooth panel renames them in the bar too.
function deviceLabel(device) {
  if (!device) return ""
  var name = plainText(device.name).trim()
  if (name) return name
  var reported = plainText(device.deviceName).trim()
  if (reported) return reported
  return str(device.address)
}

// BlueZ sets Icon from the device class. Earbuds and headsets land on
// audio-headset / audio-headphones; the name check catches the ones that
// arrive with a bare audio-card or no icon at all.
function isAudioDevice(device) {
  if (!device) return false
  if (str(device.icon).toLowerCase().indexOf("audio") !== -1) return true
  var name = deviceLabel(device).toLowerCase()
  return name.indexOf("buds") !== -1
    || name.indexOf("headphone") !== -1
    || name.indexOf("headset") !== -1
    || name.indexOf("airpod") !== -1
}

function matchesFilter(device, filter) {
  var needle = str(filter).trim().toLowerCase()
  if (!needle) return isAudioDevice(device)
  var haystack = (deviceLabel(device) + " " + str(device.address)).toLowerCase()
  return haystack.indexOf(needle) !== -1
}

// Connected beats everything, then a reported battery, then being audio at all.
// `preferAddress` is the set that was connected last and only breaks ties, so a
// device that is connected now always outranks the one you used before. A
// paired-but-disconnected match still beats nothing, so the popup can name the
// earbuds it is waiting for.
function score(device, preferAddress) {
  var points = 0
  if (device.connected) points += 16
  if (device.batteryAvailable) points += 4
  if (isAudioDevice(device)) points += 2
  if (preferAddress && str(device.address).toUpperCase() === str(preferAddress).toUpperCase())
    points += 1
  return points
}

// Every device the widget would consider, best first. The order is the one the
// bar draws its icons in and the one the panel walks with , and . — score
// decides it, and two devices on the same score are ordered by name so the
// icons keep their places between one reading and the next. The list index is
// the last tie-break, because a sort that is not total moves icons about for no
// reason a person can see.
function rankDevices(devices, filter, preferAddress) {
  var list = devices || []
  var rows = []
  for (var i = 0; i < list.length; i++) {
    var device = list[i]
    if (!device) continue
    if (!device.paired && !device.connected) continue
    if (!matchesFilter(device, filter)) continue
    rows.push({
      device: device,
      points: score(device, preferAddress),
      label: deviceLabel(device).toLowerCase(),
      index: i
    })
  }
  rows.sort(function (a, b) {
    if (a.points !== b.points) return b.points - a.points
    if (a.label !== b.label) return a.label < b.label ? -1 : 1
    return a.index - b.index
  })
  var out = []
  for (var j = 0; j < rows.length; j++) out.push(rows[j].device)
  return out
}

function pickDevice(devices, filter, preferAddress) {
  var ranked = rankDevices(devices, filter, preferAddress)
  return ranked.length > 0 ? ranked[0] : null
}

// The addresses the service follows, best first: every connected match, because
// two headsets on one desk are two sets of earbuds and not a competition. With
// nothing connected it falls back to the one device that would have been picked
// — a paired match, most likely the set used last — so the widget can still
// name the earbuds it is waiting for rather than vanishing between them.
function followedAddresses(devices, filter, preferAddress) {
  var ranked = rankDevices(devices, filter, preferAddress)
  var out = []
  for (var i = 0; i < ranked.length; i++)
    if (ranked[i].connected) out.push(str(ranked[i].address))
  if (out.length === 0 && ranked.length > 0) out.push(str(ranked[0].address))
  return out
}

// The device behind an address, which is how a follower stays pinned to the one
// set it was made for: it never re-picks, it looks its own address up again.
// Case-insensitively, because an address that came back from a helper is not
// guaranteed to be cased the way BlueZ writes it.
function deviceByAddress(devices, address) {
  var wanted = str(address).trim().toUpperCase()
  if (wanted === "") return null
  var list = devices || []
  for (var i = 0; i < list.length; i++)
    if (list[i] && str(list[i].address).toUpperCase() === wanted) return list[i]
  return null
}

// The followers in the order the bar draws them: connected first, then the set
// used last, then by name, then by the order they were made. Same rule as
// rankDevices, over the followers themselves — they carry connected, address
// and name, which is all the order needs, and asking them rather than their
// devices keeps the panel from having to reach through to BlueZ.
function sortFollowers(followers, preferAddress) {
  var list = followers || []
  var wanted = str(preferAddress).toUpperCase()
  var rows = []
  for (var i = 0; i < list.length; i++) {
    var follower = list[i]
    if (!follower) continue
    var points = 0
    if (follower.connected) points += 16
    if (wanted && str(follower.address).toUpperCase() === wanted) points += 1
    rows.push({
      follower: follower,
      points: points,
      label: str(follower.name).toLowerCase(),
      index: i
    })
  }
  rows.sort(function (a, b) {
    if (a.points !== b.points) return b.points - a.points
    if (a.label !== b.label) return a.label < b.label ? -1 : 1
    return a.index - b.index
  })
  var out = []
  for (var j = 0; j < rows.length; j++) out.push(rows[j].follower)
  return out
}

// Which followed device an IPC caller meant, as an index into the list, and -1
// for a word that names none of them. A substring of the name or the address,
// case-insensitively, the same rule the deviceMatch setting uses — anyone who
// can pin the widget to "jbl" can ask "jbl" for its battery. Nothing named is
// the first device, which is what every no-argument call answers for.
function findByWhich(followers, which) {
  var list = followers || []
  var needle = str(which).trim().toLowerCase()
  if (needle === "") return list.length > 0 ? 0 : -1
  for (var i = 0; i < list.length; i++) {
    var follower = list[i]
    if (!follower) continue
    // Name, address, or the mode backend ("sony", "jbl"): a Sony headset calls
    // itself "WH-CH720N", so the brand a person types is in the backend, not
    // the name.
    var haystack = (str(follower.name) + " " + str(follower.address) + " " + str(follower.controlBackend)).toLowerCase()
    if (haystack.indexOf(needle) !== -1) return i
  }
  return -1
}

// -1 means "no number to show": either nothing is connected or BlueZ has no
// Battery1 for it. Callers must not paint a 0% meter for an unknown level.
function batteryLevel(device) {
  if (!device || !device.connected || !device.batteryAvailable) return -1
  var level = Math.round(Number(device.battery) * 100)
  if (!isFinite(level)) return -1
  return Math.max(0, Math.min(100, level))
}

function levelGlyph(level, charging) {
  // Total guard: undefined and NaN both fail every comparison, so a bare
  // `level < 0` would let them through and index the ramp with NaN.
  if (typeof level !== "number" || !isFinite(level) || level < 0) return ""
  var index = Math.max(0, Math.min(9, Math.floor(level / 10)))
  return charging ? CHARGING_GLYPHS[index] : LEVEL_GLYPHS[index]
}

// A whole number inside a range, for a dial that is stepped off whatever the
// device last said: a step at either end must stop there rather than ask for a
// figure the device has no room for. Anything that is not a number lands on
// `low`, because a dial with nothing to move is at its bottom, not anywhere
// else — callers that must tell "no number" from a real zero check first.
function clamp(value, low, high) {
  var number = Math.round(Number(value))
  if (!isFinite(number)) return low
  return Math.max(low, Math.min(high, number))
}

// The earbud that will die first is the number worth carrying in the bar; a
// bud sitting in the case reports nothing and must not drag it to zero.
function lowestBud(left, right) {
  if (left >= 0 && right >= 0) return Math.min(left, right)
  if (left >= 0) return left
  if (right >= 0) return right
  return -1
}

function barText(level, showPercentage) {
  if (level < 0 || !showPercentage) return HEADPHONES_GLYPH
  return HEADPHONES_GLYPH + " " + level + "%"
}

function percentLabel(level) {
  return level < 0 ? "—" : level + "%"
}

// A headset that reports one battery for the whole set, and the figure it
// reported. -1 for a set with per-earbud levels, and for a single set that has
// said nothing yet, so every caller can ask one question instead of two.
function singleLevel(state) {
  if (!state || state.single !== true) return -1
  var value = state.singleLevel
  return typeof value === "number" && value >= 0 ? value : -1
}

function statusLine(state) {
  if (!state.hasDevice) return "no headphones paired"
  if (!state.connected) return "not connected"
  // The levels sit in the rows right under this line, so the line does not
  // repeat them. What it adds is what the rows do not say on their own: whether
  // anything is charging, and whether the device has reported a battery at all.
  var known = singleLevel(state) >= 0 || state.left >= 0 || state.right >= 0 || state.level >= 0
  if (!known) return "connected · battery not reported"
  return state.charging ? "connected · charging" : "connected"
}

function tooltip(state) {
  if (!state.hasDevice) return "No headphones paired"
  if (!state.connected) return state.name + " · not connected"
  if (singleLevel(state) >= 0) return state.name + " · " + singleLevel(state) + "%"
  var parts = []
  if (state.left >= 0) parts.push("L " + state.left + "%")
  if (state.right >= 0) parts.push("R " + state.right + "%")
  if (state.caseLevel >= 0) parts.push("case " + state.caseLevel + "%")
  // With neither bud reporting, the whole-set level is what the bar shows, so it
  // has to lead here as well; a case-only tooltip otherwise names a number the
  // bar never mentions and contradicts statusLine.
  if (state.left < 0 && state.right < 0 && state.level >= 0)
    parts.unshift(state.level + "%")
  if (parts.length > 0) return state.name + " · " + parts.join(" · ")
  if (state.level >= 0) return state.name + " · " + state.level + "%"
  return state.name + " · battery unknown"
}

function lowBatteryBody(state) {
  if (singleLevel(state) >= 0) return singleLevel(state) + "% left"
  var parts = []
  if (state.left >= 0) parts.push("L " + state.left + "%")
  if (state.right >= 0) parts.push("R " + state.right + "%")
  if (parts.length > 0) return parts.join(" · ") + " left"
  if (state.level >= 0) return state.level + "% left"
  return "battery low"
}

// What a helper that died without explaining itself said on stderr, reduced to
// the one line worth putting in a panel: the last non-empty one, which for a
// Python traceback is the exception rather than the frames above it. Trimmed to
// something that fits, because a panel is not a log.
function shortError(text, fallback) {
  var lines = str(text).split("\n")
  for (var i = lines.length - 1; i >= 0; i--) {
    var line = lines[i].replace(/^\s+|\s+$/g, "")
    if (line === "") continue
    line = plainText(line)
    return line.length > 160 ? line.substring(0, 157) + "…" : line
  }
  return fallback
}

// One JSON line from gfps-reader into the shape the panel binds to. Absent keys
// keep their previous value: the reader resends its whole values dict on every
// change, and only the three-key error line it writes when the stream goes down
// ({address, stream, error}) lacks modelId and firmware, which must survive it.
// Anything that is not a JSON object — junk, a bare number, an array whose
// indices would merge in as keys "0", "1" — leaves the state untouched.
//
// `address` merges in like any other key rather than being filtered out. It is
// the same address on every line a follower is given — the service routes by it
// before this is reached — so carrying it costs one sticky key and makes a
// dumped `reading` say which device it came from.
function mergeReaderLine(previous, raw) {
  var next = {}
  for (var key in previous) next[key] = previous[key]
  var parsed = null
  try {
    parsed = JSON.parse(String(raw || "").trim() || "{}")
  } catch (e) {
    return next
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return next
  for (var incoming in parsed) next[incoming] = parsed[incoming]
  return next
}

// Which device a reader line is about, uppercase, or "" for one that is about
// the reader itself. One gfps-reader serves every followed device — BlueZ hands
// out one Message Stream registration for the whole system, so it has to — and
// `address` is how a line finds its follower. A line without one is a failure
// of the process rather than of a channel (a missing python module, a
// registration refused), which is every device's problem and no device's line.
// Junk parses to "" as well: an unroutable line and an unparseable one need the
// same treatment, and the merge below already ignores both.
function readerLineAddress(raw) {
  var parsed = null
  try {
    parsed = JSON.parse(String(raw || "").trim() || "{}")
  } catch (e) {
    return ""
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return ""
  if (typeof parsed.address !== "string") return ""
  return parsed.address.trim().toUpperCase()
}

// The addresses to start the one reader for: the followers whose device is
// connected. A follower for a device in its case is kept so the widget can name
// what it is waiting for, but it has no channel to open — and asking BlueZ for
// one would connect the earbuds behind their owner's back.
function readerAddresses(followers) {
  var list = followers || []
  var out = []
  for (var i = 0; i < list.length; i++) {
    var follower = list[i]
    if (!follower || !follower.connected) continue
    var address = str(follower.address).trim().toUpperCase()
    if (address !== "" && out.indexOf(address) === -1) out.push(address)
  }
  return out
}

// The bridge's record of which Fast Pair model ids answered for their listening
// mode. Unreadable or absent means "never asked", which costs one probe.
function parseSupport(raw) {
  try {
    var parsed = JSON.parse(String(raw || "").trim() || "{}")
    // An array passes `typeof === "object"`, and support[modelId] on one would
    // read as "never asked" by luck rather than by rule; refuse it outright.
    return (parsed && typeof parsed === "object" && !Array.isArray(parsed)) ? parsed : {}
  } catch (e) {
    return {}
  }
}

// 1 answered before, 0 gave up on after repeated silence, -1 not settled yet.
// An entry only reads 0 once the bridge has connected and heard nothing several
// times over, so a single bad connection never retires the feature.
function supportVerdict(support, modelId) {
  if (!modelId) return -1
  var entry = support ? support[modelId] : undefined
  if (!entry || typeof entry !== "object") return -1
  if (entry.supported === true) return 1
  if (entry.supported === false) return 0
  return -1
}

function readerLevel(state, key) {
  var value = state ? state[key] : undefined
  return typeof value === "number" && value >= 0 ? value : -1
}

// ---- Which helper can control the listening mode of a given device.
//
// Three protocols, decided per device from its SDP record rather than from its
// name: Sony's MDR v2 lives on an RFCOMM channel the headset itself serves, and
// advertising the UUID is the whole claim — a device that lists it speaks it.
// Xiaomi Buds 5 Pro (and other QCC sets that advertise CSR GAIA) speak Compact
// GAIA on standard SPP; the GAIA UUID is the claim, SPP is the socket.
// JBL's is a BLE GATT service at an address that rotates and is announced only
// on the Fast Pair Message Stream, so knowing that address is what makes that
// path possible at all.
var SONY_MDR_V2_UUID = "956c7b26-d49a-4ba8-b03f-b17d393cb6e2"
var CSR_GAIA_UUID = "00001100-d102-11e1-9b23-00025b00a5a5"
var SOUNDCORE_UUID_PREFIX = "0cf12d31-fac3-4553-bd80-d6832e7"

// The UUIDs `bluetoothctl info <address>` printed, lowercased.
// Quickshell.Bluetooth exposes no uuids property, so the SDP record is read the
// way a person would read it:
//
//   \tUUID: Vendor specific           (956c7b26-d49a-4ba8-b03f-b17d393cb6e2)
//
// Everything else in that output — Modalias, Battery Percentage, the name —
// carries no parenthesised UUID and falls out on its own.
function uuidsFromBluetoothctl(text) {
  var out = []
  var lines = str(text).split("\n")
  for (var i = 0; i < lines.length; i++) {
    var found = lines[i].match(/UUID:.*\(([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\)/)
    if (found) out.push(found[1].toLowerCase())
  }
  return out
}

// "sony", "xiaomi", "soundcore", "jbl" or "" — the backend to run for this device, and the
// empty string for a device no path can reach. SDP UUIDs win because they come
// from the device's own record: Sony first, then CSR GAIA (Xiaomi / QCC on
// SPP), then Soundcore vendor RFCOMM. A known BLE address only says the Message Stream is up, which every
// Fast Pair device does whether or not it answers a mode query, so it is last.
function controlBackend(uuids, bleAddress) {
  var list = uuids || []
  var gaia = false
  var soundcore = false
  for (var i = 0; i < list.length; i++) {
    var id = str(list[i]).trim().toLowerCase()
    if (id === SONY_MDR_V2_UUID) return "sony"
    if (id === CSR_GAIA_UUID) gaia = true
    if (id.indexOf(SOUNDCORE_UUID_PREFIX) === 0) soundcore = true
  }
  if (gaia) return "xiaomi"
  if (soundcore) return "soundcore"
  return str(bleAddress).trim() !== "" ? "jbl" : ""
}

// The order the panel draws them in, and the only names a bridge may use.
var MODE_ORDER = ["off", "anc", "ambient", "talkthru"]

// Which modes to offer for the state the bridge last reported. A line with no
// `available` key is the JBL bridge, which names none and means all four — its
// protocol has one fixed set of slots. The Sony bridge lists what the headset
// has, and an over-ear WH has no TalkThru. Names it does not recognise are
// dropped rather than drawn: a button the device will not take does nothing.
function modesAvailable(state) {
  var list = state ? state.available : undefined
  if (!list || !Array.isArray(list)) return MODE_ORDER.slice()
  var out = []
  for (var i = 0; i < MODE_ORDER.length; i++)
    if (list.indexOf(MODE_ORDER[i]) !== -1) out.push(MODE_ORDER[i])
  return out
}
