from __future__ import annotations

import socket
import struct
import threading
import time

import pytest

from app.openrgb import (
    MAGIC,
    REQUEST_CONTROLLER_COUNT,
    REQUEST_CONTROLLER_DATA,
    REQUEST_PROTOCOL_VERSION,
    SET_CLIENT_NAME,
    SET_CUSTOM_MODE,
    UPDATE_ZONE_LEDS,
    OpenRGBClient,
    OpenRGBProtocolError,
    build_zone_payload,
    parse_device_payload,
)


def pack_string(value: str) -> bytes:
    raw = value.encode("utf-8") + b"\x00"
    return struct.pack("<H", len(raw)) + raw


def build_device_payload(protocol: int = 4, mode_name: str = "Direct") -> bytes:
    body = struct.pack("<i", 1)  # DRAM
    body += pack_string("Aura Test RAM")
    body += pack_string("Aura Labs")
    body += pack_string("Test DIMM")
    body += pack_string("1.0")
    body += pack_string("SN-123")
    body += pack_string("I2C: 0x50")
    body += struct.pack("<Hi", 1, 0)  # one mode, active 0

    mode = pack_string(mode_name)
    mode += struct.pack("<iI", 0, 0)  # mode value, flags
    mode += struct.pack("<II", 0, 0)  # speed min/max
    mode += struct.pack("<II", 0, 100)  # brightness min/max
    mode += struct.pack("<II", 0, 0)  # colours min/max
    mode += struct.pack("<I", 0)  # speed
    mode += struct.pack("<I", 100)  # brightness
    mode += struct.pack("<I", 0)  # direction
    mode += struct.pack("<I", 1)  # per-LED colour mode
    mode += struct.pack("<H", 0)  # mode colours
    body += mode

    body += struct.pack("<H", 1)  # one zone
    body += pack_string("RAM strip")
    body += struct.pack("<iIII", 1, 0, 8, 8)  # linear, min, max, count
    body += struct.pack("<H", 0)  # no matrix map
    body += struct.pack("<H", 0)  # no segments (protocol 4)
    body += struct.pack("<H", 8)  # eight LEDs
    for index in range(8):
        body += pack_string(f"LED {index}")
        body += struct.pack("<I", index)
    body += struct.pack("<H", 8)  # eight current colours
    for index in range(8):
        body += struct.pack("<BBBB", index * 10, 0, 0, 0)
    return struct.pack("<I", len(body) + 4) + body


def test_parse_device_payload() -> None:
    payload = build_device_payload()
    device = parse_device_payload(payload, 4)
    assert device.name == "Aura Test RAM"
    assert device.vendor == "Aura Labs"
    assert device.serial == "SN-123"
    assert device.key.startswith("dev-")
    assert device.zones[0].led_count == 8
    assert device.zones[0].name == "RAM strip"
    assert device.zones[0].led_names[0] == "LED 0"
    assert device.zones[0].led_names[-1] == "LED 7"


def test_parse_rejects_truncated_payload() -> None:
    with pytest.raises(OpenRGBProtocolError):
        parse_device_payload(b"\x04\x00\x00\x00", 4)


def test_zone_payload_shape() -> None:
    payload = build_zone_payload(2, [(255, 0, 0), (0, 255, 0)])
    size = struct.unpack("<I", payload[:4])[0]
    assert size == len(payload)
    zone_index, count = struct.unpack("<IH", payload[4:10])
    assert zone_index == 2
    assert count == 2
    assert payload[10:14] == bytes((255, 0, 0, 0))


