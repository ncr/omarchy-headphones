import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Earbuds battery on the bar, per earbud and for the case.
//
// This is the view. Everything that talks to the earbuds — the device pick, the
// Fast Pair reader, the BLE bridge, the low-battery warning — lives in
// Service.qml, which the shell loads once for the session. A bar surface exists
// per monitor, so this file is built once per screen and each copy reads the
// same service and pushes the widget's settings into it.
//
// One widget, one icon per device the service follows. With one set connected
// that is one icon and everything below reads as it always did; with a pair of
// earbuds and a headset connected at once it is two, side by side in one bar
// entry, each drawn from its own device's levels. Clicking an icon opens the
// popup for that device, and , and . walk between them once the popup is up.
//
// Connect, disconnect and forget live in the Bluetooth panel; volume and output
// device in the Audio panel. b and v walk to them.
Panel {
  id: root
  moduleName: "io.github.ncr.omaphones"
  // The "omaphones" IPC target belongs to Service.qml, which registers it once for
  // the session: this file is built once per monitor, and a handler here would
  // claim the same name on every screen. manageIpc: false keeps the base panel
  // from opening one; the service opens and closes this widget through the
  // shell, which finds whichever bar is showing it.
  manageIpc: false

  // Defaults must match manifest.json's barWidget.defaults and the fallbacks in
  // Service.qml: an entry in shell.json with no keys of its own falls through to
  // the value written here, and a service nobody has pushed settings into yet
  // must behave the same way.
  readonly property string deviceMatch: setting("deviceMatch", "")
  // Clamped to the range the settings form offers, so a hand-edited shell.json
  // cannot ask for a threshold the widget was never designed around.
  readonly property int lowThreshold: Math.max(5, Math.min(50,
    Model.asInt(setting("lowBatteryThreshold", 20), 20)))
  readonly property bool showPercentage: Model.asBool(setting("showPercentage", false), false)
  readonly property bool hideWhenDisconnected: Model.asBool(setting("hideWhenDisconnected", true), true)
  readonly property bool notifyLowBattery: Model.asBool(setting("notifyLowBattery", true), true)
  readonly property bool useFastPair: Model.asBool(setting("useFastPair", true), true)
  readonly property bool useModeControl: Model.asBool(setting("useModeControl", true), true)

  // The one instance of the plugin's service, shared by every monitor's copy of
  // this widget. Null for the moment between the bar loading and the service
  // being constructed, and while the plugin is disabled.
  readonly property var service: bar && bar.shell ? bar.shell.serviceFor("io.github.ncr.omaphones") : null

  // Every device the service follows, in the order it draws them: one icon each.
  readonly property var followed: service ? service.followed : []
  readonly property bool anyConnected: {
    for (var i = 0; i < followed.length; i++)
      if (followed[i].connected) return true
    return false
  }

  // The device the popup is about. `chosen` is the one whose icon was clicked,
  // or walked to with , and . — and it is only a preference: a device that has
  // gone (unplugged, out of range, filtered away by a changed deviceMatch)
  // leaves the popup on the first icon rather than on nothing at all.
  property var chosen: null
  readonly property var current: followed.indexOf(chosen) !== -1
    ? chosen
    : (followed.length > 0 ? followed[0] : null)

  // The icon the popup hangs under, claimed by whichever mark is drawing
  // `current`. Null until the marks exist, and again if the one that was
  // claiming it is destroyed, in which case the popup falls back to the whole
  // widget — which is where a single-icon widget's popup sat anyway.
  property Item currentAnchor: null

  readonly property bool hasDevice: current ? current.hasDevice : false
  readonly property bool connected: current ? current.connected : false
  readonly property string deviceName: current ? current.name : ""

  readonly property int leftLevel: current ? current.leftLevel : -1
  readonly property int rightLevel: current ? current.rightLevel : -1
  readonly property int caseLevel: current ? current.caseLevel : -1
  readonly property bool leftCharging: current ? current.leftCharging : false
  readonly property bool rightCharging: current ? current.rightCharging : false
  readonly property bool caseCharging: current ? current.caseCharging : false
  readonly property bool perBud: current ? current.perBud : false
  // One battery for the whole headset: one row instead of three, and both
  // halves of the bar mark filled from the same figure.
  readonly property bool single: current ? current.single : false
  readonly property int singleLevel: current ? current.singleLevel : -1
  readonly property bool singleCharging: current ? current.singleCharging : false
  readonly property int bluezLevel: current ? current.bluezLevel : -1
  readonly property int level: current ? current.level : -1
  readonly property bool low: current ? current.low : false
  readonly property string readerError: current ? current.readerError : ""

  readonly property bool ancSupported: current ? current.ancSupported : false
  readonly property string ancMode: current ? current.ancMode : ""
  readonly property string ancError: current ? current.ancError : ""
  // Which modes this device actually offers, as its bridge reported them. A JBL
  // pair offers all four; a Sony over-ear has no TalkThru.
  readonly property var modesAvailable: current ? current.modesAvailable : []
  // Ambient detail, Sony only: how much of the room comes through, 0-20, and
  // whether voices are lifted out of it. `ambientControls` is the follower's
  // answer to "did the running bridge report a level", which is the only thing
  // that distinguishes a device with a dial from one without.
  readonly property int ambientLevel: current ? current.ambientLevel : -1
  readonly property bool ambientVoice: current ? current.ambientVoice : false
  readonly property bool ambientControls: current ? current.ambientControls : false
  // The row is a control, so it appears only when there is something to control:
  // the setting is on, the device has answered for its listening mode, and at
  // least one of the modes it named is one this panel knows how to draw.
  readonly property bool modeRowVisible: useModeControl && ancSupported && ancOptions.length > 0
  // The dial and the voice switch belong to Ambient, and to a device that has
  // them at all: a JBL pair's Ambient Aware is a mode with no amount to it, and
  // on a Sony the level is stored with the ambient setting — a dial drawn next
  // to Noise Cancelling would move a number nothing is listening to.
  readonly property bool ambientRowVisible: modeRowVisible && ambientControls && ancMode === "ambient"

  // The level waiting on the debounce below, and -1 with nothing waiting.
  property int pendingAmbientLevel: -1
  // The level last asked for, until the headset says it happened, and what the
  // slider draws in the meantime. It has to be kept: PanelSlider drops its own
  // live position the moment the button comes up, and the headset's report is
  // half a second behind, so the knob would snap back to the old figure and
  // then forward again on every drag. Also what a second key press steps off,
  // so holding ] walks up the dial rather than stepping off a figure the
  // headset has not caught up with.
  property int askedAmbientLevel: -1

  readonly property var summary: current ? current.summary : ({
    hasDevice: false, connected: false, name: "",
    level: -1, left: -1, right: -1, caseLevel: -1,
    single: false, singleLevel: -1
  })

  // Every followed device, one line each, because the icons are next to one
  // another and a tooltip that named only the one under the pointer would make
  // you hover them in turn to read the desk.
  readonly property string tooltipText: {
    if (followed.length === 0) return Model.tooltip(root.summary)
    var lines = []
    for (var i = 0; i < followed.length; i++) lines.push(Model.tooltip(followed[i].summary))
    return lines.join("\n")
  }

  // Every mode this panel can draw, in the fixed order it draws them, each with
  // the key that reaches it. The list is the same for every device; which of
  // them are offered is not.
  readonly property var allAncOptions: [
    { value: "off", key: "o", label: "Off", tooltip: "No noise control" },
    { value: "anc", key: "n", label: "ANC", tooltip: "Noise Cancelling" },
    { value: "ambient", key: "a", label: "Ambient", tooltip: "Ambient Aware" },
    { value: "talkthru", key: "t", label: "TalkThru", tooltip: "TalkThru" }
  ]

  // What this device offers, in that order. A button for a mode the device will
  // not take is a button that does nothing, and its key would be a key that
  // silently fails — so both come from the same filtered list, and so does the
  // hint line that tells you which keys there are.
  readonly property var ancOptions: {
    var out = []
    for (var i = 0; i < allAncOptions.length; i++)
      if (modesAvailable.indexOf(allAncOptions[i].value) !== -1) out.push(allAncOptions[i])
    return out
  }

  readonly property string ancHint: {
    var parts = []
    for (var i = 0; i < ancOptions.length; i++)
      parts.push(ancOptions[i].key + " " + ancOptions[i].label)
    // The two Ambient keys exist only while the row they drive is on screen, so
    // they are named only then: a hint that listed them the rest of the time
    // would be offering keys that do nothing.
    if (ambientRowVisible) parts.push("[ ] Level", "f Voice")
    return parts.join(" · ")
  }

  // The , and . pair is named only when there is a second device to walk to,
  // for the same reason: with one set connected they do nothing, and a line
  // that offered them would be describing a widget you do not have.
  readonly property string keyHint: {
    var parts = ["r Refresh"]
    if (followed.length > 1) parts.push(", . Device")
    parts.push("b Bluetooth", "v Volume", "tab Next panel")
    return parts.join(" · ")
  }

  // Nothing followed is nothing to draw. Otherwise the same rule as before:
  // a set in its case still gets its icon unless you asked for it to go.
  readonly property bool shouldShow: followed.length > 0 && (anyConnected || !hideWhenDisconnected)
  readonly property bool vertical: bar ? bar.vertical : false

  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property color track: Style.selectedFillFor(foreground, Color.accent, urgent)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  implicitWidth: vertical ? markColumn.implicitWidth : markRow.implicitWidth
  implicitHeight: vertical ? markColumn.implicitHeight : markRow.implicitHeight

  // The bar's open-panel mark under the widget is 55% of one slot by default,
  // which under two or more icons underlines only the middle. With several
  // devices it should run under all of them with the same margins a single
  // icon gets: the distance between the outer marks' centres plus one 55% slot.
  // 0 leaves the host's default in place.
  readonly property real openPanelIndicatorWidth: !vertical && followed.length > 1
    ? Math.round(markRow.implicitWidth / followed.length * (followed.length - 0.45)) : 0
  readonly property real openPanelIndicatorHeight: vertical && followed.length > 1
    ? Math.round(markColumn.implicitHeight / followed.length * (followed.length - 0.45)) : 0
  visible: shouldShow

  // What this widget's settings mean for the shared service. Every monitor's
  // copy pushes the same values, because they all read the same shell.json
  // entry; hideWhenDisconnected and showPercentage stay here, being about the
  // drawing rather than about the earbuds.
  Binding {
    target: root.service
    property: "deviceMatch"
    value: root.deviceMatch
    when: root.service !== null
  }
  Binding {
    target: root.service
    property: "useFastPair"
    value: root.useFastPair
    when: root.service !== null
  }
  Binding {
    target: root.service
    property: "useModeControl"
    value: root.useModeControl
    when: root.service !== null
  }
  Binding {
    target: root.service
    property: "lowThreshold"
    value: root.lowThreshold
    when: root.service !== null
  }
  Binding {
    target: root.service
    property: "notifyLow"
    value: root.notifyLowBattery
    when: root.service !== null
  }

  // Hand off to a stock panel rather than grow a second copy of its controls.
  // Closing first keeps one popup on screen at a time.
  function openPanel(target) {
    close()
    if (bar) bar.run("omarchy-shell shell summon " + target)
  }

  function refresh() {
    if (current) current.refresh()
  }

  function setAncMode(mode) {
    return current ? current.setAncMode(mode) : false
  }

  // Walk to the next device, wrapping. Dead with one device followed, which is
  // why the hint line does not mention the keys then.
  // `omarchy-shell omaphones openFor <which>`: the service names an address, the
  // panel selects that follower (the summon that follows opens it).
  Connections {
    target: root.service
    enabled: root.service !== null
    function onOpenRequestChanged() {
      var want = root.service ? String(root.service.openRequest || "") : ""
      if (want === "") return
      for (var i = 0; i < root.followed.length; i++)
        if (root.followed[i].address === want) { root.chosen = root.followed[i]; break }
    }
  }

  function stepDevice(delta) {
    if (followed.length < 2) return false
    var index = followed.indexOf(current)
    if (index < 0) index = 0
    chosen = followed[(index + delta + followed.length) % followed.length]
    return true
  }

  // Writes are held for a moment, so dragging across the track is one command
  // rather than twenty: the headset ACKs a set at once but only reports the new
  // state about half a second later, and a flood of sets leaves the slider
  // arguing with reports that are already out of date. Nothing is dropped — the
  // last value asked for is the one that goes out.
  function setAmbientLevel(value) {
    if (!current) return false
    pendingAmbientLevel = Model.clamp(value, 0, 20)
    askedAmbientLevel = pendingAmbientLevel
    ambientWrite.restart()
    return true
  }

  function stepAmbientLevel(delta) {
    if (!ambientRowVisible) return false
    var from = askedAmbientLevel >= 0 ? askedAmbientLevel : ambientLevel
    return setAmbientLevel(from + delta)
  }

  // Asked for, not set optimistically: the switch follows the headset the same
  // way the mode buttons do, and moves when it reports.
  function toggleAmbientVoice() {
    if (!ambientRowVisible || !current) return false
    return current.setAmbientVoice(!ambientVoice)
  }

  Timer {
    id: ambientWrite
    interval: 150
    repeat: false
    onTriggered: {
      var value = root.pendingAmbientLevel
      root.pendingAmbientLevel = -1
      if (value < 0) return
      // A write the device refuses — no bridge to carry it, or a device with
      // no dial — will never be reported back, so the figure asked for is
      // dropped and the slider returns to what the headset last said.
      if (!root.current || !root.current.setAmbientLevel(value)) root.askedAmbientLevel = -1
    }
  }

  // Whatever the headset says outranks whatever was asked for, including a
  // level turned on the headset itself while a write was in flight.
  onAmbientLevelChanged: askedAmbientLevel = -1

  // A mode key, resolved against the same filtered list the buttons and the hint
  // are built from: a key for a mode this device does not offer is not a key at
  // all, and t on a Sony headset with no TalkThru does nothing rather than
  // sending a command the headset answers by ignoring.
  function setAncModeByKey(key) {
    var wanted = String(key).toLowerCase()
    for (var i = 0; i < ancOptions.length; i++)
      if (ancOptions[i].key === wanted) return setAncMode(ancOptions[i].value)
    return false
  }

  // Opening the panel is when someone wants the truth about a reading that may
  // have gone stale in the case. The device on screen is the one asked; the
  // others are refreshed when you walk to them.
  onOpenedChanged: if (opened && current) current.refreshIfStale()

  // Walking to another device is opening its panel: the same rule applies to
  // whatever it last said as to the one the popup opened on.
  onCurrentChanged: if (opened && current) current.refreshIfStale()

  // A popup anchored to a button that is no longer drawn would float on its own
  // over the bar.
  onShouldShowChanged: if (!shouldShow) close()

  // Every row reserves the same label column, wide enough for the longest label
  // any row can carry, so the meters line up and nothing elides to "Batte…".
  TextMetrics {
    id: labelMetrics
    font.family: root.fontFamily
    font.pixelSize: Style.font.body
    text: "Battery"
  }

  // The marks, one per followed device, along the bar. Two positioners rather
  // than one that turns: a bar icon slot is a square in a vertical bar and the
  // marks have to stack the way the bar runs, and only the one in use is given
  // a model, so the other holds nothing at all.
  Row {
    id: markRow
    visible: !root.vertical

    Repeater {
      model: root.vertical ? [] : root.followed
      DeviceMark {}
    }
  }

  Column {
    id: markColumn
    visible: root.vertical

    Repeater {
      model: root.vertical ? root.followed : []
      DeviceMark {}
    }
  }

  // Where the popup card is on screen, for tools/gallery-shot: the keyboard
  // panel's layer covers the whole output, so nothing outside the shell can
  // see the card's own rectangle. Published while open, blank when closed.
  readonly property string panelRectText: panel.open
    ? [Math.round(panel.cardOrigin.x), Math.round(panel.cardOrigin.y),
       Math.round(panel.contentWidth), Math.round(panel.contentHeight)].join(" ")
    : ""
  onPanelRectTextChanged: if (service) service.panelRect = panelRectText

  KeyboardPanel {
    id: panel
    // The icon the popup belongs to, so with two devices in the bar it opens
    // under the one you clicked rather than under the pair of them. Nothing to
    // claim it — the moment before the marks are built — leaves it on the whole
    // widget, which is where a single-icon widget put it anyway.
    anchorItem: root.currentAnchor ? root.currentAnchor : root
    owner: root
    bar: root.bar
    open: root.opened && root.hasDevice
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(340))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onActivateRequested: root.refresh()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(t) {
        if (t === "b" || t === "B") root.openPanel("omarchy.bluetooth")
        else if (t === "v" || t === "V") root.openPanel("omarchy.audio")
        else if (t === "r" || t === "R") root.refresh()
        // The brackets are the dial, and they are dead unless it is drawn. The
        // mode keys are letters, so a bracket cannot be mistaken for one, and a
        // headset with no dial simply has nothing on them.
        else if (t === "[") root.stepAmbientLevel(-1)
        else if (t === "]") root.stepAmbientLevel(1)
        else if (t === "f" || t === "F") root.toggleAmbientVoice()
        // The two device keys, punctuation for the same reason the brackets
        // are: every letter here already belongs to a mode or to a panel, and
        // , and . sit next to each other under the hand that is on the keys.
        else if (t === ",") root.stepDevice(-1)
        else if (t === ".") root.stepDevice(1)
        else root.setAncModeByKey(t)
      }
      // h/l and the arrows, the way the stock Audio panel moves a slider. This
      // panel has no cursor to walk, so they mean the one slider it can have.
      onMoveRequested: function(dx, dy) {
        if (dx !== 0) root.stepAmbientLevel(dx)
      }

      Column {
        id: column
        width: parent.width
        spacing: Style.space(12)

        // Panel state the hero's icon reads. Inside a Component the name `root`
        // can resolve to the component being built rather than this panel, so
        // what it needs is republished here under `header`.
        Item {
          id: header
          width: parent.width
          implicitHeight: hero.implicitHeight

          readonly property color iconTint: root.low ? root.urgent : root.foreground

          PanelHero {
            id: hero
            width: parent.width
            title: root.deviceName || "Earbuds"
            meta: Model.statusLine(root.summary)
            foreground: root.foreground
            fontFamily: root.fontFamily
            iconOpacity: root.connected ? 1.0 : 0.5

            iconComponent: Component {
              Text {
                text: Model.HEADPHONES_GLYPH
                color: header.iconTint
                font.family: hero.fontFamily
                font.pixelSize: Style.font.display
              }
            }
          }
        }

        PanelSeparator { foreground: root.foreground }

        // ---- One battery for the whole headset, from the Message Stream. No
        //      side and no case to draw: a set that reports one figure gets one
        //      row, rather than a Left row with a Right that will never fill.
        Column {
          width: parent.width
          visible: root.single
          spacing: Style.space(8)

          BatteryRow {
            label: "Battery"
            level: root.singleLevel
            charging: root.singleCharging
          }
        }

        // ---- Per-earbud, from the Message Stream. A component with no reading
        //      is left out rather than drawn at zero.
        Column {
          width: parent.width
          visible: root.perBud
          spacing: Style.space(8)

          BatteryRow {
            label: "Left"
            level: root.leftLevel
            charging: root.leftCharging
          }
          BatteryRow {
            label: "Right"
            level: root.rightLevel
            charging: root.rightCharging
          }
          // No charging bolt for the case, on purpose. The earbuds report the case
          // second-hand and lazily: its level sat at 78% for hours while the case
          // was on a charger and only jumped to 98% once an earbud docked, and the
          // charging bit stayed set for minutes with the case empty and unplugged
          // — while reading clear at a moment the case was plugged in. A level
          // that lags is a small lie; a bolt claiming "charging, now" when the
          // cable is out is a plain one, so the level stays and the bolt goes.
          BatteryRow {
            label: "Case"
            level: root.caseLevel
            charging: false
          }
        }

        // ---- BlueZ's single figure, for a device with no Message Stream. A
        //      headset that reports one battery over the stream has a row of
        //      its own above, and drawing this one too would be two "Battery"
        //      rows for the same battery.
        Column {
          width: parent.width
          visible: !root.perBud && !root.single && root.bluezLevel >= 0
          spacing: Style.space(8)

          BatteryRow {
            label: "Battery"
            level: root.bluezLevel
            charging: false
          }
        }

        // A reader that failed says so even when BlueZ is still supplying a
        // figure: the per-earbud rows are missing for a reason, and the reason is
        // this line. With Fast Pair switched off there is nothing to re-open, so
        // the hint about pressing r would be an instruction to nowhere.
        Text {
          width: parent.width
          visible: root.connected && text !== ""
          text: {
            if (root.readerError !== "") return root.readerError
            if (root.level >= 0) return ""
            if (!root.useFastPair) return "Fast Pair off — BlueZ figure only"
            return "No level yet — press r to re-open the channel"
          }
          textFormat: Text.PlainText
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        Text {
          width: parent.width
          visible: root.hasDevice && !root.connected
          text: "Paired, not connected — press b"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        // ---- Mode — noise control. Present only when the device answered the mode
        //      query — over its own RFCOMM channel on a Sony headset, over BLE
        //      on a JBL pair — and carrying only the modes that answer named.
        Column {
          width: parent.width
          visible: root.modeRowVisible
          spacing: Style.space(8)

          PanelSectionHeader {
            width: parent.width
            text: "MODE"
            foreground: root.foreground
            fontFamily: root.fontFamily
          }

          ButtonGroup {
            width: parent.width
            options: root.ancOptions
            value: root.ancMode
            foreground: root.foreground
            background: Color.background
            fontFamily: root.fontFamily
            fontSize: Style.font.bodySmall
            // The earbuds report their own state, including changes made by
            // touching them, so the selection follows the device rather than the
            // click: `value` is bound to what the device last said.
            onChanged: function(mode) { root.setAncMode(mode) }
          }

          // ---- The two settings that live inside Ambient on a Sony: how much
          //      of the room comes through, and whether voices are lifted out
          //      of it. Drawn under the buttons and only while Ambient is the
          //      mode, because that is the only mode either of them means
          //      anything in.
          Column {
            width: parent.width
            visible: root.ambientRowVisible
            spacing: Style.space(6)

            Item {
              width: parent.width
              implicitHeight: Math.max(ambientLabel.implicitHeight, ambientValue.implicitHeight)

              Text {
                id: ambientLabel
                text: "Ambient level"
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
              }

              // The figure under the hand while a drag is in flight, and the
              // one the headset last reported the rest of the time — which is
              // the same number, since the slider follows the device.
              Text {
                id: ambientValue
                text: String(Math.round(ambientSlider.liveValue))
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
              }
            }

            PanelSlider {
              id: ambientSlider
              bar: root.bar
              width: parent.width
              minimum: 0
              maximum: 20
              step: 1
              integer: true
              // What the headset last said, or the figure asked for while it
              // catches up. Turning the dial on the headset moves this one too,
              // the same way the mode buttons follow it.
              value: root.askedAmbientLevel >= 0
                ? root.askedAmbientLevel
                : Math.max(0, root.ambientLevel)

              onMoved: function(value) { root.setAmbientLevel(value) }
            }

            Item {
              width: parent.width
              implicitHeight: Math.max(voiceLabel.implicitHeight, voiceSwitch.implicitHeight)

              Text {
                id: voiceLabel
                text: "Focus on voice"
                color: root.foreground
                font.family: root.fontFamily
                font.pixelSize: Style.font.body
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
              }

              ToggleSwitch {
                id: voiceSwitch
                checked: root.ambientVoice
                foreground: root.foreground
                accent: Color.accent
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter

                onToggled: root.toggleAmbientVoice()
              }
            }
          }
        }

        // Where the row would have been, when the bridge has a reason it is not
        // there. Silent when the feature is simply switched off.
        Text {
          width: parent.width
          visible: root.connected && !root.modeRowVisible && root.ancError !== ""
          text: "Mode · " + root.ancError
          textFormat: Text.PlainText
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        PanelSeparator {
          visible: root.modeRowVisible
          foreground: root.foreground
        }

        Text {
          width: parent.width
          visible: root.modeRowVisible
          text: root.ancHint
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          horizontalAlignment: Text.AlignHCenter
          wrapMode: Text.Wrap
        }

        PanelSeparator { foreground: root.foreground }

        Text {
          width: parent.width
          text: root.keyHint
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          horizontalAlignment: Text.AlignHCenter
          // Wide enough to overflow once the device-switch keys join the line;
          // a second row is the answer, not a wider panel.
          wrapMode: Text.Wrap
        }
      }
    }
  }

  // The headphones mark, drawn rather than set in a font. A font glyph cannot be
  // filled by percentage: its metrics describe the outline, and for this Nerd
  // Font glyph the outline runs 15px while the pixels it actually paints run
  // 12.5, so "40%" of the metric came out looking like 30% of the drawing. Qt
  // offers no way to ask what was rasterised. Drawn here instead, the ink spans
  // y=0 to y=height by construction, so a fraction of the item is exactly that
  // fraction of the mark.
  component HeadphonesMark: Item {
    id: mark
    property color tint: root.barForeground

    readonly property real stroke: Math.max(1, Math.round(height * 0.09))
    readonly property real cupWidth: Math.max(3, Math.round(width * 0.30))
    readonly property real cupHeight: Math.max(4, Math.round(height * 0.46))

    // The headband is a ring with its lower part clipped away, which is the
    // cheapest honest arch: no Shapes import, no path to get wrong.
    Item {
      width: parent.width
      height: parent.height - mark.cupHeight + mark.stroke
      clip: true

      Rectangle {
        width: parent.width
        height: mark.width
        radius: width / 2
        color: "transparent"
        border.width: mark.stroke
        border.color: mark.tint
      }
    }

    Rectangle {
      x: 0
      width: mark.cupWidth
      height: mark.cupHeight
      radius: Math.max(1, Math.round(mark.cupWidth * 0.35))
      anchors.bottom: parent.bottom
      color: mark.tint
    }

    Rectangle {
      x: mark.width - mark.cupWidth
      width: mark.cupWidth
      height: mark.cupHeight
      radius: Math.max(1, Math.round(mark.cupWidth * 0.35))
      anchors.bottom: parent.bottom
      color: mark.tint
    }
  }

  // One half of the mark, filled from the bottom to `level`. The bright copy is
  // pinned to the same place as the dim one underneath; the window only clips it.
  // One half of the mark, filled from the bottom by one battery. The region is a rectangle in the mark's own coordinates; the
  // bright copy of the whole mark is drawn through it, clipped to the fraction
  // its level says.
  // A pair of earbuds, for devices that report a left and a right: two
  // capsules with a stem each, the stems inward-down the way a pair sits in
  // its case — drawn the same way as the headphones mark, so the ink spans the
  // whole square and a fraction of the item is that fraction of the mark.
  component EarbudsMark: Item {
    id: buds
    property color tint: root.barForeground

    readonly property real bodyW: Math.max(3, Math.round(width * 0.36))
    readonly property real bodyH: Math.max(5, Math.round(height * 0.64))
    readonly property real stemW: Math.max(1, Math.round(width * 0.16))
    readonly property real inset: Math.round(width * 0.04)

    // Left bud: body top-left, stem hanging from its inner-bottom corner.
    Rectangle {
      x: buds.inset; y: 0
      width: buds.bodyW; height: buds.bodyH
      radius: buds.bodyW / 2
      color: buds.tint
    }
    Rectangle {
      x: buds.inset + buds.bodyW - buds.stemW
      y: buds.bodyH - buds.stemW
      width: buds.stemW; height: buds.height - y
      radius: buds.stemW / 2
      color: buds.tint
    }
    // Right bud, mirrored.
    Rectangle {
      x: buds.width - buds.inset - buds.bodyW; y: 0
      width: buds.bodyW; height: buds.bodyH
      radius: buds.bodyW / 2
      color: buds.tint
    }
    Rectangle {
      x: buds.width - buds.inset - buds.bodyW
      y: buds.bodyH - buds.stemW
      width: buds.stemW; height: buds.height - y
      radius: buds.stemW / 2
      color: buds.tint
    }
  }

  // Whichever mark a device is: earbuds when it reports a left and a right,
  // headphones otherwise (a headset, or a set that has not said yet).
  component DeviceGlyph: Item {
    property bool earbuds: false
    property color tint: root.barForeground
    EarbudsMark { anchors.fill: parent; visible: parent.earbuds; tint: parent.tint }
    HeadphonesMark { anchors.fill: parent; visible: !parent.earbuds; tint: parent.tint }
  }

  component MarkPart: Item {
    id: part
    property rect region: Qt.rect(0, 0, 0, 0)
    property int level: -1
    property bool earbuds: false
    // Handed in rather than read off the panel: each device's mark is coloured
    // by its own battery, so two icons in one widget can be one urgent and one
    // plain at the same time.
    property color tint: root.barForeground

    anchors.fill: parent

    Item {
      id: window
      clip: true
      x: part.region.x
      width: part.region.width
      // Any charge left draws at least one row, the same floor the panel's meters
      // use, so 3% reads as nearly empty rather than as empty. Only a real zero
      // and "no reading" draw nothing. The top has the mirror rule: a single dim
      // row at the crown of the band does not read as "nearly full", it reads
      // as the outline being broken, so anything short by less than two rows
      // draws full — at 13 pixels that is roughly 90% and up.
      height: {
        if (part.level <= 0) return 0
        var rows = Math.max(1, Math.round(part.region.height * part.level / 100))
        if (part.region.height - rows < 2) rows = part.region.height
        return rows
      }
      y: part.region.y + part.region.height - height

      Behavior on height { NumberAnimation { duration: 240; easing.type: Easing.OutCubic } }

      DeviceGlyph {
        width: part.width
        height: part.height
        x: -window.x
        y: -window.y
        earbuds: part.earbuds
        tint: part.tint
      }
    }
  }

  // One device's place in the bar: the button that opens its popup, with its
  // mark drawn over it.
  //
  // The bar icon is the meter: a dim headphones glyph with a bright copy of
  // itself filling from the bottom, clipped down the middle so the left half
  // carries the left earbud and the right half the right one. A headset with
  // one battery fills both halves from that one figure. Drawn this way
  // because a device has to fit the width of one bar icon — a vertical bar gives
  // it a single square, and "90%" does not fit in a square. Exact numbers live
  // in the tooltip and the panel.
  //
  // A bud with no reading leaves its half dim, which is what a bud resting in
  // the case looks like, and is the honest drawing for "this one is not saying".
  component DeviceMark: Item {
    id: slot
    required property var modelData
    readonly property var follower: slot.modelData

    readonly property bool connected: follower ? follower.connected : false
    readonly property bool low: follower ? follower.low : false
    readonly property int level: follower ? follower.level : -1
    readonly property bool perBud: follower ? follower.perBud : false
    readonly property int singleLevel: follower ? follower.singleLevel : -1
    readonly property int bluezLevel: follower ? follower.bluezLevel : -1

    readonly property color tint: {
      if (low) return root.urgent
      if (!connected) return Qt.darker(root.barForeground, 1.55)
      return root.barForeground
    }

    // The mark shows the headphones' own batteries and nothing else: the left
    // half is the left earbud, the right half the right one; the case is a row
    // in the panel, not a region of the icon. One battery fills both halves —
    // dimming one would say an earbud is silent on a headset that has none.
    // Earbuds the moment the device reports a left and a right; headphones for
    // a headset, and until a set has said which it is.
    readonly property bool earbuds: singleLevel < 0 && perBud

    readonly property int leftValue: singleLevel >= 0
      ? singleLevel : (perBud ? follower.leftLevel : bluezLevel)
    readonly property int rightValue: singleLevel >= 0
      ? singleLevel : (perBud ? follower.rightLevel : bluezLevel)

    readonly property bool written: root.showPercentage && !root.vertical

    // The mark takes the same parity as the slot it sits in. The bar centres its
    // open-panel mark with Math.round, and an even-width mark in an odd-width
    // slot rounds half a pixel away from an odd-width indicator in the same slot
    // — one physical pixel of visible disagreement. Matching parity makes both
    // divisions exact, and keeps the drawn rectangles on whole pixels.
    readonly property real markSize: {
      var extent = Math.round(width)
      var size = Math.round(Style.bar.iconCanvas)
      if (extent > 0 && (extent - size) % 2 !== 0) size -= 1
      return Math.max(8, size)
    }

    readonly property real markExtent: {
      var h = Math.round(markSize * 0.8)
      if ((markSize - h) % 2 !== 0) h -= 1
      return Math.max(6, h)
    }

    implicitWidth: markButton.implicitWidth
    implicitHeight: markButton.implicitHeight

    // The popup hangs under whichever mark is drawing the device it is about, so
    // it follows a click on another icon and the , and . keys alike.
    function claimAnchor() {
      if (root.current === slot.follower) root.currentAnchor = slot
    }

    Component.onCompleted: claimAnchor()
    Component.onDestruction: if (root.currentAnchor === slot) root.currentAnchor = null

    Connections {
      target: root
      function onCurrentChanged() { slot.claimAnchor() }
    }

    BarIconButton {
      id: markButton
      anchors.fill: parent
      bar: root.bar
      // The drawn mark covers every state, including "connected but saying
      // nothing", which is simply both halves dim. Only the opt-in percentage
      // mode falls back to the font glyph, because there it is a label, not a
      // meter.
      //
      // The mark is drawn below as a sibling rather than handed over as
      // iconComponent: the button centres an icon inside its own optical canvas,
      // and that canvas rounds to a different pixel than the bar's open-panel
      // mark, which is centred on the slot with Math.round. One pixel of
      // disagreement is visible, so the mark is positioned by the same rule.
      text: slot.written ? Model.barText(slot.level, true) : ""
      hasVisualContent: true
      foreground: slot.tint
      slotSize: Style.bar.iconSlot * (slot.written && slot.level >= 0 ? 2 : 1)
      tooltipText: root.opened ? "" : root.tooltipText

      onPressed: function(b) {
        if (b === Qt.RightButton) root.openPanel("omarchy.bluetooth")
        else if (b === Qt.MiddleButton) root.openPanel("omarchy.audio")
        // A click on the icon of a device the popup is not about switches to it
        // and leaves the popup open: with two icons in the bar, closing and
        // reopening to read the other one is a click too many. A click on the
        // icon it is already about is the toggle it has always been.
        else if (root.opened && root.current !== slot.follower) root.chosen = slot.follower
        else {
          root.chosen = slot.follower
          root.toggle()
        }
      }
    }

    // Rounded the same way the bar rounds its open-panel mark: both are centred
    // on this slot with Math.round, so the two are concentric to the pixel.
    Item {
      id: markBox
      visible: !slot.written
      // The neighbouring font glyphs paint about four fifths of the icon canvas
      // (the canvas leaves them headroom); a mark drawn to the full canvas stood
      // a head above the Bluetooth glyph next to it. Scaled down uniformly —
      // width and height alike, so the shape is the one the README describes —
      // with parity kept so the halves still split on a pixel.
      width: slot.markExtent
      height: slot.markExtent
      x: Math.round((slot.width - width) / 2)
      y: Math.round((slot.height - height) / 2)

      // The dim copy. The headband deliberately overlaps the cups by a stroke
      // width so the join is clean, and a translucent tint would composite that
      // overlap twice — 0.5 over 0.5 is 0.75 — leaving a brighter seam exactly
      // where the arch meets each cup. Painting opaque into a layer and fading
      // the layer flattens the overlap first, so the seam disappears.
      DeviceGlyph {
        anchors.fill: parent
        earbuds: slot.earbuds
        tint: slot.tint
        // Bright enough that the unfilled part of the mark reads as the rest
        // of the outline — at 91% the empty top of the band is one pixel row,
        // and at a third of the brightness it read as the mark being cut off.
        opacity: 0.5
        layer.enabled: true
      }

      MarkPart {
        region: Qt.rect(0, 0, Math.round(slot.markExtent / 2), slot.markExtent)
        level: slot.leftValue
        earbuds: slot.earbuds
        tint: slot.tint
      }
      MarkPart {
        region: Qt.rect(Math.round(slot.markExtent / 2), 0,
                        slot.markExtent - Math.round(slot.markExtent / 2), slot.markExtent)
        level: slot.rightValue
        earbuds: slot.earbuds
        tint: slot.tint
      }
    }
  }

  // One battery: glyph, name, meter, percentage. Charging shows in the glyph,
  // which is the same ramp the stock power widget uses.
  component BatteryRow: Item {
    id: row
    property string label: ""
    property int level: -1
    property bool charging: false

    readonly property bool known: level >= 0
    readonly property bool low: known && level <= root.lowThreshold && !charging
    readonly property color tint: !known ? root.dim : (low ? root.urgent : root.foreground)

    // Always drawn. A component that reports nothing gets a dash and an empty
    // track: a row that vanishes reads as a broken widget, and the earbud going
    // quiet is information worth showing rather than hiding.
    width: parent ? parent.width : 0
    implicitHeight: Math.max(rowGlyph.implicitHeight, rowLabel.implicitHeight,
                             rowPercent.implicitHeight)

    Text {
      id: rowGlyph
      text: row.known ? Model.levelGlyph(row.level, row.charging) : Model.UNKNOWN_GLYPH
      color: row.tint
      font.family: root.fontFamily
      font.pixelSize: Style.font.iconLarge
      anchors.left: parent.left
      anchors.verticalCenter: parent.verticalCenter
    }

    Text {
      id: rowLabel
      text: row.label
      color: root.foreground
      font.family: root.fontFamily
      font.pixelSize: Style.font.body
      width: Math.ceil(labelMetrics.width)
      elide: Text.ElideRight
      anchors.left: rowGlyph.right
      anchors.leftMargin: Style.spacing.md
      anchors.verticalCenter: parent.verticalCenter
    }

    Item {
      id: rowMeter
      anchors.left: rowLabel.right
      anchors.leftMargin: Style.spacing.md
      anchors.right: rowPercent.left
      anchors.rightMargin: Style.spacing.md
      anchors.verticalCenter: parent.verticalCenter
      implicitHeight: Math.max(Style.space(5), Math.round(Style.spacing.controlHeight * 0.16))
      height: implicitHeight

      Rectangle {
        id: meterTrack
        anchors.fill: parent
        radius: height / 2
        color: root.track
      }

      Rectangle {
        anchors.left: meterTrack.left
        anchors.verticalCenter: meterTrack.verticalCenter
        height: meterTrack.height
        radius: meterTrack.radius
        width: row.known
          ? Math.max(meterTrack.height, meterTrack.width * row.level / 100)
          : 0
        color: row.tint

        Behavior on width { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } }
        Behavior on color { ColorAnimation { duration: 200 } }
      }
    }

    Text {
      id: rowPercent
      text: Model.percentLabel(row.level)
      color: row.tint
      font.family: root.fontFamily
      font.pixelSize: Style.font.bodySmall
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
    }
  }
}
