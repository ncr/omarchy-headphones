"""The [1.6] path: the question a Bose that refuses [31.3] is asked instead.

    python -m unittest tests.bose_qc35_test

The frozen session is tests/pins/bose/qc35.json and the evidence behind it is
docs/captures/bose-qc35.txt. What is here is everything a pin cannot say: that
the fallback is reached only on the headset's own ERROR, that a QC45 never
reaches it, and how this path behaves when the clock runs and the link breaks.

Frames marked synthetic are constructed to exercise a branch; every other byte
in this file was answered by the headset in the capture. No hardware, no
socket: the bridge's only effects are sendall() and emit(), and both are
captured.
"""
import unittest
from unittest.mock import patch

from tests import harness
from tests.bose_bridge_test import bridge_module as m, Session
from tests.bose_review_test import Clock, Sock, load_tool

tool = load_tool("bose_qc35_session")

# Every byte below is from docs/captures/bose-qc35.txt.
MODES_ERROR = "1f 03 04 01 03"        # [31.3] ERROR: no audio modes here
NOISE_LOW = "01 06 03 02 01 0b"       # [1.6] STATUS: value 1, mask 0b1011
NOISE_HIGH = "01 06 03 02 03 0b"      # [1.6] STATUS: value 3
NOISE_OFF_REPLY = "01 06 03 02 00 0b"  # [1.6] STATUS: value 0
NOISE_REFUSED = "01 06 04 01 06"      # [1.6] ERROR: the value outside the mask
BATTERY_70 = "02 02 03 01 46"         # [2.2] STATUS: one byte, 70%
# Unsolicited frames this headset sent after the init, unasked and unparsed.
CHATTER = "05 01 03 09 00 02 01 00 00 00 00 00 00" "04 02 06 06 08 b4 d2 34 88 65"


def answered(*frames):
    """A session on the [1.6] path, having answered what the pin's first
    steps answer: the ERROR that moves it there, then a [1.6] STATUS."""
    s = Session()
    s.do_open()
    s.device(BATTERY_70)
    s.device(MODES_ERROR)
    for frame in frames or (NOISE_LOW,):
        s.device(frame)
    return s


class PathSwitch(unittest.TestCase):
    """Which question a headset is asked is the headset's to answer."""

    def test_the_qc45_question_still_goes_out_first(self):
        s = Session()
        s.do_open()
        self.assertEqual(s.sent, ["02 02 01 00", "1f 03 01 00"])
        self.assertEqual(s.bridge.path, m.PATH_MODES)

    def test_an_error_asks_the_other_question_once(self):
        s = Session()
        s.do_open()
        s.device(MODES_ERROR)
        self.assertEqual(s.bridge.path, m.PATH_NOISE)
        self.assertEqual(s.sent[-1], "01 06 01 00")
        s.device(MODES_ERROR)  # a second refusal is not a second question
        self.assertEqual(s.sent.count("01 06 01 00"), 1)

    def test_an_error_alone_is_not_a_mode(self):
        s = Session()
        s.do_open()
        s.device(MODES_ERROR)
        self.assertIsNone(s.bridge.mode)
        self.assertEqual(s.lines, [])

    def test_a_headset_that_answers_the_audio_modes_is_never_asked(self):
        """The QC45's guarantee: its wire does not gain a frame."""
        s = Session()
        s.do_open()
        s.device("02 02 03 04 5a ff ff 00")
        s.device("1f 03 03 01 01")
        s.fire()
        s.command("set anc")
        self.assertEqual(s.bridge.path, m.PATH_MODES)
        self.assertNotIn("01 06 01 00", s.sent)
        self.assertEqual(s.lines[-1]["available"], ["anc", "ambient"])
        self.assertNotIn("ancLevels", s.lines[-1])

    def test_an_error_after_the_audio_modes_answered_keeps_the_qc45_question(self):
        """A headset that answered [31.3] once stays on it. The ERROR is
        synthetic: no QC45 capture shows one, which is why it must not move
        a QC45 onto a question it was never sent."""
        s = Session()
        s.do_open()
        s.device("02 02 03 04 5a ff ff 00")
        s.device("1f 03 03 01 01")
        s.command("set anc")
        s.device("1f 03 04 01 03")  # synthetic: the START refused
        s.fire()
        self.assertEqual(s.bridge.path, m.PATH_MODES)
        self.assertNotIn("01 06 01 00", s.sent)
        self.assertEqual(s.bridge.mode, "ambient")

    def test_an_error_after_an_unnamed_audio_mode_keeps_the_qc45_question(self):
        """A STATUS naming a custom slot (2) leaves the mode unnamed, but the
        headset still answered [31.3]. The slot and the ERROR are synthetic."""
        s = Session()
        s.do_open()
        s.device("02 02 03 04 5a ff ff 00")
        s.device("1f 03 03 01 02")  # synthetic: a custom slot
        s.device("1f 03 04 01 03")  # synthetic: an ERROR after it
        self.assertEqual(s.bridge.path, m.PATH_MODES)
        self.assertNotIn("01 06 01 00", s.sent)

    def test_a_noise_reply_before_the_switch_is_ignored(self):
        s = Session()
        s.do_open()
        s.device(NOISE_LOW)  # unasked, and this headset has not refused [31.3]
        self.assertIsNone(s.bridge.mode)
        self.assertEqual(s.lines, [])

    def test_the_poll_follows_the_path(self):
        s = answered()
        s.fire()
        self.assertEqual(s.sent[-1], "01 06 01 00")
        self.assertNotIn("1f 03 01 00", s.sent[2:])


