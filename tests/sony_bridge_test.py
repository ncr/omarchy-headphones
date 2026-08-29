"""Pins what sony-bridge sends each headset that has answered it.

    python -m unittest tests/sony_bridge_test.py

A case here is somebody's working headphones, and this is what keeps the next
model from changing what theirs are sent. Every case scripts one session — the
handshake reply, the RET that settles the inquired type, a few widget commands,
a notification — and asserts the exact outbound payloads and stdout lines,
frame for frame. A change that alters a pinned model's sequence has to alter its
case here, in the open, and that is the moment to ask its owner.

No hardware and no D-Bus: the bridge's only two effects on the world are
`write()` and `emit()`, and both are captured. The payloads are laid out from
PROTOCOL.md rather than recorded — they pin the frames the bridge sends, which
is the point, not the parsing of one particular unit's bytes.
"""
import importlib.machinery
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "..", "sony-bridge")
loader = importlib.machinery.SourceFileLoader("sony_bridge", PATH)
spec = importlib.util.spec_from_loader("sony_bridge", loader)
bridge_module = importlib.util.module_from_spec(spec)
loader.exec_module(bridge_module)

GET = bridge_module.NCASM_GET
SET = bridge_module.NCASM_SET
RET = bridge_module.NCASM_RET
NTFY = bridge_module.NCASM_NTFY
DATA_MDR = bridge_module.DATA_MDR
ACK = bridge_module.ACK


def device_frame(payload, seq=0):
    """A frame from the headset, built the way the headset builds one."""
    return bridge_module.encode(DATA_MDR, seq, bytes(payload))


def ack_frame(seq=1):
    return bridge_module.encode(ACK, seq)


class FakeGLib:
    """Records what the bridge schedules; the test decides when it fires."""

    PRIORITY_DEFAULT = 0
    IO_IN = IO_HUP = IO_ERR = 0

    def __init__(self):
        self.timers = []

    def timeout_add(self, ms, fn, *args):
        self.timers.append((ms, fn, args))
        return len(self.timers)

    def io_add_watch(self, *_args):
        return 0


class Session:
    """One bridge with its effects captured: payloads out, lines out, timers."""

    def __init__(self, uuid=None):
        self.frames = []
        self.lines = []
        self.glib = FakeGLib()
        bridge_module.emit = self.lines.append
        bridge_module.GLib = self.glib
        loop = type("Loop", (), {"quit": lambda self: None})()
        self.bridge = bridge_module.Bridge(
            None, "94:DB:56:D0:F0:F0", loop, uuid or bridge_module.UUID_V2)
        self.bridge.write = self.frames.append
        # A real link has an fd; only write() and the framer are exercised here,
        # and write() is captured above.
        self.bridge.fd = -1

    def receive(self, frame):
        self.bridge.buffer += frame
        self.bridge.parse_buffer()

    def command(self, line):
        self.bridge.command(line)

    def ack(self):
        """What the headset sends after every command, freeing the queue."""
        self.receive(ack_frame())

    @property
    def sent(self):
        """The payloads the bridge sent, ACKs of device frames left out."""
        out = []
        for frame in self.frames:
            decoded = bridge_module.decode(frame)
            if decoded and decoded[0] == DATA_MDR:
                out.append(list(decoded[2]))
        return out

    @property
    def acked(self):
        """How many device frames the bridge acknowledged."""
        return sum(1 for f in self.frames
                   if (bridge_module.decode(f) or (None,))[0] == ACK)

    @property
    def timers(self):
        return [ms for ms, _fn, _args in self.glib.timers]

    def fire(self):
        """Run every scheduled timer, in order, once."""
        pending, self.glib.timers = self.glib.timers, []
        for _ms, fn, args in pending:
            fn(*args)


class Framing(unittest.TestCase):
    """encode/decode, pinned once so the sessions below can talk in payloads."""

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


class WhCh720n(unittest.TestCase):
    """0x17, MDR v2 — ncr. Frozen: change this only with a CH720N in hand."""

    HANDSHAKE = [0x01, 0x00, 0x03, 0x00, 0x10, 0x02, 0x00, 0x00]
    # RET: changed, on, ambient, normal, level 20.
    STATE = [RET, 0x17, 0x01, 0x01, 0x01, 0x00, 0x14]

    def test_frozen_session(self):
        s = Session()
        s.receive(device_frame(self.HANDSHAKE))
        # Eight bytes, so the v2 questions come first — and 0x17 is the first.
        self.assertEqual(s.sent, [[GET, 0x17]])
        self.assertEqual(s.lines, [])

        s.ack()
        s.receive(device_frame(self.STATE))
        self.assertEqual(s.lines, [{"modes": True, "mode": "ambient",
                                    "available": ["off", "anc", "ambient"],
                                    "level": 20, "voice": False}])

        # Off, ANC, back to ambient, a level, a voice switch. Every SET carries
        # the mode, level and voice flag the headset last *reported* — nothing
        # here is remembered optimistically, so the level 5 above is gone again
        # by the time the voice switch is sent. The notification below is what
        # moves the stored values.
        for line in ("set off", "set anc", "set ambient", "level 5", "voice on"):
            s.command(line)
            s.ack()

        self.assertEqual(s.sent, [
            [GET, 0x17],
            [SET, 0x17, 0x01, 0, 0, 0, 20],
            [SET, 0x17, 0x01, 1, 0, 0, 20],
            [SET, 0x17, 0x01, 1, 1, 0, 20],
            [SET, 0x17, 0x01, 1, 1, 0, 5],
            [SET, 0x17, 0x01, 1, 1, 1, 20],
        ])
        # Nothing was read back and nothing was reported: the headset's own
        # notification is what the panel is shown.
        self.assertEqual(len(s.lines), 1)

        s.receive(device_frame([NTFY, 0x17, 0x01, 0x01, 0x01, 0x01, 0x05]))
        self.assertEqual(s.lines[-1], {"modes": True, "mode": "ambient",
                                       "available": ["off", "anc", "ambient"],
                                       "level": 5, "voice": True})
        self.assertIsNone(s.bridge.exit_code)

    def test_a_block_of_another_type_is_dropped_once_one_answered(self):
        s = Session()
        s.receive(device_frame(self.HANDSHAKE))
        s.ack()
        s.receive(device_frame(self.STATE))
        # A v1-numbered block on a headset that answered 0x17 is not a v1
        # headset; reading it as one would move the panel to a mode nobody
        # asked for.
        s.receive(device_frame([NTFY, 0x02, 0x01, 0x02, 0x02, 0x01, 0x00, 0x00]))
        self.assertEqual(len(s.lines), 1)
        self.assertEqual(s.bridge.inquired, 0x17)


