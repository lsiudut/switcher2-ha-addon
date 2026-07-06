"""Rolettini blind controller register metadata and helpers."""
from dataclasses import dataclass
from typing import Any

from entities import Entity, EntityType
from devices.base import DeviceInfo, KEY_DEVICE_STRIDE, KEY_ROLETTINI_BASE, QueuedWrite

# Command codes
CMD_NONE = 0x0000
CMD_EMERGENCY_STOP = 0x0001
CMD_START_CALIBRATION = 0x0002
CMD_CLEAR_ALERTS = 0x0003
CMD_START_POSITION_CAL = 0x0004
CMD_CLEAR_EMERGENCY = 0x0005
CMD_CONFIRM_IMAGE = 0x0006
CMD_SAVE_CONFIG = 0x0010
CMD_RESET_STATISTICS = 0x0020
CMD_REBOOT_SYSTEM = 0x00FF

# Control registers
REG_CONTROL_CMD = 0x0000
REG_TARGET_POSITION = 0x0001
REG_MOVEMENT_MODE = 0x0002
REG_MOVEMENT_STOP = 0x0003

# Configuration registers
REG_DEBOUNCE_TIME = 0x0100
REG_SHORT_PRESS_TIME = 0x0101
REG_RELAY_DEAD_TIME = 0x0102
REG_OVERCURRENT_THRESHOLD = 0x0103
REG_TEMP_SHUTDOWN_THRESHOLD = 0x0104
REG_DIDT_THRESHOLD = 0x0105
REG_MODBUS_ADDRESS = 0x0106
REG_MODBUS_BAUD_RATE = 0x0107
REG_MODBUS_PARITY = 0x0108
REG_UART0_MODE = 0x010A
REG_LOG_LEVEL = 0x010B
REG_MOTOR_VOLTAGE = 0x010C
REG_MOTOR_POWER_NOMINAL = 0x010D
REG_ADC_COMP_UP = 0x010F
REG_ADC_COMP_DOWN = 0x0110
REG_ADC_ALERT_DELAY = 0x0111

# Status registers
REG_SYSTEM_STATE = 0x0200
REG_CURRENT_POSITION = 0x0201
REG_RELAY_STATE = 0x0202
REG_ALERT_FLAGS_LOW = 0x0203
REG_ALERT_FLAGS_HIGH = 0x0204
REG_BUTTON_STATE = 0x0205
REG_CONFIG_MODIFIED = 0x0206
REG_EMERGENCY_STOP = 0x0207
REG_IMAGE_PENDING_CONFIRM = 0x0208

# Measurement registers
REG_CURRENT_INSTANT = 0x0300
REG_CURRENT_RMS = 0x0301
REG_CURRENT_ENVELOPE = 0x0302
REG_CURRENT_BASELINE = 0x0303
REG_MOTOR_POWER = 0x0304
REG_DI_DT = 0x0305
REG_NTC_TEMP = 0x0306
REG_TEMP_MAX = 0x0307
REG_OBSTACLE_DETECTED = 0x0308
REG_OBSTACLE_COUNT_LOW = 0x0309
REG_OBSTACLE_COUNT_HIGH = 0x030A
REG_TEMP_WARNINGS = 0x030B
REG_ADC_HEALTHY = 0x030C
REG_ADC_HEARTBEAT_LOW = 0x030D
REG_ADC_HEARTBEAT_HIGH = 0x030E
REG_LAST_PEAK_CURRENT = 0x030F
REG_LAST_PEAK_DIDT = 0x0310
REG_ALERT_TRIGGER_CURRENT = 0x0311
REG_ALERT_TRIGGER_DIDT = 0x0312
REG_ALERT_TRIGGER_VALID = 0x0313
REG_CURRENT_CURRENT_MAX = 0x0314

# Calibration registers
REG_CAL_STATUS = 0x0400
REG_CAL_UP_TIME_LOW = 0x0401
REG_CAL_UP_TIME_HIGH = 0x0402
REG_CAL_DOWN_TIME_LOW = 0x0403
REG_CAL_DOWN_TIME_HIGH = 0x0404

