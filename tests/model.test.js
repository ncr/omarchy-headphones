// Model.js holds the picking, parsing and formatting, with no QML imports, so it
// runs outside the shell. The cases here are the ones that bite: a bud that
// reports nothing, a reader line that is not JSON, a set with one battery, and a
// device list where the wrong device is easy to pick.
//
//   deno test --allow-read tests/model.test.js
//
// Loading: Model.js is plain script text, not a module, because QML imports it
// with `import "Model.js" as Model`. Read and evaluate it, then pull the
// functions out of the resulting scope. The export list is derived from the
// source rather than written by hand: a hand-written one drifts silently, and a
// helper that is missing from it simply reads as undefined here, so a test for
// it would fail for the wrong reason (or never be written at all).

import { assertEquals } from "jsr:@std/assert@1";

const source = await Deno.readTextFile(
  new URL("../Model.js", import.meta.url),
);
const exported = [
  ...source.matchAll(/^function\s+(\w+)/gm),
  ...source.matchAll(/^var\s+(\w+)\s*=/gm),
].map((match) => match[1]);
const Model = new Function(
  source + "\nreturn { " + exported.join(", ") + " };",
)();

Deno.test("every top-level helper and glyph constant is reachable", () => {
  // Guards the derivation above: if the regexes stop seeing the source, this
  // fails here instead of turning every other test into `undefined is not a
  // function`.
  for (const name of ["tooltip", "statusLine", "parseSupport", "supportVerdict"]) {
    assertEquals(typeof Model[name], "function", name);
  }
  assertEquals(Model.UNKNOWN_GLYPH, "\u{f0091}");
  assertEquals(Model.HEADPHONES_GLYPH, "\u{f02cb}");
  const missing = exported.filter((name) => Model[name] === undefined);
  assertEquals(missing, []);
});

const buds = (extra = {}) => ({
  name: "JBL TUNE230NC TWS",
  address: "AA:BB:CC:DD:EE:FF",
  icon: "audio-headset",
  paired: true,
  connected: true,
  batteryAvailable: true,
  battery: 0.2,
  ...extra,
});

const mouse = (extra = {}) => ({
  name: "MX Master 4",
  address: "AA:BB:CC:DD:EE:FF",
  icon: "input-mouse",
  paired: true,
  connected: true,
  batteryAvailable: true,
  battery: 0.9,
  ...extra,
});

Deno.test("deviceLabel prefers the name and falls back to the address", () => {
  assertEquals(Model.deviceLabel(buds()), "JBL TUNE230NC TWS");
  assertEquals(
    Model.deviceLabel({ name: "", deviceName: "", address: "AA:BB:CC:DD:EE:FF" }),
    "AA:BB:CC:DD:EE:FF",
  );
  // With no user-set alias the device-reported name carries it.
  assertEquals(
    Model.deviceLabel({ name: "", deviceName: "Sony WH", address: "B0:11:22:33:44:55" }),
    "Sony WH",
  );
  assertEquals(Model.deviceLabel(null), "");
});

Deno.test("isAudioDevice falls back to the name when BlueZ sends no icon", () => {
  assertEquals(Model.isAudioDevice({ icon: "", name: "Pixel Buds Pro" }), true);
  assertEquals(Model.isAudioDevice({ icon: "", name: "MX Master 4" }), false);
  assertEquals(Model.isAudioDevice(null), false);
});

Deno.test("an empty filter accepts audio devices only", () => {
  assertEquals(Model.matchesFilter(buds(), ""), true);
  assertEquals(Model.matchesFilter(mouse(), ""), false);
  // A named filter is matched against the name and the address, case-insensitively.
  assertEquals(Model.matchesFilter(buds(), "jbl"), true);
  assertEquals(Model.matchesFilter(buds(), "aa:bb"), true);
  assertEquals(Model.matchesFilter(buds(), "sony"), false);
  // ...and it overrides the audio check, so a filter can name anything.
  assertEquals(Model.matchesFilter(mouse(), "MX Master"), true);
});

Deno.test("pickDevice takes the connected earbuds over a paired mouse", () => {
  const picked = Model.pickDevice([mouse(), buds()], "");
  assertEquals(Model.deviceLabel(picked), "JBL TUNE230NC TWS");
});

Deno.test("pickDevice prefers connected over the last used", () => {
  const sony = buds({ name: "WH-CH720N", address: "B0:11:22:33:44:55", connected: false });
  const picked = Model.pickDevice([sony, buds()], "", "B0:11:22:33:44:55");
  assertEquals(Model.deviceLabel(picked), "JBL TUNE230NC TWS");
});

