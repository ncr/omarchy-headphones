"""What redmi-bridge sends Redmi Buds 5, and what it prints.

    python -m unittest tests.redmi_bridge_test

The frozen session is tests/pins/redmi/buds-5.json. The frames here are
verbatim what a Redmi Buds 5 sent (docs/captures/redmi-buds-5.txt): left 75,
right 80, case 100, confirmed against the Xiaomi Earbuds app, and the noise
control going transparency -> cancelling -> off -> transparency. What is
here beyond the pin is the framing against those frames, damage the parser
must survive (synthetic, and marked as such), and the run loop driven through
the scheduled timers, the socket callbacks and a fake BlueZ: silence, a
dropped link, a closed pipe, a stop during connect.

No hardware and no socket: the bridge's effects on the world are write(),
emit() and the file descriptor callbacks, and all of them are captured.
"""
import contextlib
import errno
import io
import types
import unittest
from unittest import mock

from tests import harness

bridge = harness.load_bridge("redmi-bridge")

ADDRESS = "AA:BB:CC:00:00:01"

# GetTargetInfo answer, as the earbuds sent it.
ANSWER = bytes.fromhex(
    "fe dc ba 00 02 00 2c 00 01 05 01 10 38 10 38 05 03 27 17 50 6a 02 04 01 "
    "02 05 00 03 06 10 38 04 07 4b 50 64 02 08 02 02 09 00 02 0c 00 02 0d 02 "
    "02 0e 00 ef")
# GetDeviceConfig(11) answers: transparency, cancelling, off.
NOISE_AMBIENT = bytes.fromhex("fe dc ba 00 f3 00 07 00 01 04 00 0b 02 00 ef")
NOISE_ANC = bytes.fromhex("fe dc ba 00 f3 00 07 00 05 04 00 0b 01 00 ef")
NOISE_OFF = bytes.fromhex("fe dc ba 00 f3 00 07 00 07 04 00 0b 00 00 ef")
# What the earbuds announce on their own after a set.
NOTIFY_ANC = bytes.fromhex("fe dc ba c7 f4 00 06 05 04 00 0b 01 00 ef")
SET_ACK = bytes.fromhex("fe dc ba 00 f2 00 02 00 04 ef")
STATUS_REPORT_ANC = bytes.fromhex("fe dc ba c7 0e 00 04 04 02 04 01 ef")


class Session(harness.Session):
    """A Redmi session. "device" in a pin is bytes as hex, fed through the
    bridge's framer. "sent" is every frame the bridge wrote, as hex. "open" is
    the channel coming up, which asks for the mode and the battery (or, for a
    model whose row authenticates, sends the challenge) and schedules the
    first-answer check, the mode grace and the poll. A pin's session may name
    the model ("name", the bridge's second argument) and fix the 16-byte
    challenge it sends ("challenge", hex) to the one in its capture."""

    def __init__(self, name=None, challenge=None):
        super().__init__(bridge)
        model = bridge.MODELS[name] if name else bridge.NAMELESS
        self.bridge = bridge.Bridge(None, ADDRESS, harness.FakeLoop(), model)
        self.bridge.write = self.frames.append
        if challenge:
            self.bridge.make_challenge = lambda: harness.hexbytes(challenge)

    def device(self, spec):
        self.bridge.buffer += harness.hexbytes(spec)
        self.bridge.parse_buffer()

    def do_open(self):
        self.bridge.opened(-1)


harness.pin_tests(globals(), "redmi-bridge", Session)


class AskTest(unittest.TestCase):
    def test_battery_ask_is_get_target_info_with_every_attribute(self):
        self.assertEqual(bridge.encode_get_target_info(1).hex(" "),
                         "fe dc ba c0 02 00 05 01 ff ff ff ff ef")

    def test_noise_ask_is_get_device_config_11(self):
        self.assertEqual(bridge.encode_get_noise(1).hex(" "),
                         "fe dc ba c0 f3 00 03 01 00 0b ef")

    def test_noise_set_is_the_config_the_app_wrote(self):
        # The sets in the capture: transparency (sn 2), cancelling (4), off (6).
        self.assertEqual(bridge.encode_set_noise(2, 2, 0).hex(" "),
                         "fe dc ba c0 f2 00 06 02 04 00 0b 02 00 ef")
        self.assertEqual(bridge.encode_set_noise(4, 1, 0).hex(" "),
                         "fe dc ba c0 f2 00 06 04 04 00 0b 01 00 ef")
        self.assertEqual(bridge.encode_set_noise(6, 0, 0).hex(" "),
                         "fe dc ba c0 f2 00 06 06 04 00 0b 00 00 ef")

    def test_sequence_number_wraps_to_a_byte(self):
        self.assertEqual(bridge.encode_get_target_info(0x101)[7], 0x01)


