"""Pins what soundcore-bridge sends to each model in MODELS.

    python -m unittest tests/soundcore_bridge_test.py

A row in MODELS is somebody's working headphones, and this is what keeps the
next model from changing what theirs are sent. Every case scripts one session
— the state packet the device answers the handshake with, a few widget
commands, a notification — and asserts the exact outbound frames and stdout
lines, frame for frame. A change that alters a pinned model's sequence has to
alter its case here, in the open, and that is the moment to ask its owner.

No hardware and no D-Bus: the bridge's only two effects on the world are
`write()` and `emit()`, and both are captured. The state payloads are laid out
from PROTOCOL.md rather than recorded — they pin the frames the bridge sends,
which is the point, not the parsing of one particular unit's bytes.
"""
import importlib.machinery
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "..", "soundcore-bridge")
loader = importlib.machinery.SourceFileLoader("soundcore_bridge", PATH)
spec = importlib.util.spec_from_loader("soundcore_bridge", loader)
bridge_module = importlib.util.module_from_spec(spec)
loader.exec_module(bridge_module)

INBOUND_HDR = bytes([0x09, 0xFF, 0x00, 0x00, 0x01])


def inbound(cmd, body):
    """A device frame, the mirror of make_packet."""
    total = 5 + 2 + 2 + len(body) + 1
    raw = INBOUND_HDR + bytes(cmd) + bytes([total & 0xFF, total >> 8]) + bytes(body)
    return raw + bytes([bridge_module.calc_checksum(raw)])


def state_payload(length, offset, six):
    """A 01 01 state payload with the six sound-mode bytes at `offset`.

    Everything else is 0x31: a plausible switch value, which is what makes a
    wrong offset read as a plausible mode — the trap PROTOCOL.md describes.
    """
    body = bytearray([0x31] * length)
    body[offset:offset + 6] = bytes(six)
    return bytes(body)


class Session:
    """One bridge with its two effects captured."""

    def __init__(self, uuid):
        self.sent = []
        self.lines = []
        bridge_module.emit = self.lines.append
        loop = type("Loop", (), {"quit": lambda self: None})()
        self.bridge = bridge_module.Bridge(None, "84:9D:4B:B0:2D:00", loop)
        self.bridge.model = bridge_module.model_for(uuid)
        self.bridge.write = self.sent.append

    def receive(self, frame):
        self.bridge.buffer += frame
        self.bridge.parse_buffer()

    def command(self, line):
        self.bridge.command(line)


class ModelLookup(unittest.TestCase):
    def test_space_2_by_uuid_suffix(self):
        row = bridge_module.model_for("0cf12d31-fac3-4553-bd80-d6832e7d1402")
        self.assertEqual(row["name"], "Space 2")

    def test_case_insensitive(self):
        row = bridge_module.model_for("0CF12D31-FAC3-4553-BD80-D6832E7D1402")
        self.assertEqual(row["name"], "Space 2")

    def test_default_uuid_is_unknown(self):
        self.assertIs(bridge_module.model_for(bridge_module.DEFAULT_UUID),
                      bridge_module.UNKNOWN)

    def test_unseen_model_is_unknown(self):
        self.assertIs(bridge_module.model_for("0cf12d31-fac3-4553-bd80-d6832e7ffff0"),
                      bridge_module.UNKNOWN)


class Space2(unittest.TestCase):
    """d1402 — Sovego, PR #3. Frozen: change this only with a Space 2 in hand."""

    UUID = "0cf12d31-fac3-4553-bd80-d6832e7d1402"
    # 103-byte payload, sound modes at 71..77: ambient, level 3.
    STATE = state_payload(103, 71, [0x01, 0x1F, 0xFF, 0x00, 0x00, 0x03])

    def test_frozen_session(self):
        s = Session(self.UUID)
        SET = bridge_module.CMD_SOUND_MODES_SET
        make = bridge_module.make_packet

        s.receive(inbound((0x01, 0x01), self.STATE))
        # The state is read in place; nothing is asked of the device.
        self.assertEqual(s.sent, [])
        self.assertEqual(s.lines, [{"modes": True, "mode": "ambient",
                                    "available": ["off", "anc", "ambient"],
                                    "level": 3, "voice": False}])

        s.command("set anc")
        s.receive(inbound((0x06, 0x81), []))                       # ACK
        s.receive(inbound((0x06, 0x01), [0x00, 0x1F, 0xFF, 0, 0, 3]))  # its own notification
        s.command("level 5")
        s.command("voice on")

        # The whole conversation, frame for frame.
        self.assertEqual(s.sent, [
            make(SET, bytes([0x00, 0x1F, 0xFF, 0x00, 0x00, 0x03])),
            make(SET, bytes([0x00, 0x1F, 0xFF, 0x00, 0x00, 0x05])),
            make(SET, bytes([0x00, 0x1F, 0xFF, 0x00, 0x01, 0x05])),
        ])
        self.assertEqual([(l["mode"], l["level"], l["voice"]) for l in s.lines],
                         [("ambient", 3, False), ("anc", 3, False),
                          ("anc", 5, False), ("anc", 5, True)])
        self.assertIsNone(s.bridge.exit_code)

    def test_short_state_is_unsupported(self):
        s = Session(self.UUID)
        s.receive(inbound((0x01, 0x01), bytes(40)))
        self.assertEqual(s.sent, [])
        self.assertEqual(s.bridge.exit_code, bridge_module.EXIT_UNSUPPORTED)


class Unknown(unittest.TestCase):
    """A model nobody has held. Not frozen — this is the row that may change."""

    UUID = bridge_module.DEFAULT_UUID
    STATE = state_payload(103, 71, [0x02, 0x1F, 0xFF, 0x00, 0x00, 0x01])

    def test_reads_at_71(self):
        s = Session(self.UUID)
        s.receive(inbound((0x01, 0x01), self.STATE))
        self.assertEqual(s.lines[0]["mode"], "off")
        self.assertEqual(s.sent, [])


if __name__ == "__main__":
    unittest.main()