# Device info registers
REG_FW_VERSION_MAJOR = 0x0600
REG_FW_VERSION_MINOR = 0x0601
REG_FW_VERSION_PATCH = 0x0602
REG_HW_VERSION = 0x0603
REG_FLASH_SIZE_MB = 0x0604
REG_ACTIVE_PARTITION = 0x0605

# OTA status registers
REG_OTA_STATE = 0x0710
REG_OTA_ERROR_CODE = 0x0715

SYSTEM_STATES = {
    0: "INIT",
    1: "IDLE",
    2: "MOVING_UP",
    3: "MOVING_DOWN",
    4: "CALIBRATING",
    5: "ERROR_OVERCURRENT",
    6: "ERROR_OVERTEMP",
    7: "ERROR_TIMEOUT",
    8: "ERROR_OBSTACLE",
    9: "ERROR_OVERPOWER",
}

RELAY_STATES = {
    0: "OFF",
    1: "UP",
    2: "DOWN",
}

MODBUS_BAUD_RATES = {
    0: "9600",
    1: "19200",
    2: "38400",
    3: "57600",
    4: "115200",
}

MODBUS_PARITIES = {
    0: "None",
    1: "Even",
    2: "Odd",
}

UART0_MODES = {
    0: "DEBUG",
    1: "CONTROL",
}

LOG_LEVELS = {
    0: "NONE",
    1: "ERROR",
    2: "WARN",
    3: "INFO",
    4: "DEBUG",
    5: "TRACE",
}

OTA_STATES = {
    0: "IDLE",
    1: "ERASING",
    2: "READY",
    3: "RECEIVING",
    4: "WRITING",
    5: "FINALIZING",
    6: "COMPLETE",
    7: "ERROR",
}

OTA_ERRORS = {
    0: "NONE",
    1: "INVALID_SIZE",
    2: "INVALID_SLOT",
    3: "ERASE_FAILED",
    4: "WRITE_FAILED",
    5: "TIMEOUT",
}


@dataclass(frozen=True)
class RegisterDef:
    symbol: str
    address: int
    name: str
    access: str
    unit: str = ""
    scale: float = 1.0
    signed: bool = False
    offset: float = 0.0
    entity_type: EntityType = EntityType.SENSOR
    device_class: str = ""
    accuracy_decimals: int = 0
    enum: dict[int, str] | None = None
    min_value: float | None = None
    max_value: float | None = None
    category: str = "status"


def _reg(
    symbol: str,
    address: int,
    name: str,
    access: str,
    unit: str = "",
    scale: float = 1.0,
    signed: bool = False,
    offset: float = 0.0,
    entity_type: EntityType = EntityType.SENSOR,
    device_class: str = "",
    accuracy_decimals: int | None = None,
    enum: dict[int, str] | None = None,
    min_value: float | None = None,
    max_value: float | None = None,
    category: str = "status",
) -> RegisterDef:
    if accuracy_decimals is None:
        accuracy_decimals = 1 if scale not in (1, 1.0) else 0
    return RegisterDef(
        symbol=symbol,
        address=address,
        name=name,
        access=access,
        unit=unit,
        scale=scale,
        signed=signed,
        offset=offset,
        entity_type=entity_type,
        device_class=device_class,
        accuracy_decimals=accuracy_decimals,
        enum=enum,
        min_value=min_value,
        max_value=max_value,
        category=category,
    )


