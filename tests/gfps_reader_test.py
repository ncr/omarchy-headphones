"""Fast Pair reference sessions: actual owner frames plus labelled fault cases.

Real nonblocking pipes exercise partial reads, glued messages and EOF. No
Bluetooth, D-Bus, radio, wall-clock timers or outside processes are used.
"""
import os
import unittest
from unittest.mock import patch

from tests import canonical, harness

reader = harness.load_bridge('gfps-reader')


class FastPair(unittest.TestCase):
    def setUp(self):
        self.lines = []
        self.glib = harness.FakeGLib()
        for name, value in [('emit', self.lines.append), ('GLib', self.glib)]:
            p = patch.object(reader, name, value)
            p.start()
            self.addCleanup(p.stop)

    def stream(self, brand):
        incoming, outgoing = os.pipe()
        state = reader.State(canonical.MODELS[brand]['address'])
        r = reader.Reader(incoming, state)
        self.addCleanup(r.close, 'test complete')
        self.addCleanup(os.close, outgoing)
        return r, outgoing

    def send(self, r, fd, data):
        os.write(fd, data)
        self.assertTrue(r.on_io(r.fd, self.glib.IO_IN))

    def test_owner_battery_frames_name_only_the_parts_that_exist(self):
        for brand in ('sony', 'jbl'):
            with self.subTest(brand=brand):
                r, fd = self.stream(brand)
                self.send(r, fd, canonical.frame(brand, 'gfps', 'battery'))
                line = self.lines[-1]
                self.assertEqual(line['address'], canonical.MODELS[brand]['address'])
                self.assertTrue(line['stream'])
                if brand == 'sony':
                    self.assertEqual((line['single'], line['battery'], line['left'], line['right'], line['case']),
                                     (True, 39, -1, -1, -1))
                else:
                    self.assertEqual((line['single'], line['battery'], line['left'], line['right'], line['case']),
                                     (False, -1, 70, 80, 67))
                self.assertFalse(any(line[k] for k in ('batteryCharging', 'leftCharging', 'rightCharging', 'caseCharging')))

    def test_every_split_point_waits_for_the_complete_recorded_frame(self):
        for brand in ('sony', 'jbl'):
            frame = canonical.frame(brand, 'gfps', 'battery')
            for split in range(1, len(frame)):
                with self.subTest(brand=brand, split=split):
                    r, fd = self.stream(brand)
                    before = len(self.lines)
                    self.send(r, fd, frame[:split])
                    self.assertEqual(len(self.lines), before)
                    self.send(r, fd, frame[split:])
                    self.assertEqual(len(self.lines), before + 1)
                    self.assertEqual(r.buffer, b'')

    def test_glued_model_ble_and_battery_frames_keep_all_fields(self):
        for brand in ('sony', 'jbl'):
            r, fd = self.stream(brand)
            self.send(r, fd, b''.join(canonical.frame(brand, 'gfps', key) for key in ('model', 'ble', 'battery')))
            line = self.lines[-1]
            self.assertEqual(line['modelId'], 'f42ffc' if brand == 'sony' else '71f20a')
            self.assertEqual(line['bleAddress'], 'CA:D0:19:9C:8C:D3' if brand == 'sony' else '64:3B:E9:EB:E3:0B')
            self.assertEqual(r.buffer, b'')

    def test_one_device_error_or_reading_cannot_overwrite_the_other(self):
        sony, sf = self.stream('sony')
        jbl, jf = self.stream('jbl')
        self.send(sony, sf, canonical.frame('sony', 'gfps', 'battery'))
        self.send(jbl, jf, canonical.frame('jbl', 'gfps', 'battery'))
        before = dict(jbl.state.values)
        sony.close('link lost')
        self.assertEqual(jbl.state.values, before)
        self.assertTrue(jbl.alive)
        self.assertEqual(self.lines[-1]['address'], canonical.MODELS['sony']['address'])

    def test_duplicate_is_quiet_but_refresh_reannounces_identical_battery(self):
        r, fd = self.stream('jbl')
        battery = canonical.frame('jbl', 'gfps', 'battery')
        self.send(r, fd, battery)
        self.send(r, fd, battery)
        self.assertEqual(len(self.lines), 1)
        r.state.announce_again()
        self.send(r, fd, canonical.frame('jbl', 'gfps', 'model'))
        self.assertTrue(r.state.repeat)
        self.send(r, fd, battery)
        self.assertEqual(len(self.lines), 3)
        self.assertFalse(r.state.repeat)
        self.send(r, fd, battery)
        self.assertEqual(len(self.lines), 3)

    def test_reconnected_stream_clears_error_and_reuses_retained_reading(self):
        r, fd = self.stream('sony')
        self.send(r, fd, canonical.frame('sony', 'gfps', 'battery'))
        r.state.stream_down('lost')
        r.state.stream_down('lost')
        self.assertEqual(len(self.lines), 2)
        r.state.stream_up()
        r.state.announce_again()
        self.send(r, fd, canonical.frame('sony', 'gfps', 'battery'))
        self.assertEqual(len(self.lines), 3)
        self.assertTrue(self.lines[-1]['stream'])
        self.assertNotIn('error', self.lines[-1])
        self.assertEqual(self.lines[-1]['battery'], 39)

    def test_hangup_reads_final_battery_before_closing_once(self):
        r, fd = self.stream('jbl')
        closed = []
        r.on_close = lambda: closed.append(True)
        os.write(fd, canonical.frame('jbl', 'gfps', 'battery'))
        self.assertFalse(r.on_io(r.fd, self.glib.IO_IN | self.glib.IO_HUP))
        self.assertEqual(self.lines[0]['case'], 67)
        self.assertFalse(self.lines[1]['stream'])
        self.assertFalse(r.alive)
        self.assertIsNone(r.watch)
        r.close('again')
        self.assertEqual(closed, [True])
        self.assertEqual(len(self.lines), 2)

    def test_truncated_message_at_eof_never_becomes_a_reading(self):
        # Synthetic damage: remove the last byte from the owner's frame.
        r, fd = self.stream('sony')
        os.write(fd, canonical.frame('sony', 'gfps', 'battery')[:-1])
        r.on_io(r.fd, self.glib.IO_HUP)
        self.assertEqual(len(self.lines), 1)
        self.assertFalse(self.lines[0]['stream'])
        self.assertNotIn('battery', self.lines[0])

    def test_synthetic_unknown_groups_and_invalid_lengths_are_ignored(self):
        r, fd = self.stream('jbl')
        for data in ('04 03 00 01 64', '03 03 00 00', '03 03 00 02 64 64',
                     '03 03 00 04 64 64 64 64', '03 02 00 05 01 02 03 04 05'):
            self.send(r, fd, bytes.fromhex(data))
        self.assertEqual(self.lines, [])
        self.send(r, fd, canonical.frame('jbl', 'gfps', 'battery'))
        self.assertEqual(self.lines[-1]['left'], 70)

    def test_a_byte_above_100_is_not_a_level(self):
        # 0xFE is the only battery byte a Redmi Buds 5 sent in one session
        # (docs/captures/redmi-buds-5-fastpair.txt); the spec's levels are 0-100
        # and 0x7F is unknown. The neighbours around the boundary are synthetic.
        for byte in (0xfe, 0x7e, 101, 0xe5):
            self.assertEqual(reader.component(byte), (-1, False), hex(byte))
        self.assertEqual(reader.component(100), (100, False))
        self.assertEqual(reader.component(0x80 | 100), (100, True))
        self.assertEqual(reader.component(0x80 | 101), (-1, False))

    def test_a_single_battery_byte_above_100_is_unreported_not_126_percent(self):
        r, fd = self.stream('jbl')
        self.send(r, fd, bytes.fromhex('03 03 00 01 fe'))
        last = self.lines[-1]
        self.assertTrue(last['single'])
        self.assertEqual((last['battery'], last['batteryCharging']), (-1, False))

    def test_the_two_byte_battery_a_redmi_buds_5_sent_is_not_read(self):
        # Real frame from docs/captures/redmi-buds-5-fastpair.txt: `94 94`, which
        # would read as 20% charging on both buds while the app showed 65 / 65.
        # The reader reads one byte or three, so it says nothing.
        r, fd = self.stream('jbl')
        before = list(self.lines)
        self.send(r, fd, bytes.fromhex('03 03 00 02 94 94'))
        self.assertEqual(self.lines, before)

    def test_synthetic_charging_and_unknown_components(self):
        # Protocol boundary inputs; not claims about what these owners captured.
        for byte, expected in [(0, (0, False)), (100, (100, False)),
                               (0x80, (0, True)), (0xe4, (100, True)),
                               (0x7f, (-1, False)), (0xff, (-1, False))]:
            self.assertEqual(reader.component(byte), expected)
        r, fd = self.stream('jbl')
        self.send(r, fd, bytes.fromhex('03 03 00 03 ff e4 7f'))
        self.assertEqual((self.lines[-1]['left'], self.lines[-1]['right'], self.lines[-1]['case']), (-1, 100, -1))
        self.assertTrue(self.lines[-1]['rightCharging'])


