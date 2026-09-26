"""Owner NC9 Pro replies plus explicitly synthetic faults. No radio in CI."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from tests import harness

bridge_module = harness.load_bridge('tozo-bridge')
B = bridge_module
ADDRESS = '94:4B:F8:C1:5F:98'
CASE = '41:42:B1:F6:F8:4F'
RX = {
    'off': '00 30 01 00 00', 'anc': '00 30 01 01 01',
    'ambient': '00 30 01 02 02', 'wind': '00 30 01 03 03',
    'leisure': '00 30 01 04 04', 'adaptive': '00 30 01 06 06',
    'buds': '00 02 02 64 64 c8', 'case': '01 02 01 64 64',
    'case_address': '00 20 06 41 42 b1 f6 f8 4f 71',
    'case_peer': '01 09 06 94 4b f8 c1 5f 98 8f',
    'event': '20 0d 02 01 03 04',
}


class Session(harness.Session):
    """Each sent string includes buds/case and the complete GATT value."""
    def __init__(self, address=ADDRESS):
        super().__init__(B)
        self.now = 0.0
        self.cases = []
        self.bridge = B.Bridge(address, 'TOZO NC9 Pro',
            lambda role, data: self.frames.append((role, data)),
            self.lines.append, lambda: self.now, self.cases.append)

    @property
    def sent(self):
        return [role + ' ' + data.hex(' ') for role, data in self.frames]

    def device(self, spec):
        if isinstance(spec, str):
            self.bridge.receive('buds', bytes.fromhex(spec))
        else:
            self.bridge.receive(spec['role'], bytes.fromhex(spec['wire']))

    def do_advance(self, seconds):
        target = self.now + seconds
        while self.now < target:
            self.now = min(target, round(self.now + 0.05, 6))
            self.bridge.tick()

    def do_ready(self):
        self.bridge.connected('buds')
        self.do_advance(.5)
        self.device(RX['anc'])


harness.pin_tests(globals(), 'tozo-bridge', Session)


class Protocol(unittest.TestCase):
    def ready(self):
        s = Session(); s.do_ready(); return s

    def test_literal_evidence_is_present_in_owner_capture(self):
        root = Path(__file__).parents[1]
        evidence = (root/'docs/captures/tozo-nc9-pro-live.txt').read_text() + (root/'docs/captures/tozo-nc9-pro-phone.txt').read_text()
        for frame in RX.values():
            self.assertIn(frame, evidence)
        for command in B.MODELS['TOZO NC9 Pro']['sets'].values():
            self.assertIn(command, evidence)

    def test_every_partial_damaged_or_combined_datagram_is_ignored_then_recovers(self):
        raw = bytes.fromhex(RX['ambient'])
        for split in range(1, len(raw)):
            s = self.ready()
            s.bridge.receive('buds', raw[:split]); s.bridge.receive('buds', raw[split:])
            self.assertEqual(s.bridge.mode, 'anc')
            s.bridge.receive('buds', raw)
            self.assertEqual(s.bridge.mode, 'ambient')
        for bad in (raw + raw, raw[:-1] + b'\xff', b'noise' + raw,
                    bytes.fromhex('00 30 01 05 05'), bytes.fromhex('00 30 00 00')):
            s = self.ready(); s.bridge.receive('buds', bad)
            self.assertEqual(s.bridge.mode, 'anc')
            s.bridge.receive('buds', raw)
            self.assertEqual(s.bridge.mode, 'ambient')

    def test_control_is_serialized_and_readback_is_scheduled_after_ack(self):
        s = self.ready(); before = list(s.lines)
        s.command('set ambient'); s.command('set wind'); s.do_advance(.2)
        self.assertEqual(s.sent[-1], 'buds 10 05 01 01 01')
        s.device('10 05 01 00 00'); s.do_advance(1)
        self.assertEqual(s.lines, before)
        self.assertEqual(s.sent[-1], 'buds 10 05 01 01 01')
        # A stale pre-control query must not release the next queued command.
        s.device(RX['anc']); self.assertEqual(s.bridge.pending, 'ambient')
        s.do_advance(.6)
        self.assertEqual(s.sent[-1], 'buds 00 30 00 00')
        s.device(RX['ambient']); s.do_advance(.2)
        self.assertEqual(s.lines[-1]['mode'], 'ambient')
        self.assertEqual(s.sent[-1], 'buds 10 07 01 01 01')

    def test_failed_or_echoed_ack_does_not_publish_requested_mode(self):
        s = self.ready(); s.command('set ambient'); s.do_advance(.2)
        before = list(s.lines)
        s.device('10 05 01 01 01')  # synthetic echo/error, not success
        self.assertEqual(s.lines, before)
        s.do_advance(2); self.assertEqual(s.sent[-1], 'buds 00 30 00 00')
        s.do_advance(8); self.assertEqual(s.exit_code, 1)

    def test_silence_disconnect_and_shutdown_use_real_scheduler(self):
        silent = Session(); silent.bridge.connected('buds'); silent.do_advance(9)
        self.assertEqual(silent.exit_code, 3)
        lost = self.ready(); lost.bridge.disconnected('buds')
        self.assertEqual(lost.exit_code, 1)
        stopped = self.ready(); stopped.command('set ambient'); stopped.bridge.finish(0)
        before = list(stopped.frames); stopped.do_advance(60)
        stopped.bridge.connected('buds'); stopped.command('set anc')
        self.assertEqual(stopped.frames, before); self.assertEqual(stopped.exit_code, 0)
        recovering = self.ready(); self.assertEqual(recovering.bridge.mode, 'anc')

    def test_unsolicited_event_schedules_readback_and_duplicates_do_not_emit(self):
        s = self.ready(); s.device(RX['event']); s.do_advance(1)
        self.assertEqual(s.bridge.mode, 'anc')
        s.do_advance(.6); self.assertEqual(s.sent[-1], 'buds 00 30 00 00')
        s.device(RX['wind']); count = len(s.lines); s.device(RX['wind'])
        self.assertEqual(len(s.lines), count); self.assertEqual(s.bridge.mode, 'wind')

    def test_unknown_commands_and_preinitialization_writes_are_inert(self):
        for s in (Session(), self.ready()):
            before = list(s.frames)
            for command in ('set talkthru', 'set bad', 'level high', 'voice on', 'latency on', ''):
                s.command(command)
            s.do_advance(.1); self.assertEqual(s.frames, before)
        s = Session(); s.command('set anc'); s.do_advance(1); self.assertEqual(s.frames, [])

    def test_case_requires_bidirectional_association_and_recovers_after_disconnect(self):
        s = self.ready(); s.device(RX['case_address'])
        self.assertEqual(s.cases, [CASE]); s.bridge.connected('case'); s.do_advance(.2)
        self.assertEqual(s.sent[-1], 'case 01 09 00 00')
        s.device({'role': 'case', 'wire': RX['case']})
        self.assertNotIn('case', s.bridge.battery)
        s.device({'role': 'case', 'wire': RX['case_peer']}); s.do_advance(.2)
        self.assertEqual(s.sent[-1], 'case 01 02 00 00')
        s.device({'role': 'case', 'wire': RX['case']})
        self.assertEqual(s.bridge.battery, {'case': 100, 'caseStale': False})
        s.bridge.disconnected('case'); self.assertTrue(s.bridge.battery['caseStale'])
        for _ in range(31):
            s.do_advance(2); s.device(RX['anc'])
        self.assertEqual(s.cases, [CASE, CASE])
        s.bridge.connected('case'); self.assertFalse(s.bridge.case_verified)
        s.device({'role': 'case', 'wire': RX['case_peer']})
        s.device({'role': 'case', 'wire': RX['case']})
        self.assertFalse(s.bridge.battery['caseStale'])

    def test_two_devices_do_not_share_case_battery_mode_or_timers(self):
        a = self.ready(); b = Session('AA:BB:CC:DD:EE:FF'); b.do_ready()
        for s in (a, b):
            s.device({'role': 'case', 'wire': RX['case_peer']})
            s.device({'role': 'case', 'wire': RX['case']})
        self.assertEqual(a.bridge.battery['case'], 100)
        self.assertNotIn('case', b.bridge.battery)
        a.device(RX['ambient']); self.assertEqual(b.bridge.mode, 'anc')
        a.bridge.finish(0); self.assertIsNone(b.exit_code)

    def test_battery_unknown_charging_and_boundaries_are_synthetic(self):
        s = self.ready(); s.device(RX['buds'])
        original = dict(s.bridge.battery)
        for raw in ('00 02 02 ff 64 63', '00 02 02 e4 64 48', '00 02 01 64 64'):
            s.device(raw); self.assertEqual(s.bridge.battery, original)
        # The owner has not captured a charging flag. No high-bit interpretation.
        self.assertNotIn('charging', s.bridge.battery)
        s.device('00 02 02 00 64 64')
        self.assertEqual(s.bridge.battery, {'left': 0, 'right': 100})

    def test_closed_stdout_and_failed_transport_stop_cleanly(self):
        s = self.ready(); s.bridge.output = Mock(side_effect=BrokenPipeError())
        s.device(RX['ambient']); self.assertEqual(s.exit_code, 0)
        s = self.ready(); s.bridge.send = Mock(side_effect=OSError('lost'))
        s.command('set ambient'); s.do_advance(.2); self.assertEqual(s.exit_code, 1)


class Transport(unittest.TestCase):
    def transport(self):
        t = B.BlueZ.__new__(B.BlueZ)
        t.closed = False; t.scanning = None; t.address = ADDRESS
        t.links = {}; t.stdin_buffer = b''; t.wire = Mock(); t.loop = Mock()
        t.core = B.Bridge(ADDRESS, 'TOZO NC9 Pro', t.send, Mock(), open_case=t.open_case)
        t.dbus = Mock(); t.dbus.DBusException = RuntimeError
        t.interface = Mock(); t.objects = Mock(return_value={})
        return t

    def test_shutdown_during_discovery_prevents_more_connects(self):
        t = self.transport(); t.core.finish(0)
        t.open('buds', ADDRESS); t.advance('buds', {})
        t.interface.assert_not_called(); self.assertFalse(t.tick())
        t.loop.quit.assert_called_once()

    def test_connect_failure_and_deadline_release_link(self):
        t = self.transport()
        t.links['buds'] = {'ready': False, 'deadline': 0, 'owned': False, 'path': '/buds'}
        t.tick(); self.assertEqual(t.core.exit_code, 1); self.assertEqual(t.links, {})

    def test_wrong_device_notifications_and_actual_disconnect_callbacks(self):
        t = self.transport(); t.links['buds'] = {'notify': '/buds/n', 'path': '/buds', 'ready': True, 'owned': False}
        t.changed('org.bluez.GattCharacteristic1', {'Value': bytes.fromhex(RX['anc'])}, [], path='/other/n')
        self.assertIsNone(t.core.mode)
        t.changed('org.bluez.GattCharacteristic1', {'Value': bytes.fromhex(RX['anc'])}, [], path='/buds/n')
        self.assertEqual(t.core.mode, 'anc')
        t.bearer_lost('reason', 'message', path='/buds'); self.assertEqual(t.core.exit_code, 1)

    def test_subscription_failure_and_late_success_are_cleaned_up(self):
        t = self.transport(); link={'notify':'/n', 'path':'/buds','ready':False,'owned':False}
        t.links['buds']=link; t.failed('buds',link,RuntimeError('failed'))
        self.assertEqual(t.core.exit_code,1)
        t.subscribed('buds',link)
        t.interface.return_value.StopNotify.assert_called_once()
        self.assertFalse(t.core.linked)

    def test_stdin_partial_lines_eof_and_read_error(self):
        t=self.transport();t.core.receive('buds',bytes.fromhex(RX['anc']))
        with patch.object(B.os,'read',side_effect=[b'set amb',b'ient\n',b'']):
            self.assertTrue(t.stdin(0,1)); self.assertIsNone(t.core.pending)
            self.assertTrue(t.stdin(0,1)); self.assertEqual(t.core.pending,'ambient')
            self.assertFalse(t.stdin(0,16)); self.assertEqual(t.core.exit_code,0)
        t=self.transport()
        with patch.object(B.os,'read',side_effect=OSError()):
            self.assertFalse(t.stdin(0,8));self.assertEqual(t.core.exit_code,0)

    def test_cleanup_disconnects_only_case_connections_owned_by_this_process(self):
        t=self.transport(); t.signal_match=Mock();t.disconnect_match=Mock()
        t.links={'buds':{'ready':True,'notify':'/buds/n','path':'/buds','owned':False},
                 'case':{'ready':True,'notify':'/case/n','path':'/case','owned':True}}
        t.close();t.close()
        self.assertEqual(t.interface.return_value.Disconnect.call_count,1)
        self.assertEqual(t.interface.return_value.StopNotify.call_count,2)

class AdditionalLifecycle(unittest.TestCase):
    def test_optional_case_silence_closes_only_case_then_retries(self):
        s=Session();s.do_ready();s.device(RX['case_address'])
        s.bridge.drop_case=Mock();s.bridge.connected('case')
        s.do_advance(9)
        s.bridge.drop_case.assert_called_once()
        self.assertIsNone(s.exit_code)
        self.assertFalse(s.bridge.case_verified)
        self.assertGreater(s.bridge.case_retry_at,s.now)

    def test_battery_and_mode_polls_send_only_observed_queries(self):
        s=Session();s.do_ready()
        for _ in range(20):
            s.do_advance(2);s.device(RX['anc'])
        self.assertEqual(set(s.sent), {'buds 00 30 00 00','buds 00 02 00 00','buds 00 20 00 00'})
        self.assertGreater(s.sent.count('buds 00 02 00 00'),1)

    def test_notifications_before_subscription_reply_are_retained(self):
        t=Transport().transport()
        link={'ready':False,'path':'/buds','notify':'/buds/n','owned':False,'early':[]}
        t.links['buds']=link
        t.changed('org.bluez.GattCharacteristic1',{'Value':bytes.fromhex(RX['anc'])},[],path='/buds/n')
        t.changed('org.bluez.GattCharacteristic1',{'Value':bytes.fromhex(RX['buds'])},[],path='/buds/n')
        self.assertIsNone(t.core.mode)
        t.subscribed('buds',link)
        self.assertEqual(t.core.mode,'anc')
        self.assertEqual(t.core.battery,{'left':100,'right':100})

    def test_existing_gatt_service_is_selected_by_uuid_and_device_path(self):
        t=Transport().transport()
        path='/org/bluez/hci1/dev_94_4B_F8_C1_5F_98'
        objects={path:{'org.bluez.Device1':{'Address':ADDRESS,'Connected':True}},
                 path+'/s':{'org.bluez.GattService1':{'UUID':B.SERVICE}},
                 path+'/s/n':{'org.bluez.GattCharacteristic1':{'UUID':B.NOTIFY,'Service':path+'/s'}},
                 path+'/s/w':{'org.bluez.GattCharacteristic1':{'UUID':B.WRITE,'Service':path+'/s'}},
                 '/other/s/n':{'org.bluez.GattCharacteristic1':{'UUID':B.NOTIFY,'Service':'/other/s'}}}
        t.objects.return_value=objects;t.open('buds',ADDRESS)
        self.assertEqual(t.links['buds']['notify'],path+'/s/n')
        self.assertEqual(t.links['buds']['write'],path+'/s/w')
        callback=t.interface.return_value.StartNotify.call_args.kwargs['reply_handler']
        callback();self.assertTrue(t.core.linked)
        self.assertEqual(list(t.core.outbox),[('buds',B.MODE_GET),('buds',B.BATTERY_GET),('buds',B.CASE_GET)])

    def test_connect_callback_error_is_transient_and_no_later_attempt_occurs(self):
        t=Transport().transport();path='/buds'
        t.objects.return_value={path:{'org.bluez.Device1':{'Address':ADDRESS,'Connected':False}}}
        t.open('buds',ADDRESS)
        callback=t.interface.return_value.Connect.call_args.kwargs['error_handler']
        callback(RuntimeError('refused'));self.assertEqual(t.core.exit_code,1)
        count=t.interface.call_count;t.open('buds',ADDRESS);t.tick()
        self.assertEqual(t.interface.call_count,count)

    def test_help_and_bad_arguments_do_not_access_bluetooth(self):
        with patch.object(B,'BlueZ') as radio,patch.object(B,'emit'),patch('builtins.print'):
            self.assertEqual(B.main(['--help']),0)
            self.assertEqual(B.main(['bad','TOZO NC9 Pro']),4)
            self.assertEqual(B.main([ADDRESS,'TOZO other']),4)
            radio.assert_not_called()