Deno.test("with nothing connected, the last used device wins", () => {
  const sony = buds({ name: "WH-CH720N", address: "B0:11:22:33:44:55", connected: false });
  const jbl = buds({ connected: false });
  const picked = Model.pickDevice([jbl, sony], "", "B0:11:22:33:44:55");
  assertEquals(Model.deviceLabel(picked), "WH-CH720N");
});

Deno.test("pickDevice ignores devices that are neither paired nor connected", () => {
  assertEquals(Model.pickDevice([buds({ paired: false, connected: false })], ""), null);
  assertEquals(Model.pickDevice([], ""), null);
  assertEquals(Model.pickDevice(null, ""), null);
});

Deno.test("rankDevices puts the connected first and orders the rest by name", () => {
  const sony = buds({ name: "WH-CH720N", address: "B0:11:22:33:44:55" });
  const jbl = buds();
  // Both connected and both reporting: the tie goes to the name, so the icons
  // keep their places in the bar between one reading and the next.
  assertEquals(
    Model.rankDevices([sony, jbl], "").map(Model.deviceLabel),
    ["JBL TUNE230NC TWS", "WH-CH720N"],
  );
  // ...and the set used last breaks it first, which is what the bar reads as
  // "the one you just put on".
  assertEquals(
    Model.rankDevices([jbl, sony], "", "B0:11:22:33:44:55").map(Model.deviceLabel),
    ["WH-CH720N", "JBL TUNE230NC TWS"],
  );
  // Connected still beats everything, whatever it is called.
  assertEquals(
    Model.rankDevices([jbl, buds({ name: "AAA", connected: false })], "")
      .map(Model.deviceLabel),
    ["JBL TUNE230NC TWS", "AAA"],
  );
  assertEquals(Model.rankDevices([mouse()], ""), []);
  assertEquals(Model.rankDevices(null, ""), []);
});

Deno.test("followedAddresses names every connected match", () => {
  const sony = buds({ name: "WH-CH720N", address: "B0:11:22:33:44:55" });
  const jbl = buds();
  // Two headsets on one desk are two followers, not a competition.
  assertEquals(Model.followedAddresses([sony, jbl], ""), [
    "AA:BB:CC:DD:EE:FF",
    "B0:11:22:33:44:55",
  ]);
  // A filter still applies, and a mouse is never audio.
  assertEquals(Model.followedAddresses([sony, jbl, mouse()], "jbl"), [
    "AA:BB:CC:DD:EE:FF",
  ]);
  // With nothing connected it falls back to the one device that would have been
  // picked, so the widget can name the earbuds it is waiting for.
  const parked = [
    buds({ connected: false }),
    buds({ name: "WH-CH720N", address: "B0:11:22:33:44:55", connected: false }),
  ];
  assertEquals(Model.followedAddresses(parked, "", "B0:11:22:33:44:55"), [
    "B0:11:22:33:44:55",
  ]);
  // A connected device beats that fallback outright: the paired one is left out.
  assertEquals(Model.followedAddresses([parked[1], jbl], "", "B0:11:22:33:44:55"), [
    "AA:BB:CC:DD:EE:FF",
  ]);
  assertEquals(Model.followedAddresses([mouse()], ""), []);
  assertEquals(Model.followedAddresses([], ""), []);
});

Deno.test("deviceByAddress is how a follower stays pinned to one set", () => {
  const sony = buds({ name: "WH-CH720N", address: "B0:11:22:33:44:55" });
  const jbl = buds();
  assertEquals(
    Model.deviceLabel(Model.deviceByAddress([jbl, sony], "B0:11:22:33:44:55")),
    "WH-CH720N",
  );
  // Whatever cased the address, it is the same device.
  assertEquals(
    Model.deviceLabel(Model.deviceByAddress([jbl, sony], "b0:11:22:33:44:55")),
    "WH-CH720N",
  );
  assertEquals(Model.deviceByAddress([jbl], "B0:11:22:33:44:55"), null);
  assertEquals(Model.deviceByAddress([jbl], ""), null);
  assertEquals(Model.deviceByAddress(null, "AA:BB:CC:DD:EE:FF"), null);
});

Deno.test("sortFollowers orders the icons the way the bar draws them", () => {
  const follower = (name, address, connected = true) => ({ name, address, connected });
  const jbl = follower("JBL TUNE230NC TWS", "AA:BB:CC:DD:EE:FF");
  const sony = follower("WH-CH720N", "B0:11:22:33:44:55");
  assertEquals(
    Model.sortFollowers([sony, jbl], "").map((f) => f.name),
    ["JBL TUNE230NC TWS", "WH-CH720N"],
  );
  assertEquals(
    Model.sortFollowers([jbl, sony], "b0:11:22:33:44:55").map((f) => f.name),
    ["WH-CH720N", "JBL TUNE230NC TWS"],
  );
  // A device in its case sinks below one that is here, whatever its name.
  const parked = follower("AAA", "11:22:33:44:55:66", false);
  assertEquals(
    Model.sortFollowers([parked, jbl], "").map((f) => f.name),
    ["JBL TUNE230NC TWS", "AAA"],
  );
  assertEquals(Model.sortFollowers([], ""), []);
  assertEquals(Model.sortFollowers(null, ""), []);
});

