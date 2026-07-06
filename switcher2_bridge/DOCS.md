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

The add-on options use the same structure as `tools/ha_bridge/config.toml`, but
written as YAML/JSON in the add-on options editor.

Example:

The default add-on configuration intentionally has an empty `devices` list. The add-on exits with a clear error until you add at least one Modbus device.

```yaml
device:
  name: switcher2
  mac: AA:BB:CC:DD:EE:01
server:
  port: 6053
  scheduler_interval_ms: 50
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
    serial:
      port: /dev/ttyUSB0
      baud: 19200
      slave_addr: 22
      parity: E
      bytesize: 8
      stopbits: 1
      timeout: 0.2
```

Supported device types:

- `switcher2`
- `dds1946_power_meter`
- `rolettini_blinds`

For DDS1946/DTS1946 meters and Rolettini controllers, use the same type-specific
keys shown in `tools/ha_bridge/config.toml`, such as `model`, `wordorder`,
`read_fc`, `parameters`, and `readable_attributes`.

## Serial Devices

The add-on enables UART, USB, and udev access. Prefer stable serial paths such
as `/dev/serial/by-id/...` when available.

## Persistent Data

The add-on stores mutable bridge metadata in `/data`, including `names.json`.
