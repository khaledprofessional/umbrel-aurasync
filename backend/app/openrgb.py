"""Minimal, dependency-free OpenRGB SDK client (protocol 0-4).

The SDK protocol is a binary TCP protocol. Implementing it directly keeps the
AuraSync backend image small and makes reconnects deterministic. Protocol 4 is
the newest version this client negotiates; newer OpenRGB servers remain fully
supported because they automatically fall back to the negotiated version.
"""

from __future__ import annotations

import hashlib
import logging
import socket
import struct
import time
from dataclasses import dataclass, field
from typing import Any

LOGGER = logging.getLogger(__name__)

PROTOCOL_VERSION = 4
HEADER = struct.Struct("<4sIII")
MAGIC = b"ORGB"
MAX_PACKET_SIZE = 16 * 1024 * 1024
MAX_DEVICES = 512
MAX_ZONES = 512
MAX_LEDS = 4096
MAX_MODES = 128

REQUEST_CONTROLLER_COUNT = 0
REQUEST_CONTROLLER_DATA = 1
REQUEST_PROTOCOL_VERSION = 40
SET_CLIENT_NAME = 50
DEVICE_LIST_UPDATED = 100
UPDATE_ZONE_LEDS = 1051
SET_CUSTOM_MODE = 1100

ZONE_TYPE_NAMES = {
    0: "single",
    1: "linear",
    2: "matrix",
    3: "linear-loop",
    4: "matrix-loop-x",
    5: "matrix-loop-y",
    6: "segmented",
}

DEVICE_TYPE_NAMES = {
    0: "motherboard",
    1: "dram",
    2: "gpu",
    3: "cooler",
    4: "led-strip",
    5: "keyboard",
    6: "mouse",
    7: "mousepad",
    8: "headset",
    9: "headset-stand",
    10: "gamepad",
    11: "light",
    12: "speaker",
    13: "virtual",
    14: "storage",
    15: "case",
    16: "microphone",
    17: "accessory",
    18: "keypad",
    19: "unknown",
}

COLOR = tuple[int, int, int]


class OpenRGBError(RuntimeError):
    pass


class OpenRGBDisconnected(OpenRGBError):
    pass


class OpenRGBProtocolError(OpenRGBError):
    pass


class _Buffer:
    def __init__(self, data: bytes, offset: int = 0) -> None:
        self.data = data
        self.offset = offset

    def take(self, size: int) -> bytes:
        if size < 0 or self.offset + size > len(self.data):
            raise OpenRGBProtocolError("OpenRGB response ended unexpectedly")
        chunk = self.data[self.offset : self.offset + size]
        self.offset += size
        return chunk

    def unpack(self, fmt: str) -> Any:
        size = struct.calcsize(fmt)
        values = struct.unpack(fmt, self.take(size))
        return values[0] if len(values) == 1 else values

    def u16(self) -> int:
        return int(self.unpack("<H"))

    def i32(self) -> int:
        return int(self.unpack("<i"))

    def u32(self) -> int:
        return int(self.unpack("<I"))

    def string(self) -> str:
        length = self.u16()
        if length == 0:
            return ""
        if length > 8192:
            raise OpenRGBProtocolError("OpenRGB string is unreasonably long")
        raw = self.take(length)
        return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")

    def color(self) -> COLOR:
        red, green, blue, _reserved = struct.unpack("<BBBB", self.take(4))
        return (red, green, blue)

    def remaining(self) -> int:
        return len(self.data) - self.offset


@dataclass(slots=True)
class OpenRGBZone:
    index: int
    name: str
    zone_type: int
    led_count: int
    start_idx: int
    matrix: dict[str, Any] | None = None
    segments: list[dict[str, Any]] = field(default_factory=list)
    led_names: list[str] = field(default_factory=list)

    @property
    def type_name(self) -> str:
        return ZONE_TYPE_NAMES.get(self.zone_type, "unknown")

    def to_dict(self, device_key: str) -> dict[str, Any]:
        return {
            "id": f"{device_key}:z{self.index}",
            "index": self.index,
            "name": self.name or f"Zone {self.index + 1}",
            "type": self.type_name,
            "led_count": self.led_count,
            "start_idx": self.start_idx,
            "matrix": self.matrix,
            "segments": self.segments,
            "led_names": self.led_names,
        }


