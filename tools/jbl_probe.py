#!/usr/bin/env python3
"""Talk the JBL vendor protocol on RFCOMM UUID 8a482a08-5507-42ac-b673-a88df48b3fc7.

Frame, deduced from the device's own replies:

    magic  cmd  seq  len  payload[len]  checksum
    0xAA = request, 0xBE = response/notification
    checksum = (~sum(all preceding bytes)) & 0xFF

Usage: jbl_probe.py <address> [name-of-frame ...]
"""
import os
import sys

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

UUID = os.environ.get("PROBE_UUID", "8a482a08-5507-42ac-b673-a88df48b3fc7")
PROFILE_PATH = "/io/github/ncr/omaphones/jblprobe"

REQ, RESP = 0xAA, 0xBE

CMD_NAMES = {
    0x21: "version", 0x25: "battery", 0x50: "notify-50", 0x91: "anc/mode",
    0x82: "audio-get", 0x83: "audio", 0x94: "model", 0x96: "profiles",
    0x9B: "enable-notify", 0x77: "caps", 0x12: "name",
}


def checksum(data):
    return (~sum(data)) & 0xFF


def frame(cmd, payload=b"", seq=0x00):
    head = bytes([REQ, cmd, seq, len(payload)]) + bytes(payload)
    return head + bytes([checksum(head)])


FRAMES = {
    "notify-on":  frame(0x9B, [0x01, 0x01]),
    "version-a":  frame(0x21, [0x30]),
    "version-b":  frame(0x21, [0x35]),
    "battery":    frame(0x25, [0x00]),
    "anc":        frame(0x91, [0x11]),
    "audio":      frame(0x82, []),
    "caps":       frame(0x77, [0x01, 0xFF]),
    "model":      frame(0x94, [0x01]),
    "profiles":   frame(0x96, [0x01]),
}


def decode(magic, cmd, seq, payload, valid):
    print("    %s cmd=0x%02x (%s) seq=0x%02x len=%d payload=%s%s"
          % ("RESP" if magic == RESP else "REQ ", cmd, CMD_NAMES.get(cmd, "?"),
             seq, len(payload), payload.hex() or "-",
             "" if valid else "  [BAD CHECKSUM]"), flush=True)
    if cmd == 0x25 and len(payload) >= 3:
        print("      battery: %s" % " ".join("%d" % b for b in payload), flush=True)
    if cmd == 0x91 and len(payload) >= 2:
        slots = {0x01: "anc", 0x02: "ambient", 0x03: "voice", 0x10: "set", 0x11: "query"}
        pairs = ["%s=%d" % (slots.get(payload[i], "slot0x%02x" % payload[i]), payload[i + 1])
                 for i in range(0, len(payload) - 1, 2)]
        print("      mode: %s" % ", ".join(pairs), flush=True)
    if cmd in (0x94, 0x12, 0x21) and payload:
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in payload)
        print("      text: %s" % text, flush=True)


class Reader:
    def __init__(self, fd, plan):
        self.fd = fd
        self.buf = b""
        self.plan = plan
        GLib.io_add_watch(fd, GLib.PRIORITY_DEFAULT,
                          GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self.on_io)
        for index, name in enumerate(plan):
            GLib.timeout_add(1200 + index * 1400, lambda n=name: (self.send(n), False)[1])

    def on_io(self, fd, condition):
        # Returning False drops the watch but not the descriptor, and the probe
        # keeps running until its timer expires — so close it here, or BlueZ is
        # left holding a half of a socket nobody reads.
        # The descriptor is gone once either branch below runs, so mark it as
        # such: a timer that fires afterwards must not write into a number that
        # now belongs to some other file.
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            print("!! closed by peer", flush=True)
            os.close(fd)
            self.fd = -1
            return False
        data = os.read(fd, 4096)
        if not data:
            print("!! EOF", flush=True)
            os.close(fd)
            self.fd = -1
            return False
        print("<<< %s" % data.hex(), flush=True)
        self.buf += data
        self.drain()
        return True

    def drain(self):
        while len(self.buf) >= 5:
            if self.buf[0] not in (REQ, RESP):
                self.buf = self.buf[1:]
                continue
            length = self.buf[3]
            total = 4 + length + 1
            if len(self.buf) < total:
                return
            packet, self.buf = self.buf[:total], self.buf[total:]
            valid = packet[-1] == checksum(packet[:-1])
            decode(packet[0], packet[1], packet[2], packet[4:-1], valid)

    def send(self, name):
        if self.fd < 0:
            print(">>> %-10s skipped, the channel is closed" % name, flush=True)
            return
        data = FRAMES[name]
        print(">>> %-10s %s" % (name, data.hex()), flush=True)
        try:
            os.write(self.fd, data)
        except OSError as error:
            print("!! write failed: %s" % error, flush=True)


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: jbl_probe.py <address> [name-of-frame ...]")
    address = sys.argv[1]
    plan = sys.argv[2:] or ["notify-on", "version-a", "battery", "anc", "model", "caps"]
    for name in plan:
        if name not in FRAMES:
            print("unknown frame %r; known: %s" % (name, ", ".join(FRAMES)))
            return

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    class Profile(dbus.service.Object):
        @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
        def Release(self):
            pass

        @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}", out_signature="")
        def NewConnection(self, path, fd, properties):
            print("== connected", flush=True)
            Reader(fd.take(), plan)

        @dbus.service.method("org.bluez.Profile1", in_signature="o", out_signature="")
        def RequestDisconnection(self, path):
            pass

    Profile(bus, PROFILE_PATH)
    manager = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"),
                             "org.bluez.ProfileManager1")
    manager.RegisterProfile(PROFILE_PATH, UUID, {
        "Name": "JBL probe",
        "Role": "client",
        "RequireAuthentication": dbus.Boolean(False),
        "RequireAuthorization": dbus.Boolean(False),
        "AutoConnect": dbus.Boolean(True),
    })

    dev = "/org/bluez/hci0/dev_" + address.upper().replace(":", "_")

    def connect(attempt=0):
        try:
            dbus.Interface(bus.get_object("org.bluez", dev),
                           "org.bluez.Device1").ConnectProfile(UUID)
        except dbus.DBusException as error:
            message = error.get_dbus_message()
            print("ConnectProfile: %s" % message, flush=True)
            # br-connection-busy just means another profile is mid-handshake.
            if "busy" in message and attempt < 8:
                GLib.timeout_add(1500, lambda: connect(attempt + 1))
        return False

    GLib.timeout_add(300, connect)
    loop = GLib.MainLoop()
    GLib.timeout_add_seconds(int(os.environ.get("PROBE_SECONDS", "20")),
                             lambda: (loop.quit(), False)[1])
    loop.run()
    try:
        manager.UnregisterProfile(PROFILE_PATH)
    except dbus.DBusException:
        pass
    print("== done", flush=True)


if __name__ == "__main__":
    main()