Deno.test("findByWhich answers for the device an IPC caller named", () => {
  const followed = [
    { name: "JBL TUNE230NC TWS", address: "AA:BB:CC:DD:EE:FF" },
    { name: "WH-CH720N", address: "B0:11:22:33:44:55", controlBackend: "sony" },
    { name: "Xiaomi Buds 5 Pro", address: "64:8F:DB:87:06:CB", controlBackend: "xiaomi" },
  ];
  // The brand is often only in the backend: a Sony calls itself "WH-CH720N".
  assertEquals(Model.findByWhich(followed, "sony"), 1);
  assertEquals(Model.findByWhich(followed, "xiaomi"), 2);
  assertEquals(Model.findByWhich(followed, "buds 5"), 2);
  // Nothing named is the first device, which is what a no-argument call means.
  assertEquals(Model.findByWhich(followed, ""), 0);
  assertEquals(Model.findByWhich(followed, "  "), 0);
  assertEquals(Model.findByWhich(followed, "jbl"), 0);
  assertEquals(Model.findByWhich(followed, "ch720"), 1);
  // The address works as well as the name, and case is nobody's business.
  assertEquals(Model.findByWhich(followed, "b0:11:22"), 1);
  assertEquals(Model.findByWhich(followed, "airpods"), -1);
  assertEquals(Model.findByWhich([], ""), -1);
  assertEquals(Model.findByWhich(null, "jbl"), -1);
});

Deno.test("shortError keeps the last line a helper said, trimmed", () => {
  assertEquals(
    Model.shortError("Traceback:\n  File x\nModuleNotFoundError: no dbus\n", "fell over"),
    "ModuleNotFoundError: no dbus",
  );
  // Nothing said at all is what the fallback is for.
  assertEquals(Model.shortError("", "fell over"), "fell over");
  assertEquals(Model.shortError("   \n\n", "fell over"), "fell over");
  assertEquals(Model.shortError(null, "fell over"), "fell over");
  // A panel is not a log: a wall of text is cut and marked as cut.
  const long = Model.shortError("x".repeat(400), "fell over");
  assertEquals(long.length, 158);
  assertEquals(long.slice(-1), "…");
});

Deno.test("batteryLevel needs a connection and a reported battery", () => {
  assertEquals(Model.batteryLevel(buds()), 20);
  assertEquals(Model.batteryLevel(buds({ connected: false })), -1);
  assertEquals(Model.batteryLevel(buds({ batteryAvailable: false })), -1);
  assertEquals(Model.batteryLevel(null), -1);
  // Out-of-range input is clamped rather than trusted.
  assertEquals(Model.batteryLevel(buds({ battery: 1.4 })), 100);
  assertEquals(Model.batteryLevel(buds({ battery: -0.2 })), 0);
  // BatteryAvailable without a Percentage yet: unknown, not zero.
  assertEquals(Model.batteryLevel({ connected: true, batteryAvailable: true }), -1);
});

Deno.test("lowestBud ignores a bud that reports nothing", () => {
  assertEquals(Model.lowestBud(80, 40), 40);
  assertEquals(Model.lowestBud(-1, 40), 40);
  assertEquals(Model.lowestBud(80, -1), 80);
  assertEquals(Model.lowestBud(-1, -1), -1);
  // The point of the function: a bud in the case must not drag the bar to zero.
  assertEquals(Model.lowestBud(-1, 90), 90);
});

Deno.test("levelGlyph walks the ramp and switches on charging", () => {
  assertEquals(Model.levelGlyph(-1, false), "");
  assertEquals(Model.levelGlyph(0, false), "\u{f007a}");
  assertEquals(Model.levelGlyph(100, false), "\u{f0079}");
  assertEquals(Model.levelGlyph(50, true), "\u{f0089}");
  // 100 must not index past the end of the ramp.
  assertEquals(Model.levelGlyph(100, true), "\u{f0085}");
  // A missing level is not a level: no glyph, and no NaN index into the ramp.
  assertEquals(Model.levelGlyph(undefined, false), "");
  assertEquals(Model.levelGlyph(NaN, true), "");
});

