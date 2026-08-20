#!/usr/bin/env python3
"""Probe Compact GAIA on Xiaomi Buds 5 Pro: handshake, GET mode, optional SET.

Usage: xiaomi_probe.py <address> [seconds] [set:off|anc|ambient]

Registers an org.bluez.Profile1 for standard SPP, lets BlueZ connect it, sends
the GAIA handshake (vendor 0x000A cmd 0x0300), then GET 0x001D/0x1003. Optional
`set:` writes one 1-byte SET 0x1004 afterwards. Prints every frame.

The widget's xiaomi-bridge holds the same SPP profile, so turn useModeControl
off before running this, or BlueZ will refuse the registration.
"""
import os
import struct
import sys
import time

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

UUID = "00001101-0000-1000-8000-00805f9b34fb"
PROFILE_PATH = "/io/github/ncr/omaphones/xiaomiprobe"
START = time.monotonic()

GAIA_VENDOR, DEVICE_VENDOR = 0x000A, 0x001D
HANDSHAKE, GET_MODE, SET_MODE = 0x0300, 0x1003, 0x1004
# 0x04 reboots Xiaomi Buds 5 Pro - never a set: value.
SET_BYTE = {"off": 0x00, "anc": 0x01, "ambient": 0x02}


def stamp():
    return "%7.2fs" % (time.monotonic() - START)


def frame(version, vendor, command, payload=b""):
    return bytes([0xFF, version & 0xFF, 0x00, len(payload)]) + struct.pack(
        ">HH", vendor, command) + payload


def decode(raw):
    out = []
    i = 0
    while i + 8 <= len(raw) and raw[i] == 0xFF:
        plen = raw[i + 3]
        vendor, command = struct.unpack(">HH", raw[i + 4:i + 8])
        payload = raw[i + 8:i + 8 + plen]
        if len(payload) < plen:
            break
        out.append("ver=%d vendor=%04x cmd=%04x payload=%s" % (
            raw[i + 1], vendor, command, payload.hex() or "-"))
        i += 8 + plen
    return out or [raw.hex()]


class Link:
    def __init__(self, fd, plan):
        self.fd = fd
        GLib.io_add_watch(fd, GLib.PRIORITY_DEFAULT,
                          GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self.on_io)
        delay = 400
        for name, data in plan:
            GLib.timeout_add(delay, lambda n=name, d=data: (self.send(n, d), False)[1])
            delay += 700

    def on_io(self, fd, condition):
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            print("%s !! closed" % stamp(), flush=True)
            self.fd = -1
            return False
        data = os.read(fd, 4096)
        if not data:
            print("%s !! EOF" % stamp(), flush=True)
            self.fd = -1
            return False
        print("%s <<< %s" % (stamp(), data.hex()), flush=True)
        for line in decode(data):
            print("%s     %s" % (stamp(), line), flush=True)
        return True

    def send(self, name, data):
        if self.fd < 0:
            return
        print("%s >>> %s %s" % (stamp(), name, data.hex()), flush=True)
        try:
            os.write(self.fd, data)
        except OSError as error:
            print("%s !! write: %s" % (stamp(), error), flush=True)


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: xiaomi_probe.py <address> [seconds] [set:off|anc|ambient]")
        return 0
    address = argv[0]
    seconds = 12
    wanted = None
    for arg in argv[1:]:
        if arg.startswith("set:"):
            wanted = arg.split(":", 1)[1].strip().lower()
            if wanted not in SET_BYTE:
                sys.exit("unknown mode %r (off, anc, ambient)" % wanted)
        else:
            seconds = int(arg)

    plan = [
        ("hs", frame(3, GAIA_VENDOR, HANDSHAKE)),
        ("get", frame(3, DEVICE_VENDOR, GET_MODE)),
    ]
    if wanted is not None:
        plan.append(("set-%s" % wanted, frame(3, DEVICE_VENDOR, SET_MODE,
                                              bytes([SET_BYTE[wanted]]))))
        plan.append(("get2", frame(3, DEVICE_VENDOR, GET_MODE)))

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    loop = GLib.MainLoop()
    link = {"l": None}

    class Profile(dbus.service.Object):
        @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
        def Release(self):
            pass

        @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}",
                             out_signature="")
        def NewConnection(self, path, fd, properties):
            print("%s == connected" % stamp(), flush=True)
            link["l"] = Link(fd.take(), plan)

        @dbus.service.method("org.bluez.Profile1", in_signature="o", out_signature="")
        def RequestDisconnection(self, path):
            print("%s == BlueZ asked to disconnect" % stamp(), flush=True)

    Profile(bus, PROFILE_PATH)
    manager = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"),
                             "org.bluez.ProfileManager1")
    manager.RegisterProfile(PROFILE_PATH, UUID, {
        "Name": "Xiaomi probe",
        "Role": "client",
        "Channel": dbus.UInt16(0),
        "RequireAuthentication": dbus.Boolean(False),
        "RequireAuthorization": dbus.Boolean(False),
        "AutoConnect": dbus.Boolean(False),
    })

    def device_path():
        objects = dbus.Interface(bus.get_object("org.bluez", "/"),
                                 "org.freedesktop.DBus.ObjectManager").GetManagedObjects()
        want = address.upper()
        for path, ifaces in objects.items():
            dev = ifaces.get("org.bluez.Device1")
            if dev and str(dev.get("Address", "")).upper() == want:
                return path
        sys.exit("no paired device with address %s" % address)

    dev = device_path()

    def connect(attempt=0):
        def failed(error):
            print("%s ConnectProfile: %s" % (stamp(), error.get_dbus_message()), flush=True)
            if attempt < 10:
                GLib.timeout_add(1500, lambda: connect(attempt + 1))

        dbus.Interface(bus.get_object("org.bluez", dev), "org.bluez.Device1").ConnectProfile(
            UUID, reply_handler=lambda: None, error_handler=failed, timeout=30)
        return False

    GLib.timeout_add(500, connect)
    GLib.timeout_add_seconds(seconds, lambda: (loop.quit(), False)[1])
    loop.run()
    try:
        manager.UnregisterProfile(PROFILE_PATH)
    except dbus.DBusException:
        pass
    print("%s == done" % stamp(), flush=True)


if __name__ == "__main__":
    main()
