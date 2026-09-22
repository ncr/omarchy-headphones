"""What sony-bridge sends each headset that has answered it.

    python -m unittest tests.sony_bridge_test

The frozen sessions — one per model, somebody's working headphones — are the
pin files in tests/pins/sony/, played by the harness; a change to what a
pinned model is sent has to change its file, in the open, and that is the
moment to ask its owner. What is here is the rest: framing, and the rules
that hold across models (the candidate order, who is asked the wear
question, what a silent headset does).

No hardware and no D-Bus: the bridge's only two effects on the world are
`write()` and `emit()`, and both are captured.
"""
import unittest

from tests import harness

bridge_module = harness.load_bridge("sony-bridge")

GET = bridge_module.NCASM_GET
SET = bridge_module.NCASM_SET
RET = bridge_module.NCASM_RET
NTFY = bridge_module.NCASM_NTFY
DATA_MDR = bridge_module.DATA_MDR
ACK = bridge_module.ACK
WEAR_GET = bridge_module.SYSTEM_GET_STATUS
WEAR_TYPE = bridge_module.WEARING_STATUS_TYPE


class Session(harness.Session):
    """A Sony session. "device" in a pin is an MDR payload as hex, or {"wire": "hex"} for an exact captured frame. For a payload, the frame
    around it (type 0x0C, seq 0, length, checksum, byte stuffing) is built the
    way the headset builds one. "sent" is the payload of every 0x0C frame the
    bridge wrote, as hex; the ACKs it sent for device frames are left out."""

    def __init__(self, uuid="v2", name=""):
        super().__init__(bridge_module)
        uuid = {"v2": bridge_module.UUID_V2, "v1": bridge_module.UUID_V1}.get(uuid, uuid)
        self.bridge = bridge_module.Bridge(
            None, "94:DB:56:D0:F0:F0", harness.FakeLoop(), uuid, name)
        self.bridge.write = self.frames.append
        # A real link has an fd; only write() and the framer are exercised
        # here, and write() is captured above.
        self.bridge.fd = -1

    def receive(self, frame):
        self.bridge.buffer += frame
        self.bridge.parse_buffer()

    def device(self, spec):
        if isinstance(spec, dict):
            self.receive(harness.hexbytes(spec["wire"]))
        else:
            self.receive(bridge_module.encode(DATA_MDR, 0, harness.hexbytes(spec)))

    def ack(self):
        """What the headset sends after every command, freeing the queue."""
        self.receive(bridge_module.encode(ACK, 1))

    @property
    def sent(self):
        out = []
        for frame in self.frames:
            decoded = bridge_module.decode(frame)
            if decoded and decoded[0] == DATA_MDR:
                out.append(harness.hexstr(decoded[2]))
        return out


harness.pin_tests(globals(), "sony-bridge", Session)


class Framing(unittest.TestCase):
    """encode/decode, pinned once so the sessions can talk in payloads."""

    def test_round_trip(self):
        frame = bridge_module.encode(DATA_MDR, 0, bytes([GET, 0x17]))
        self.assertEqual(frame.hex(), "3e0c000000000266178b3c")
        self.assertEqual(bridge_module.decode(frame), (DATA_MDR, 0, b"\x66\x17"))

    def test_a_marker_in_the_payload_is_stuffed(self):
        # 0x3C is the trailer; it may never appear raw inside a body.
        frame = bridge_module.encode(DATA_MDR, 0, bytes([SET, 0x17, 0x01, 0x01,
                                                         0x01, 0x00, 0x3C]))
        self.assertNotIn(0x3C, frame[1:-1])
        self.assertEqual(bridge_module.decode(frame)[2][-1], 0x3C)


class OneTypeAtATime(unittest.TestCase):
    def test_a_block_of_another_type_is_dropped_once_one_answered(self):
        s = Session(name="WH-CH720N")
        s.device("01 00 03 00 10 02 00 00")
        s.ack()
        s.device("67 17 01 01 01 00 14")
        # A v1-numbered block on a headset that answered 0x17 is not a v1
        # headset; reading it as one would move the panel to a mode nobody
        # asked for.
        s.device("69 02 01 02 02 01 00 00")
        self.assertEqual(len(s.lines), 1)
        self.assertEqual(s.bridge.inquired, 0x17)

    def test_a_short_block_is_not_read(self):
        # Sony's v1 table numbers an NC-only 0x01 and an ambient-only 0x03 that
        # nobody has seen answered, so neither is asked; a 0x02 block that
        # arrives short of its seven bytes is dropped rather than guessed at.
        self.assertEqual(bridge_module.CANDIDATES_V1, (0x02,))
        self.assertIsNone(bridge_module.parse_ncasm(bytes([RET, 0x02, 0x01, 0x02])))