Deno.test("statusLine states the connection and leaves the levels to the rows", () => {
  const base = { hasDevice: true, connected: true, name: "JBL", level: 40 };
  assertEquals(Model.statusLine({ ...base, left: 55, right: 40 }), "connected");
  assertEquals(Model.statusLine({ ...base, left: 55, right: 40, charging: true }), "connected · charging");
  assertEquals(Model.statusLine({ ...base, left: -1, right: -1, level: 35 }), "connected");
  assertEquals(Model.statusLine({ ...base, single: true, singleLevel: 97, level: 97 }), "connected");
  assertEquals(Model.statusLine({ ...base, left: -1, right: -1, level: -1 }), "connected · battery not reported");
  assertEquals(Model.statusLine({ hasDevice: true, connected: false }), "not connected");
  assertEquals(Model.statusLine({ hasDevice: false }), "no headphones paired");
});

Deno.test("tooltip lists only the components that reported", () => {
  assertEquals(
    Model.tooltip({
      hasDevice: true, connected: true, name: "JBL",
      left: 90, right: 100, caseLevel: 78, level: 90,
    }),
    "JBL · L 90% · R 100% · case 78%",
  );
  assertEquals(
    Model.tooltip({
      hasDevice: true, connected: true, name: "JBL",
      left: -1, right: -1, caseLevel: -1, level: 20,
    }),
    "JBL · 20%",
  );
  assertEquals(
    Model.tooltip({
      hasDevice: true, connected: true, name: "JBL",
      left: -1, right: -1, caseLevel: -1, level: -1,
    }),
    "JBL · battery unknown",
  );
  assertEquals(
    Model.tooltip({ hasDevice: true, connected: false, name: "JBL" }),
    "JBL · not connected",
  );
  assertEquals(Model.tooltip({ hasDevice: false }), "No headphones paired");
});

Deno.test("tooltip leads with the set level when only the case reported", () => {
  // The bug this pins: with both buds silent the bar shows state.level, and the
  // tooltip used to name the case alone, so the two disagreed on screen.
  const state = {
    hasDevice: true, connected: true, name: "JBL",
    left: -1, right: -1, caseLevel: 78, level: 35,
  };
  assertEquals(Model.tooltip(state), "JBL · 35% · case 78%");
  assertEquals(Model.statusLine(state), "connected");
});

Deno.test("a headset with one battery is never given a side", () => {
  // The WH-CH720N sends a one-byte battery payload: one figure for the whole
  // headset, with no left, no right and no case. It used to arrive as `left`
  // and read "L 100%", which claims a right earbud that does not exist.
  const state = {
    hasDevice: true, connected: true, name: "WH-CH720N",
    left: -1, right: -1, caseLevel: -1, level: 100,
    single: true, singleLevel: 100,
  };
  assertEquals(Model.singleLevel(state), 100);
  assertEquals(Model.statusLine(state), "connected");
  assertEquals(Model.tooltip(state), "WH-CH720N · 100%");
  assertEquals(Model.lowBatteryBody({ ...state, level: 15, singleLevel: 15 }), "15% left");
});

Deno.test("singleLevel answers only for a set that says it has one battery", () => {
  // A pair of earbuds carries no `single`, and a single headset that has not
  // reported yet carries -1; both mean "no single figure", so callers can ask
  // one question rather than checking a flag and a number.
  assertEquals(Model.singleLevel({ single: true, singleLevel: -1 }), -1);
  assertEquals(Model.singleLevel({ single: false, singleLevel: 90 }), -1);
  assertEquals(Model.singleLevel({ singleLevel: 90 }), -1);
  assertEquals(Model.singleLevel({ single: true, singleLevel: "90" }), -1);
  assertEquals(Model.singleLevel(null), -1);
  // With the flag off, the per-earbud tooltip wording is untouched.
  assertEquals(
    Model.tooltip({
      hasDevice: true, connected: true, name: "JBL",
      left: 55, right: 40, level: 40, single: false, singleLevel: -1,
    }),
    "JBL · L 55% · R 40%",
  );
});

Deno.test("lowBatteryBody says which bud is low", () => {
  assertEquals(
    Model.lowBatteryBody({ left: 15, right: 8, level: 8 }),
    "L 15% · R 8% left",
  );
  assertEquals(Model.lowBatteryBody({ left: -1, right: -1, level: 20 }), "20% left");
  assertEquals(Model.lowBatteryBody({ left: -1, right: -1, level: -1 }), "battery low");
});

Deno.test("barText writes a percentage only when asked and known", () => {
  assertEquals(Model.barText(40, true), "\u{f02cb} 40%");
  assertEquals(Model.barText(40, false), "\u{f02cb}");
  assertEquals(Model.barText(-1, true), "\u{f02cb}");
  assertEquals(Model.percentLabel(-1), "—");
  assertEquals(Model.percentLabel(0), "0%");
});