REGISTER_DEFS = [
    _reg("target_position", REG_TARGET_POSITION, "Target Position", "rw", "%", min_value=0, max_value=100, category="control"),
    _reg("movement_mode", REG_MOVEMENT_MODE, "Movement Mode", "rw", category="control"),
    _reg("debounce_time", REG_DEBOUNCE_TIME, "Debounce Time", "rw", "ms", min_value=10, max_value=200, category="config"),
    _reg("short_press_time", REG_SHORT_PRESS_TIME, "Short Press Time", "rw", "ms", min_value=100, max_value=2000, category="config"),
    _reg("relay_dead_time", REG_RELAY_DEAD_TIME, "Relay Dead Time", "rw", "ms", min_value=50, max_value=1000, category="config"),
    _reg("overcurrent_threshold", REG_OVERCURRENT_THRESHOLD, "Overcurrent Threshold", "rw", "A", 0.1, device_class="current", min_value=0, max_value=100, category="config"),
    _reg("temp_shutdown_threshold", REG_TEMP_SHUTDOWN_THRESHOLD, "Temperature Shutdown", "rw", "°C", 0.1, device_class="temperature", min_value=50, max_value=120, category="config"),
    _reg("didt_threshold", REG_DIDT_THRESHOLD, "dI/dt Threshold", "rw", "A/s", 0.1, min_value=1, max_value=1000, category="config"),
    _reg("modbus_address", REG_MODBUS_ADDRESS, "Modbus Address", "rw", min_value=1, max_value=247, category="advanced"),
    _reg("modbus_baud_rate", REG_MODBUS_BAUD_RATE, "Modbus Baud Rate", "rw", entity_type=EntityType.TEXT_SENSOR, enum=MODBUS_BAUD_RATES, min_value=0, max_value=4, category="advanced"),
    _reg("modbus_parity", REG_MODBUS_PARITY, "Modbus Parity", "rw", entity_type=EntityType.TEXT_SENSOR, enum=MODBUS_PARITIES, min_value=0, max_value=2, category="advanced"),
    _reg("uart0_mode", REG_UART0_MODE, "UART0 Mode", "rw", entity_type=EntityType.TEXT_SENSOR, enum=UART0_MODES, min_value=0, max_value=1, category="advanced"),
    _reg("log_level", REG_LOG_LEVEL, "Log Level", "rw", entity_type=EntityType.TEXT_SENSOR, enum=LOG_LEVELS, min_value=0, max_value=5, category="advanced"),
    _reg("motor_voltage", REG_MOTOR_VOLTAGE, "Motor Voltage", "rw", "V", device_class="voltage", min_value=1, max_value=500, category="config"),
    _reg("motor_power_nominal", REG_MOTOR_POWER_NOMINAL, "Motor Nominal Power", "rw", "W", device_class="power", min_value=0, max_value=10000, category="config"),
    _reg("adc_comp_up", REG_ADC_COMP_UP, "ADC Compensation UP", "rw", "mA", signed=True, min_value=-500, max_value=500, category="config"),
    _reg("adc_comp_down", REG_ADC_COMP_DOWN, "ADC Compensation DOWN", "rw", "mA", signed=True, min_value=-500, max_value=500, category="config"),
    _reg("adc_alert_delay", REG_ADC_ALERT_DELAY, "ADC Alert Delay", "rw", "ms", min_value=0, max_value=1000, category="config"),
    _reg("system_state", REG_SYSTEM_STATE, "System State", "read", entity_type=EntityType.TEXT_SENSOR, enum=SYSTEM_STATES),
    _reg("current_position", REG_CURRENT_POSITION, "Current Position", "read", "%"),
    _reg("relay_state", REG_RELAY_STATE, "Relay State", "read", entity_type=EntityType.TEXT_SENSOR, enum=RELAY_STATES),
    _reg("alert_flags_low", REG_ALERT_FLAGS_LOW, "Alert Flags Low", "read"),
    _reg("alert_flags_high", REG_ALERT_FLAGS_HIGH, "Alert Flags High", "read"),
    _reg("button_state", REG_BUTTON_STATE, "Button State", "read"),
    _reg("config_modified", REG_CONFIG_MODIFIED, "Config Modified", "read", entity_type=EntityType.BINARY_SENSOR),
    _reg("emergency_stop", REG_EMERGENCY_STOP, "Emergency Stop", "read", entity_type=EntityType.BINARY_SENSOR),
    _reg("image_pending_confirm", REG_IMAGE_PENDING_CONFIRM, "Image Pending Confirm", "read", entity_type=EntityType.BINARY_SENSOR),
    _reg("current_instant", REG_CURRENT_INSTANT, "Instantaneous Current", "read", "A", 0.01, device_class="current", accuracy_decimals=2),
    _reg("current_rms", REG_CURRENT_RMS, "RMS Current", "read", "A", 0.01, device_class="current", accuracy_decimals=2),
    _reg("current_envelope", REG_CURRENT_ENVELOPE, "Envelope Current", "read", "A", 0.01, device_class="current", accuracy_decimals=2),
    _reg("current_baseline", REG_CURRENT_BASELINE, "Baseline Voltage", "read", "V", 0.001, device_class="voltage", accuracy_decimals=3),
    _reg("motor_power", REG_MOTOR_POWER, "Motor Power", "read", "W", 0.1, device_class="power"),
    _reg("di_dt", REG_DI_DT, "dI/dt", "read", "A/s", 0.1, signed=True),
    _reg("ntc_temp", REG_NTC_TEMP, "NTC Temperature", "read", "°C", 0.1, offset=-327.68, device_class="temperature"),
    _reg("temp_max", REG_TEMP_MAX, "Max Temperature", "read", "°C", 0.1, signed=True, device_class="temperature"),
    _reg("obstacle_detected", REG_OBSTACLE_DETECTED, "Obstacle Detected", "read", entity_type=EntityType.BINARY_SENSOR),
    _reg("obstacle_count_low", REG_OBSTACLE_COUNT_LOW, "Obstacle Count Low", "read"),
    _reg("obstacle_count_high", REG_OBSTACLE_COUNT_HIGH, "Obstacle Count High", "read"),
    _reg("temp_warnings", REG_TEMP_WARNINGS, "Temperature Warnings", "read"),
    _reg("adc_healthy", REG_ADC_HEALTHY, "ADC Healthy", "read", entity_type=EntityType.BINARY_SENSOR),
    _reg("adc_heartbeat_low", REG_ADC_HEARTBEAT_LOW, "ADC Heartbeat Low", "read", "µs"),
    _reg("adc_heartbeat_high", REG_ADC_HEARTBEAT_HIGH, "ADC Heartbeat High", "read", "µs"),
    _reg("last_peak_current", REG_LAST_PEAK_CURRENT, "Last Peak Current", "read", "A", 0.01, device_class="current", accuracy_decimals=2),
    _reg("last_peak_didt", REG_LAST_PEAK_DIDT, "Last Peak dI/dt", "read", "A/s", 0.1),
    _reg("alert_trigger_current", REG_ALERT_TRIGGER_CURRENT, "Alert Trigger Current", "read", "A", 0.01, device_class="current", accuracy_decimals=2),
    _reg("alert_trigger_didt", REG_ALERT_TRIGGER_DIDT, "Alert Trigger dI/dt", "read", "A/s", 0.1),
    _reg("alert_trigger_valid", REG_ALERT_TRIGGER_VALID, "Alert Trigger Valid", "read", entity_type=EntityType.BINARY_SENSOR),
    _reg("current_current_max", REG_CURRENT_CURRENT_MAX, "Max Current In Last Cycle", "read", "A", 0.01, device_class="current", accuracy_decimals=2),
    _reg("cal_status", REG_CAL_STATUS, "Calibration Status", "read", entity_type=EntityType.BINARY_SENSOR),
    _reg("cal_up_time_low", REG_CAL_UP_TIME_LOW, "Cal Up Time Low", "rw", "ms", category="config"),
    _reg("cal_up_time_high", REG_CAL_UP_TIME_HIGH, "Cal Up Time High", "rw", "ms", category="config"),
    _reg("cal_down_time_low", REG_CAL_DOWN_TIME_LOW, "Cal Down Time Low", "rw", "ms", category="config"),
    _reg("cal_down_time_high", REG_CAL_DOWN_TIME_HIGH, "Cal Down Time High", "rw", "ms", category="config"),
    _reg("fw_version_major", REG_FW_VERSION_MAJOR, "FW Version Major", "read"),
    _reg("fw_version_minor", REG_FW_VERSION_MINOR, "FW Version Minor", "read"),
    _reg("fw_version_patch", REG_FW_VERSION_PATCH, "FW Version Patch", "read"),
    _reg("hw_version", REG_HW_VERSION, "HW Version", "read"),
    _reg("flash_size_mb", REG_FLASH_SIZE_MB, "Flash Size", "read", "MB"),
    _reg("active_partition", REG_ACTIVE_PARTITION, "Active Partition", "read"),
    _reg("ota_state", REG_OTA_STATE, "OTA State", "read", entity_type=EntityType.TEXT_SENSOR, enum=OTA_STATES),
    _reg("ota_error_code", REG_OTA_ERROR_CODE, "OTA Error Code", "read", entity_type=EntityType.TEXT_SENSOR, enum=OTA_ERRORS),
]

