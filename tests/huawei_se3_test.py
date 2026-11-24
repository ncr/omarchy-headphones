"""The FreeBuds SE 3 row of huawei-bridge, on the SE 3's own replies.

    python -m unittest tests.huawei_se3_test

The frozen session is tests/pins/huawei/freebuds-se-3.json and the evidence
behind it is docs/captures/huawei-freebuds-se-3.txt. A pin starts from an
open socket, so what is here is what it cannot say: that the row dials
channel 1, how the SE 3's frames survive being split and joined, what the
run loop does with silence, a refused connect and the reset this model
sends as the lid closes on its right bud, and that an SE 2 beside it keeps
its own reading.

Frames marked synthetic are bent on purpose to exercise a branch; every
other byte in this file was sent by the FreeBuds SE 3 in the capture. No
hardware and no socket: the bridge's only effects are sendall() and emit(),
and both are captured.
"""
import unittest

from tests import harness
from tests import huawei_bridge_test as se2
from tests.huawei_bridge_test import bridge_module as m, Session

NAME = "HUAWEI FreeBuds SE 3"
ADDRESS = "00:8A:55:00:00:01"

QUERY = "5a 00 09 00 01 08 01 00 02 00 03 00 fb b9"

# Every frame below is from docs/captures/huawei-freebuds-se-3.txt.
HELLO = "5a 00 03 00 01 06 3e bd"
# Session 1: both buds out of the case.
EVENT_97_97_93 = "5a 00 14 00 01 27 01 01 61 02 03 61 61 5d 03 03 00 00 00 04 02 14 0a 4e 39"
ANSWER_97_97_93 = "5a 00 14 00 01 08 01 01 61 02 03 61 61 5d 03 03 00 00 00 04 02 14 0a ba 5c"
# Session 2: the lid closing on the left bud, and opening.
LID_CLOSED = "5a 00 06 00 2b 5f 01 01 01 13 24"
LEFT_UNDER_LID = "5a 00 14 00 01 08 01 01 60 02 03 00 60 5d 03 03 00 00 00 04 02 14 0a 7c 7c"
LID_OPEN = "5a 00 06 00 2b 5f 01 01 00 03 05"
ANSWER_96_96_93 = "5a 00 14 00 01 08 01 01 60 02 03 60 60 5d 03 03 00 00 00 04 02 14 0a cf 9c"
# Session 3: what the first connect after the reset was answered with, then
# the cable going in and coming out with the right bud docked, lid open.
RIGHT_UNDER_LID = "5a 00 14 00 01 27 01 01 60 02 03 60 00 5c 03 03 00 00 00 04 02 14 0a ba 13"
EVENT_96_96_92 = "5a 00 14 00 01 27 01 01 60 02 03 60 60 5c 03 03 00 00 00 04 02 14 0a 54 bc"
ON_CABLE = "5a 00 14 00 01 27 01 01 60 02 03 60 60 5c 03 03 00 00 01 04 02 14 0a fe ed"

CAPTURED = (HELLO, EVENT_97_97_93, ANSWER_97_97_93, LID_CLOSED, LEFT_UNDER_LID, LID_OPEN,
            ANSWER_96_96_93, RIGHT_UNDER_LID, EVENT_96_96_92, ON_CABLE)


def line(**battery):
    battery["caseStale"] = False
    return {"modes": True, "available": [], "battery": battery}


class Row(unittest.TestCase):
    def test_the_row_names_channel_1_and_the_se_2_row_is_as_it_was(self):
        self.assertEqual(m.MODELS[NAME], {"channel": 1})
        self.assertEqual(m.MODELS[se2.NAME], {"channel": 1})

    def test_a_near_miss_of_the_name_has_no_row(self):
        for name in ("HUAWEI FreeBuds SE 3i", "FreeBuds SE 3", "HUAWEI FreeBuds SE 4"):
            self.assertNotIn(name, m.MODELS)