class Wh1000xm5(unittest.TestCase):
    """0x17, MDR v2 — huynguyendinhquang, PR #4. Frozen."""

    HANDSHAKE = [0x01, 0x00, 0x03, 0x00, 0x20, 0x16, 0x00, 0x00]
    STATE = [RET, 0x17, 0x01, 0x01, 0x01, 0x00, 0x14]

    def test_frozen_session(self):
        s = Session()
        s.receive(device_frame(self.HANDSHAKE))
        s.ack()
        s.receive(device_frame(self.STATE))
        s.command("set anc")
        s.ack()
        s.command("voice on")

        # The voice switch goes out in the mode the headset last reported —
        # ambient — rather than dragging it anywhere on its own.
        self.assertEqual(s.sent, [
            [GET, 0x17],
            [SET, 0x17, 0x01, 1, 0, 0, 20],
            [SET, 0x17, 0x01, 1, 1, 1, 20],
        ])
        self.assertEqual(s.lines[0]["mode"], "ambient")
        self.assertIsNone(s.bridge.exit_code)


class Wh1000xm4(unittest.TestCase):
    """0x02, MDR v1 — seth-reee, PR #6. Frozen: change this with an XM4 in hand.

    Nobody here has one. What is pinned is what PROTOCOL.md records the headset
    answering, and the frames the bridge builds from it.
    """

    HANDSHAKE = [0x01, 0x00, 0x70, 0x00]
    # RET: on, DUAL_SINGLE_OFF, nc=DUAL, asm normal, level 0.
    STATE = [RET, 0x02, 0x01, 0x02, 0x02, 0x01, 0x00, 0x00]

    def test_frozen_session(self):
        s = Session(bridge_module.UUID_V1)
        s.receive(device_frame(self.HANDSHAKE))
        # Four bytes, so the v1 question comes first.
        self.assertEqual(s.sent, [[GET, 0x02]])

        s.ack()
        s.receive(device_frame(self.STATE))
        self.assertEqual(s.lines, [{"modes": True, "mode": "anc",
                                    "available": ["off", "anc", "ambient"],
                                    "level": 0, "voice": False}])
        # ncType came off the wire, not out of the default.
        self.assertEqual(s.bridge.nc_value, 0x02)

        for line in ("set off", "set ambient", "set anc", "level 5", "voice on"):
            s.command(line)
            s.ack()

        # As on the v2 models: each SET carries what the headset last reported,
        # so the level 5 is gone again by the voice switch, which goes out in
        # the reported mode (anc).
        self.assertEqual(s.sent, [
            [GET, 0x02],
            [SET, 0x02, 0, 0x02, 0, 0x01, 0, 0],
            [SET, 0x02, 1, 0x02, 1, 0x01, 0, 0],
            [SET, 0x02, 1, 0x02, 2, 0x01, 0, 0],
            [SET, 0x02, 1, 0x02, 1, 0x01, 0, 5],
            [SET, 0x02, 1, 0x02, 2, 0x01, 1, 0],
        ])
        self.assertEqual(len(s.lines), 1)

        s.receive(device_frame([NTFY, 0x02, 0x01, 0x02, 0x01, 0x01, 0x01, 0x05]))
        self.assertEqual(s.lines[-1], {"modes": True, "mode": "ambient",
                                       "available": ["off", "anc", "ambient"],
                                       "level": 5, "voice": True})
        self.assertIsNone(s.bridge.exit_code)

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
        s.receive(device_frame([0x01, 0x00, 0x70, 0x00]))
        self.assertEqual(s.sent, [[GET, 0x02]])

        s.ack()
        s.fire()                                   # 0x02 goes unanswered
        s.ack()
        self.assertEqual(s.sent[-1], [GET, 0x17])

        s.receive(device_frame([RET, 0x17, 0x01, 0x01, 0x01, 0x00, 0x14]))
        self.assertEqual(s.bridge.inquired, 0x17)
        self.assertEqual(s.lines[-1]["mode"], "ambient")
        self.assertIsNone(s.bridge.exit_code)

    def test_every_candidate_has_a_mode_list(self):
        for candidate in bridge_module.CANDIDATES:
            self.assertIn(candidate, bridge_module.AVAILABLE)


class Silent(unittest.TestCase):
    def test_nothing_answers_and_the_address_is_parked(self):
        s = Session()
        s.receive(device_frame([0x01, 0x00, 0x03, 0x00, 0x10, 0x02, 0x00, 0x00]))
        for _ in bridge_module.CANDIDATES:
            s.ack()
            s.fire()
        self.assertEqual(s.sent, [[GET, 0x17], [GET, 0x15], [GET, 0x22],
                                  [GET, 0x02]])
        self.assertEqual(s.bridge.exit_code, bridge_module.EXIT_UNSUPPORTED)


if __name__ == "__main__":
    unittest.main()