Deno.test("mergeReaderLine keeps values the newer line omits", () => {
  const first = Model.mergeReaderLine({}, '{"stream":true,"modelId":"71f20a","left":90}');
  assertEquals(first.modelId, "71f20a");
  // A later battery line carries no modelId; it must survive.
  const second = Model.mergeReaderLine(first, '{"stream":true,"left":80,"right":70}');
  assertEquals(second.modelId, "71f20a");
  assertEquals(second.left, 80);
  assertEquals(second.right, 70);
});

Deno.test("mergeReaderLine takes the single-battery line as the reader writes it", () => {
  const state = Model.mergeReaderLine(
    {},
    '{"stream":true,"single":true,"battery":100,"batteryCharging":false,' +
      '"left":-1,"right":-1,"case":-1,"modelId":"0e4c0a"}',
  );
  assertEquals(state.single, true);
  assertEquals(Model.readerLevel(state, "battery"), 100);
  // The three component keys stay unknown: the headset measured one battery.
  assertEquals(Model.readerLevel(state, "left"), -1);
  assertEquals(Model.readerLevel(state, "right"), -1);
  assertEquals(Model.readerLevel(state, "case"), -1);
});

Deno.test("readerLineAddress routes a line to the device it is about", () => {
  // One reader serves every device, so every line for a device names it.
  assertEquals(
    Model.readerLineAddress('{"address":"A0:11:22:33:44:55","stream":true,"left":90}'),
    "A0:11:22:33:44:55",
  );
  // Whatever case it arrives in; the service compares it with BlueZ's.
  assertEquals(
    Model.readerLineAddress('{"address":" a0:11:22:33:44:55 ","stream":false,"error":"x"}'),
    "A0:11:22:33:44:55",
  );
  // No address is the reader talking about itself, which is every device's
  // problem and no device's line.
  assertEquals(Model.readerLineAddress('{"stream":false,"error":"no system bus"}'), "");
  assertEquals(Model.readerLineAddress('{"stream":true}'), "");
  // Junk is unroutable in exactly the same way.
  assertEquals(Model.readerLineAddress("not json at all"), "");
  assertEquals(Model.readerLineAddress(""), "");
  assertEquals(Model.readerLineAddress(null), "");
  assertEquals(Model.readerLineAddress("[7,8]"), "");
  assertEquals(Model.readerLineAddress("42"), "");
  assertEquals(Model.readerLineAddress("null"), "");
  // An address that is not a string is not an address.
  assertEquals(Model.readerLineAddress('{"address":7,"stream":true}'), "");
});

Deno.test("readerAddresses names the devices the one reader is started for", () => {
  const connected = { address: "A0:11:22:33:44:55", connected: true };
  const parked = { address: "B0:11:22:33:44:55", connected: false };
  assertEquals(Model.readerAddresses([connected, parked]), ["A0:11:22:33:44:55"]);
  // Uppercased, so the address on a line and the address in the follow list are
  // written the same way.
  assertEquals(
    Model.readerAddresses([{ address: "b0:11:22:33:44:55", connected: true }]),
    ["B0:11:22:33:44:55"],
  );
  // A device in its case has no channel to open, and asking BlueZ for one would
  // connect it behind its owner's back.
  assertEquals(Model.readerAddresses([parked]), []);
  assertEquals(Model.readerAddresses([{ address: "", connected: true }]), []);
  assertEquals(Model.readerAddresses([connected, connected]), ["A0:11:22:33:44:55"]);
  assertEquals(Model.readerAddresses([null]), []);
  assertEquals(Model.readerAddresses([]), []);
  assertEquals(Model.readerAddresses(null), []);
});

Deno.test("mergeReaderLine carries the address along with the reading", () => {
  const state = Model.mergeReaderLine(
    {},
    '{"address":"A0:11:22:33:44:55","stream":true,"left":90,"right":80}',
  );
  assertEquals(state.address, "A0:11:22:33:44:55");
  // The service routed by it already, so it is only ever the same address; it
  // survives the error line like the other identifying keys.
  const down = Model.mergeReaderLine(
    state,
    '{"address":"A0:11:22:33:44:55","stream":false,"error":"message stream ended"}',
  );
  assertEquals(down.address, "A0:11:22:33:44:55");
  assertEquals(down.left, 90);
});

Deno.test("mergeReaderLine survives junk without losing what it had", () => {
  const state = Model.mergeReaderLine({ left: 90, stream: true }, "not json at all");
  assertEquals(state.left, 90);
  assertEquals(state.stream, true);
  assertEquals(Model.mergeReaderLine({ left: 90 }, "").left, 90);
  assertEquals(Model.mergeReaderLine({ left: 90 }, null).left, 90);
  // A JSON array is valid JSON; merging it would add keys "0" and "1".
  const array = Model.mergeReaderLine({ left: 90 }, "[7,8]");
  assertEquals(array.left, 90);
  assertEquals(Object.keys(array), ["left"]);
  assertEquals(Model.mergeReaderLine({ left: 90 }, "42").left, 90);
  assertEquals(Object.keys(Model.mergeReaderLine({ left: 90 }, "null")), ["left"]);
});

