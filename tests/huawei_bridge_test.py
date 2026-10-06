"""What huawei-bridge sends Huawei FreeBuds, and what it prints.

    python -m unittest tests.huawei_bridge_test

The frozen session is tests/pins/huawei/freebuds-se-2.json. What is here is
the framing against frames the FreeBuds SE 2 sent
(docs/captures/huawei-freebuds-se-2.txt), damage the parsers must survive,
and the run loop driven through a fake clock, socket and wait: silence,
a dropped link, a closed pipe, the poll, and a stop during connect.

No hardware and no socket: the bridge's only effects on the world are the
socket's sendall() and emit(), and both are captured.
"""
import types
import unittest

from tests import harness

bridge_module = harness.load_bridge("huawei-bridge")

NAME = "HUAWEI FreeBuds SE 2"
ADDRESS = "AC:33:28:8C:A2:CD"

# Frames the FreeBuds SE 2 sent, verbatim from the capture.
HELLO = "5a 00 03 00 01 06 3e bd"
EVENT_98_98_23 = "5a 00 14 00 01 27 01 01 62 02 03 62 62 17 03 03 00 00 00 04 02 14 0a 36 a2"
ANSWER_98_98_23 = "5a 00 14 00 01 08 01 01 62 02 03 62 62 17 03 03 00 00 00 04 02 14 0a c2 c7"
# The left bud going into the case, and coming out.
CASE_IN = "5a 00 06 00 2b 5f 01 01 01 13 24"
LEFT_IN_CASE = "5a 00 14 00 01 27 01 01 61 02 03 00 61 17 03 03 00 00 00 04 02 14 0a 18 77"
CASE_OUT = "5a 00 06 00 2b 5f 01 01 00 03 05"
# Session 3: the case byte 01, then 00, with the left bud docked throughout.
CASE_CHARGING = "5a 00 14 00 01 27 01 01 5f 02 03 5f 60 3f 03 03 00 00 01 04 02 14 0a c2 6a"
CASE_OFF_CABLE = "5a 00 14 00 01 27 01 01 5f 02 03 5f 60 40 03 03 00 00 00 04 02 14 0a e1 0b"


class FakeSocket:
    def __init__(self, frames):
        self.frames = frames
        self.incoming = []
        self.closed = False

    def sendall(self, data):
        self.frames.append(bytes(data))

    def recv(self, _size):
        if not self.incoming:
            raise BlockingIOError()
        item = self.incoming.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True


class Session(harness.Session):
    """A FreeBuds session. "device" in a pin is a whole frame as hex, exactly
    as the earbuds sent it, fed through the bridge's own reader in one read.
    "sent" is every whole frame the bridge wrote, as hex. "open" is the
    socket coming up: the bridge asks for the battery."""

    def __init__(self, name=NAME):
        super().__init__(bridge_module)
        self.bridge = bridge_module.Bridge(ADDRESS, name)
        self.sock = FakeSocket(self.frames)
        self.bridge.sock = self.sock

    def do_open(self):
        self.bridge.ask_battery()

    def device(self, spec):
        self.sock.incoming.append(harness.hexbytes(spec))
        self.bridge.on_socket()


harness.pin_tests(globals(), "huawei-bridge", Session)


