#!/usr/bin/env python3
"""Read-only BMAP discovery on a Bose headset.

Usage: qc35_discover.py <address> [channels...]

Connects each candidate RFCOMM channel, sends the [0.1] init GET, and on a
channel that answers with a version STATUS asks the read-only queries below.
Nothing is ever set: this run cannot change a headset setting.

    [0.1]  00 01 01 00   init / firmware version
    [2.2]  02 02 01 00   battery
    [31.3] 1f 03 01 00   current audio mode   (the QC45 path)
    [1.6]  01 06 01 00   noise cancelling     (the based-connect QC35 path)

Raw chunks are logged at receipt with a timestamp; partial frames are kept in
the buffer and only whole frames are decoded.
"""
import re
import socket
import sys
import time

OPS = {0: "SET", 1: "GET", 2: "SETGET", 3: "STATUS", 4: "ERROR",
       5: "START", 6: "RESULT", 7: "PROCESSING"}

QUERIES = [
    ("[0.1]  version", bytes.fromhex("00010100")),
    ("[2.2]  battery", bytes.fromhex("02020100")),
    ("[31.3] audio mode", bytes.fromhex("1f030100")),
    ("[1.6]  noise cancelling", bytes.fromhex("01060100")),
]
INIT = QUERIES[0][1]


class Link:
    def __init__(self, sock, wait):
        self.sock, self.wait = sock, wait
        self.buffer = bytearray()
        self.started = time.monotonic()

    def log(self, text):
        print("%7.2fs %s" % (time.monotonic() - self.started, text), flush=True)

    def exchange(self, frame, label, wait=None):
        self.log(">>> %-24s %s" % (label, frame.hex(" ")))
        self.sock.sendall(frame)
        replies = []
        deadline = time.monotonic() + (self.wait if wait is None else wait)
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


def speaks_bmap(replies):
    return any((b, f, op) == (0, 1, 3) and
               re.fullmatch(rb"[0-9]+\.[0-9]+\.[0-9]+", p)
               for b, f, op, p in replies)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: qc35_discover.py <address> [channels...]")
    address = sys.argv[1].upper()
    if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", address):
        raise SystemExit("invalid Bluetooth address")
    channels = [int(a) for a in sys.argv[2:]] or [8, 2, 9]

    for channel in channels:
        print("\n===== RFCOMM channel %d =====" % channel, flush=True)
        sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                             socket.BTPROTO_RFCOMM)
        try:
            sock.settimeout(10.0)
            sock.connect((address, channel))
        except OSError as error:
            print("connect failed: %s" % error, flush=True)
            sock.close()
            continue
        try:
            sock.settimeout(0.2)
            link = Link(sock, 2.0)
            if not speaks_bmap(link.exchange(INIT, QUERIES[0][0])):
                print("no valid init STATUS on this channel", flush=True)
                continue
            print("-- channel %d speaks BMAP --" % channel, flush=True)
            for label, frame in QUERIES[1:]:
                link.exchange(frame, label)
            return 0
        except (OSError, ConnectionError) as error:
            print("link error: %s" % error, flush=True)
        finally:
            sock.close()
    print("\nno channel answered the BMAP init", flush=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
