#!/usr/bin/env python3
"""Drive the [1.6] noise-cancelling setting on a Bose QC35 and restore it.

Usage: qc35_session.py <address> [seconds-per-step]

Reads the initial setting before changing anything and refuses to write if it
could not be read. The first write re-sends the value the headset already
reports, so the operator itself is confirmed without changing a setting. The
initial value is restored in `finally` and the restoration is verified by a
readback; a restoration that could not be confirmed is reported, never hidden.

Release any competing mode bridge first: BMAP on channel 8 takes one holder.
While this runs the headset's noise cancelling audibly changes.
"""
import re
import signal
import socket
import sys
import time

OPS = {0: "SET", 1: "GET", 2: "SETGET", 3: "STATUS", 4: "ERROR",
       5: "START", 6: "RESULT", 7: "PROCESSING"}

INIT = bytes.fromhex("00010100")
BATTERY = bytes.fromhex("02020100")
QC45_MODE = bytes.fromhex("1f030100")
NC_GET = bytes.fromhex("01060100")


def nc_setget(value):
    return bytes([0x01, 0x06, 0x02, 0x01, value])


def nc_set(value):
    return bytes([0x01, 0x06, 0x00, 0x01, value])


class CaptureLink:
    def __init__(self, sock, wait=3.0):
        self.sock, self.wait = sock, wait
        self.buffer = bytearray()
        self.started = time.monotonic()

    def log(self, text):
        print("%7.2fs %s" % (time.monotonic() - self.started, text), flush=True)

    def exchange(self, frame, label, wait=None):
        self.log(">>> %-22s %s" % (label, frame.hex(" ")))
        self.sock.sendall(frame)
        return self.collect(self.wait if wait is None else wait)

    def collect(self, wait):
        replies = []
        deadline = time.monotonic() + wait
        while time.monotonic() < deadline:
            try:
                chunk = self.sock.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                raise ConnectionError("device disconnected")
            self.log("<<< RAW   " + chunk.hex(" "))
            self.buffer += chunk
            while len(self.buffer) >= 4 and len(self.buffer) >= 4 + self.buffer[3]:
                size = 4 + self.buffer[3]
                raw = bytes(self.buffer[:size])
                del self.buffer[:size]
                op = raw[2] & 0x0F
                self.log("<<< FRAME [%d.%d] %-10s %s" %
                         (raw[0], raw[1], OPS.get(op, op), raw.hex(" ")))
                replies.append((raw[0], raw[1], op, raw[4:]))
        if not replies:
            self.log("<<< (silence)")
        return replies


def read_nc(link, label):
    """The current [1.6] value, or None when the headset did not say."""
    replies = link.exchange(NC_GET, label)
    values = [p[0] for b, f, op, p in replies
              if (b, f, op) == (1, 6, 3) and len(p) >= 1]
    return values[-1] if values else None


def run(link):
    replies = link.exchange(INIT, "init")
    if not any((b, f, op) == (0, 1, 3) and
               re.fullmatch(rb"[0-9]+\.[0-9]+\.[0-9]+", p)
               for b, f, op, p in replies):
        raise RuntimeError("no valid init STATUS")
    link.exchange(BATTERY, "battery")
    link.exchange(QC45_MODE, "[31.3] QC45 path")

    initial = read_nc(link, "[1.6] initial")
    if initial is None:
        raise RuntimeError("no [1.6] reply; refusing blind writes")
    print("\n== initial noise cancelling = 0x%02x ==\n" % initial, flush=True)

    wrote = False
    try:
        # A no-op write: the value the headset already holds. This confirms
        # the operator without changing a setting.
        link.exchange(nc_setget(initial), "SETGET initial (no-op)")
        wrote = True
        if read_nc(link, "readback") != initial:
            raise RuntimeError("the no-op write moved the setting; stopping")

        # 0x0b = 0b1011 in the second reply byte reads as a mask of the
        # supported values 0, 1 and 3. Every candidate is driven and read
        # back; 2 is included to record whether it is refused.
        for value in (0x00, 0x01, 0x03, 0x02):
            link.exchange(nc_setget(value), "SETGET 0x%02x" % value)
            actual = read_nc(link, "readback")
            print("   -> asked 0x%02x, device reports %s\n" %
                  (value, "None" if actual is None else "0x%02x" % actual),
                  flush=True)
    finally:
        if wrote:
            try:
                link.exchange(nc_setget(initial), "restore 0x%02x" % initial)
                actual = read_nc(link, "restore check")
                if actual != initial:
                    raise RuntimeError(
                        "restoration readback is %s, not the initial 0x%02x"
                        % (actual, initial))
                link.log("== restored initial 0x%02x ==" % initial)
            except BaseException:
                link.log("!! RESTORATION FAILED; set the headset by hand")
                raise


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: qc35_session.py <address> [seconds-per-step]")
    address = sys.argv[1].upper()
    if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", address):
        raise SystemExit("invalid Bluetooth address")
    wait = float(sys.argv[2]) if len(sys.argv) > 2 else 2.0
    if wait <= 0:
        raise SystemExit("seconds-per-step must be positive")

    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    with socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                       socket.BTPROTO_RFCOMM) as sock:
        sock.settimeout(10.0)
        sock.connect((address, 8))
        sock.settimeout(0.2)
        run(CaptureLink(sock, wait))


if __name__ == "__main__":
    main()
