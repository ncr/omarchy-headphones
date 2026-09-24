#!/usr/bin/env python3
"""Capture a Bose QC35 session on raw RFCOMM channel 8.

    bose_qc35_session.py <address>                 read, drive and restore
    bose_qc35_session.py <address> --read-only     ask, change nothing
    bose_qc35_session.py <address> --rank          name the strengths by ear
    bose_qc35_session.py <address> --probe-unlisted
                                                   also drive the values the
                                                   headset's mask leaves out
    bose_qc35_session.py <address> --seconds N     collection window per step

Release the plugin's mode bridge first: BMAP on channel 8 takes one holder.

This is the QC35 sibling of bose_session.py, which drives the QC45's [31.3]
audio modes. The QC35 answers that GET with an ERROR and keeps its noise
cancelling on [1.6] instead, so the two tools ask different questions over
the same framing. Records complete raw RX chunks at receipt plus decoded
frames, keeps partial frames in the buffer between reads, reads the initial
setting before changing anything and restores it in `finally`, verifying the
readback. A disconnected headset may prevent restoration; that failure is
reported, never hidden.

--rank exists because the wire names nothing: [1.6] reports 0, 1 and 3 and
does not say which of 1 and 3 cancels more. It presents them unnamed, so the
listener's answer is not led, and says on the desktop which state is running
because the listener is wearing the headphones and cannot read this log.
"""
import re
import signal
import socket
import subprocess
import sys
import time

OPS = {0: "SET", 1: "GET", 2: "SETGET", 3: "STATUS", 4: "ERROR",
       5: "START", 6: "RESULT", 7: "PROCESSING"}

INIT = bytes.fromhex("00010100")       # [0.1]  GET
BATTERY = bytes.fromhex("02020100")    # [2.2]  GET
QC45_MODES = bytes.fromhex("1f030100")  # [31.3] GET — expected to ERROR here
NOISE = bytes.fromhex("01060100")      # [1.6]  GET

CHANNEL = 8
GRACE, HOLD, WATCH = 30.0, 12.0, 40.0


def set_noise(value):
    """SETGET [1.6]: answered with the resulting STATUS, not with an ack."""
    return bytes([0x01, 0x06, 0x02, 0x01, value])