class Mask(unittest.TestCase):
    """The second byte of a [1.6] STATUS, and what is built on it."""

    def test_the_observed_reply_names_off_and_both_strengths(self):
        value, supported = m.parse_noise(harness.hexbytes("01 0b"))
        self.assertEqual(value, 1)
        self.assertEqual(supported, [0, 1, 3])

    def test_a_reply_without_the_mask_falls_back_to_the_named_levels(self):
        # SYNTHETIC: a one-byte [1.6] STATUS. This headset always sent two.
        value, supported = m.parse_noise(harness.hexbytes("01"))
        self.assertEqual(value, 1)
        self.assertIsNone(supported)
        s = answered("01 06 03 01 01")
        self.assertEqual(s.lines[-1]["ancLevels"], ["low", "high"])
        self.assertEqual(s.lines[-1]["available"], ["off", "anc"])

    def test_an_empty_payload_is_no_value(self):
        self.assertEqual(m.parse_noise(b""), (None, None))

    def test_a_mask_without_the_off_bit_does_not_offer_off(self):
        # SYNTHETIC: mask 0x0a, bits 1 and 3. This headset answered 0x0b.
        s = answered("01 06 03 02 01 0a")
        self.assertEqual(s.lines[-1]["available"], ["anc"])
        s.command("set off")
        self.assertNotIn("01 06 02 01 00", s.sent)

    def test_a_mask_with_one_strength_offers_one(self):
        # SYNTHETIC: mask 0x03, bits 0 and 1.
        s = answered("01 06 03 02 01 03")
        self.assertEqual(s.lines[-1]["ancLevels"], ["low"])
        self.assertEqual(s.lines[-1]["available"], ["off", "anc"])

    def test_an_unnamed_value_is_not_forced_into_a_name(self):
        s = answered()
        settled = dict(s.lines[-1])
        # SYNTHETIC: value 2, the one the headset refused to be set to.
        s.device("01 06 03 02 02 0b")
        self.assertEqual(s.lines[-1], settled)
        self.assertEqual(s.bridge.mode, "anc")
        self.assertEqual(s.bridge.level, "low")
        self.assertIsNone(s.bridge.exit_code)


class Strengths(unittest.TestCase):
    """The two strengths, named by the owner listening to them."""

    def test_the_names_come_from_the_hardware_not_the_published_tables(self):
        # The owner ranked the three values unnamed, twice each: 0x00 was the
        # loudest and 0x03 the quietest. The third-party tables for this
        # protocol say the reverse, and this is the assertion that keeps a
        # well-meaning correction from putting High on the weaker setting.
        self.assertEqual(m.NOISE_LEVEL_BY_VALUE[0x01], "low")
        self.assertEqual(m.NOISE_LEVEL_BY_VALUE[0x03], "high")
        self.assertEqual(answered(NOISE_LOW).lines[-1]["ancLevel"], "low")
        self.assertEqual(answered(NOISE_HIGH).lines[-1]["ancLevel"], "high")

    def test_off_is_a_mode_and_not_a_strength(self):
        s = answered(NOISE_OFF_REPLY)
        self.assertEqual(s.lines[-1]["mode"], "off")
        self.assertEqual(s.lines[-1]["ancLevels"], ["low", "high"])

    def test_the_strength_last_seen_is_kept_across_off(self):
        s = answered(NOISE_HIGH, NOISE_OFF_REPLY)
        self.assertEqual(s.lines[-1]["mode"], "off")
        self.assertEqual(s.lines[-1]["ancLevel"], "high")

    def test_set_anc_asks_for_the_strength_last_seen(self):
        s = answered(NOISE_HIGH, NOISE_OFF_REPLY)
        s.command("set anc")
        self.assertEqual(s.sent[-1], "01 06 02 01 03")

    def test_set_anc_with_no_strength_yet_asks_for_the_strongest(self):
        s = answered(NOISE_OFF_REPLY)
        self.assertEqual(s.lines[-1]["ancLevel"], "high")  # the panel's default
        self.assertIsNone(s.bridge.level)
        s.command("set anc")
        self.assertEqual(s.sent[-1], "01 06 02 01 03")

    def test_each_strength_is_asked_for_by_its_own_value(self):
        s = answered()
        s.command("level high")
        self.assertEqual(s.sent[-1], "01 06 02 01 03")
        s.command("level low")
        self.assertEqual(s.sent[-1], "01 06 02 01 01")

    def test_the_refusal_of_a_value_outside_the_mask_is_not_a_change(self):
        s = answered(NOISE_HIGH)
        settled = dict(s.lines[-1])
        s.device(NOISE_REFUSED)
        self.assertEqual(s.lines[-1], settled)
        self.assertIsNone(s.bridge.exit_code)


