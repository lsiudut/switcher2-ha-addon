"""DDS/DTS1946 power meter register definitions and decoding."""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence

from entities import Entity, EntityType
from devices.base import DeviceInfo, KEY_DEVICE_STRIDE, KEY_METER_BASE, QueuedWrite


class Kind(str, Enum):
    UINT16 = "uint16"
    INT16 = "int16"
    UINT32 = "uint32"
    INT32 = "int32"
    FLOAT32 = "float32"


@dataclass(frozen=True)
class Param:
    name: str
    address: int
    count: int
    kind: Kind
    unit: str = ""
    scale: float = 1.0
    description: str = ""
    device_class: str = ""
    accuracy_decimals: int = 2


def _s16(x: int) -> int:
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x


def _regs_to_u32(regs: Sequence[int], wordorder: str) -> int:
    if len(regs) != 2:
        raise ValueError("u32 needs exactly 2 registers")
    a, b = regs
    if wordorder == "ba":
        a, b = b, a
    elif wordorder != "ab":
        raise ValueError("wordorder must be ab or ba")
    return ((a & 0xFFFF) << 16) | (b & 0xFFFF)


def decode(param: Param, regs: Sequence[int], wordorder: str) -> Any:
    if param.kind == Kind.UINT16:
        value = regs[0] & 0xFFFF
    elif param.kind == Kind.INT16:
        value = _s16(regs[0])
    elif param.kind == Kind.UINT32:
        value = _regs_to_u32(regs, wordorder)
    elif param.kind == Kind.INT32:
        raw = _regs_to_u32(regs, wordorder)
        value = raw - 0x100000000 if raw & 0x80000000 else raw
    elif param.kind == Kind.FLOAT32:
        import struct
        value = struct.unpack(">f", _regs_to_u32(regs, wordorder).to_bytes(4, "big"))[0]
    else:
        raise ValueError(param.kind)
    return value * param.scale if param.scale != 1.0 else value


def measurement_params_1p() -> list[Param]:
    return [
        Param("U", 0x0200, 1, Kind.UINT16, "V", 0.1, "Voltage", "voltage", 1),
        Param("I", 0x0201, 1, Kind.UINT16, "A", 0.01, "Current", "current", 2),
        Param("P", 0x0202, 1, Kind.INT16, "W", 10, "Active power", "power", 0),
        Param("Q", 0x0203, 1, Kind.INT16, "var", 10, "Reactive power", "reactive_power", 0),
        Param("S", 0x0204, 1, Kind.UINT16, "VA", 10, "Apparent power", "apparent_power", 0),
        Param("PF", 0x0205, 1, Kind.INT16, "", 0.001, "Power factor", "power_factor", 3),
        Param("F", 0x0206, 1, Kind.UINT16, "Hz", 0.01, "Frequency", "frequency", 2),
        Param("EP_plus", 0x0106, 2, Kind.UINT32, "Wh", 10, "Import active energy", "energy", 0),
        Param("EP_minus", 0x0108, 2, Kind.UINT32, "Wh", 10, "Export active energy", "energy", 0),
        Param("EQ_plus", 0x010A, 2, Kind.UINT32, "varh", 10, "Import reactive energy", "", 0),
        Param("EQ_minus", 0x010C, 2, Kind.UINT32, "varh", 10, "Export reactive energy", "", 0),
    ]


