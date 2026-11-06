"""What airoha-bridge sends the JBL Tour Pro 3, and what it prints.

    python -m unittest tests.airoha_bridge_test

The frozen session is tests/pins/airoha/jbl-tour-pro-3.json. Every frame the
device sends in it is a reply or notification copied from
docs/captures/jbl-tour-pro-3.txt; every frame the bridge sends is one the JBL
Headphones app sent, from the same capture's section 2. What is here is the
rest: framing faults, silence, a closed link, what is not read, and the
argument checks. Cases marked synthetic are fault injection, not something
the earbuds said.
"""
import io
import os
import re
import unittest
from unittest import mock

from tests import harness

bridge_module = harness.load_bridge("airoha-bridge")

CAPTURE = os.path.join(harness.ROOT, "docs", "captures", "jbl-tour-pro-3.txt")

GET = "05 5a 04 00 01 09 05 00"
AVAILABLE = ["off", "anc", "ambient", "talkthru"]
# Observed, section 3 of the capture.
REPLY_OFF = "05 5b 09 00 01 09 05 00 00 00 00 00 06"
EVENTS = {
    "off": "05 5d 08 00 01 09 05 00 00 00 1e e4",
    "anc": "05 5d 05 00 86 00 00 01 00 05 5d 08 00 01 09 05 00 00 01 07 00",
    "ambient": "05 5d 08 00 01 09 05 00 00 0a 07 00",
    "talkthru": "05 5d 08 00 01 09 05 00 00 09 00 04",
}


def line(mode):
    return {"modes": True, "mode": mode, "available": AVAILABLE}


class Session(harness.Session):
    """An Airoha session. "device" in a pin is whole or partial RACE frames as
    hex, fed through the bridge's framer as one read. "sent" is every frame the
    bridge wrote, as hex. "open" is the channel opening: it sends the get."""

    def __init__(self):
        super().__init__(bridge_module)
        self.bridge = bridge_module.Bridge(None, "A0:11:22:33:44:55", harness.FakeLoop())
        self.bridge.write = self.frames.append
        self.bridge.fd = -1

    def device(self, spec):
        self.bridge.buffer += harness.hexbytes(spec)
        self.bridge.parse_buffer()

    def do_open(self):
        self.bridge.ask()


harness.pin_tests(globals(), "airoha-bridge", Session)


class Evidence(unittest.TestCase):
    def test_the_pin_names_its_capture(self):
        pins = harness.pins_for("airoha-bridge")
        self.assertTrue(pins)
        for _path, pin in pins:
            self.assertTrue(pin["capture"].startswith("docs/captures/jbl-tour-pro-3"))
            self.assertTrue(os.path.exists(os.path.join(harness.ROOT, pin["capture"])))

    def test_every_frame_in_the_pin_is_in_the_capture(self):
        for _path, pin in harness.pins_for("airoha-bridge"):
            # The pin's own capture, plus the main one: a wear pin borrows the
            # mode answer that its session needs from the mode capture.
            text = ""
            for name in {pin["capture"], "docs/captures/jbl-tour-pro-3.txt"}:
                with open(os.path.join(harness.ROOT, name)) as handle:
                    text += handle.read()
            for step in pin["steps"]:
                if "device" in step:
                    for frame in re.split(r"(?=05 5[abcd] )", step["device"]):
                        if frame.strip():
                            self.assertTrue(frame.strip() in text, frame)
                for sent in step.get("sent", []) + [step.get("sent_last")]:
                    if sent:
                        self.assertTrue(sent in text, sent)

    def test_the_sets_are_the_apps_frames(self):
        with open(CAPTURE) as handle:
            text = handle.read()
        for mode, frame in bridge_module.SET.items():
            self.assertTrue("TX " + harness.hexstr(frame) in text, mode)


class Framing(unittest.TestCase):
    def feed(self, chunks):
        s = Session()
        for chunk in chunks:
            s.device(chunk)
        return s

    def test_a_stream_split_at_every_byte_boundary_reads_the_same(self):
        stream = harness.hexbytes(" ".join([REPLY_OFF, EVENTS["anc"], EVENTS["ambient"]]))
        for cut in range(1, len(stream)):
            s = Session()
            s.bridge.buffer += stream[:cut]
            s.bridge.parse_buffer()
            s.bridge.buffer += stream[cut:]
            s.bridge.parse_buffer()
            self.assertEqual(s.lines, [line("off"), line("anc"), line("ambient")], cut)

    def test_frames_glued_together_are_all_read(self):
        s = self.feed([" ".join([REPLY_OFF, EVENTS["anc"]])])
        self.assertEqual(s.lines, [line("off"), line("anc")])

    def test_synthetic_noise_before_and_between_frames_is_skipped(self):
        s = self.feed(["00 ff 05 05 5e " + EVENTS["ambient"] + " 05 5d ff ff " + EVENTS["off"]])
        self.assertEqual(s.lines, [line("ambient"), line("off")])
        self.assertEqual(len(s.bridge.buffer), 0)

    def test_synthetic_oversized_length_is_not_waited_for(self):
        s = self.feed(["05 5d ff 7f " + EVENTS["talkthru"]])
        self.assertEqual(s.lines, [line("talkthru")])


