import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Bluetooth
import "Model.js" as Model

// Everything about the earbuds that must exist exactly once, and one follower
// per set of earbuds that is connected.
//
// A bar surface exists per monitor, so Panel.qml is built once per screen. Two
// Message Stream readers would fight over the single RFCOMM channel BlueZ hands
// out, two BLE bridges would each hold a link open on the earbuds' radio, and
// one drained battery would produce as many warnings as you have monitors.
// Loaded as a service instead, this runs once for the session; every panel finds
// it with shell.serviceFor("io.github.ncr.omaphones") and only draws what it says.
//
// What it does not do is talk to a device. It used to follow one — the best of
// whatever was paired — and a JBL pair and a Sony headset connected at the same
// time were one widget arguing with itself: the pick moved, the helpers were
// re-aimed, and lines from the reader that had just been killed landed after the
// switch, putting one device's name over the other's levels. So the device half
// moved into DeviceFollower.qml, one instance per connected device, each pinned
// to its address for its lifetime. This file keeps what they share:
//
//   the settings          pushed in by the panel, the same for every device
//   the device list       from BlueZ, which is what followers are made from
//   the Fast Pair reader  one process for every device, because BlueZ hands out
//                         one Message Stream registration per system and not
//                         per device; its lines are routed by the address each
//                         one carries
//   the caches            mode support on disk, parked models and addresses,
//                         the retry backoff, the warned-about flags
//   the notification      one process, one queue, however many headsets
//   the IPC surface       which answers for one device or for all of them
//
// Two sources of battery, in order of what they can say:
//
//   gfps-reader   sits on the Google Fast Pair Message Stream (an RFCOMM
//                 channel these earbuds serve for Android's battery UI) and
//                 reports left, right and case separately, 0-100, with a
//                 charging flag — or one battery for the whole set, on a
//                 headset that has only one. It streams: the device pushes a
//                 new reading when a level changes.
//   BlueZ         org.bluez.Battery1, one number for the whole set, rounded to
//                 ten steps by the HFP indicator it comes from. The fallback
//                 for a device with no Message Stream.
Item {
  id: root

  property var shell: null

  // ---- Settings. The service has no shell.json entry of its own: each panel
  //      instance pushes the widget's settings in with Binding. The values below
  //      are what the service runs on until one does, so a service with no
  //      widget on any bar behaves like a widget with default settings.
  //
  //      These defaults must stay in step with manifest.json's
  //      barWidget.defaults and with the setting() fallbacks in Panel.qml.
  property string deviceMatch: ""
  property bool useFastPair: true
  property bool useModeControl: true
  property int lowThreshold: 20
  property bool notifyLow: true

  // ---- Which devices, from BlueZ.
  readonly property var devices: Bluetooth.devices ? Bluetooth.devices.values : []
  // Model.followedAddresses reads connected/battery off each device while this
  // binding evaluates, so it re-runs when any of them changes — not only when a
  // device is added or removed. Every connected match is followed; with nothing
  // connected it names the one device the widget would have picked, so the panel
  // can still say which earbuds it is waiting for.
  readonly property var followedAddresses: Model.followedAddresses(devices, deviceMatch, persisted.lastAddress)

  // ---- The followers, and the order the bar and the panel take them in.
  //
  //      `followers` is creation order, which is whatever order the addresses
  //      turned up in; `followed` is the order a person reads — connected first,
  //      then the set used last, then by name. The panel draws one icon per
  //      entry and the IPC answers for `primary` when nobody said which device.
  property var followers: []
  readonly property var followed: Model.sortFollowers(followers, persisted.lastAddress)
  readonly property var primary: followed.length > 0 ? followed[0] : null

  readonly property string pluginId: "io.github.ncr.omaphones"

  // Which addresses have a follower, as a model rather than as a list, because a
  // list assigned wholesale rebuilds every delegate: a JBL pair connecting would
  // tear down the Sony's reader and bridge and open them again a moment later,
  // which is exactly the mixing this refactor exists to stop. Rows are added and
  // removed one at a time instead, and an untouched row keeps its follower —
  // and with it, its processes.
  ListModel { id: followerRows }

  function syncFollowers() {
    var wanted = followedAddresses
    for (var i = followerRows.count - 1; i >= 0; i--)
      if (wanted.indexOf(followerRows.get(i).deviceAddress) === -1) followerRows.remove(i)
    for (var j = 0; j < wanted.length; j++) {
      var known = false
      for (var k = 0; k < followerRows.count; k++)
        if (followerRows.get(k).deviceAddress === wanted[j]) { known = true; break }
      if (!known) followerRows.append({ deviceAddress: wanted[j] })
    }
  }

  function rebuildFollowers() {
    var list = []
    for (var i = 0; i < followerHost.count; i++) {
      var object = followerHost.objectAt(i)
      if (object) list.push(object)
    }
    followers = list
  }

  onFollowedAddressesChanged: syncFollowers()
  Component.onCompleted: syncFollowers()

  Instantiator {
    id: followerHost
    model: followerRows
    delegate: DeviceFollower {
      // Taken from the row as a required property rather than off the injected
      // model object: the follower has an `address` of its own, and a role that
      // arrives under the same name is one shadowing away from a follower
      // pointed at nothing.
      required property string deviceAddress

      service: root
      address: deviceAddress
    }
    onObjectAdded: root.rebuildFollowers()
    onObjectRemoved: root.rebuildFollowers()
  }

  // The follower an IPC caller meant. No word means the primary device, which is
  // what every no-argument call answers for; a word that names none of them is
  // null, and each method says so in whatever its own vocabulary is.
  // The address an `openFor` IPC call asked the panel to show. Set, then read by
  // the panel; cleared by nobody — the next request simply overwrites it, and a
  // repeated request for the same address is re-signalled by blanking first.
  property string openRequest: ""

  // "x y w h" of the open popup card in logical screen pixels, written by the
  // panel that is open; "" while none is. Read by tools/gallery-shot.
  property string panelRect: ""

  function followerFor(which) {
    var index = Model.findByWhich(followed, which)
    return index >= 0 ? followed[index] : null
  }

  // ---- The Fast Pair reader: one process, however many devices.
  //
  //      BlueZ registers an org.bluez.Profile1 per UUID for the whole system
  //      rather than per device, so the second reader to ask is told the UUID
  //      is taken — and with two Fast Pair sets connected, one of them lost its
  //      per-earbud levels and (on the JBL side) the BLE address the mode
  //      bridge is reached at. So the reader lives here, holding the one
  //      registration and serving every followed device down one pipe: each
  //      line it writes for a device carries that device's `address`, which is
  //      what routes it to a follower, and a line without one is the process
  //      saying it cannot do the job for any of them.
  //
  //      The mode bridges stay with their followers. Each of those is a link to
  //      one device and collides with nothing.
  readonly property string readerPath: Qt.resolvedUrl("gfps-reader").toString().replace(/^file:\/\//, "")
  // The devices the reader is asked to hold a channel open for. A follower for
  // a device that is not connected is kept so the widget can name what it is
  // waiting for, but it has nothing to open.
  readonly property var readerAddresses: Model.readerAddresses(followed)
  readonly property bool readerRunning: gfpsReader.running
  property bool readerEnabled: true
  property int readerBackoffMs: 8000
  // What the running process has been told to follow, so a device connecting or
  // going away is one line on its stdin rather than a restart: restarting drops
  // the registration, and with it every other device's channel.
  property var readerFollowing: []
  // What the reader last said about itself, as opposed to about a device. Every
  // follower shows it, because a reader that cannot run is every device's
  // problem; `readerRunError` is the same thing kept so an exit can tell a
  // process that explained itself from one that simply died.
  property string readerError: ""
  property string readerRunError: ""

  // One line of the reader's stdout, to whichever follower it is about.
  function applyReaderLine(line) {
    var address = Model.readerLineAddress(line)
    if (address !== "") {
      var follower = followerWithAddress(address)
      if (follower) follower.applyReaderLine(line)
      // A run that got a device's line out is a healthy one; the next failure
      // starts its backoff from the bottom again.
      readerBackoffMs = 8000
      return
    }
    // No address: the line is about the reader itself. `{stream: false, error}`
    // is a failure every device is down with, and a line saying the stream is
    // back is the reader saying that failure is over — nothing else ever would.
    // Anything that parses to neither said nothing about anything.
    var fields = Model.mergeReaderLine({}, line)
    if (fields.stream === undefined) return
    if (fields.stream === false) {
      readerError = String(fields.error || "")
      readerRunError = readerError
    } else {
      readerError = ""
      readerRunError = ""
      readerBackoffMs = 8000
    }
  }

  // The follower an address belongs to. Model.deviceByAddress matches on the
  // `address` property, which a follower carries as surely as a BlueZ device
  // does — and matches it case-insensitively, so a line's address needs no
  // agreement with BlueZ about how to write one.
  function followerWithAddress(address) {
    return Model.deviceByAddress(followers, address)
  }

  // Tell the running reader what changed. Nothing to do when it is not running:
  // the addresses go on its command line, and it follows them at start.
  function syncReader() {
    if (!gfpsReader.running) return
    var wanted = readerAddresses
    var told = readerFollowing
    for (var i = 0; i < told.length; i++)
      if (wanted.indexOf(told[i]) === -1) gfpsReader.write("unfollow " + told[i] + "\n")
    for (var j = 0; j < wanted.length; j++)
      if (told.indexOf(wanted[j]) === -1) gfpsReader.write("follow " + wanted[j] + "\n")
    readerFollowing = wanted.slice()
  }

  onReaderAddressesChanged: syncReader()

  // Ask one device for a fresh reading. True when the request actually went
  // out, because a follower that is told nothing happened must not blank its
  // rows waiting for an answer that is not coming.
  function refreshReader(address) {
    if (!useFastPair) return false
    if (gfpsReader.running && readerFollowing.indexOf(String(address).toUpperCase()) !== -1) {
      gfpsReader.write("refresh " + address + "\n")
      return true
    }
    // Nothing to re-open — the reader is between attempts, or was never allowed
    // to start. Bring the next attempt forward instead of latching it off.
    readerBackoffMs = 8000
    readerRestart.stop()
    readerEnabled = true
    return false
  }

  Process {
    id: gfpsReader
    running: root.useFastPair && root.readerAddresses.length > 0 && root.readerEnabled
    command: [root.readerPath].concat(root.readerAddresses)
    stdinEnabled: true
    stdout: SplitParser {
      onRead: function(line) { root.applyReaderLine(line) }
    }
    stderr: StdioCollector { id: readerStderr; waitForEnd: true }
    // A fresh run starts with a clean slate, the same as the bridges: whatever
    // the run that died complained about is not about this one, and leaving it
    // on screen would read as a live fault while the channels are open.
    onRunningChanged: {
      if (running) {
        root.readerError = ""
        root.readerRunError = ""
        // Started from the command line above, which is the address list as it
        // was when the process started.
        root.readerFollowing = root.readerAddresses.slice()
        for (var i = 0; i < root.followers.length; i++) root.followers[i].clearReaderError()
      } else {
        root.readerFollowing = []
      }
    }
    onExited: function(exitCode, exitStatus) {
      // A clean exit is the reader that was asked to stop — Fast Pair switched
      // off, the last device gone — and it has finished rather than failed.
      // Anything else is a failure that should not be retried tightly.
      var deliberate = exitCode === 0
      // A helper that died without saying why on stdout still said something on
      // stderr — a missing python module, most often, which is worth printing
      // rather than leaving the panel to shrug.
      if (!deliberate && root.readerRunError === "")
        root.readerError = Model.shortError(readerStderr.text,
          "the Fast Pair reader stopped (exit " + exitCode + ")")
      root.readerEnabled = false
      readerRestart.interval = deliberate ? 600 : root.readerBackoffMs
      // Doubling up to five minutes: the usual reasons a reader dies are the
      // earbuds dropping the channel and another program holding the Message
      // Stream, and neither is fixed by asking again straight away.
      if (!deliberate) root.readerBackoffMs = Math.min(300000, root.readerBackoffMs * 2)
      readerRestart.restart()
    }
  }

  Timer {
    id: readerRestart
    repeat: false
    onTriggered: root.readerEnabled = true
  }

  // ---- Caches the followers share, because they outlive any one of them.
  //
  //      Which models answered for their listening mode, remembered across
  //      restarts by the bridge and only read here. Nothing is assumed from a
  //      device's name: an unknown model gets one probe, and the answer is kept
  //      so a silent device is not reconnected to after every restart just to
  //      ask again.
  //
  //        1  answered before      0  stayed silent before      -1  never asked
  property var modeSupport: ({})
  // Models that failed during this session, so a failure stops the retries now
  // rather than waiting for the cache write to land. Keyed by model, so plugging
  // in a silent headset does not disable the row for the earbuds that do answer.
  property var ancParked: ({})
  // Addresses whose Classic-channel bridge (Sony, Nothing, Xiaomi) failed for
  // good this session. Kept apart from the model-keyed map above because the
  // two name different things: those paths never learn a Fast Pair model id,
  // and one headset failing must not retire another that happens to share a
  // keyspace by accident.
  property var sonyParked: ({})
  // How long to wait before the next attempt, keyed by whatever identifies the
  // device for the backend in play — the Fast Pair model for the JBL bridge, the
  // Classic address for the others: a device that is out of reach must not be
  // dialled every ten seconds all afternoon.
  property var ancBackoff: ({})

  function ancBackoffFor(key) {
    var value = ancBackoff[String(key)]
    return typeof value === "number" && value > 0 ? value : 10000
  }

  function bumpAncBackoff(key) {
    var next = {}
    for (var name in ancBackoff) next[name] = ancBackoff[name]
    next[String(key)] = Math.min(300000, ancBackoffFor(key) * 2)
    ancBackoff = next
  }

  function resetAncBackoff(key) {
    if (ancBackoff[String(key)] === undefined) return
    var next = {}
    for (var name in ancBackoff) next[name] = ancBackoff[name]
    delete next[String(key)]
    ancBackoff = next
  }

  function parkModel(model) {
    var next = {}
    for (var key in ancParked) next[key] = ancParked[key]
    next[String(model)] = true
    ancParked = next
  }

  function parkAddress(value) {
    if (String(value || "") === "") return
    var next = {}
    for (var key in sonyParked) next[key] = sonyParked[key]
    next[String(value)] = true
    sonyParked = next
  }

  // Which devices have been warned about, by address, and remembered across a
  // reload. One flag per address rather than one flag: two headsets draining in
  // the same hour are two warnings, and clearing one must not re-arm the other.
  readonly property var notifiedLow: persisted.notifiedLow

  function setNotifiedLow(address, value) {
    var key = String(address || "")
    if (key === "") return
    var current = persisted.notifiedLow
    if (!current || typeof current !== "object") current = ({})
    if ((current[key] === true) === (value === true)) return
    var next = {}
    for (var name in current) next[name] = current[name]
    if (value) next[key] = true
    else delete next[key]
    persisted.notifiedLow = next
  }

  // The address the widget falls back to while nothing is connected, and the
  // tie-breaker in the ranking. `followedAddresses` is picked with it and every
  // follower's address is read off that list, so writing it from a follower's
  // handler would close a binding loop. Defer the write to the next event-loop
  // turn; the value it records is the same.
  function rememberAddress(value) {
    if (persisted.lastAddress === value) return
    Qt.callLater(function () { persisted.lastAddress = value })
  }

  // ---- The notification, sent for whichever device ran low. One process, and a
  //      queue behind it: a Process that is already running would drop the
  //      second warning, and two flat headsets are two things worth saying.
  property var notifyQueue: []

  function notify(title, body) {
    var next = notifyQueue.slice()
    next.push({ title: String(title), body: String(body) })
    notifyQueue = next
    sendNextNotification()
  }

  function sendNextNotification() {
    if (notifyProcess.running || notifyQueue.length === 0) return
    var pending = notifyQueue[0]
    notifyQueue = notifyQueue.slice(1)
    notifyProcess.command = [
      "omarchy-notification-send",
      "-u", "critical",
      "-g", Model.HEADPHONES_GLYPH,
      pending.title,
      pending.body
    ]
    notifyProcess.running = true
  }

  // ---- The IPC surface, `omarchy-shell omaphones <method>`. It lives here and
  //      not in Panel.qml because a target may be registered once and a bar
  //      surface exists per monitor: two screens would mean two handlers
  //      fighting over the name "omaphones". The panel methods go the long way
  //      round through the shell, which finds whichever bar is showing the
  //      widget; everything else is answered from the followers' state, which
  //      is the same state every panel draws.
  //
  //      Each question comes in two forms: the plain one, which answers for the
  //      primary device — the first icon in the bar — and a `…For` one that
  //      takes a trailing `which`, a case-insensitive substring of a name or an
  //      address, and answers for the device that matches. Two names rather than
  //      one optional argument because an IPC function's arity is fixed:
  //      quickshell refuses a call with one argument too few or too many, and a
  //      typed parameter may not carry a default. `status` with no argument is
  //      the exception that needs no `which` at all — it lists every device the
  //      widget follows, one per line.
  IpcHandler {
    target: "omaphones"

    function open(): void { if (root.shell) root.shell.summon(root.pluginId) }
    // openFor names the device the panel should show before it opens; the panel
    // watches `openRequest` and moves its selection to that follower.
    function panelRect(): string { return root.panelRect }
    function openFor(which: string): string {
      var follower = root.followerFor(which)
      if (!follower) return "no device matching: " + which
      root.openRequest = ""
      root.openRequest = follower.address
      if (root.shell) root.shell.summon(root.pluginId)
      return "ok"
    }
    function close(): void { if (root.shell) root.shell.hide(root.pluginId) }
    function show(): void { if (root.shell) root.shell.summon(root.pluginId) }
    function hide(): void { if (root.shell) root.shell.hide(root.pluginId) }
    function toggle(): void { if (root.shell) root.shell.toggle(root.pluginId) }

    function refresh(): void { if (root.primary) root.primary.refresh() }
    function refreshFor(which: string): void {
      var follower = root.followerFor(which)
      if (follower) follower.refresh()
    }

    // Every device the widget follows, one line each, so a script can see the
    // whole desk in one call. Nothing followed is the one line the single-device
    // version always printed: there is nothing to enumerate.
    function status(): string {
      var list = root.followed
      if (list.length === 0) return Model.tooltip({ hasDevice: false })
      var lines = []
      for (var i = 0; i < list.length; i++) lines.push(Model.tooltip(list[i].summary))
      return lines.join("\n")
    }
    function statusFor(which: string): string {
      var follower = root.followerFor(which)
      return follower ? Model.tooltip(follower.summary) : root.noSuchDevice(which)
    }

    // The one number the bar carries: the headset's own figure where there is
    // one battery, otherwise the lowest earbud, or BlueZ's rounded single
    // figure when the Message Stream has said nothing.
    function battery(): string { return String(root.primary ? root.primary.level : -1) }
    function batteryFor(which: string): string { return root.levelOf(which, "level") }

    // The earbuds' current BLE address, which rotates and is published only on
    // this channel. tools/jbl-anc asks for it rather than opening a second
    // Message Stream, because BlueZ allows only one holder of the profile.
    function bleAddress(): string { return String(root.primary ? root.primary.bleAddress : "") }
    function bleAddressFor(which: string): string {
      var follower = root.followerFor(which)
      return follower ? String(follower.bleAddress) : ""
    }

    // Three answers, and the caller can act on each: a mode to use, "pending"
    // while the bridge is coming up — wait and ask again — and "unsupported"
    // for earbuds this shell cannot ask, where the only way to a mode is to
    // open a link yourself.
    function mode(): string { return root.modeOf(root.primary) }
    function modeFor(which: string): string { return root.modeOf(root.followerFor(which)) }

    // Same three states, one word each: "ok" the frame went out, "busy" the
    // bridge is up but not answering yet, so the same set is worth offering
    // again, and "unavailable" there is no bridge to write through at all — or
    // the device has answered and does not offer this mode, which is a settled
    // no rather than something to try again.
    function setMode(mode: string): string { return root.writeMode(root.primary, mode) }
    function setModeFor(mode: string, which: string): string {
      return root.writeMode(root.followerFor(which), mode)
    }

    // The Ambient dial, 0-20, on devices that have one (Sony). -1 while nothing
    // has said, which is also what a JBL pair reads as: its Ambient Aware is a
    // mode, not an amount.
    function ambientLevel(): string { return String(root.primary ? root.primary.ambientLevel : -1) }
    function ambientLevelFor(which: string): string { return root.levelOf(which, "ambientLevel") }

    // Sets it, and switches the device to Ambient with it, because the amount is
    // stored only by a set that carries it. "unavailable" for a device with no
    // dial, or no bridge to write through.
    function setAmbientLevel(level: int): string {
      return root.writeAmbientLevel(root.primary, level)
    }
    function setAmbientLevelFor(level: int, which: string): string {
      return root.writeAmbientLevel(root.followerFor(which), level)
    }

    // Focus on Voice, the other half of Ambient on a Sony. "on" or "off", and
    // empty on a device that has never mentioned it — a JBL pair, or a bridge
    // that has not answered yet — because "off" there would claim a switch that
    // does not exist is switched off.
    function ambientVoice(): string { return root.voiceOf(root.primary) }
    function ambientVoiceFor(which: string): string { return root.voiceOf(root.followerFor(which)) }

    // Takes the same words a setting does — on/off, true/false, 1/0 — because
    // the shell hands IPC arguments over as strings whatever they look like.
    function setAmbientVoice(on: string): string {
      return root.writeAmbientVoice(root.primary, on)
    }
    function setAmbientVoiceFor(on: string, which: string): string {
      return root.writeAmbientVoice(root.followerFor(which), on)
    }

    // How strong the noise cancelling is, on a device that grades it (Nothing):
    // low, mid, high or adaptive, and empty on a device that has never named a
    // strength — a JBL pair, a Sony headset, or a bridge that has not answered.
    function ancLevel(): string { return root.ancLevelOf(root.primary) }
    function ancLevelFor(which: string): string { return root.ancLevelOf(root.followerFor(which)) }

    // Sets it, and switches the device to ANC with it, because the device
    // stores the strength with the mode. "unavailable" for a device with no
    // strengths, or no bridge to write through.
    function setAncLevel(level: string): string {
      return root.writeAncLevel(root.primary, level)
    }
    function setAncLevelFor(level: string, which: string): string {
      return root.writeAncLevel(root.followerFor(which), level)
    }

    // Low latency, on devices whose channel carries the switch (Nothing). "on"
    // or "off", and empty where the bridge has never mentioned it.
    function latency(): string { return root.latencyOf(root.primary) }
    function latencyFor(which: string): string { return root.latencyOf(root.followerFor(which)) }
    function setLatency(on: string): string { return root.writeLatency(root.primary, on) }
    function setLatencyFor(on: string, which: string): string {
      return root.writeLatency(root.followerFor(which), on)
    }

    // The A2DP codec PipeWire negotiated for the link — "aac", "sbc", "ldac" —
    // and the ones the card offers, one per line. Empty while the device is not
    // connected or the card has not been read yet.
    function codec(): string { return root.codecOf(root.primary) }
    function codecFor(which: string): string { return root.codecOf(root.followerFor(which)) }
    function codecs(): string { return root.codecsOf(root.primary) }
    function codecsFor(which: string): string { return root.codecsOf(root.followerFor(which)) }

    // Asks PipeWire for a codec the card offers. "ok" the change was handed
    // over — `codec` a moment later says what it settled on — and
    // "unavailable" for a codec the card does not list.
    function setCodec(key: string): string { return root.writeCodec(root.primary, key) }
    function setCodecFor(key: string, which: string): string {
      return root.writeCodec(root.followerFor(which), key)
    }

    // The three components, each -1 when it reports nothing. All three read -1
    // on a headset with one battery for the whole set: it has no left earbud,
    // and `battery` above is where its figure lives.
    function left(): string { return String(root.primary ? root.primary.leftLevel : -1) }
    function leftFor(which: string): string { return root.levelOf(which, "leftLevel") }
    function right(): string { return String(root.primary ? root.primary.rightLevel : -1) }
    function rightFor(which: string): string { return root.levelOf(which, "rightLevel") }
    function batteryCase(): string { return String(root.primary ? root.primary.caseLevel : -1) }
    function batteryCaseFor(which: string): string { return root.levelOf(which, "caseLevel") }

    // Which components say they are charging, for looking into the cases where
    // that is not what you expected. Empty means none of them said so, and
    // "battery" is the whole set on a headset that has only one.
    function charging(): string { return root.chargingOf(root.primary) }
    function chargingFor(which: string): string { return root.chargingOf(root.followerFor(which)) }
  }

  // ---- What the two forms of each method above share, so the pair cannot drift
  //      apart. A null follower is a device nobody could find, and each of these
  //      answers that in the vocabulary its own method already had: an unknown
  //      number is -1, an unreachable mode is "unsupported", a write that never
  //      went out is "unavailable".
  function noSuchDevice(which) {
    return "no device matching: " + String(which)
  }

  function levelOf(which, key) {
    var follower = followerFor(which)
    return String(follower ? follower[key] : -1)
  }

  function modeOf(follower) {
    if (!follower) return "unsupported"
    if (follower.ancLive && follower.ancMode !== "") return follower.ancMode
    if (follower.bridgeRunning) return "pending"
    return "unsupported"
  }

  function writeMode(follower, mode) {
    if (["off", "anc", "ambient", "talkthru"].indexOf(String(mode)) === -1)
      return "unknown mode: " + mode
    if (!follower) return "unavailable"
    if (follower.setAncMode(mode)) return "ok"
    if (follower.ancLive) return "unavailable"
    return follower.bridgeRunning ? "busy" : "unavailable"
  }

  function writeAmbientLevel(follower, level) {
    return follower && follower.setAmbientLevel(level) ? "ok" : "unavailable"
  }

  function writeAmbientVoice(follower, on) {
    return follower && follower.setAmbientVoice(Model.asBool(on, false)) ? "ok" : "unavailable"
  }

  function voiceOf(follower) {
    if (!follower || !follower.ambientControls) return ""
    return follower.ambientVoice ? "on" : "off"
  }

  function ancLevelOf(follower) {
    if (!follower || !follower.ancLive || follower.ancLevels.length === 0) return ""
    return follower.ancLevel
  }

  function writeAncLevel(follower, level) {
    if (Model.ANC_LEVEL_ORDER.indexOf(String(level)) === -1) return "unknown level: " + level
    return follower && follower.setAncLevel(String(level)) ? "ok" : "unavailable"
  }

  function latencyOf(follower) {
    if (!follower || !follower.latencyKnown) return ""
    return follower.latencyEnabled ? "on" : "off"
  }

  function writeLatency(follower, on) {
    return follower && follower.setLatency(Model.asBool(on, false)) ? "ok" : "unavailable"
  }

  function codecOf(follower) {
    return follower && follower.connected ? follower.activeCodec : ""
  }

  function codecsOf(follower) {
    if (!follower || !follower.connected) return ""
    var keys = []
    for (var i = 0; i < follower.codecOptions.length; i++) keys.push(follower.codecOptions[i].key)
    return keys.join("\n")
  }

  function writeCodec(follower, key) {
    return follower && follower.setCodec(String(key)) ? "ok" : "unavailable"
  }

  function chargingOf(follower) {
    if (!follower) return ""
    var parts = []
    if (follower.singleCharging) parts.push("battery")
    if (follower.leftCharging) parts.push("left")
    if (follower.rightCharging) parts.push("right")
    if (follower.caseCharging) parts.push("case")
    return parts.join(",")
  }

  PersistentProperties {
    id: persisted
    reloadableId: "omaphones"
    // Which devices have already been warned about, keyed by address. It was one
    // boolean while the widget followed one device; an old boolean restored into
    // this reads as an empty map, which costs at most one repeated warning.
    property var notifiedLow: ({})
    // Which earbuds to name while nothing is connected, so a widget set to stay
    // visible does not offer to show the battery of a headset you last used in
    // another room.
    property string lastAddress: ""
  }

  Process {
    id: notifyProcess
    onExited: root.sendNextNotification()
  }

  FileView {
    id: modeSupportFile
    // Quickshell.env returns null, not "", for a variable that is not set.
    path: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state")
      + "/omaphones/mode-support.json"
    watchChanges: true
    printErrors: false
    onLoaded: root.modeSupport = Model.parseSupport(text())
    onFileChanged: reload()
  }
}