class BatteryTest(unittest.TestCase):
    def test_left_right_case_from_the_captured_answer(self):
        self.assertEqual(bridge.battery_of(ANSWER),
                         {"left": 75, "right": 80, "case": 100, "charging": []})

    def test_the_status_report_the_earbuds_send_is_not_read_for_a_battery(self):
        # It carried none in the capture, so nothing is taken from it.
        self.assertIsNone(bridge.battery_of(STATUS_REPORT_ANC))

    # Synthetic below: the capture has no charging earbud and no empty one.
    def test_charging_bit_and_no_reading(self):
        self.assertEqual(bridge.battery_from([0xCB, 0x50, 0xFF]),
                         {"left": 75, "right": 80, "charging": ["left"]})

    def test_nothing_reported_is_none(self):
        self.assertIsNone(bridge.battery_from([0xFF, 0xFF, 0xFF]))

    def test_out_of_range_level_is_dropped(self):
        self.assertEqual(bridge.battery_from([0x7F, 0x50, 0x64]),
                         {"right": 80, "case": 100, "charging": []})

    def test_an_error_status_carries_no_battery(self):
        failed = bytearray(ANSWER)
        failed[7] = 0x01
        self.assertIsNone(bridge.battery_of(bytes(failed)))

    def test_other_opcodes_are_ignored(self):
        other = bytearray(ANSWER)
        other[4] = 0x05
        self.assertIsNone(bridge.battery_of(bytes(other)))

    def test_our_own_ask_echoed_back_is_not_an_answer(self):
        self.assertIsNone(bridge.battery_of(bridge.encode_get_target_info(1)))
        self.assertIsNone(bridge.noise_of(bridge.encode_get_noise(1)))


class NoiseTest(unittest.TestCase):
    def test_the_three_states(self):
        self.assertEqual(bridge.noise_of(NOISE_AMBIENT), (2, 0))
        self.assertEqual(bridge.noise_of(NOISE_ANC), (1, 0))
        self.assertEqual(bridge.noise_of(NOISE_OFF), (0, 0))

    def test_the_announcement_after_a_set(self):
        self.assertEqual(bridge.noise_of(NOTIFY_ANC), (1, 0))

    def test_the_set_ack_and_the_status_report_say_nothing_here(self):
        self.assertIsNone(bridge.noise_of(SET_ACK))
        self.assertIsNone(bridge.noise_of(STATUS_REPORT_ANC))

    # Synthetic: no state but 0, 1, 2 was seen.
    def test_an_unknown_state_is_not_a_mode(self):
        odd = bytearray(NOISE_ANC)
        odd[12] = 0x09
        self.assertIsNone(bridge.noise_of(bytes(odd)))

    def test_another_config_is_not_the_noise_control(self):
        other = bytearray(NOISE_ANC)
        other[11] = 0x25
        self.assertIsNone(bridge.noise_of(bytes(other)))

    def test_a_config_too_short_to_hold_state_and_level(self):
        short = bytes.fromhex("fe dc ba 00 f3 00 06 00 01 03 00 0b 02 ef")
        self.assertIsNone(bridge.noise_of(short))


class FramingTest(unittest.TestCase):
    def test_a_frame_split_across_reads(self):
        buffer = bytearray()
        got = []
        for i in range(0, len(ANSWER), 5):
            buffer += ANSWER[i:i + 5]
            frame, buffer = bridge.split_frame(buffer)
            if frame:
                got.append(frame)
        self.assertEqual(got, [ANSWER])

    def test_three_frames_in_one_read_as_the_earbuds_send_after_a_set(self):
        burst = STATUS_REPORT_ANC + NOTIFY_ANC + SET_ACK
        got = []
        buffer = bytearray(burst)
        while True:
            frame, buffer = bridge.split_frame(buffer)
            if frame is None:
                break
            got.append(frame)
        self.assertEqual(got, [STATUS_REPORT_ANC, NOTIFY_ANC, SET_ACK])

    # Synthetic damage.
    def test_garbage_before_and_two_frames(self):
        frame, rest = bridge.split_frame(bytearray(b"\x00\x01" + ANSWER + ANSWER))
        self.assertEqual(frame, ANSWER)
        self.assertEqual(bytes(rest), ANSWER)

    def test_an_absurd_length_does_not_stall(self):
        frame, rest = bridge.split_frame(bytearray(b"\xfe\xdc\xba\x00\x02\xff\xff" + ANSWER))
        self.assertEqual(frame, ANSWER)

    def test_a_bad_tail_resyncs(self):
        broken = bytearray(ANSWER)
        broken[-1] = 0x00
        frame, rest = bridge.split_frame(bytearray(bytes(broken) + ANSWER))
        self.assertEqual(frame, ANSWER)

    def test_a_header_cut_in_two_is_kept(self):
        frame, rest = bridge.split_frame(bytearray(b"\x00\x00\xfe\xdc"))
        self.assertIsNone(frame)
        self.assertEqual(bytes(rest), b"\xfe\xdc")
        frame, rest = bridge.split_frame(rest + ANSWER[2:])
        self.assertEqual(frame, ANSWER)

    def test_empty_and_header_only_input(self):
        self.assertEqual(bridge.split_frame(bytearray())[0], None)
        self.assertEqual(bridge.split_frame(bytearray(b"\xfe\xdc\xba"))[0], None)


