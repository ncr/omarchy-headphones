"""What earfun-bridge sends EarFun Air Pro 4, and what it prints.

    python -m unittest tests.earfun_bridge_test

The frozen session is tests/pins/earfun/air-pro-4.json. The frames here are
verbatim what an EarFun Air Pro 4 sent (docs/captures/earfun-air-pro-4.txt),
and the first test checks that each of them is in that capture: the three
answers to the mode get, the answer to the ANC-style get, and the frames the
earbuds send on their own, alone and glued as they came. Beyond the pin: the
framing against those frames, damage the parser must survive (synthetic, and
marked as such), the run loop through the scheduled timers, the socket
callbacks and a fake BlueZ, and the battery, which is the Fast Pair stream's,
through gfps-reader with the frames the same earbuds sent there.

No hardware and no socket: the bridge's effects on the world are write(),
emit() and the file descriptor callbacks, and all of them are captured.
"""
import contextlib
import errno
import io
import os
import types
import unittest
from unittest import mock

from tests import canonical, harness

bridge = harness.load_bridge("earfun-bridge")
reader = harness.load_bridge("gfps-reader")

ADDRESS = "AA:BB:CC:00:00:02"
NAME = "EarFun Air Pro 4"
CAPTURE = os.path.join(harness.ROOT, "docs", "captures", "earfun-air-pro-4.txt")

# Answers to the mode get (0315): off, noise cancelling, transparency.
OFF = bytes.fromhex("ff 03 00 02 00 0a 83 15 00 00")
ANC = bytes.fromhex("ff 03 00 02 00 0a 83 15 00 01")
AMBIENT = bytes.fromhex("ff 03 00 02 00 0a 83 15 00 02")
# The answer to the ANC-style get (033B): same shape, another command.
ANC_STYLE = bytes.fromhex("ff 03 00 02 00 0a 83 3b 00 02")
FIRMWARE = bytes.fromhex(
    "ff 03 00 1b 00 0a 83 09 00 54 57 36 30 30 2d 33 30 39 31 5f 32 30 32 35 30 39 31 39"
    " 5f 76 30 2e 34 2e 31")
# What the earbuds send unasked, glued in one read as they came.
OWN_0358_A = bytes.fromhex("ff 03 00 05 00 0a 03 58 00 5c 3b 4d 01")
OWN_0358_B = bytes.fromhex("ff 03 00 05 00 0a 03 58 00 33 4e e5 00")
OWN_034D = bytes.fromhex("ff 03 00 02 00 0a 03 4d 00 03")
OWN_0350 = bytes.fromhex("ff 03 00 02 00 0a 03 50 00 01")
OWN_BURST = OWN_0358_A + OWN_0358_B + OWN_034D
# What the bridge sends.
GET = bytes.fromhex("ff 04 00 00 00 0a 03 15")
SET = {"off": bytes.fromhex("ff 04 00 01 00 0a 03 14 00"),
       "anc": bytes.fromhex("ff 04 00 01 00 0a 03 14 01"),
       "ambient": bytes.fromhex("ff 04 00 01 00 0a 03 14 02")}

# The same earbuds on the Fast Pair Message Stream.
GFPS_MODEL = bytes.fromhex("03 01 00 03 f3 d9 b4")
GFPS_BATTERY = bytes.fromhex("03 03 00 03 64 64 5a")
GFPS_GLUED = bytes.fromhex(
    "03 01 00 03 f3 d9 b4 03 02 00 06 50 07 3d 6e 6e 42 03 03 00 03 64 64 5a"
    " 03 0a 00 08 ae e5 46 c9 b8 8c 97 8f")


class Session(harness.Session):
    """An EarFun session. "device" in a pin is bytes as hex, fed through the
    bridge's framer. "sent" is every whole frame the bridge wrote, as hex.
    "open" is the channel coming up, which asks for the mode and schedules the
    second ask, the first-answer check and the poll."""

    def __init__(self, name=NAME):
        super().__init__(bridge)
        self.bridge = bridge.Bridge(None, ADDRESS, name, harness.FakeLoop())
        self.bridge.write = self.frames.append

    def device(self, spec):
        self.bridge.buffer += harness.hexbytes(spec)
        self.bridge.parse_buffer()

    def do_open(self):
        self.bridge.opened(-1)


