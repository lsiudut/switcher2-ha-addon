#!/usr/bin/env python3
"""Home Assistant add-on entry point for the switcher2 bridge.

The standalone bridge reads TOML and advertises ESPHome via mDNS. In the add-on
container, Supervisor owns configuration and Home Assistant can connect to the
published ESPHome port directly, so this entry point reads /data/options.json
and intentionally does not register mDNS.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from bridge import Sw2Bridge
from esphome_server import EspHomeServer
from names import NamesStore

log = logging.getLogger(__name__)

OPTIONS_PATH = Path("/data/options.json")
DEFAULT_NAMES_PATH = Path("/data/names.json")


DEFAULT_CONFIG: dict[str, Any] = {
    "device": {
        "name": "switcher2",
        "mac": "AA:BB:CC:DD:EE:01",
    },
    "server": {
        "port": 6053,
        "poll_interval": 0.2,
        "scheduler_interval_ms": 50,
    },
    "webui": {
        "enabled": True,
        "host": "0.0.0.0",
        "port": 8090,
    },
    "names": {
        "file": str(DEFAULT_NAMES_PATH),
    },
    "devices": [],
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _flat_device_to_bridge(device: dict[str, Any]) -> dict[str, Any]:
    cfg = dict(device)

    serial = {
        "port": cfg.pop("serial_port", ""),
        "baud": cfg.pop("serial_baud", 0),
        "slave_addr": cfg.pop("serial_slave_addr", 0),
        "parity": cfg.pop("serial_parity", "E"),
        "bytesize": cfg.pop("serial_bytesize", 8),
        "stopbits": cfg.pop("serial_stopbits", 1),
        "timeout": cfg.pop("serial_timeout", 0.2),
    }
    cfg["serial"] = serial

    thresholds: dict[str, float] = {}
    for suffix in ("P", "Ua", "Ub", "Uc", "Ia", "Ib", "Ic", "F"):
        key = f"ha_update_on_change_{suffix}"
        value = cfg.pop(key, 0)
        if isinstance(value, (int, float)) and float(value) > 0:
            thresholds[suffix] = float(value)
    if thresholds:
        cfg["ha_update_on_change"] = thresholds

    if not str(cfg.get("readable_attributes", "")).strip():
        cfg.pop("readable_attributes", None)
    if not str(cfg.get("model", "")).strip():
        cfg.pop("model", None)
    if not str(cfg.get("wordorder", "")).strip():
        cfg.pop("wordorder", None)
    if int(cfg.get("read_fc", 0) or 0) <= 0:
        cfg.pop("read_fc", None)
    if int(cfg.get("ha_update_interval_ms", 0) or 0) <= 0:
        cfg.pop("ha_update_interval_ms", None)
    if int(cfg.get("ha_max_updates_per_minute", 0) or 0) <= 0:
        cfg.pop("ha_max_updates_per_minute", None)
    if not cfg.get("parameters"):
        cfg.pop("parameters", None)

    return cfg


def _normalize_config(cfg: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(cfg)
    devices = normalized.get("devices", [])
    if isinstance(devices, list):
        normalized["devices"] = [
            _flat_device_to_bridge(device) if isinstance(device, dict) else device
            for device in devices
        ]
    return normalized


def _load_options() -> dict[str, Any]:
    if not OPTIONS_PATH.exists():
        log.warning("%s not found; using built-in defaults", OPTIONS_PATH)
        return dict(DEFAULT_CONFIG)
    with OPTIONS_PATH.open("r", encoding="utf-8") as f:
        user = json.load(f)
    if not isinstance(user, dict):
        raise ValueError("/data/options.json must contain a JSON object")

    cfg = _normalize_config(_deep_merge(DEFAULT_CONFIG, user))

    webui = cfg.setdefault("webui", {})
    webui["host"] = "0.0.0.0"
    webui["port"] = int(webui.get("port") or 8090)

    names = cfg.setdefault("names", {})
    names["file"] = str(names.get("file") or DEFAULT_NAMES_PATH)
    return cfg


async def _poll_loop(bridge: Sw2Bridge, interval: float) -> None:
    loop = asyncio.get_running_loop()
    while True:
        try:
            await loop.run_in_executor(None, bridge.poll_once)
        except Exception as exc:
            log.warning("Poll loop error: %s", exc)
        await asyncio.sleep(interval)


async def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    try:
        cfg = _load_options()
    except Exception as exc:
        log.error("Cannot load add-on options: %s", exc)
        sys.exit(1)

    devices = cfg.get("devices")
    if not isinstance(devices, list) or not devices:
        log.error(
            "No Modbus devices configured. Add at least one device "
            "under the add-on devices option before starting."
        )
        sys.exit(1)

    dev = cfg["device"]
    srv = cfg["server"]
    names_file = Path(cfg.get("names", {}).get("file", DEFAULT_NAMES_PATH))
    names_file.parent.mkdir(parents=True, exist_ok=True)
    names = NamesStore(str(names_file))

    try:
        bridge = Sw2Bridge(cfg, names)
        bridge.build_entities()
        bridge.poll_once()
    except Exception as exc:
        log.error("Cannot initialize configured Modbus device(s): %s", exc)
        sys.exit(1)

    webui_cfg = cfg.get("webui", {})
    if webui_cfg.get("enabled", True):
        try:
            from webui_server import start_webui
        except ImportError:
            log.error("Flask is not installed; web UI disabled")
        else:
            start_webui(
                bridge,
                host=webui_cfg.get("host", "0.0.0.0"),
                port=int(webui_cfg.get("port", 8090)),
            )

    port = int(srv.get("port", 6053))
    esphome = EspHomeServer(bridge, str(dev["name"]), str(dev["mac"]), port)
    server = await esphome.start()

    scheduler_interval = float(srv.get("scheduler_interval_ms", 50)) / 1000.0
    asyncio.create_task(_poll_loop(bridge, scheduler_interval))

    log.info("mDNS discovery disabled in add-on mode")
    log.info("Bridge ready: ESPHome native API on port %s", port)
    log.info("In Home Assistant, add an ESPHome device using the host running this add-on")

    try:
        async with server:
            await server.serve_forever()
    finally:
        bridge.close()


if __name__ == "__main__":
    asyncio.run(main())
