"""ESPHome native API TCP server for the Modbus bridge.

Implements the ESPHome protobuf API (api.proto) over TCP port 6053 so that
Home Assistant's built-in ESPHome integration can discover and control
configured Modbus devices without any custom HA component or MQTT broker.

Protocol framing: \x00  VarInt(body_len)  VarInt(msg_type_id)  protobuf_body
Reference: https://github.com/esphome/aioesphomeapi
"""
import asyncio
import logging

from proto import (
    frame_message, read_message, decode_message, bits_to_float,
    field_string, field_bool, field_uint32, field_fixed32,
    field_float, field_enum, field_packed_enum, field_int32,
    field_message,
)
from entities import Entity, EntityType
from bridge import Sw2Bridge

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Message type IDs (api.proto option (id) = N)
# ---------------------------------------------------------------------------
MSG_HELLO_REQUEST              = 1
MSG_HELLO_RESPONSE             = 2
MSG_DISCONNECT_REQUEST         = 5
MSG_DISCONNECT_RESPONSE        = 6
MSG_PING_REQUEST               = 7
MSG_PING_RESPONSE              = 8
MSG_DEVICE_INFO_REQUEST        = 9
MSG_DEVICE_INFO_RESPONSE       = 10
MSG_LIST_ENTITIES_REQUEST      = 11
MSG_LIST_ENTITIES_BINARY_SENSOR = 12
MSG_LIST_ENTITIES_COVER        = 13
MSG_LIST_ENTITIES_LIGHT        = 15
MSG_LIST_ENTITIES_SENSOR       = 16
MSG_LIST_ENTITIES_TEXT_SENSOR  = 18
MSG_LIST_ENTITIES_DONE         = 19
MSG_SUBSCRIBE_STATES           = 20
MSG_BINARY_SENSOR_STATE        = 21
MSG_COVER_STATE                = 22
MSG_LIGHT_STATE                = 24
MSG_SENSOR_STATE               = 25
MSG_TEXT_SENSOR_STATE          = 27
MSG_COVER_COMMAND              = 30
MSG_LIGHT_COMMAND              = 32
MSG_LIST_ENTITIES_BUTTON       = 61
MSG_BUTTON_COMMAND             = 62

# ColorMode enum values (api.proto)
COLOR_MODE_ON_OFF = 1

# ---------------------------------------------------------------------------
# ESPHome response builders
# ---------------------------------------------------------------------------

def _build_child_device(device_id: int, name: str) -> bytes:
    return field_uint32(1, device_id) + field_string(2, name)


def _build_device_info(name: str, mac: str, devices: list[dict]) -> bytes:
    child_devices = b''.join(
        field_message(20, _build_child_device(d["esphome_device_id"], d["name"]))
        for d in devices
    )
    return (
        field_string(2, name) +
        field_string(3, mac) +
        field_string(4, "1.0.0") +       # esphome_version
        field_string(6, "Modbus HA Bridge") +
        field_string(12, "ha_bridge") +
        field_string(13, name) +
        child_devices
    )


def _build_list_binary_sensor(e: Entity, device_id: int = 0) -> bytes:
    return (
        field_string(1, e.object_id) +
        field_fixed32(2, e.key) +
        field_string(3, e.name) +
        field_string(5, e.device_class) +
        field_uint32(10, device_id)
    )


def _build_list_cover(e: Entity, device_id: int = 0) -> bytes:
    return (
        field_string(1, e.object_id) +
        field_fixed32(2, e.key) +
        field_string(3, e.name) +
        field_bool(6, e.supports_position) +
        field_bool(12, True) +  # supports_stop
        field_uint32(13, device_id)
    )


def _build_list_light(e: Entity, device_id: int = 0) -> bytes:
    return (
        field_string(1, e.object_id) +
        field_fixed32(2, e.key) +
        field_string(3, e.name) +
        field_packed_enum(12, [COLOR_MODE_ON_OFF]) +  # supported_color_modes
        field_uint32(16, device_id)
    )


