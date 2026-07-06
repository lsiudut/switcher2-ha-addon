"""Bridge scheduler and public API for Modbus-backed devices."""
from __future__ import annotations

import heapq
import itertools
import logging
import os
import sys
import threading
import time
import zlib
from typing import Any, Callable

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import sw2lib

from devices.base import DeviceInfo, QueuedWrite
from devices.dds1946 import Dds1946Device
from devices.rolettini import RolettiniDevice
from devices.switcher2 import Switcher2Device
from entities import Entity, EntityType
from modbus_bus import ModbusManager
from names import NamesStore

log = logging.getLogger(__name__)
_MISSING = object()


class _WritePending(Exception):
    """Internal signal used to let queued writes preempt polling reads."""


def _state_delta(old: Any, new: Any) -> float:
    if isinstance(old, bool) or isinstance(new, bool):
        return float("inf") if old != new else 0.0
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return abs(float(new) - float(old))
    if isinstance(old, (tuple, list)) and isinstance(new, (tuple, list)):
        deltas = [
            _state_delta(a, b)
            for a, b in zip(old, new)
            if isinstance(a, (int, float, bool)) and isinstance(b, (int, float, bool))
        ]
        return max(deltas) if deltas else (float("inf") if old != new else 0.0)
    return float("inf") if old != new else 0.0


