#!/usr/bin/env python3
"""Probe the Sony MDR channel on a headset: init, then ask for the NC/ASM state.

Usage: sony_probe.py <address> [seconds] [v1|v2] [set:off|nc|ambient[:level[:voice]]]

Registers an org.bluez.Profile1 for the MDR UUID — v2 unless you say `v1`, which
is the one the older headsets serve; `bluetoothctl info` says which your headset
lists. Lets BlueZ connect it, sends the protocol-info handshake, ACKs everything
the device sends, asks NCASM_GET_PARAM with every candidate inquired type (0x17,
0x15, 0x22 on v2; 0x02 on v1) and prints every decoded frame. The reply that
echoes the type you asked for, and its payload length, is what a bridge must
speak. Optional `set:` writes one mode after the GETs, using the layout the
device answered with.

Both generations' types are asked whichever UUID you registered: the numbers do
not collide, so what answers tells you the layout even if the handshake or the
UUID suggested otherwise.
"""
import os
import struct
import sys
import time

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

UUID_V2 = "956c7b26-d49a-4ba8-b03f-b17d393cb6e2"
UUID_V1 = "96cc203e-5068-46ad-b32d-e316f5e069ba"
PROFILE_PATH = "/io/github/ncr/omaphones/sonyprobe"
START = time.monotonic()

HDR, TRL, ESC, MASK = 0x3E, 0x3C, 0x3D, 0xEF
DATA_MDR, ACK = 0x0C, 0x01


def stamp():
    return "%7.2fs" % (time.monotonic() - START)


def escape(b):
    out = bytearray()
    for x in b:
        if x in (HDR, TRL, ESC):
            out += bytes([ESC, x & MASK])
        else:
            out.append(x)
    return bytes(out)


def unescape(b):
    out, i = bytearray(), 0
    while i < len(b):
        if b[i] == ESC:
            i += 1
            out.append(b[i] | 0x10)
        else:
            out.append(b[i])
        i += 1
    return bytes(out)


def encode(dtype, seq, payload=b""):
    body = bytes([dtype, seq]) + struct.pack(">I", len(payload)) + payload
    return bytes([HDR]) + escape(body + bytes([sum(body) & 0xFF])) + bytes([TRL])


def decode(frame):
    m = unescape(frame[1:-1])
    dtype, seq = m[0], m[1]
    n = struct.unpack(">I", m[2:6])[0]
    payload, cksum = m[6:6 + n], m[6 + n]
    ok = len(payload) == n and cksum == sum(m[:6 + n]) & 0xFF
    return dtype, seq, payload, ok


def parse_ncasm(p):
    if len(p) < 6 or p[0] not in (0x67, 0x69):
        return None
    # v1: NcAsmParam, read by index — ncAsmEffect, ncType, ncValue, asmType,
    # asmId, asmValue after the type byte.
    if p[1] == 0x02:
        if len(p) < 8:
            return None
        on = p[2] == 0x01
        return {"type": "0x02", "len": len(p), "gen": "v1",
                "mode": "off" if not on else ("ambient" if p[4] == 0x01 else "nc"),
                "ncType": "0x%02x" % p[3], "voice": p[6] == 0x01, "level": p[7]}
    if p[1] not in (0x15, 0x17, 0x22):
        return None
    on = p[3] == 0x01
    ambient = True if p[1] == 0x22 else (p[4] == 0x01)
    return {"type": "0x%02x" % p[1], "len": len(p), "gen": "v2",
            "mode": "off" if not on else ("ambient" if ambient else "nc"),
            "voice": p[-2] == 0x01, "level": p[-1]}


