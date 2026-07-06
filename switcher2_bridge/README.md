# Switcher2 Bridge Add-on

Runs the switcher2 Modbus Home Assistant bridge as a supervised add-on.

The add-on exposes the configured Modbus hardware through the ESPHome native API
on port `6053`. mDNS discovery is disabled in add-on mode, so add the ESPHome
device manually in Home Assistant using the host address of the Home Assistant
machine and port `6053`.

The bridge web UI is available through Home Assistant ingress from the add-on
sidebar panel.

## Install

1. Push this repository to GitHub.
2. In Home Assistant, open **Settings -> Add-ons -> Add-on Store**.
3. Open the three-dot menu and choose **Repositories**.
4. Add this repository URL.
5. Install **Switcher2 Bridge**.
6. Configure the `devices` list.
7. Start the add-on.

The add-on requires Home Assistant OS or Home Assistant Supervised. It is not
available on plain Home Assistant Container/Core installs because those do not
run the Supervisor add-on system.

## ESPHome Setup

mDNS discovery is disabled in add-on mode. Add the bridge manually:

1. Open **Settings -> Devices & services -> Add integration**.
2. Choose **ESPHome**.
3. Enter the Home Assistant host address.
4. Enter port `6053`.

Use the host address of the Home Assistant machine, not `localhost`, unless you
are deliberately testing a matching network namespace.

## Flattened Add-on Configuration

The add-on configuration is edited directly in Home Assistant. Device entries use
flat serial fields because Home Assistant Supervisor does not handle deeply
nested per-device schemas well.

```yaml
device:
  name: switcher2
  mac: AA:BB:CC:DD:EE:01

server:
  port: 6053
  scheduler_interval_ms: 50
  poll_interval: 0.2

webui:
  enabled: true
  host: 0.0.0.0
  port: 8090

names:
  file: /data/names.json

devices:
  - id: relay_board
    type: switcher2
    name: Relay Board
    poll_interval_ms: 200
    write_priority: 10
    unavailable_after_failures: 3
    unavailable_cooldown_s: 5
    readable_attributes: ""
    model: ""
    wordorder: ""
    read_fc: 0
    parameters: []
    ha_update_interval_ms: 0
    ha_max_updates_per_minute: 0
    ha_update_on_change_P: 0.0
    ha_update_on_change_Ua: 0.0
    ha_update_on_change_Ub: 0.0
    ha_update_on_change_Uc: 0.0
    ha_update_on_change_Ia: 0.0
    ha_update_on_change_Ib: 0.0
    ha_update_on_change_Ic: 0.0
    ha_update_on_change_F: 0.0
    serial_port: /dev/serial/by-id/usb-your-adapter
    serial_baud: 19200
    serial_slave_addr: 22
    serial_parity: E
    serial_bytesize: 8
    serial_stopbits: 1
    serial_timeout: 0.2
```

The add-on rebuilds the nested bridge config at startup. Empty strings, zero
advanced values, and empty parameter lists are ignored.

Supported `type` values:

- `switcher2`
- `dds1946_power_meter`
- `rolettini_blinds`

## Local Docker Build

From the repository root:

```sh
docker build -t switcher2-bridge-addon:local switcher2_bridge
```

Create `/tmp/switcher2-addon-data/options.json` with JSON equivalent to the flattened YAML above, then run:

```sh
docker run --rm \
  --name switcher2-bridge-addon \
  --device /dev/serial/by-id/usb-your-adapter \
  -v /tmp/switcher2-addon-data:/data \
  -p 6053:6053 \
  -p 8090:8090 \
  switcher2-bridge-addon:local
```

The web UI will be available at `http://localhost:8090` during local Docker
testing.
