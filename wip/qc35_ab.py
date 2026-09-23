#!/usr/bin/env python3
"""Name the two QC35 noise-cancelling values by ear, and watch for pushes.

Usage: qc35_ab.py <address>

Alternates the observed values 0x01 (A) and 0x03 (B) so the listener can say
which cancels more, then listens without sending while the listener changes
the setting on the headset itself. The initial value is read first and
restored in `finally`, with the restoration verified by a readback.
"""
import re
import signal
import socket
import sys
import time

OPS = {0: "SET", 1: "GET", 2: "SETGET", 3: "STATUS", 4: "ERROR",
       5: "START", 6: "RESULT", 7: "PROCESSING"}

INIT = bytes.fromhex("00010100")
NC_GET = bytes.fromhex("01060100")
GRACE = 25.0
HOLD = 10.0
WATCH = 30.0


def nc_setget(value):
    return bytes([0x01, 0x06, 0x02, 0x01, value])


class Link:
    def __init__(self, sock):
        self.sock = sock
        self.buffer = bytearray()
        self.started = time.monotonic()

    def log(self, text):
        print("%7.2fs %s" % (time.monotonic() - self.started, text), flush=True)

    def drain(self, wait):
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
        return replies

    def exchange(self, frame, label, wait=2.0):
        self.log(">>> %-18s %s" % (label, frame.hex(" ")))
        self.sock.sendall(frame)
        return self.drain(wait)


def read_nc(link, label):
    values = [p[0] for b, f, op, p in link.exchange(NC_GET, label)
              if (b, f, op) == (1, 6, 3) and len(p) >= 1]
    return values[-1] if values else None


def run(link):
    if not any((b, f, op) == (0, 1, 3) and
               re.fullmatch(rb"[0-9]+\.[0-9]+\.[0-9]+", p)
               for b, f, op, p in link.exchange(INIT, "init")):
        raise RuntimeError("no valid init STATUS")
    initial = read_nc(link, "[1.6] initial")
    if initial is None:
        raise RuntimeError("no [1.6] reply; refusing blind writes")
    link.log("== initial 0x%02x ==" % initial)

    print("\n>>> PUT THE HEADPHONES ON. Starting in %d seconds.\n" % GRACE,
          flush=True)
    for left in range(int(GRACE), 0, -5):
        print("    %d..." % left, flush=True)
        link.drain(5.0)

    wrote = False
    try:
        for round_number in (1, 2):
            for name, value in (("A", 0x01), ("B", 0x03)):
                print("\n>>> ROUND %d — %s (0x%02x) — listen for %d seconds\n"
                      % (round_number, name, value, HOLD), flush=True)
                wrote = True
                link.exchange(nc_setget(value), "set %s" % name)
                link.drain(HOLD)

        print("\n>>> NOW CHANGE THE NOISE CANCELLING YOURSELF — the button on\n"
              ">>> the headset, or the Bose Connect app. %d seconds. Nothing\n"
              ">>> is being sent; anything printed came from the headset.\n"
              % WATCH, flush=True)
        pushed = link.drain(WATCH)
        announced = [p for b, f, op, p in pushed if (b, f, op) == (1, 6, 3)]
        print("\n>>> the headset announced %d [1.6] STATUS frames unasked\n"
              % len(announced), flush=True)
    finally:
        if wrote:
            try:
                link.exchange(nc_setget(initial), "restore 0x%02x" % initial)
                actual = read_nc(link, "restore check")
                if actual != initial:
                    raise RuntimeError("restore readback %s, not 0x%02x"
                                       % (actual, initial))
                link.log("== restored initial 0x%02x ==" % initial)
            except BaseException:
                link.log("!! RESTORATION FAILED; set the headset by hand")
                raise


def main():
    address = sys.argv[1].upper() if len(sys.argv) > 1 else ""
    if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", address):
        raise SystemExit("usage: qc35_ab.py <address>")

    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    with socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                       socket.BTPROTO_RFCOMM) as sock:
        sock.settimeout(10.0)
        sock.connect((address, 8))
        sock.settimeout(0.2)
        run(Link(sock))


if __name__ == "__main__":
    main()