class Framing(unittest.TestCase):
    def test_the_crc_reproduces_every_captured_frame(self):
        for text in CAPTURED:
            raw = harness.hexbytes(text)
            self.assertEqual(m.crc16(raw[:-2]), int.from_bytes(raw[-2:], "big"), text)

    def test_the_hello_and_two_battery_frames_in_one_read(self):
        buffer = bytearray(harness.hexbytes(" ".join((HELLO, EVENT_97_97_93, ANSWER_97_97_93))))
        frames = m.take_frames(buffer)
        self.assertEqual([(s, c) for s, c, _ in frames], [(1, 0x06), (1, 0x27), (1, 0x08)])
        self.assertEqual(buffer, bytearray())
        self.assertEqual(m.parse_battery(frames[2][2]), {"left": 97, "right": 97, "case": 93})

    def test_every_battery_frame_survives_being_split_at_every_byte_boundary(self):
        for text in (EVENT_97_97_93, ANSWER_97_97_93, LEFT_UNDER_LID, RIGHT_UNDER_LID, ON_CABLE):
            raw = harness.hexbytes(text)
            whole = m.parse_battery(m.take_frames(bytearray(raw))[0][2])
            for cut in range(1, len(raw)):
                buffer = bytearray()
                frames = []
                for chunk in (raw[:cut], raw[cut:]):
                    buffer += chunk
                    frames += m.take_frames(buffer)
                self.assertEqual(len(frames), 1, "%s split at %d" % (text, cut))
                self.assertEqual(m.parse_battery(frames[0][2]), whole)

    def test_the_lid_frame_and_the_reading_under_it_joined(self):
        frames = m.take_frames(bytearray(harness.hexbytes(LID_CLOSED + " " + LEFT_UNDER_LID)))
        self.assertEqual([(s, c) for s, c, _ in frames], [(0x2B, 0x5F), (1, 0x08)])
        self.assertEqual(m.parse_battery(frames[1][2]), {"right": 96, "case": 93})

    def test_each_bud_under_the_lid_reads_0_and_is_left_out(self):
        for text, reading in ((LEFT_UNDER_LID, {"right": 96, "case": 93}),
                              (RIGHT_UNDER_LID, {"left": 96, "case": 92})):
            frames = m.take_frames(bytearray(harness.hexbytes(text)))
            self.assertEqual(m.parse_battery(frames[0][2]), reading, text)

    def test_the_case_byte_on_a_cable_changes_nothing_read(self):
        readings = [m.parse_battery(m.take_frames(bytearray(harness.hexbytes(text)))[0][2])
                    for text in (EVENT_96_96_92, ON_CABLE)]
        self.assertEqual(readings, [{"left": 96, "right": 96, "case": 92}] * 2)


class Malformed(unittest.TestCase):
    """Fault injection: SE 3 frames bent on purpose. None of these is
    something the FreeBuds SE 3 was seen to send."""

    def test_a_flipped_byte_anywhere_in_an_answer_never_prints_a_wrong_reading(self):
        # Synthetic. A flip in the sync byte or the length may leave nothing
        # or wait for more; no flip may pass the CRC as a battery answer.
        raw = harness.hexbytes(ANSWER_97_97_93)
        for at in range(len(raw)):
            damaged = bytearray(raw)
            damaged[at] ^= 0xFF
            for _service, command, payload in m.take_frames(damaged):
                self.assertNotIn(command, (m.CMD_BATTERY, m.CMD_BATTERY_EVENT), "flip at %d" % at)

    def test_an_answer_cut_short_is_held_not_printed(self):
        # Synthetic: the frame ends early and the rest never comes.
        raw = harness.hexbytes(ANSWER_97_97_93)
        for keep in range(1, len(raw)):
            self.assertEqual(m.take_frames(bytearray(raw[:keep])), [], "kept %d" % keep)

    def test_a_damaged_frame_does_not_take_the_real_one_after_it(self):
        # Synthetic: a CRC-damaged event, then the real answer.
        damaged = bytearray(harness.hexbytes(EVENT_97_97_93))
        damaged[-1] ^= 0xFF
        s = Session(NAME)
        s.sock.incoming.append(bytes(damaged) + harness.hexbytes(ANSWER_96_96_93))
        s.bridge.on_socket()
        self.assertEqual(s.lines, [line(left=96, right=96, case=93)])