class Framing(unittest.TestCase):
    def test_the_query_is_the_one_the_earbuds_answered(self):
        self.assertEqual(harness.hexstr(bridge_module.BATTERY_QUERY),
                         "5a 00 09 00 01 08 01 00 02 00 03 00 fb b9")

    def test_the_crc_reproduces_every_captured_frame(self):
        for text in (HELLO, EVENT_98_98_23, ANSWER_98_98_23, CASE_IN, LEFT_IN_CASE, CASE_OUT,
                     CASE_CHARGING, CASE_OFF_CABLE):
            raw = harness.hexbytes(text)
            self.assertEqual(bridge_module.crc16(raw[:-2]), int.from_bytes(raw[-2:], "big"), text)

    def test_the_hello_and_two_battery_frames_in_one_read(self):
        buffer = bytearray(harness.hexbytes(HELLO + " " + EVENT_98_98_23 + " " + ANSWER_98_98_23))
        frames = bridge_module.take_frames(buffer)
        self.assertEqual([(s, c) for s, c, _ in frames], [(1, 0x06), (1, 0x27), (1, 0x08)])
        self.assertEqual(buffer, bytearray())
        self.assertEqual(bridge_module.parse_battery(frames[2][2]),
                         {"left": 98, "right": 98, "case": 23})

    def test_a_real_answer_survives_being_split_at_every_byte_boundary(self):
        raw = harness.hexbytes(ANSWER_98_98_23)
        for cut in range(1, len(raw)):
            buffer = bytearray()
            frames = []
            for chunk in (raw[:cut], raw[cut:]):
                buffer += chunk
                frames += bridge_module.take_frames(buffer)
            self.assertEqual(len(frames), 1, "split at %d" % cut)

    def test_a_bud_in_a_closed_case_reads_0_and_is_left_out(self):
        frames = bridge_module.take_frames(bytearray(harness.hexbytes(CASE_IN + " " + LEFT_IN_CASE)))
        self.assertEqual([(s, c) for s, c, _ in frames], [(0x2B, 0x5F), (1, 0x27)])
        self.assertEqual(bridge_module.parse_battery(frames[1][2]), {"right": 97, "case": 23})

    def test_the_case_byte_on_and_off_a_cable_changes_nothing_printed(self):
        # The case byte is relayed by a docked bud and goes stale without one
        # (the owner unplugged the case and it still read 01), so it is not
        # a charging state; the two frames differ in it, and in the case level.
        for text, case in ((CASE_CHARGING, 63), (CASE_OFF_CABLE, 64)):
            frames = bridge_module.take_frames(bytearray(harness.hexbytes(text)))
            self.assertEqual(bridge_module.parse_battery(frames[0][2]),
                             {"left": 95, "right": 96, "case": case}, text)

    def test_bytes_before_a_frame_are_skipped(self):
        buffer = bytearray(b"\x00\x13\x37" + harness.hexbytes(ANSWER_98_98_23))
        self.assertEqual(len(bridge_module.take_frames(buffer)), 1)


class Malformed(unittest.TestCase):
    """Fault injection: bytes bent on purpose. None of these is something the
    FreeBuds SE 2 was seen to send."""

    def test_a_flipped_crc_byte_drops_the_frame(self):
        damaged = bytearray(harness.hexbytes(ANSWER_98_98_23))
        damaged[-1] ^= 0xFF
        self.assertEqual(bridge_module.take_frames(damaged), [])

    def test_a_length_too_short_for_a_command_is_dropped(self):
        raw = bytearray(b"\x5a\x00\x01\x00")
        raw += bridge_module.crc16(raw).to_bytes(2, "big")
        self.assertEqual(bridge_module.take_frames(raw), [])

    def test_a_tlv_that_runs_off_the_end_is_nothing(self):
        self.assertEqual(bridge_module.parse_battery(harness.hexbytes("02 03 62 62")), None)

    def test_no_tag_2_is_nothing(self):
        self.assertEqual(bridge_module.parse_battery(harness.hexbytes("01 01 62")), None)

    def test_a_level_over_100_is_dropped_not_clamped(self):
        self.assertEqual(bridge_module.parse_battery(harness.hexbytes("02 03 65 62 17")), None)

    def test_the_charging_bytes_are_not_read(self):
        # Synthetic: whatever tag 3 says, no part is reported charging.
        self.assertEqual(
            bridge_module.parse_battery(harness.hexbytes("02 03 62 62 17 03 03 01 01 01")),
            {"left": 98, "right": 98, "case": 23})

    def test_a_frame_for_another_command_prints_nothing(self):
        s = Session()
        s.device(HELLO)
        self.assertEqual(s.lines, [])