Deno.test("parseSupport reads anything that is not an object as no record", () => {
  assertEquals(Model.parseSupport(""), {});
  assertEquals(Model.parseSupport("not json"), {});
  assertEquals(Model.parseSupport("null"), {});
  assertEquals(Model.parseSupport("[]"), {});
  assertEquals(Model.parseSupport(null), {});
  assertEquals(
    Model.parseSupport('{"71f20a":{"supported":true}}'),
    { "71f20a": { supported: true } },
  );
});

Deno.test("supportVerdict only retires a model the bridge gave up on", () => {
  // Misses alone are still "not settled": the bridge writes supported:false
  // itself once it has heard silence often enough.
  assertEquals(Model.supportVerdict({ "x": { misses: 2 } }, "x"), -1);
  assertEquals(Model.supportVerdict({ "x": { supported: false } }, "x"), 0);
  assertEquals(Model.supportVerdict({ "x": { supported: true } }, "x"), 1);
  // A malformed entry, an empty record and a missing model id all cost a probe.
  assertEquals(Model.supportVerdict({ "x": true }, "x"), -1);
  assertEquals(Model.supportVerdict({}, ""), -1);
  assertEquals(Model.supportVerdict({}, "x"), -1);
  assertEquals(Model.supportVerdict(null, "x"), -1);
});

Deno.test("readerLevel treats absent, negative and non-numeric alike", () => {
  assertEquals(Model.readerLevel({ left: 90 }, "left"), 90);
  assertEquals(Model.readerLevel({ left: -1 }, "left"), -1);
  assertEquals(Model.readerLevel({}, "left"), -1);
  assertEquals(Model.readerLevel({ left: "90" }, "left"), -1);
  assertEquals(Model.readerLevel(null, "left"), -1);
  // The single-battery line puts its figure in `battery`, read the same way.
  assertEquals(Model.readerLevel({ battery: 100 }, "battery"), 100);
  assertEquals(Model.readerLevel({ battery: -1 }, "battery"), -1);
});

Deno.test("asBool accepts the strings `omarchy bar set` writes", () => {
  assertEquals(Model.asBool(false, true), false);
  assertEquals(Model.asBool(true, false), true);
  // The case this exists for: a JSON string, which is truthy in QML.
  assertEquals(Model.asBool("false", true), false);
  assertEquals(Model.asBool("off", true), false);
  assertEquals(Model.asBool("0", true), false);
  assertEquals(Model.asBool("true", false), true);
  assertEquals(Model.asBool("on", false), true);
  assertEquals(Model.asBool(0, true), false);
  assertEquals(Model.asBool(1, false), true);
  // Anything unrecognised keeps the default rather than guessing.
  assertEquals(Model.asBool("maybe", true), true);
  assertEquals(Model.asBool(undefined, true), true);
  assertEquals(Model.asBool("", false), false);
});

Deno.test("asInt parses numbers written as strings", () => {
  assertEquals(Model.asInt(15, 20), 15);
  assertEquals(Model.asInt("15", 20), 15);
  assertEquals(Model.asInt("15.6", 20), 16);
  assertEquals(Model.asInt("nonsense", 20), 20);
  assertEquals(Model.asInt(undefined, 20), 20);
  assertEquals(Model.asInt("", 20), 20);
  // Number("  ") is 0, which as a low-battery threshold would mean "never warn".
  assertEquals(Model.asInt("  ", 20), 20);
});

Deno.test("clamp keeps a stepped dial inside its range", () => {
  assertEquals(Model.clamp(12, 0, 20), 12);
  // A step off either end stops there rather than asking for 21 or -1.
  assertEquals(Model.clamp(21, 0, 20), 20);
  assertEquals(Model.clamp(-1, 0, 20), 0);
  // The slider hands over a real, and the dial has whole stops only.
  assertEquals(Model.clamp(12.4, 0, 20), 12);
  assertEquals(Model.clamp(12.5, 0, 20), 13);
  assertEquals(Model.clamp("8", 0, 20), 8);
  assertEquals(Model.clamp("nonsense", 0, 20), 0);
  assertEquals(Model.clamp(undefined, 0, 20), 0);
});