class Modes(unittest.TestCase):
    def ready(self):
        s = Session()
        s.do_open()
        s.device(NOISE_AMBIENT.hex(" "))
        s.device(ANSWER.hex(" "))
        s.frames.clear()
        return s

    def test_a_set_sends_the_config_and_does_not_claim_the_new_mode(self):
        s = self.ready()
        s.command("set anc")
        self.assertEqual(len(s.frames), 1)
        self.assertEqual(s.frames[0][4:5], b"\xf2")
        self.assertEqual(bytes(s.frames[0][-5:-1]), bytes([0x00, 0x0b, 1, 0]))
        self.assertEqual(s.lines[-1]["mode"], "ambient")

    def test_the_announcement_moves_the_mode(self):
        s = self.ready()
        s.device(NOTIFY_ANC.hex(" "))
        self.assertEqual(s.lines[-1]["mode"], "anc")

    def test_a_set_keeps_the_strength_the_state_was_last_seen_at(self):
        # Synthetic: every level in the capture was 0.
        s = self.ready()
        deep = bytearray(NOTIFY_ANC)
        deep[12] = 2
        s.device(bytes(deep).hex(" "))
        s.device(NOISE_AMBIENT.hex(" "))
        s.frames.clear()
        s.command("set anc")
        self.assertEqual(bytes(s.frames[0][-5:-1]), bytes([0x00, 0x0b, 1, 2]))

    def test_nothing_is_sent_before_the_earbuds_have_said_their_mode(self):
        s = Session()
        s.do_open()
        s.frames.clear()
        s.command("set anc")
        self.assertEqual(s.frames, [])

    def test_unknown_commands_are_ignored_without_sending(self):
        s = self.ready()
        for line in ("set talkthru", "set", "level 3", "voice on", "set anc now", ""):
            s.command(line)
        self.assertEqual(s.frames, [])

    def test_the_readback_after_a_set_is_driven_by_the_timer(self):
        s = self.ready()
        s.command("set off")
        self.assertIn(bridge.RECHECK_MS, s.timers)
        s.glib.timers = [t for t in s.glib.timers if t[0] == bridge.RECHECK_MS]
        s.frames.clear()
        s.fire()
        self.assertEqual(s.frames[0][4:5], b"\xf3")

    def test_the_battery_goes_out_alone_when_no_mode_comes(self):
        s = Session()
        s.do_open()
        s.device(ANSWER.hex(" "))
        self.assertEqual(s.lines, [])
        self.assertIn(bridge.MODE_GRACE_MS, s.timers)
        s.fire()
        self.assertEqual(s.lines[-1], {"modes": True, "available": [],
                                       "battery": {"left": 75, "right": 80, "case": 100,
                                                   "charging": []}})

    def test_the_same_state_is_not_printed_twice(self):
        s = self.ready()
        before = len(s.lines)
        s.device(NOISE_AMBIENT.hex(" "))
        s.device(ANSWER.hex(" "))
        self.assertEqual(len(s.lines), before)

    def test_the_poll_asks_for_the_mode_and_the_battery_again(self):
        s = self.ready()
        self.assertTrue(s.bridge.poll())
        self.assertEqual([f[4] for f in s.frames], [0xF3, 0x02])