class NotRead(unittest.TestCase):
    def test_other_frames_the_earbuds_sent_say_nothing(self):
        s = Session()
        for frame in (
            "05 5c 06 00 01 09 65 00 00 4b",           # connect-time notification
            "05 5d 1e 00 82 00 00 01 01 00 01 01 01 01 01 01 05 06 04 00 00 00 00 00 00 01 01 01 01 01 01 01 01 01",
            "05 5d 0a 00 93 00 00 aa b1 04 02 03 01 01",  # periodic status
            "05 5b 08 00 06 0e 00 0a 01 00 00 00",     # write acknowledgement
            "05 5d 0c 00 15 0e 02 00 00 00 00 00 00 00 00 00",
            "05 5b 07 00 01 09 07 00 00 07 00",        # 0901 but another query
            GET,                                       # an echo of the get itself
        ):
            s.device(frame)
        self.assertEqual(s.lines, [])

    def test_synthetic_unknown_mode_byte_prints_nothing(self):
        s = Session()
        s.device("05 5d 08 00 01 09 05 00 00 7f 07 00")
        self.assertEqual(s.lines, [])
        self.assertIsNone(s.bridge.last_mode)

    def test_commands_it_does_not_know_send_nothing(self):
        s = Session()
        s.device(REPLY_OFF)
        for text in ("set wind", "set", "set anc extra", "level 3", "voice on", "", "anc"):
            s.command(text)
        self.assertEqual(s.sent, [])

    def test_a_set_waits_for_the_first_answer(self):
        s = Session()
        s.command("set anc")
        self.assertEqual(s.sent, [])


class Wear(unittest.TestCase):
    def lines_for(self, *frames):
        s = Session()
        s.device(REPLY_OFF)
        for frame in frames:
            s.device(frame)
        return s.lines

    def test_a_wear_frame_that_is_not_that_exact_shape_says_nothing(self):
        for frame in (
            "05 5c 05 00 0c 00 00 02 01",       # synthetic: an ear that does not exist
            "05 5c 05 00 0c 00 00 00 02",       # synthetic: a state that is neither
            "05 5c 05 00 0c 00 01 00 01",       # synthetic: a non-zero status
            "05 5d 05 00 0c 00 00 00 01",       # synthetic: a response, not a notification
            "05 5c 05 00 0b 00 00 00 01",       # synthetic: another command
        ):
            self.assertEqual(self.lines_for(frame), [line("off")], frame)

    def test_both_ears_out_is_not_worn_and_one_ear_in_is_worn(self):
        out = self.lines_for("05 5c 05 00 0c 00 00 00 00", "05 5c 05 00 0c 00 00 01 00")
        self.assertEqual(out[-1]["worn"], False)
        one = self.lines_for("05 5c 05 00 0c 00 00 00 00", "05 5c 05 00 0c 00 00 01 01")
        self.assertEqual(one[-1]["worn"], True)

    def test_one_ear_heard_out_is_not_a_verdict(self):
        self.assertEqual(self.lines_for("05 5c 05 00 0c 00 00 00 00"), [line("off")])

    def test_worn_is_left_out_until_an_ear_has_spoken(self):
        self.assertNotIn("worn", self.lines_for()[-1])


class Silent(unittest.TestCase):
    def test_silence_after_the_get_parks_the_address(self):
        s = Session()
        s.do_open()
        s.bridge.answer_timeout()
        self.assertEqual(s.bridge.exit_code, bridge_module.EXIT_UNSUPPORTED)

    def test_an_answer_cancels_the_verdict(self):
        s = Session()
        s.do_open()
        s.device(REPLY_OFF)
        s.bridge.answer_timeout()
        self.assertIsNone(s.bridge.exit_code)

    def test_only_a_frame_that_reads_as_a_mode_counts_as_an_answer(self):
        s = Session()
        s.do_open()
        s.device("05 5d 0a 00 93 00 00 aa b1 04 02 00 01 00")
        s.bridge.answer_timeout()
        self.assertEqual(s.bridge.exit_code, bridge_module.EXIT_UNSUPPORTED)


class Link(unittest.TestCase):
    def test_a_hangup_is_transient(self):
        s = Session()
        s.bridge.fd = None
        s.bridge.on_io(None, harness.FakeGLib.IO_HUP)
        self.assertEqual(s.bridge.exit_code, bridge_module.EXIT_TRANSIENT)
        self.assertFalse(s.lines[-1]["modes"])

    def test_it_stops_cleanly_once(self):
        s = Session()
        s.bridge.finish(0)
        s.bridge.finish(bridge_module.EXIT_TRANSIENT, "late")
        self.assertEqual(s.bridge.exit_code, 0)
        self.assertEqual(s.lines, [])


class Arguments(unittest.TestCase):
    def run_main(self, argv):
        out = io.StringIO()
        lines = []
        with mock.patch.object(bridge_module.sys, "argv", ["airoha-bridge"] + argv), \
                mock.patch.object(bridge_module, "emit", lines.append), \
                mock.patch("sys.stdout", out):
            try:
                code = bridge_module.main()
            except SystemExit as stop:
                code = stop.code
        return code, lines, out.getvalue()

    def test_help_is_exit_zero(self):
        code, _lines, printed = self.run_main(["--help"])
        self.assertEqual(code, 0)
        self.assertIn("usage: airoha-bridge", printed)

    def test_bad_addresses_and_missing_names_are_setup_failures(self):
        for argv in ([], ["A0:11:22:33:44:55"], ["nope", "JBL Tour Pro 3"],
                     ["A0:11:22:33:44:55", "JBL Tour Pro 3", "extra"]):
            code, lines, _ = self.run_main(argv)
            self.assertEqual(code, bridge_module.EXIT_SETUP, argv)
            self.assertFalse(lines[-1]["modes"])

    def test_only_its_own_model_has_a_row(self):
        for name in ("", "JBL Tour Pro 2", "JBL Tour Pro 3 ", "jbl tour pro 3", "JBL TUNE230NC TWS"):
            code, lines, _ = self.run_main(["A0:11:22:33:44:55", name])
            self.assertEqual(code, bridge_module.EXIT_SETUP, name)
            self.assertIn("no row", lines[-1]["error"])


if __name__ == "__main__":
    unittest.main()
