#!/usr/bin/env python3
"""Probe the Huawei FreeBuds SPP channel: ask for the battery, print every frame.

Usage: huawei_probe.py [--channel 1] [--listen SECONDS] [--poll SECONDS] [--info] <address>

Opens an RFCOMM socket to the selected channel (default 1, where the FreeBuds
SE 2 answers; 16 is refused there), asks for the battery, and prints each
frame in both directions — raw and decoded — while it listens. The probe only
reads: it sends no set, so there is no state to restore. `--poll` asks for the
battery again on that interval, for watching a bud go into the case or come
out of it; the earbuds also announce a change on their own (01 27).

`--info` asks for the device info (01 07) as well. That answer carries the
serial numbers of both buds; the probe masks their bytes with "**" and says
so on the line, so a capture can be shared as it is printed.

The widget's bridge holds the same channel while the earbuds are connected
and mode control is on: switch `useModeControl` off first.
"""
import argparse
import socket
import sys
import time

SOF = 0x5A

COMMANDS = {(0x01, 0x06): "hello", (0x01, 0x07): "device-info",
            (0x01, 0x08): "battery", (0x01, 0x27): "battery-event"}
# Device-info tags whose values are serial numbers.
SERIAL_TAGS = (0x09, 0x18)
INFO_TAGS = {0x02: "hardware", 0x03: "region", 0x07: "firmware", 0x09: "serial",
             0x0A: "build", 0x0F: "model", 0x18: "bud serials", 0x19: "flag"}

START = time.monotonic()


def stamp():
    return "%6.2fs" % (time.monotonic() - START)


def crc16(data):
    """CRC-16/XMODEM: init 0, poly 1021, no reflection."""
    crc = 0
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return crc


def frame(service, command, tags=()):
    body = bytes([service, command])
    for tag, value in tags:
        body += bytes([tag, len(value)]) + value
    head = bytes([SOF]) + (len(body) + 1).to_bytes(2, "big") + b"\x00"
    return head + body + crc16(head + body).to_bytes(2, "big")


def take_frames(buffer):
    """(raw, service, command, tlv-bytes, crc-ok) for each whole frame."""
    frames = []
    while True:
        try:
            start = buffer.index(SOF)
        except ValueError:
            buffer.clear()
            break
        if start:
            del buffer[:start]
        if len(buffer) < 4:
            break
        length = int.from_bytes(buffer[1:3], "big")
        total = 3 + length + 2
        if len(buffer) < total:
            break
        raw = bytes(buffer[:total])
        del buffer[:total]
        ok = int.from_bytes(raw[-2:], "big") == crc16(raw[:-2]) and length >= 3
        frames.append((raw, raw[4] if length >= 3 else None,
                       raw[5] if length >= 3 else None, raw[6:-2], ok))
    return frames


def tlv(data):
    out = []
    index = 0
    while index + 2 <= len(data):
        tag, size = data[index], data[index + 1]
        out.append((tag, data[index + 2:index + 2 + size], index + 2))
        index += 2 + size
    return out


def decode(service, command, data):
    pairs = tlv(data)
    if (service, command) in ((0x01, 0x08), (0x01, 0x27)):
        parts = []
        for tag, value, _ in pairs:
            if tag == 1 and len(value) == 1:
                parts.append("overall %d%%" % value[0])
            elif tag == 2 and len(value) == 3:
                parts.append("left %d%% right %d%% case %d%%" % tuple(value))
            elif tag == 3:
                parts.append("charging %s" % value.hex(" "))
            else:
                parts.append("tag %d=%s" % (tag, value.hex(" ")))
        return ", ".join(parts)
    if (service, command) == (0x01, 0x07):
        parts = []
        for tag, value, _ in pairs:
            name = INFO_TAGS.get(tag, "tag %d" % tag)
            if tag in SERIAL_TAGS:
                parts.append("%s (redacted)" % name)
            elif value and all(32 <= b < 127 for b in value):
                parts.append("%s %s" % (name, value.decode()))
            else:
                parts.append("%s %s" % (name, value.hex(" ")))
        return ", ".join(parts)
    return ""


def masked(raw, service, command, data):
    """The raw frame as hex, with serial-number bytes shown as **."""
    cells = raw.hex(" ").split(" ")
    if (service, command) == (0x01, 0x07):
        for tag, value, offset in tlv(data):
            if tag in SERIAL_TAGS:
                for i in range(len(value)):
                    cells[6 + offset + i] = "**"
    return " ".join(cells)


def show(prefix, raw, service, command, data, ok=True):
    name = COMMANDS.get((service, command), "%02x %02x" % (service or 0, command or 0))
    note = decode(service, command, data) if ok else ""
    print("%s %s %-13s %s%s%s" % (
        stamp(), prefix, name, masked(raw, service, command, data),
        ("   " + note) if note else "", "" if ok else "   BAD CRC"), flush=True)


def send(sock, service, command, tags=()):
    raw = frame(service, command, tags)
    show("->", raw, service, command, raw[6:-2])
    sock.sendall(raw)


def ask_battery(sock):
    send(sock, 0x01, 0x08, [(1, b""), (2, b""), (3, b"")])


def listen(sock, seconds, poll):
    buffer = bytearray()
    deadline = time.monotonic() + seconds
    next_poll = time.monotonic() + poll if poll else None
    while time.monotonic() < deadline:
        now = time.monotonic()
        if next_poll is not None and now >= next_poll:
            ask_battery(sock)
            next_poll = now + poll
        wake = min(deadline, next_poll) if next_poll else deadline
        sock.settimeout(max(0.05, wake - time.monotonic()))
        try:
            data = sock.recv(4096)
        except socket.timeout:
            continue
        if not data:
            print(stamp(), "channel closed", flush=True)
            return
        buffer += data
        for raw, service, command, tlvs, ok in take_frames(buffer):
            show("<-", raw, service, command, tlvs, ok)


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__.strip())
        return 2
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", type=int, default=1)
    parser.add_argument("--listen", type=float, default=4.0)
    parser.add_argument("--poll", type=float, default=0.0)
    parser.add_argument("--info", action="store_true")
    parser.add_argument("address")
    args = parser.parse_args(argv)

    sock = None
    for attempt in range(4):
        if attempt:
            time.sleep(1.5)
        sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        sock.settimeout(5.0)
        try:
            sock.connect((args.address, args.channel))
            break
        except OSError as error:
            sock.close()
            sock = None
            print(stamp(), "connect attempt %d, channel %d: %s"
                  % (attempt + 1, args.channel, error), flush=True)
    if sock is None:
        return 1
    print(stamp(), "connected to channel %d" % args.channel, flush=True)

    try:
        ask_battery(sock)
        if args.info:
            listen(sock, 1.0, 0)
            send(sock, 0x01, 0x07, [(tag, b"") for tag in range(0, 25)])
        listen(sock, args.listen, args.poll)
    except KeyboardInterrupt:
        print(stamp(), "interrupted", flush=True)
    finally:
        sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
