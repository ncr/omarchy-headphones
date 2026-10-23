#!/usr/bin/env python3
"""Probe a Redmi Buds Xiaomi channel: read the mode and battery, print every frame.

Usage: redmi_probe.py [--name NAME] [--listen SECONDS] [--cycle MODE[,MODE...]] <address>

Opens the earbuds' 0xFD2D service through BlueZ (a Profile1 registration, as
the widget's bridge does), asks for the noise control (GetDeviceConfig 11) and
the battery (GetTargetInfo), and prints each frame in both directions, raw and
decoded, with the time it was received. By default the probe only reads: it
sends no set, so there is no state to restore. `--listen` keeps it open for
that many seconds afterwards (default 3), for watching what the earbuds
announce on their own: a bud going into the case, a touch on a stem.

`--cycle off,anc,ambient` also sets those modes, one after another, and puts
the earbuds back. The initial mode is read first and nothing is written unless
it is known. Every set is checked against what the earbuds report back (their
announcement, or a read after it), and the mode the earbuds were in is set again
in a `finally` and checked the same way. If that cannot be done (the link
dropped, the earbuds did not agree) the probe says RESTORE FAILED and exits 2:
set the mode by hand. A mode change is audible, and cancelling can briefly cut
what is playing. Each mode is set with the strength the earbuds last reported
for it, or 0.

`--name` is the name the earbuds report, and picks their row in the bridge's
MODELS. Where the row says so (the Redmi Buds 3 Pro) the probe authenticates
first, as the bridge does, and sends nothing else until both sides have
confirmed; the earbuds' answer to its challenge is checked against its own
computation. Where the row says so it also answers each announcement the
earbuds make (0E, F4), as the bridge does: unanswered, they repeat it every two
seconds, and a stale mode would be read as the current one. Without `--name`
it is the Redmi Buds 5 conversation.

The widget's bridge holds the same service while the earbuds are connected and
mode control is on: switch `useModeControl` off first.

Exit codes: 0 done, 1 could not open the channel or it closed, 2 the earbuds
were not restored, 3 asked for a cycle but the initial mode was not known,
4 the authentication was not completed (nothing else was sent).
"""
import argparse
import importlib.machinery
import importlib.util
import os
import re
import select
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
UUID = "0000fd2d-0000-1000-8000-00805f9b34fb"
PROFILE_PATH = "/io/github/ncr/omaphones/redmi_probe"
ADDRESS = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")

EXIT_OK = 0
EXIT_LINK = 1
EXIT_NOT_RESTORED = 2
EXIT_NO_INITIAL = 3
EXIT_NO_AUTH = 4

ANSWER_WAIT = 3.0
SET_WAIT = 2.5
SETTLE = 0.3