class Unsupported(unittest.TestCase):
    def test_nothing_this_headset_lacks_is_ever_sent(self):
        s = answered()
        before = list(s.sent)
        for command in ("set ambient", "set talkthru", "level mid",
                        "level adaptive", "level 5", "voice on", "latency on"):
            s.command(command)
        self.assertEqual(s.sent, before)

    def test_nothing_is_sent_before_the_headset_has_answered(self):
        s = Session()
        s.do_open()
        s.device(MODES_ERROR)
        before = list(s.sent)
        s.command("set off")
        s.command("level high")
        self.assertEqual(s.sent, before)


class Battery(unittest.TestCase):
    def test_the_one_byte_shape_this_generation_answers(self):
        self.assertEqual(m.parse_battery(harness.hexbytes("46")), 70)

    def test_it_rides_on_the_noise_line(self):
        s = answered()
        self.assertEqual(s.lines[-1]["battery"],
                         {"headset": 70, "charging": []})
        self.assertNotIn("left", s.lines[-1]["battery"])

    def test_a_level_over_100_is_dropped_not_clamped(self):
        # SYNTHETIC: this headset answered 0x46. 0x65 exercises the bound.
        self.assertIsNone(m.parse_battery(harness.hexbytes("65")))

    def test_a_battery_announcement_alone_moves_the_line(self):
        s = answered()
        # SYNTHETIC: 69%, derived from the observed 70%.
        s.device("02 02 03 01 45")
        self.assertEqual(s.lines[-1]["battery"],
                         {"headset": 69, "charging": []})
        self.assertEqual(s.lines[-1]["ancLevel"], "low")


class Framing(unittest.TestCase):
    def test_a_noise_reply_survives_being_split_at_every_byte_boundary(self):
        for cut in range(1, len(harness.hexbytes(NOISE_HIGH))):
            s = Session()
            s.do_open()
            s.device(MODES_ERROR)
            whole = harness.hexbytes(NOISE_HIGH)
            s.device(whole[:cut].hex(" "))
            s.device(whole[cut:].hex(" "))
            self.assertEqual(s.bridge.level, "high", "split at %d" % cut)

    def test_the_error_and_the_answer_in_one_read_are_both_taken(self):
        s = Session()
        s.do_open()
        s.device(MODES_ERROR + NOISE_HIGH)
        self.assertEqual(s.bridge.path, m.PATH_NOISE)
        self.assertEqual(s.bridge.mode, "anc")
        self.assertEqual(s.bridge.level, "high")

    def test_the_chatter_this_headset_sends_unasked_is_stepped_over(self):
        s = Session()
        s.do_open()
        s.device(MODES_ERROR)
        s.device(CHATTER + NOISE_LOW)
        self.assertEqual(s.bridge.mode, "anc")
        self.assertEqual(s.lines[-1]["ancLevel"], "low")
        self.assertIsNone(s.bridge.exit_code)


