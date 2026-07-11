"""Entity model for Modbus-to-Home Assistant bridge."""
from dataclasses import dataclass
from enum import IntEnum


class EntityType(IntEnum):
    BINARY_SENSOR = 1
    COVER = 2
    LIGHT = 3
    SENSOR = 4
    TEXT_SENSOR = 5
    BUTTON = 6


class SensorStateClass(IntEnum):
    NONE = 0
    MEASUREMENT = 1
    TOTAL_INCREASING = 2
    TOTAL = 3


@dataclass
class Entity:
    key: int            # Stable uint32 identifier used in ESPHome API
    name: str           # Human-readable name shown in HA
    object_id: str      # Machine-readable id (used for HA entity_id suffix)
    entity_type: EntityType
    device_id: str = ''    # Configured Modbus device id that owns this entity

    # Optional per-type fields
    device_class: str = ''
    unit_of_measurement: str = ''
    accuracy_decimals: int = 1
    supports_position: bool = False
    force_update: bool = False
    state_class: SensorStateClass = SensorStateClass.MEASUREMENT

    # ESPHome/Home Assistant publication policy. Zero/None values preserve the
    # historical behavior: publish every detected change and do not publish
    # unchanged values periodically.
    update_interval_s: float = 0.0
    update_on_change: float | None = None
    max_updates_per_minute: int = 0

    # Source mapping — exactly one of these is set
    channel: int = -1       # switcher2 channel index 0–13
    input_index: int = -1   # physical input index 0–15
    sensor_index: int = -1  # LM75 sensor index 0–3
    param_name: str = ''    # Generic sensor parameter name
    register_name: str = '' # Generic Modbus register/attribute name
    command_name: str = ''  # Generic command/action name
