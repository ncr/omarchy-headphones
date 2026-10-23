"""What tools/earfun_probe.py writes to EarFun Air Pro 4, and whether it puts them back.

    python -m unittest tests.earfun_probe_test

The probe reads by default. With --cycle it sets modes, and then what matters
is that it does not write unless the initial mode is known, that every set is
checked against what the earbuds report, and that the mode they were in is set
again and checked, on every way out. The earbuds here are a fake that answers
the way the real ones did in docs/captures/earfun-air-pro-4.txt (no reply to a
set, the old mode read back until the change is done), on a fake clock.
"""
import contextlib
import importlib.machinery
import importlib.util
import io
import os
import unittest

from tests import harness

bridge = harness.load_bridge("earfun-bridge")


def load_probe():
    path = os.path.join(harness.ROOT, "tools", "earfun_probe.py")
    loader = importlib.machinery.SourceFileLoader("earfun_probe", path)
    spec = importlib.util.spec_from_loader("earfun_probe", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


probe = load_probe()

FIRMWARE = bytes.fromhex(
    "ff 03 00 1b 00 0a 83 09 00 54 57 36 30 30 2d 33 30 39 31 5f 32 30 32 35 30 39 31 39"
    " 5f 76 30 2e 34 2e 31")
OWN_BURST = bytes.fromhex(
    "ff 03 00 05 00 0a 03 58 00 5c 3b 4d 01 ff 03 00 05 00 0a 03 58 00 33 4e e5 00"
    " ff 03 00 02 00 0a 03 4d 00 03")
VALUE = {"off": 0, "anc": 1, "ambient": 2}


def answer(mode):
    return bytes.fromhex("ff 03 00 02 00 0a 83 15 00 %02x" % VALUE[mode])


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


class Earbuds:
    """Earbuds that answer as the captured ones did. Synthetic in what they are
    made to ignore, to drop or to keep quiet about."""

    def __init__(self, clock, mode="off", delay=1.5, silent=False, ignore_from=None,
                 drop_after_sets=None, interrupt_on_set=None, glue=False):
        self.clock = clock
        self.mode = mode
        self.delay = delay
        self.silent = silent
        self.ignore_from = ignore_from          # ignore the Nth set and on
        self.drop_after_sets = drop_after_sets
        self.interrupt_on_set = interrupt_on_set
        self.glue = glue
        self.change = None                      # (when, mode)
        self.sets = []
        self.writes = []
        self.queue = []
        self.dead = False

    def current(self):
        if self.change and self.clock.now >= self.change[0]:
            self.mode = self.change[1]
            self.change = None
        return self.mode

    def write(self, data):
        if self.dead:
            raise OSError("closed")
        self.writes.append(bytes(data))
        command = int.from_bytes(data[6:8], "big")
        if command == bridge.SET_AMBIENT_SOUND:
            mode = bridge.MODE_FROM_VALUE[data[8]]
            self.sets.append(mode)
            if self.interrupt_on_set == len(self.sets):
                raise KeyboardInterrupt
            if self.drop_after_sets == len(self.sets):
                self.dead = True
                return
            if self.ignore_from is None or len(self.sets) < self.ignore_from:
                self.change = (self.clock.now + self.delay, mode)
            return
        if self.silent:
            return
        if command == bridge.GET_AMBIENT_SOUND:
            reply = answer(self.current())
            self.queue.append(OWN_BURST + reply if self.glue else reply)
        elif command == probe.GET_FIRMWARE:
            self.queue.append(FIRMWARE)

    def read(self, timeout):
        if self.dead:
            return None
        if self.queue:
            return self.queue.pop(0)
        self.clock.now += timeout
        return b""


def run(earbuds, clock, modes, listen=0.0):
    out = []
    code = probe.run(bridge, earbuds, modes, listen, out.append, clock)
    return code, out


class ReadOnly(unittest.TestCase):
    def test_without_a_cycle_nothing_is_set(self):
        clock = Clock()
        buds = Earbuds(clock, "ambient")
        code, out = run(buds, clock, [])
        self.assertEqual(code, probe.EXIT_OK)
        self.assertEqual(buds.sets, [])
        self.assertEqual(buds.writes, [bridge.encode(probe.GET_FIRMWARE), bridge.encode_get_mode()])
        self.assertTrue(any("noise control ambient" in line for line in out))
        self.assertTrue(any("firmware TW600-3091_20250919_v0.4.1" in line for line in out))

    def test_a_glued_read_is_kept_whole_and_every_frame_in_it_is_shown(self):
        clock = Clock()
        buds = Earbuds(clock, "anc", glue=True)
        code, out = run(buds, clock, [])
        self.assertEqual(code, probe.EXIT_OK)
        raw = [line for line in out if "RX  " in line]
        self.assertTrue(any((OWN_BURST + answer("anc")).hex(" ") in line for line in raw))
        frames = [line for line in out if "frame " in line]
        self.assertEqual(sum("own 0358" in line for line in frames), 2)
        self.assertEqual(sum("own 034d" in line for line in frames), 1)
        self.assertTrue(any("noise control anc" in line for line in frames))


class Cycle(unittest.TestCase):
    def test_every_mode_is_set_checked_and_the_initial_one_restored(self):
        clock = Clock()
        buds = Earbuds(clock, "off")
        code, out = run(buds, clock, ["anc", "ambient", "off"])
        self.assertEqual(code, probe.EXIT_OK)
        self.assertEqual(buds.sets, ["anc", "ambient", "off", "off"])
        self.assertEqual(buds.mode, "off")
        self.assertEqual(sum("the earbuds agree" in line for line in out), 4)
        self.assertIn("restored: off", out[-1])

    def test_a_slow_change_is_waited_for_rather_than_reported_failed(self):
        # 2.1 s, the slowest seen, is past the first readback.
        clock = Clock()
        buds = Earbuds(clock, "off", delay=2.1)
        code, out = run(buds, clock, ["anc"])
        self.assertEqual(code, probe.EXIT_OK)
        self.assertNotIn("NOT CONFIRMED", "\n".join(out))
        after_set = out[next(i for i, line in enumerate(out) if "set anc" in line):]
        seen = [line.rsplit("noise control ", 1)[1] for line in after_set
                if "frame" in line and "noise control" in line]
        self.assertEqual(seen[:3], ["off", "off", "anc"])

    def test_an_unknown_initial_mode_writes_nothing(self):
        clock = Clock()
        buds = Earbuds(clock, silent=True)
        code, out = run(buds, clock, ["anc"])
        self.assertEqual(code, probe.EXIT_NO_INITIAL)
        self.assertEqual(buds.sets, [])
        self.assertIn("nothing is written", out[-1])

    def test_earbuds_that_ignore_a_set_are_not_reported_restored(self):
        clock = Clock()
        buds = Earbuds(clock, "ambient", ignore_from=2)
        code, out = run(buds, clock, ["anc"])
        self.assertEqual(code, probe.EXIT_NOT_RESTORED)
        self.assertEqual(buds.sets, ["anc", "ambient"])
        self.assertIn("RESTORE FAILED", out[-1])
        # The probe asked the bridge's count of times before giving up.
        gets = buds.writes[buds.writes.index(bridge.encode_set_mode("ambient")) + 1:]
        self.assertEqual(gets, [bridge.encode_get_mode()] * bridge.RECHECKS)

    def test_a_link_that_drops_mid_cycle_is_a_failed_restore(self):
        clock = Clock()
        buds = Earbuds(clock, "off", drop_after_sets=2)
        code, out = run(buds, clock, ["anc", "ambient", "off"])
        self.assertEqual(code, probe.EXIT_NOT_RESTORED)
        self.assertEqual(buds.sets, ["anc", "ambient"])
        self.assertIn("RESTORE FAILED: the link closed", out[-1])

    def test_an_interrupt_mid_cycle_still_restores(self):
        clock = Clock()
        buds = Earbuds(clock, "off", interrupt_on_set=2)
        code, out = run(buds, clock, ["anc", "ambient", "off"])
        self.assertEqual(code, probe.EXIT_OK)
        self.assertEqual(buds.sets, ["anc", "ambient", "off"])
        self.assertEqual(buds.mode, "off")
        self.assertTrue(any("interrupted" in line for line in out))
        self.assertIn("restored: off", out[-1])

    def test_a_link_already_closed_at_the_first_read_writes_nothing_more(self):
        clock = Clock()
        buds = Earbuds(clock)
        buds.dead = True
        code, _out = run(buds, clock, ["anc"])
        self.assertEqual(code, probe.EXIT_LINK)
        self.assertEqual(buds.sets, [])


class Arguments(unittest.TestCase):
    def test_a_bad_address_or_mode_is_refused_before_anything_opens(self):
        for argv in (["nope"], ["AA:BB:CC:00:00:02", "--cycle", "talkthru"]):
            with self.assertRaises(SystemExit) as raised, \
                    contextlib.redirect_stderr(io.StringIO()):
                probe.main(argv)
            self.assertEqual(raised.exception.code, 2, argv)


if __name__ == "__main__":
    unittest.main()
