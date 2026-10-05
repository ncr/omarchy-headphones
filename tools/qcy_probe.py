#!/usr/bin/env python3
"""Discover what a QCY headset exposes and capture its replies.

    tools/qcy_probe.py ADDRESS [--listen SECONDS]
    tools/qcy_probe.py ADDRESS --requests   # send candidate read/request probes
    tools/qcy_probe.py ADDRESS --spp        # Serial Port (00001101) over RFCOMM

Enumerates the whole GATT tree the device exposes to BlueZ, subscribes to
every notify-capable service, and logs raw TX/RX bytes with timestamps. It
writes nothing to the device except the requests explicitly asked for.

`--spp` takes the other door as well: it asks the headset's own SDP server
(L2CAP PSM 1) which channel serves Serial Port, opens a Bluetooth RFCOMM socket
on that channel — or, when the record is unreadable, on each channel that opens —
and sends the read requests of the QCY standard table there. No frame with a
trailing parameter is sent, so nothing in this run can set anything.

On the QCY H3 (Jieli JL7018F6) no GATT tree ever appears: BlueZ opens only
the BR/EDR bearer, the device never advertises its BLE control service, and
the probe reports no write channel. See docs/captures/qcy-h3-live.txt.
"""
import argparse
import datetime
import signal
import socket
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

# --- Serial Port (00001101) over RFCOMM.
#
# The channel is asked for rather than guessed: the SDP server answers over
# L2CAP on PSM 1, and a Serial Port record carries its RFCOMMChannel in
# attribute 0x0004. When the headset answers nothing there, the RFCOMM PSVs
# it does open are the only candidates left, and each is logged with what it
# did.
SDP_PSM = 1
SPP_PSV_SCAN = tuple(range(1, 31))
SDP_WAIT = 4.0
SPP_READ_MS = 500
SPP_CONNECT_TIMEOUT = 6.0
# ServiceSearchAttributeRequest (0x06), transaction 1: the 00001101 record,
# asking for its handle (0x0000), its class list (0x0001), its channel
# (0x0004) and its name (0x0005). Both are uint16 elements: 09 01 <hi lo>.
SDP_QUERY = (b"\x06\x00\x01\x00\x18"
             + b"\x35\x04\x18\x00\x11\x01"
             + b"\x35\x10\x09\x01\x00\x00\x09\x01\x00\x01"
             + b"\x09\x01\x00\x04\x09\x01\x00\x05")
# The read requests of the same table, in the form that carries no parameter.
# The 01 00 tails of fe 01 0c 01 00 and fe 01 17 01 00 are the length and the
# value of a *setting*, so the bare queries are sent instead.
SPP_FRAMES = (
    b"\xfe\x01\x02",   # battery
    b"\xfe\x01\x0c",   # listening mode
    b"\xfe\x01\x17",   # anc setting
    b"\xfe\x01\x30",   # version
)


def sdp_element(data, pos):
    """One SDP data element at `pos`: (type, value bytes, next position)."""
    kind = data[pos]
    width = data[pos + 1]
    # Sequences and alternatives spell their byte count in the size index, as
    # records encode them; the other types spell their width as a power of two
    # (0 = 1 byte, 1 = 2, 2 = 4, ...). Anything past a name or a URL stops the
    # walk in sdp_channels, and the channel precedes both.
    size = width if kind in (0x35, 0x36) else 1 << width
    return kind, data[pos + 2:pos + 2 + size], pos + 2 + size