harness.pin_tests(globals(), "earfun-bridge", Session)


def only(s, ms):
    """Keep only the timers scheduled for this interval."""
    s.glib.timers = [t for t in s.glib.timers if t[0] == ms]


class Evidence(unittest.TestCase):
    def test_every_frame_here_is_in_the_capture(self):
        with open(CAPTURE) as handle:
            text = handle.read()
        flat = " ".join(text.split())
        for frame in (OFF, ANC, AMBIENT, ANC_STYLE, FIRMWARE, OWN_0358_A, OWN_0358_B,
                      OWN_034D, OWN_0350, OWN_BURST, GET, *SET.values()):
            with self.subTest(frame=frame.hex(" ")):
                self.assertIn(frame.hex(" "), flat)
        for frame in (GFPS_MODEL, GFPS_BATTERY, GFPS_GLUED):
            with self.subTest(frame=frame.hex()):
                self.assertIn(frame.hex(), text)

    def test_the_pin_feeds_only_captured_frames(self):
        with open(CAPTURE) as handle:
            flat = " ".join(handle.read().split())
        for _path, pin in harness.pins_for("earfun-bridge"):
            self.assertEqual(pin["capture"], "docs/captures/earfun-air-pro-4.txt")
            for step in pin["steps"]:
                for key in ("device", "sent_last"):
                    if key in step:
                        self.assertIn(step[key], flat)
                for frame in step.get("sent", []):
                    self.assertIn(frame, flat)


class Encode(unittest.TestCase):
    def test_the_get_is_the_one_the_earbuds_answered(self):
        self.assertEqual(bridge.encode_get_mode(), GET)

    def test_the_three_sets(self):
        for mode, frame in SET.items():
            self.assertEqual(bridge.encode_set_mode(mode), frame, mode)


class ModeOf(unittest.TestCase):
    def test_the_three_answers(self):
        self.assertEqual(bridge.mode_of(OFF), "off")
        self.assertEqual(bridge.mode_of(ANC), "anc")
        self.assertEqual(bridge.mode_of(AMBIENT), "ambient")

    def test_another_answer_of_the_same_shape_is_not_the_mode(self):
        self.assertIsNone(bridge.mode_of(ANC_STYLE))
        self.assertIsNone(bridge.mode_of(FIRMWARE))

    def test_the_earbuds_own_frames_are_not_the_mode(self):
        for frame in (OWN_0358_A, OWN_0358_B, OWN_034D, OWN_0350):
            self.assertIsNone(bridge.mode_of(frame))

    def test_our_own_frames_echoed_back_are_not_answers(self):
        self.assertIsNone(bridge.mode_of(GET))
        for frame in SET.values():
            self.assertIsNone(bridge.mode_of(frame))

    # Synthetic below: nothing but status 00 and values 00-02 was seen.
    def test_an_error_status_is_not_a_mode(self):
        failed = bytearray(ANC)
        failed[8] = 0x01
        self.assertIsNone(bridge.mode_of(bytes(failed)))

    def test_an_unknown_value_is_not_a_mode(self):
        odd = bytearray(ANC)
        odd[9] = 0x03
        self.assertIsNone(bridge.mode_of(bytes(odd)))

    def test_another_vendor_is_not_a_mode(self):
        other = bytearray(ANC)
        other[5] = 0x1D
        self.assertIsNone(bridge.mode_of(bytes(other)))

    def test_a_payload_of_another_length_is_not_a_mode(self):
        self.assertIsNone(bridge.mode_of(bytes.fromhex("ff 03 00 01 00 0a 83 15 01")))
        self.assertIsNone(bridge.mode_of(bytes.fromhex("ff 03 00 03 00 0a 83 15 00 01 00")))


def split_all(data):
    frames = []
    buffer = bytearray(data)
    while True:
        frame, buffer = bridge.split_frame(buffer)
        if frame is None:
            return frames, bytes(buffer)
        frames.append(frame)