def load_bridge():
    """The bridge's framing, so the probe cannot drift from what the widget reads."""
    path = os.path.join(HERE, "..", "redmi-bridge")
    loader = importlib.machinery.SourceFileLoader("redmi_bridge", path)
    spec = importlib.util.spec_from_loader("redmi_bridge", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class Probe:
    """The conversation, on an io with write(bytes) and read(timeout).

    read() returns bytes, b"" when nothing arrived in time, and None when the
    link has closed. The probe keeps the last mode and battery the earbuds
    reported, whichever way they said it."""

    def __init__(self, bridge, io, out, clock=time.monotonic, model=None):
        self.bridge = bridge
        self.model = model or bridge.NAMELESS
        self.io = io
        self.out = out
        self.clock = clock
        self.start = clock()
        self.buffer = bytearray()
        self.sn = 0
        self.noise = None       # (state, level) as last reported
        self.battery = None
        self.levels = {}        # state -> the level it was last seen at
        self.closed = False
        self.rejected = False   # a set was answered with an error status
        self.challenge = None   # ours, while authenticating
        self.ours_verified = False
        self.theirs_confirmed = False
        self.auth_failed = False

    # ---- output

    def say(self, text):
        self.out("%6.2fs %s" % (self.clock() - self.start, text))

    def describe(self, frame):
        is_command, opcode, status, payload = self.bridge.parts_of(frame)
        if opcode == self.bridge.OP_AUTH_CHALLENGE:
            if is_command:
                return "their authentication challenge"
            if self.challenge is None:
                return "an answer to a challenge we did not send"
            expected = b"\x01" + self.bridge.auth_response(self.challenge)
            if status == 0 and payload == expected:
                return "their answer to our challenge: matches"
            return "their answer to our challenge: WRONG (status %s)" % status
        if opcode == self.bridge.OP_AUTH_CONFIRM:
            return ("their authentication confirmation" if is_command
                    else "our confirmation acknowledged (status %s)" % status)
        noise = self.bridge.noise_of(frame)
        battery = self.bridge.battery_of(frame)
        if noise is not None:
            name = self.bridge.MODE_FROM_STATE[noise[0]]
            return "noise control %s (state %d, level %d)" % (name, noise[0], noise[1])
        if battery is not None:
            charging = ",".join(battery["charging"]) or "none"
            levels = ", ".join("%s %d%%" % (part, battery[part])
                               for part in self.bridge.PARTS if part in battery)
            return "battery %s; charging: %s" % (levels, charging)
        if not is_command and opcode == self.bridge.OP_SET_CONFIG:
            return "set acknowledged" if status == 0 else "set REFUSED (status %d)" % status
        if is_command and opcode == 0x0E:
            return "status report (the earbuds' own)"
        return "not read"

    # ---- traffic

    def send(self, frame, what):
        if self.closed:
            self.say("not sent, the link is closed: %s" % what)
            return
        self.say("TX  %s  # %s" % (frame.hex(" "), what))
        try:
            self.io.write(frame)
        except OSError as error:
            self.closed = True
            self.say("write failed: %s" % error)

    def next_sn(self):
        self.sn = (self.sn + 1) & 0xFF
        return self.sn

    def ask(self):
        self.send(self.bridge.encode_get_noise(self.next_sn()), "get the noise control")
        self.send(self.bridge.encode_get_target_info(self.next_sn()), "get the battery")

    def pump(self, seconds, until=None):
        """Read for up to `seconds`, or until `until()` is true."""
        deadline = self.clock() + seconds
        while not self.closed and self.clock() < deadline:
            if until and until():
                return True
            data = self.io.read(max(0.0, deadline - self.clock()))
            if data is None:
                self.closed = True
                self.say("link closed")
                return False
            if not data:
                continue
            self.buffer += data
            while True:
                frame, self.buffer = self.bridge.split_frame(self.buffer)
                if frame is None:
                    break
                self.take(frame)
        return bool(until and until())

    def take(self, frame):
        self.say("RX  %s  # %s" % (frame.hex(" "), self.describe(frame)))
        if self.challenge is not None and not (self.ours_verified and self.theirs_confirmed):
            self.take_auth(frame)
            return
        is_command, opcode, status, _payload = self.bridge.parts_of(frame)
        if self.model["acknowledge"] and is_command and frame[3] & self.bridge.FLAG_WANTS_RESPONSE \
                and opcode in self.bridge.ANNOUNCEMENTS:
            self.send(self.bridge.encode_response(opcode, frame[7]), "acknowledge it")
        noise = self.bridge.noise_of(frame)
        if noise is not None:
            self.noise = noise
            self.levels[noise[0]] = noise[1]
        battery = self.bridge.battery_of(frame)
        if battery is not None:
            self.battery = battery
        if not is_command and opcode == self.bridge.OP_SET_CONFIG and status != 0:
            self.rejected = True

    # ---- authentication, for a model whose row asks for it

    def authenticate(self, challenge):
        """Both challenges, as the bridge runs them. True once both sides confirmed."""
        self.challenge = challenge
        self.send(self.bridge.encode_auth_challenge(self.next_sn(), challenge),
                  "our authentication challenge")
        done = self.pump(ANSWER_WAIT, until=lambda: self.auth_failed
                         or (self.ours_verified and self.theirs_confirmed))
        ok = done and not self.auth_failed
        self.say("authenticated" if ok else "NOT AUTHENTICATED: nothing else is sent")
        return ok

    def take_auth(self, frame):
        bridge = self.bridge
        is_command, opcode, status, payload = bridge.parts_of(frame)
        if is_command and opcode == bridge.OP_AUTH_CHALLENGE \
                and len(payload) == 17 and payload[0] == 1:
            self.send(bridge.encode_response(bridge.OP_AUTH_CHALLENGE, frame[7],
                                             b"\x01" + bridge.auth_response(payload[1:])),
                      "our answer to their challenge")
        elif is_command and opcode == bridge.OP_AUTH_CONFIRM and self.ours_verified:
            self.theirs_confirmed = True
            self.send(bridge.encode_response(bridge.OP_AUTH_CONFIRM, frame[7], b"\x01"),
                      "acknowledge their confirmation")
        elif not is_command and opcode == bridge.OP_AUTH_CHALLENGE:
            if status != 0 or payload != b"\x01" + bridge.auth_response(self.challenge):
                self.auth_failed = True
                return
            self.ours_verified = True
            self.send(bridge.encode_auth_confirm(self.next_sn()), "our confirmation")

    # ---- a set, checked against what the earbuds say

    def set_mode(self, state, level):
        """Set a state and report whether the earbuds say they are in it."""
        name = self.bridge.MODE_FROM_STATE[state]
        self.rejected = False
        self.noise = None
        self.send(self.bridge.encode_set_noise(self.next_sn(), state, level),
                  "set %s (state %d, level %d)" % (name, state, level))
        # Their own announcement, normally; failing that, ask.
        self.pump(SET_WAIT, until=lambda: self.noise is not None or self.rejected)
        if self.noise is None and not self.closed and not self.rejected:
            self.send(self.bridge.encode_get_noise(self.next_sn()), "read it back")
            self.pump(ANSWER_WAIT, until=lambda: self.noise is not None)
        confirmed = self.noise is not None and self.noise[0] == state
        self.say("%s: %s" % (name, "the earbuds agree" if confirmed else "NOT CONFIRMED"))
        # What follows the announcement (the acknowledgement, a closing link)
        # is read before anything else is written.
        self.pump(SETTLE)
        return confirmed and not self.closed


def run(bridge, io, modes, listen, out, clock=time.monotonic,
        model=None, challenge=os.urandom):
    """The whole probe. Returns the exit code."""
    probe = Probe(bridge, io, out, clock, model)
    if model and model["authenticate"]:
        if not probe.authenticate(challenge(16)):
            return EXIT_LINK if probe.closed else EXIT_NO_AUTH
    probe.ask()
    probe.pump(ANSWER_WAIT, until=lambda: probe.noise is not None and probe.battery is not None)
    if probe.closed:
        return EXIT_LINK
    if probe.noise is None:
        probe.say("the earbuds did not report their noise control")
    if probe.battery is None:
        probe.say("the earbuds did not report their battery")
    if not modes:
        probe.pump(listen)
        return EXIT_LINK if probe.closed else EXIT_OK

    if probe.noise is None:
        probe.say("the initial mode is unknown: nothing is written")
        return EXIT_NO_INITIAL
    initial = probe.noise
    probe.say("initial mode: %s (state %d, level %d)"
              % (bridge.MODE_FROM_STATE[initial[0]], initial[0], initial[1]))
    code = EXIT_OK
    try:
        for mode in modes:
            state = bridge.STATE_FROM_MODE[mode]
            level = probe.levels.get(state, 0)
            if probe.closed:
                break
            probe.set_mode(state, level)
    finally:
        if probe.closed:
            probe.say("RESTORE FAILED: the link closed; the earbuds may not be in %s"
                      % bridge.MODE_FROM_STATE[initial[0]])
            code = EXIT_NOT_RESTORED
        elif probe.set_mode(initial[0], initial[1]):
            probe.say("restored: %s" % bridge.MODE_FROM_STATE[initial[0]])
        else:
            probe.say("RESTORE FAILED: set %s by hand" % bridge.MODE_FROM_STATE[initial[0]])
            code = EXIT_NOT_RESTORED
    return code


class Channel:
    """The channel through BlueZ: a Profile1 for 0xFD2D, the descriptor it hands over."""

    def __init__(self, address):
        import dbus
        import dbus.mainloop.glib
        import dbus.service
        from gi.repository import GLib
        self.dbus = dbus
        self.GLib = GLib
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.loop = GLib.MainLoop()
        self.fd = None
        self.error = None
        channel = self

        class Profile(dbus.service.Object):
            @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
            def Release(self):
                pass

            @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}", out_signature="")
            def NewConnection(self, path, fd, properties):
                channel.fd = fd.take()
                channel.loop.quit()

            @dbus.service.method("org.bluez.Profile1", in_signature="o", out_signature="")
            def RequestDisconnection(self, path):
                channel.fd = None

        self.profile = Profile(self.bus, PROFILE_PATH)
        self.address = address
        self.manager = dbus.Interface(self.bus.get_object("org.bluez", "/org/bluez"),
                                      "org.bluez.ProfileManager1")
        self.registered = False

    def open(self):
        dbus = self.dbus
        path = "/org/bluez/hci0/dev_" + self.address.upper().replace(":", "_")
        self.manager.RegisterProfile(PROFILE_PATH, UUID, {
            "Name": "Omaphones Redmi probe", "Role": "client",
            "Channel": dbus.UInt16(0),
            "RequireAuthentication": dbus.Boolean(False),
            "RequireAuthorization": dbus.Boolean(False),
            "AutoConnect": dbus.Boolean(False)})
        self.registered = True
        device = dbus.Interface(self.bus.get_object("org.bluez", path), "org.bluez.Device1")

        def failed(error):
            self.error = error.get_dbus_message()
            self.loop.quit()

        device.ConnectProfile(UUID, reply_handler=lambda: None, error_handler=failed,
                              timeout=15000)
        self.GLib.timeout_add(20000, self.loop.quit)
        self.loop.run()
        return self.fd is not None

    def write(self, data):
        written = 0
        while written < len(data):
            written += os.write(self.fd, data[written:])

    def read(self, timeout):
        if self.fd is None:
            return None
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return b""
        try:
            data = os.read(self.fd, 4096)
        except OSError:
            return None
        return data if data else None

    def close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        if self.registered:
            try:
                self.manager.UnregisterProfile(PROFILE_PATH)
            except self.dbus.DBusException:
                pass
            self.registered = False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("address")
    parser.add_argument("--name", default="", metavar="NAME",
                        help="the name the earbuds report, for their row in MODELS")
    parser.add_argument("--listen", type=float, default=3.0, metavar="SECONDS")
    parser.add_argument("--cycle", default="", metavar="MODES",
                        help="set these modes in turn, then restore (off, anc, ambient)")
    args = parser.parse_args(argv)
    if not ADDRESS.match(args.address):
        parser.error("not a Bluetooth address: %r" % args.address)
    bridge = load_bridge()
    modes = [m for m in args.cycle.split(",") if m]
    for mode in modes:
        if mode not in bridge.STATE_FROM_MODE:
            parser.error("unknown mode %r (off, anc, ambient)" % mode)

    model = None
    if args.name:
        if args.name not in bridge.MODELS:
            parser.error("no Redmi model row for %r (%s)"
                         % (args.name, ", ".join(sorted(bridge.MODELS))))
        model = bridge.MODELS[args.name]

    channel = Channel(args.address)
    try:
        if not channel.open():
            print("could not open the channel%s" % (": " + channel.error if channel.error else ""),
                  file=sys.stderr)
            return EXIT_LINK
        return run(bridge, channel, modes, args.listen, print, model=model)
    except KeyboardInterrupt:
        return EXIT_LINK
    finally:
        channel.close()


if __name__ == "__main__":
    sys.exit(main())