REGISTER_MAP = {r.address: r for r in REGISTER_DEFS}
REGISTER_BY_SYMBOL = {r.symbol: r for r in REGISTER_DEFS}
REGISTER_BY_NAME = {r.name.lower().replace(" ", "_"): r for r in REGISTER_DEFS}
READABLE_REGISTERS = [r for r in REGISTER_DEFS if r.access in ("read", "rw")]

ALERT_FLAGS = {
    0: "OVERCURRENT",
    1: "OVERTEMP_NTC",
    2: "TIMEOUT",
    3: "EMERGENCY_STOP",
    6: "OBSTACLE_DETECTED",
    7: "OVERPOWER",
}

EDITABLE_CONFIG_SYMBOLS = [
    "debounce_time",
    "short_press_time",
    "relay_dead_time",
    "overcurrent_threshold",
    "temp_shutdown_threshold",
    "didt_threshold",
    "motor_voltage",
    "motor_power_nominal",
    "adc_comp_up",
    "adc_comp_down",
    "adc_alert_delay",
    "cal_up_time_low",
    "cal_up_time_high",
    "cal_down_time_low",
    "cal_down_time_high",
]

ADVANCED_READONLY_SYMBOLS = [
    "modbus_address",
    "modbus_baud_rate",
    "modbus_parity",
    "uart0_mode",
    "log_level",
]