Deno.test("uuidsFromBluetoothctl reads the UUID lines and nothing else", () => {
  const info = [
    "Device B0:11:22:33:44:55 (public)",
    "\tName: WH-CH720N",
    "\tIcon: audio-headset",
    "\tUUID: Headset                   (00001108-0000-1000-8000-00805f9b34fb)",
    "\tUUID: Vendor specific           (956C7B26-D49A-4BA8-B03F-B17D393CB6E2)",
    "\tModalias: usb:v054Cp0EAFd0112",
    "\tBattery Percentage: 0x64 (100)",
  ].join("\n");
  assertEquals(Model.uuidsFromBluetoothctl(info), [
    "00001108-0000-1000-8000-00805f9b34fb",
    "956c7b26-d49a-4ba8-b03f-b17d393cb6e2",
  ]);
  // A failed probe, and a device that lists none, both read as "nothing seen".
  assertEquals(Model.uuidsFromBluetoothctl(""), []);
  assertEquals(Model.uuidsFromBluetoothctl(null), []);
  assertEquals(
    Model.uuidsFromBluetoothctl("Device 00:11:22:33:44:55 not available"),
    [],
  );
});

Deno.test("controlBackend picks the protocol the device advertises", () => {
  const sony = ["0000110b-0000-1000-8000-00805f9b34fb", Model.SONY_MDR_V2_UUID];
  // The SDP record is the stronger statement: a Sony headset that also happens
  // to have a Fast Pair address is still driven over its own channel.
  assertEquals(Model.controlBackend(sony, ""), "sony");
  assertEquals(Model.controlBackend(sony, "48:B4:41:00:00:01"), "sony");
  // bluetoothctl prints them lowercase, but nothing guarantees it.
  assertEquals(Model.controlBackend([Model.SONY_MDR_V2_UUID.toUpperCase()], ""), "sony");
  // CSR GAIA in the SDP record is Xiaomi / QCC on SPP, and beats a BLE address
  // the same way Sony does: the UUID is the device's own claim.
  const xiaomi = [
    "00001101-0000-1000-8000-00805f9b34fb",
    Model.CSR_GAIA_UUID,
  ];
  assertEquals(Model.controlBackend(xiaomi, ""), "xiaomi");
  assertEquals(Model.controlBackend(xiaomi, "48:B4:41:00:00:01"), "xiaomi");
  assertEquals(Model.controlBackend([Model.CSR_GAIA_UUID.toUpperCase()], ""), "xiaomi");
  // Soundcore vendor UUID in SDP record picks soundcore backend.
  const soundcore = [
    "00001101-0000-1000-8000-00805f9b34fb",
    "0cf12d31-fac3-4553-bd80-d6832e7d1402",
  ];
  assertEquals(Model.controlBackend(soundcore, ""), "soundcore");
  assertEquals(Model.controlBackend(soundcore, "48:B4:41:00:00:01"), "soundcore");
  assertEquals(Model.controlBackend(["0CF12D31-FAC3-4553-BD80-D6832E7D1402"], ""), "soundcore");
  // Sony still wins when both vendor UUIDs are listed.
  assertEquals(
    Model.controlBackend([Model.CSR_GAIA_UUID, Model.SONY_MDR_V2_UUID], ""),
    "sony",
  );
  // No Sony, GAIA or Soundcore UUID: the BLE address from the Message Stream is what is left.
  assertEquals(Model.controlBackend([], "48:B4:41:00:00:01"), "jbl");
  assertEquals(Model.controlBackend(null, "48:B4:41:00:00:01"), "jbl");
  // Nothing to reach the device with.
  assertEquals(Model.controlBackend([], ""), "");
  assertEquals(Model.controlBackend(null, ""), "");
  assertEquals(Model.controlBackend([], "   "), "");
});

Deno.test("modesAvailable defaults to the JBL four and filters what Sony names", () => {
  // The JBL bridge names none: its protocol has one fixed set of slots.
  assertEquals(Model.modesAvailable({ modes: true, mode: "anc" }), [
    "off", "anc", "ambient", "talkthru",
  ]);
  assertEquals(Model.modesAvailable({}), ["off", "anc", "ambient", "talkthru"]);
  assertEquals(Model.modesAvailable(null), ["off", "anc", "ambient", "talkthru"]);
  // A Sony over-ear, in the panel's fixed order rather than the line's.
  assertEquals(
    Model.modesAvailable({ available: ["ambient", "off", "anc"] }),
    ["off", "anc", "ambient"],
  );
  // Names neither bridge should send are dropped, not drawn.
  assertEquals(Model.modesAvailable({ available: ["off", "wind"] }), ["off"]);
  // An explicit empty list means "offers nothing", which hides the row — very
  // different from a line that never mentioned the subject.
  assertEquals(Model.modesAvailable({ available: [] }), []);
});