class Link:
    def __init__(self, fd, plan):
        self.fd = fd
        self.buf = bytearray()
        self.seq = 0          # our outgoing seq, advanced from received ACKs
        self.queue = list(plan)
        self.waiting = False
        self.answered_type = None
        self.answered_len = None
        GLib.io_add_watch(fd, GLib.PRIORITY_DEFAULT,
                          GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, self.on_io)
        self.send(b"\x00\x00", "CONNECT_GET_PROTOCOL_INFO")

    def send(self, payload, label):
        frame = encode(DATA_MDR, self.seq, payload)
        print("%s >>> %-28s seq=%d %s" % (stamp(), label, self.seq, frame.hex()), flush=True)
        os.write(self.fd, frame)
        self.waiting = True

    def ack(self, rseq):
        os.write(self.fd, encode(ACK, 1 - rseq))

    def pump(self):
        if self.waiting or not self.queue:
            return False
        item = self.queue.pop(0)
        if callable(item):
            item = item()
            if item is None:
                return self.pump()
        payload, label = item
        self.send(payload, label)
        return False

    def on_io(self, fd, cond):
        if cond & (GLib.IO_HUP | GLib.IO_ERR):
            print("%s !! closed by peer" % stamp(), flush=True)
            return False
        data = os.read(fd, 4096)
        if not data:
            return False
        self.buf += data
        while True:
            s = self.buf.find(HDR)
            if s < 0:
                self.buf.clear()
                break
            e = self.buf.find(TRL, s + 1)
            if e < 0:
                del self.buf[:s]
                break
            frame = bytes(self.buf[s:e + 1])
            del self.buf[:e + 1]
            dtype, rseq, payload, ok = decode(frame)
            if dtype == ACK:
                print("%s <<< ACK seq=%d" % (stamp(), rseq), flush=True)
                self.seq = rseq
                self.waiting = False
                GLib.timeout_add(150, self.pump)
                continue
            self.ack(rseq)
            tag = ""
            if payload and payload[0] == 0x01:
                tag = "  PROTOCOL_INFO (%d bytes => %s)" % (len(payload), "v2" if len(payload) == 8 else "v1?")
            st = parse_ncasm(payload)
            if st:
                tag = "  NCASM %s" % st
                if payload[0] == 0x67:
                    self.answered_type, self.answered_len = payload[1], len(payload)
            print("%s <<< type=0x%02x seq=%d payload=%s%s%s"
                  % (stamp(), dtype, rseq, payload.hex(), "" if ok else " [BAD CK]", tag),
                  flush=True)
        return True


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: sony_probe.py <address> [seconds] [v1|v2] "
                 "[set:off|nc|ambient[:level[:voice]]]")
    address = sys.argv[1]
    rest = sys.argv[2:]
    seconds = int(rest[0]) if rest and rest[0].isdigit() else 25
    setting = next((a for a in rest if a.startswith("set:")), "")
    uuid = UUID_V1 if "v1" in rest else UUID_V2

    link = {}
    # The likely generation first, the other behind it: a headset answers one
    # type and ignores the rest, so asking all four costs nothing but frames.
    types = [0x02, 0x17, 0x15, 0x22] if uuid == UUID_V1 else [0x17, 0x15, 0x22, 0x02]
    plan = [(bytes([0x66, t]), "NCASM_GET_PARAM 0x%02x" % t) for t in types]
    if setting.startswith("set:"):
        parts = setting.split(":")[1:]
        mode = parts[0]
        level = int(parts[1]) if len(parts) > 1 else 10
        voice = len(parts) > 2 and parts[2] in ("1", "on", "voice")

        def build():
            t = link["l"].answered_type
            if t is None:
                print("%s -- no NCASM answer, not setting" % stamp(), flush=True)
                return None
            on = mode != "off"
            amb = mode == "ambient"
            if t == 0x02:
                # v1: the mode is ncValue, and ncType is echoed as reported.
                p = bytes([0x68, 0x02, int(on), 0x02, 0 if not on else (1 if amb else 2),
                           0x01, int(voice), level])
            elif t == 0x17:
                p = bytes([0x68, 0x17, 0x01, int(on), int(on and amb), int(voice), level])
            elif t == 0x15:
                p = bytes([0x68, 0x15, 0x01, int(on), int(on and amb), 0x02, int(voice), level])
            else:
                p = bytes([0x68, 0x22, 0x01, int(on), int(voice), level])
            return (p, "NCASM_SET_PARAM %s" % mode)
        plan.append(build)
        plan.append(lambda: (bytes([0x66, link["l"].answered_type]),
                             "NCASM_GET_PARAM 0x%02x (readback)"
                             % link["l"].answered_type)
                    if link["l"].answered_type is not None else None)

    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()

    class Profile(dbus.service.Object):
        @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
        def Release(self):
            pass

        @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}", out_signature="")
        def NewConnection(self, path, fd, properties):
            print("%s == connected" % stamp(), flush=True)
            link["l"] = Link(fd.take(), plan)

        @dbus.service.method("org.bluez.Profile1", in_signature="o", out_signature="")
        def RequestDisconnection(self, path):
            print("%s == BlueZ asked to disconnect" % stamp(), flush=True)

    Profile(bus, PROFILE_PATH)
    manager = dbus.Interface(bus.get_object("org.bluez", "/org/bluez"),
                             "org.bluez.ProfileManager1")
    manager.RegisterProfile(PROFILE_PATH, uuid, {
        "Name": "Sony probe",
        "Role": "client",
        "RequireAuthentication": dbus.Boolean(False),
        "RequireAuthorization": dbus.Boolean(False),
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
        # Asynchronous: a blocking ConnectProfile would stall the main loop, and
        # NewConnection is delivered on that same loop.
        def failed(error):
            print("%s ConnectProfile: %s" % (stamp(), error.get_dbus_message()), flush=True)
            if attempt < 10:
                GLib.timeout_add(1500, lambda: connect(attempt + 1))
        dbus.Interface(bus.get_object("org.bluez", dev), "org.bluez.Device1").ConnectProfile(
            uuid, reply_handler=lambda: None, error_handler=failed, timeout=30)
        return False

    GLib.timeout_add(500, connect)
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
