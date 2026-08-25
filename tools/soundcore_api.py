#!/usr/bin/env python3
"""Soundcore Protocol Client Library for Linux (BlueZ / RFCOMM)

Supports Soundcore Space 2, Space One, Space Q45, Life Q30/Q35, Liberty 4/NC, AeroClip, etc.
"""
import ctypes
import os
import re
import signal
import struct
import sys
import time
from typing import Callable, Optional, Dict, List, Tuple

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

SOUNDCORE_UUID_PREFIX = "0cf12d31-fac3-4553-bd80-d6832e7"
DEFAULT_UUID = "0cf12d31-fac3-4553-bd80-d6832e700000"

OUTBOUND_HDR = bytes([0x08, 0xEE, 0x00, 0x00, 0x00])

CMD_STATE_UPDATE = (0x01, 0x01)
CMD_BATTERY_LEVEL = (0x01, 0x03)
CMD_BATTERY_CHARGING = (0x01, 0x04)
CMD_SERIAL_FIRMWARE = (0x01, 0x05)
CMD_SET_EQ = (0x02, 0x81)
CMD_SOUND_MODES_NOTIFY = (0x06, 0x01)
CMD_SOUND_MODES_SET = (0x06, 0x81)
CMD_SET_AUTO_POWER_OFF = (0x01, 0x83)