class Framing(unittest.TestCase):
    def test_every_split_point_of_a_recorded_answer(self):
        for frame in (ANC, FIRMWARE):
            for cut in range(1, len(frame)):
                with self.subTest(frame=frame[:8].hex(), cut=cut):
                    got, rest = split_all(frame[:cut])
                    self.assertEqual(got, [])
                    got, rest = split_all(rest + frame[cut:])
                    self.assertEqual(got, [frame])
                    self.assertEqual(rest, b"")

    def test_the_glued_read_the_earbuds_sent(self):
        self.assertEqual(split_all(OWN_BURST), ([OWN_0358_A, OWN_0358_B, OWN_034D], b""))

    def test_an_answer_glued_after_the_earbuds_own_frames(self):
        self.assertEqual(split_all(OWN_034D + AMBIENT)[0], [OWN_034D, AMBIENT])

    # Synthetic damage.
    def test_garbage_before_a_frame(self):
        self.assertEqual(split_all(b"\x00\x13\x37" + ANC), ([ANC], b""))

    def test_a_start_byte_without_the_seen_version_resyncs(self):
        self.assertEqual(split_all(b"\xff\x04\x00" + ANC)[0], [ANC])
        self.assertEqual(split_all(b"\xff\x03\x01" + ANC)[0], [ANC])
        self.assertEqual(split_all(b"\xff\xff" + ANC)[0], [ANC])

    def test_a_truncated_frame_waits_and_nothing_is_read_from_it(self):
        s = Session()
        s.do_open()
        s.device(ANC[:-1].hex(" "))
        self.assertEqual(s.lines, [])
        self.assertEqual(bytes(s.bridge.buffer), ANC[:-1])

    def test_a_lone_start_byte_is_kept(self):
        got, rest = split_all(b"\x00\xff")
        self.assertEqual((got, rest), ([], b"\xff"))

    def test_nothing_and_no_start_byte(self):
        self.assertEqual(split_all(b""), ([], b""))
        self.assertEqual(split_all(b"\x01\x02\x03"), ([], b""))