def sdp_channels(pdu):
    """The RFCOMMChannel attribute values in a ServiceSearchAttribute answer."""
    if len(pdu) < 5 or pdu[0] != 0x07:
        return []
    kind, body, _ = sdp_element(pdu, 5)
    if kind != 0x35:
        return []
    channels = []
    pos = 0
    while pos + 2 <= len(body):
        try:
            id_kind, id_bytes, pos = sdp_element(body, pos)
            val_kind, val_bytes, pos = sdp_element(body, pos)
        except IndexError:
            break
        if id_kind != 0x09:
            break
        if int.from_bytes(id_bytes, "big") == 0x0004 and val_kind == 0x08 and val_bytes:
            channels.append(val_bytes[0])
    return channels


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
        log("DEVICE " + self.address + " @ " + path + " connecting")
        self.link = {"deadline": time.monotonic() + CONNECT_TIMEOUT, "connected": False}
        device = self.interface(path, "org.bluez.Device1")
        props = dbus.Interface(self.bus.get_object("org.bluez", path),
                               "org.freedesktop.DBus.Properties")
        device.Connect(reply_handler=self.connected, error_handler=self.connect_failed,
                       timeout=20)

    def connected(self):
        self.link["connected"] = True
        log("DEVICE CONNECTED")

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
        log("GATT TREE %d services %d characteristics under " % (len(services), len(chars))
            + self.path)

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

    def rfcomm(self, psv, label):
        """A connected RFCOMM socket on `psv`, or None with the error logged."""
        sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                             socket.BTPROTO_RFCOMM)
        sock.settimeout(SPP_CONNECT_TIMEOUT)
        try:
            sock.connect((self.address, psv))
        except OSError as error:
            self.wire("%s CONNECT FAILED channel %d: %s"
                      % (label, psv, error.strerror or error))
            sock.close()
            return None
        self.wire("%s CONNECTED channel %d" % (label, psv))
        return sock

    def read_window(self, sock, ms):
        """Log every chunk that arrives within `ms`; True if any arrived."""
        end = time.monotonic() + ms / 1000
        arrived = False
        while True:
            left = end - time.monotonic()
            if left <= 0:
                return arrived
            sock.settimeout(min(0.1, left))
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                continue
            except OSError as error:
                self.wire("RX failed " + str(error.strerror or error))
                return arrived
            if not chunk:
                self.wire("RX closed by peer")
                return arrived
            self.wire("RX " + chunk.hex(" "))
            arrived = True

    def read_pdu(self, sock, timeout):
        """One SDP PDU: the 5-byte header plus the parameter length it names."""
        end = time.monotonic() + timeout
        data = b""
        sock.settimeout(timeout)
        while len(data) < 5 and time.monotonic() < end:
            try:
                chunk = sock.recv(4096)
            except socket.timeout:
                return b""
            except OSError:
                return b""
            if not chunk:
                return b""
            data += chunk
        if len(data) < 5:
            return b""
        want = 5 + int.from_bytes(data[3:5], "big")
        while len(data) < want and time.monotonic() < end:
            try:
                data += sock.recv(4096)
            except socket.timeout:
                break
            except OSError:
                break
        return data

    def l2cap(self, psm, label):
        """A connected L2CAP socket on `psm`, or None with the error logged."""
        sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_SEQPACKET,
                             socket.BTPROTO_L2CAP)
        sock.settimeout(SPP_CONNECT_TIMEOUT)
        try:
            sock.connect((self.address, psm))
        except OSError as error:
            self.wire("%s CONNECT FAILED psm %d: %s"
                      % (label, psm, error.strerror or error))
            sock.close()
            return None
        self.wire("%s CONNECTED psm %d" % (label, psm))
        return sock

    def sdp_channel(self):
        """The channel the headset's SDP record gives Serial Port, or None.

        The SDP server speaks over L2CAP, not RFCOMM: it is on PSM 1, so the
        Serial Port (00001101) record is asked for there and its RFCOMMChannel
        attribute read out of the answer, rather than any channel being
        guessed.
        """
        sock = self.l2cap(SDP_PSM, "SDP")
        if sock is None:
            self.wire("SPP SDP CHANNEL none (PSM %d would not open)" % SDP_PSM)
            return None
        try:
            self.wire("SDP TX " + SDP_QUERY.hex(" "))
            try:
                sock.sendall(SDP_QUERY)
            except OSError as error:
                self.wire("SDP TX failed " + str(error.strerror or error))
                return None
            pdu = self.read_pdu(sock, SDP_WAIT)
            if not pdu:
                self.wire("SDP RX none")
                self.wire("SPP SDP CHANNEL none (PSM %d answered no SDP request)"
                          % SDP_PSM)
                return None
            self.wire("SDP RX " + pdu.hex(" "))
            channels = sdp_channels(pdu)
        finally:
            sock.close()
            self.wire("SDP CLOSED psm %d" % SDP_PSM)
        if not channels:
            self.wire("SPP SDP CHANNEL none (no RFCOMMChannel in the Serial Port record)")
            return None
        self.wire("SPP SDP CHANNEL %d (Serial Port record on PSM %d)"
                  % (channels[0], SDP_PSM))
        return channels[0]

    def spp_exchange(self, psv):
        """Send the read requests on `psv` and log every byte either way."""
        sock = self.rfcomm(psv, "SPP")
        if sock is None:
            return False
        try:
            for frame in SPP_FRAMES:
                try:
                    sock.sendall(frame)
                except OSError as error:
                    self.wire("TX failed " + str(error.strerror or error))
                    break
                self.wire("TX " + frame.hex(" "))
                if not self.read_window(sock, SPP_READ_MS):
                    self.wire("RX none")
        finally:
            sock.close()
            self.wire("SPP CLOSED channel %d" % psv)
        return True

    def spp_test(self):
        """Serial Port (00001101) over a real RFCOMM socket, read-only.

        The channel comes from the headset's SDP record. A record that names
        no Serial Port channel leaves the channels that do open as the only
        candidates, so each of those is tried and logged too.
        """
        channel = self.sdp_channel()
        if channel is None:
            self.wire("SPP PSV SCAN %d..%d" % (SPP_PSV_SCAN[0], SPP_PSV_SCAN[-1]))
            for psv in SPP_PSV_SCAN:
                self.spp_exchange(psv)
            return
        self.spp_exchange(channel)



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
