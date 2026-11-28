"""What bose-bridge sends Bose headsets.

    python -m unittest tests.bose_bridge_test

The frozen session is tests/pins/bose/qc45.json. What is here is the framing
(the BMAP length-field framer) and the rules that hold across models: how the
channel is found and confirmed, who answers the listening-mode query, what a
silent headset does.

No hardware and no socket: the bridge's only two effects on the world are the
socket's sendall() and emit(), and both are captured.
"""
import socket
import time
import types
import unittest

from tests import harness

bridge_module = harness.load_bridge("bose-bridge")


class FakeSocket:
    def __init__(self, frames):
        self.frames = frames

    def sendall(self, data):
        self.frames.append(bytes(data))


class Session(harness.Session):
    """A Bose session. "device" in a pin is a BMAP reply as hex, fed through
    the bridge's framer and parsers. "sent" is every frame the bridge wrote,
    as hex. "open" is the socket coming up with the [0.1] init already
    answered (connect()'s channel probe did that off-pin); "fire" is a poll.
    """

    def __init__(self):
        super().__init__(bridge_module)
        self.bridge = bridge_module.Bridge("AC:BF:71:64:56:B9")
        self.bridge.sock = FakeSocket(self.frames)

    def do_open(self):
        self.bridge.on_open()

    def fire(self):
        self.bridge.poll()

    def device(self, spec):
        self.bridge.buffer += harness.hexbytes(spec)
        for frame in bridge_module.take_frames(self.bridge.buffer):
            self.bridge.on_frame(*frame)
            if self.bridge.exit_code is not None:
                return


harness.pin_tests(globals(), "bose-bridge", Session)


class Framing(unittest.TestCase):
    """take_frames: the length field is the framer, and nothing is guessed."""

    def test_one_answer_parses_from_the_init(self):
        frames = bridge_module.take_frames(
            bytearray(harness.hexbytes("00 01 03 05 31 2e 31 2e 30")))
        self.assertEqual(len(frames), 1)
        fblock, func, op, payload = frames[0]
        self.assertEqual((fblock, func, op), (0x00, 0x01, 0x03))
        self.assertEqual(payload, b"1.1.0")

    def test_a_real_reply_survives_being_split_at_every_byte_boundary(self):
        block = bytearray(harness.hexbytes("1f 03 03 01 01"))
        for cut in range(1, len(block)):
            buffer = bytearray()
            frames = []
            for chunk in (block[:cut], block[cut:]):
                buffer += chunk
                frames += bridge_module.take_frames(buffer)
            self.assertEqual(len(frames), 1, "split at %d" % cut)
            self.assertEqual(frames[0][:3], (0x1F, 0x03, 0x03))

    def test_two_answers_in_one_read_are_both_taken(self):
        block = bytearray(harness.hexbytes(
            "02 02 03 04 5a ff ff 00" "1f 03 03 01 01"))
        frames = bridge_module.take_frames(block)
        self.assertEqual([f[:2] for f in frames], [(2, 2), (31, 3)])
        self.assertEqual(block, bytearray())

    def test_a_length_that_has_not_arrived_waits_rather_than_guesses(self):
        # length 0x05 but only three payload bytes: not a frame yet.
        buffer = bytearray(harness.hexbytes("1f 03 03 05 01 01"))
        self.assertEqual(bridge_module.take_frames(buffer), [])
        buffer += bytearray(harness.hexbytes("00 00 00"))
        self.assertEqual(len(bridge_module.take_frames(buffer)), 1)

    def test_a_truncated_header_waits(self):
        buffer = bytearray(harness.hexbytes("1f 03"))
        self.assertEqual(bridge_module.take_frames(buffer), [])


class Battery(unittest.TestCase):
    def test_the_real_shape_reads_the_first_byte(self):
        self.assertEqual(bridge_module.parse_battery(
            harness.hexbytes("5a ff ff 00")), 90)

    def test_a_level_over_100_is_dropped_not_clamped(self):
        self.assertIsNone(bridge_module.parse_battery(
            harness.hexbytes("65 ff ff 00")))

    def test_an_empty_payload_is_no_level(self):
        self.assertIsNone(bridge_module.parse_battery(b""))

    def test_no_earpiece_components_are_invented(self):
        s = Session()
        s.device("02 02 03 04 5a ff ff 00")
        self.assertEqual(s.bridge.battery, 90)  # stored, not yet a line
        self.assertEqual(s.lines, [])
        s.device("1f 03 03 01 01")
        self.assertEqual(s.lines[-1]["battery"], {"headset": 90, "charging": []})
        self.assertNotIn("left", s.lines[-1]["battery"])