@dataclass(slots=True)
class OpenRGBDevice:
    key: str
    index: int
    name: str
    device_type: int
    vendor: str
    description: str
    version: str
    serial: str
    location: str
    active_mode: int
    modes: list[str]
    zones: list[OpenRGBZone]

    @property
    def type_name(self) -> str:
        return DEVICE_TYPE_NAMES.get(self.device_type, "unknown")

    @property
    def led_count(self) -> int:
        return sum(zone.led_count for zone in self.zones)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "index": self.index,
            "name": self.name or "OpenRGB device",
            "type": self.type_name,
            "vendor": self.vendor,
            "description": self.description,
            "version": self.version,
            "serial": self.serial,
            "location": self.location,
            "active_mode": self.active_mode,
            "modes": self.modes,
            "led_count": self.led_count,
            "zones": [zone.to_dict(self.key) for zone in self.zones],
        }


@dataclass(slots=True)
class OpenRGBStatus:
    connected: bool = False
    error: str | None = None
    server_protocol: int | None = None
    device_count: int = 0
    last_discovery: float | None = None
    last_write: float | None = None
    last_write_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "error": self.error,
            "server_protocol": self.server_protocol,
            "device_count": self.device_count,
            "last_discovery": self.last_discovery,
            "last_write": self.last_write,
            "last_write_error": self.last_write_error,
        }


def _read_string_from(data: _Buffer) -> str:
    return data.string()


def parse_device_payload(payload: bytes, protocol: int = PROTOCOL_VERSION) -> OpenRGBDevice:
    """Parse a REQUEST_CONTROLLER_DATA response.

    The payload starts with a uint32 data-size field, followed by the device
    description block. This parser covers protocol versions 0-4 exactly; the
    client never negotiates above 4.
    """

    buffer = _Buffer(payload)
    declared_size = buffer.u32()
    if declared_size < 4 or declared_size > len(payload):
        raise OpenRGBProtocolError("invalid controller data size")
    device_type = buffer.i32()
    if device_type not in DEVICE_TYPE_NAMES:
        device_type = 19
    name = buffer.string()
    vendor = buffer.string() if protocol >= 1 else ""
    description = buffer.string()
    firmware = buffer.string()
    serial = buffer.string()
    location = buffer.string()

    num_modes = buffer.u16()
    if num_modes > MAX_MODES:
        raise OpenRGBProtocolError("too many modes")
    active_mode = buffer.i32()
    modes: list[str] = []
    for _ in range(num_modes):
        mode_name = buffer.string()
        buffer.i32()  # mode value, required for protocol <= 5
        flags = buffer.u32()
        buffer.u32()  # speed min
        buffer.u32()  # speed max
        if protocol >= 3:
            buffer.u32()  # brightness min
            buffer.u32()  # brightness max
        buffer.u32()  # colors min
        buffer.u32()  # colors max
        buffer.u32()  # speed
        if protocol >= 3:
            buffer.u32()  # brightness
        buffer.u32()  # direction
        buffer.u32()  # color mode
        num_colors = buffer.u16()
        if num_colors > 1024:
            raise OpenRGBProtocolError("too many mode colours")
        for _ in range(num_colors):
            buffer.color()
        modes.append(mode_name or f"Mode {len(modes)}")
        del flags

    num_zones = buffer.u16()
    if num_zones > MAX_ZONES:
        raise OpenRGBProtocolError("too many zones")
    zones: list[OpenRGBZone] = []
    running_led_index = 0
    for zone_index in range(num_zones):
        zone_name = buffer.string()
        zone_type = buffer.i32()
        buffer.u32()  # leds min
        buffer.u32()  # leds max
        led_count = buffer.u32()
        if led_count > MAX_LEDS:
            raise OpenRGBProtocolError("zone has too many LEDs")
        matrix_size = buffer.u16()
        matrix = None
        if matrix_size > 0:
            height = buffer.u32()
            width = buffer.u32()
            if height * width > MAX_LEDS * 4:
                raise OpenRGBProtocolError("matrix map is too large")
            values = [buffer.u32() for _ in range(height * width)]
            matrix = {"height": height, "width": width, "leds": values}
        segments: list[dict[str, Any]] = []
        if protocol >= 4:
            num_segments = buffer.u16()
            if num_segments > 256:
                raise OpenRGBProtocolError("too many segments")
            for segment_index in range(num_segments):
                segment_name = buffer.string()
                segment_type = buffer.i32()
                start_idx = buffer.u32()
                count = buffer.u32()
                segments.append(
                    {
                        "index": segment_index,
                        "name": segment_name,
                        "type": ZONE_TYPE_NAMES.get(segment_type, "unknown"),
                        "start_idx": start_idx,
                        "led_count": count,
                    }
                )
        zones.append(
            OpenRGBZone(
                index=zone_index,
                name=zone_name,
                zone_type=zone_type,
                led_count=led_count,
                start_idx=running_led_index,
                matrix=matrix,
                segments=segments,
            )
        )
        running_led_index += led_count

    total_leds = buffer.u16()
    if total_leds > MAX_LEDS:
        raise OpenRGBProtocolError("device has too many LEDs")
    led_names: list[str] = []
    for _ in range(total_leds):
        led_names.append(buffer.string())
        buffer.u32()  # LED value, required for protocol <= 5

    num_colors = buffer.u16()
    if num_colors > MAX_LEDS:
        raise OpenRGBProtocolError("device has too many colours")
    for _ in range(num_colors):
        buffer.color()

    for zone in zones:
        zone.led_names = led_names[zone.start_idx : zone.start_idx + zone.led_count]

    identity = "\x00".join((name, vendor, serial, location, str(device_type)))
    digest = hashlib.sha1(identity.encode("utf-8", errors="replace")).hexdigest()[:16]
    return OpenRGBDevice(
        key=f"dev-{digest}",
        index=0,
        name=name,
        device_type=device_type,
        vendor=vendor,
        description=description,
        version=firmware,
        serial=serial,
        location=location,
        active_mode=active_mode,
        modes=modes,
        zones=zones,
    )


