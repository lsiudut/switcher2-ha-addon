"""Minimal protobuf wire-format encoder/decoder for ESPHome native API.

No external dependencies — hand-rolled to avoid protoc/grpcio requirement.

Wire types used:
  0  varint      — bool, uint32, int32, enum
  2  length-del  — string, bytes, packed-repeated
  5  32-bit      — fixed32 (entity keys), float
"""
import struct


# ---------------------------------------------------------------------------
# Varint helpers
# ---------------------------------------------------------------------------

def _encode_varint(value: int) -> bytes:
    result = []
    while value > 0x7F:
        result.append((value & 0x7F) | 0x80)
        value >>= 7
    result.append(value)
    return bytes(result)


def _decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7


# ---------------------------------------------------------------------------
# Field encoders
# ---------------------------------------------------------------------------

def field_string(field_num: int, value: str) -> bytes:
    if not value:
        return b''
    enc = value.encode('utf-8')
    return _encode_varint((field_num << 3) | 2) + _encode_varint(len(enc)) + enc


def field_bool(field_num: int, value: bool) -> bytes:
    if not value:
        return b''
    return _encode_varint((field_num << 3) | 0) + b'\x01'


def field_uint32(field_num: int, value: int) -> bytes:
    if value == 0:
        return b''
    return _encode_varint((field_num << 3) | 0) + _encode_varint(value)


def field_int32(field_num: int, value: int) -> bytes:
    if value == 0:
        return b''
    if value < 0:
        value = value & 0xFFFFFFFFFFFFFFFF  # 64-bit two's complement varint
    return _encode_varint((field_num << 3) | 0) + _encode_varint(value)


def field_fixed32(field_num: int, value: int) -> bytes:
    return _encode_varint((field_num << 3) | 5) + struct.pack('<I', value)


def field_float(field_num: int, value: float) -> bytes:
    return _encode_varint((field_num << 3) | 5) + struct.pack('<f', value)


def field_enum(field_num: int, value: int) -> bytes:
    if value == 0:
        return b''
    return _encode_varint((field_num << 3) | 0) + _encode_varint(value)


def field_packed_enum(field_num: int, values: list[int]) -> bytes:
    """Encode a packed repeated enum (proto3 default for scalar repeated fields)."""
    if not values:
        return b''
    packed = b''.join(_encode_varint(v) for v in values)
    return _encode_varint((field_num << 3) | 2) + _encode_varint(len(packed)) + packed


def field_message(field_num: int, value: bytes) -> bytes:
    """Encode a nested protobuf message."""
    if not value:
        return b''
    return _encode_varint((field_num << 3) | 2) + _encode_varint(len(value)) + value


# ---------------------------------------------------------------------------
# Message decoder
# ---------------------------------------------------------------------------

def decode_message(data: bytes) -> dict:
    """Decode protobuf bytes into {field_num: raw_value}.

    Wire type 0 (varint)         → int
    Wire type 2 (length-delim)  → bytes
    Wire type 5 (32-bit)        → int (uint32 bit-pattern; reinterpret as float if needed)
    Wire type 1 (64-bit)        → int (uint64 bit-pattern)
    """
    pos = 0
    fields = {}
    while pos < len(data):
        tag, pos = _decode_varint(data, pos)
        field_num = tag >> 3
        wire_type = tag & 0x7
        if wire_type == 0:
            value, pos = _decode_varint(data, pos)
        elif wire_type == 2:
            length, pos = _decode_varint(data, pos)
            value = data[pos:pos + length]
            pos += length
        elif wire_type == 5:
            value = struct.unpack_from('<I', data, pos)[0]
            pos += 4
        elif wire_type == 1:
            value = struct.unpack_from('<Q', data, pos)[0]
            pos += 8
        else:
            break  # unknown wire type — stop parsing
        fields[field_num] = value
    return fields


def bits_to_float(bits: int) -> float:
    """Reinterpret a uint32 bit-pattern as IEEE-754 float."""
    return struct.unpack('<f', struct.pack('<I', bits))[0]


# ---------------------------------------------------------------------------
# ESPHome native API framing
# ---------------------------------------------------------------------------
# Format: \x00  VarInt(body_size)  VarInt(msg_type)  body_bytes
# The body_size counts ONLY the protobuf body, NOT the msg_type varint.

def frame_message(msg_type: int, body: bytes) -> bytes:
    return b'\x00' + _encode_varint(len(body)) + _encode_varint(msg_type) + body


async def read_message(reader) -> tuple[int, bytes]:
    """Read one ESPHome framed message. Returns (msg_type, protobuf_body)."""
    zero = await reader.readexactly(1)
    if zero != b'\x00':
        raise ValueError(f"Expected framing byte 0x00, got {zero!r}")

    # body size varint
    size = 0
    shift = 0
    while True:
        b = (await reader.readexactly(1))[0]
        size |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7

    # message type varint
    msg_type = 0
    shift = 0
    while True:
        b = (await reader.readexactly(1))[0]
        msg_type |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7

    body = await reader.readexactly(size) if size > 0 else b''
    return msg_type, body