class Silent(unittest.TestCase):
    def test_no_mode_answer_parks_the_address(self):
        s = Session()
        s.bridge.finish(bridge_module.EXIT_UNSUPPORTED,
                        "the headset did not answer the listening-mode query")
        self.assertEqual(s.bridge.exit_code, bridge_module.EXIT_UNSUPPORTED)
        self.assertEqual(s.lines[-1]["modes"], False)

    def test_battery_without_a_mode_answer_prints_nothing(self):
        s = Session()
        s.do_open()
        s.device("02 02 03 04 5a ff ff 00")
        self.assertEqual(s.lines, [])
        self.assertIsNone(s.bridge.exit_code)

    def test_nothing_is_written_before_the_mode_is_known(self):
        s = Session()
        s.command("set anc")
        s.command("set ambient")
        self.assertEqual(len(s.sent), 0)


class Unsupported(unittest.TestCase):
    def _answered(self):
        s = Session()
        s.do_open()
        s.device("02 02 03 04 5a ff ff 00")
        s.device("1f 03 03 01 01")
        return s

    def test_off_talkthru_and_levels_are_never_sent(self):
        s = self._answered()
        s.command("set off")
        s.command("set talkthru")
        s.command("level 5")
        s.command("voice on")
        s.command("latency off")
        settled = list(s.sent)
        self.assertEqual(len(settled), 2)  # just the two startup queries

    def test_the_unmapped_second_mode_index_is_not_forced_into_a_name(self):
        s = self._answered()
        settled = dict(s.lines[-1])
        s.device("1f 03 03 01 02")  # QC45 custom slot 2, never configured
        self.assertEqual(s.lines[-1], settled)
        self.assertEqual(s.bridge.mode, "ambient")
        self.assertIsNone(s.bridge.exit_code)

    def test_a_battery_announcement_alone_moves_the_line(self):
        s = self._answered()
        s.device("02 02 03 04 59 ff ff 00")
        self.assertEqual(s.lines[-1]["battery"], {"headset": 89, "charging": []})
        self.assertEqual(s.lines[-1]["mode"], "ambient")


def mode_config(index, prompt=0, editable=0, configured=0, favourite=0,
                name=b"", cnc=0):
    """A 47-byte [31.6] STATUS frame as the QC45 sends it, as a hex string."""
    payload = bytearray(47)
    payload[0], payload[1], payload[2] = index, prompt >> 8, prompt & 0xff
    payload[3], payload[4], payload[5] = editable, configured, favourite
    payload[6:6 + len(name)] = name
    payload[42] = cnc
    return (bytes([0x1f, 0x06, 0x03, 47]) + payload).hex(" ")


