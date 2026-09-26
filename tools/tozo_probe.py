#!/usr/bin/env python3
"""Capture the NC9 Pro's own BLE replies, optionally cycle and restore six modes.

Run outside the installed plugin. Release its bridge using useModeControl first.
  tools/tozo_probe.py ADDRESS
  tools/tozo_probe.py ADDRESS --cycle --listen 10
The case must be nearby to read its battery. Each RX is timestamped at receipt.
"""
import argparse
import datetime
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import signal
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader('tozo_probe_bridge', str(ROOT / 'tozo-bridge'))
spec = importlib.util.spec_from_loader(loader.name, loader)
bridge = importlib.util.module_from_spec(spec)
loader.exec_module(bridge)


def log(text):
    print(datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='milliseconds'), text, flush=True)


def cycle(driver, modes, report=log):
    """Read initial state before writes, and verify restoration even on failure."""
    initial = driver.read_mode()
    if initial not in modes:
        raise RuntimeError('Initial mode unknown; refusing control writes')
    report('INITIAL ' + initial)
    changed = False
    try:
        for mode in modes:
            changed = True  # even a failed send may have reached the device
            reported = driver.set_and_read(mode)
            report('RESULT requested=' + mode + ' reported=' + str(reported))
            if reported != mode:
                raise RuntimeError('Device did not report requested mode')
    finally:
        if changed:
            try:
                restored = driver.set_and_read(initial)
            except BaseException as error:
                report("RESTORATION FAILED " + repr(error))
                raise
            if restored != initial:
                report('RESTORATION FAILED expected=' + initial + ' reported=' + str(restored))
                raise RuntimeError('Restoration was not confirmed')
            report('RESTORED ' + restored)


class Driver:
    def __init__(self, address):
        self.mode_revision = 0
        self.transport = bridge.BlueZ(address, 'TOZO NC9 Pro',
                                      lambda state: log('STATE ' + json.dumps(state)), self.wire)
        try:
            self.transport.open('buds', address)
        except BaseException:
            self.transport.close()
            raise

    def wire(self, direction, role, raw):
        log(direction + ' ' + role + ' BLE GATT ' + raw.hex(' '))
        parsed = bridge.packet(raw)
        if direction == 'RX' and role == 'buds' and parsed and parsed[:2] == (0, 0x30):
            self.mode_revision += 1

    def wait(self, predicate, timeout=30):
        end = time.monotonic() + timeout
        context = self.transport.glib.MainContext.default()
        while time.monotonic() < end:
            while context.pending():
                context.iteration(False)
            if self.transport.core.exit_code is not None:
                raise RuntimeError('Bridge stopped with exit ' + str(self.transport.core.exit_code))
            self.transport.tick()
            if predicate():
                return
            time.sleep(.05)
        raise TimeoutError('Device response timed out')

    def read_mode(self):
        self.wait(lambda: self.transport.core.mode is not None)
        return self.transport.core.mode

    def set_and_read(self, mode):
        previous = self.mode_revision
        self.transport.core.command('set ' + mode)
        self.wait(lambda: self.mode_revision > previous
                  and self.transport.core.pending is None
                  and not self.transport.core.commands, timeout=15)
        return self.transport.core.mode

    def listen(self, seconds):
        end = time.monotonic() + seconds
        self.wait(lambda: time.monotonic() >= end, timeout=seconds + 1)

    def close(self):
        self.transport.core.finish(0)
        self.transport.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('address')
    parser.add_argument('--cycle', action='store_true')
    parser.add_argument('--listen', type=float, default=8)
    args = parser.parse_args()
    if not bridge.ADDRESS.fullmatch(args.address) or not 0 <= args.listen <= 600:
        parser.error('valid address and listen duration 0..600 required')
    driver = None
    def stop(*_):
        raise KeyboardInterrupt()
    signal.signal(signal.SIGTERM, stop)
    try:
        driver = Driver(args.address)
        log('INITIAL ' + driver.read_mode())
        if args.cycle:
            cycle(driver, bridge.MODELS['TOZO NC9 Pro']['sets'])
        driver.listen(args.listen)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        log('FAILED ' + repr(error))
        return 1
    finally:
        if driver:
            driver.close()


if __name__ == '__main__':
    sys.exit(main())