class Modes(unittest.TestCase):
    def ready(self, answer=OFF):
        s = Session()
        s.do_open()
        s.device(answer.hex(" "))
        s.frames.clear()
        s.glib.timers.clear()
        return s

    def test_the_first_answer_is_printed(self):
        s = self.ready()
        self.assertEqual(s.lines, [{"modes": True, "mode": "off",
                                    "available": ["off", "anc", "ambient"]}])

    def test_a_set_sends_one_frame_and_does_not_claim_the_mode(self):
        s = self.ready()
        s.command("set anc")
        self.assertEqual(s.frames, [SET["anc"]])
        self.assertEqual(s.lines[-1]["mode"], "off")
        self.assertEqual(len(s.lines), 1)

    def test_the_readback_is_driven_by_the_timer_until_the_earbuds_agree(self):
        s = self.ready()
        s.command("set anc")
        self.assertEqual(s.timers, [bridge.RECHECK_MS])
        s.frames.clear()
        # The change takes a while: the first readback still says off.
        s.fire()
        self.assertEqual(s.frames, [GET])
        s.device(OFF.hex(" "))
        self.assertEqual(len(s.lines), 1)
        # The fake loop does not re-arm a repeating timer; the bridge said True.
        self.assertTrue(s.bridge.recheck())
        s.device(ANC.hex(" "))
        self.assertEqual(s.lines[-1]["mode"], "anc")
        s.frames.clear()
        self.assertFalse(s.bridge.recheck())
        self.assertEqual(s.frames, [])

    def test_the_readback_gives_up_after_its_count(self):
        s = self.ready()
        s.command("set ambient")
        s.frames.clear()
        results = [s.bridge.recheck() for _ in range(bridge.RECHECKS + 2)]
        self.assertEqual(results, [True] * bridge.RECHECKS + [False, False])
        self.assertEqual(s.frames, [GET] * bridge.RECHECKS)
        self.assertEqual(s.lines[-1]["mode"], "off")

    def test_a_second_set_during_the_readback_starts_no_second_timer(self):
        s = self.ready()
        s.command("set anc")
        s.bridge.recheck()
        s.command("set ambient")
        self.assertEqual(s.timers, [bridge.RECHECK_MS])
        self.assertEqual(s.bridge.rechecks, bridge.RECHECKS)
        self.assertEqual(s.bridge.wanted, "ambient")

    def test_nothing_is_sent_before_the_earbuds_have_said_their_mode(self):
        s = Session()
        s.do_open()
        s.frames.clear()
        s.command("set anc")
        self.assertEqual(s.frames, [])

    def test_unknown_commands_are_ignored_without_sending(self):
        s = self.ready()
        for line in ("set talkthru", "set wind", "set", "level 3", "voice on",
                     "set anc now", "SET ANC", ""):
            s.command(line)
        self.assertEqual(s.frames, [])

    def test_the_same_state_is_not_printed_twice(self):
        s = self.ready()
        s.device(OFF.hex(" "))
        s.device((OWN_BURST + OFF).hex(" "))
        self.assertEqual(len(s.lines), 1)

    def test_the_poll_asks_again(self):
        s = self.ready()
        self.assertTrue(s.bridge.poll())
        self.assertEqual(s.frames, [GET])

    def test_a_change_the_bridge_did_not_ask_for_is_printed_when_the_poll_reads_it(self):
        # The frames are recorded; that the change came from elsewhere is the
        # synthetic part: the earbuds were never seen to change on their own.
        s = self.ready(AMBIENT)
        only(s, bridge.POLL_MS)
        s.bridge.poll()
        s.device(ANC.hex(" "))
        self.assertEqual(s.lines[-1]["mode"], "anc")
        self.assertEqual(len(s.lines), 2)


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

    def test_open_asks_and_schedules_the_second_ask_the_check_and_the_poll(self):
        s = self.open()
        self.assertEqual(s.frames, [GET])
        self.assertEqual(sorted(s.timers),
                         sorted([bridge.ASK_AGAIN_MS, bridge.FIRST_ANSWER_MS, bridge.POLL_MS]))

    def test_silence_asks_once_more_then_is_exit_3(self):
        s = self.open()
        only(s, bridge.ASK_AGAIN_MS)
        s.fire()
        self.assertEqual(s.frames, [GET, GET])
        self.assertIsNone(s.bridge.exit_code)
        s = self.open()
        only(s, bridge.FIRST_ANSWER_MS)
        s.fire()
        self.assertEqual(s.bridge.exit_code, bridge.EXIT_UNSUPPORTED)
        self.assertEqual(s.lines[-1]["modes"], False)

    def test_the_earbuds_own_frames_alone_are_not_an_answer(self):
        s = self.open()
        self.feed(s, OWN_BURST, OWN_0350)
        only(s, bridge.FIRST_ANSWER_MS)
        s.fire()
        self.assertEqual(s.bridge.exit_code, bridge.EXIT_UNSUPPORTED)

    def test_an_answer_means_the_timers_find_nothing_to_do(self):
        s = self.open()
        self.feed(s, OFF)
        s.glib.timers = [t for t in s.glib.timers if t[0] != bridge.POLL_MS]
        s.frames.clear()
        s.fire()
        self.assertIsNone(s.bridge.exit_code)
        self.assertEqual(s.frames, [])

    def test_replies_through_the_socket_callback_in_pieces(self):
        s = self.open()
        self.assertTrue(self.feed(s, OWN_BURST[:7], OWN_BURST[7:20], OWN_BURST[20:] + AMBIENT[:4],
                                  AMBIENT[4:]))
        self.assertEqual(s.lines, [{"modes": True, "mode": "ambient",
                                    "available": ["off", "anc", "ambient"]}])

    def test_echoes_and_junk_print_nothing(self):
        s = self.open()
        self.feed(s, GET + SET["anc"], b"\x00\x01\x02", ANC_STYLE, FIRMWARE)
        self.assertEqual(s.lines, [])
        self.assertIsNone(s.bridge.exit_code)

    def test_the_link_closing_is_exit_1(self):
        s = self.open()
        self.assertFalse(self.feed(s, b""))
        self.assertEqual(s.bridge.exit_code, bridge.EXIT_TRANSIENT)
        self.assertIn("closed", s.lines[-1]["error"])

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
            s.bridge.write(GET)
        self.assertEqual(s.bridge.exit_code, bridge.EXIT_TRANSIENT)

    def test_a_short_write_is_finished(self):
        s = self.open()
        s.bridge.write = bridge.Bridge.write.__get__(s.bridge)
        s.bridge.fd = 99
        written = []

        def write(fd, data):
            written.append(bytes(data[:3]))
            return min(3, len(data))

        with mock.patch.object(bridge.os, "write", side_effect=write):
            s.bridge.write(SET["anc"])
        self.assertEqual(b"".join(written), SET["anc"])

    def test_nothing_is_written_once_the_bridge_has_stopped(self):
        s = self.open()
        self.feed(s, OFF)
        s.command("set anc")
        s.bridge.finish(0)
        s.bridge.write = bridge.Bridge.write.__get__(s.bridge)
        s.bridge.fd = 99
        with mock.patch.object(bridge.os, "write") as write:
            s.bridge.command("set ambient")
            s.bridge.ask()
            self.assertFalse(s.bridge.poll())
            self.assertFalse(s.bridge.recheck())
        write.assert_not_called()

    def test_a_late_link_after_the_stop_is_closed_and_asks_nothing(self):
        b = bridge.Bridge(mock.Mock(), ADDRESS, NAME, mock.Mock())
        b.finish(0)
        b.write = mock.Mock()
        with mock.patch.object(bridge.os, "close") as close:
            b.opened(8)
        close.assert_called_once_with(8)
        self.assertIsNone(b.fd)
        b.write.assert_not_called()

    def test_a_stop_during_connect_makes_no_later_attempt(self):
        loop = mock.Mock()
        b = bridge.Bridge(mock.Mock(), ADDRESS, NAME, loop)
        b.device = mock.Mock()
        b.finish(0)
        self.assertFalse(b.connect(0))
        b.device.ConnectProfile.assert_not_called()
        loop.quit.assert_called_once()

    def busy(self):
        return types.SimpleNamespace(get_dbus_message=lambda: "br-connection-busy")

    def test_a_busy_connect_is_retried_on_the_timer_with_the_same_uuid(self):
        s = Session()
        b = bridge.Bridge(mock.Mock(), ADDRESS, NAME, harness.FakeLoop())
        b.device = mock.Mock()
        b.connect(0)
        b.device.ConnectProfile.call_args.kwargs["error_handler"](self.busy())
        self.assertIsNone(b.exit_code)
        self.assertEqual(s.timers, [bridge.CONNECT_RETRY])
        s.fire()
        self.assertEqual(b.device.ConnectProfile.call_count, 2)
        self.assertEqual(b.device.ConnectProfile.call_args.args, (bridge.UUID,))

    def test_retries_stop_at_the_count_and_say_why(self):
        s = Session()
        b = bridge.Bridge(mock.Mock(), ADDRESS, NAME, harness.FakeLoop())
        b.device = mock.Mock()
        b.connect(0)
        for _ in range(bridge.CONNECT_ATTEMPTS):
            b.device.ConnectProfile.call_args.kwargs["error_handler"](self.busy())
            s.fire()
        self.assertEqual(b.device.ConnectProfile.call_count, bridge.CONNECT_ATTEMPTS)
        self.assertEqual(b.exit_code, bridge.EXIT_TRANSIENT)
        self.assertIn("br-connection-busy", s.lines[-1]["error"])

    def test_a_retry_due_after_the_stop_does_not_dial(self):
        s = Session()
        b = bridge.Bridge(mock.Mock(), ADDRESS, NAME, harness.FakeLoop())
        b.device = mock.Mock()
        b.connect(0)
        b.device.ConnectProfile.call_args.kwargs["error_handler"](self.busy())
        b.finish(0)
        s.fire()
        self.assertEqual(b.device.ConnectProfile.call_count, 1)

    def test_a_connect_that_fails_after_the_stop_changes_nothing(self):
        Session()
        b = bridge.Bridge(mock.Mock(), ADDRESS, NAME, mock.Mock())
        b.device = mock.Mock()
        b.connect(0)
        failed = b.device.ConnectProfile.call_args.kwargs["error_handler"]
        b.finish(0)
        failed(types.SimpleNamespace(get_dbus_message=lambda: "late"))
        self.assertEqual(b.exit_code, 0)

    def test_an_unpaired_address_is_exit_1(self):
        s = Session()
        b = bridge.Bridge(mock.Mock(), ADDRESS, NAME, mock.Mock())
        with mock.patch.object(bridge, "find_device_path", return_value=None):
            b.register()
        self.assertEqual(b.exit_code, bridge.EXIT_TRANSIENT)
        self.assertIn(ADDRESS, s.lines[-1]["error"])

    def test_cleanup_closes_the_socket_and_the_profile(self):
        b = bridge.Bridge(mock.Mock(), ADDRESS, NAME, mock.Mock())
        b.fd = 42
        b.manager = mock.Mock()
        b.registered = True
        with mock.patch.object(bridge.os, "close") as close:
            b.unregister()
            b.unregister()
        close.assert_called_once_with(42)
        b.manager.UnregisterProfile.assert_called_once()
        self.assertIsNone(b.fd)
        self.assertFalse(b.registered)

    def test_a_second_channel_is_closed_and_ignored(self):
        b = bridge.Bridge(mock.Mock(), ADDRESS, NAME, mock.Mock())
        b.fd = 7
        with mock.patch.object(bridge.os, "close") as close:
            b.opened(8)
        close.assert_called_once_with(8)
        self.assertEqual(b.fd, 7)

    def test_a_closed_stdout_is_a_clean_stop(self):
        real = harness.load_bridge("earfun-bridge")
        closed = mock.Mock(write=mock.Mock(side_effect=BrokenPipeError))
        with mock.patch.object(real.sys, "stdout", closed), \
                mock.patch.object(real.os, "_exit", side_effect=SystemExit) as leave:
            with self.assertRaises(SystemExit):
                real.emit({"modes": True})
        leave.assert_called_once_with(0)