def _build_list_sensor(e: Entity, device_id: int = 0) -> bytes:
    return (
        field_string(1, e.object_id) +
        field_fixed32(2, e.key) +
        field_string(3, e.name) +
        field_string(6, e.unit_of_measurement) +
        field_int32(7, e.accuracy_decimals) +
        field_bool(8, e.force_update) +
        field_string(9, e.device_class) +
        field_enum(10, int(e.state_class)) +
        field_uint32(14, device_id)
    )


def _build_list_text_sensor(e: Entity, device_id: int = 0) -> bytes:
    return (
        field_string(1, e.object_id) +
        field_fixed32(2, e.key) +
        field_string(3, e.name) +
        field_uint32(9, device_id)
    )


def _build_list_button(e: Entity, device_id: int = 0) -> bytes:
    return (
        field_string(1, e.object_id) +
        field_fixed32(2, e.key) +
        field_string(3, e.name) +
        field_uint32(9, device_id)
    )


def _build_binary_sensor_state(key: int, state: bool, device_id: int = 0) -> bytes:
    return field_fixed32(1, key) + field_bool(2, state) + field_uint32(4, device_id)


def _build_cover_state(key: int, position: float, operation: int, device_id: int = 0) -> bytes:
    return (
        field_fixed32(1, key) +
        field_float(3, position) +
        field_enum(5, operation) +
        field_uint32(6, device_id)
    )


def _build_light_state(key: int, state: bool, device_id: int = 0) -> bytes:
    return (
        field_fixed32(1, key) +
        field_bool(2, state) +
        field_enum(11, COLOR_MODE_ON_OFF) +
        field_uint32(14, device_id)
    )


def _build_sensor_state(key: int, state: float | None, device_id: int = 0) -> bytes:
    if state is None:
        return field_fixed32(1, key) + field_bool(3, True) + field_uint32(4, device_id)
    return field_fixed32(1, key) + field_float(2, state) + field_uint32(4, device_id)


def _build_text_sensor_state(key: int, state: str | None, device_id: int = 0) -> bytes:
    if state is None:
        return field_fixed32(1, key) + field_bool(3, True) + field_uint32(4, device_id)
    return field_fixed32(1, key) + field_string(2, str(state)) + field_uint32(4, device_id)


def entity_state_frame(entity: Entity, state, device_id: int = 0) -> bytes | None:
    """Encode an entity state as a complete ESPHome framed message."""
    if entity.entity_type == EntityType.BINARY_SENSOR:
        return frame_message(MSG_BINARY_SENSOR_STATE,
                             _build_binary_sensor_state(entity.key, state, device_id))
    if entity.entity_type == EntityType.COVER:
        pos, op = state
        return frame_message(MSG_COVER_STATE,
                             _build_cover_state(entity.key, pos, op, device_id))
    if entity.entity_type == EntityType.LIGHT:
        return frame_message(MSG_LIGHT_STATE,
                             _build_light_state(entity.key, state, device_id))
    if entity.entity_type == EntityType.SENSOR:
        return frame_message(MSG_SENSOR_STATE,
                             _build_sensor_state(entity.key, state, device_id))
    if entity.entity_type == EntityType.TEXT_SENSOR:
        return frame_message(MSG_TEXT_SENSOR_STATE,
                             _build_text_sensor_state(entity.key, state, device_id))
    return None


# ---------------------------------------------------------------------------
# Per-connection handler
# ---------------------------------------------------------------------------

