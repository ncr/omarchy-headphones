#!/usr/bin/env python3
"""Probe the Nothing NT Link channel: ask for everything, print every frame.

Usage: nothing_probe.py <address> [set-anc <off|low|mid|high|adaptive|transparency>
                                   | set-latency <on|off>]

Opens an RFCOMM socket to channel 15, sends the device-info, battery,
noise-control and low-latency gets, and prints each frame in both directions —
raw and decoded — for a few seconds. With a `set-…` argument it writes that
setting afterwards and asks for the state again, so the ack and the read-back
can be seen. What it prints is what nothing-bridge and PROTOCOL.md are built
on; a device that answers differently is worth a pull request.

The widget's bridge holds the same channel while the earbuds are connected and
noise control is on, and the second client is refused: switch `useModeControl`
off first, or reconnect the earbuds with the panel closed.
"""
import socket
import struct
import sys
import time

RFCOMM_CHANNEL = 15
SOF = 0x55
CTRL_WITH_CRC = 0x0160

COMMANDS = {0x06: "device-info", 0x07: "battery", 0x1E: "anc", 0x0F: "anc-set",
            0x41: "latency", 0x40: "latency-set", 0x29: "codec-flag",
            0x01: "battery-event", 0x03: "anc-event"}
DIRECTIONS = {0xC0: "get", 0xF0: "set", 0x40: "answer", 0x70: "ack", 0xE0: "event"}
MODES = {0x01: "high", 0x02: "mid", 0x03: "low", 0x04: "adaptive",
         0x05: "off", 0x07: "transparency"}
MODE_BYTES = {name: byte for byte, name in MODES.items()}
COMPONENTS = {2: "left", 3: "right", 4: "case", 6: "headset"}

START = time.monotonic()


def stamp():
    return "%6.2fs" % (time.monotonic() - START)


def crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF


def frame(command, direction, payload=b""):
    wire = (command & 0xFF) | ((direction & 0xFF) << 8)
    body = struct.pack("<BHHH", SOF, CTRL_WITH_CRC, wire, len(payload)) + b"\x01" + payload
    return body + struct.pack("<H", crc16(body))


def take_frames(buffer):
    frames = []
    while True:
        try:
            start = buffer.index(SOF)
        except ValueError:
            buffer.clear()
            break
        if start:
            del buffer[:start]
        if len(buffer) < 8:
            break
        _, ctrl, wire, length = struct.unpack_from("<BHHH", buffer)
        crc_size = 2 if ctrl & 0x20 else 0
        total = 8 + length + crc_size
        if len(buffer) < total:
            break
        raw = bytes(buffer[:total])
        del buffer[:total]
        ok = not crc_size or struct.unpack_from("<H", raw, 8 + length)[0] == crc16(raw[:8 + length])
        frames.append((raw, wire & 0xFF, (wire >> 8) & 0xFF, raw[8:8 + length], ok))
    return frames


def decode(command, direction, payload):
    if command in (0x1E, 0x03) and len(payload) >= 2:
        return "mode %s" % MODES.get(payload[1], "unknown 0x%02x" % payload[1])
    if command in (0x07, 0x01) and payload:
        parts = []
        for index in range(payload[0]):
            offset = 1 + index * 2
            if offset + 1 >= len(payload):
                break
            name = COMPONENTS.get(payload[offset], "component %d" % payload[offset])
            raw = payload[offset + 1]
            parts.append("%s %d%%%s" % (name, raw & 0x7F, " charging" if raw & 0x80 else ""))
        return ", ".join(parts) or "no components"
    if command == 0x41 and payload:
        return "low latency %s" % ("on" if payload[0] == 1 else "off")
    if command == 0x29 and payload:
        return "codec flag %d" % payload[0]
    return ""


def show(prefix, raw, command, direction, payload, ok=True):
    name = COMMANDS.get(command, "0x%02x" % command)
    kind = DIRECTIONS.get(direction, "0x%02x" % direction)
    note = decode(command, direction, payload)
    print("%s %s %-14s %-6s %s%s%s" % (
        stamp(), prefix, name, kind, raw.hex(" "),
        ("   " + note) if note else "", "" if ok else "   BAD CRC"))


def send(sock, command, direction, payload=b""):
    raw = frame(command, direction, payload)
    show("->", raw, command, direction, payload)
    sock.sendall(raw)


def listen(sock, seconds):
    buffer = bytearray()
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        sock.settimeout(max(0.05, deadline - time.monotonic()))
        try:
            data = sock.recv(4096)
        except socket.timeout:
            continue
        if not data:
            print(stamp(), "channel closed")
            return
        buffer += data
        for raw, command, direction, payload, ok in take_frames(buffer):
            show("<-", raw, command, direction, payload, ok)


def main():
    argv = sys.argv[1:]
    if not argv:
        print(__doc__.strip())
        return 2
    address = argv[0]
    action = argv[1] if len(argv) > 1 else ""
    value = argv[2] if len(argv) > 2 else ""

    sock = None
    for attempt in range(4):
        sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        sock.settimeout(5.0)
        try:
            sock.connect((address, RFCOMM_CHANNEL))
            break
        except OSError as error:
            sock.close()
            sock = None
            print(stamp(), "connect attempt %d: %s" % (attempt + 1, error))
            time.sleep(1.5)
    if sock is None:
        return 1
    print(stamp(), "connected to channel %d" % RFCOMM_CHANNEL)

    try:
        send(sock, 0x06, 0xC0)
        listen(sock, 1.5)
        for command in (0x07, 0x1E, 0x41, 0x29):
            send(sock, command, 0xC0)
        listen(sock, 3.0)

        if action == "set-anc" and value in MODE_BYTES:
            send(sock, 0x0F, 0xF0, bytes([0x01, MODE_BYTES[value], 0x00]))
            listen(sock, 1.0)
            send(sock, 0x1E, 0xC0)
            listen(sock, 2.0)
        elif action == "set-latency" and value in ("on", "off"):
            send(sock, 0x40, 0xF0, bytes([0x01 if value == "on" else 0x02]))
            listen(sock, 1.0)
            send(sock, 0x41, 0xC0)
            listen(sock, 2.0)
        elif action:
            print(stamp(), "unknown action %r %r" % (action, value))
    finally:
        sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
