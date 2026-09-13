"""What soundcore-bridge sends to each model in MODELS.

    python -m unittest tests.soundcore_bridge_test

The frozen sessions — one per MODELS row, somebody's working headphones — are
the pin files in tests/pins/soundcore/. What is here is the model lookup and
the behaviour of UNKNOWN, the one row that may change.

No hardware and no D-Bus: the bridge's only two effects on the world are
`write()` and `emit()`, and both are captured.
"""
import unittest

from tests import harness

bridge_module = harness.load_bridge("soundcore-bridge")

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


class Session(harness.Session):
    """A Soundcore session. "device" in a pin is {"cmd": "06 01", "body": hex}
    — the command pair and the body, wrapped the way the device wraps them.
    "sent" is every whole frame the bridge wrote, as hex."""

    def __init__(self, uuid):
        super().__init__(bridge_module)
        self.bridge = bridge_module.Bridge(None, "84:9D:4B:B0:2D:00", harness.FakeLoop())
        self.bridge.model = bridge_module.model_for(uuid)
        self.bridge.write = self.frames.append

    def receive(self, frame):
        self.bridge.buffer += frame
        self.bridge.parse_buffer()

    def device(self, spec):
        self.receive(inbound(harness.hexbytes(spec["cmd"]),
                             harness.hexbytes(spec.get("body", ""))))


harness.pin_tests(globals(), "soundcore-bridge", Session)


class ModelLookup(unittest.TestCase):
    def test_space_2_by_uuid_suffix(self):
        row = bridge_module.model_for("0cf12d31-fac3-4553-bd80-d6832e7d1402")
        self.assertEqual(row["name"], "Space 2")

    def test_r60i_nc_by_uuid_suffix(self):
        row = bridge_module.model_for("0cf12d31-fac3-4553-bd80-d6832e71202c")
        self.assertEqual(row["name"], "soundcore R60i NC")

    def test_case_insensitive(self):
        row = bridge_module.model_for("0CF12D31-FAC3-4553-BD80-D6832E7D1402")
        self.assertEqual(row["name"], "Space 2")

    def test_default_uuid_is_unknown(self):
        self.assertIs(bridge_module.model_for(bridge_module.DEFAULT_UUID),
                      bridge_module.UNKNOWN)

    def test_unseen_model_is_unknown(self):
        self.assertIs(bridge_module.model_for("0cf12d31-fac3-4553-bd80-d6832e7ffff0"),
                      bridge_module.UNKNOWN)

    def test_every_pinned_model_has_a_row(self):
        for _path, pin in harness.pins_for("soundcore-bridge"):
            row = bridge_module.model_for(pin["session"]["uuid"])
            self.assertIsNot(row, bridge_module.UNKNOWN, pin["model"])


class ShortState(unittest.TestCase):
    def test_short_state_is_unsupported(self):
        s = Session("0cf12d31-fac3-4553-bd80-d6832e7d1402")
        s.receive(inbound((0x01, 0x01), bytes(40)))
        self.assertEqual(s.sent, [])
        self.assertEqual(s.bridge.exit_code, bridge_module.EXIT_UNSUPPORTED)


class Unknown(unittest.TestCase):
    """A model nobody has held. Not frozen — this is the row that may change."""

    UUID = bridge_module.DEFAULT_UUID
    # Six bytes at 69, as on the One Pro, so 71 reads a plausible wrong mode.
    SIX = [0x02, 0x50, 0x01, 0x01, 0x00, 0x05]
    STATE = state_payload(95, 69, SIX)

    def test_reply_stands_over_the_offset(self):
        s = Session(self.UUID)
        QUERY = bridge_module.CMD_SOUND_MODES_NOTIFY
        SET = bridge_module.CMD_SOUND_MODES_SET
        make = bridge_module.make_packet

        s.receive(inbound((0x01, 0x01), self.STATE))
        self.assertEqual(s.lines[0]["mode"], "ambient")   # 71: the wrong byte
        self.assertEqual(s.frames, [make(QUERY)])
        s.receive(inbound((0x06, 0x01), self.SIX))
        self.assertEqual(s.lines[-1]["mode"], "off")      # corrected
        # And the write carries the reply's five bytes, not the neighbours'.
        s.command("set anc")
        self.assertEqual(s.frames[-1], make(SET, bytes([0x00, 0x50, 0x01, 0x01, 0x00, 0x05])))
        self.assertEqual(s.timers, [400])

    def test_silent_device_is_asked_once(self):
        s = Session(self.UUID)
        QUERY = bridge_module.CMD_SOUND_MODES_NOTIFY
        make = bridge_module.make_packet
        s.receive(inbound((0x01, 0x01), state_payload(103, 71, [0x01, 0x1F, 0xFF, 0, 0, 3])))
        s.command("set anc")
        # Never answered 06 01, so nothing is asked after the write.
        self.assertEqual([f for f in s.frames if f == make(QUERY)], [make(QUERY)])
        self.assertEqual(s.timers, [])


if __name__ == "__main__":
    unittest.main()