class Sw2Bridge:
    """Owns device adapters, cached state, and prioritized Modbus writes."""

    def __init__(self, config: dict, names: NamesStore):
        self._config = config
        self._names = names
        self._modbus = ModbusManager()
        self._devices: dict[str, dict[str, Any]] = {}
        self._adapters: dict[str, Any] = {}
        self._entities: list[Entity] = []
        self._entity_by_key_map: dict[int, Entity] = {}
        self._state: dict[int, Any] = {}
        self._published_state: dict[int, Any] = {}
        self._last_publish_at: dict[int, float] = {}
        self._publish_times: dict[int, list[float]] = {}
        self._callbacks: list[Callable[[Entity, Any], None]] = []
        self._avail_callbacks: list[Callable[[bool], None]] = []
        self._reconnect_callbacks: list[Callable[[], None]] = []
        self._write_lock = threading.Lock()
        self._write_cv = threading.Condition(self._write_lock)
        self._write_queue: list[tuple[int, int, str, QueuedWrite, float]] = []
        self._write_seq = itertools.count()
        self._writes_waiting = 0
        self._closed = False
        self._init_devices()
        self._write_thread = threading.Thread(
            target=self._write_worker,
            name="modbus-write-worker",
            daemon=True,
        )
        self._write_thread.start()

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    def _init_devices(self) -> None:
        device_cfgs = self._config.get("devices")
        if not device_cfgs:
            legacy = dict(self._config.get("serial", {}))
            legacy.update({
                "id": "switcher2",
                "type": "switcher2",
                "name": self._config.get("device", {}).get("name", "switcher2"),
                "poll_interval_ms": int(self._config.get("server", {}).get("poll_interval", 0.2) * 1000),
                "write_priority": 10,
                "timeout": legacy.get("timeout", 0.2),
                "unavailable_after_failures": 3,
                "unavailable_cooldown_s": 5.0,
            })
            device_cfgs = [legacy]

        for idx, cfg in enumerate(device_cfgs):
            dev_id = str(cfg.get("id") or f"device_{idx}")
            typ = str(cfg.get("type", "switcher2"))
            serial = dict(cfg.get("serial", cfg))
            info = DeviceInfo(
                id=dev_id,
                type=typ,
                name=str(cfg.get("name", dev_id)),
                index=idx,
                config=cfg,
                serial=serial,
                poll_interval_s=float(cfg.get("poll_interval_ms", 1000)) / 1000.0,
                write_priority=int(cfg.get("write_priority", 0)),
                esphome_device_id=self._stable_esphome_device_id(dev_id),
            )
            bus = self._modbus.add_device(dev_id, serial, cfg)
            adapter = self._make_adapter(info)
            self._devices[dev_id] = {
                "info": info,
                "bus": bus,
                "adapter": adapter,
                "next_poll": 0.0,
                "failed": 0,
                "max_failures": int(cfg.get("unavailable_after_failures", 3)),
                "cooldown_s": float(cfg.get("unavailable_cooldown_s", 5.0)),
                "unavailable_until": 0.0,
            }
            self._adapters[dev_id] = adapter

    def _make_adapter(self, info: DeviceInfo):
        if info.type == "switcher2":
            return Switcher2Device(info, self._names)
        if info.type in ("dds1946", "dds1946_power_meter", "power_meter"):
            return Dds1946Device(info)
        if info.type == "rolettini_blinds":
            return RolettiniDevice(info)
        raise ValueError(f"Unknown device type {info.type!r} for {info.id}")

    @staticmethod
    def _stable_esphome_device_id(device_id: str) -> int:
        # ESPHome device_id=0 is the root API node. Child devices get stable
        # non-zero ids derived from their configured ids.
        value = zlib.crc32(device_id.encode("utf-8")) & 0x7FFFFFFF
        return value or 1

    def build_entities(self) -> list[Entity]:
        entities: list[Entity] = []
        for dev_id, rec in self._devices.items():
            adapter = rec["adapter"]
            try:
                with self._modbus.borrow(dev_id) as bus:
                    built = adapter.build_entities(bus)
            except sw2lib.ModbusError:
                raise
            entities.extend(built)
        self._entities = entities
        self._entity_by_key_map = {e.key: e for e in entities}
        self._configure_entity_update_policies()
        log.info(
            "Entities: %d lights, %d covers, %d binary sensors, %d sensors, %d text sensors, %d buttons",
            sum(1 for e in entities if e.entity_type == EntityType.LIGHT),
            sum(1 for e in entities if e.entity_type == EntityType.COVER),
            sum(1 for e in entities if e.entity_type == EntityType.BINARY_SENSOR),
            sum(1 for e in entities if e.entity_type == EntityType.SENSOR),
            sum(1 for e in entities if e.entity_type == EntityType.TEXT_SENSOR),
            sum(1 for e in entities if e.entity_type == EntityType.BUTTON),
        )
        return entities

    def _configure_entity_update_policies(self) -> None:
        server_cfg = getattr(self, "_config", {}).get("server", {})
        global_interval_ms = server_cfg.get("ha_update_interval_ms", 0)
        global_max_updates = server_cfg.get("ha_max_updates_per_minute", 0)

        for entity in self._entities:
            rec = self._devices.get(entity.device_id, {})
            device_cfg = rec.get("info").config if rec.get("info") else {}
            entity_cfg = self._entity_config(device_cfg, entity)
            entity.update_interval_s = 0.0
            entity.update_on_change = None
            entity.max_updates_per_minute = 0
            entity.force_update = False

            interval_ms = entity_cfg.get(
                "update_interval_ms",
                device_cfg.get("ha_update_interval_ms", global_interval_ms),
            )
            entity.update_interval_s = max(0.0, float(interval_ms or 0) / 1000.0)
            entity.max_updates_per_minute = max(0, int(entity_cfg.get(
                "max_updates_per_minute",
                device_cfg.get("ha_max_updates_per_minute", global_max_updates),
            ) or 0))

            threshold = entity_cfg.get("update_on_change")
            if threshold is None:
                threshold = self._mapped_entity_value(device_cfg.get("ha_update_on_change", {}), entity)
            if threshold is not None:
                entity.update_on_change = max(0.0, float(threshold))

            entity.force_update = bool(entity.update_interval_s > 0 or entity_cfg.get("force_update", False))

    def _entity_config(self, device_cfg: dict[str, Any], entity: Entity) -> dict[str, Any]:
        entities_cfg = device_cfg.get("ha_entities", {})
        value = self._mapped_entity_value(entities_cfg, entity)
        return dict(value) if isinstance(value, dict) else {}

    def _mapped_entity_value(self, mapping: Any, entity: Entity) -> Any:
        if not isinstance(mapping, dict):
            return None
        for ident in self._entity_config_identifiers(entity):
            if ident in mapping:
                return mapping[ident]
        return None

    def _entity_config_identifiers(self, entity: Entity) -> list[str]:
        values = [
            entity.param_name,
            entity.register_name,
            entity.command_name,
            entity.object_id,
            entity.name,
            str(entity.key),
        ]
        if entity.channel >= 0:
            values.append(f"channel:{entity.channel}")
        if entity.input_index >= 0:
            values.append(f"input:{entity.input_index}")
        if entity.sensor_index >= 0:
            values.append(f"sensor:{entity.sensor_index}")
        return [v for v in values if v]

    # ------------------------------------------------------------------
    # Public read/callback API
    # ------------------------------------------------------------------

    def get_entities(self) -> list[Entity]:
        return list(self._entities)

    def get_state(self) -> dict[int, Any]:
        return dict(self._state)

    def is_available(self) -> bool:
        return any(rec["info"].available for rec in self._devices.values())

    def get_device_list(self) -> list[dict[str, Any]]:
        devices = []
        for rec in self._devices.values():
            info: DeviceInfo = rec["info"]
            adapter = rec["adapter"]
            devices.append({
                "id": info.id,
                "name": info.name,
                "type": info.type,
                "available": bool(info.available),
                "web_ui": getattr(adapter, "WEB_UI", None),
                "esphome_device_id": info.esphome_device_id,
                "poll_interval_ms": int(info.poll_interval_s * 1000),
                "serial": dict(info.serial),
            })
        return devices

    def get_esphome_devices(self) -> list[dict[str, Any]]:
        """Return logical child devices advertised through ESPHome."""
        return [
            {
                "id": rec["info"].id,
                "name": rec["info"].name,
                "type": rec["info"].type,
                "esphome_device_id": rec["info"].esphome_device_id,
                "available": bool(rec["info"].available),
            }
            for rec in self._devices.values()
        ]

    def esphome_device_id_for_entity(self, entity: Entity) -> int:
        rec = self._devices.get(entity.device_id)
        if rec is None:
            return 0
        return int(rec["info"].esphome_device_id)

    def read_web(self, device_id: str, view: str, payload: dict[str, Any] | None = None) -> Any:
        adapter = self._adapter_or_raise(device_id)
        return adapter.web_read(view, self.get_state(), payload)

    def get_names(self) -> dict[str, Any]:
        return {
            "channel_names": self._names.all_channel_names(),
            "input_names": self._names.all_input_names(),
        }

    def update_web_metadata(
        self,
        device_id: str,
        action: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        adapter = self._adapter_or_raise(device_id)
        handler = getattr(adapter, "update_web_metadata", None)
        if handler is None:
            raise ValueError(f"Device {device_id!r} does not support metadata action {action!r}")
        result = handler(action, payload or {})
        if isinstance(result, dict) and result.get("ha_reconnect"):
            self._request_reconnect()
        return result

    def register_callback(self, cb: Callable[[Entity, Any], None]) -> None:
        if cb not in self._callbacks:
            self._callbacks.append(cb)

    def unregister_callback(self, cb: Callable[[Entity, Any], None]) -> None:
        try:
            self._callbacks.remove(cb)
        except ValueError:
            pass

    def register_avail_callback(self, cb: Callable[[bool], None]) -> None:
        if cb not in self._avail_callbacks:
            self._avail_callbacks.append(cb)

    def unregister_avail_callback(self, cb: Callable[[bool], None]) -> None:
        try:
            self._avail_callbacks.remove(cb)
        except ValueError:
            pass

    def register_reconnect_callback(self, cb: Callable[[], None]) -> None:
        if cb not in self._reconnect_callbacks:
            self._reconnect_callbacks.append(cb)

    def unregister_reconnect_callback(self, cb: Callable[[], None]) -> None:
        try:
            self._reconnect_callbacks.remove(cb)
        except ValueError:
            pass

    # ------------------------------------------------------------------
    # Public write API
    # ------------------------------------------------------------------

    def enqueue_write(
        self,
        device_id: str,
        action: str,
        payload: dict[str, Any] | None = None,
        source: str = "api",
    ) -> None:
        rec = self._device_or_raise(device_id)
        write = rec["adapter"].prepare_write(action, payload)
        enqueued_at = time.monotonic()
        with self._write_cv:
            seq = next(self._write_seq)
            heapq.heappush(
                self._write_queue,
                (-rec["info"].write_priority, seq, device_id, write, enqueued_at),
            )
            log.info(
                "%s: queued %s write %s priority=%s seq=%s queue_depth=%s",
                device_id,
                source,
                write.desc,
                rec["info"].write_priority,
                seq,
                len(self._write_queue),
            )
            self._write_cv.notify()

    def cmd_light(self, key: int, state: bool) -> None:
        entity = self._entity_by_key(key)
        if entity is None:
            log.warning("Light command for unknown key %s", key)
            return
        self.enqueue_write(entity.device_id, "light", {
            "channel": entity.channel,
            "state": state,
        }, source="esphome")

    def cmd_cover(self, key: int, position: float | None, stop: bool) -> None:
        entity = self._entity_by_key(key)
        if entity is None:
            log.warning("Cover command for unknown key %s", key)
            return
        self.enqueue_write(entity.device_id, "cover", {
            "channel": entity.channel,
            "position": position,
            "stop": stop,
        }, source="esphome")

    def cmd_button(self, key: int) -> None:
        entity = self._entity_by_key(key)
        if entity is None:
            log.warning("Button command for unknown key %s", key)
            return
        self.enqueue_write(entity.device_id, "button", {
            "command_name": entity.command_name,
        }, source="esphome")

    # ------------------------------------------------------------------
    # Poll/write scheduler
    # ------------------------------------------------------------------

    def poll_once(self) -> list[tuple[Entity, Any]]:
        self._ensure_publish_state()
        changes: list[tuple[Entity, Any]] = []
        self._drain_writes()
        now = time.monotonic()
        for dev_id, rec in self._devices.items():
            if now < rec["next_poll"]:
                continue
            rec["next_poll"] = now + rec["info"].poll_interval_s
            if not self._device_available_for_io(rec):
                continue
            try:
                if self._writes_pending():
                    raise _WritePending()
                with self._modbus.borrow(dev_id) as bus:
                    if self._writes_pending():
                        raise _WritePending()
                    values = rec["adapter"].poll(_PreemptingBus(bus, self._writes_pending))
            except _WritePending:
                self._drain_writes()
                continue
            except sw2lib.ModbusError as exc:
                self._record_failure(rec, exc)
                continue
            self._record_success(rec)
            for key, new_state in values.items():
                old_state = self._state.get(key, _MISSING)
                if old_state is _MISSING or new_state != old_state:
                    self._state[key] = new_state
                entity = self._entity_by_key_map.get(key)
                if entity is not None and self._should_publish(entity, old_state, new_state, now):
                    changes.append((entity, new_state))
                    self._mark_published(entity, new_state, now)
                    self._emit_state(entity, new_state)
        return changes

    def _ensure_publish_state(self) -> None:
        if not hasattr(self, "_published_state"):
            self._published_state = {}
        if not hasattr(self, "_last_publish_at"):
            self._last_publish_at = {}
        if not hasattr(self, "_publish_times"):
            self._publish_times = {}

    def _should_publish(self, entity: Entity, old_state: Any, new_state: Any, now: float) -> bool:
        if not self._publish_allowed(entity, now):
            return False

        if entity.key not in self._published_state:
            return True

        published_state = self._published_state[entity.key]
        changed_since_poll = old_state is _MISSING or new_state != old_state
        changed_since_publish = new_state != published_state

        if entity.update_on_change is not None and changed_since_publish:
            if _state_delta(published_state, new_state) >= entity.update_on_change:
                return True

        if entity.update_interval_s > 0:
            last = self._last_publish_at.get(entity.key, 0.0)
            return now - last >= entity.update_interval_s

        return changed_since_poll

    def _publish_allowed(self, entity: Entity, now: float) -> bool:
        limit = int(getattr(entity, "max_updates_per_minute", 0) or 0)
        if limit <= 0:
            return True
        times = self._publish_times.setdefault(entity.key, [])
        cutoff = now - 60.0
        del times[:next((i for i, ts in enumerate(times) if ts >= cutoff), len(times))]
        return len(times) < limit

    def _mark_published(self, entity: Entity, new_state: Any, now: float) -> None:
        self._published_state[entity.key] = new_state
        self._last_publish_at[entity.key] = now
        limit = int(getattr(entity, "max_updates_per_minute", 0) or 0)
        if limit > 0:
            self._publish_times.setdefault(entity.key, []).append(now)

    def _drain_writes(self) -> None:
        while True:
            with self._write_cv:
                try:
                    _prio, _seq, dev_id, write, enqueued_at = heapq.heappop(self._write_queue)
                except IndexError:
                    return
            self._execute_write(dev_id, write, enqueued_at)

    def _write_worker(self) -> None:
        while True:
            with self._write_cv:
                while not self._write_queue and not self._closed:
                    self._write_cv.wait()
                if self._closed and not self._write_queue:
                    return
                _prio, _seq, dev_id, write, enqueued_at = heapq.heappop(self._write_queue)
            self._execute_write(dev_id, write, enqueued_at)

    def _execute_write(self, dev_id: str, write: QueuedWrite, enqueued_at: float) -> None:
        rec = self._devices.get(dev_id)
        if rec is None:
            log.warning("%s: dropping write %s: device missing", dev_id, write.desc)
            return
        wait_ms = (time.monotonic() - enqueued_at) * 1000.0
        log.info("%s: dequeued write %s after %.1f ms queued", dev_id, write.desc, wait_ms)
        with self._write_cv:
            self._writes_waiting += 1
        ok = False
        try:
            if not self._device_available_for_io(rec):
                raise sw2lib.ModbusError(f"{dev_id} unavailable")
            with self._modbus.borrow(dev_id) as bus:
                write.fn(bus)
            ok = True
        except sw2lib.ModbusError as exc:
            self._record_failure(rec, exc)
            log.warning("%s: write failed %s: %s", dev_id, write.desc, exc)
        finally:
            with self._write_cv:
                self._writes_waiting -= 1
                self._write_cv.notify_all()
        if ok:
            self._record_success(rec)

    def _writes_pending(self) -> bool:
        with self._write_lock:
            return self._writes_waiting > 0 or bool(self._write_queue)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _device_or_raise(self, device_id: str) -> dict[str, Any]:
        rec = self._devices.get(device_id)
        if rec is None:
            raise sw2lib.ModbusError(f"Unknown device {device_id!r}")
        return rec

    def _adapter_or_raise(self, device_id: str):
        return self._device_or_raise(device_id)["adapter"]

    def _entity_by_key(self, key: int) -> Entity | None:
        return self._entity_by_key_map.get(key)

    def _emit_state(self, entity: Entity, new_state: Any) -> None:
        for cb in list(self._callbacks):
            try:
                cb(entity, new_state)
            except Exception as exc:
                log.warning("State callback error: %s", exc)

    def _request_reconnect(self) -> None:
        for cb in list(self._reconnect_callbacks):
            try:
                cb()
            except Exception as exc:
                log.warning("Reconnect callback error: %s", exc)

    def _device_available_for_io(self, rec: dict[str, Any]) -> bool:
        info: DeviceInfo = rec["info"]
        if info.available:
            return True
        if time.monotonic() < rec["unavailable_until"]:
            return False
        self._set_device_available(rec, True)
        log.info("Device %s leaving cooldown; retrying", info.id)
        return True

    def _record_failure(self, rec: dict[str, Any], exc: Exception) -> None:
        rec["failed"] += 1
        if rec["failed"] > rec["max_failures"]:
            rec["unavailable_until"] = time.monotonic() + rec["cooldown_s"]
            self._set_device_available(rec, False)
        log.debug("%s: Modbus error: %s", rec["info"].id, exc)

    def _record_success(self, rec: dict[str, Any]) -> None:
        rec["failed"] = 0
        self._set_device_available(rec, True)

    def _set_device_available(self, rec: dict[str, Any], available: bool) -> None:
        info: DeviceInfo = rec["info"]
        if available == info.available:
            return
        info.available = available
        for cb in list(self._avail_callbacks):
            try:
                cb(self.is_available())
            except Exception as exc:
                log.warning("Availability callback error: %s", exc)

    def close(self) -> None:
        self._closed = True
        with self._write_cv:
            self._write_cv.notify_all()
        for adapter in self._adapters.values():
            try:
                adapter.close()
            except Exception:
                pass
        self._modbus.close()


class _PreemptingBus:
    """Bus proxy that lets queued writes interrupt multi-read adapter polls."""

    def __init__(self, bus, writes_pending: Callable[[], bool]):
        self._bus = bus
        self._writes_pending = writes_pending

    def __getattr__(self, name: str):
        attr = getattr(self._bus, name)
        if not callable(attr):
            return attr

        def checked(*args, **kwargs):
            if self._writes_pending():
                raise _WritePending()
            return attr(*args, **kwargs)

        return checked