class RunLoop(unittest.TestCase):
    """The bridge through its timers and its descriptor callbacks."""

    def open(self):
        s = Session()
        s.do_open()
        return s

    def feed(self, s, *chunks):
        reads = list(chunks)

        def read(fd, size):
            item = reads.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with mock.patch.object(bridge.os, "read", side_effect=read):
            result = None
            for _ in chunks:
                result = s.bridge.on_io(-1, bridge.GLib.IO_IN)
            return result

    def test_silence_is_found_by_the_timer_and_is_exit_3(self):
        s = self.open()
        self.assertIn(bridge.FIRST_ANSWER_MS, s.timers)
        s.fire()
        self.assertEqual(s.bridge.exit_code, bridge.EXIT_UNSUPPORTED)
        self.assertEqual(s.lines[-1]["modes"], False)

    def test_an_answer_means_the_timer_finds_nothing_to_report(self):
        s = self.open()
        self.feed(s, NOISE_AMBIENT)
        s.fire()
        self.assertIsNone(s.bridge.exit_code)

    def test_replies_through_the_socket_callback_in_pieces(self):
        s = self.open()
        self.feed(s, ANSWER[:10], ANSWER[10:30], ANSWER[30:] + NOISE_ANC[:6], NOISE_ANC[6:])
        self.assertEqual(s.lines[-1]["mode"], "anc")
        self.assertEqual(s.lines[-1]["battery"]["left"], 75)

    def test_a_burst_of_frames_after_a_set(self):
        s = self.open()
        self.feed(s, NOISE_AMBIENT, ANSWER)
        self.feed(s, STATUS_REPORT_ANC + NOTIFY_ANC + SET_ACK)
        self.assertEqual(s.lines[-1]["mode"], "anc")

    def test_echoes_and_junk_print_nothing(self):
        s = self.open()
        self.feed(s, bridge.encode_get_noise(1) + bridge.encode_get_target_info(2),
                  b"\x00\x01\x02", SET_ACK)
        self.assertEqual(s.lines, [])
        self.assertIsNone(s.bridge.exit_code)

    def test_the_link_closing_is_exit_1(self):
        s = self.open()
        self.assertFalse(self.feed(s, b""))
        self.assertEqual(s.bridge.exit_code, bridge.EXIT_TRANSIENT)

    def test_a_read_error_is_exit_1(self):
        s = self.open()
        self.assertFalse(self.feed(s, OSError(errno.ECONNRESET, "reset")))
        self.assertEqual(s.bridge.exit_code, bridge.EXIT_TRANSIENT)

    def test_a_hangup_condition_is_exit_1(self):
        s = self.open()
        self.assertFalse(s.bridge.on_io(-1, bridge.GLib.IO_HUP))
        self.assertEqual(s.bridge.exit_code, bridge.EXIT_TRANSIENT)

    def test_a_write_error_is_exit_1(self):
        s = self.open()
        s.bridge.write = bridge.Bridge.write.__get__(s.bridge)
        s.bridge.fd = 99
        with mock.patch.object(bridge.os, "write", side_effect=OSError(errno.EPIPE, "pipe")):
            s.bridge.write(b"x")
        self.assertEqual(s.bridge.exit_code, bridge.EXIT_TRANSIENT)

    def test_nothing_is_written_once_the_bridge_has_stopped(self):
        s = self.open()
        self.feed(s, NOISE_AMBIENT)
        s.bridge.finish(0)
        s.frames.clear()
        s.bridge.command("set anc")
        s.bridge.ask()
        self.assertFalse(s.bridge.poll())
        self.assertEqual(s.frames, [])

    def test_a_stop_during_connect_makes_no_later_attempt(self):
        bus = mock.Mock()
        loop = mock.Mock()
        b = bridge.Bridge(bus, ADDRESS, loop)
        b.device = mock.Mock()
        b.finish(0)
        self.assertFalse(b.connect())
        b.device.ConnectProfile.assert_not_called()
        loop.quit.assert_called_once()

    def test_a_connect_that_fails_after_the_stop_changes_nothing(self):
        b = bridge.Bridge(mock.Mock(), ADDRESS, mock.Mock())
        b.device = mock.Mock()
        b.connect()
        failed = b.device.ConnectProfile.call_args.kwargs["error_handler"]
        b.finish(0)
        failed(types.SimpleNamespace(get_dbus_message=lambda: "late"))
        self.assertEqual(b.exit_code, 0)

    def test_a_refused_channel_is_exit_1_with_the_reason(self):
        s = Session()
        b = bridge.Bridge(mock.Mock(), ADDRESS, mock.Mock())
        b.device = mock.Mock()
        b.connect()
        failed = b.device.ConnectProfile.call_args.kwargs["error_handler"]
        failed(types.SimpleNamespace(get_dbus_message=lambda: "Connection refused"))
        self.assertEqual(b.exit_code, bridge.EXIT_TRANSIENT)
        self.assertIn("Connection refused", s.lines[-1]["error"])

    def test_an_unpaired_address_is_exit_1(self):
        s = Session()
        b = bridge.Bridge(mock.Mock(), ADDRESS, mock.Mock())
        with mock.patch.object(bridge, "find_device_path", return_value=None):
            b.register()
        self.assertEqual(b.exit_code, bridge.EXIT_TRANSIENT)
        self.assertIn(ADDRESS, s.lines[-1]["error"])

    def test_cleanup_closes_the_socket_and_the_profile(self):
        b = bridge.Bridge(mock.Mock(), ADDRESS, mock.Mock())
        b.fd = 42
        b.manager = mock.Mock()
        b.registered = True
        with mock.patch.object(bridge.os, "close") as close:
            b.unregister()
        close.assert_called_once_with(42)
        b.manager.UnregisterProfile.assert_called_once()
        self.assertIsNone(b.fd)
        self.assertFalse(b.registered)

    def test_a_second_channel_is_closed_and_ignored(self):
        b = bridge.Bridge(mock.Mock(), ADDRESS, mock.Mock())
        b.fd = 7
        with mock.patch.object(bridge.os, "close") as close:
            b.opened(8)
        close.assert_called_once_with(8)
        self.assertEqual(b.fd, 7)

    def test_a_closed_stdout_is_a_clean_stop(self):
        # A Session replaces emit on the shared module; the real one is what a
        # closed pipe has to survive, so it comes from a fresh load.
        real = harness.load_bridge("redmi-bridge")
        closed = mock.Mock(write=mock.Mock(side_effect=BrokenPipeError))
        with mock.patch.object(real.sys, "stdout", closed), \
                mock.patch.object(real.os, "_exit", side_effect=SystemExit) as leave:
            with self.assertRaises(SystemExit):
                real.emit({"modes": True})
        leave.assert_called_once_with(0)


