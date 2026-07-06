"""Flask web UI server for ha_bridge."""
from __future__ import annotations

import logging
import threading
from pathlib import Path

from flask import Flask, jsonify, send_from_directory

from bridge import Sw2Bridge
from devices import rolettini_web, switcher2_web
import sw2lib

log = logging.getLogger(__name__)

_STATIC = Path(__file__).parent / 'static'


def create_webui_app(bridge: Sw2Bridge) -> Flask:
    app = Flask(__name__, static_folder=str(_STATIC))
    logging.getLogger('werkzeug').setLevel(logging.WARNING)

    def _err(msg: str, status: int = 400):
        return jsonify({"error": msg}), status

    def _merr(e: sw2lib.ModbusError):
        return jsonify({"error": str(e), "connected": False}), 503

    @app.route('/')
    def index():
        return send_from_directory(str(_STATIC), 'index.html')

    @app.route('/api/devices')
    def api_devices():
        return jsonify(bridge.get_device_list())

    @app.route('/api/devices/<device_id>/readings')
    def api_device_readings(device_id: str):
        dev = next((d for d in bridge.get_device_list() if d['id'] == device_id), None)
        if dev is None:
            return _err(f"Unknown device '{device_id}'", 404)
        try:
            return jsonify(bridge.read_web(device_id, "readings"))
        except ValueError:
            return jsonify({
                "id": dev["id"],
                "name": dev["name"],
                "type": dev["type"],
                "available": dev["available"],
                "supported": False,
                "message": "Web UI is not implemented for this device type yet.",
            })
        except sw2lib.ModbusError as e:
            return _merr(e)

    rolettini_web.register_routes(app, bridge, _err, _merr)
    switcher2_web.register_routes(app, bridge, _err, _merr)

    return app


def start_webui(bridge: Sw2Bridge, host: str = '0.0.0.0', port: int = 5000) -> None:
    """Start the Flask web UI in a daemon thread. Returns immediately."""
    flask_app = create_webui_app(bridge)
    t = threading.Thread(
        target=flask_app.run,
        kwargs=dict(host=host, port=port, debug=False, use_reloader=False),
        daemon=True,
    )
    t.start()
    log.info(f"Web UI listening on http://{host}:{port}")