PRESETS: Dict[str, Tuple[int, List[float]]] = {
    "Soundcore Signature": (0, [0.0] * 10),
    "Acoustic":            (1, [4.0, 1.0, 2.0, 2.0, 4.0, 4.0, 4.0, 2.0, 2.0, 2.0]),
    "Bass Booster":        (2, [4.0, 3.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
    "Bass Reducer":        (3, [-4.0, -3.0, -1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
    "Classical":           (4, [3.0, 3.0, -2.0, -2.0, 0.0, 2.0, 3.0, 4.0, 3.0, 2.0]),
    "Podcast":             (5, [-3.0, 2.0, 4.0, 4.0, 3.0, 2.0, 0.0, -2.0, -2.0, -2.0]),
    "Dance":               (6, [2.0, -3.0, -1.0, 1.0, 2.0, 2.0, 1.0, -3.0, -2.0, 1.0]),
    "Deep":                (7, [2.0, 1.0, 3.0, 3.0, 2.0, -2.0, -4.0, -5.0, -4.0, -2.0]),
    "Electronic":          (8, [3.0, 2.0, -2.0, 2.0, 1.0, 2.0, 3.0, 3.0, 2.0, 2.0]),
    "Flat":                (9, [-2.0, -2.0, -1.0, 0.0, 0.0, 0.0, -2.0, -2.0, -2.0, -2.0]),
    "Hip-Hop":             (10, [2.0, 3.0, -1.0, -1.0, 2.0, -1.0, 2.0, 3.0, 2.0, 1.0]),
    "Jazz":                (11, [2.0, 2.0, -2.0, -2.0, 0.0, 2.0, 3.0, 4.0, 3.0, 2.0]),
    "Latin":               (12, [0.0, 0.0, -2.0, -2.0, -2.0, 0.0, 3.0, 5.0, 4.0, 2.0]),
    "Lounge":              (13, [-1.0, 2.0, 4.0, 3.0, 0.0, -2.0, 2.0, 1.0, 0.0, 0.0]),
    "Piano":               (14, [0.0, 3.0, 3.0, 2.0, 4.0, 5.0, 3.0, 4.0, 3.0, 2.0]),
    "Pop":                 (15, [-1.0, 1.0, 3.0, 3.0, 1.0, -1.0, -2.0, -3.0, -2.0, 0.0]),
    "R&B":                 (16, [5.0, 2.0, -2.0, -2.0, 2.0, 3.0, 3.0, 4.0, 3.0, 2.0]),
    "Rock":                (17, [3.0, 2.0, -1.0, -1.0, 1.0, 3.0, 3.0, 3.0, 2.0, 2.0]),
    "Small Speakers":      (18, [4.0, 3.0, 1.0, 0.0, -2.0, -3.0, -4.0, -4.0, -3.0, -2.0]),
    "Spoken Word":         (19, [-3.0, -2.0, 1.0, 2.0, 2.0, 1.0, 0.0, -3.0, -2.0, -1.0]),
    "Treble Booster":      (20, [-2.0, -2.0, -2.0, -1.0, 1.0, 2.0, 2.0, 4.0, 5.0, 5.0]),
    "Treble Reducer":      (21, [0.0, 0.0, 0.0, 0.0, -1.0, -2.0, -3.0, -5.0, -5.0, -5.0]),
}

EQ_FREQUENCIES_10 = ["100 Hz", "200 Hz", "400 Hz", "800 Hz", "1.6 kHz", "3.2 kHz", "4.8 kHz", "6.4 kHz", "9.6 kHz", "12.8 kHz"]


def calc_checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def make_packet(cmd: tuple[int, int], body: bytes = b"") -> bytes:
    total_len = 5 + 2 + 2 + len(body) + 1
    raw = OUTBOUND_HDR + bytes([cmd[0], cmd[1], total_len & 0xFF, (total_len >> 8) & 0xFF]) + body
    return raw + bytes([calc_checksum(raw)])


def find_soundcore_devices() -> List[Dict[str, str]]:
    dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
    bus = dbus.SystemBus()
    objects = dbus.Interface(bus.get_object("org.bluez", "/"),
                             "org.freedesktop.DBus.ObjectManager").GetManagedObjects()
    devices = []
    for path, ifaces in objects.items():
        dev = ifaces.get("org.bluez.Device1")
        if not dev:
            continue
        address = str(dev.get("Address", ""))
        name = str(dev.get("Name", dev.get("Alias", address)))
        uuids = [str(u).lower() for u in dev.get("UUIDs", [])]
        connected = bool(dev.get("Connected", False))
        
        target_uuid = None
        for u in uuids:
            if u.startswith(SOUNDCORE_UUID_PREFIX):
                target_uuid = u
                break
                
        is_sc = target_uuid is not None or "soundcore" in name.lower() or "anker" in name.lower()
        if is_sc:
            devices.append({
                "path": str(path),
                "address": address,
                "name": name,
                "uuid": target_uuid or DEFAULT_UUID,
                "connected": connected,
            })
    return devices


class SoundcoreDevice:
    def __init__(self, address: str, target_uuid: Optional[str] = None):
        self.address = address.upper()
        self.target_uuid = target_uuid or DEFAULT_UUID
        self.fd: Optional[int] = None
        self.buffer = bytearray()
        
        self.connected = False
        self.battery_level: int = -1
        self.battery_charging: bool = False
        self.firmware: str = ""
        self.serial: str = ""
        
        self.mode: str = "anc"  # "anc", "ambient", "off"
        self.anc_level: int = 1  # 1..5
        self.anc_adaptive: bool = False
        self.ambient_level: int = 1  # 1..5
        self.wind_noise: bool = False
        self.sound_mode_params = [0x00, 0x1F, 0xFF, 0x00, 0x00, 0x01]
        
        self.current_preset: str = "Soundcore Signature"
        self.eq_bands: List[float] = [0.0] * 10
        
        self.on_state_change: Optional[Callable[[], None]] = None
        self.bus = None
        self.manager = None
        self.profile = None
        self.profile_path = f"/io/github/ncr/omaphones/sc_lib_{int(time.time()*1000)%100000}"

    def connect_sync(self, timeout_sec: float = 6.0) -> bool:
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        dev_info = None
        for d in find_soundcore_devices():
            if d["address"].upper() == self.address:
                dev_info = d
                break
        if not dev_info:
            return False
            
        self.target_uuid = dev_info["uuid"]
        loop = GLib.MainLoop()
        success = False
        
        device_obj = self
        class Profile(dbus.service.Object):
            @dbus.service.method("org.bluez.Profile1", in_signature="", out_signature="")
            def Release(self):
                pass

            @dbus.service.method("org.bluez.Profile1", in_signature="oha{sv}", out_signature="")
            def NewConnection(self, _path, fd, _properties):
                nonlocal success
                device_obj.fd = fd.take()
                device_obj.connected = True
                success = True
                GLib.io_add_watch(device_obj.fd, GLib.PRIORITY_DEFAULT,
                                  GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR, device_obj._on_io)
                device_obj._send(make_packet(CMD_STATE_UPDATE))
                GLib.timeout_add(300, lambda: (loop.quit(), False)[1])

            @dbus.service.method("org.bluez.Profile1", in_signature="o", out_signature="")
            def RequestDisconnection(self, _path):
                device_obj.connected = False

        self.profile = Profile(self.bus, self.profile_path)
        self.manager = dbus.Interface(self.bus.get_object("org.bluez", "/org/bluez"), "org.bluez.ProfileManager1")
        try:
            self.manager.RegisterProfile(self.profile_path, self.target_uuid, {
                "Name": "Soundcore Lib",
                "Role": "client",
                "Channel": dbus.UInt16(0),
                "RequireAuthentication": dbus.Boolean(False),
                "RequireAuthorization": dbus.Boolean(False),
                "AutoConnect": dbus.Boolean(False),
            })
        except dbus.DBusException:
            pass

        dev = dbus.Interface(self.bus.get_object("org.bluez", dev_info["path"]), "org.bluez.Device1")
        dev.ConnectProfile(self.target_uuid, reply_handler=lambda: None, error_handler=lambda e: None, timeout=int(timeout_sec))
        
        GLib.timeout_add(int(timeout_sec * 1000), lambda: (loop.quit(), False)[1])
        loop.run()
        return success

    def disconnect(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        self.connected = False
        if self.manager and self.profile_path:
            try:
                self.manager.UnregisterProfile(self.profile_path)
            except Exception:
                pass

    def _send(self, data: bytes):
        if self.fd is not None:
            try:
                os.write(self.fd, data)
            except OSError:
                self.connected = False

    def _on_io(self, _fd, condition):
        if condition & (GLib.IO_HUP | GLib.IO_ERR):
            self.connected = False
            return False
        try:
            data = os.read(self.fd, 4096)
        except OSError:
            self.connected = False
            return False
        if not data:
            self.connected = False
            return False
        self.buffer += data
        self._parse_buffer()
        return True

    def _parse_buffer(self):
        while len(self.buffer) >= 9:
            if not (self.buffer[0] == 0x09 and self.buffer[1] == 0xFF):
                idx = self.buffer.find(b"\x09\xff")
                if idx == -1:
                    self.buffer = bytearray()
                    break
                self.buffer = self.buffer[idx:]
                if len(self.buffer) < 9:
                    break
            cmd = (self.buffer[5], self.buffer[6])
            total_len = self.buffer[7] | (self.buffer[8] << 8)
            if len(self.buffer) < total_len:
                break
            packet = bytes(self.buffer[:total_len])
            self.buffer = self.buffer[total_len:]
            if calc_checksum(packet[:-1]) != packet[-1]:
                continue
            body = packet[9:-1]
            self._handle_packet(cmd, body)

    def _handle_packet(self, cmd: tuple[int, int], body: bytes):
        if cmd == CMD_STATE_UPDATE:
            if len(body) >= 2:
                self.battery_level = body[0]
                self.battery_charging = bool(body[1])
            if len(body) >= 7:
                self.firmware = body[2:7].decode("utf-8", "replace")
            if len(body) >= 23:
                self.serial = body[7:23].decode("utf-8", "replace")
            # EQ bands
            if len(body) >= 35:
                raw_eq = body[25:35]
                self.eq_bands = [(b - 120) / 10.0 for b in raw_eq]
            # Sound modes
            if len(body) >= 77:
                self.sound_mode_params = list(body[71:77])
                mode_byte = body[71]
                self.mode = {0: "anc", 1: "ambient", 2: "off"}.get(mode_byte, "anc")
                self.anc_level = max(1, min(5, (body[72] >> 4) & 0x0F))
                self.anc_adaptive = (body[74] == 1)
                self.wind_noise = bool(body[75])
                self.ambient_level = max(1, min(5, body[76]))
            if self.on_state_change:
                self.on_state_change()

        elif cmd == CMD_SOUND_MODES_NOTIFY:
            if len(body) >= 1:
                mode_byte = body[0]
                self.mode = {0: "anc", 1: "ambient", 2: "off"}.get(mode_byte, "anc")
                if len(body) >= 6:
                    self.sound_mode_params = list(body[:6])
                    self.anc_level = max(1, min(5, (body[1] >> 4) & 0x0F))
                    self.anc_adaptive = (body[3] == 1)
                    self.wind_noise = bool(body[4])
                    self.ambient_level = max(1, min(5, body[5]))
                if self.on_state_change:
                    self.on_state_change()

    def set_listening_mode(self, mode: str, level: Optional[int] = None, wind: Optional[bool] = None, adaptive: Optional[bool] = None):
        mode_val = {"anc": 0x00, "ambient": 0x01, "off": 0x02}.get(mode.lower(), 0x00)
        body = list(self.sound_mode_params)
        body[0] = mode_val
        if level is not None:
            if mode_val == 0x00:  # ANC level
                body[1] = ((level & 0x0F) << 4) | (body[1] & 0x0F)
            elif mode_val == 0x01:  # Ambient level
                body[5] = max(1, min(5, level))
        if wind is not None:
            body[4] = 1 if wind else 0
        if adaptive is not None:
            body[3] = 1 if adaptive else 0
        self.sound_mode_params = body
        self._send(make_packet(CMD_SOUND_MODES_SET, bytes(body)))
        self.mode = mode.lower()

    def set_preset_eq(self, preset_name: str):
        if preset_name not in PRESETS:
            return
        preset_id, default_bands = PRESETS[preset_name]
        band_bytes = [max(60, min(180, int(round(120 + g * 10)))) for g in default_bands]
        body = bytes([preset_id & 0xFF, (preset_id >> 8) & 0xFF]) + bytes(band_bytes)
        self._send(make_packet(CMD_SET_EQ, body))
        self.current_preset = preset_name
        self.eq_bands = list(default_bands)

    def set_custom_eq(self, bands_db: List[float]):
        band_bytes = [max(60, min(180, int(round(120 + g * 10)))) for g in bands_db]
        body = bytes([0xFE, 0xFE]) + bytes(band_bytes)
        self._send(make_packet(CMD_SET_EQ, body))
        self.current_preset = "Custom"
        self.eq_bands = list(bands_db)