class Stdin(unittest.TestCase):
    def read(self, s, *chunks):
        reads = list(chunks)
        with mock.patch.object(bridge.os, "read", side_effect=lambda fd, n: reads.pop(0)):
            result = True
            for _ in chunks:
                result = s.bridge.on_stdin(0, bridge.GLib.IO_IN)
            return result

    def ready(self):
        s = Session()
        s.do_open()
        s.device(NOISE_AMBIENT.hex(" "))
        s.frames.clear()
        return s

    def test_a_command_in_two_reads(self):
        s = self.ready()
        self.read(s, b"set a", b"nc\n")
        self.assertEqual(len(s.frames), 1)

    def test_eof_is_a_clean_stop(self):
        s = self.ready()
        self.assertFalse(self.read(s, b""))
        self.assertEqual(s.bridge.exit_code, 0)

    def test_a_hangup_is_a_clean_stop(self):
        s = self.ready()
        self.assertFalse(s.bridge.on_stdin(0, bridge.GLib.IO_HUP))
        self.assertEqual(s.bridge.exit_code, 0)


class Arguments(unittest.TestCase):
    def run_main(self, argv):
        with mock.patch.object(bridge.sys, "argv", ["redmi-bridge"] + argv):
            lines = []
            with mock.patch.object(bridge, "emit", lines.append):
                with self.assertRaises(SystemExit) as raised:
                    bridge.main()
        return raised.exception.code, lines

    def test_no_address_is_exit_4(self):
        code, lines = self.run_main([])
        self.assertEqual(code, bridge.EXIT_SETUP)
        self.assertFalse(lines[0]["modes"])

    def test_a_string_that_is_not_an_address_is_exit_4_and_never_reaches_bluez(self):
        for bad in ("nope", "AA:BB:CC:00:00", "AA:BB:CC:00:00:0G", "; rm -rf /",
                    "AA:BB:CC:00:00:01 --evil"):
            code, lines = self.run_main([bad])
            self.assertEqual(code, bridge.EXIT_SETUP, bad)

    def test_help_prints_usage_and_exits_0(self):
        with mock.patch.object(bridge.sys, "argv", ["redmi-bridge", "--help"]), \
                contextlib.redirect_stdout(io.StringIO()) as printed:
            self.assertEqual(bridge.main(), 0)
        self.assertIn("usage: redmi-bridge", printed.getvalue())


class Silent(unittest.TestCase):
    def test_a_noise_answer_alone_is_an_answer(self):
        s = Session()
        s.do_open()
        s.device(NOISE_AMBIENT.hex(" "))
        s.bridge.first_answer_timeout()
        self.assertIsNone(s.bridge.exit_code)



