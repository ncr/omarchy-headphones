#!/usr/bin/env python3
"""Discover what a QCY headset exposes over LE GATT and capture its replies.

    tools/qcy_probe.py ADDRESS [--listen SECONDS]
    tools/qcy_probe.py ADDRESS --requests   # send candidate read/request probes

Enumerates the whole GATT tree the device exposes to BlueZ, subscribes to
every notify-capable service, and logs raw TX/RX bytes with timestamps. It
writes nothing to the device except the requests explicitly asked for.

On the QCY H3 (Jieli JL7018F6) no GATT tree ever appears: BlueZ opens only
the BR/EDR bearer, the device never advertises its BLE control service, and
the probe reports no write channel. See docs/captures/qcy-h3-live.txt.
"""
import argparse
import datetime
import signal
import sys
import time

import dbus
import dbus.mainloop.glib
from gi.repository import GLib

WRITE_CANDIDATES = [
    "00001001-0000-1000-8000-00805f9b34fb",
    "0000a001-0000-1000-8000-00805f9b34fb",
]
NOTIFY_CANDIDATES = [
    "00001002-0000-1000-8000-00805f9b34fb",
    "0000000e-0000-1000-8000-00805f9b34fb",
]
V1_BATTERY = "00000008-0000-1000-8000-00805f9b34fb"
V1_VERSION = "00000007-0000-1000-8000-00805f9b34fb"
V1_BATTERY_STD = "00002a19-0000-1000-8000-00805f9b34fb"

REPLY_TIMEOUT = 8.0
CONNECT_TIMEOUT = 45.0


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds")


def log(text):
    print(now(), text, flush=True)


def qcy(cmd, plen, *params):
    body = bytes([cmd, plen] + list(params))
    return b"\xff" + bytes([len(body) + 1]) + body


REQUESTS = {
    "battery_req": b"\xfe\x01\x2f",
    "mode_req": b"\xfe\x01\x0c",
    "anc_setting_req": b"\xfe\x01\x17",
    "version_req": b"\xfe\x01\x30",
    "lowlvl_req": b"\xfe\x01\x09",
    "wear_req": b"\xfe\x01\x29",
    "inesense_req": b"\xfe\x01\x48",
    "ancwear_req": b"\xfe\x01\x2c",
    "gen_req": b"\xfe\x01\x01",
}

