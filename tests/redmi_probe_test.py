"""What tools/redmi_probe.py writes to Redmi Buds 5, and whether it puts them back.

    python -m unittest tests.redmi_probe_test

The probe reads by default. With --cycle it sets modes, and then what matters
is that it does not write unless the initial mode is known, that every set is
checked against what the earbuds report, and that the mode they were in is set
again and checked, on every way out. The earbuds here are a fake that answers
the way the real ones did in docs/captures/redmi-buds-5.txt, on a fake clock.
"""
import contextlib
import importlib.machinery
import io as stdio
import importlib.util
import os
import unittest

from tests import harness

ROOT = harness.ROOT
bridge = harness.load_bridge("redmi-bridge")


def load_probe():
    path = os.path.join(ROOT, "tools", "redmi_probe.py")
    loader = importlib.machinery.SourceFileLoader("redmi_probe", path)
    spec = importlib.util.spec_from_loader("redmi_probe", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


probe = load_probe()

# GetTargetInfo answer, as the earbuds sent it (75, 80, 100).
ANSWER = bytes.fromhex(
    "fe dc ba 00 02 00 2c 00 01 05 01 10 38 10 38 05 03 27 17 50 6a 02 04 01 "
    "02 05 00 03 06 10 38 04 07 4b 50 64 02 08 02 02 09 00 02 0c 00 02 0d 02 "
    "02 0e 00 ef")


def noise(state, level=0, sn=1):
    return bytes.fromhex("fe dc ba 00 f3 00 07 00 %02x 04 00 0b %02x %02x ef" % (sn, state, level))


def notify(state, level=0, sn=1):
    return bytes.fromhex("fe dc ba c7 f4 00 06 %02x 04 00 0b %02x %02x ef" % (sn, state, level))


def ack(sn, status=0):
    return bytes.fromhex("fe dc ba 00 f2 00 02 %02x %02x ef" % (status, sn))


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Earbuds:
    """A pair of earbuds that answer as the captured ones did. Synthetic in what
    it is made to refuse, to drop or to keep quiet about."""

    def __init__(self, clock, state=2, level=0, announces=True, silent=False,
                 refuse_from=None, drop_after_sets=None, interrupt_on_set=None):
        self.clock = clock
        self.state, self.level = state, level
        self.announces = announces
        self.silent = silent
        self.refuse_from = refuse_from        # refuse the Nth set and on
        self.drop_after_sets = drop_after_sets
        self.interrupt_on_set = interrupt_on_set
        self.sets = []
        self.writes = []
        self.queue = []
        self.dead = False

    def write(self, data):
        self.writes.append(bytes(data))
        frame, _ = bridge.split_frame(bytearray(data))
        opcode, sn = frame[4], frame[7]
        if self.silent:
            return
        if opcode == bridge.OP_GET_CONFIG:
            self.queue.append(noise(self.state, self.level, sn))
        elif opcode == bridge.OP_GET_TARGET_INFO:
            self.queue.append(ANSWER)
        elif opcode == bridge.OP_SET_CONFIG:
            self.sets.append((frame[11], frame[12]))
            if self.interrupt_on_set == len(self.sets):
                self.interrupt_on_set = None
                raise KeyboardInterrupt
            if self.refuse_from is not None and len(self.sets) >= self.refuse_from:
                self.queue.append(ack(sn, status=1))
                return
            self.state, self.level = frame[11], frame[12]
            if self.announces:
                self.queue.append(notify(self.state, self.level, sn))
            self.queue.append(ack(sn))
            if self.drop_after_sets == len(self.sets):
                self.queue.append(None)

    def read(self, timeout):
        if self.dead:
            return None
        if self.queue:
            item = self.queue.pop(0)
            if item is None:
                self.dead = True
            return item
        self.clock.now += timeout
        return b""


def run(modes, listen=1.0, **earbuds):
    clock = Clock()
    io = Earbuds(clock, **earbuds)
    lines = []
    try:
        code = probe.run(bridge, io, modes, listen, lines.append, clock)
    except KeyboardInterrupt:
        code = "interrupted"
    return code, io, lines


def sent_states(io):
    return [state for state, _level in io.sets]


class Reading(unittest.TestCase):
    def test_by_default_it_only_reads(self):
        code, io, lines = run([])
        self.assertEqual(code, probe.EXIT_OK)
        self.assertEqual(io.sets, [])
        self.assertEqual([w[4] for w in io.writes], [bridge.OP_GET_CONFIG, bridge.OP_GET_TARGET_INFO])

    def test_it_prints_both_directions_decoded(self):
        _, _, lines = run([])
        text = "\n".join(lines)
        self.assertIn("TX  fe dc ba c0 f3 00 03 01 00 0b ef", text)
        self.assertIn("noise control ambient (state 2, level 0)", text)
        self.assertIn("battery left 75%, right 80%, case 100%; charging: none", text)

    def test_a_silent_pair_is_reported_not_hung_on(self):
        code, io, lines = run([], silent=True)
        self.assertEqual(code, probe.EXIT_OK)
        self.assertIn("did not report their noise control", "\n".join(lines))

    def test_a_closed_link_is_exit_1(self):
        code, io, lines = run([], drop_after_sets=0)
        io.dead = True
        clock = Clock()
        io2 = Earbuds(clock)
        io2.dead = True
        self.assertEqual(probe.run(bridge, io2, [], 1.0, lines.append, clock), probe.EXIT_LINK)

    def test_the_decoding_of_a_refused_set_and_an_announcement(self):
        p = probe.Probe(bridge, None, lambda line: None)
        self.assertEqual(p.describe(ack(3, status=1)), "set REFUSED (status 1)")
        self.assertEqual(p.describe(ack(3)), "set acknowledged")
        self.assertIn("status report", p.describe(bytes.fromhex("fe dc ba c7 0e 00 04 04 02 04 01 ef")))
        self.assertEqual(p.describe(bytes.fromhex("fe dc ba 00 05 00 02 00 01 ef")), "not read")


class Cycling(unittest.TestCase):
    def test_every_mode_is_set_and_the_initial_one_comes_back(self):
        code, io, lines = run(["off", "anc", "ambient"])
        self.assertEqual(code, probe.EXIT_OK)
        self.assertEqual(sent_states(io), [0, 1, 2, 2])
        self.assertEqual((io.state, io.level), (2, 0))
        self.assertIn("restored: ambient", "\n".join(lines))

    def test_each_set_is_checked_against_what_the_earbuds_say(self):
        _, _, lines = run(["anc"])
        self.assertIn("anc: the earbuds agree", "\n".join(lines))

    def test_without_an_announcement_the_probe_reads_it_back(self):
        code, io, lines = run(["anc"], announces=False)
        self.assertEqual(code, probe.EXIT_OK)
        self.assertIn("read it back", "\n".join(lines))
        self.assertEqual(sent_states(io), [1, 2])

    def test_the_strength_the_earbuds_were_at_is_what_comes_back(self):
        code, io, lines = run(["off"], state=1, level=2)
        self.assertEqual(io.sets, [(0, 0), (1, 2)])
        self.assertEqual(code, probe.EXIT_OK)

    def test_an_unknown_initial_mode_means_nothing_is_written(self):
        code, io, lines = run(["anc"], silent=True)
        self.assertEqual(code, probe.EXIT_NO_INITIAL)
        self.assertEqual(io.sets, [])
        self.assertIn("nothing is written", "\n".join(lines))

    def test_earbuds_that_refuse_cannot_be_restored_and_it_says_so(self):
        code, io, lines = run(["off", "anc"], refuse_from=2)
        self.assertEqual(code, probe.EXIT_NOT_RESTORED)
        self.assertIn("RESTORE FAILED: set ambient by hand", "\n".join(lines))

    def test_a_refusal_is_not_taken_for_agreement(self):
        code, io, lines = run(["off"], refuse_from=1)
        self.assertIn("off: NOT CONFIRMED", "\n".join(lines))

    def test_a_link_that_drops_mid_cycle_says_the_restore_failed(self):
        code, io, lines = run(["off", "anc"], drop_after_sets=1)
        self.assertEqual(code, probe.EXIT_NOT_RESTORED)
        text = "\n".join(lines)
        self.assertIn("RESTORE FAILED: the link closed", text)
        self.assertEqual(sent_states(io), [0])

    def test_a_write_that_fails_is_a_closed_link_not_a_traceback(self):
        clock = Clock()
        io = Earbuds(clock)
        real_write = io.write

        def write(data):
            frame, _ = bridge.split_frame(bytearray(data))
            if frame[4] == bridge.OP_SET_CONFIG:
                raise BrokenPipeError("gone")
            real_write(data)

        io.write = write
        lines = []
        code = probe.run(bridge, io, ["off"], 1.0, lines.append, clock)
        self.assertEqual(code, probe.EXIT_NOT_RESTORED)
        self.assertIn("write failed", "\n".join(lines))

    def test_an_interrupt_still_puts_the_earbuds_back(self):
        code, io, lines = run(["off", "anc"], interrupt_on_set=2)
        self.assertEqual(code, "interrupted")
        self.assertEqual((io.state, io.level), (2, 0))
        self.assertIn("restored: ambient", "\n".join(lines))

    def test_the_restoration_is_verified_not_assumed(self):
        # The earbuds acknowledge the restoring set and then report the other mode.
        clock = Clock()
        io = Earbuds(clock)
        real_write = io.write

        def write(data):
            real_write(data)
            frame, _ = bridge.split_frame(bytearray(data))
            if frame[4] == bridge.OP_SET_CONFIG and len(io.sets) == 2:
                io.queue[:] = [notify(1), ack(frame[7])]

        io.write = write
        lines = []
        code = probe.run(bridge, io, ["anc"], 1.0, lines.append, clock)
        self.assertEqual(code, probe.EXIT_NOT_RESTORED)


class Arguments(unittest.TestCase):
    def test_a_bad_address_or_mode_is_refused_before_any_connection(self):
        for argv in (["nope"], ["AA:BB:CC:00:00:01", "--cycle", "talkthru"]):
            with contextlib.redirect_stderr(stdio.StringIO()), \
                    self.assertRaises(SystemExit) as raised:
                probe.main(argv)
            self.assertEqual(raised.exception.code, 2)



# ---- Redmi Buds 3 Pro: the handshake first, and announcements that come back
#      until they are answered (docs/captures/redmi-buds-3-pro.txt, runs 2 and 3).

THEIR_CHALLENGE = bytes.fromhex("785af7fbb2609cc774c27d69d13621b9")
B3P = bridge.MODELS["Redmi Buds 3 Pro"]
REPEAT = 2.0   # seconds before an unanswered announcement came again


class AuthEarbuds(Earbuds):
    """Earbuds that answer nothing until authenticated, and repeat every
    unanswered announcement two seconds later, as the captured ones did. Synthetic where told to answer wrongly or not at all."""

    def __init__(self, clock, wrong_answer=False, mute_auth=False, **kwargs):
        super().__init__(clock, **kwargs)
        self.wrong_answer = wrong_answer
        self.mute_auth = mute_auth
        self.authenticated = False
        self.unanswered = []
        self.acked = []

    def write(self, data):
        frame, _ = bridge.split_frame(bytearray(data))
        opcode, flags = frame[4], frame[3]
        if not self.authenticated:
            self.writes.append(bytes(data))
            if self.mute_auth:
                return
            if opcode == bridge.OP_AUTH_CHALLENGE and flags & 0x80:
                answer = bridge.auth_response(frame[9:25])
                if self.wrong_answer:
                    answer = bytes([answer[0] ^ 1]) + answer[1:]
                self.queue.append(bridge.encode_response(opcode, frame[7], b"\x01" + answer))
            elif opcode == bridge.OP_AUTH_CONFIRM and flags & 0x80:
                self.queue.append(bridge.encode_response(opcode, frame[7], b"\x01"))
                self.queue.append(bridge.encode(bridge.OP_AUTH_CHALLENGE, 0, b"\x01" + THEIR_CHALLENGE))
            elif opcode == bridge.OP_AUTH_CHALLENGE and frame[10:26] == bridge.auth_response(THEIR_CHALLENGE):
                self.queue.append(bridge.encode(bridge.OP_AUTH_CONFIRM, 1, b"\x01\x00"))
            elif opcode == bridge.OP_AUTH_CONFIRM and not flags & 0x80:
                self.authenticated = True
            return
        if not flags & 0x80:
            self.writes.append(bytes(data))
            self.acked.append((opcode, frame[8]))
            self.unanswered = [(at, f) for at, f in self.unanswered
                               if (f[4], f[7]) != (opcode, frame[8])]
            return
        before, state = len(self.queue), self.state
        super().write(data)
        if opcode == bridge.OP_SET_CONFIG and frame[11] == state:
            # A set to the mode they are in was acknowledged and not announced.
            self.queue[before:] = [item for item in self.queue[before:]
                                   if item is None or item[4] != bridge.OP_NOTIFY_CONFIG]
        for item in self.queue[before:]:
            if item and item[3] & 0x80:
                self.unanswered.append((self.clock.now, item))

    def read(self, timeout):
        due = [f for at, f in self.unanswered if self.clock.now - at >= REPEAT]
        if not self.queue and due and not self.dead:
            self.unanswered = [(self.clock.now, f) for _at, f in self.unanswered]
            self.queue.extend(due)
            return self.queue.pop(0)
        if not self.queue and self.unanswered and not self.dead:
            first = min(at for at, _f in self.unanswered) + REPEAT
            wait = min(timeout, max(0.0, first - self.clock.now))
            if wait < timeout:
                self.clock.now += wait
                return b""
        return super().read(timeout)


def run_b3p(modes, model=B3P, **earbuds):
    clock = Clock()
    io = AuthEarbuds(clock, **earbuds)
    lines = []
    code = probe.run(bridge, io, modes, 1.0, lines.append, clock, model=model,
                     challenge=lambda n: bytes.fromhex("dd3b5c5dfbe669841c2e8184758e6600"))
    return code, io, lines


class Buds3Pro(unittest.TestCase):
    def test_it_authenticates_then_reads(self):
        code, io, lines = run_b3p([])
        self.assertEqual(code, probe.EXIT_OK)
        text = "\n".join(lines)
        self.assertIn("their answer to our challenge: matches", text)
        self.assertIn("authenticated", text)
        self.assertIn("noise control ambient", text)

    def test_the_cycle_restores_and_every_announcement_is_answered(self):
        code, io, lines = run_b3p(["off", "anc", "ambient"])
        self.assertEqual(code, probe.EXIT_OK)
        self.assertEqual(sent_states(io), [0, 1, 2, 2])
        self.assertIn("restored: ambient", "\n".join(lines))
        self.assertEqual(io.unanswered, [])
        self.assertEqual([sn for op, sn in io.acked if op == 0xF4], [5, 6, 7])

    def test_without_answering_a_stale_announcement_is_taken_for_the_mode(self):
        # The capture's second run, which is why the row answers them.
        code, io, lines = run_b3p(["off", "anc", "ambient"],
                                  model={"authenticate": True, "acknowledge": False,
                                         "status_battery": False})
        self.assertEqual(code, probe.EXIT_NOT_RESTORED)
        self.assertIn("ambient: NOT CONFIRMED", "\n".join(lines))
        self.assertEqual(io.state, 2)

    def test_a_wrong_answer_stops_it_before_anything_else_is_sent(self):
        code, io, lines = run_b3p(["off"], wrong_answer=True)
        self.assertEqual(code, probe.EXIT_NO_AUTH)
        self.assertEqual([w[4] for w in io.writes], [bridge.OP_AUTH_CHALLENGE])
        self.assertIn("their answer to our challenge: WRONG", "\n".join(lines))
        self.assertEqual(io.sets, [])

    def test_silence_during_the_handshake_is_reported_and_nothing_is_written(self):
        code, io, lines = run_b3p(["off"], mute_auth=True)
        self.assertEqual(code, probe.EXIT_NO_AUTH)
        self.assertIn("NOT AUTHENTICATED", "\n".join(lines))
        self.assertEqual(io.sets, [])

    def test_an_unknown_name_is_refused_before_any_connection(self):
        with contextlib.redirect_stderr(stdio.StringIO()), \
                self.assertRaises(SystemExit) as raised:
            probe.main(["--name", "Redmi Buds 9", "AA:BB:CC:00:00:01"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
