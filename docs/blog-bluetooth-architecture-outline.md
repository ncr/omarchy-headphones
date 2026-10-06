# Who Owns the Bluetooth Connection? Lessons from Omarchy Plugins

## Core idea

Small desktop widgets hide consequential architectural choices: who owns the connection, where state lives, and what survives a UI reload.

Scope: Bluetooth broadly, including BLE—Omaphones uses both BLE and classic Bluetooth. Based on source and documentation review; the evaluations below are architectural judgments.

## 1. Start with Omaphones

A battery icon and an ANC switch look simple. Supporting different headphones introduces proprietary protocols, reconnects, disappearing devices, and hardware the maintainer cannot personally test.

Use that experience to introduce the architectural choices.

## 2. Compare four approaches

| Approach and real examples | What works well | Where it becomes costly |
|---|---|---|
| **Use existing system services.** Omarchy’s [native Bluetooth panel](https://github.com/omacom/omarchy/blob/quattro/shell/plugins/panels/bluetooth/Panel.qml) reads Quickshell Bluetooth state and delegates connection operations. | Little device-specific code; builds on the desktop’s existing infrastructure. | Limited to what those services expose; proprietary controls need another layer. |
| **Poll a command-line tool.** [omarchy-peripherals](https://github.com/tpatzelt/omarchy-peripherals) periodically parses `upower --dump`. | Small, inspectable implementation; sensible for slowly changing battery levels. | Delayed updates, text parsing, repeated process launches; a weaker fit for interactive controls. |
| **Let the plugin manage a persistent bridge.** [Omaphones](https://github.com/ncr/omarchy-headphones) and [WalkingPad Control](https://github.com/shllg/omarchy-walkingpad-control) exchange commands and state through stdin/stdout. | Clear UI/protocol boundary; independently testable backend; straightforward installation. | Connection lifetime follows the shell/plugin; reloads require recovery. Multiple bridges can duplicate lifecycle logic. |
| **Run an independent background service.** [WalkingPad](https://github.com/msegoviadev/omarchy-walkingpad) uses a systemd collector; [Omapods](https://github.com/thisisgm/omarchy-pods) uses a bundled, modified librepods daemon. | Collection and device handling survive UI reloads; useful for history and ongoing behavior. | More installation, upgrade and cleanup work; backend dependencies and forks become maintenance responsibilities. |

## 3. Separate the choices that often get conflated

- **Backend lifetime versus UI updates:** WalkingPad polls its collector’s data; Omapods watches a status file. Having a daemon does not automatically mean event-driven updates.
- **Libraries versus direct BlueZ integration:** WalkingPad reuses a controller library; WalkingPad Control implements transport through Gio/BlueZ. Reuse reduces implementation work; direct integration reduces extra dependencies but increases code ownership.
- **Polling versus notifications:** WalkingPad Control documents a device that requires status queries. Polling the hardware can be necessary even when the UI receives streamed updates. [Protocol explanation](https://github.com/shllg/omarchy-walkingpad-control#behaviour-that-looks-like-a-bug-and-is-not)

## 4. What I would carry back into Omaphones

Explicit connection ownership, a stable bridge contract, separate requested and observed state, and device-specific replay evidence. Discuss where shared lifecycle code helps—and where abstraction could accidentally change another owner’s working headphones.

## 5. Closing takeaway

**Choose the architecture around what must keep working when the widget disappears.** Battery display, headphone controls, and continuous activity recording justify different amounts of infrastructure.
