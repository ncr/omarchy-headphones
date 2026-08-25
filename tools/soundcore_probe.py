#!/usr/bin/env python3
"""Probe Soundcore listening mode over RFCOMM.

Registers an org.bluez.Profile1 for the Soundcore vendor UUID (0cf12d31-fac3-4553-bd80-d6832e7...),
connects the socket, and sends a state query (0x01, 0x01), optionally setting a mode.

Usage: soundcore_probe.py <address> [seconds] [set:off|anc|ambient]
"""
import datetime
import os
import re
import sys

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

SOUNDCORE_UUID_PREFIX = "0cf12d31-fac3-4553-bd80-d6832e7"
DEFAULT_UUID = "0cf12d31-fac3-4553-bd80-d6832e700000"
PROFILE_PATH = "/io/github/ncr/omaphones/soundcore_probe"

OUTBOUND_HDR = bytes([0x08, 0xEE, 0x00, 0x00, 0x00])

CMD_STATE_UPDATE = (0x01, 0x01)
CMD_SOUND_MODES_NOTIFY = (0x06, 0x01)
CMD_SOUND_MODES_SET = (0x06, 0x81)

SET_BYTE = {"anc": 0x00, "ambient": 0x01, "off": 0x02}
MODE_NAME = {0x00: "anc", 0x01: "ambient", 0x02: "off"}


def stamp():
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]


def calc_checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def make_packet(cmd: tuple[int, int], body: bytes = b"") -> bytes:
    total_len = 5 + 2 + 2 + len(body) + 1
    raw = OUTBOUND_HDR + bytes([cmd[0], cmd[1], total_len & 0xFF, (total_len >> 8) & 0xFF]) + body
    return raw + bytes([calc_checksum(raw)])


def find_device_path_and_uuid(bus, address):
    wanted = address.upper()
    objects = dbus.Interface(bus.get_object("org.bluez", "/"),
                             "org.freedesktop.DBus.ObjectManager").GetManagedObjects()
    for path, interfaces in objects.items():
        device = interfaces.get("org.bluez.Device1")
        if device and str(device.get("Address", "")).upper() == wanted:
            uuids = [str(u).lower() for u in device.get("UUIDs", [])]
            for u in uuids:
                if u.startswith(SOUNDCORE_UUID_PREFIX):
                    return str(path), u
            return str(path), DEFAULT_UUID
    return None, None