WEB_SNAPSHOT_SYMBOLS = sorted(set(
    EDITABLE_CONFIG_SYMBOLS
    + ADVANCED_READONLY_SYMBOLS
    + [
        "system_state",
        "current_position",
        "relay_state",
        "alert_flags_low",
        "alert_flags_high",
        "button_state",
        "config_modified",
        "emergency_stop",
        "image_pending_confirm",
        "current_instant",
        "current_rms",
        "current_envelope",
        "current_baseline",
        "motor_power",
        "di_dt",
        "ntc_temp",
        "temp_max",
        "obstacle_detected",
        "obstacle_count_low",
        "obstacle_count_high",
        "temp_warnings",
        "adc_healthy",
        "adc_heartbeat_low",
        "adc_heartbeat_high",
        "last_peak_current",
        "last_peak_didt",
        "alert_trigger_current",
        "alert_trigger_didt",
        "alert_trigger_valid",
        "current_current_max",
        "cal_status",
        "fw_version_major",
        "fw_version_minor",
        "fw_version_patch",
        "hw_version",
        "flash_size_mb",
        "active_partition",
        "ota_state",
        "ota_error_code",
    ]
))
WEB_SNAPSHOT_REGISTERS = sorted(
    [REGISTER_BY_SYMBOL[s] for s in WEB_SNAPSHOT_SYMBOLS],
    key=lambda r: r.address,
) if "REGISTER_BY_SYMBOL" in globals() else []


def decode_register(reg: RegisterDef, raw_value: int) -> Any:
    value = raw_value
    if reg.signed and value > 32767:
        value -= 65536
    scaled = value * reg.scale + reg.offset
    if reg.enum is not None:
        return reg.enum.get(value, f"UNKNOWN({value})")
    if reg.entity_type == EntityType.BINARY_SENSOR:
        return bool(value)
    if reg.scale == 1.0 and reg.offset == 0.0:
        return int(value)
    return scaled


def encode_register(reg: RegisterDef, value: Any) -> int:
    if reg.access != "rw":
        raise ValueError(f"{reg.symbol} is not writable")
    if reg.enum is not None and isinstance(value, str):
        normalized = value.strip().lower()
        reverse = {label.lower(): raw for raw, label in reg.enum.items()}
        if normalized not in reverse:
            raise ValueError(f"{reg.symbol} must be one of {sorted(reg.enum.values())}")
        value = reverse[normalized]
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{reg.symbol} must be numeric") from None
    if reg.min_value is not None and numeric < reg.min_value:
        raise ValueError(f"{reg.symbol} must be >= {reg.min_value:g}")
    if reg.max_value is not None and numeric > reg.max_value:
        raise ValueError(f"{reg.symbol} must be <= {reg.max_value:g}")
    raw = int(round((numeric - reg.offset) / reg.scale))
    if not -32768 <= raw <= 65535:
        raise ValueError(f"{reg.symbol} encoded value out of 16-bit range")
    if raw < 0:
        raw = 65536 + raw
    return raw