class FakeOpenRGBServer(threading.Thread):
    def __init__(self, payload: bytes) -> None:
        super().__init__(daemon=True)
        self.payload = payload
        self.received: list[tuple[int, int, bytes]] = []
        self.ready = threading.Event()
        self.port = 0
        self._halt = threading.Event()
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self.port = self._sock.getsockname()[1]
        self._sock.listen(1)
        self._sock.settimeout(0.2)

    def stop(self) -> None:
        self._halt.set()
        try:
            self._sock.close()
        except OSError:
            pass

    def send(self, device: int, packet_id: int, payload: bytes) -> None:
        conn = self.conn
        conn.sendall(struct.pack("<4sIII", MAGIC, device, packet_id, len(payload)) + payload)

    def run(self) -> None:
        self.ready.set()
        try:
            conn, _ = self._sock.accept()
        except OSError:
            return
        self.conn = conn
        conn.settimeout(5)
        try:
            while not self._halt.is_set():
                header = self._recv_exact(16)
                if header is None:
                    break
                magic, device, packet_id, size = struct.unpack("<4sIII", header)
                assert magic == MAGIC
                body = self._recv_exact(size) if size else b""
                self.received.append((device, packet_id, body))
                if packet_id == REQUEST_PROTOCOL_VERSION:
                    self.send(0, REQUEST_PROTOCOL_VERSION, struct.pack("<I", 4))
                elif packet_id == REQUEST_CONTROLLER_COUNT:
                    self.send(0, REQUEST_CONTROLLER_COUNT, struct.pack("<I", 1))
                elif packet_id == REQUEST_CONTROLLER_DATA:
                    self.send(device, REQUEST_CONTROLLER_DATA, self.payload)
        finally:
            try:
                conn.close()
            except OSError:
                pass

    def _recv_exact(self, size: int) -> bytes | None:
        data = b""
        while len(data) < size:
            try:
                chunk = self.conn.recv(size - len(data))
            except OSError:
                return None
            if not chunk:
                return None
            data += chunk
        return data


def test_client_discovers_and_writes_zone_colours() -> None:
    server = FakeOpenRGBServer(build_device_payload())
    server.start()
    client = OpenRGBClient("127.0.0.1", server.port, "AuraSync test")
    try:
        devices = client.discover()
        assert len(devices) == 1
        assert devices[0].name == "Aura Test RAM"
        client.set_zone_colours(0, 0, [(10, 20, 30)] * 8)
        deadline = time.monotonic() + 3
        write_packet: tuple[int, int, bytes] | None = None
        while time.monotonic() < deadline and write_packet is None:
            write_packet = next(
                (packet for packet in server.received if packet[1] == UPDATE_ZONE_LEDS),
                None,
            )
            time.sleep(0.02)
        assert write_packet is not None
        device, packet_id, body = write_packet
        assert device == 0
        assert packet_id == UPDATE_ZONE_LEDS
        assert len(body) == 10 + 8 * 4
        assert struct.unpack("<I", body[:4])[0] == len(body)
    finally:
        client.close()
        server.stop()
        server.join(2)


def test_client_sends_client_name() -> None:
    server = FakeOpenRGBServer(build_device_payload())
    server.start()
    client = OpenRGBClient("127.0.0.1", server.port, "AuraSync test")
    try:
        client.discover()
        assert any(packet[1] == SET_CLIENT_NAME for packet in server.received)
        custom = [packet for packet in server.received if packet[1] == SET_CUSTOM_MODE]
        assert len(custom) == 0
    finally:
        client.close()
        server.stop()
        server.join(2)


def test_client_requests_custom_mode_when_direct_is_not_active() -> None:
    server = FakeOpenRGBServer(build_device_payload(mode_name="Rainbow"))
    server.start()
    client = OpenRGBClient("127.0.0.1", server.port, "AuraSync test")
    try:
        client.discover()
        deadline = time.monotonic() + 2
        custom: list[tuple[int, int, bytes]] = []
        while time.monotonic() < deadline and not custom:
            custom = [packet for packet in server.received if packet[1] == SET_CUSTOM_MODE]
            time.sleep(0.02)
        assert len(custom) == 1
    finally:
        client.close()
        server.stop()
        server.join(2)