class RunLoop(unittest.TestCase):
    """Driven through the clock and the loop, not by calling finish()."""

    def test_a_refusal_then_silence_parks_the_address(self):
        s = Session()
        s.bridge.buffer += harness.hexbytes(MODES_ERROR)
        clock = Clock()

        def select(*_args):
            clock.now += 2
            return [], [], []

        with patch.object(s.bridge, "connect", return_value=True), \
                patch.object(m.time, "monotonic", clock.monotonic), \
                patch.object(m.select, "select", side_effect=select):
            self.assertEqual(s.bridge.run(), 3)
        self.assertEqual(s.bridge.path, m.PATH_NOISE)
        self.assertGreater(s.bridge.polls, 0)
        self.assertFalse(s.lines[-1]["modes"])

    def test_the_delayed_readback_asks_the_noise_question(self):
        s = Session()
        clock = Clock()
        sock = Sock([harness.hexbytes(MODES_ERROR + NOISE_LOW),
                     harness.hexbytes(NOISE_HIGH)])
        s.bridge.sock = sock
        steps = []
        reads = iter([b"level high\n", b""])

        def select(*_args):
            steps.append(1)
            if len(steps) == 1:
                return [sock], [], []      # the refusal and the first answer
            if len(steps) == 2:
                return [0], [], []         # the command
            if len(steps) == 3:
                clock.now = 2.1            # past READBACK_DELAY, before a poll
                return [], [], []
            if len(steps) == 4:
                return [sock], [], []      # what the readback brought
            return [0], [], []             # stdin EOF: a clean stop

        with patch.object(s.bridge, "connect", return_value=True), \
                patch.object(m.time, "monotonic", clock.monotonic), \
                patch.object(m.select, "select", side_effect=select), \
                patch.object(m.os, "read", side_effect=lambda *_: next(reads, b"")):
            self.assertEqual(s.bridge.run(), 0)
        self.assertEqual(s.bridge.level, "high")
        self.assertEqual(s.bridge.polls, 0)  # the readback, not a poll
        self.assertEqual(sock.sent.count(m.NOISE), 2)
        self.assertEqual(sock.sent.count(m.CURRENT), 1)  # the one at open

    def test_a_reset_on_this_path_is_transient(self):
        s = answered()
        s.bridge.sock = Sock([ConnectionResetError("synthetic reset")])
        with patch.object(s.bridge, "connect", return_value=True), \
                patch.object(m.select, "select",
                             return_value=([s.bridge.sock], [], [])):
            self.assertEqual(s.bridge.run(), 1)
        self.assertIn("closed", s.lines[-1]["error"])

    def test_the_link_going_away_on_this_path_is_transient(self):
        s = answered()
        s.bridge.sock = Sock([b""])
        with patch.object(s.bridge, "connect", return_value=True), \
                patch.object(m.select, "select",
                             return_value=([s.bridge.sock], [], [])):
            self.assertEqual(s.bridge.run(), 1)
        self.assertFalse(s.lines[-1]["modes"])


class Isolation(unittest.TestCase):
    def test_a_qc35_and_a_qc45_do_not_disturb_each_other(self):
        qc45 = Session()
        qc45.do_open()
        qc45.device("02 02 03 04 5a ff ff 00")
        qc45.device("1f 03 03 01 01")
        settled = dict(qc45.lines[-1])
        qc35 = answered()  # from here the module's emit points at this one
        self.assertEqual(qc45.bridge.path, m.PATH_MODES)
        self.assertEqual(qc45.bridge.mode, "ambient")
        self.assertEqual(qc45.bridge.battery, 90)
        self.assertEqual(qc45.lines[-1], settled)
        self.assertEqual(qc35.bridge.path, m.PATH_NOISE)
        self.assertEqual(qc35.bridge.mode, "anc")
        self.assertEqual(qc35.bridge.battery, 70)


class ToolLink:
    """A CaptureLink stand-in answering what this headset answered.

    `mask` is the second byte of a [1.6] STATUS; a value whose bit it leaves
    clear is refused the way the headset refused 2, and nothing moves.
    """

    def __init__(self, initial=1, mask=0x0b, interrupt_on=None,
                 noop_moves_to=None):
        self.value = initial
        self.mask = mask
        self.interrupt_on = interrupt_on
        self.noop_moves_to = noop_moves_to
        self.interrupted = False
        self.writes = []
        self.logs = []

    def log(self, text):
        self.logs.append(text)

    def collect(self, _wait):
        return []

    def exchange(self, frame, label, wait=None):
        self.writes.append(frame)
        if frame == tool.INIT:
            return [(0, 1, 3, b"1.0.4")]
        if frame == tool.BATTERY:
            return [(2, 2, 3, bytes([70]))]
        if frame == tool.QC45_MODES:
            return [(31, 3, 4, bytes([3]))]
        if frame == tool.NOISE:
            if self.value is None:
                return []
            payload = (bytes([self.value]) if self.mask is None
                       else bytes([self.value, self.mask]))
            return [(1, 6, 3, payload)]
        if frame[:3] == bytes([1, 6, 2]):
            wanted = frame[4]
            if wanted == self.interrupt_on and not self.interrupted:
                self.interrupted = True
                raise KeyboardInterrupt
            if self.noop_moves_to is not None and wanted == self.value:
                self.value = self.noop_moves_to
            elif self.mask is None or self.mask & (1 << wanted):
                self.value = wanted
            else:
                return [(1, 6, 4, bytes([6]))]
            return [(1, 6, 3, bytes([self.value, self.mask]))]
        return []

    def driven(self):
        return [f[4] for f in self.writes if f[:3] == bytes([1, 6, 2])]


