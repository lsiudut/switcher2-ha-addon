"""Flask routes for switcher2 device views and commands."""
from __future__ import annotations

from flask import jsonify, request

import sw2lib


def register_routes(app, bridge, err, merr) -> None:
    def first_switcher_id() -> str | None:
        for dev in bridge.get_device_list():
            if dev["type"] == "switcher2":
                return dev["id"]
        return None

    def require_switcher_id() -> str:
        dev_id = first_switcher_id()
        if dev_id is None:
            raise sw2lib.ModbusError("Web UI requires a configured switcher2 device")
        return dev_id

    def read(view: str):
        return bridge.read_web(require_switcher_id(), view)

    def enqueue(action: str, payload: dict | None = None):
        bridge.enqueue_write(require_switcher_id(), action, payload or {}, source="web")

    @app.route('/api/names')
    def api_names():
        return jsonify(bridge.get_names())

    @app.route('/api/names/channel/<int:ch>', methods=['PUT'])
    def api_name_channel(ch: int):
        if not 0 <= ch < sw2lib.CHANNEL_MAX:
            return err(f"Channel must be 0–{sw2lib.CHANNEL_MAX - 1}")
        data = request.get_json(silent=True) or {}
        try:
            result = bridge.update_web_metadata(
                require_switcher_id(),
                "channel_name",
                {"channel": ch, "name": data.get("name", "")},
            )
        except sw2lib.ModbusError as e:
            return merr(e)
        return jsonify(result)

    @app.route('/api/names/input/<int:inp>', methods=['PUT'])
    def api_name_input(inp: int):
        if not 0 <= inp < sw2lib.INPUT_MAX:
            return err(f"Input must be 0–{sw2lib.INPUT_MAX - 1}")
        data = request.get_json(silent=True) or {}
        try:
            result = bridge.update_web_metadata(
                require_switcher_id(),
                "input_name",
                {"input": inp, "name": data.get("name", "")},
            )
        except sw2lib.ModbusError as e:
            return merr(e)
        return jsonify(result)

    @app.route('/api/status')
    def api_status():
        try:
            return jsonify(read("status"))
        except sw2lib.ModbusError as e:
            return jsonify({
                "connected": False,
                "error": str(e),
                "dirty": False,
                "firmware_version": None,
                "channel_status": [0] * sw2lib.CHANNEL_MAX,
                "channel_motion": [0] * sw2lib.CHANNEL_MAX,
                "inputs": [0] * sw2lib.INPUT_MAX,
                "relays": [0] * sw2lib.CHANNEL_MAX,
                "temperatures": [None] * sw2lib.SENSOR_MAX,
            }), 503

    @app.route('/api/channels')
    def api_channels():
        try:
            return jsonify(read("channels"))
        except sw2lib.ModbusError as e:
            return merr(e)

    @app.route('/api/channels/<int:ch>/config', methods=['PUT'])
    def api_channel_config(ch: int):
        if not 0 <= ch < sw2lib.CHANNEL_MAX:
            return err(f"Channel must be 0–{sw2lib.CHANNEL_MAX - 1}")
        data = request.get_json(silent=True) or {}
        try:
            type_ = int(data.get('type', 0))
            t_open = int(data.get('travel_ms_open', 0))
            t_close = int(data.get('travel_ms_close', 0))
            off_delay = int(data.get('light_off_delay_s', 0))
            default_on = int(bool(data.get('light_default_on', False)))
        except (TypeError, ValueError) as exc:
            return err(f"Invalid field: {exc}")
        if type_ not in (0, 1, 2):
            return err("type must be 0 (unassigned), 1 (light), or 2 (blind)")
        if type_ == 1:
            relay_field1 = int(data.get('relay_mask', 0)) & 0x3FFF
            relay_b = 0
        else:
            relay_field1 = int(data.get('relay_a', 0))
            relay_b = int(data.get('relay_b', 0))
            if not 0 <= relay_field1 <= 14:
                return err("relay_a must be 0–14")
            if not 0 <= relay_b <= 14:
                return err("relay_b must be 0–14")
        if not 0 <= off_delay <= 65535:
            return err("light_off_delay_s must be 0–65535")
        try:
            enqueue("channel_config", {
                "channel": ch,
                "type": type_,
                "relay_a": relay_field1,
                "relay_b": relay_b,
                "travel_ms_open": t_open,
                "travel_ms_close": t_close,
                "light_off_delay_s": off_delay,
                "light_default_on": default_on,
                "relay_mask": relay_field1,
            })
        except sw2lib.ModbusError as e:
            return merr(e)
        return jsonify({"ok": True})

    @app.route('/api/channels/<int:ch>/cmd', methods=['POST'])
    def api_channel_cmd(ch: int):
        if not 0 <= ch < sw2lib.CHANNEL_MAX:
            return err(f"Channel must be 0–{sw2lib.CHANNEL_MAX - 1}")
        data = request.get_json(silent=True) or {}
        cmd = data.get('cmd', '')
        cmd_map = {"off": 0, "on": 1, "toggle": 2, "stop": 10001, "calibrate": 10002}
        if cmd in cmd_map:
            value = cmd_map[cmd]
        elif isinstance(cmd, str) and cmd.startswith("pos="):
            try:
                value = int(cmd[4:])
                if not 0 <= value <= 10000:
                    raise ValueError
            except ValueError:
                return err("pos= requires integer 0–10000")
        else:
            return err(f"Unknown command '{cmd}'. Use: on/off/toggle/stop/calibrate/pos=N")
        try:
            enqueue("channel_cmd", {"channel": ch, "value": value})
        except sw2lib.ModbusError as e:
            return merr(e)
        return jsonify({"ok": True})

    @app.route('/api/actions')
    def api_actions():
        try:
            return jsonify(read("actions"))
        except sw2lib.ModbusError as e:
            return merr(e)

    @app.route('/api/actions/<int:inp>/<int:ev>', methods=['PUT'])
    def api_action_set(inp: int, ev: int):
        if not 0 <= inp < sw2lib.INPUT_MAX:
            return err(f"Input must be 0–{sw2lib.INPUT_MAX - 1}")
        if not 0 <= ev < sw2lib.BUTTON_EVENT_COUNT:
            return err(f"Event must be 0–{sw2lib.BUTTON_EVENT_COUNT - 1}")
        data = request.get_json(silent=True) or {}
        try:
            action = int(data.get('action', 0))
            channel = int(data.get('channel', 0))
            param = int(data.get('param', 0))
        except (TypeError, ValueError) as exc:
            return err(f"Invalid field: {exc}")
        if not 0 <= action <= 7:
            return err("action must be 0–7")
        try:
            enqueue("action", {
                "input": inp,
                "event": ev,
                "action_code": action,
                "channel": channel,
                "param": param,
            })
        except sw2lib.ModbusError as e:
            return merr(e)
        return jsonify({"ok": True})

    @app.route('/api/debounce')
    def api_debounce():
        try:
            return jsonify(read("debounce"))
        except sw2lib.ModbusError as e:
            return merr(e)

    @app.route('/api/debounce/<int:inp>', methods=['PUT'])
    def api_debounce_set(inp: int):
        if not 0 <= inp < sw2lib.INPUT_MAX:
            return err(f"Input must be 0–{sw2lib.INPUT_MAX - 1}")
        data = request.get_json(silent=True) or {}
        try:
            ms = int(data.get('ms', 10))
        except (TypeError, ValueError):
            return err("ms must be an integer")
        if not 0 <= ms <= 65535:
            return err("ms must be 0–65535")
        try:
            enqueue("debounce", {"input": inp, "ms": ms})
        except sw2lib.ModbusError as e:
            return merr(e)
        return jsonify({"ok": True})

    @app.route('/api/zcd')
    def api_zcd():
        try:
            return jsonify(read("zcd"))
        except sw2lib.ModbusError as e:
            return merr(e)

    @app.route('/api/zcd', methods=['PUT'])
    def api_zcd_set():
        data = request.get_json(silent=True) or {}
        try:
            enabled = data["enabled"]
            delays = [int(v) for v in data["delays"]]
        except (KeyError, TypeError, ValueError) as exc:
            return err(f"Missing or invalid ZCD field: {exc}")
        if not isinstance(enabled, bool):
            return err("enabled must be boolean")
        if len(delays) != sw2lib.RELAY_MAX:
            return err(f"delays must contain {sw2lib.RELAY_MAX} relay values")
        for delay in delays:
            if delay < -1 or delay > 32767:
                return err("ZCD delays must be -1 or 0–32767 ms")
        try:
            enqueue("zcd_config", {"enabled": enabled, "delays": delays})
        except sw2lib.ModbusError as e:
            return merr(e)
        return jsonify({"ok": True})

    @app.route('/api/config/save', methods=['POST'])
    def api_config_save():
        try:
            enqueue("config_save")
        except sw2lib.ModbusError as e:
            return merr(e)
        return jsonify({"ok": True, "queued": True})

    @app.route('/api/config/reset', methods=['POST'])
    def api_config_reset():
        try:
            enqueue("config_reset")
        except sw2lib.ModbusError as e:
            return merr(e)
        return jsonify({"ok": True})

    @app.route('/api/config/discard', methods=['POST'])
    def api_config_discard():
        try:
            enqueue("config_discard")
        except sw2lib.ModbusError as e:
            return merr(e)
        return jsonify({"ok": True})

    @app.route('/api/ota/status')
    def api_ota_status():
        try:
            return jsonify(read("ota_status"))
        except sw2lib.ModbusError as e:
            return merr(e)

    @app.route('/api/ota/flash', methods=['POST'])
    def api_ota_flash():
        trial = request.args.get('trial', 'false').lower() == 'true'
        f = request.files.get('firmware')
        if f is None:
            return err("No firmware file in request (field name: 'firmware')")
        image_bytes = f.read()
        if len(image_bytes) < 256:
            return err("Firmware too small (< 256 bytes)")
        try:
            enqueue("ota_flash", {"image_bytes": image_bytes, "trial": trial})
        except sw2lib.ModbusError as e:
            return merr(e)
        return jsonify({"ok": True, "size": len(image_bytes), "queued": True})

    @app.route('/api/ota/trial', methods=['POST'])
    def api_ota_trial():
        try:
            enqueue("ota_trial")
        except sw2lib.ModbusError as e:
            return merr(e)
        return jsonify({"ok": True})

    @app.route('/api/ota/abort', methods=['POST'])
    def api_ota_abort():
        try:
            enqueue("ota_abort")
        except sw2lib.ModbusError as e:
            return merr(e)
        return jsonify({"ok": True})

    @app.route('/api/serial')
    def api_serial_get():
        try:
            return jsonify(read("serial"))
        except sw2lib.ModbusError as e:
            return merr(e)

    @app.route('/api/serial', methods=['POST'])
    def api_serial_set():
        data = request.get_json(silent=True) or {}
        try:
            cfg = {
                'port': str(data['port']),
                'baud': int(data['baud']),
                'slave_addr': int(data['slave_addr']),
                'parity': str(data['parity']).upper(),
                'bytesize': int(data['bytesize']),
                'stopbits': int(data['stopbits']),
            }
        except (KeyError, TypeError, ValueError) as e:
            return err(f"Missing or invalid field: {e}")
        if cfg['parity'] not in ('E', 'O', 'N'):
            return err("parity must be E, O, or N")
        if cfg['bytesize'] not in (5, 6, 7, 8):
            return err("bytesize must be 5–8")
        if cfg['stopbits'] not in (1, 2):
            return err("stopbits must be 1 or 2")
        try:
            enqueue("serial", {"config": cfg})
        except Exception as e:
            return err(f"Reconnect failed: {e}", 503)
        return jsonify({"ok": True})

    @app.route('/api/reboot', methods=['POST'])
    def api_reboot():
        try:
            enqueue("reboot")
        except sw2lib.ModbusError as e:
            return merr(e)
        return jsonify({"ok": True})