class Link:
    def __init__(self, fd, plan):
        self.fd = fd
        self.buffer = bytearray()
        self.sound_mode_params = [0x00, 0x1F, 0xFF, 0x00, 0x00, 0x01]
        GLib.io_add_watch(fd, GLib.PRIORITY_DEFAULT,
                          GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self.on_io)
        delay = 400
        for name, data in plan:
            GLib.timeout_add(delay, lambda n=name, d=data: (self.send(n, d), False)[1])
            delay += 1200

    def on_io(self, _fd, condition):
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            print("%s !! closed" % stamp(), flush=True)
            self.fd = -1
            return False
        try:
            data = os.read(self.fd, 4096)
        except OSError as error:
            print("%s !! read err: %s" % (stamp(), error), flush=True)
            self.fd = -1
            return False
        if not data:
            print("%s !! EOF" % stamp(), flush=True)
            self.fd = -1
            return False
        self.buffer += data
        self.parse_buffer()
        return True

    def parse_buffer(self):
        while len(self.buffer) >= 9:
            if not (self.buffer[0] == 0x09 and self.buffer[1] == 0xFF):
                idx = self.buffer.find(b"\x09\xff")
                if idx == -1:
                    self.buffer = bytearray()
                    break
                self.buffer = self.buffer[idx:]
                if len(self.buffer) < 9:
                    break
            cmd = (self.buffer[5], self.buffer[6])
            total_len = self.buffer[7] | (self.buffer[8] << 8)
            if len(self.buffer) < total_len:
                break
            packet = bytes(self.buffer[:total_len])
            self.buffer = self.buffer[total_len:]

            cksum = packet[-1]
            if calc_checksum(packet[:-1]) != cksum:
                print("%s !! checksum mismatch in packet" % stamp(), flush=True)
                continue

            body = packet[9:-1]
            if cmd == CMD_STATE_UPDATE:
                if len(body) >= 77:
                    self.sound_mode_params = list(body[71:77])
                    mode_name = MODE_NAME.get(body[71], "unknown(%d)" % body[71])
                    print("%s <<< STATE: mode=%s params=%s" % (stamp(), mode_name, bytes(body[71:77]).hex()), flush=True)
                else:
                    print("%s <<< STATE (short payload: %d bytes)" % (stamp(), len(body)), flush=True)
            elif cmd == CMD_SOUND_MODES_NOTIFY:
                mode_name = MODE_NAME.get(body[0] if body else -1, "unknown")
                print("%s <<< NOTIFY: mode=%s body=%s" % (stamp(), mode_name, body.hex()), flush=True)
            elif cmd == CMD_SOUND_MODES_SET:
                print("%s <<< ACK [06 81]" % stamp(), flush=True)
            else:
                print("%s <<< PKT cmd=(0x%02x, 0x%02x) len=%d body=%s" % (
                    stamp(), cmd[0], cmd[1], total_len, body.hex()), flush=True)

    def send(self, name, data):
        if self.fd < 0:
            return
        print("%s >>> %s (%d bytes) %s" % (stamp(), name, len(data), data.hex()), flush=True)
        try:
            os.write(self.fd, data)
        except OSError as error:
            print("%s !! write: %s" % (stamp(), error), flush=True)


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: soundcore_probe.py <address> [seconds] [set:off|anc|ambient]")
        return 0
    address = argv[0]
    seconds = 10
    wanted = None
    for arg in argv[1:]:
        if arg.startswith("set:"):
            wanted = arg.split(":", 1)[1].strip().lower()
            if wanted not in SET_BYTE:
                sys.exit("unknown mode %r (off, anc, ambient)" % wanted)
        else:
            seconds = int(arg)

    plan = [
        ("req_state", make_packet(CMD_STATE_UPDATE)),
    ]
    if wanted is not None:
        body = [SET_BYTE[wanted], 0x1F, 0xFF, 0x00, 0x00, 0x01]
        plan.append(("set-%s" % wanted, make_packet(CMD_SOUND_MODES_SET, bytes(body))))
        plan.append(("req_state2", make_packet(CMD_STATE_UPDATE)))

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    loop = GLib.MainLoop()
    link = {"l": None}

    device_path, target_uuid = find_device_path_and_uuid(bus, address)
    if not device_path:
        sys.exit("no paired device with address %s" % address)

    class Profile(dbus.service.Object):
        @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
        def Release(self):
            pass

        @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}",
                             out_signature="")
        def NewConnection(self, _path, fd, _properties):
            print("%s == connected" % stamp(), flush=True)
            link["l"] = Link(fd.take(), plan)

        @dbus.service.method("org.bluez.Profile1", in_signature="o", out_signature="")
        def RequestDisconnection(self, _path):
            print("%s == BlueZ asked to disconnect" % stamp(), flush=True)

    Profile(bus, PROFILE_PATH)
    manager = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"),
                             "org.bluez.ProfileManager1")
    manager.RegisterProfile(PROFILE_PATH, target_uuid, {
        "Name": "Soundcore probe",
        "Role": "client",
        "Channel": dbus.UInt16(0),
        "RequireAuthentication": dbus.Boolean(False),
        "RequireAuthorization": dbus.Boolean(False),
        "AutoConnect": dbus.Boolean(False),
    })

    dev = dbus.Interface(bus.get_object("org.bluez", device_path), "org.bluez.Device1")

    def connect(attempt=0):
        def failed(error):
            print("%s ConnectProfile: %s" % (stamp(), error.get_dbus_message()), flush=True)
            if attempt < 10:
                GLib.timeout_add(1500, lambda: connect(attempt + 1))

        dev.ConnectProfile(target_uuid, reply_handler=lambda: None,
                           error_handler=failed, timeout=30)
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