class Tool(unittest.TestCase):
    """tools/bose_qc35_session.py, which changes a setting and must put it
    back. These are tests of what it does, not of what it contains."""

    def test_read_only_discovery_writes_nothing(self):
        link = ToolLink()
        value, listed = tool.run_discovery(link)
        self.assertEqual((value, listed), (1, [0, 1, 3]))
        self.assertEqual(link.driven(), [])

    def test_it_restores_the_actual_initial_value(self):
        for initial in (0, 1, 3):
            link = ToolLink(initial=initial)
            tool.run_session(link)
            self.assertEqual(link.value, initial)
            self.assertEqual(link.writes[-2], tool.set_noise(initial))
            self.assertEqual(link.writes[-1], tool.NOISE)

    def test_an_unknown_initial_value_prevents_every_write(self):
        link = ToolLink(initial=None)
        with self.assertRaises(RuntimeError):
            tool.run_session(link)
        self.assertEqual(link.driven(), [])

    def test_a_no_op_write_that_moves_the_setting_stops_before_driving(self):
        link = ToolLink(initial=1, noop_moves_to=3)
        with self.assertRaises(RuntimeError):
            tool.run_session(link)
        self.assertEqual(link.driven(), [1, 1])  # the no-op, then the restore

    def test_it_restores_after_an_interrupted_write(self):
        link = ToolLink(initial=1, interrupt_on=0)
        with self.assertRaises(KeyboardInterrupt):
            tool.run_session(link)
        self.assertEqual(link.value, 1)
        self.assertTrue(any("restored" in text for text in link.logs))

    def test_a_failed_restoration_is_reported_not_hidden(self):
        link = ToolLink(initial=1)
        exchange = link.exchange

        def fail_restore(frame, label, wait=None):
            if label.startswith("restore"):
                raise ConnectionError("synthetic disconnect")
            return exchange(frame, label, wait)

        link.exchange = fail_restore
        with self.assertRaises(ConnectionError):
            tool.run_session(link)
        self.assertTrue(any("RESTORATION FAILED" in t for t in link.logs))

    def test_only_the_values_the_mask_names_are_driven(self):
        link = ToolLink(initial=1)
        tool.run_session(link)
        self.assertEqual(link.driven(), [1, 0, 1, 3, 1])

    def test_probing_the_unlisted_values_is_off_by_default(self):
        link = ToolLink(initial=1)
        tool.run_session(link, probe_unlisted=True)
        self.assertIn(2, link.driven())
        self.assertEqual(link.value, 1)
        again = ToolLink(initial=1)
        tool.run_session(again)
        self.assertNotIn(2, again.driven())

    def test_the_ranking_presents_each_state_twice_and_restores(self):
        link = ToolLink(initial=1)
        said = []
        states = tool.run_ranking(link, announce=lambda *a: said.append(a[0]))
        self.assertEqual(states, [(1, 0), (2, 1), (3, 3)])
        for label in (1, 2, 3):
            self.assertEqual(said.count("STATE %d" % label), 2)
        self.assertEqual(link.driven(), [0, 1, 3, 0, 1, 3, 1])
        self.assertEqual(link.value, 1)

    def test_a_reply_split_across_reads_is_kept_and_then_taken(self):
        whole = harness.hexbytes(NOISE_LOW)
        clock = Clock()
        sock = Sock()
        chunks = iter([whole[:3], whole[3:]])

        def recv(_count):
            clock.now += 1
            return next(chunks)

        sock.recv = recv
        link = tool.CaptureLink(sock, wait=1)
        with patch.object(tool.time, "monotonic", clock.monotonic), \
                patch.object(link, "log") as logged:
            self.assertEqual(link.exchange(tool.NOISE, "first"), [])
            self.assertEqual(link.buffer, whole[:3])
            self.assertEqual(link.exchange(tool.NOISE, "second"),
                             [(1, 6, 3, whole[4:])])
        self.assertEqual(link.buffer, bytearray())
        # Both halves were logged as they landed, not once at the end.
        self.assertEqual(sum("<<< RAW" in c.args[0]
                             for c in logged.call_args_list), 2)


if __name__ == "__main__":
    unittest.main()