# ---- Redmi Buds 3 Pro: the same frames behind an authentication. Verbatim
#      from docs/captures/redmi-buds-3-pro.txt, the third run unless marked.

BUDS_3_PRO = "Redmi Buds 3 Pro"
OUR_CHALLENGE = bytes.fromhex("dd3b5c5dfbe669841c2e8184758e6600")
THEIR_ANSWER = bytes.fromhex(
    "fe dc ba 04 50 00 13 00 01 01 bd 04 53 94 ac 59 2f f4 4e be c2 18 fe 55 63 e9 ef")
CONFIRM_ACK = bytes.fromhex("fe dc ba 04 51 00 03 00 02 01 ef")
THEIR_CHALLENGE = bytes.fromhex(
    "fe dc ba c0 50 00 12 00 01 78 5a f7 fb b2 60 9c c7 74 c2 7d 69 d1 36 21 b9 ef")
OUR_ANSWER = bytes.fromhex(
    "fe dc ba 04 50 00 13 00 00 01 ff dc 81 66 35 b6 d1 a4 88 7a e1 42 f6 22 7c cc ef")
THEIR_CONFIRM = bytes.fromhex("fe dc ba c0 51 00 03 01 01 00 ef")
B3P_NOISE_AMBIENT = bytes.fromhex("fe dc ba 00 f3 00 07 00 03 04 00 0b 02 00 ef")
B3P_ANSWER = bytes.fromhex(
    "fe dc ba 00 02 00 38 00 04 11 00 52 65 64 6d 69 20 42 75 64 73 20 33 20 50 72 6f "
    "05 01 11 11 11 11 02 02 5e 05 03 5a 4d ea 0b 02 04 01 02 05 00 03 06 11 11 02 08 "
    "01 04 07 5e 5e 2c 02 0d 02 ef")
CONFIG_12 = bytes.fromhex("fe dc ba c7 f4 00 05 02 03 00 0c 0c ef")
# The fourth run: status reports with the batteries, the left bud going in.
STATUS_BATTERY = bytes.fromhex("fe dc ba c7 0e 00 06 08 04 00 5c 5c 2c ef")
STATUS_NO_READING = bytes.fromhex("fe dc ba c7 0e 00 06 09 04 00 ff ff ff ef")
STATUS_CHARGING = bytes.fromhex("fe dc ba c7 0e 00 06 0a 04 00 dc 5c 2c ef")


def buds_3_pro():
    s = Session(BUDS_3_PRO, OUR_CHALLENGE.hex())
    s.do_open()
    return s


def authenticated():
    s = buds_3_pro()
    for frame in (THEIR_ANSWER, CONFIRM_ACK, THEIR_CHALLENGE, THEIR_CONFIRM):
        s.device(frame.hex(" "))
    return s