class Loop(unittest.TestCase):
    """The run loop on the SE 3 row, with the clock, the wait and the socket
    of tests/huawei_bridge_test.py."""

    setUp = se2.Loop.setUp
    tearDown = se2.Loop.tearDown
    script = se2.Loop.script

    def bridge(self):
        return m.Bridge(ADDRESS, NAME)

    def test_it_dials_channel_1_asks_once_and_prints_the_reading(self):
        self.script([(0.1, harness.hexbytes(HELLO + " " + EVENT_97_97_93), None),
                     (0.1, harness.hexbytes(ANSWER_97_97_93), None)])
        self.assertEqual(self.bridge().run(), 0)
        self.assertEqual(self.connects, [(ADDRESS, 1)])
        self.assertEqual([harness.hexstr(f) for f in self.frames], [QUERY])
        self.assertEqual(self.lines, [line(left=97, right=97, case=93)])

    def test_silence_is_exit_3_and_is_not_a_connection_failure(self):
        self.script([(0.1, harness.hexbytes(HELLO), None)] + [(None, None, None)] * 20)
        self.assertEqual(self.bridge().run(), m.EXIT_UNSUPPORTED)
        self.assertEqual(self.connects, [(ADDRESS, 1)], "connected, and not dialled again")
        self.assertEqual(self.lines[-1]["modes"], False)

    def test_a_refused_connect_is_exit_1_and_is_not_silence(self):
        # Synthetic: the refusal while a phone holds the channel was seen on
        # the SE 2, and not tried on the SE 3.
        self.refuse = 99
        self.assertEqual(self.bridge().run(), m.EXIT_TRANSIENT)
        self.assertEqual(self.connects, [(ADDRESS, 1)] * m.CONNECT_ATTEMPTS)
        self.assertEqual(self.frames, [], "nothing was asked")

    def test_stdin_commands_send_nothing(self):
        self.script([(0.1, harness.hexbytes(ANSWER_97_97_93), None),
                     (0.1, None, b"set anc\nset off\nlevel 5\n")])
        self.bridge().run()
        self.assertEqual([harness.hexstr(f) for f in self.frames], [QUERY])

    def test_the_reset_under_the_lid_is_exit_1_and_the_next_run_recovers(self):
        # The reset is what the SE 3 did as the lid first closed on the right
        # bud (ECONNRESET, sessions 2 and 3); the frames after it are what
        # the next connect was answered with in session 3.
        self.script([(0.1, harness.hexbytes(HELLO + " " + EVENT_96_96_92), None),
                     (0.1, OSError(104, "Connection reset by peer"), None)])
        self.assertEqual(self.bridge().run(), m.EXIT_TRANSIENT)
        self.assertEqual(self.lines[0], line(left=96, right=96, case=92))
        self.assertEqual(self.lines[-1]["modes"], False)

        del self.lines[:], self.frames[:], self.connects[:], self.sock.incoming[:]
        self.script([(0.1, harness.hexbytes(HELLO + " " + RIGHT_UNDER_LID), None),
                     (0.1, harness.hexbytes(LID_OPEN + " " + EVENT_96_96_92), None)])
        self.assertEqual(self.bridge().run(), 0)
        self.assertEqual(self.connects, [(ADDRESS, 1)])
        self.assertEqual([harness.hexstr(f) for f in self.frames], [QUERY])
        self.assertEqual(self.lines, [line(left=96, case=92),
                                      line(left=96, right=96, case=92)])


class Isolation(unittest.TestCase):
    """Two bridges are two processes. Here they share one module, so each
    frame is fed with emit pointed at the lines of the bridge it is for."""

    def feed(self, session, frame):
        m.emit = session.lines.append
        session.device(frame)

    def test_an_se_2_and_an_se_3_side_by_side_keep_their_own_readings(self):
        other, mine = Session(se2.NAME), Session(NAME)
        self.feed(other, se2.EVENT_98_98_23)
        self.feed(mine, EVENT_97_97_93)
        self.feed(mine, LID_CLOSED)
        self.feed(mine, LEFT_UNDER_LID)
        self.assertEqual(other.lines, [line(left=98, right=98, case=23)])
        self.assertEqual(mine.lines, [line(left=97, right=97, case=93),
                                      line(right=96, case=93)])
        self.feed(other, se2.LEFT_IN_CASE)
        self.assertEqual(other.lines[-1], line(right=97, case=23))
        self.assertEqual(len(mine.lines), 2, "the SE 2's lid is not the SE 3's")
        # The SE 3's next frame is compared with its own last reading.
        self.feed(mine, LEFT_UNDER_LID)
        self.assertEqual(len(mine.lines), 2, "unchanged, so not printed again")

if __name__ == "__main__":
    unittest.main()