class _ClientHandler:
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        bridge: Sw2Bridge,
        name: str,
        mac: str,
    ):
        self._reader = reader
        self._writer = writer
        self._bridge = bridge
        self._name = name
        self._mac = mac
        self._addr = writer.get_extra_info('peername')
        self._subscribed = False
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._loop = asyncio.get_event_loop()
        self._avail_registered = False
        self._reconnect_registered = False

    # ---- internal send helpers ----

    def _send(self, msg_type: int, body: bytes) -> None:
        self._writer.write(frame_message(msg_type, body))

    async def _flush(self) -> None:
        await self._writer.drain()

    # ---- message handlers ----

    async def _on_hello(self, data: bytes) -> None:
        fields = decode_message(data)
        client_info = fields.get(1, b'')
        if isinstance(client_info, bytes):
            client_info = client_info.decode('utf-8', errors='replace')
        log.debug(f"[{self._addr}] HelloRequest from '{client_info}'")
        body = (
            field_uint32(1, 1) +                              # api_version_major
            field_uint32(2, 10) +                             # api_version_minor
            field_string(3, "modbus-ha-bridge v1.0") +        # server_info
            field_string(4, self._name)                       # name
        )
        self._send(MSG_HELLO_RESPONSE, body)
        await self._flush()
        log.debug(f"[{self._addr}] ESPHome connection established; device metadata will be rebuilt on request")

    async def _on_device_info(self) -> None:
        devices = self._bridge.get_esphome_devices()
        log.debug(f"[{self._addr}] Advertising {len(devices)} logical ESPHome device(s)")
        self._send(MSG_DEVICE_INFO_RESPONSE, _build_device_info(self._name, self._mac, devices))
        await self._flush()

    async def _on_list_entities(self) -> None:
        # HA asks for this on connection/reconnect. Rebuild the entity list from
        # the current bridge cache every time so HA can reconfigure if devices
        # or names changed since the previous connection.
        for entity in self._bridge.get_entities():
            device_id = self._bridge.esphome_device_id_for_entity(entity)
            if entity.entity_type == EntityType.BINARY_SENSOR:
                self._send(MSG_LIST_ENTITIES_BINARY_SENSOR, _build_list_binary_sensor(entity, device_id))
            elif entity.entity_type == EntityType.COVER:
                self._send(MSG_LIST_ENTITIES_COVER, _build_list_cover(entity, device_id))
            elif entity.entity_type == EntityType.LIGHT:
                self._send(MSG_LIST_ENTITIES_LIGHT, _build_list_light(entity, device_id))
            elif entity.entity_type == EntityType.SENSOR:
                self._send(MSG_LIST_ENTITIES_SENSOR, _build_list_sensor(entity, device_id))
            elif entity.entity_type == EntityType.TEXT_SENSOR:
                self._send(MSG_LIST_ENTITIES_TEXT_SENSOR, _build_list_text_sensor(entity, device_id))
            elif entity.entity_type == EntityType.BUTTON:
                self._send(MSG_LIST_ENTITIES_BUTTON, _build_list_button(entity, device_id))
        self._send(MSG_LIST_ENTITIES_DONE, b'')
        await self._flush()

    async def _on_subscribe_states(self) -> None:
        self._subscribed = True
        # Push full current state snapshot
        state = self._bridge.get_state()
        for entity in self._bridge.get_entities():
            s = state.get(entity.key)
            if s is None:
                continue
            f = entity_state_frame(entity, s, self._bridge.esphome_device_id_for_entity(entity))
            if f:
                self._writer.write(f)
        await self._flush()
        # Register for future state changes
        self._bridge.register_callback(self._on_state_change)

    def _on_state_change(self, entity: Entity, new_state) -> None:
        """Called from asyncio event-loop thread when poll detects a change."""
        f = entity_state_frame(
            entity,
            new_state,
            self._bridge.esphome_device_id_for_entity(entity),
        )
        if f:
            self._queue.put_nowait(f)

    def _on_availability_change(self, available: bool) -> None:
        """Called from asyncio event-loop thread when device goes up or down."""
        if not available:
            log.warning(f"[{self._addr}] Device unavailable — closing connection")
            self._close_writer()

    def _on_reconnect_request(self) -> None:
        """Called from Flask thread — schedule writer close on the asyncio event loop."""
        log.info(f"[{self._addr}] Entity names changed — closing connection for HA to reconnect")
        self._loop.call_soon_threadsafe(self._close_writer)

    def _close_writer(self) -> None:
        # Closing the writer causes readexactly() in run() to raise,
        # which exits the read loop cleanly.
        try:
            self._writer.close()
        except Exception:
            pass

    async def _on_light_command(self, data: bytes) -> None:
        fields = decode_message(data)
        key      = fields.get(1, 0)   # fixed32
        has_state = bool(fields.get(2, 0))
        state    = bool(fields.get(3, 0))
        if has_state:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._bridge.cmd_light, key, state)

    async def _on_cover_command(self, data: bytes) -> None:
        fields = decode_message(data)
        key          = fields.get(1, 0)
        has_position = bool(fields.get(4, 0))
        pos_bits     = fields.get(5, 0)   # fixed32 (float bits)
        stop         = bool(fields.get(8, 0))
        position     = bits_to_float(pos_bits) if has_position else None
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._bridge.cmd_cover, key, position, stop)

    async def _on_button_command(self, data: bytes) -> None:
        fields = decode_message(data)
        key = fields.get(1, 0)
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._bridge.cmd_button, key)

    # ---- writer drain loop ----

    async def _writer_loop(self) -> None:
        """Drain the state-update queue and forward frames to the HA client."""
        while True:
            frame = await self._queue.get()
            if frame is None:
                break
            self._writer.write(frame)
            try:
                await self._writer.drain()
            except Exception:
                break

    # ---- main entry point ----

    async def run(self) -> None:
        # Reject connection immediately if device is currently unavailable
        if not self._bridge.is_available():
            log.warning(f"[{self._addr}] Rejecting connection — device unavailable")
            self._send(MSG_DISCONNECT_REQUEST, b'')
            try:
                await self._flush()
            except Exception:
                pass
            self._writer.close()
            return

        self._bridge.register_avail_callback(self._on_availability_change)
        self._avail_registered = True
        self._bridge.register_reconnect_callback(self._on_reconnect_request)
        self._reconnect_registered = True

        writer_task = asyncio.create_task(self._writer_loop())
        try:
            while True:
                msg_type, data = await read_message(self._reader)
                log.debug(f"[{self._addr}] RX type={msg_type} len={len(data)}")

                if msg_type == MSG_HELLO_REQUEST:
                    await self._on_hello(data)
                elif msg_type == MSG_DEVICE_INFO_REQUEST:
                    await self._on_device_info()
                elif msg_type == MSG_LIST_ENTITIES_REQUEST:
                    await self._on_list_entities()
                elif msg_type == MSG_SUBSCRIBE_STATES:
                    await self._on_subscribe_states()
                elif msg_type == MSG_PING_REQUEST:
                    self._send(MSG_PING_RESPONSE, b'')
                    await self._flush()
                elif msg_type == MSG_DISCONNECT_REQUEST:
                    self._send(MSG_DISCONNECT_RESPONSE, b'')
                    await self._flush()
                    break
                elif msg_type == MSG_LIGHT_COMMAND:
                    await self._on_light_command(data)
                elif msg_type == MSG_COVER_COMMAND:
                    await self._on_cover_command(data)
                elif msg_type == MSG_BUTTON_COMMAND:
                    await self._on_button_command(data)
                else:
                    log.debug(f"[{self._addr}] Unhandled message type {msg_type}")

        except asyncio.IncompleteReadError:
            log.debug(f"[{self._addr}] Client disconnected")
        except Exception as e:
            log.warning(f"[{self._addr}] Connection error: {e}")
        finally:
            if self._subscribed:
                self._bridge.unregister_callback(self._on_state_change)
            if self._avail_registered:
                self._bridge.unregister_avail_callback(self._on_availability_change)
            if self._reconnect_registered:
                self._bridge.unregister_reconnect_callback(self._on_reconnect_request)
            self._queue.put_nowait(None)  # signal writer loop to exit
            await writer_task
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class EspHomeServer:
    def __init__(
        self,
        bridge: Sw2Bridge,
        name: str,
        mac: str,
        port: int = 6053,
    ):
        self._bridge = bridge
        self._name = name
        self._mac = mac
        self._port = port

    async def start(self) -> asyncio.Server:
        server = await asyncio.start_server(
            self._handle_client,
            '0.0.0.0',
            self._port,
        )
        log.info(f"ESPHome API server listening on port {self._port}")
        return server

    async def _handle_client(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        addr = writer.get_extra_info('peername')
        log.debug(f"New connection from {addr}")
        handler = _ClientHandler(reader, writer, self._bridge, self._name, self._mac)
        await handler.run()