class Authentication(unittest.TestCase):
    def test_the_response_to_both_captured_challenges(self):
        # Ours, answered by the earbuds; theirs, whose answer they accepted.
        self.assertEqual(b"\x01" + bridge.auth_response(OUR_CHALLENGE),
                         bridge.parts_of(THEIR_ANSWER)[3])
        self.assertEqual(bridge.auth_response(THEIR_CHALLENGE[9:25]), OUR_ANSWER[10:26])
        # And the session from the capture's first authenticated run.
        self.assertEqual(
            bridge.auth_response(bytes.fromhex("f72c67873c8a3a67a5ffff5c018f4b0a")).hex(),
            "1bf76a9f5b2bce90ba6dc4e311022f16")

    def test_the_challenge_does_not_change_the_caller_s_bytes(self):
        challenge = bytes(OUR_CHALLENGE)
        bridge.auth_response(challenge)
        self.assertEqual(challenge, OUR_CHALLENGE)

    def test_only_the_challenge_goes_out_until_both_sides_confirmed(self):
        s = buds_3_pro()
        self.assertEqual(s.sent, [bridge.encode_auth_challenge(1, OUR_CHALLENGE).hex(" ")])
        s.bridge.ask()
        self.assertTrue(s.bridge.poll())
        s.bridge.recheck()
        s.command("set anc")
        self.assertEqual(len(s.frames), 1)

    def test_after_the_handshake_the_reads_are_the_buds_5_s(self):
        s = authenticated()
        self.assertEqual(s.sent[-2:], ["fe dc ba c0 f3 00 03 03 00 0b ef",
                                       "fe dc ba c0 02 00 05 04 ff ff ff ff ef"])
        self.assertTrue(s.bridge.authenticated)

    def test_a_wrong_answer_to_our_challenge_is_exit_3_and_nothing_more(self):
        # Synthetic damage: one byte of the captured answer changed.
        s = buds_3_pro()
        wrong = bytearray(THEIR_ANSWER)
        wrong[12] ^= 0x01
        s.device(bytes(wrong).hex(" "))
        self.assertEqual(s.bridge.exit_code, bridge.EXIT_UNSUPPORTED)
        self.assertEqual(len(s.frames), 1)
        self.assertFalse(s.lines[-1]["modes"])

    def test_an_error_status_to_our_challenge_is_exit_3(self):
        # Synthetic: status 1 on the captured answer.
        s = buds_3_pro()
        failed = bytearray(THEIR_ANSWER)
        failed[7] = 0x01
        s.device(bytes(failed).hex(" "))
        self.assertEqual(s.bridge.exit_code, bridge.EXIT_UNSUPPORTED)

    def test_their_confirmation_before_ours_was_checked_is_not_taken(self):
        s = buds_3_pro()
        s.device(THEIR_CONFIRM.hex(" "))
        self.assertEqual(len(s.frames), 1)
        self.assertFalse(s.bridge.authenticated)

    def test_a_silent_handshake_is_found_by_the_timer_and_is_exit_3(self):
        s = buds_3_pro()
        self.assertIn(bridge.FIRST_ANSWER_MS, s.timers)
        s.fire()
        self.assertEqual(s.bridge.exit_code, bridge.EXIT_UNSUPPORTED)
        self.assertEqual(len(s.frames), 1)

    def test_a_handshake_that_stalls_halfway_is_exit_3_too(self):
        s = buds_3_pro()
        s.device(THEIR_ANSWER.hex(" "))
        s.fire()
        self.assertEqual(s.bridge.exit_code, bridge.EXIT_UNSUPPORTED)

    def test_the_handshake_split_at_every_byte_boundary(self):
        stream = THEIR_ANSWER + CONFIRM_ACK + THEIR_CHALLENGE + THEIR_CONFIRM \
            + B3P_NOISE_AMBIENT + B3P_ANSWER
        for cut in range(1, len(stream)):
            s = buds_3_pro()
            s.device(stream[:cut].hex(" "))
            s.device(stream[cut:].hex(" "))
            self.assertEqual(s.lines[-1]["mode"], "ambient", cut)
            self.assertEqual(s.lines[-1]["battery"]["left"], 94, cut)
            self.assertEqual(s.sent, authenticated_sent(), cut)

    def test_the_handshake_and_the_answers_in_one_read(self):
        s = buds_3_pro()
        stream = THEIR_ANSWER + CONFIRM_ACK + THEIR_CHALLENGE + THEIR_CONFIRM + CONFIG_12 \
            + B3P_NOISE_AMBIENT + B3P_ANSWER
        RunLoop().feed(s, stream)
        self.assertEqual(s.lines[-1]["battery"], {"left": 94, "right": 94, "case": 44,
                                                  "charging": []})
        self.assertEqual(s.sent[-1], "fe dc ba 04 f4 00 02 00 02 ef")

    def test_a_stop_during_the_handshake_writes_nothing_more(self):
        s = buds_3_pro()
        s.bridge.finish(0)
        s.frames.clear()
        for frame in (THEIR_ANSWER, THEIR_CHALLENGE, THEIR_CONFIRM):
            s.device(frame.hex(" "))
        self.assertFalse(s.bridge.poll())
        self.assertEqual(s.frames, [])

    def test_the_link_closing_during_the_handshake_is_exit_1(self):
        s = buds_3_pro()
        self.assertFalse(RunLoop().feed(s, THEIR_ANSWER[:9], b""))
        self.assertEqual(s.bridge.exit_code, bridge.EXIT_TRANSIENT)

    def test_the_buds_5_are_not_asked_to_authenticate(self):
        s = Session()
        s.do_open()
        self.assertEqual([f[4] for f in s.frames], [bridge.OP_GET_CONFIG, bridge.OP_GET_TARGET_INFO])


def authenticated_sent():
    return [
        bridge.encode_auth_challenge(1, OUR_CHALLENGE).hex(" "),
        "fe dc ba c4 51 00 03 02 01 00 ef",
        OUR_ANSWER.hex(" "),
        "fe dc ba 04 51 00 03 00 01 01 ef",
        "fe dc ba c0 f3 00 03 03 00 0b ef",
        "fe dc ba c0 02 00 05 04 ff ff ff ff ef",
    ]


