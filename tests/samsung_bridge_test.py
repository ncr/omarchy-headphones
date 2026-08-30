"""Pins what samsung-bridge sends for the Galaxy Buds2.

    python -m unittest tests/samsung_bridge_test.py

The Samsung row is the same kind of promise as the Sony and Soundcore ones:
this headset answered one exact status payload, and the bridge may keep
sending only those exact frames. The test below freezes the bytes the bridge
writes on connect and on `set <mode>`, and it freezes the one status packet the
device itself answered with.
"""
import importlib.machinery
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, "..", "samsung-bridge")
loader = importlib.machinery.SourceFileLoader("samsung_bridge", PATH)
spec = importlib.util.spec_from_loader("samsung_bridge", loader)
bridge_module = importlib.util.module_from_spec(spec)
loader.exec_module(bridge_module)

STATUS_FRAME = bytes.fromhex(
  "fd2a00610b031212010111000000bf22010040014001030003660002001000000000110200010000400000993ddd"
)
STATUS_PAYLOAD = bytes.fromhex(
  "0b031212010111000000bf22010040014001030003660002001000000000110200010000400000"
)


class Session:
    def __init__(self):
        self.frames = []
        self.lines = []
        bridge_module.emit = self.lines.append
        loop = type("Loop", (), {"quit": lambda self: None})()
        self.bridge = bridge_module.Bridge(None, "84:5F:04:B5:D6:74", loop)
        self.bridge.write = self.frames.append
        self.bridge.fd = 1


class SamsungBridge(unittest.TestCase):
    def test_manager_info_frame(self):
        s = Session()
        s.bridge.send_manager_info()
        self.assertEqual([frame.hex() for frame in s.frames], [
            "fd061088010122da58dd",
        ])

    def test_status_packet_updates_mode_and_battery(self):
        s = Session()
        s.bridge.on_frame(STATUS_FRAME)
        self.assertEqual(s.lines, [{
            "modes": True,
            "mode": "anc",
            "available": ["off", "anc", "ambient"],
            "battery": {
                "left": 18,
                "right": 18,
                "case": 0,
                "charging": [],
            },
        }])

    def test_set_writes_the_observed_noise_control_frames(self):
        s = Session()
        for line in ("set off", "set anc", "set ambient", "set talkthru"):
            s.bridge.command(line)
        self.assertEqual([frame.hex() for frame in s.frames], [
            "fd04107800f081dd",
            "fd04107801d191dd",
            "fd04107802b2a1dd",
        ])
        self.assertEqual(s.lines, [])

    def test_parse_state_uses_the_observed_offsets(self):
        self.assertEqual(bridge_module.parse_state(STATUS_PAYLOAD), {
            "modes": True,
            "mode": "anc",
            "available": ["off", "anc", "ambient"],
            "battery": {
                "left": 18,
                "right": 18,
                "case": 0,
                "charging": [],
            },
        })


if __name__ == "__main__":
    unittest.main()
