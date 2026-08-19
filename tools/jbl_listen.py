#!/usr/bin/env python3
"""Listen on the JBL vendor RFCOMM channel and log every frame. Sends nothing.

Usage: jbl_listen.py <address> [seconds]
"""
import os
import sys
import time

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

UUID = os.environ.get("PROBE_UUID", "8a482a08-5507-42ac-b673-a88df48b3fc7")
PROFILE_PATH = "/io/github/ncr/omaphones/jbllisten"
START = time.monotonic()


def stamp():
    return "%7.2fs" % (time.monotonic() - START)


def checksum(data):
    return (~sum(data)) & 0xFF


class Reader:
    def __init__(self, fd):
        self.fd = fd
        self.buf = b""
        GLib.io_add_watch(fd, GLib.PRIORITY_DEFAULT,
                          GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self.on_io)

    def on_io(self, fd, condition):
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            print("%s !! closed by peer" % stamp(), flush=True)
            return False
        data = os.read(fd, 4096)
        if not data:
            return False
        print("%s <<< %s" % (stamp(), data.hex()), flush=True)
        self.buf += data
        while len(self.buf) >= 5:
            if self.buf[0] not in (0xAA, 0xBE):
                self.buf = self.buf[1:]
                continue
            total = 4 + self.buf[3] + 1
            if len(self.buf) < total:
                break
            packet, self.buf = self.buf[:total], self.buf[total:]
            ok = packet[-1] == checksum(packet[:-1])
            # The heartbeat is noise here; anything else is a real event.
            tag = "heartbeat" if packet[1] == 0x50 else "*** EVENT"
            print("%s     %s cmd=0x%02x seq=0x%02x payload=%s%s"
                  % (stamp(), tag, packet[1], packet[2], packet[4:-1].hex() or "-",
                     "" if ok else " [BAD CK]"), flush=True)
        return True


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: jbl_listen.py <address> [seconds]")
    address = sys.argv[1]
    seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 150

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    class Profile(dbus.service.Object):
        @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
        def Release(self):
            pass

        @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}", out_signature="")
        def NewConnection(self, path, fd, properties):
            print("%s == connected, listening only" % stamp(), flush=True)
            Reader(fd.take())

        @dbus.service.method("org.bluez.Profile1", in_signature="o", out_signature="")
        def RequestDisconnection(self, path):
            pass

    Profile(bus, PROFILE_PATH)
    manager = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"),
                             "org.bluez.ProfileManager1")
    manager.RegisterProfile(PROFILE_PATH, UUID, {
        "Name": "JBL listener",
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
            print("%s ConnectProfile: %s" % (stamp(), message), flush=True)
            if attempt < 10:
                GLib.timeout_add(1500, lambda: connect(attempt + 1))
        return False

    GLib.timeout_add(300, connect)
    loop = GLib.MainLoop()
    GLib.timeout_add_seconds(seconds, lambda: (loop.quit(), False)[1])
    loop.run()
    try:
        manager.UnregisterProfile(PROFILE_PATH)
    except dbus.DBusException:
        pass
    print("%s == done" % stamp(), flush=True)


if __name__ == "__main__":
    main()