class CustomSlots(unittest.TestCase):
    """Every configured custom slot from GetAll is offered as its own mode,
    "custom<index>", under its name or, with none, the voice prompt the
    headset announces for it. GetAll is sent only once the headset reports a
    slot that is not Quiet or Aware. The base table is the QC45 in
    tests/pins/bose/qc-headphones.json: slot 2 is prompt Work, slot 3
    is configured but has neither name nor prompt."""

    def _session(self, current="1f 03 03 01 02", slot3=None):
        s = Session()
        s.do_open()
        s.device("02 02 03 04 64 ff ff 00")
        s.device(current)
        s.device(mode_config(0, prompt=1, favourite=1, name=b"Quiet"))
        s.device(mode_config(1, prompt=2, favourite=1, name=b"Aware", cnc=10))
        s.device(mode_config(2, prompt=11, editable=1, configured=1, favourite=1))
        s.device(slot3 or mode_config(3, editable=1, configured=1))
        return s

    def test_quiet_and_aware_alone_never_ask_for_the_slot_table(self):
        s = Session()
        s.do_open()
        s.device("1f 03 03 01 01")
        s.device("1f 03 03 01 00")
        s.fire()
        self.assertNotIn("1f 01 05 00", s.sent)

    def test_a_custom_slot_asks_for_the_table_once(self):
        s = self._session()
        self.assertEqual(s.sent.count("1f 01 05 00"), 1)
        s.device("1f 03 03 01 03")
        s.device("1f 03 03 01 02")
        self.assertEqual(s.sent.count("1f 01 05 00"), 1)

    def test_the_prompt_names_a_slot_with_no_name(self):
        s = self._session()
        self.assertEqual(s.lines[-1]["available"], ["anc", "ambient", "custom2"])
        self.assertEqual(s.lines[-1]["modeLabels"], {"custom2": "Work"})
        self.assertEqual(s.lines[-1]["mode"], "custom2")

    def test_both_slots_set_up_are_both_offered_in_slot_order(self):
        s = self._session(slot3=mode_config(3, editable=1, configured=1,
                                            name=b"Late night"))
        self.assertEqual(s.lines[-1]["available"],
                         ["anc", "ambient", "custom2", "custom3"])
        self.assertEqual(s.lines[-1]["modeLabels"],
                         {"custom2": "Work", "custom3": "Late night"})
        s.command("set custom3")
        self.assertEqual(s.sent[-1], "1f 03 05 02 03 00")
        s.device("1f 03 03 01 03")
        self.assertEqual(s.lines[-1]["mode"], "custom3")

    def test_a_prompt_never_seen_is_offered_without_a_label(self):
        s = self._session(slot3=mode_config(3, prompt=12, editable=1, configured=1))
        self.assertEqual(s.lines[-1]["available"],
                         ["anc", "ambient", "custom2", "custom3"])
        self.assertEqual(s.lines[-1]["modeLabels"], {"custom2": "Work"})

    def test_more_slots_than_a_qc45_has(self):
        s = Session()
        s.do_open()
        s.device("1f 03 03 01 05")
        for index in range(5, 11):
            s.device(mode_config(index, name=b"Slot %d" % index,
                                 editable=1, configured=1))
        self.assertEqual(s.lines[-1]["available"][2:],
                         ["custom5", "custom6", "custom7", "custom8", "custom9", "custom10"])
        self.assertEqual(s.lines[-1]["mode"], "custom5")

    def test_switching_away_and_back(self):
        s = self._session()
        s.command("set anc")
        self.assertEqual(s.sent[-1], "1f 03 05 02 00 00")
        s.device("1f 03 03 01 00")
        self.assertEqual(s.lines[-1]["mode"], "anc")
        s.command("set custom2")
        self.assertEqual(s.sent[-1], "1f 03 05 02 02 00")
        s.device("1f 03 03 01 02")
        self.assertEqual(s.lines[-1]["mode"], "custom2")

    def test_a_slot_not_offered_is_never_switched_to(self):
        s = self._session()
        before = list(s.sent)
        s.command("set custom3")   # configured, but no name or prompt
        s.command("set custom9")   # no such slot
        s.command("set custom")    # the bare prefix names nothing
        self.assertEqual(s.sent, before)

    def test_a_slot_that_stops_qualifying_is_withdrawn(self):
        s = self._session(current="1f 03 03 01 01")
        s.device("1f 03 03 01 02")
        s.device(mode_config(2, prompt=11, editable=1, configured=1))
        self.assertIn("custom2", s.lines[-1]["available"])
        s.device(mode_config(2, prompt=11, editable=1, configured=0))
        self.assertNotIn("modeLabels", s.lines[-1])
        self.assertEqual(s.lines[-1]["available"], ["anc", "ambient"])

    def test_the_owners_own_name_wins_over_the_prompt(self):
        s = Session()
        s.do_open()
        s.device("1f 03 03 01 02")
        s.device(mode_config(2, prompt=11, editable=1, configured=1, name=b"Desk"))
        self.assertEqual(s.lines[-1]["modeLabels"], {"custom2": "Desk"})

    def test_an_unconfigured_slot_as_in_the_original_capture_is_not_offered(self):
        s = Session()
        s.do_open()
        s.device("1f 03 03 01 02")
        s.device(mode_config(2, editable=1, configured=0))
        self.assertNotIn("modeLabels", s.lines[-1])
        self.assertEqual(s.lines[-1]["available"], ["anc", "ambient"])