class Acknowledgement(unittest.TestCase):
    def test_each_announcement_is_answered_with_its_sn(self):
        s = authenticated()
        s.frames.clear()
        s.device(CONFIG_12.hex(" "))
        s.device(STATUS_REPORT_ANC.hex(" "))
        self.assertEqual(s.sent, ["fe dc ba 04 f4 00 02 00 02 ef",
                                  "fe dc ba 04 0e 00 02 00 04 ef"])

    def test_answers_and_set_acks_are_not_answered(self):
        s = authenticated()
        s.frames.clear()
        for frame in (B3P_NOISE_AMBIENT, B3P_ANSWER, SET_ACK):
            s.device(frame.hex(" "))
        self.assertEqual(s.frames, [])

    def test_the_buds_5_are_sent_no_acknowledgement(self):
        s = Modes().ready()
        s.device(NOTIFY_ANC.hex(" "))
        s.device(STATUS_REPORT_ANC.hex(" "))
        self.assertEqual(s.frames, [])


class StatusBattery(unittest.TestCase):
    def ready(self):
        s = authenticated()
        s.device(B3P_NOISE_AMBIENT.hex(" "))
        s.device(B3P_ANSWER.hex(" "))
        return s

    def test_the_status_report_s_battery(self):
        self.assertEqual(bridge.status_battery_of(STATUS_BATTERY),
                         {"left": 92, "right": 92, "case": 44, "charging": []})
        self.assertEqual(bridge.status_battery_of(STATUS_CHARGING),
                         {"left": 92, "right": 92, "case": 44, "charging": ["left"]})
        self.assertIsNone(bridge.status_battery_of(STATUS_NO_READING))
        self.assertIsNone(bridge.status_battery_of(STATUS_REPORT_ANC))

    def test_a_charging_bud_is_printed_and_no_reading_keeps_the_last(self):
        s = self.ready()
        s.device(STATUS_BATTERY.hex(" "))
        count = len(s.lines)
        s.device(STATUS_NO_READING.hex(" "))
        self.assertEqual(len(s.lines), count)
        s.device(STATUS_CHARGING.hex(" "))
        self.assertEqual(s.lines[-1]["battery"]["charging"], ["left"])
        self.assertEqual(s.lines[-1]["mode"], "ambient")

    def test_our_own_answer_echoed_back_is_not_a_report(self):
        self.assertIsNone(bridge.status_battery_of(bridge.encode_response(0x0E, 8, b"\x04\x00\x5c\x5c\x2c")))

    def test_the_buds_5_do_not_read_a_battery_from_a_status_report(self):
        # Synthetic for them: their reports carried none.
        s = Modes().ready()
        before = list(s.lines)
        s.device(STATUS_CHARGING.hex(" "))
        self.assertEqual(s.lines, before)


class ModelArguments(unittest.TestCase):
    def run_main(self, argv):
        return Arguments().run_main(argv)

    def test_an_unknown_name_is_exit_4(self):
        code, lines = self.run_main([ADDRESS, "Redmi Buds 5"])
        self.assertEqual(code, bridge.EXIT_SETUP)
        self.assertIn("no Redmi model row", lines[0]["error"])

    def test_too_many_arguments_is_exit_4(self):
        code, lines = self.run_main([ADDRESS, BUDS_3_PRO, "extra"])
        self.assertEqual(code, bridge.EXIT_SETUP)

    def test_the_name_picks_the_row_and_no_name_the_buds_5(self):
        seen = []

        class Stop(Exception):
            pass

        def capture(bus, address, loop, model):
            seen.append(model)
            raise Stop

        for argv in ([ADDRESS, BUDS_3_PRO], [ADDRESS]):
            with mock.patch.object(bridge.sys, "argv", ["redmi-bridge"] + argv), \
                    mock.patch.object(bridge, "Bridge", side_effect=capture), \
                    mock.patch.object(bridge.dbus, "SystemBus", create=True), \
                    mock.patch.object(bridge.dbus.mainloop.glib, "DBusGMainLoop", create=True), \
                    mock.patch.object(bridge.GLib, "MainLoop", create=True):
                with self.assertRaises(Stop):
                    bridge.main()
        self.assertEqual(seen, [bridge.MODELS[BUDS_3_PRO], bridge.NAMELESS])
        self.assertEqual(bridge.NAMELESS, {"authenticate": False, "acknowledge": False,
                                           "status_battery": False})


if __name__ == "__main__":
    unittest.main()