def register_to_web(reg: RegisterDef, value: Any = None, raw_value: int | None = None) -> dict[str, Any]:
    return {
        "symbol": reg.symbol,
        "address": reg.address,
        "name": reg.name,
        "access": reg.access,
        "unit": reg.unit,
        "value": value,
        "raw": raw_value,
        "scale": reg.scale,
        "signed": reg.signed,
        "offset": reg.offset,
        "accuracy_decimals": reg.accuracy_decimals,
        "enum": reg.enum,
        "min": reg.min_value,
        "max": reg.max_value,
        "category": reg.category,
    }


def decode_alert_flags(low: int, high: int) -> list[str]:
    flags = ((high & 0xFFFF) << 16) | (low & 0xFFFF)
    return [name for bit, name in ALERT_FLAGS.items() if flags & (1 << bit)]


def selected_registers(configured: Any) -> list[RegisterDef]:
    if configured is None or configured == "all":
        return list(READABLE_REGISTERS)
    if isinstance(configured, str):
        configured = [configured]

    selected: list[RegisterDef] = []
    seen: set[int] = set()
    for item in configured:
        key = str(item).strip().lower()
        key = key[4:] if key.startswith("reg_") else key
        key = key.replace(" ", "_").replace("-", "_")
        reg = REGISTER_BY_SYMBOL.get(key) or REGISTER_BY_NAME.get(key)
        if reg is None:
            raise ValueError(f"Unknown Rolettini readable attribute {item!r}")
        if reg.access not in ("read", "rw"):
            raise ValueError(f"Rolettini attribute {item!r} is not readable")
        if reg.address not in seen:
            selected.append(reg)
            seen.add(reg.address)
    return sorted(selected, key=lambda r: r.address)


def contiguous_groups(registers: list[RegisterDef]) -> list[tuple[int, int]]:
    if not registers:
        return []
    addrs = sorted({r.address for r in registers})
    groups = []
    start = prev = addrs[0]
    for addr in addrs[1:]:
        if addr == prev + 1:
            prev = addr
            continue
        groups.append((start, prev - start + 1))
        start = prev = addr
    groups.append((start, prev - start + 1))
    return groups