class ChannelSelection(unittest.TestCase):
    """The known channel is asked first, then the others, and a channel only
    counts when it answers the [0.1] probe as well as opening."""

    def _connect_with(self, open_channels, speaks=None):
        tried = []

        class FakeSock:
            def __init__(self, *_args):
                self.channel = None
                self.opened = False

            def settimeout(self, *_):
                pass

            def setblocking(self, *_):
                pass

            def close(self):
                pass

            def connect(self, target):
                _address, channel = target
                tried.append(channel)
                self.channel = channel
                if channel not in open_channels:
                    raise OSError(111, "Connection refused")

            def sendall(self, data):
                self.sent = bytes(data)

            def recv(self, _n):
                if speaks and not self.opened and self.channel in speaks:
                    self.opened = True
                    return bytes(speaks[self.channel])
                raise socket.timeout

        fake = types.SimpleNamespace(
            AF_BLUETOOTH=getattr(socket, "AF_BLUETOOTH", 31),
            SOCK_STREAM=getattr(socket, "SOCK_STREAM", 1),
            BTPROTO_RFCOMM=getattr(socket, "BTPROTO_RFCOMM", 3),
            timeout=socket.timeout,
            socket=FakeSock,
        )
        bridge = bridge_module.Bridge("AC:BF:71:64:56:B9")
        saved_socket = bridge_module.socket
        saved_attempts = bridge_module.CONNECT_ATTEMPTS
        saved_timeout = bridge_module.PROBE_TIMEOUT
        bridge_module.socket = fake
        bridge_module.CONNECT_ATTEMPTS = 1  # no retry sleeps in a unit test
        bridge_module.PROBE_TIMEOUT = 0.05  # ditto for silent channels
        try:
            ok = bridge.connect()
        finally:
            bridge_module.socket = saved_socket
            bridge_module.CONNECT_ATTEMPTS = saved_attempts
            bridge_module.PROBE_TIMEOUT = saved_timeout
        return ok, tried, bridge

    def test_channel_8_answers_and_2_and_9_are_never_tried(self):
        ok, tried, bridge = self._connect_with(
            {8}, speaks={8: bytes.fromhex("00 01 03 05 31 2e 31 2e 30")})
        self.assertTrue(ok)
        self.assertEqual(tried, [8])
        self.assertEqual(bridge.channel, 8)

    def test_a_channel_that_opens_but_does_not_speak_is_tried_next(self):
        ok, tried, bridge = self._connect_with(
            {8, 2}, speaks={2: bytes.fromhex("00 01 03 05 31 2e 31 2e 30")})
        self.assertTrue(ok)
        self.assertEqual(tried, [8, 2])
        self.assertEqual(bridge.channel, 2)

    def test_sockets_that_open_but_say_nothing_park_the_address(self):
        ok, tried, bridge = self._connect_with({8, 2, 9})
        self.assertFalse(ok)
        self.assertEqual(tried, [8, 2, 9])
        self.assertEqual(bridge.exit_code, bridge_module.EXIT_UNSUPPORTED)
        self.assertIsNone(bridge.channel)

    def test_a_device_that_never_opens_is_transient(self):
        ok, tried, bridge = self._connect_with(set())
        self.assertFalse(ok)
        self.assertEqual(tried, [8, 2, 9])
        self.assertEqual(bridge.exit_code, bridge_module.EXIT_TRANSIENT)
        self.assertIsNone(bridge.channel)


class StrictOrder(unittest.TestCase):
    """The wire between a set and the readback that settles it."""

    def test_a_set_sends_the_start_and_waits_for_the_device_to_say(self):
        s = Session()
        s.do_open()
        s.device("02 02 03 04 5a ff ff 00")
        s.device("1f 03 03 01 01")
        first = dict(s.lines[-1])
        s.command("set anc")
        self.assertEqual(s.sent[-1], "1f 03 05 02 00 00")
        # The PROCESSING ack is not a state change.
        s.device("1f 03 07 00")
        self.assertEqual(s.lines[-1], first)
        self.assertEqual(s.bridge.mode, "ambient")
        # The device's own readback is what moves the line.
        s.fire()
        s.device("1f 03 03 01 00")
        self.assertEqual(s.lines[-1]["mode"], "anc")


class Isolation(unittest.TestCase):
    def test_a_second_headset_does_not_disturb_the_first(self):
        first = Session()
        first.do_open()
        first.device("02 02 03 04 5a ff ff 00")
        first.device("1f 03 03 01 01")
        first_line = dict(first.lines[-1])
        second = Session()  # from here module.emit points at `second`
        second.do_open()
        second.device("02 02 03 04 58 ff ff 00")
        second.device("1f 03 03 01 00")
        self.assertEqual(first.bridge.mode, "ambient")
        self.assertEqual(first.bridge.battery, 90)
        self.assertEqual(first.lines[-1], first_line)
        self.assertEqual(second.bridge.mode, "anc")
        self.assertEqual(second.bridge.battery, 88)


if __name__ == "__main__":
    unittest.main()