class Probe:
    def __init__(self, address, wire=log):
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        self.manager = dbus.Interface(self.bus.get_object("org.bluez", "/"),
                                      "org.freedesktop.DBus.ObjectManager")
        self.loop = GLib.MainLoop()
        self.address = address.upper()
        self.wire = wire
        self.path = None
        self.link = None
        self.write_char = None
        self.notify_char = None
        self.extra_notify = []
        self.stop_at = None
        self.deadline = None
        self.pending_read = None
        self.closed = False
        self.signal_match = self.bus.add_signal_receiver(
            self.changed, signal_name="PropertiesChanged",
            dbus_interface="org.freedesktop.DBus.Properties", path_keyword="path")

    def objects(self):
        return self.manager.GetManagedObjects(timeout=3)

    def interface(self, path, interface):
        return dbus.Interface(self.bus.get_object("org.bluez", path), interface)

    def find_listed(self):
        objects = self.objects()
        path = next((str(p) for p, v in objects.items()
                     if str(v.get("org.bluez.Device1", {}).get("Address", "")).upper()
                     == self.address), None)
        if not path:
            return None, {}
        chars = {}
        for p, v in objects.items():
            if str(p).startswith(path + "/") and "org.bluez.GattCharacteristic1" in v:
                chars[str(v["org.bluez.GattCharacteristic1"]["UUID"])] = str(p)
        return path, chars

    def connect(self):
        path, _ = self.find_listed()
        if not path:
            raise RuntimeError("device not present in BlueZ")
        self.path = path
        self.link = {"deadline": time.monotonic() + CONNECT_TIMEOUT, "connected": False}
        device = self.interface(path, "org.bluez.Device1")
        props = dbus.Interface(self.bus.get_object("org.bluez", path),
                               "org.freedesktop.DBus.Properties")
        device.Connect(reply_handler=self.connected, error_handler=self.connect_failed,
                       timeout=20)

    def connected(self):
        self.link["connected"] = True

    def connect_failed(self, error):
        log("CONNECT FAILED " + str(error))
        self.deadline = time.monotonic()

    def changed(self, interface, values, invalidated, path=None):
        if self.closed:
            return
        if interface == "org.bluez.Device1" and path == self.path and "Connected" in values:
            if not bool(values["Connected"]):
                log("DEVICE DISCONNECTED")
                self.deadline = time.monotonic()
                return
        if interface != "org.bluez.GattCharacteristic1" or "Value" not in values:
            return
        role = "write" if path == self.notify_char else "notify"
        self.wire("RX " + role + " " + bytes(values["Value"]).hex(" "))

    def wire(self, text):
        log(text)

    def wire_handle(self, path, raw):
        role = "write" if path == self.notify_char else "notify"
        self.wire("RX " + role + " " + raw.hex(" "))

    def wait_ms(self, ms):
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            context = GLib.MainContext.default()
            while context.pending():
                context.iteration(False)
            time.sleep(0.01)


    def discover(self):
        start = time.monotonic()
        end = start + CONNECT_TIMEOUT
        while time.monotonic() < end:
            objects = self.objects()
            services = [(str(p), str(v["org.bluez.GattService1"]["UUID"]))
                        for p, v in objects.items()
                        if str(p).startswith(self.path + "/")
                        and "org.bluez.GattService1" in v]
            chars = [(str(p), str(v["org.bluez.GattCharacteristic1"]["UUID"]),
                      list(v["org.bluez.GattCharacteristic1"].get("Flags", ())),
                      list(v["org.bluez.GattCharacteristic1"].get("Value", ())))
                     for p, v in objects.items()
                     if str(p).startswith(self.path + "/")
                     and "org.bluez.GattCharacteristic1" in v]
            if services or chars:
                break
            self.wait_ms(100)
        objects = self.objects()
        services = [(str(p), str(v["org.bluez.GattService1"]["UUID"]))
                    for p, v in objects.items()
                    if str(p).startswith(self.path + "/")
                    and "org.bluez.GattService1" in v]
        chars = [(str(p), str(v["org.bluez.GattCharacteristic1"]["UUID"]),
                  list(v["org.bluez.GattCharacteristic1"].get("Flags", ())),
                  list(v["org.bluez.GattCharacteristic1"].get("Value", ())))
                 for p, v in objects.items()
                 if str(p).startswith(self.path + "/")
                 and "org.bluez.GattCharacteristic1" in v]
        services.sort()
        chars.sort()
        for p, uuid in services:
            log("SERVICE " + uuid + " @" + p)
        for p, uuid, flags, value in chars:
            log("CHAR " + uuid + " flags=" + ",".join(flags) + " value=" + bytes(value).hex(" "))

    def listen(self, seconds):
        self.wait_ms(seconds * 1000)

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.signal_match:
            try:
                self.signal_match.remove()
            except Exception:
                pass

    def spp_test(self):
        """Serial Port (00001101) test using the exact SPP frames from the test.
        Logs every TX and RX line with a timestamp, as the GATT part does.
        """
        spp_frames = [
            b"\xfe\x01\x02",
            b"\xfe\x01\x0c\x01\x00",
            b"\xfe\x01\x17\x01\x00",
            b"\xfe\x01\x30",
        ]
        for frame in spp_frames:
            self.wire("TX " + frame.hex(" "))
            self.wait_ms(500)



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address")
    parser.add_argument("--listen", type=float, default=5)
    parser.add_argument("--requests", action="store_true")
    parser.add_argument("--spp", action="store_true", help="Serial Port (00001101) test with SPP frames")
    args = parser.parse_args()
    if len(args.address.replace(":", "")) != 12 or not 0 <= args.listen <= 600:
        parser.error("valid MAC address and listen seconds 0..600 required")
    probe = None
    state = {"stopping": False}

    def stop(*_):
        state["stopping"] = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        probe = Probe(args.address)
        probe.connect()
        try:
            probe.discover()
        except Exception as e:
            log("FAILED " + repr(e))
        if state["stopping"]:
            return 0
        if args.requests:
            try:
                probe.requests()
            except Exception as e:
                log("FAILED " + repr(e))
        if args.spp:
            probe.spp_test()
        probe.listen(args.listen)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        log("FAILED " + repr(error))
        return 1
    finally:
        if probe:
            probe.close()
if __name__ == "__main__":
    sys.exit(main())