class RolettiniDevice:
    """Rolettini blind-controller adapter."""

    WEB_UI = "rolettini"

    def __init__(self, info: DeviceInfo):
        self.info = info
        cfg = info.config
        regs = selected_registers(cfg.get("readable_attributes", "all"))
        poll_regs_by_addr = {r.address: r for r in regs}
        for reg in WEB_SNAPSHOT_REGISTERS:
            poll_regs_by_addr.setdefault(reg.address, reg)
        for addr in (REG_CURRENT_POSITION, REG_SYSTEM_STATE):
            poll_regs_by_addr.setdefault(addr, REGISTER_MAP[addr])
        self.entity_registers = {r.symbol: r for r in regs}
        self.poll_registers_by_addr = dict(sorted(poll_regs_by_addr.items()))
        self.read_groups = contiguous_groups(list(self.poll_registers_by_addr.values()))
        self.raw_by_addr: dict[int, int] = {}
        self.entities: list[Entity] = []

    def build_entities(self, bus=None) -> list[Entity]:
        entities: list[Entity] = []
        base = KEY_ROLETTINI_BASE + self.info.index * KEY_DEVICE_STRIDE
        entities.append(Entity(
            key=base,
            name=self.info.name,
            object_id=f"{self.info.id}_cover",
            entity_type=EntityType.COVER,
            device_id=self.info.id,
            supports_position=True,
        ))
        for i, reg in enumerate(self.entity_registers.values()):
            entities.append(Entity(
                key=base + 100 + i,
                name=f"{self.info.name} {reg.name}",
                object_id=f"{self.info.id}_{reg.symbol}",
                entity_type=reg.entity_type,
                device_id=self.info.id,
                device_class=reg.device_class,
                unit_of_measurement=reg.unit,
                accuracy_decimals=reg.accuracy_decimals,
                register_name=reg.symbol,
            ))
        for offset, command_name, name in (
            (0, "top_bottom_calibration", "Top/Bottom Calibration"),
            (1, "current_position_calibration", "Current Position Calibration"),
        ):
            entities.append(Entity(
                key=base + 900 + offset,
                name=f"{self.info.name} {name}",
                object_id=f"{self.info.id}_{command_name}",
                entity_type=EntityType.BUTTON,
                device_id=self.info.id,
                command_name=command_name,
            ))
        self.entities = entities
        return entities

    def poll(self, bus) -> dict[int, Any]:
        raw_by_addr: dict[int, int] = {}
        for start, count in self.read_groups:
            regs = bus.read_registers(start, count, functioncode=3)
            for i, raw in enumerate(regs):
                raw_by_addr[start + i] = raw
        self.raw_by_addr = raw_by_addr
        decoded = {}
        for addr, raw in raw_by_addr.items():
            reg = self.poll_registers_by_addr.get(addr)
            if reg is not None:
                decoded[reg.symbol] = decode_register(reg, raw)

        values: dict[int, Any] = {}
        for entity in self.entities:
            if entity.entity_type == EntityType.BUTTON:
                continue
            if entity.entity_type == EntityType.COVER:
                raw_pos = raw_by_addr.get(REG_CURRENT_POSITION)
                if raw_pos is None:
                    continue
                raw_state = raw_by_addr.get(REG_SYSTEM_STATE, 0)
                pos = max(0.0, min(1.0, raw_pos / 100.0))
                op = 1 if raw_state == 2 else 2 if raw_state == 3 else 0
                values[entity.key] = (pos, op)
            elif entity.register_name:
                values[entity.key] = decoded.get(entity.register_name)
        return values

    def web_read(self, view: str, state: dict[int, Any], payload: dict[str, Any] | None = None) -> Any:
        if view not in ("readings", "snapshot", "rolettini"):
            raise ValueError(f"Unsupported Rolettini view {view!r}")
        return self._snapshot_from_raw(self.raw_by_addr)

    def prepare_write(self, action: str, payload: dict[str, Any] | None = None) -> QueuedWrite:
        payload = dict(payload or {})
        if action == "stop":
            return QueuedWrite(action, payload, lambda bus: bus.write_hr(REG_MOVEMENT_STOP, 1), "rolettini stop")

        if action in ("cover", "set_position"):
            stop = bool(payload.get("stop", False))
            value = payload.get("position", payload.get("value"))
            if stop:
                return QueuedWrite(action, payload, lambda bus: bus.write_hr(REG_MOVEMENT_STOP, 1), "rolettini stop")
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                raise ValueError("set_position requires numeric value") from None
            pos = max(0, min(100, round(numeric * 100))) if action == "cover" else int(round(numeric))
            if not 0 <= pos <= 100:
                raise ValueError("position must be 0-100")
            return QueuedWrite(action, payload, lambda bus, pos=pos: bus.write_hr(REG_TARGET_POSITION, pos),
                               f"rolettini set_position value={pos}")

        if action == "config":
            fields = payload.get("fields", payload)
            if not isinstance(fields, dict):
                raise ValueError("config payload must be an object")
            writes: list[tuple[RegisterDef, int]] = []
            editable = set(EDITABLE_CONFIG_SYMBOLS)
            for symbol, value in fields.items():
                symbol_str = str(symbol)
                reg = REGISTER_BY_SYMBOL.get(symbol_str)
                if reg is None:
                    raise ValueError(f"Unknown Rolettini config field {symbol!r}")
                if symbol_str not in editable:
                    raise ValueError(f"{symbol_str} is not editable from the web UI")
                writes.append((reg, encode_register(reg, value)))
            return QueuedWrite(
                action,
                payload,
                lambda bus, writes=writes: [bus.write_hr(reg.address, raw) for reg, raw in writes],
                "rolettini config",
            )

        command_map = {
            "button_top_bottom_calibration": CMD_START_CALIBRATION,
            "button_current_position_calibration": CMD_START_POSITION_CAL,
            "top_bottom_calibration": CMD_START_CALIBRATION,
            "current_position_calibration": CMD_START_POSITION_CAL,
            "emergency_stop": CMD_EMERGENCY_STOP,
            "clear_alerts": CMD_CLEAR_ALERTS,
            "clear_emergency": CMD_CLEAR_EMERGENCY,
            "save_config": CMD_SAVE_CONFIG,
            "reset_statistics": CMD_RESET_STATISTICS,
            "reboot": CMD_REBOOT_SYSTEM,
        }
        if action == "button":
            action = f"button_{payload.get('command_name', '')}"
        cmd = command_map.get(action)
        if cmd is None:
            raise ValueError(f"Unknown Rolettini command {action!r}")
        return QueuedWrite(action, payload, lambda bus, cmd=cmd: bus.write_hr(REG_CONTROL_CMD, cmd),
                           f"rolettini command action={action} value={cmd}")

    def close(self) -> None:
        pass

    def _snapshot_from_raw(self, raw_by_addr: dict[int, int]) -> dict:
        decoded: dict[str, Any] = {}
        registers: dict[str, dict] = {}
        for reg in WEB_SNAPSHOT_REGISTERS:
            raw = raw_by_addr.get(reg.address, 0)
            value = decode_register(reg, raw)
            decoded[reg.symbol] = value
            registers[reg.symbol] = register_to_web(reg, value, raw)

        config_symbols = set(EDITABLE_CONFIG_SYMBOLS)
        advanced_symbols = set(ADVANCED_READONLY_SYMBOLS)
        config_fields = [registers[s] for s in EDITABLE_CONFIG_SYMBOLS if s in registers]
        advanced_fields = [registers[s] for s in ADVANCED_READONLY_SYMBOLS if s in registers]
        diagnostics = [
            data for symbol, data in registers.items()
            if symbol not in config_symbols and symbol not in advanced_symbols
        ]
        fw = ".".join(str(decoded.get(s, 0)) for s in (
            "fw_version_major", "fw_version_minor", "fw_version_patch"
        ))
        obstacle_count = (
            (raw_by_addr.get(REG_OBSTACLE_COUNT_HIGH, 0) << 16)
            | raw_by_addr.get(REG_OBSTACLE_COUNT_LOW, 0)
        )
        adc_heartbeat_us = (
            (raw_by_addr.get(REG_ADC_HEARTBEAT_HIGH, 0) << 16)
            | raw_by_addr.get(REG_ADC_HEARTBEAT_LOW, 0)
        )
        cal_up_time_ms = (
            (raw_by_addr.get(REG_CAL_UP_TIME_HIGH, 0) << 16)
            | raw_by_addr.get(REG_CAL_UP_TIME_LOW, 0)
        )
        cal_down_time_ms = (
            (raw_by_addr.get(REG_CAL_DOWN_TIME_HIGH, 0) << 16)
            | raw_by_addr.get(REG_CAL_DOWN_TIME_LOW, 0)
        )
        return {
            "id": self.info.id,
            "name": self.info.name,
            "type": self.info.type,
            "available": self.info.available,
            "status": {
                "position": decoded.get("current_position"),
                "system_state": decoded.get("system_state"),
                "relay_state": decoded.get("relay_state"),
                "calibrated": decoded.get("cal_status"),
                "config_modified": decoded.get("config_modified"),
                "emergency_stop": decoded.get("emergency_stop"),
                "alerts": decode_alert_flags(
                    raw_by_addr.get(REG_ALERT_FLAGS_LOW, 0),
                    raw_by_addr.get(REG_ALERT_FLAGS_HIGH, 0),
                ),
            },
            "config": config_fields,
            "advanced": advanced_fields,
            "diagnostics": diagnostics,
            "derived": {
                "firmware_version": fw,
                "obstacle_count": obstacle_count,
                "adc_heartbeat_us": adc_heartbeat_us,
                "cal_up_time_ms": cal_up_time_ms,
                "cal_down_time_ms": cal_down_time_ms,
            },
            "commands": {
                "set_position": True,
                "stop": True,
                "top_bottom_calibration": True,
                "current_position_calibration": True,
                "emergency_stop": True,
                "clear_alerts": True,
                "clear_emergency": True,
                "save_config": True,
                "reset_statistics": True,
                "reboot": True,
            },
        }