Deno.test("a device-authored name can never read as rich text", () => {
  assertEquals(
    Model.deviceLabel({ name: '<img src="http://evil/x.png">' }),
    "‹img src=\"http://evil/x.png\"›",
  );
  assertEquals(
    Model.deviceLabel({ name: "", deviceName: "<b>Buds</b>" }),
    "‹b›Buds‹/b›",
  );
  assertEquals(Model.deviceLabel({ name: "JBL <3" }), "JBL ‹3");
});

Deno.test("shortError neutralises markup a helper quoted", () => {
  assertEquals(
    Model.shortError("boom: <img src=x>\n", "fallback"),
    "boom: ‹img src=x›",
  );
});

Deno.test("controlBackend picks nothing from the NT Link UUID", () => {
  const nothing = ["0000110b-0000-1000-8000-00805f9b34fb", Model.NOTHING_NT_LINK_UUID];
  assertEquals(Model.controlBackend(nothing, ""), "nothing");
  // A Fast Pair address does not outrank the device's own record.
  assertEquals(Model.controlBackend(nothing, "48:B4:41:00:00:01"), "nothing");
  assertEquals(Model.controlBackend([Model.NOTHING_NT_LINK_UUID.toUpperCase()], ""), "nothing");
  // Sony still wins; GAIA loses to Nothing the same way it loses to Sony.
  assertEquals(
    Model.controlBackend([Model.NOTHING_NT_LINK_UUID, Model.SONY_MDR_V2_UUID], ""),
    "sony",
  );
  assertEquals(
    Model.controlBackend([Model.CSR_GAIA_UUID, Model.NOTHING_NT_LINK_UUID], ""),
    "nothing",
  );
  assertEquals(Model.isClassicBackend("nothing"), true);
  assertEquals(Model.isClassicBackend("sony"), true);
  assertEquals(Model.isClassicBackend("xiaomi"), true);
  assertEquals(Model.isClassicBackend("soundcore"), true);
  assertEquals(Model.isClassicBackend("jbl"), false);
  assertEquals(Model.isClassicBackend(""), false);
});

Deno.test("ancLevelsAvailable is empty unless the bridge graded the noise cancelling", () => {
  // The JBL and Sony bridges never mention strengths: no row.
  assertEquals(Model.ancLevelsAvailable({ modes: true, mode: "anc" }), []);
  assertEquals(Model.ancLevelsAvailable({}), []);
  assertEquals(Model.ancLevelsAvailable(null), []);
  // The Nothing bridge's four, in the panel's order rather than the line's.
  assertEquals(
    Model.ancLevelsAvailable({ ancLevels: ["adaptive", "high", "low", "mid"] }),
    ["low", "mid", "high", "adaptive"],
  );
  assertEquals(Model.ancLevelsAvailable({ ancLevels: ["high", "wind"] }), ["high"]);
  assertEquals(Model.ancLevelsAvailable({ ancLevels: [] }), []);
});

Deno.test("ancLevel names only a strength the panel can draw", () => {
  assertEquals(Model.ancLevel({ ancLevel: "high" }), "high");
  assertEquals(Model.ancLevel({ ancLevel: "adaptive" }), "adaptive");
  assertEquals(Model.ancLevel({ ancLevel: "loud" }), "");
  assertEquals(Model.ancLevel({}), "");
  assertEquals(Model.ancLevel(null), "");
});

Deno.test("bridge battery reads what the line carried and nothing more", () => {
  const line = {
    modes: true,
    battery: { left: 85, right: 15, case: 85, charging: ["case"], caseStale: true },
  };
  assertEquals(Model.bridgeLevel(line, "left"), 85);
  assertEquals(Model.bridgeLevel(line, "right"), 15);
  assertEquals(Model.bridgeLevel(line, "case"), 85);
  // Not mentioned is not reported.
  assertEquals(Model.bridgeLevel(line, "headset"), -1);
  assertEquals(Model.bridgeCharging(line, "case"), true);
  assertEquals(Model.bridgeCharging(line, "left"), false);
  assertEquals(Model.bridgeCaseStale(line), true);
  // Out-of-range and non-numbers are "not reported", not clamped.
  assertEquals(Model.bridgeLevel({ battery: { left: 130 } }, "left"), -1);
  assertEquals(Model.bridgeLevel({ battery: { left: "85" } }, "left"), -1);
  assertEquals(Model.bridgeLevel({ battery: { left: -1 } }, "left"), -1);
  // A line with no battery, an array, or no line at all.
  assertEquals(Model.bridgeLevel({ modes: true, mode: "anc" }, "left"), -1);
  assertEquals(Model.bridgeLevel({ battery: [85] }, "0"), -1);
  assertEquals(Model.bridgeLevel(null, "left"), -1);
  assertEquals(Model.bridgeCharging(null, "left"), false);
  assertEquals(Model.bridgeCaseStale({ battery: { case: 50 } }), false);
  assertEquals(Model.bridgeCaseStale(null), false);
});