def notify(summary, body, seconds):
    """Say it on the desktop: the listener cannot read a log from inside a
    pair of headphones. One notification id, so states replace each other."""
    try:
        subprocess.run(["notify-send", "-r", "9001", "-u", "critical",
                        "-t", str(int(seconds * 1000)), summary, body],
                       check=False, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


class CaptureLink:
    def __init__(self, sock, wait=2.0):
        self.sock, self.wait = sock, wait
        self.buffer = bytearray()
        self.started = time.monotonic()

    def log(self, text):
        print("%7.2fs %s" % (time.monotonic() - self.started, text), flush=True)

    def collect(self, wait):
        """Every whole frame that arrives inside the window, with the raw
        reads logged as they land and a partial frame left in the buffer."""
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
                self.log("<<< FRAME [%d.%d] %-10s %s"
                         % (raw[0], raw[1], OPS.get(op, op), raw.hex(" ")))
                replies.append((raw[0], raw[1], op, raw[4:]))
        return replies

    def exchange(self, frame, label, wait=None):
        self.log(">>> %-22s %s" % (label, frame.hex(" ")))
        self.sock.sendall(frame)
        return self.collect(self.wait if wait is None else wait)


def require_init(link):
    if not any((b, f, op) == (0, 1, 3)
               and re.fullmatch(rb"[0-9]+\.[0-9]+\.[0-9]+", p)
               for b, f, op, p in link.exchange(INIT, "init")):
        raise RuntimeError("no valid init STATUS")


def read_noise(link, label):
    """(value, the values the mask names) from a [1.6] GET, or (None, None)."""
    for fblock, func, op, payload in reversed(link.exchange(NOISE, label)):
        if (fblock, func, op) == (1, 6, 3) and len(payload) >= 1:
            mask = payload[1] if len(payload) >= 2 else None
            listed = (None if mask is None
                      else [bit for bit in range(8) if mask & (1 << bit)])
            return payload[0], listed
    return None, None


def run_discovery(link):
    """Ask, and change nothing. Safe to run on anybody's headset."""
    require_init(link)
    link.exchange(BATTERY, "battery")
    link.exchange(QC45_MODES, "[31.3] QC45 path")
    value, listed = read_noise(link, "[1.6] noise cancelling")
    link.log("== value %s, mask names %s =="
             % ("none" if value is None else "0x%02x" % value, listed))
    return value, listed


def restoring(link, initial):
    """Put the headset back and prove it went back, or say it did not."""
    try:
        link.exchange(set_noise(initial), "restore 0x%02x" % initial)
        actual, _ = read_noise(link, "restore check")
        if actual != initial:
            raise RuntimeError("restoration readback is %s, not the initial "
                               "0x%02x" % (actual, initial))
        link.log("== restored initial 0x%02x ==" % initial)
    except BaseException:
        link.log("!! RESTORATION FAILED; set the headset by hand")
        raise


def run_session(link, probe_unlisted=False):
    """Drive the values this headset names, and put it back afterwards."""
    initial, listed = run_discovery(link)
    if initial is None:
        raise RuntimeError("no [1.6] reply; refusing blind writes")
    values = list(listed) if listed else [initial]
    if probe_unlisted:
        # Recording what the headset does with a value its own mask leaves
        # out. Off by default: it is a write of something unestablished.
        values += [v for v in range(4) if v not in values]

    wrote = False
    try:
        # A no-op write first: the value the headset already holds, which
        # confirms the operator without moving a setting.
        link.exchange(set_noise(initial), "SETGET initial (no-op)")
        wrote = True
        actual, _ = read_noise(link, "readback")
        if actual != initial:
            raise RuntimeError("the no-op write moved the setting; stopping")
        for value in values:
            link.exchange(set_noise(value), "SETGET 0x%02x" % value)
            actual, _ = read_noise(link, "readback")
            link.log("== asked 0x%02x, headset reports %s =="
                     % (value, "none" if actual is None else "0x%02x" % actual))
    finally:
        if wrote:
            restoring(link, initial)


def run_ranking(link, announce=notify):
    """Present the strengths unnamed and let the owner rank them by ear."""
    initial, listed = run_discovery(link)
    if initial is None:
        raise RuntimeError("no [1.6] reply; refusing blind writes")
    states = list(enumerate(listed if listed else [initial], start=1))

    for left in range(int(GRACE), 0, -10):
        link.log("== starting in %d ==" % left)
        announce("Put the headphones on — no music",
                 "Starting in %d seconds. Background noise is needed." % left,
                 10)
        link.collect(10.0)

    wrote = False
    try:
        for round_number in (1, 2):
            for label, value in states:
                link.log("== ROUND %d, STATE %d ==" % (round_number, label))
                wrote = True
                link.exchange(set_noise(value), "state %d" % label)
                announce("STATE %d" % label,
                         "round %d of 2  ·  %d seconds"
                         % (round_number, int(HOLD)), HOLD)
                link.collect(HOLD)

        announce("Now change it yourself",
                 "The buttons on the headset, or the vendor's app. "
                 "%d seconds." % int(WATCH), WATCH)
        unasked = [p.hex(" ") for b, f, _op, p in link.collect(WATCH)
                   if (b, f) == (1, 6)]
        link.log("== the headset sent %d [1.6] frames unasked: %s =="
                 % (len(unasked), unasked))
    finally:
        if wrote:
            restoring(link, initial)
            announce("Done", "The initial setting is restored.", 30)
    return [(label, value) for label, value in states]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    address = argv[0].upper() if argv else ""
    if not re.fullmatch(r"(?:[0-9A-F]{2}:){5}[0-9A-F]{2}", address):
        raise SystemExit(__doc__.strip().splitlines()[2].strip())
    rest = argv[1:]
    read_only = "--read-only" in rest
    rank = "--rank" in rest
    probe_unlisted = "--probe-unlisted" in rest
    wait = 2.0
    if "--seconds" in rest:
        wait = float(rest[rest.index("--seconds") + 1])
    if wait <= 0:
        raise SystemExit("--seconds must be positive")
    if read_only and (rank or probe_unlisted):
        raise SystemExit("--read-only changes nothing, so it takes neither "
                         "--rank nor --probe-unlisted")

    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    with socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM,
                       socket.BTPROTO_RFCOMM) as sock:
        sock.settimeout(10.0)
        sock.connect((address, CHANNEL))
        sock.settimeout(0.2)
        link = CaptureLink(sock, wait)
        if read_only:
            run_discovery(link)
        elif rank:
            run_ranking(link)
        else:
            run_session(link, probe_unlisted)


if __name__ == "__main__":
    main()