def build_zone_payload(zone_index: int, colours: list[COLOR]) -> bytes:
    """Build the data block for NET_PACKET_ID_RGBCONTROLLER_UPDATEZONELEDS."""

    if not 0 <= len(colours) <= 4096:
        raise ValueError("invalid number of colours")
    body = struct.pack("<IH", zone_index, len(colours))
    body += b"".join(struct.pack("<BBBB", *colour, 0) for colour in colours)
    return struct.pack("<I", len(body) + 4) + body


class OpenRGBClient:
    """One blocking SDK connection, owned by the renderer thread."""

    def __init__(self, host: str, port: int, client_name: str = "AuraSync") -> None:
        self.host = host
        self.port = port
        self.client_name = client_name
        self._sock: socket.socket | None = None
        self.protocol = PROTOCOL_VERSION
        self.status = OpenRGBStatus()
        self._custom_mode: set[int] = set()
        self._connection_id = 0

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def connect(self) -> None:
        self.close()
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3.0)
        try:
            sock.connect((self.host, self.port))
        except OSError as exc:
            sock.close()
            raise OpenRGBDisconnected(f"cannot reach OpenRGB at {self.host}:{self.port}: {exc}") from exc
        self._sock = sock
        self._connection_id += 1
        self._custom_mode.clear()
        try:
            self._negotiate_protocol()
            self.status.server_protocol = self.protocol
            self._send_client_name()
            self.status.connected = True
            self.status.error = None
        except Exception:
            self.close()
            raise

    def _negotiate_protocol(self) -> None:
        assert self._sock is not None
        self._send_packet(0, REQUEST_PROTOCOL_VERSION, struct.pack("<I", PROTOCOL_VERSION))
        self._sock.settimeout(1.5)
        try:
            _device, packet_id, payload = self._receive_packet()
        except TimeoutError:
            self.protocol = 0
            self._sock.settimeout(5.0)
            return
        except OpenRGBDisconnected:
            raise
        if packet_id != REQUEST_PROTOCOL_VERSION or len(payload) < 4:
            # A protocol-0 server does not answer this request at all. Some
            # old builds may emit an unrelated packet first; treat it as v0.
            self.protocol = 0
        else:
            server_version = struct.unpack("<I", payload[:4])[0]
            self.protocol = max(0, min(PROTOCOL_VERSION, int(server_version)))
        self._sock.settimeout(5.0)

    def _send_client_name(self) -> None:
        name = f"{self.client_name}\x00".encode()
        self._send_packet(0, SET_CLIENT_NAME, name)

    def _send_packet(self, device: int, packet_id: int, payload: bytes = b"") -> None:
        if self._sock is None:
            raise OpenRGBDisconnected("OpenRGB is not connected")
        header = HEADER.pack(MAGIC, device, packet_id, len(payload))
        try:
            self._sock.sendall(header + payload)
        except OSError as exc:
            self.close()
            raise OpenRGBDisconnected(f"OpenRGB connection lost: {exc}") from exc

    def _recv_exact(self, size: int) -> bytes:
        if self._sock is None:
            raise OpenRGBDisconnected("OpenRGB is not connected")
        chunks = bytearray()
        while len(chunks) < size:
            try:
                chunk = self._sock.recv(size - len(chunks))
            except TimeoutError:
                raise
            except OSError as exc:
                self.close()
                raise OpenRGBDisconnected(f"OpenRGB read failed: {exc}") from exc
            if not chunk:
                self.close()
                raise OpenRGBDisconnected("OpenRGB closed the connection")
            chunks.extend(chunk)
        return bytes(chunks)

    def _receive_packet(self) -> tuple[int, int, bytes]:
        header = self._recv_exact(HEADER.size)
        magic, device, packet_id, size = HEADER.unpack(header)
        if magic != MAGIC:
            self.close()
            raise OpenRGBProtocolError("invalid OpenRGB packet magic")
        if size > MAX_PACKET_SIZE:
            self.close()
            raise OpenRGBProtocolError("OpenRGB packet is too large")
        payload = self._recv_exact(size) if size else b""
        return device, packet_id, payload

    def _receive_until(self, packet_id: int, device: int | None = None) -> bytes:
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline:
            got_device, got_id, payload = self._receive_packet()
            if got_id == packet_id and (device is None or got_device == device):
                return payload
            if got_id == DEVICE_LIST_UPDATED:
                LOGGER.info("OpenRGB device list changed during request")
            else:
                LOGGER.debug("Ignoring OpenRGB packet id=%s device=%s", got_id, got_device)
        raise OpenRGBProtocolError(f"timed out waiting for OpenRGB packet {packet_id}")

    def discover(self) -> list[OpenRGBDevice]:
        if not self.connected:
            self.connect()
        assert self._sock is not None
        self._sock.settimeout(5.0)
        self._send_packet(0, REQUEST_CONTROLLER_COUNT)
        payload = self._receive_until(REQUEST_CONTROLLER_COUNT, device=0)
        if len(payload) < 4:
            raise OpenRGBProtocolError("invalid controller count response")
        count = struct.unpack("<I", payload[:4])[0]
        if count > MAX_DEVICES:
            raise OpenRGBProtocolError("OpenRGB reported too many devices")

        devices: list[OpenRGBDevice] = []
        for index in range(count):
            if self.protocol >= 1:
                request = struct.pack("<I", self.protocol)
            else:
                request = b""
            self._send_packet(index, REQUEST_CONTROLLER_DATA, request)
            device_payload = self._receive_until(REQUEST_CONTROLLER_DATA, device=index)
            device = parse_device_payload(device_payload, self.protocol)
            device.index = index
            devices.append(device)

        # Stable keys must not depend on the enumeration index. In the rare
        # case of two physically identical controllers, disambiguate by order.
        seen: dict[str, int] = {}
        for device in devices:
            seen[device.key] = seen.get(device.key, 0) + 1
            if seen[device.key] > 1:
                device.key = f"{device.key}-{seen[device.key]}"

        for device in devices:
            self._ensure_custom_mode(device)
        self.status.device_count = len(devices)
        self.status.last_discovery = time.time()
        self.status.connected = True
        self.status.error = None
        return devices

    def _ensure_custom_mode(self, device: OpenRGBDevice) -> None:
        if device.index in self._custom_mode:
            return
        direct_index = next(
            (i for i, name in enumerate(device.modes) if name.lower() == "direct"),
            None,
        )
        if direct_index is not None and device.active_mode == direct_index:
            self._custom_mode.add(device.index)
            return
        try:
            self._send_packet(device.index, SET_CUSTOM_MODE)
            self._custom_mode.add(device.index)
        except OpenRGBDisconnected:
            raise
        except Exception as exc:  # noqa: BLE001  # defensive hardware path
            LOGGER.warning("Could not switch %s to Direct mode: %s", device.name, exc)

    def set_zone_colours(self, device_index: int, zone_index: int, colours: list[COLOR]) -> None:
        if not self.connected:
            raise OpenRGBDisconnected("OpenRGB is not connected")
        payload = build_zone_payload(zone_index, colours)
        self._send_packet(device_index, UPDATE_ZONE_LEDS, payload)
        self.status.last_write = time.time()
        self.status.last_write_error = None
        self.status.error = None

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None
        self._custom_mode.clear()
        self.status.connected = False

    def mark_error(self, message: str) -> None:
        self.status.connected = False
        self.status.error = message[:500]
