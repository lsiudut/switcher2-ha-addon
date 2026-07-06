"""switcher2 relay/blind-board adapter."""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import sw2lib

from entities import Entity, EntityType
from devices.base import (
    DeviceInfo,
    KEY_COVER_BASE,
    KEY_DEVICE_STRIDE,
    KEY_INPUT_BASE,
    KEY_LIGHT_BASE,
    KEY_SENSOR_BASE,
    QueuedWrite,
)

log = logging.getLogger(__name__)

CH_TYPE_UNASSIGNED = 0
CH_TYPE_LIGHT = 1
CH_TYPE_BLIND = 2
LIGHT_OFF = 0
LIGHT_ON = 1
LIGHT_TOGGLE = 2
BLIND_STOP = 10001
BLIND_CALIBRATE = 10002


class Switcher2Device:
    """switcher2 board adapter with cached web views."""

    WEB_UI = "switcher2"

    def __init__(self, info: DeviceInfo, names):
        self.info = info
        self._names = names
        self.entities: list[Entity] = []
        self.channel_cfgs: list[int] = []
        self.device_info: dict[str, Any] = {}
        self.live_status: dict[str, Any] = {
            "dirty": False,
            "channel_status": [0] * sw2lib.CHANNEL_MAX,
            "channel_motion": [0] * sw2lib.CHANNEL_MAX,
            "inputs": [0] * sw2lib.INPUT_MAX,
            "relays": [0] * sw2lib.CHANNEL_MAX,
        }
        self.temperatures: list[float | None] = [None] * sw2lib.SENSOR_MAX
        self.debounce: list[int] = [0] * sw2lib.INPUT_MAX
        self.actions: list[list[dict[str, int]]] = [
            [{"action": 0, "channel": 0, "param": 0} for _ in range(sw2lib.BUTTON_EVENT_COUNT)]
            for _ in range(sw2lib.INPUT_MAX)
        ]
        self.zcd: dict[str, Any] = {
            "enabled": False,
            "delays": [-1] * sw2lib.RELAY_MAX,
            "pending": [0] * sw2lib.RELAY_MAX,
            "edge_count": 0,
            "edge_age_ms": 0xFFFF,
            "fallback_count": 0,
        }
        self.serial_config = dict(info.serial)
        self._ota_state_lock = threading.Lock()
        self._ota_state: dict[str, Any] = {
            "phase": "idle",
            "progress": 0.0,
            "error": None,
            "bytes_total": 0,
            "bytes_done": 0,
            "rate_kbs": 0.0,
            "elapsed": 0.0,
        }

    def build_entities(self, bus=None) -> list[Entity]:
        if bus is not None:
            self.refresh_config_cache(bus)
        entities: list[Entity] = []
        key_offset = self.info.index * KEY_DEVICE_STRIDE
        object_prefix = "" if self.info.id == "switcher2" and self.info.index == 0 else f"{self.info.id}_"
        cfgs = self.channel_cfgs
        for ch in range(sw2lib.CHANNEL_MAX):
            ch_type = cfgs[ch * sw2lib.CH_CFG_SIZE] if cfgs else CH_TYPE_UNASSIGNED
            if ch_type == CH_TYPE_LIGHT:
                entities.append(Entity(
                    key=key_offset + KEY_LIGHT_BASE + ch,
                    name=self._names.channel_name(ch),
                    object_id=f"{object_prefix}light_{ch:02d}",
                    entity_type=EntityType.LIGHT,
                    device_id=self.info.id,
                    channel=ch,
                ))
            elif ch_type == CH_TYPE_BLIND:
                entities.append(Entity(
                    key=key_offset + KEY_COVER_BASE + ch,
                    name=self._names.channel_name(ch),
                    object_id=f"{object_prefix}cover_{ch:02d}",
                    entity_type=EntityType.COVER,
                    device_id=self.info.id,
                    supports_position=True,
                    channel=ch,
                ))
        for i in range(sw2lib.INPUT_MAX):
            entities.append(Entity(
                key=key_offset + KEY_INPUT_BASE + i,
                name=self._names.input_name(i),
                object_id=f"{object_prefix}input_{i + 1:02d}",
                entity_type=EntityType.BINARY_SENSOR,
                device_id=self.info.id,
                input_index=i,
            ))
        for i in range(sw2lib.SENSOR_MAX):
            name = "Chip Temperature (RP2350)" if i == sw2lib.SENSOR_CHIP_TEMP_IDX else f"Temperature {i + 1}"
            entities.append(Entity(
                key=key_offset + KEY_SENSOR_BASE + i,
                name=name,
                object_id=f"{object_prefix}temp_{i:02d}",
                entity_type=EntityType.SENSOR,
                device_id=self.info.id,
                device_class="temperature",
                unit_of_measurement="°C",
                accuracy_decimals=1,
                sensor_index=i,
            ))
        self.entities = entities
        return entities

    def poll(self, bus) -> dict[int, Any]:
        dirty = bus.read_hr(sw2lib.HR_CONFIG_DIRTY, 1)[0]
        ch_status = bus.read_ir(sw2lib.IR_STATUS_BASE, sw2lib.CHANNEL_MAX)
        ch_motion = bus.read_ir(sw2lib.IR_MOTION_BASE, sw2lib.CHANNEL_MAX)
        inputs = bus.read_di(sw2lib.DI_INPUT_BASE, sw2lib.INPUT_MAX)
        relays = bus.read_di(sw2lib.DI_RELAY_BASE, sw2lib.CHANNEL_MAX)
        temps_raw = bus.read_ir(sw2lib.IR_TEMP_BASE, sw2lib.SENSOR_MAX)
        self.live_status = {
            "dirty": bool(dirty),
            "channel_status": ch_status,
            "channel_motion": ch_motion,
            "inputs": [1 if b else 0 for b in inputs],
            "relays": [1 if b else 0 for b in relays],
        }
        self.temperatures = [self._decode_temp(raw) for raw in temps_raw]
        self._refresh_zcd_status(bus)
        values: dict[int, Any] = {}
        for entity in self.entities:
            if entity.entity_type == EntityType.LIGHT:
                values[entity.key] = bool(ch_status[entity.channel])
            elif entity.entity_type == EntityType.COVER:
                raw = ch_status[entity.channel]
                pos = 0.0 if raw == 0xFFFF else raw / 10000.0
                values[entity.key] = (pos, ch_motion[entity.channel])
            elif entity.entity_type == EntityType.BINARY_SENSOR:
                values[entity.key] = bool(inputs[entity.input_index])
            elif entity.entity_type == EntityType.SENSOR:
                values[entity.key] = self.temperatures[entity.sensor_index]
        return values

    def refresh_config_cache(self, bus) -> None:
        self.channel_cfgs = sw2lib.read_all_channel_cfgs(bus)
        self.debounce = bus.read_hr(sw2lib.HR_DEBOUNCE_BASE, sw2lib.INPUT_MAX)
        self.actions = []
        for i in range(sw2lib.INPUT_MAX):
            base = sw2lib.HR_ACTION_BASE + i * sw2lib.BUTTON_EVENT_COUNT * 3
            regs = bus.read_hr(base, sw2lib.BUTTON_EVENT_COUNT * 3)
            row = []
            for j in range(sw2lib.BUTTON_EVENT_COUNT):
                b = j * 3
                row.append({"action": regs[b], "channel": regs[b + 1], "param": regs[b + 2]})
            self.actions.append(row)
        regs = bus.read_hr(sw2lib.HR_DEVICE_VER, 10)
        sdk_regs = bus.read_hr(sw2lib.HR_SDK_VERSION, 1)
        git_hash = (regs[sw2lib.HR_BUILD_HASH_HI] << 16) | regs[sw2lib.HR_BUILD_HASH_LO]
        build_ts = (regs[sw2lib.HR_BUILD_TS_HI] << 16) | regs[sw2lib.HR_BUILD_TS_LO]
        fw_ver = regs[sw2lib.HR_FW_VERSION]
        sdk_ver = sdk_regs[0]
        self.device_info = {
            "version": regs[0],
            "dirty": bool(regs[4]),
            "git_hash": f"{git_hash:08x}",
            "build_ts": build_ts,
            "fw_version": f"{fw_ver >> 8}.{fw_ver & 0xFF}",
            "sdk_version": f"{sdk_ver >> 8}.{sdk_ver & 0xFF}",
        }
        self._refresh_zcd_config(bus)

    def web_read(self, view: str, state: dict[int, Any], payload: dict[str, Any] | None = None) -> Any:
        if view == "readings":
            return {
                "id": self.info.id,
                "name": self.info.name,
                "type": self.info.type,
                "available": self.info.available,
                "supported": True,
            }
        if view == "status":
            return {
                "connected": self.info.available,
                "firmware_version": self.device_info.get("version"),
                "git_hash": self.device_info.get("git_hash"),
                "build_ts": self.device_info.get("build_ts"),
                "fw_version": self.device_info.get("fw_version"),
                "sdk_version": self.device_info.get("sdk_version"),
                "temperatures": list(self.temperatures),
                **self.live_status,
            }
        if view == "device_info":
            return dict(self.device_info)
        if view == "channels":
            return self._channels()
        if view == "temperatures":
            return list(self.temperatures)
        if view == "actions":
            return self.actions
        if view == "debounce":
            return list(self.debounce)
        if view == "zcd":
            return {
                **self.zcd,
                "delays": list(self.zcd["delays"]),
                "pending": list(self.zcd["pending"]),
            }
        if view == "serial":
            return dict(self.serial_config)
        if view == "ota_status":
            with self._ota_state_lock:
                return dict(self._ota_state)
        raise ValueError(f"Unsupported switcher2 view {view!r}")

    def prepare_write(self, action: str, payload: dict[str, Any] | None = None) -> QueuedWrite:
        payload = dict(payload or {})
        if action == "light":
            ch = int(payload["channel"])
            state = bool(payload["state"])
            reg = sw2lib.HR_CH_CMD_BASE + ch
            return QueuedWrite(action, payload, lambda bus: bus.write_hr(reg, LIGHT_ON if state else LIGHT_OFF),
                               f"light ch={ch} state={state}")
        if action == "cover":
            ch = int(payload["channel"])
            stop = bool(payload.get("stop", False))
            position = payload.get("position")
            reg = sw2lib.HR_CH_CMD_BASE + ch
            def write(bus):
                if stop:
                    bus.write_hr(reg, BLIND_STOP)
                elif position is not None:
                    bus.write_hr(reg, max(0, min(10000, round(float(position) * 10000))))
            return QueuedWrite(action, payload, write, f"cover ch={ch} stop={stop} position={position}")
        if action == "channel_cmd":
            ch = int(payload["channel"])
            value = int(payload["value"])
            return QueuedWrite(action, payload, lambda bus: bus.write_hr(sw2lib.HR_CH_CMD_BASE + ch, value),
                               f"switcher channel ch={ch} value={value}")
        if action == "channel_config":
            ch = int(payload["channel"])
            vals = self._encode_channel_config(payload)
            def write(bus):
                bus.write_hrs(sw2lib.HR_CH_CFG_BASE + ch * sw2lib.CH_CFG_SIZE, vals)
                self._write_channel_cache(ch, vals)
            return QueuedWrite(action, payload, write, f"switcher channel config ch={ch}")
        if action == "action":
            inp = int(payload["input"])
            ev = int(payload["event"])
            vals = [int(payload["action_code"]), int(payload["channel"]), int(payload["param"])]
            base = sw2lib.HR_ACTION_BASE + inp * sw2lib.BUTTON_EVENT_COUNT * 3 + ev * 3
            def write(bus):
                bus.write_hrs(base, vals)
                self.actions[inp][ev] = {"action": vals[0], "channel": vals[1], "param": vals[2]}
            return QueuedWrite(action, payload, write, f"switcher input action inp={inp} ev={ev}")
        if action == "debounce":
            inp = int(payload["input"])
            ms = int(payload["ms"])
            def write(bus):
                bus.write_hr(sw2lib.HR_DEBOUNCE_BASE + inp, ms)
                self.debounce[inp] = ms
            return QueuedWrite(action, payload, write, f"switcher debounce inp={inp} ms={ms}")
        if action == "zcd_config":
            enabled = payload["enabled"]
            delays = [int(v) for v in payload["delays"]]
            if not isinstance(enabled, bool):
                raise ValueError("ZCD enabled must be boolean")
            if len(delays) != sw2lib.RELAY_MAX:
                raise ValueError(f"ZCD delays must contain {sw2lib.RELAY_MAX} relay values")
            regs = [self._encode_zcd_delay(v) for v in delays]
            def write(bus):
                bus.write_hr(sw2lib.HR_ZCD_GLOBAL, 1 if enabled else 0)
                bus.write_hrs(sw2lib.HR_ZCD_DELAY_BASE, regs)
                self.zcd["enabled"] = enabled
                self.zcd["delays"] = list(delays)
            return QueuedWrite(action, payload, write, "switcher ZCD config")
        if action == "config_save":
            return QueuedWrite(action, payload, lambda bus: bus.write_hr(sw2lib.HR_CONFIG_SAVE, sw2lib.SAVE_MAGIC),
                               "switcher config save")
        if action == "config_reset":
            return QueuedWrite(action, payload, lambda bus: bus.write_hr(sw2lib.HR_CONFIG_RESET, sw2lib.SAVE_MAGIC),
                               "switcher config reset")
        if action == "config_discard":
            return QueuedWrite(action, payload, lambda bus: bus.write_hr(sw2lib.HR_CONFIG_DISC, sw2lib.SAVE_MAGIC),
                               "switcher config discard")
        if action == "reboot":
            return QueuedWrite(action, payload, lambda bus: bus.write_hr(sw2lib.HR_SYS_REBOOT, sw2lib.SAVE_MAGIC),
                               "switcher reboot")
        if action == "serial":
            cfg = dict(payload["config"])
            return QueuedWrite(action, payload, lambda _bus: self._set_serial_config(cfg),
                               "switcher serial config")
        if action == "ota_abort":
            return QueuedWrite(action, payload, lambda bus: bus.write_hr(sw2lib.HR_OTA_CMD, sw2lib.OTA_CMD_ABORT),
                               "switcher ota abort")
        if action == "ota_trial":
            return QueuedWrite(action, payload, lambda bus: bus.write_hr(sw2lib.HR_TRIAL_BOOT, sw2lib.SAVE_MAGIC),
                               "switcher ota trial")
        if action == "ota_flash":
            image_bytes = bytes(payload["image_bytes"])
            trial = bool(payload.get("trial", False))
            return QueuedWrite(action, {"trial": trial}, lambda bus: self._ota_flash_on_bus(bus, image_bytes, trial),
                               f"switcher ota flash size={len(image_bytes)} trial={trial}")
        raise ValueError(f"Unknown switcher2 write action {action!r}")

    def set_channel_name(self, ch: int, name: str) -> None:
        self._names.set_channel(ch, name)
        for e in self.entities:
            if e.channel == ch and e.entity_type in (EntityType.LIGHT, EntityType.COVER):
                e.name = self._names.channel_name(ch)
                break

    def set_input_name(self, inp: int, name: str) -> None:
        self._names.set_input(inp, name)
        for e in self.entities:
            if e.input_index == inp and e.entity_type == EntityType.BINARY_SENSOR:
                e.name = self._names.input_name(inp)
                break

    def update_web_metadata(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if action == "channel_name":
            self.set_channel_name(int(payload["channel"]), str(payload.get("name", "")).strip())
            return {"ok": True, "ha_reconnect": True}
        if action == "input_name":
            self.set_input_name(int(payload["input"]), str(payload.get("name", "")).strip())
            return {"ok": True}
        raise ValueError(f"Unknown switcher2 metadata action {action!r}")

    def close(self) -> None:
        pass

    def _channels(self) -> list[dict[str, Any]]:
        s = sw2lib.CH_CFG_SIZE
        result = []
        status = self.live_status["channel_status"]
        motion = self.live_status["channel_motion"]
        for i in range(sw2lib.CHANNEL_MAX):
            b = i * s
            row = self.channel_cfgs[b:b + s] if self.channel_cfgs else [0] * s
            typ, f1, f2, f3, f4 = row[0], row[1], row[2], row[3], row[4]
            t_open, t_close, off_delay = row[5], row[6], row[7]
            default_on = row[8] if s >= 9 else 0
            if typ == CH_TYPE_LIGHT:
                relay_mask = f1 | (f2 << 16) | (f3 << 32) | (f4 << 48)
                relay_a = relay_b = 0
            else:
                relay_mask = 0
                relay_a, relay_b = f1, f2
            result.append({
                "ch": i,
                "name": self._names.channel_name(i),
                "type": typ,
                "relay_mask": relay_mask,
                "relay_a": relay_a,
                "relay_b": relay_b,
                "travel_ms_open": t_open,
                "travel_ms_close": t_close,
                "light_off_delay_s": off_delay,
                "light_default_on": bool(default_on),
                "status": status[i] if i < len(status) else 0,
                "motion": motion[i] if i < len(motion) else 0,
            })
        return result

    @staticmethod
    def _decode_temp(raw: int) -> float | None:
        if raw == sw2lib.TEMP_NO_READING:
            return None
        signed = raw if raw < 0x8000 else raw - 0x10000
        return signed / 10.0

    @staticmethod
    def _encode_channel_config(payload: dict[str, Any]) -> list[int]:
        type_ = int(payload["type"])
        relay_a = int(payload.get("relay_a", 0))
        relay_b = int(payload.get("relay_b", 0))
        t_open = int(payload.get("travel_ms_open", 0))
        t_close = int(payload.get("travel_ms_close", 0))
        off_delay = int(payload.get("light_off_delay_s", 0))
        default_on = int(bool(payload.get("light_default_on", False)))
        if type_ == CH_TYPE_LIGHT:
            mask = int(payload.get("relay_mask", relay_a))
            return [
                type_,
                mask & 0xFFFF,
                (mask >> 16) & 0xFFFF,
                (mask >> 32) & 0xFFFF,
                (mask >> 48) & 0xFFFF,
                0,
                0,
                off_delay,
                default_on,
            ]
        return [type_, relay_a, relay_b, 0, 0, t_open, t_close, off_delay, default_on]

    def _write_channel_cache(self, ch: int, vals: list[int]) -> None:
        start = ch * sw2lib.CH_CFG_SIZE
        if not self.channel_cfgs:
            self.channel_cfgs = [0] * (sw2lib.CHANNEL_MAX * sw2lib.CH_CFG_SIZE)
        self.channel_cfgs[start:start + sw2lib.CH_CFG_SIZE] = vals

    def _refresh_zcd_config(self, bus) -> None:
        try:
            regs = bus.read_hr(sw2lib.HR_ZCD_GLOBAL, 1 + sw2lib.RELAY_MAX)
        except sw2lib.ModbusError:
            return
        self.zcd["enabled"] = bool(regs[0])
        self.zcd["delays"] = [self._decode_zcd_delay(raw) for raw in regs[1:1 + sw2lib.RELAY_MAX]]

    def _refresh_zcd_status(self, bus) -> None:
        try:
            regs = bus.read_hr(sw2lib.HR_ZCD_PENDING_BASE, sw2lib.RELAY_MAX + 3)
        except sw2lib.ModbusError:
            return
        self.zcd["pending"] = [1 if raw else 0 for raw in regs[:sw2lib.RELAY_MAX]]
        self.zcd["edge_count"] = int(regs[sw2lib.RELAY_MAX])
        self.zcd["edge_age_ms"] = int(regs[sw2lib.RELAY_MAX + 1])
        self.zcd["fallback_count"] = int(regs[sw2lib.RELAY_MAX + 2])

    @staticmethod
    def _decode_zcd_delay(raw: int) -> int:
        raw &= 0xFFFF
        return raw if raw < 0x8000 else raw - 0x10000

    @staticmethod
    def _encode_zcd_delay(value: int) -> int:
        if value < -1 or value > 32767:
            raise ValueError("ZCD delay must be -1 or 0-32767 ms")
        return value & 0xFFFF

    def _set_serial_config(self, cfg: dict[str, Any]) -> None:
        self.serial_config = dict(cfg)
        self.info.serial = dict(cfg)

    def _ota_set_state(self, **kw) -> None:
        with self._ota_state_lock:
            self._ota_state.update(kw)

    def _ota_flash_on_bus(self, bus, image_bytes: bytes, trial: bool) -> None:
        with self._ota_state_lock:
            if self._ota_state["phase"] not in ("idle", "done", "error"):
                raise sw2lib.ModbusError("OTA already in progress")
            self._ota_state = {
                "phase": "starting",
                "progress": 0.0,
                "error": None,
                "bytes_total": len(image_bytes),
                "bytes_done": 0,
                "rate_kbs": 0.0,
                "elapsed": 0.0,
            }
        try:
            image = bytearray(image_bytes)
            if len(image) % 2:
                image += b"\xff"
            size = len(image)
            status = bus.read_hr(sw2lib.HR_OTA_STATUS, 1)[0]
            if status in (1, 2):
                raise sw2lib.ModbusError(f"OTA busy (status={sw2lib.OTA_STATUS_NAMES.get(status)})")
            bus.write_hr(sw2lib.HR_OTA_SIZE_LO, size & 0xFFFF)
            bus.write_hr(sw2lib.HR_OTA_SIZE_HI, (size >> 16) & 0xFFFF)
            bus.write_hr(sw2lib.HR_OTA_CMD, sw2lib.OTA_CMD_BEGIN)
            self._ota_set_state(phase="erasing", bytes_total=size)

            deadline = time.monotonic() + 30.0
            while True:
                time.sleep(0.3)
                if time.monotonic() > deadline:
                    raise sw2lib.ModbusError("Erase timeout (30 s)")
                try:
                    status = bus.read_hr(sw2lib.HR_OTA_STATUS, 1)[0]
                except sw2lib.ModbusError:
                    continue
                if status == 2:
                    break
                if status == 4:
                    raise sw2lib.ModbusError("Erase failed (flash error)")

            self._ota_set_state(phase="flashing")
            chunk_size = sw2lib.HR_OTA_DATA_REGS * 2
            sent = 0
            t0 = time.monotonic()
            while sent < size:
                chunk = image[sent:sent + chunk_size]
                regs = [(chunk[i] << 8) | chunk[i + 1] for i in range(0, len(chunk), 2)]
                bus.write_hrs(sw2lib.HR_OTA_DATA, regs)
                sent += len(chunk)
                elapsed = time.monotonic() - t0 or 0.001
                self._ota_set_state(
                    bytes_done=sent,
                    progress=sent / size,
                    rate_kbs=sent / elapsed / 1024,
                    elapsed=elapsed,
                )
            bus.write_hr(sw2lib.HR_OTA_CMD, sw2lib.OTA_CMD_FINISH)
            deadline = time.monotonic() + 5.0
            while True:
                time.sleep(0.2)
                status = bus.read_hr(sw2lib.HR_OTA_STATUS, 1)[0]
                if status == 3:
                    break
                if status == 4:
                    raise sw2lib.ModbusError("Finish failed (flash error)")
                if time.monotonic() > deadline:
                    raise sw2lib.ModbusError("Finish timeout")
            elapsed = time.monotonic() - t0
            self._ota_set_state(phase="done", progress=1.0, bytes_done=size, elapsed=elapsed)
            if trial:
                bus.write_hr(sw2lib.HR_TRIAL_BOOT, sw2lib.SAVE_MAGIC)
                self._ota_set_state(phase="confirming")
        except Exception as exc:
            self._ota_set_state(phase="error", error=str(exc))
            try:
                bus.write_hr(sw2lib.HR_OTA_CMD, sw2lib.OTA_CMD_ABORT)
            except Exception:
                pass
            raise