class CandidateOrder(unittest.TestCase):
    """The handshake orders the questions. It never removes one."""

    def test_v2_handshake_asks_v2_first_and_v1_last(self):
        s = Session()
        s.bridge.order_candidates(8)
        self.assertEqual(s.bridge.candidates, (0x17, 0x15, 0x22, 0x02))

    def test_v1_handshake_asks_v1_first_and_v2_after(self):
        s = Session()
        s.bridge.order_candidates(4)
        self.assertEqual(s.bridge.candidates, (0x02, 0x17, 0x15, 0x22))

    def test_a_short_handshake_still_reaches_the_v2_questions(self):
        """The invariant: a headset that answers 0x17 is asked 0x17.

        Two models answer 0x17 today. Neither may be lost because a third
        headset replied to the handshake with four bytes and the bridge decided
        from that alone which questions exist.
        """
        s = Session()
        s.device("01 00 70 00")
        self.assertEqual(s.sent, ["66 02"])

        s.ack()
        s.fire()                                   # 0x02 goes unanswered
        s.ack()
        self.assertEqual(s.sent[-1], "66 17")

        s.device("67 17 01 01 01 00 14")
        self.assertEqual(s.bridge.inquired, 0x17)
        self.assertEqual(s.lines[-1]["mode"], "ambient")
        self.assertIsNone(s.bridge.exit_code)

    def test_every_candidate_has_a_mode_list(self):
        for candidate in bridge_module.CANDIDATES:
            self.assertIn(candidate, bridge_module.AVAILABLE)


class WearQuestion(unittest.TestCase):
    """Who is asked f2 10: a model with no row, and nobody without a name."""

    HANDSHAKE = "01 00 03 00 20 16 00 00"

    def test_a_model_nobody_has_held_is_asked(self):
        s = Session(name="WF-1000XM5")
        s.device(self.HANDSHAKE)
        s.ack()
        self.assertEqual(s.sent, ["66 17", "f2 10"])

    def test_no_name_is_the_old_caller_and_gets_the_old_frames(self):
        s = Session()
        s.device(self.HANDSHAKE)
        s.ack()
        self.assertEqual(s.sent, ["66 17"])

    def test_every_pinned_model_has_a_row(self):
        # A NO_MODES name deliberately has no MODELS row — it is asked
        # nothing at all, the wear question included — so it satisfies this
        # a different way: named there instead.
        for _path, pin in harness.pins_for("sony-bridge"):
            name = pin["session"]["name"]
            self.assertTrue(
                name in bridge_module.MODELS or name in bridge_module.NO_MODES,
                pin["model"])