class Loop(unittest.TestCase):
    """The run loop, with the clock, the wait and the socket under test."""

    def setUp(self):
        self.clock = [100.0]
        self.saved = (bridge_module.now, bridge_module.wait_ready,
                      bridge_module.socket, bridge_module.os, bridge_module.time)
        bridge_module.now = lambda: self.clock[0]
        self.lines = []
        self.saved_emit = bridge_module.emit
        bridge_module.emit = self.lines.append
        self.frames = []
        self.sock = FakeSocket(self.frames)
        self.stdin = []
        self.connects = []
        self.sleeps = []
        self.refuse = 0
        self.connect_error = OSError(111, "Connection refused")

        test = self

        class FakeRfcomm:
            """The socket the bridge makes: connect() as scripted, then the
            FakeSocket's recv and sendall."""

            def __init__(self, *_args):
                pass

            def settimeout(self, *_):
                pass

            def setblocking(self, *_):
                pass

            def close(self):
                pass

            def connect(self, target):
                test.connects.append(target)
                if test.refuse:
                    test.refuse -= 1
                    raise test.connect_error

            def recv(self, size):
                return test.sock.recv(size)

            def sendall(self, data):
                test.sock.sendall(data)

        real = self.saved[2]

        bridge_module.socket = types.SimpleNamespace(
            AF_BLUETOOTH=getattr(real, "AF_BLUETOOTH", 31),
            SOCK_STREAM=getattr(real, "SOCK_STREAM", 1),
            BTPROTO_RFCOMM=getattr(real, "BTPROTO_RFCOMM", 3),
            socket=FakeRfcomm)

        def read(_fd, _size):
            return self.stdin.pop(0) if self.stdin else b""

        bridge_module.os = types.SimpleNamespace(read=read, _exit=self.saved[3]._exit)
        bridge_module.time = types.SimpleNamespace(
            sleep=self.sleeps.append, monotonic=lambda: self.clock[0])

    def tearDown(self):
        (bridge_module.now, bridge_module.wait_ready, bridge_module.socket,
         bridge_module.os, bridge_module.time) = self.saved
        bridge_module.emit = self.saved_emit

    def script(self, steps):
        """Each wait takes the next step: (seconds, incoming bytes or None,
        stdin bytes or None). Running out of steps is the pipe closing."""
        steps = list(steps)

        def wait(readers, timeout):
            if not steps:
                self.stdin.append(b"")
                return [0]
            seconds, incoming, typed = steps.pop(0)
            self.clock[0] += seconds if seconds is not None else timeout
            ready = []
            if incoming is not None:
                self.sock.incoming.append(incoming)
                ready.append(readers[1])
            if typed is not None:
                self.stdin.append(typed)
                ready.append(0)
            return ready

        bridge_module.wait_ready = wait

    def bridge(self):
        return bridge_module.Bridge(ADDRESS, NAME)

    def test_an_answer_prints_the_battery_and_a_closed_pipe_is_a_clean_stop(self):
        self.script([(0.1, harness.hexbytes(HELLO + " " + EVENT_98_98_23), None)])
        code = self.bridge().run()
        self.assertEqual(code, 0)
        self.assertEqual(self.connects, [(ADDRESS, 1)])
        self.assertEqual([harness.hexstr(f) for f in self.frames],
                         ["5a 00 09 00 01 08 01 00 02 00 03 00 fb b9"])
        self.assertEqual(self.lines, [{
            "modes": True, "available": [],
            "battery": {"left": 98, "right": 98, "case": 23, "caseStale": False}}])

    def test_silence_through_the_deadline_is_exit_3(self):
        self.script([(None, None, None)] * 20)
        code = self.bridge().run()
        self.assertEqual(code, bridge_module.EXIT_UNSUPPORTED)
        self.assertGreaterEqual(self.clock[0], 100.0 + bridge_module.ANSWER_TIMEOUT)
        self.assertEqual(self.lines[-1]["modes"], False)
        self.assertEqual(len(self.frames), 1, "asked once, not dialled again")

    def test_only_a_hello_is_still_silence(self):
        self.script([(0.1, harness.hexbytes(HELLO), None)] + [(None, None, None)] * 20)
        self.assertEqual(self.bridge().run(), bridge_module.EXIT_UNSUPPORTED)

    def test_the_link_dropping_is_exit_1(self):
        self.script([(0.1, harness.hexbytes(ANSWER_98_98_23), None), (0.1, b"", None)])
        self.assertEqual(self.bridge().run(), bridge_module.EXIT_TRANSIENT)
        self.assertEqual(self.lines[-1], {"modes": False, "error": "the Huawei channel closed"})

    def test_a_socket_error_is_exit_1(self):
        self.script([(0.1, OSError(104, "Connection reset by peer"), None)])
        self.assertEqual(self.bridge().run(), bridge_module.EXIT_TRANSIENT)

    def test_the_poll_asks_again_after_the_interval(self):
        half = bridge_module.POLL_INTERVAL / 2
        self.script([(0.1, harness.hexbytes(ANSWER_98_98_23), None),
                     (half, None, None)])
        self.bridge().run()
        self.assertEqual(len(self.frames), 1, "not before the interval")
        self.frames.clear()
        self.clock[0] = 100.0
        self.script([(0.1, harness.hexbytes(ANSWER_98_98_23), None),
                     (half, None, None), (half, None, None)])
        self.bridge().run()
        self.assertEqual(len(self.frames), 2)
        self.assertGreaterEqual(self.clock[0], 100.0 + bridge_module.POLL_INTERVAL)

    def test_an_unchanged_reading_prints_once(self):
        self.script([(0.1, harness.hexbytes(EVENT_98_98_23), None),
                     (0.1, harness.hexbytes(ANSWER_98_98_23), None)])
        self.bridge().run()
        self.assertEqual(len(self.lines), 1)

    def test_stdin_commands_send_nothing(self):
        self.script([(0.1, harness.hexbytes(ANSWER_98_98_23), None),
                     (0.1, None, b"set anc\nset off\nlevel 5\nvoice on\n")])
        self.bridge().run()
        self.assertEqual(len(self.frames), 1)

    def test_a_refused_first_connect_is_retried(self):
        self.refuse = 1
        self.script([(0.1, harness.hexbytes(ANSWER_98_98_23), None)])
        self.assertEqual(self.bridge().run(), 0)
        self.assertEqual(self.connects, [(ADDRESS, 1)] * 2)
        self.assertEqual(self.sleeps, [bridge_module.CONNECT_RETRY])

    def test_never_connecting_is_exit_1_after_every_attempt(self):
        self.refuse = 99
        self.assertEqual(self.bridge().run(), bridge_module.EXIT_TRANSIENT)
        self.assertEqual(len(self.connects), bridge_module.CONNECT_ATTEMPTS)
        self.assertEqual(self.lines[-1]["modes"], False)
        # Refused is what the earbuds answer while a phone holds the channel.
        self.assertIn("another device", self.lines[-1]["error"])

    def test_a_connect_that_times_out_says_so(self):
        self.refuse = 99
        self.connect_error = OSError(110, "Connection timed out")
        self.assertEqual(self.bridge().run(), bridge_module.EXIT_TRANSIENT)
        self.assertEqual(self.lines[-1]["error"], "cannot open the Huawei channel: Connection timed out")

    def test_a_stop_during_connect_makes_no_further_attempt(self):
        self.refuse = 99
        bridge = self.bridge()

        def sleep(_seconds):
            bridge.stopping = True

        bridge_module.time = types.SimpleNamespace(sleep=sleep, monotonic=lambda: self.clock[0])
        self.assertEqual(bridge.run(), 0)
        self.assertEqual(len(self.connects), 1)
        self.assertEqual(self.frames, [])


class Arguments(unittest.TestCase):
    def run_main(self, argv):
        lines = []
        saved = bridge_module.sys.argv, bridge_module.emit
        bridge_module.sys.argv = ["huawei-bridge"] + argv
        bridge_module.emit = lines.append
        try:
            return bridge_module.main(), lines
        finally:
            bridge_module.sys.argv, bridge_module.emit = saved

    def test_a_bad_address_is_exit_4(self):
        code, lines = self.run_main(["not-an-address", NAME])
        self.assertEqual(code, bridge_module.EXIT_SETUP)
        self.assertEqual(lines[-1]["modes"], False)

    def test_a_model_with_no_row_is_exit_4(self):
        for name in ("", "HUAWEI FreeBuds 5i", "TOZO NC9 Pro"):
            code, lines = self.run_main([ADDRESS, name])
            self.assertEqual(code, bridge_module.EXIT_SETUP, name)
            self.assertIn("no row", lines[-1]["error"])
