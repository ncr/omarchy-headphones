#!/usr/bin/env python3
"""Let the owner rank the three observed [1.6] values by how quiet they are.

Usage: qc35_rank.py <address>

The values are presented as unnamed states so the ranking is not led. The
initial value is read first and restored in `finally`, verified by readback.
"""
import re
import signal
import socket
import sys
import time

INIT = bytes.fromhex("00010100")
NC_GET = bytes.fromhex("01060100")
GRACE, HOLD, WATCH = 30.0, 12.0, 40.0
STATES = ((1, 0x00), (2, 0x01), (3, 0x03))


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
                replies.append((raw[0], raw[1], raw[2] & 15, raw[4:]))
        return replies

    def exchange(self, frame, label, wait=2.0):
        self.log(">>> %-16s %s" % (label, frame.hex(" ")))
        self.sock.sendall(frame)
        return self.drain(wait)


def read_nc(link, label):
    values = [p[0] for b, f, op, p in link.exchange(NC_GET, label)
              if (b, f, op) == (1, 6, 3) and len(p) >= 1]
    return values[-1] if values else None


def banner(text):
    print("\n" + "=" * 58, flush=True)
    print(text, flush=True)
    print("=" * 58 + "\n", flush=True)


def run(link):
    if not any((b, f, op) == (0, 1, 3) and
               re.fullmatch(rb"[0-9]+\.[0-9]+\.[0-9]+", p)
               for b, f, op, p in link.exchange(INIT, "init")):
        raise RuntimeError("no valid init STATUS")
    initial = read_nc(link, "initial")
    if initial is None:
        raise RuntimeError("no [1.6] reply; refusing blind writes")
    link.log("== initial 0x%02x ==" % initial)

    banner("PUT THE HEADPHONES ON. No music. %d seconds." % GRACE)
    for left in range(int(GRACE), 0, -10):
        print("    starting in %d..." % left, flush=True)
        link.drain(10.0)

    wrote = False
    try:
        for round_number in (1, 2):
            for label, value in STATES:
                banner("ROUND %d  --  STATE %d  --  listen for %d seconds"
                       % (round_number, label, HOLD))
                wrote = True
                link.exchange(nc_setget(value), "state %d" % label)
                link.drain(HOLD)

        banner("RANKING DONE. Now press the buttons on the left earcup a\n"
               "few times, or change noise cancelling in the Bose Connect\n"
               "app. %d seconds. Nothing is being sent from here." % WATCH)
        pushed = link.drain(WATCH)
        announced = [p.hex(" ") for b, f, op, p in pushed if (b, f) == (1, 6)]
        banner("the headset sent %d [1.6] frames unasked: %s"
               % (len(announced), announced))
    finally:
        if wrote:
            try:
                link.exchange(nc_setget(initial), "restore")
                if read_nc(link, "restore check") != initial:
                    raise RuntimeError("restore readback differs")
                link.log("== restored initial 0x%02x ==" % initial)
            except BaseException:
                link.log("!! RESTORATION FAILED; set the headset by hand")
                raise


def main():
    address = sys.argv[1].upper() if len(sys.argv) > 1 else ""
    if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", address):
        raise SystemExit("usage: qc35_rank.py <address>")

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