class NoModes(unittest.TestCase):
    """NO_MODES names are asked nothing at all, and nobody else is affected."""

    HANDSHAKE = "01 00 03 00 10 01 00 00"

    def test_a_no_modes_name_is_asked_nothing_and_parked(self):
        s = Session(name="WH-CH520")
        s.device(self.HANDSHAKE)
        self.assertEqual(s.sent, [])
        self.assertEqual(s.bridge.exit_code, bridge_module.EXIT_UNSUPPORTED)

    def test_a_models_row_name_is_unaffected(self):
        s = Session(name="WH-CH720N")
        s.device(self.HANDSHAKE)
        s.ack()
        self.assertEqual(s.sent, ["66 17"])
        self.assertIsNone(s.bridge.exit_code)

    def test_no_modes_and_models_never_share_a_name(self):
        self.assertEqual(set(bridge_module.NO_MODES) & set(bridge_module.MODELS), set())

    def test_controls_and_pending_timers_send_no_queries_after_parking(self):
        # RX capture contains decoded payloads; Session framing is synthetic.
        s = Session(name="WH-CH520")
        s.bridge.send_init(1)
        s.device(self.HANDSHAKE)
        before = list(s.frames)
        for command in ("set anc", "set off", "set ambient", "level 10", "voice on"):
            s.command(command)
        s.bridge.send_init(2)
        s.bridge.probe(0)
        self.assertEqual(s.frames, before)
        self.assertEqual(s.sent, ["00 00"])
        self.assertEqual(s.bridge.exit_code, bridge_module.EXIT_UNSUPPORTED)

    def test_reconnect_parks_again_without_changing_another_sony(self):
        peer = Session(name="WH-CH720N")
        peer.device(self.HANDSHAKE)
        peer_frames, peer_lines = list(peer.frames), list(peer.lines)
        for _ in range(2):
            s = Session(name="WH-CH520")
            s.device(self.HANDSHAKE)
            self.assertEqual(s.sent, [])
            self.assertEqual(s.bridge.exit_code, bridge_module.EXIT_UNSUPPORTED)
        self.assertEqual(peer.frames, peer_frames)
        self.assertEqual(peer.lines, peer_lines)
        self.assertIsNone(peer.bridge.exit_code)

    def test_unanswered_handshake_keeps_transient_failure(self):
        s = Session(name="WH-CH520")
        s.bridge.send_init(bridge_module.INIT_ATTEMPTS + 1)
        self.assertEqual(s.bridge.exit_code, bridge_module.EXIT_TRANSIENT)
        self.assertEqual(s.sent, [])


class V1AmbientLevel(unittest.TestCase):
    """The WH-1000XM4 reports level 0 in noise cancelling. Frames from
    docs/captures/sony-wh-1000xm4-ambient.txt."""

    def session(self):
        s = Session("v1", "WH-1000XM4")
        s.device("01 00 70 00")
        s.ack()
        s.device("67 02 01 02 02 01 00 00")     # RET: noise cancelling, level 0
        return s

    def test_ambient_returns_to_the_last_reported_level(self):
        s = self.session()
        s.device("69 02 01 02 00 01 00 14")     # NTFY: ambient, level 20
        s.device("69 02 01 02 02 01 00 00")     # NTFY: noise cancelling, level 0
        s.command("set ambient")
        self.assertEqual(s.sent[-1], "68 02 11 01 00 01 00 14")

    def test_nothing_remembered_starts_at_one(self):
        s = self.session()
        s.command("set ambient")
        self.assertEqual(s.sent[-1], "68 02 11 01 00 01 00 01")

    def test_a_level_asked_for_is_sent_as_asked(self):
        s = self.session()
        s.device("69 02 01 02 00 01 00 14")
        s.device("69 02 01 02 02 01 00 00")
        s.command("level 5")
        self.assertEqual(s.sent[-1], "68 02 11 01 00 01 00 05")

    def test_the_level_kept_while_off_is_remembered_too(self):
        s = self.session()
        s.device("69 02 00 02 00 01 00 14")     # NTFY: effect off, level 20 kept
        s.device("69 02 01 02 02 01 00 00")
        s.command("set ambient")
        self.assertEqual(s.sent[-1], "68 02 11 01 00 01 00 14")

    def test_v2_headsets_are_sent_what_they_were(self):
        # A v2 report with a level above zero is not remembered, and the
        # ambient SET carries the reported level, zero included.
        s = Session("v2", "WH-CH720N")
        s.bridge.on_state({"inquired": 0x17, "mode": "ambient", "level": 12,
                           "voice": False, "ncValue": None})
        s.bridge.on_state({"inquired": 0x17, "mode": "anc", "level": 0,
                           "voice": False, "ncValue": None})
        self.assertEqual(s.bridge.ambient_level, 0)
        s.command("set ambient")
        self.assertEqual(s.sent[-1], "68 17 01 01 01 00 00")


class Silent(unittest.TestCase):
    def test_nothing_answers_and_the_address_is_parked(self):
        s = Session()
        s.device("01 00 03 00 10 02 00 00")
        for _ in bridge_module.CANDIDATES:
            s.ack()
            s.fire()
        self.assertEqual(s.sent, ["66 17", "66 15", "66 22", "66 02"])
        self.assertEqual(s.bridge.exit_code, bridge_module.EXIT_UNSUPPORTED)


if __name__ == "__main__":
    unittest.main()
