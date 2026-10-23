#!/usr/bin/env python3
"""Probe EarFun earbuds over SPP: read the noise control, print every frame.

Usage: earfun_probe.py [--listen SECONDS] [--cycle MODE[,MODE...]] <address>

Opens standard SPP (`00001101-…`) through BlueZ (a Profile1 registration, as
the widget's bridge does), asks for the firmware (0309) and the noise control
(0315), and prints each frame in both directions, raw and decoded, with the
time it was received. A read that held several frames is printed as it came,
then frame by frame. By default the probe only reads: it sends no set, so there
is no state to restore. `--listen` keeps it open for that many seconds
afterwards (default 3), for watching what the earbuds send on their own.

`--cycle off,anc,ambient` also sets those modes, one after another, and puts
the earbuds back. The initial mode is read first and nothing is written unless
it is known. The earbuds do not acknowledge a set, and the get answers the old
mode until the change is done, so each set is checked by asking again every
RECHECK_MS, RECHECKS times at most, as the bridge does. The mode the earbuds
were in is set again in a `finally` and checked the same way. If that cannot be done (the
link dropped, the earbuds did not agree) the probe says RESTORE FAILED and
exits 2: set the mode by hand. A mode change is audible.

Nothing else holds this channel while the widget has no earfun row for the
earbuds; once it has, switch `useModeControl` off first.

Exit codes: 0 done, 1 could not open the channel or it closed, 2 the earbuds
were not restored, 3 asked for a cycle but the initial mode was not known.
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
PROFILE_PATH = "/io/github/ncr/omaphones/earfun_probe"
ADDRESS = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")

EXIT_OK = 0
EXIT_LINK = 1
EXIT_NOT_RESTORED = 2
EXIT_NO_INITIAL = 3

GET_FIRMWARE = 0x0309
ANSWER_WAIT = 3.0
SETTLE = 0.3


def load_bridge():
    """The bridge's framing, so the probe cannot drift from what the widget reads."""
    path = os.path.join(HERE, "..", "earfun-bridge")
    loader = importlib.machinery.SourceFileLoader("earfun_bridge", path)
    spec = importlib.util.spec_from_loader("earfun_bridge", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class Probe:
    """The conversation, on an io with write(bytes) and read(timeout).

    read() returns bytes, b"" when nothing arrived in time, and None when the
    link has closed. The probe keeps the last mode the earbuds reported."""

    def __init__(self, bridge, io, out, clock=time.monotonic):
        self.bridge = bridge
        self.io = io
        self.out = out
        self.clock = clock
        self.start = clock()
        self.buffer = bytearray()
        self.mode = None
        self.closed = False

    def say(self, text):
        self.out("%7.3fs %s" % (self.clock() - self.start, text))

    def describe(self, frame):
        mode = self.bridge.mode_of(frame)
        if mode is not None:
            return "noise control %s" % mode
        vendor, command, payload = self.bridge.parts_of(frame)
        if vendor == self.bridge.VENDOR and command == GET_FIRMWARE | self.bridge.ACK \
                and payload[:1] == b"\x00":
            return "firmware %s" % payload[1:].decode("ascii", "replace")
        if command & self.bridge.ACK:
            return "answer to %04x, not read" % (command & 0x7FFF)
        return "the earbuds' own %04x, not read" % command

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
            self.say("RX  %s" % data.hex(" "))
            self.buffer += data
            while True:
                frame, self.buffer = self.bridge.split_frame(self.buffer)
                if frame is None:
                    break
                self.say("    frame %s  # %s" % (frame.hex(" "), self.describe(frame)))
                mode = self.bridge.mode_of(frame)
                if mode is not None:
                    self.mode = mode
        return bool(until and until())

    def ask(self, what="get the noise control"):
        self.mode = None
        self.send(self.bridge.encode_get_mode(), what)
        self.pump(ANSWER_WAIT, until=lambda: self.mode is not None)

    def set_mode(self, mode):
        """Set a mode and report whether the earbuds say they are in it."""
        self.send(self.bridge.encode_set_mode(mode), "set %s" % mode)
        # No acknowledgement comes: ask as the bridge does, until the earbuds
        # say the mode or the bridge would have given up.
        for _ in range(self.bridge.RECHECKS):
            self.pump(self.bridge.RECHECK_MS / 1000.0)
            self.ask("read it back")
            if self.mode == mode or self.closed:
                break
        confirmed = self.mode == mode
        self.say("%s: %s" % (mode, "the earbuds agree" if confirmed else "NOT CONFIRMED"))
        self.pump(SETTLE)
        return confirmed and not self.closed


def run(bridge, io, modes, listen, out, clock=time.monotonic):
    """The whole probe. Returns the exit code."""
    probe = Probe(bridge, io, out, clock)
    probe.send(bridge.encode(GET_FIRMWARE), "get the firmware")
    probe.pump(1.0)
    probe.ask()
    if probe.closed:
        return EXIT_LINK
    if probe.mode is None:
        probe.say("the earbuds did not report their noise control")
    if not modes:
        probe.pump(listen)
        return EXIT_LINK if probe.closed else EXIT_OK

    if probe.mode is None:
        probe.say("the initial mode is unknown: nothing is written")
        return EXIT_NO_INITIAL
    initial = probe.mode
    probe.say("initial mode: %s" % initial)
    code = EXIT_OK
    try:
        for mode in modes:
            if probe.closed:
                break
            probe.set_mode(mode)
    except KeyboardInterrupt:
        probe.say("interrupted: putting the earbuds back")
    finally:
        if probe.closed:
            probe.say("RESTORE FAILED: the link closed; the earbuds may not be in %s" % initial)
            code = EXIT_NOT_RESTORED
        elif probe.set_mode(initial):
            probe.say("restored: %s" % initial)
        else:
            probe.say("RESTORE FAILED: set %s by hand" % initial)
            code = EXIT_NOT_RESTORED
    if code == EXIT_OK:
        probe.pump(listen)
    return code


class Channel:
    """SPP through BlueZ: a Profile1 for 00001101, the descriptor it hands over."""

    def __init__(self, bridge, address):
        import dbus
        import dbus.mainloop.glib
        import dbus.service
        from gi.repository import GLib
        self.dbus = dbus
        self.GLib = GLib
        self.bridge = bridge
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
        path = self.bridge.find_device_path(self.bus, self.address)
        if not path:
            self.error = "no paired device with address %s" % self.address
            return False
        self.manager.RegisterProfile(PROFILE_PATH, self.bridge.UUID, {
            "Name": "Omaphones EarFun probe", "Role": "client",
            "RequireAuthentication": dbus.Boolean(False),
            "RequireAuthorization": dbus.Boolean(False),
            "AutoConnect": dbus.Boolean(False)})
        self.registered = True
        device = dbus.Interface(self.bus.get_object("org.bluez", path), "org.bluez.Device1")

        def failed(error):
            self.error = error.get_dbus_message()
            self.loop.quit()

        device.ConnectProfile(self.bridge.UUID, reply_handler=lambda: None,
                              error_handler=failed, timeout=15000)
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
    parser.add_argument("--listen", type=float, default=3.0, metavar="SECONDS")
    parser.add_argument("--cycle", default="", metavar="MODES",
                        help="set these modes in turn, then restore (off, anc, ambient)")
    args = parser.parse_args(argv)
    if not ADDRESS.match(args.address):
        parser.error("not a Bluetooth address: %r" % args.address)
    bridge = load_bridge()
    modes = [m for m in args.cycle.split(",") if m]
    for mode in modes:
        if mode not in bridge.VALUE_FROM_MODE:
            parser.error("unknown mode %r (off, anc, ambient)" % mode)

    channel = Channel(bridge, args.address)
    try:
        if not channel.open():
            print("could not open the channel%s" % (": " + channel.error if channel.error else ""),
                  file=sys.stderr)
            return EXIT_LINK
        return run(bridge, channel, modes, args.listen, lambda text: print(text, flush=True))
    except KeyboardInterrupt:
        return EXIT_LINK
    finally:
        channel.close()


if __name__ == "__main__":
    sys.exit(main())