class DevicePath(unittest.TestCase):
    """Two adapters can each hold the same address; the owner's laptop has two."""

    def objects(self, *devices):
        managed = {path: {"org.bluez.Device1": {"Address": address, "Connected": connected}}
                   for path, address, connected in devices}
        manager = mock.Mock(GetManagedObjects=mock.Mock(return_value=managed))
        return mock.patch.object(bridge.dbus, "Interface", return_value=manager)

    def test_the_adapter_it_is_connected_through_wins(self):
        with self.objects(("/org/bluez/hci0/dev_AA_BB_CC_00_00_02", ADDRESS, False),
                          ("/org/bluez/hci1/dev_AA_BB_CC_00_00_02", ADDRESS, True)):
            self.assertEqual(bridge.find_device_path(mock.Mock(), ADDRESS.lower()),
                             "/org/bluez/hci1/dev_AA_BB_CC_00_00_02")

    def test_both_connected_or_neither_is_the_first_adapter(self):
        for connected in (True, False):
            with self.objects(("/org/bluez/hci1/dev_AA_BB_CC_00_00_02", ADDRESS, connected),
                              ("/org/bluez/hci0/dev_AA_BB_CC_00_00_02", ADDRESS, connected)):
                self.assertEqual(bridge.find_device_path(mock.Mock(), ADDRESS),
                                 "/org/bluez/hci0/dev_AA_BB_CC_00_00_02")

    def test_another_device_is_not_it(self):
        with self.objects(("/org/bluez/hci0/dev_AA_BB_CC_00_00_03", "AA:BB:CC:00:00:03", True)):
            self.assertIsNone(bridge.find_device_path(mock.Mock(), ADDRESS))


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
        s.device(OFF.hex(" "))
        s.frames.clear()
        return s

    def test_a_command_in_two_reads(self):
        s = self.ready()
        self.read(s, b"set a", b"nc\n")
        self.assertEqual(s.frames, [SET["anc"]])

    def test_two_commands_in_one_read(self):
        s = self.ready()
        self.read(s, b"set anc\nset off\n")
        self.assertEqual(s.frames, [SET["anc"], SET["off"]])

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
        with mock.patch.object(bridge.sys, "argv", ["earfun-bridge"] + argv):
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
                    "AA:BB:CC:00:00:02 --evil"):
            with mock.patch.object(bridge.dbus, "SystemBus") as bus:
                code, _lines = self.run_main([bad, NAME])
            self.assertEqual(code, bridge.EXIT_SETUP, bad)
            bus.assert_not_called()

    def test_a_model_without_a_row_is_exit_4(self):
        for name in ("", "EarFun Air Pro 3", "EarFun Air Pro 4 ", "earfun air pro 4"):
            with mock.patch.object(bridge.dbus, "SystemBus") as bus:
                code, lines = self.run_main([ADDRESS, name] if name else [ADDRESS])
            self.assertEqual(code, bridge.EXIT_SETUP, repr(name))
            self.assertIn("no row for the model", lines[0]["error"])
            bus.assert_not_called()

    def test_help_prints_usage_and_exits_0(self):
        with mock.patch.object(bridge.sys, "argv", ["earfun-bridge", "--help"]), \
                contextlib.redirect_stdout(io.StringIO()) as printed:
            self.assertEqual(bridge.main(), 0)
        self.assertIn("usage: earfun-bridge", printed.getvalue())


