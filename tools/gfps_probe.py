#!/usr/bin/env python3
"""Dump Google Fast Pair Message Stream frames from a paired Bluetooth device.

Registers an org.bluez.Profile1 for the Message Stream UUID, asks BlueZ to
connect it, and prints every frame it receives as group/code/payload.

Not quite a passive listener: 1.5 s after the channel opens it sends one frame,
08 11 00 00 — Fast Pair Hearable Control, "get the ANC state" — because the
device volunteers battery and firmware on its own but reports its listening
mode only when asked. Nothing else is ever written.

Usage: gfps_probe.py <bluetooth-address> [seconds]
"""
import os
import struct
import sys

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib

UUID = "df21fe2c-2515-4fdb-8886-f12c4d67927c"
PROFILE_PATH = "/io/github/ncr/omaphones/probe"

GROUPS = {1: "BLUETOOTH_EVENT", 2: "COMPANION_APP_EVENT", 3: "DEVICE_INFO",
          4: "DEVICE_ACTION", 5: "SASS", 8: "HEARABLE_CONTROL", 0xFF: "ACK"}


def parse_component(byte):
    if (byte & 0x7F) == 0x7F:
        return "n/a"
    return "%d%%%s" % (byte & 0x7F, " charging" if byte & 0x80 else "")


def show(group, code, payload):
    name = GROUPS.get(group, "?")
    print("frame group=0x%02x (%s) code=0x%02x len=%d payload=%s"
          % (group, name, code, len(payload), payload.hex()), flush=True)
    if group == 0x03 and code == 0x03:
        parts = [parse_component(b) for b in payload]
        labels = ["left", "right", "case"] if len(payload) == 3 else ["battery"]
        print("  BATTERY: " + ", ".join("%s=%s" % (l, v) for l, v in zip(labels, parts)),
              flush=True)
    if group == 0x03 and code == 0x09:
        print("  FIRMWARE: %s" % payload.decode("utf-8", "replace"), flush=True)
    if group == 0x08 and code == 0x13 and len(payload) >= 4:
        print("  ANC: version=%d uiToggles=0x%02x settable=0x%02x state=0x%02x"
              % (payload[0], payload[1], payload[2], payload[3]), flush=True)


class Reader:
    def __init__(self, fd):
        self.fd = fd
        self.buf = b""
        GLib.io_add_watch(fd, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self.on_io)

    def on_io(self, fd, condition):
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            print("socket closed by peer", flush=True)
            os.close(fd)
            return False
        try:
            data = os.read(fd, 4096)
        except OSError as e:
            print("read error: %s" % e, flush=True)
            return False
        if not data:
            print("EOF", flush=True)
            return False
        print("<<< %s" % data.hex(), flush=True)
        self.buf += data
        while len(self.buf) >= 4:
            length = struct.unpack(">H", self.buf[2:4])[0]
            if len(self.buf) < 4 + length:
                break
            group, code = self.buf[0], self.buf[1]
            payload = self.buf[4:4 + length]
            self.buf = self.buf[4 + length:]
            show(group, code, payload)
        return True

    def send(self, data):
        print(">>> %s" % data.hex(), flush=True)
        os.write(self.fd, data)


readers = []


class Profile(dbus.service.Object):
    @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
    def Release(self):
        print("Profile.Release", flush=True)

    @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}", out_signature="")
    def NewConnection(self, path, fd, properties):
        raw = fd.take()
        print("NewConnection from %s fd=%d props=%s" % (path, raw, dict(properties)), flush=True)
        reader = Reader(raw)
        readers.append(reader)
        # Ask for the ANC state as well: group 0x08, code 0x11, no payload.
        GLib.timeout_add(1500, lambda: (reader.send(bytes([0x08, 0x11, 0x00, 0x00])), False)[1])

    @dbus.service.method("org.bluez.Profile1", in_signature="o", out_signature="")
    def RequestDisconnection(self, path):
        print("RequestDisconnection %s" % path, flush=True)


# Which /org/bluez/hciN/dev_… object carries this address. Asking the object
# manager rather than assuming hci0 keeps the probe working on a machine whose
# only adapter is a USB dongle that came up as hci1.
def find_device_path(bus, address):
    wanted = address.upper()
    objects = dbus.Interface(bus.get_object("org.bluez", "/"),
                             "org.freedesktop.DBus.ObjectManager").GetManagedObjects()
    for path, interfaces in objects.items():
        device = interfaces.get("org.bluez.Device1")
        if device and str(device.get("Address", "")).upper() == wanted:
            return str(path)
    return None


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: gfps_probe.py <bluetooth-address> [seconds]")
    address = sys.argv[1]
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 20
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    Profile(bus, PROFILE_PATH)

    manager = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"),
                             "org.bluez.ProfileManager1")
    try:
        manager.RegisterProfile(PROFILE_PATH, UUID, {
            "Name": "Earbuds GFPS probe",
            "Role": "client",
            "RequireAuthentication": dbus.Boolean(False),
            "RequireAuthorization": dbus.Boolean(False),
            "AutoConnect": dbus.Boolean(True),
        })
    except dbus.exceptions.DBusException as error:
        # BlueZ allows one holder per profile UUID, and the widget's own reader
        # is usually it. Say so instead of dumping a traceback.
        sys.exit("gfps_probe: cannot register the Fast Pair profile (%s) — the channel is "
                 "already held, most likely by the widget's reader; stop it first with: "
                 "omarchy bar set io.github.ncr.omaphones useFastPair false --json"
                 % error.get_dbus_message())
    print("profile registered for %s" % UUID, flush=True)

    dev_path = find_device_path(bus, address)
    if not dev_path:
        sys.exit("gfps_probe: no paired device with address %s" % address)
    device = dbus.Interface(bus.get_object("org.bluez", dev_path), "org.bluez.Device1")

    def connect():
        try:
            device.ConnectProfile(UUID)
            print("ConnectProfile returned", flush=True)
        except dbus.DBusException as e:
            print("ConnectProfile failed: %s" % e.get_dbus_message(), flush=True)
        return False

    GLib.timeout_add(500, connect)
    loop = GLib.MainLoop()
    GLib.timeout_add_seconds(seconds, lambda: (loop.quit(), False)[1])
    loop.run()

    try:
        manager.UnregisterProfile(PROFILE_PATH)
    except dbus.DBusException:
        pass
    print("done", flush=True)


if __name__ == "__main__":
    main()
