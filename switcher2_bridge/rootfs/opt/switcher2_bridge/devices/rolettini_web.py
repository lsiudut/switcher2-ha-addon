"""Flask routes for Rolettini device views and commands."""
from __future__ import annotations

from flask import jsonify, request

import sw2lib


def register_routes(app, bridge, err, merr) -> None:
    @app.route('/api/devices/<device_id>/rolettini')
    def api_rolettini_snapshot(device_id: str):
        try:
            return jsonify(bridge.read_web(device_id, "rolettini"))
        except sw2lib.ModbusError as e:
            if "Unknown device" in str(e):
                return err(f"Unknown device '{device_id}'", 404)
            return merr(e)
        except (TypeError, ValueError) as e:
            return err(str(e), 400)

    @app.route('/api/devices/<device_id>/rolettini/config', methods=['PUT'])
    def api_rolettini_config(device_id: str):
        data = request.get_json(silent=True) or {}
        fields = data.get("fields", data)
        try:
            bridge.enqueue_write(device_id, "config", {"fields": fields}, source="web")
        except sw2lib.ModbusError as e:
            if "Unknown device" in str(e):
                return err(f"Unknown device '{device_id}'", 404)
            return merr(e)
        except (TypeError, ValueError) as e:
            return err(str(e), 400)
        return jsonify({"ok": True, "queued": True})

    @app.route('/api/devices/<device_id>/rolettini/command', methods=['POST'])
    def api_rolettini_command(device_id: str):
        data = request.get_json(silent=True) or {}
        action = data.get("action")
        action = "set_position" if action == "set_position" else action
        try:
            bridge.enqueue_write(device_id, action, {"value": data.get("value")}, source="web")
        except sw2lib.ModbusError as e:
            if "Unknown device" in str(e):
                return err(f"Unknown device '{device_id}'", 404)
            return merr(e)
        except (TypeError, ValueError) as e:
            return err(str(e), 400)
        return jsonify({"ok": True})

