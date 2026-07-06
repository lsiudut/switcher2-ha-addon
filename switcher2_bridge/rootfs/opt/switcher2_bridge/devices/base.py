"""Common device adapter interfaces."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from entities import Entity

KEY_INPUT_BASE = 1
KEY_LIGHT_BASE = 100
KEY_COVER_BASE = 200
KEY_SENSOR_BASE = 300
KEY_METER_BASE = 10000
KEY_ROLETTINI_BASE = 20000
KEY_DEVICE_STRIDE = 1000


@dataclass
class DeviceInfo:
    id: str
    type: str
    name: str
    index: int
    config: dict
    serial: dict
    poll_interval_s: float
    write_priority: int
    esphome_device_id: int = 0
    available: bool = True


@dataclass
class QueuedWrite:
    action: str
    payload: dict[str, Any]
    fn: Callable[[Any], Any]
    desc: str


class DeviceAdapter(Protocol):
    info: DeviceInfo

    def build_entities(self, bus: Any | None = None) -> list[Entity]:
        ...

    def poll(self, bus: Any) -> dict[int, Any]:
        ...

    def web_read(self, view: str, state: dict[int, Any], payload: dict[str, Any] | None = None) -> Any:
        ...

    def prepare_write(self, action: str, payload: dict[str, Any] | None = None) -> QueuedWrite:
        ...

    def close(self) -> None:
        ...
