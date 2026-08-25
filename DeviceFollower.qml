import QtQuick
import Quickshell
import Quickshell.Io
import "Model.js" as Model

// One device, followed for as long as it is connected.
//
// Everything here belongs to a single set of earbuds: its mode bridge, its
// levels, its errors, its warning state. The address is handed in when the
// service builds this and never changes afterwards — that is the whole point of
// the split. The old single-device service pointed one reader at whichever
// device it had picked, and a pick that moved while a line was in flight put
// the Sony's name over the JBL's left, right and case. A follower cannot mix
// two devices because it only ever knew about one; when its device goes, the
// follower goes with it and Quickshell kills the bridges below.
//
// The Fast Pair reader is the one helper a follower does not own. BlueZ hands
// out a single Message Stream registration for the whole system, so one process
// serves every device and the service holds it; each line it writes names the
// device it is about, and the service calls applyReaderLine() on the follower
// that address belongs to. What a line means is still decided here.
//
// Not a service entry point. The plugin's one service (Service.qml) creates
// these, holds what they share — the settings, the reader, the mode-support
// cache, the parked and backoff maps, the notification process — and hands
// itself in as `service` so a follower can reach them.
Item {
  id: follower

  // The service that made this follower, for the shared state above. Never null
  // in practice; the guards are for the moment of construction and for anyone
  // who builds one of these by hand.
  property var service: null

  // The device this follower is about, fixed for its lifetime. Everything else
  // in this file hangs off it.
  property string address: ""

  // Looked up again rather than remembered, so a BlueZ device object that is
  // replaced (an adapter reset, a re-pair) is followed through. The lookup is by
  // address, so it can never land on a different set of earbuds.
  readonly property var device: Model.deviceByAddress(service ? service.devices : [], address)

  readonly property bool hasDevice: !!device
  readonly property bool connected: hasDevice && device.connected === true
  readonly property string name: hasDevice ? Model.deviceLabel(device) : ""

  // ---- The settings live on the service, where the panel pushes them. They are
  //      the same for every device — a threshold is about you, not about a
  //      headset — and they are read through here so the bindings below need not
  //      say `service ?` twice a line.
  readonly property bool useFastPair: service ? service.useFastPair : true
  readonly property bool useModeControl: service ? service.useModeControl : true
  readonly property int lowThreshold: service ? service.lowThreshold : 20
  readonly property bool notifyLow: service ? service.notifyLow : true

  // ---- What this device's lines from the service's Fast Pair reader said.
  property var reading: ({})
  // Set while this device's channel is being cycled on purpose, so the rows do
  // not blank while the reader drops it and opens it again.
  property bool refreshing: false
  property real readingStamp: 0
  // What this device's own lines complained about. The reader failing as a
  // whole is the service's to report, and it arrives through readerError below.
  property string readerErrorRaw: ""
  readonly property bool readerRunning: service ? service.readerRunning : false
  readonly property string serviceReaderError: service ? service.readerError : ""
  // With Fast Pair off the reader never runs, and a message left over from when
  // it did would be read as a live fault. A reader that could not start at all
  // is shown by every device it was meant to serve, because it is every one of
  // their reasons for having no per-earbud levels.
  readonly property string readerError: !useFastPair
    ? ""
    : (readerErrorRaw !== "" ? readerErrorRaw : serviceReaderError)

  // No live reader means no stream, whatever the last line said: a reader that was
  // killed rather than closed leaves its last reading behind, and showing stale
  // per-earbud levels as current is worse than falling back to BlueZ. A refresh is
  // the exception — the channel is being dropped on purpose, and blanking the rows
  // for that second would flash BlueZ's single "Battery" row in their place.
  readonly property bool streaming: reading.stream === true
    && (readerRunning || refreshing)

  readonly property int leftLevel: streaming ? Model.readerLevel(reading, "left") : -1
  readonly property int rightLevel: streaming ? Model.readerLevel(reading, "right") : -1
  readonly property int caseLevel: streaming ? Model.readerLevel(reading, "case") : -1
  readonly property bool leftCharging: streaming && reading.leftCharging === true
  readonly property bool rightCharging: streaming && reading.rightCharging === true
  readonly property bool caseCharging: streaming && reading.caseCharging === true
  readonly property bool perBud: leftLevel >= 0 || rightLevel >= 0

  // A set with one battery for the whole thing — an over-ear headset, mostly.
  // It is its own shape, not a pair with one bud missing: there is no side to
  // name and no case to report, so the panel draws one row and the bar fills
  // both halves of the mark with the same figure. `perBud` deliberately stays
  // false here, because there are no buds to compare.
  readonly property bool single: streaming && reading.single === true
  readonly property int singleLevel: single ? Model.readerLevel(reading, "battery") : -1
  readonly property bool singleCharging: single && reading.batteryCharging === true

  readonly property string modelId: String(reading.modelId || "")
  readonly property string bleAddress: String(reading.bleAddress || "")

  // ---- Listening mode. Three devices, three protocols, one piece of state: the
  //      panel shows a mode and writes a mode, and which helper carries it is
  //      decided per device from the UUIDs in its SDP record.
  //
  //        sony-bridge    Sony's MDR protocol v2, over an RFCOMM channel the
  //                       headset itself serves. Deterministic: a device that
  //                       advertises the UUID speaks the protocol, so this path
  //                       needs no Fast Pair, no rotating address and no cache of
  //                       which models answered.
  //        xiaomi-bridge  Compact GAIA on standard SPP. The CSR GAIA UUID in
  //                       the SDP record is the claim; the socket is SPP. Same
  //                       lifecycle as Sony: Classic address, no Fast Pair.
  //        jbl-bridge     JBL's BLE GATT service, on the earbuds' BLE side at an
  //                       address that rotates and is announced only on the
  //                       Message Stream — so that path needs the reader, and is
  //                       unreachable without it.
  //
  //      Either way exactly one process owns the link, because writes and the
  //      device's own notifications (a mode changed by touching the earbud) must
  //      share one connection; this follower talks to it through its stdin, and
  //      the bridges report on the same contract into the same state.
  readonly property string jblBridgePath: Qt.resolvedUrl("jbl-bridge").toString().replace(/^file:\/\//, "")
  readonly property string sonyBridgePath: Qt.resolvedUrl("sony-bridge").toString().replace(/^file:\/\//, "")
  readonly property string xiaomiBridgePath: Qt.resolvedUrl("xiaomi-bridge").toString().replace(/^file:\/\//, "")
  readonly property string soundcoreBridgePath: Qt.resolvedUrl("soundcore-bridge").toString().replace(/^file:\/\//, "")
  property var ancState: ({})
  property bool ancEnabled: true
  readonly property bool jblWanted: useModeControl && useFastPair && ancEnabled && connected
    && controlBackend === "jbl"
    && bleAddress !== ""
    && modeSupportKnown !== 0
    && !ancModelParked
  property bool jblArmed: false
  onJblWantedChanged: {
    if (!jblWanted) { jblArmed = false; return }
    Qt.callLater(function () { jblArmed = follower.jblWanted })
  }
  property bool ancRestartWanted: false
  property bool ancAnswered: false
  property string ancRunError: ""
  property string ancErrorRaw: ""
  property bool sonyEnabled: true
  property bool xiaomiEnabled: true
  property bool soundcoreEnabled: true

  // What this device serves, read once per connection with `bluetoothctl info`.
  // Empty while it is not connected, or while the probe is still out.
  property var deviceUuids: []
  readonly property string controlBackend: Model.controlBackend(deviceUuids, bleAddress)

  readonly property bool ancSupported: ancState.modes === true
  readonly property string ancMode: String(ancState.mode || "")
  // Which modes this device offers, in the order the panel draws them. The JBL
  // bridge names none and means all four; the Sony bridge lists what the headset
  // has, which for an over-ear WH is Off / NC / Ambient and no TalkThru.
  readonly property var modesAvailable: Model.modesAvailable(ancState)
  // Ambient detail, Sony only: how much of the room comes through (0-20) and
  // whether voices are lifted out of it. -1 and false mean "not said".
  readonly property int ambientLevel: typeof ancState.level === "number" ? ancState.level : -1
  readonly property bool ambientVoice: ancState.voice === true
  // Whether this device has the two Ambient extras at all, which is decided by
  // the bridge that answered rather than by a name: only the Sony one reports a
  // level, and a JBL pair's Ambient Aware is a mode with no amount to it. The
  // panel draws the dial and the voice switch on this, and nothing on a device
  // that never mentioned either.
  readonly property bool ambientControls: ancLive && ambientLevel >= 0

  // Whichever bridge this device calls for. They are exclusive — the backend is
  // one string — so this is "the bridge", not "either of two links".
  readonly property bool bridgeRunning: ancBridge.running || sonyBridge.running || xiaomiBridge.running || soundcoreBridge.running
  // The bridge is up and the device has answered on it, which is the only state
  // in which a write has somewhere to land.
  readonly property bool ancLive: bridgeRunning && ancAnswered
  // Why the listening-mode row is not there. Blank while the row is simply
  // switched off, because that needs no explaining.
  readonly property string ancError: {
    if (!useModeControl) return ""
    // Only the JBL path goes through the Message Stream. Sony, Xiaomi and Soundcore serve
    // their own Classic channels and do not care whether Fast Pair is on.
    if (controlBackend !== "sony" && controlBackend !== "xiaomi" && controlBackend !== "soundcore" && !useFastPair)
      return "needs Fast Pair for the BLE address"
    return ancErrorRaw
  }

  // The caches these read from are the service's, because they outlive any one
  // follower: which models answered before, which have failed for good in this
  // session, and how long to wait before asking again.
  readonly property int modeSupportKnown: Model.supportVerdict(service ? service.modeSupport : ({}), modelId)
  readonly property bool ancModelParked: service ? service.ancParked[modelId] === true : false
  readonly property bool addressParked: service ? service.sonyParked[address] === true : false
  readonly property bool sonyAddressParked: addressParked
  // How long to wait before the next attempt, keyed by whatever identifies the
  // device for the backend in play — the Fast Pair model for the JBL bridge, the
  // Classic address for Sony, Xiaomi and Soundcore.
  readonly property string ancBackoffKey: (controlBackend === "sony" || controlBackend === "xiaomi" || controlBackend === "soundcore")
    ? address : modelId

  readonly property int bluezLevel: Model.batteryLevel(device)
  // The bar carries one number: the headset's own figure where there is only
  // one, otherwise the earbud that dies first, or BlueZ's rounded single figure
  // when the Message Stream has said nothing.
  readonly property int level: singleLevel >= 0
    ? singleLevel
    : (perBud ? Model.lowestBud(leftLevel, rightLevel) : bluezLevel)
  readonly property bool charging: leftCharging || rightCharging || singleCharging
  readonly property bool low: connected && level >= 0 && level <= lowThreshold && !charging

  readonly property var summary: ({
    hasDevice: follower.hasDevice, connected: follower.connected, name: follower.name,
    level: follower.level, left: follower.leftLevel, right: follower.rightLevel,
    caseLevel: follower.caseLevel,
    single: follower.single, singleLevel: follower.singleLevel
  })

  // The earbuds announce on connect and when a level changes, and docking an
  // earbud is neither: park one in the case and its last level stands until
  // something asks again. Opening the panel is when someone wants the truth, so a
  // reading older than half a minute is refreshed then — which keeps the promise
  // that nothing is polled while nobody is looking.
  readonly property int stalerThanMs: 30000

  // ---- Warning state. The last level seen, and which source said it: the
  //      Message Stream's per-earbud minimum and BlueZ's rounded single figure
  //      are different measurements, and reading one after the other as a drop
  //      warns about arithmetic rather than about the battery. A level from a
  //      different source than the last one is therefore compared with nothing.
  //      `primed` absorbs the first level of the session so a shell restart with
  //      already-low earbuds stays quiet, while a connect that this follower
  //      witnesses arms the warning again — that one is news.
  property string lastSource: ""
  property int lastLevel: -1
  property bool primed: false
  property bool sawDisconnected: false

  // Warned about already, and remembered across a reload by the service, which
  // keeps one flag per address: two headsets draining at once are two warnings,
  // and one of them being silenced must not silence the other.
  readonly property bool notifiedLow: service && service.notifiedLow
    ? service.notifiedLow[address] === true : false
  function setNotifiedLow(value) {
    if (service) service.setNotifiedLow(address, value)
  }

  // What one line said for itself, as an object with only the keys that line
  // carried. Junk, an array or a blank line carried nothing. The merged state
  // cannot answer this: it keeps the keys earlier lines set, so the three-key
  // {address, stream, error} line the reader writes when the channel goes down
  // would look like it had brought a fresh left and right along with it.
  function readerLineFields(line) {
    var parsed = null
    try {
      parsed = JSON.parse(String(line || "").trim() || "{}")
    } catch (e) {
      return ({})
    }
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return ({})
    return parsed
  }

  // One line of the reader's stdout that named this device. Called by the
  // service, which owns the process and routes by the line's `address`; a
  // follower never sees another device's lines and so cannot mix them up.
  function applyReaderLine(line) {
    var incoming = readerLineFields(line)
    var next = Model.mergeReaderLine(reading, line)
    reading = next
    if (next.stream === false) readerErrorRaw = String(next.error || "")
    else readerErrorRaw = ""
    // Only a line that carried a level is a reading: the stamp is how old the
    // levels on screen are, and a refresh is over when new ones arrive, not
    // when the reader says something else about itself.
    if (incoming.left !== undefined || incoming.right !== undefined
        || incoming.battery !== undefined) {
      readingStamp = Date.now()
      refreshing = false
    }
  }

  // One JSON line from whichever bridge is running. The mode is whatever the
  // line says — a bridge reports its device's whole state on every change — but
  // the three keys only the Sony bridge sends carry forward when a line omits
  // them: the JBL bridge's {"modes", "mode"} lines say nothing about an ambient
  // level, and reading that silence as "unknown" would blank a level the device
  // never changed.
  function applyAncLine(line) {
    var parsed = null
    try {
      parsed = JSON.parse(String(line || "").trim() || "{}")
    } catch (e) {
      return
    }
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) return
    var carried = ["available", "level", "voice"]
    for (var i = 0; i < carried.length; i++) {
      var key = carried[i]
      if (parsed[key] === undefined && ancState[key] !== undefined) parsed[key] = ancState[key]
    }
    ancState = parsed
    if (parsed.modes === true) {
      ancAnswered = true
      ancErrorRaw = ""
      if (service) service.resetAncBackoff(ancBackoffKey)
    } else if (parsed.error !== undefined) {
      ancRunError = String(parsed.error || "")
      ancErrorRaw = ancRunError
    }
  }

  // What this device serves, from its SDP record. Quickshell.Bluetooth exposes
  // no uuids property, and the list does not change while a device stays
  // connected, so it is read once per connection with the tool that prints it
  // rather than watched. One probe at a time, and no need to check whose answer
  // came back: this follower asks about one address and no other.
  function probeUuids() {
    if (!connected || address === "") {
      deviceUuids = []
      return
    }
    if (uuidProbe.running) return
    uuidProbe.command = ["bluetoothctl", "info", address]
    uuidProbe.running = true
  }

  // Refresh means "ask the earbuds for a fresh battery reading". The device
  // pushes a reading when a level changes, so there is nothing to poll: dropping
  // the channel and letting it re-announce is the only way to ask for a figure
  // the device considers unchanged. The BLE address and the model id are not
  // readings — they identify the device — and dropping them would tear down the
  // listening-mode link for no reason, so they survive. Nothing else is cleared
  // either: the levels on screen stay until fresh ones replace them, because a
  // refresh that blanks the panel first is a refresh that looks like a fault.
  function refresh() {
    if (!connected) return
    readerErrorRaw = ""
    // `r` is also the way past a mode bridge's backoff: a helper that failed
    // because a package was missing is retried on a pause that reaches five
    // minutes, and the person who just installed the package should not wait
    // for it. Forget the pause, let the bridge start now.
    if (service) {
      service.resetAncBackoff(modelId)
      service.resetAncBackoff(address)
    }
    if (ancRestart.running) { ancRestart.stop(); ancEnabled = true }
    if (sonyRestart.running) { sonyRestart.stop(); sonyEnabled = true }
    if (xiaomiRestart.running) { xiaomiRestart.stop(); xiaomiEnabled = true }
    if (soundcoreRestart.running) { soundcoreRestart.stop(); soundcoreEnabled = true }
    if (!useFastPair || !service) return
    // The service cycles this device's channel and leaves every other device's
    // alone; it says whether the request went out at all, because a reader that
    // is between attempts has nothing to drop, and holding the rows on screen
    // for an answer that is not coming is worse than falling back to BlueZ.
    if (service.refreshReader(address)) {
      refreshing = true
      refreshGuard.restart()
    }
  }

  // A fresh run of the shared reader starts every device with a clean slate:
  // whatever the run that died complained about is not about this one.
  function clearReaderError() {
    readerErrorRaw = ""
  }

  function refreshIfStale() {
    if (!connected) return
    if (readingStamp === 0 || Date.now() - readingStamp > stalerThanMs) refresh()
  }

  // True only when the write actually went out, so callers can say "unavailable"
  // rather than pretend the device was told. A mode this device does not offer
  // is not a write: the Sony over-ear has no TalkThru, and sending one would be
  // a command the headset answers by doing nothing.
  function setAncMode(mode) {
    if (!ancSupported || !ancLive) return false
    if (modesAvailable.indexOf(String(mode)) === -1) return false
    if (sonyBridge.running) sonyBridge.write("set " + mode + "\n")
    else if (xiaomiBridge.running) xiaomiBridge.write("set " + mode + "\n")
    else if (soundcoreBridge.running) soundcoreBridge.write("set " + mode + "\n")
    else ancBridge.write("set " + mode + "\n")
    return true
  }

  // How much of the room comes through in Ambient, 0-20. Sony only — the JBL
  // protocol has one Ambient Aware and no dial. The bridge switches the headset
  // to ambient as part of it, because the level is stored only by a set that
  // carries it: sending a level while Noise Cancelling is on changes nothing.
  function setAmbientLevel(value) {
    if (!ancLive) return false
    if (sonyBridge.running) {
      var level = Math.max(0, Math.min(20, Math.round(Number(value))))
      if (!isFinite(level)) return false
      sonyBridge.write("level " + level + "\n")
      return true
    }
    if (soundcoreBridge.running) {
      var scLevel = Math.max(1, Math.min(5, Math.round(Number(value))))
      if (!isFinite(scLevel)) return false
      soundcoreBridge.write("level " + scLevel + "\n")
      return true
    }
    return false
  }

  // Focus on Voice (Sony) / Wind Noise Reduction (Soundcore)
  function setAmbientVoice(on) {
    if (!ancLive) return false
    if (sonyBridge.running) {
      sonyBridge.write("voice " + (on ? "on" : "off") + "\n")
      return true
    }
    if (soundcoreBridge.running) {
      soundcoreBridge.write("wind " + (on ? "on" : "off") + "\n")
      return true
    }
    return false
  }

  // Cycle a helper now rather than after its failure backoff: the reason is a
  // deliberate one (a refresh, a rotated BLE address), and waiting eight seconds
  // to follow it would look like the widget had stopped working.
  function bounceAncBridge() {
    if (ancBridge.running) {
      ancRestartWanted = true
      ancEnabled = false
      return
    }
    ancRestart.stop()
    ancEnabled = true
  }

  // Warn once per drain. The flag clears with 5 points of hysteresis so a level
  // wobbling across the threshold cannot warn twice.
  function checkLowBattery() {
    if (!notifyLow) return
    if (!connected) {
      setNotifiedLow(false)
      forgetLevelHistory()
      return
    }
    // No number is not a good number: a reader restarting drops the level to -1
    // for a second, and re-arming the warning there would send it twice for one
    // drain. The warning state survives the gap.
    if (level < 0) return

    // Compare like with like, or with nothing at all. A single-battery headset
    // is a third source, not a variety of either: its own figure and BlueZ's
    // rounded one describe the same battery through different instruments, and
    // a reader coming up would otherwise read as a drop from 100 to 90.
    var source = single ? "single" : (perBud ? "bud" : "bluez")
    var previous = source === lastSource ? lastLevel : -1
    lastSource = source
    lastLevel = level

    if (level >= lowThreshold + 5 || charging) setNotifiedLow(false)
    if (charging) return

    // The first level of the session is whatever the shell woke up to. It is a
    // baseline, not an event: earbuds that were already low before the shell
    // started are not news, and a restart must not warn about them again.
    if (!primed) {
      primed = true
      return
    }

    if (level > lowThreshold || notifiedLow) return
    var dropped = previous >= 0 && level < previous
    var firstSinceConnect = previous < 0
    if (!dropped && !firstSinceConnect) return

    setNotifiedLow(true)
    // Sent a turn later, not here. `level` is the lowest earbud, so it changes
    // as soon as one of them does, and reading the pair straight away can catch
    // the other one at its previous value — a warning that says "L 15% · R 40%"
    // when the line that triggered it said 15 and 8.
    Qt.callLater(sendLowBatteryWarning)
  }

  // Through the service, which owns the one notification process: two headsets
  // going flat in the same minute are two notifications, one after the other,
  // rather than one of them lost to a process that was already busy.
  function sendLowBatteryWarning() {
    if (!connected || level < 0 || !service) return
    service.notify(follower.name + " battery low", Model.lowBatteryBody(follower.summary))
  }

  function forgetLevelHistory() {
    lastSource = ""
    lastLevel = -1
  }

  onLevelChanged: checkLowBattery()
  onChargingChanged: checkLowBattery()
  onLowThresholdChanged: checkLowBattery()

  // A device that this follower has seen sitting disconnected and then watched
  // connect is a real connect, and its first level is worth warning about. A
  // device that was already connected when the shell started merely appears,
  // and `primed` absorbs what it says.
  onConnectedChanged: {
    if (connected && address !== "" && service) service.rememberAddress(address)
    if (connected && sawDisconnected) primed = true
    if (!connected) {
      if (hasDevice) sawDisconnected = true
      setNotifiedLow(false)
      forgetLevelHistory()
      reading = ({})
      readingStamp = 0
      readerErrorRaw = ""
      ancState = ({})
      ancAnswered = false
      // What the device serves is only known while it is here to be asked, and a
      // list left behind would keep a bridge armed for a device in its case.
      deviceUuids = []
    }
    if (connected) probeUuids()
    checkLowBattery()
  }

  onHasDeviceChanged: if (hasDevice && !connected) sawDisconnected = true

  // A follower is built for a device that is connected already, most of the
  // time, and that fires neither handler above — both are changes, and there was
  // no change.
  Component.onCompleted: {
    if (connected && address !== "" && service) service.rememberAddress(address)
    probeUuids()
    checkLowBattery()
  }

  // A refresh that never lands must not hold the per-earbud rows on screen for
  // ever: after this long the channel is treated as gone and BlueZ's figure
  // takes over again.
  Timer {
    id: refreshGuard
    interval: 12000
    repeat: false
    onTriggered: follower.refreshing = false
  }

  // Lives only while the earbuds are connected and a BLE address is known. It
  // holds an open BLE link, which is not free for the earbuds' battery, so it
  // follows the same lifecycle as the Message Stream reader rather than running
  // forever. The address comes from that reader, so Fast Pair off means no mode
  // control at all.
  Process {
    id: ancBridge
    // `running` goes through jblArmed rather than straight off the conditions:
    // `command` and the conditions both depend on bleAddress, and QML does not
    // promise which binding settles first — seen live, the bridge started with
    // an empty address, exited 4 and parked a working model for the session.
    // One turn of the event loop later every binding has caught up.
    running: follower.jblArmed
    command: [follower.jblBridgePath, follower.bleAddress, follower.modelId]
    stdinEnabled: true
    stdout: SplitParser {
      onRead: function(line) { follower.applyAncLine(line) }
    }
    stderr: StdioCollector { id: ancStderr; waitForEnd: true }
    // No bridge, no mode: a link that was killed (a rotated address, the setting
    // switched off) leaves its last report behind, and a LISTENING MODE row that
    // no longer controls anything is worse than no row.
    onRunningChanged: {
      if (running) {
        follower.ancRunError = ""
        follower.ancErrorRaw = ""
      }
      follower.ancState = ({})
      follower.ancAnswered = false
    }
    onExited: function(exitCode, exitStatus) {
      // 0 clean stop · 1 transient, retry with a growing pause · 3 linked but
      // silent, which the bridge has already written into mode-support.json ·
      // 4 the bridge could not start at all.
      //
      // Parking is per model, so it needs one: a bridge that exits before the
      // reader has named the model has nothing to remember this against. Only
      // exit 3 parks: it says something about the earbuds. Exit 4 says
      // something about this machine — a package missing — and once that is
      // installed the row should come back on its own, so it backs off like a
      // dropped link instead, with its message left on screen meanwhile.
      if (exitCode === 3 && follower.modelId !== "" && follower.service)
        follower.service.parkModel(follower.modelId)
      // A device that connected and said nothing is not a fault, and the model
      // is parked now, so the row is gone for good rather than pending. Saying
      // so in the panel would be complaining that earbuds lack a feature they
      // never claimed — they say nothing, and so do we.
      if (exitCode === 3) {
        follower.ancRunError = ""
        follower.ancErrorRaw = ""
      } else if (exitCode !== 0 && follower.ancRunError === "") {
        follower.ancErrorRaw = Model.shortError(ancStderr.text, exitCode === 4
          ? "the listening-mode bridge could not start"
          : "the listening-mode link dropped (exit " + exitCode + ")")
      }

      var deliberate = follower.ancRestartWanted
      follower.ancRestartWanted = false
      follower.ancEnabled = false
      ancRestart.interval = deliberate ? 600
        : (follower.service ? follower.service.ancBackoffFor(follower.modelId) : 10000)
      if (!deliberate && (exitCode === 1 || exitCode === 4) && follower.service)
        follower.service.bumpAncBackoff(follower.modelId)
      ancRestart.restart()
    }
  }

  // Both bridge restart timers take their interval from the exit that scheduled
  // them: a deliberate cycle waits a moment, a failure waits out its backoff.
  Timer {
    id: ancRestart
    repeat: false
    onTriggered: follower.ancEnabled = true
  }

  // Lives only while a Sony headset is connected. Nothing else gates it: the
  // channel is the headset's own, so there is no BLE address to wait for, no
  // Fast Pair to depend on and no cache to consult — the SDP UUID already said
  // this device speaks the protocol. The one reason not to run is that this
  // address has already failed for good in this session.
  Process {
    id: sonyBridge
    running: follower.useModeControl && follower.sonyEnabled && follower.connected
      && follower.controlBackend === "sony"
      && !follower.sonyAddressParked
    command: [follower.sonyBridgePath, follower.address]
    stdinEnabled: true
    stdout: SplitParser {
      onRead: function(line) { follower.applyAncLine(line) }
    }
    stderr: StdioCollector { id: sonyStderr; waitForEnd: true }
    // No bridge, no mode, the same as the JBL one: a link that was killed leaves
    // its last report behind, and a LISTENING MODE row that no longer controls
    // anything is worse than no row.
    onRunningChanged: {
      if (running) {
        follower.ancRunError = ""
        follower.ancErrorRaw = ""
      }
      follower.ancState = ({})
      follower.ancAnswered = false
    }
    onExited: function(exitCode, exitStatus) {
      // The same four codes jbl-bridge uses: 0 clean stop · 1 transient, retry
      // with a growing pause · 3 linked but silent to every query type it knows
      // · 4 could not start at all. Both of the last two are about this headset
      // rather than about this moment, so the address is parked for the session.
      // Nothing is written to disk: the SDP UUID makes the next session's
      // decision for free, and a headset that gains the feature in a firmware
      // update should not have to argue with a cache.
      //
      // The address is this follower's own, which is why the old service had to
      // remember which one a run was pointed at and this does not.
      // Exit 3 parks (the headset answered none of the query types); exit 4 is
      // this machine's problem and backs off instead, message on screen.
      if (exitCode === 3 && follower.service)
        follower.service.parkAddress(follower.address)
      // A device that linked and said nothing is not a fault to report — the
      // same silence the JBL side treats as "this model does not do this".
      if (exitCode === 3) {
        follower.ancRunError = ""
        follower.ancErrorRaw = ""
      } else if (exitCode !== 0 && follower.ancRunError === "") {
        follower.ancErrorRaw = Model.shortError(sonyStderr.text, exitCode === 4
          ? "the listening-mode bridge could not start"
          : "the listening-mode link dropped (exit " + exitCode + ")")
      }

      // Nothing cycles this bridge on purpose: the channel is the headset's own
      // and its address is this follower's, so there is no rotated address to
      // follow and no re-aiming to do. Every exit waits out its backoff.
      follower.sonyEnabled = false
      sonyRestart.interval = follower.service
        ? follower.service.ancBackoffFor(follower.address) : 10000
      if ((exitCode === 1 || exitCode === 4) && follower.service)
        follower.service.bumpAncBackoff(follower.address)
      sonyRestart.restart()
    }
  }

  Timer {
    id: sonyRestart
    repeat: false
    onTriggered: follower.sonyEnabled = true
  }

  // Lives only while Xiaomi / QCC buds that advertise CSR GAIA are connected.
  // Same gates as Sony: the channel is Classic SPP, so there is no BLE address
  // to wait for and no Fast Pair to depend on. An address that already failed
  // for good this session is parked on the same map Sony uses.
  Process {
    id: xiaomiBridge
    running: follower.useModeControl && follower.xiaomiEnabled && follower.connected
      && follower.controlBackend === "xiaomi"
      && !follower.addressParked
    command: [follower.xiaomiBridgePath, follower.address]
    stdinEnabled: true
    stdout: SplitParser {
      onRead: function(line) { follower.applyAncLine(line) }
    }
    stderr: StdioCollector { id: xiaomiStderr; waitForEnd: true }
    onRunningChanged: {
      if (running) {
        follower.ancRunError = ""
        follower.ancErrorRaw = ""
      }
      follower.ancState = ({})
      follower.ancAnswered = false
    }
    onExited: function(exitCode, exitStatus) {
      if (exitCode === 3 && follower.service)
        follower.service.parkAddress(follower.address)
      if (exitCode === 3) {
        follower.ancRunError = ""
        follower.ancErrorRaw = ""
      } else if (exitCode !== 0 && follower.ancRunError === "") {
        follower.ancErrorRaw = Model.shortError(xiaomiStderr.text, exitCode === 4
          ? "the listening-mode bridge could not start"
          : "the listening-mode link dropped (exit " + exitCode + ")")
      }

      follower.xiaomiEnabled = false
      xiaomiRestart.interval = follower.service
        ? follower.service.ancBackoffFor(follower.address) : 10000
      if ((exitCode === 1 || exitCode === 4) && follower.service)
        follower.service.bumpAncBackoff(follower.address)
      xiaomiRestart.restart()
    }
  }

  Timer {
    id: xiaomiRestart
    repeat: false
    onTriggered: follower.xiaomiEnabled = true
  }

  // Lives only while Soundcore headphones are connected.
  // Same gates as Sony/Xiaomi: Classic RFCOMM, so there is no BLE address to wait for
  // and no Fast Pair to depend on. An address that already failed for good this
  // session is parked on the same map Sony and Xiaomi use.
  Process {
    id: soundcoreBridge
    running: follower.useModeControl && follower.soundcoreEnabled && follower.connected
      && follower.controlBackend === "soundcore"
      && !follower.addressParked
    command: [follower.soundcoreBridgePath, follower.address]
    stdinEnabled: true
    stdout: SplitParser {
      onRead: function(line) { follower.applyAncLine(line) }
    }
    stderr: StdioCollector { id: soundcoreStderr; waitForEnd: true }
    onRunningChanged: {
      if (running) {
        follower.ancRunError = ""
        follower.ancErrorRaw = ""
      }
      follower.ancState = ({})
      follower.ancAnswered = false
    }
    onExited: function(exitCode, exitStatus) {
      if (exitCode === 3 && follower.service)
        follower.service.parkAddress(follower.address)
      if (exitCode === 3) {
        follower.ancRunError = ""
        follower.ancErrorRaw = ""
      } else if (exitCode !== 0 && follower.ancRunError === "") {
        follower.ancErrorRaw = Model.shortError(soundcoreStderr.text, exitCode === 4
          ? "the listening-mode bridge could not start"
          : "the listening-mode link dropped (exit " + exitCode + ")")
      }

      follower.soundcoreEnabled = false
      soundcoreRestart.interval = follower.service
        ? follower.service.ancBackoffFor(follower.address) : 10000
      if ((exitCode === 1 || exitCode === 4) && follower.service)
        follower.service.bumpAncBackoff(follower.address)
      soundcoreRestart.restart()
    }
  }

  Timer {
    id: soundcoreRestart
    repeat: false
    onTriggered: follower.soundcoreEnabled = true
  }

  // Reads the device's SDP UUIDs, which is how the backend is chosen. Started by
  // probeUuids() rather than by a `running` binding: this process exits as soon
  // as it has printed, and a binding that is still true at that moment is an
  // invitation to run it again for ever.
  Process {
    id: uuidProbe
    stdout: StdioCollector { id: uuidProbeOut; waitForEnd: true }
    onExited: function(exitCode, exitStatus) {
      // A probe that failed says nothing about the device, and an empty list is
      // exactly that: no Sony or GAIA UUID seen, so a Fast Pair BLE address decides.
      follower.deviceUuids = exitCode === 0
        ? Model.uuidsFromBluetoothctl(uuidProbeOut.text)
        : []
    }
  }

  // The BLE address rotates. When the Message Stream reports a new one the old
  // link is stale, so the bridge is restarted against the new address.
  onBleAddressChanged: if (bleAddress !== "") bounceAncBridge()
}
