# Switcher2 Bridge Add-on

## Installation

Add this repository as a Home Assistant add-on repository, install
`Switcher2 Bridge`, configure the devices, and start the add-on.

## Home Assistant Setup

This add-on intentionally does not publish mDNS records. In Home Assistant,
add an ESPHome integration manually:

- Host: the Home Assistant host address
- Port: `6053`

## Configuration

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

## Serial Devices

The add-on enables UART, USB, and udev access. Prefer stable serial paths such
as `/dev/serial/by-id/...` when available.

## Persistent Data

The add-on stores mutable bridge metadata in `/data`, including `names.json`.