class FastPairBattery(unittest.TestCase):
    """The battery is gfps-reader's: the frames the same earbuds sent there."""

    def setUp(self):
        self.lines = []
        self.glib = harness.FakeGLib()
        for name, value in [("emit", self.lines.append), ("GLib", self.glib)]:
            p = mock.patch.object(reader, name, value)
            p.start()
            self.addCleanup(p.stop)

    def stream(self, address=ADDRESS):
        incoming, outgoing = os.pipe()
        r = reader.Reader(incoming, reader.State(address))
        self.addCleanup(r.close, "test complete")
        self.addCleanup(os.close, outgoing)
        return r, outgoing

    def send(self, r, fd, data):
        os.write(fd, data)
        self.assertTrue(r.on_io(r.fd, self.glib.IO_IN))

    def test_left_right_and_case(self):
        r, fd = self.stream()
        self.send(r, fd, GFPS_BATTERY)
        line = self.lines[-1]
        self.assertEqual((line["single"], line["left"], line["right"], line["case"]),
                         (False, 100, 100, 90))
        self.assertFalse(any(line[k] for k in ("leftCharging", "rightCharging", "caseCharging")))

    def test_every_split_point_of_the_battery_frame(self):
        for cut in range(1, len(GFPS_BATTERY)):
            with self.subTest(cut=cut):
                r, fd = self.stream()
                before = len(self.lines)
                self.send(r, fd, GFPS_BATTERY[:cut])
                self.assertEqual(len(self.lines), before)
                self.send(r, fd, GFPS_BATTERY[cut:])
                self.assertEqual(len(self.lines), before + 1)
                self.assertEqual(r.buffer, b"")

    def test_the_glued_read_keeps_model_address_and_battery(self):
        r, fd = self.stream()
        self.send(r, fd, GFPS_GLUED)
        line = self.lines[-1]
        self.assertEqual(line["modelId"], "f3d9b4")
        self.assertEqual(line["bleAddress"], "50:07:3D:6E:6E:42")
        self.assertEqual((line["left"], line["right"], line["case"]), (100, 100, 90))
        self.assertEqual(r.buffer, b"")

    def test_another_pair_losing_its_stream_leaves_these_alone(self):
        earfun, ef = self.stream()
        jbl, jf = self.stream(canonical.MODELS["jbl"]["address"])
        self.send(earfun, ef, GFPS_BATTERY)
        self.send(jbl, jf, canonical.frame("jbl", "gfps", "battery"))
        before = dict(earfun.state.values)
        jbl.close("link lost")
        self.assertEqual(earfun.state.values, before)
        self.assertTrue(earfun.alive)
        self.assertEqual(self.lines[-1]["address"], canonical.MODELS["jbl"]["address"])

    def test_the_stream_closing_keeps_the_last_reading_and_says_so(self):
        r, fd = self.stream()
        os.write(fd, GFPS_BATTERY)
        self.assertFalse(r.on_io(r.fd, self.glib.IO_IN | self.glib.IO_HUP))
        self.assertEqual(self.lines[0]["case"], 90)
        self.assertFalse(self.lines[-1]["stream"])


if __name__ == "__main__":
    unittest.main()