def measurement_params_3p() -> list[Param]:
    return [
        Param("Ua", 0x0200, 1, Kind.UINT16, "V", 0.1, "Phase A voltage", "voltage", 1),
        Param("Ub", 0x0201, 1, Kind.UINT16, "V", 0.1, "Phase B voltage", "voltage", 1),
        Param("Uc", 0x0202, 1, Kind.UINT16, "V", 0.1, "Phase C voltage", "voltage", 1),
        Param("Uab", 0x0203, 1, Kind.UINT16, "V", 0.1, "AB voltage", "voltage", 1),
        Param("Ubc", 0x0204, 1, Kind.UINT16, "V", 0.1, "BC voltage", "voltage", 1),
        Param("Uca", 0x0205, 1, Kind.UINT16, "V", 0.1, "CA voltage", "voltage", 1),
        Param("Ia", 0x0206, 1, Kind.UINT16, "A", 0.01, "Phase A current", "current", 2),
        Param("Ib", 0x0207, 1, Kind.UINT16, "A", 0.01, "Phase B current", "current", 2),
        Param("Ic", 0x0208, 1, Kind.UINT16, "A", 0.01, "Phase C current", "current", 2),
        Param("Pa", 0x0209, 1, Kind.INT16, "W", 10, "Phase A active power", "power", 0),
        Param("Pb", 0x020A, 1, Kind.INT16, "W", 10, "Phase B active power", "power", 0),
        Param("Pc", 0x020B, 1, Kind.INT16, "W", 10, "Phase C active power", "power", 0),
        Param("P", 0x020C, 1, Kind.INT16, "W", 10, "Total active power", "power", 0),
        Param("Qa", 0x020D, 1, Kind.INT16, "var", 10, "Phase A reactive power", "reactive_power", 0),
        Param("Qb", 0x020E, 1, Kind.INT16, "var", 10, "Phase B reactive power", "reactive_power", 0),
        Param("Qc", 0x020F, 1, Kind.INT16, "var", 10, "Phase C reactive power", "reactive_power", 0),
        Param("Q", 0x0210, 1, Kind.INT16, "var", 10, "Total reactive power", "reactive_power", 0),
        Param("Sa", 0x0211, 1, Kind.UINT16, "VA", 10, "Phase A apparent power", "apparent_power", 0),
        Param("Sb", 0x0212, 1, Kind.UINT16, "VA", 10, "Phase B apparent power", "apparent_power", 0),
        Param("Sc", 0x0213, 1, Kind.UINT16, "VA", 10, "Phase C apparent power", "apparent_power", 0),
        Param("S", 0x0214, 1, Kind.UINT16, "VA", 10, "Total apparent power", "apparent_power", 0),
        Param("PFa", 0x0215, 1, Kind.INT16, "", 0.001, "Phase A power factor", "power_factor", 3),
        Param("PFb", 0x0216, 1, Kind.INT16, "", 0.001, "Phase B power factor", "power_factor", 3),
        Param("PFc", 0x0217, 1, Kind.INT16, "", 0.001, "Phase C power factor", "power_factor", 3),
        Param("PF", 0x0218, 1, Kind.INT16, "", 0.001, "Total power factor", "power_factor", 3),
        Param("F", 0x0219, 1, Kind.UINT16, "Hz", 0.01, "Frequency", "frequency", 2),
        Param("EP_plus", 0x0106, 2, Kind.UINT32, "Wh", 10, "Import active energy", "energy", 0),
        Param("EP_minus", 0x0108, 2, Kind.UINT32, "Wh", 10, "Export active energy", "energy", 0),
        Param("EQ_plus", 0x010A, 2, Kind.UINT32, "varh", 10, "Import reactive energy", "", 0),
        Param("EQ_minus", 0x010C, 2, Kind.UINT32, "varh", 10, "Export reactive energy", "", 0),
    ]


def measurement_params(model: str) -> Mapping[str, Param]:
    params = measurement_params_3p() if model == "3p" else measurement_params_1p()
    return {p.name: p for p in params}


class Dds1946Device:
    """DDS/DTS1946 power-meter adapter."""

    WEB_UI = "power_meter"

    def __init__(self, info: DeviceInfo):
        self.info = info
        cfg = info.config
        self.model = str(cfg.get("model", "3p"))
        self.params = measurement_params(self.model)
        self.requested = list(cfg.get("parameters") or self.params.keys())
        self.wordorder = str(cfg.get("wordorder", "ab"))
        self.read_fc = int(cfg.get("read_fc", 3))
        self.entities: list[Entity] = []

    def build_entities(self, bus=None) -> list[Entity]:
        entities: list[Entity] = []
        base = KEY_METER_BASE + self.info.index * KEY_DEVICE_STRIDE
        for i, name in enumerate(self.requested):
            if name not in self.params:
                continue
            p = self.params[name]
            safe = "".join(c.lower() if c.isalnum() else "_" for c in name).strip("_")
            entities.append(Entity(
                key=base + i,
                name=f"{self.info.name} {p.description or name}",
                object_id=f"{self.info.id}_{safe}",
                entity_type=EntityType.SENSOR,
                device_id=self.info.id,
                device_class=p.device_class,
                unit_of_measurement=p.unit,
                accuracy_decimals=p.accuracy_decimals,
                param_name=name,
            ))
        self.entities = entities
        return entities

    def poll(self, bus) -> dict[int, Any]:
        values: dict[int, Any] = {}
        for entity in self.entities:
            p = self.params[entity.param_name]
            regs = bus.read_registers(p.address, p.count, functioncode=self.read_fc)
            values[entity.key] = decode(p, regs, self.wordorder)
        return values

    def web_read(self, view: str, state: dict[int, Any], payload: dict[str, Any] | None = None) -> Any:
        if view != "readings":
            raise ValueError(f"Unsupported power-meter view {view!r}")
        readings = []
        for entity in self.entities:
            param = self.params.get(entity.param_name)
            readings.append({
                "key": entity.key,
                "name": entity.name,
                "parameter": entity.param_name,
                "description": getattr(param, "description", "") or entity.param_name,
                "value": state.get(entity.key),
                "unit": entity.unit_of_measurement,
                "device_class": entity.device_class,
                "accuracy_decimals": entity.accuracy_decimals,
            })
        return {
            "id": self.info.id,
            "name": self.info.name,
            "type": self.info.type,
            "available": self.info.available,
            "readings": readings,
        }

    def prepare_write(self, action: str, payload: dict[str, Any] | None = None) -> QueuedWrite:
        raise ValueError(f"Power meter does not support write action {action!r}")

    def close(self) -> None:
        pass