class FollowerLifecycle(unittest.TestCase):
    def setUp(self):
        p = patch.object(reader, 'GLib', harness.FakeGLib())
        p.start(); self.addCleanup(p.stop)
        p = patch.object(reader, 'emit', lambda _: None)
        p.start(); self.addCleanup(p.stop)
        self.f = reader.Follower(None, canonical.MODELS['sony']['address'])
        self.calls = []
        calls = self.calls
        class Device:
            def ConnectProfile(self, uuid, **kwargs): calls.append(('connect', uuid, kwargs))
            def DisconnectProfile(self, uuid, **kwargs): calls.append(('disconnect', uuid, kwargs))
        self.f.device = Device()

    def test_retry_waits_for_disconnect_reply_before_connecting(self):
        self.f.supervise()
        self.assertEqual([x[0] for x in self.calls], ['connect'])
        self.f.supervise()
        self.assertEqual(len(self.calls), 1)
        self.f.calling = False
        self.f.supervise()
        self.assertEqual([x[0] for x in self.calls], ['connect', 'disconnect'])
        self.calls[-1][2]['reply_handler']()
        self.assertEqual([x[0] for x in self.calls], ['connect', 'disconnect', 'connect'])

    def test_refresh_is_quiet_preserves_reading_and_cycles_only_its_profile(self):
        self.f.state.values['battery'] = 39
        self.f.refresh()
        self.assertTrue(self.f.state.repeat)
        self.assertEqual(self.f.state.values['battery'], 39)
        self.assertFalse(self.f.state.quiet)
        self.assertEqual([x[0] for x in self.calls], ['disconnect'])
        self.calls[-1][2]['error_handler'](None)
        self.assertEqual([x[0] for x in self.calls], ['disconnect', 'connect'])

    def test_unfollowed_device_cannot_be_reconnected_by_old_timers(self):
        self.f.drop()
        before = list(self.calls)
        self.f.supervise(); self.f.refresh()
        self.assertEqual(self.calls, before)
        self.assertTrue(self.f.state.quiet)
