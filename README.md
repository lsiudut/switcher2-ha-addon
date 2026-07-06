# Switcher2 Home Assistant Add-on

Standalone Home Assistant add-on repository for the switcher2 Modbus bridge.

The add-on runs the Python bridge in a supervised Docker container and exposes
configured Modbus hardware to Home Assistant through the ESPHome native API.

In add-on mode, mDNS discovery is disabled. After the add-on starts, add it to
Home Assistant manually as an ESPHome device using port `6053`.

## Repository Layout

```text
repository.yaml
switcher2_bridge/
  config.yaml
  Dockerfile
  README.md
  DOCS.md
  CHANGELOG.md
  rootfs/
```

## Requirements

The add-on installation path requires one of:

- Home Assistant OS
- Home Assistant Supervised

It will not work as a Supervisor add-on on a plain Home Assistant Container or
Home Assistant Core venv install.

The add-on needs access to the serial adapter used for Modbus RTU. Prefer stable
device paths such as:

```text
/dev/serial/by-id/usb-...
```

instead of `/dev/ttyUSB0` when possible.

## Deploy From GitHub

1. Push this repository to GitHub.
2. In Home Assistant, open **Settings -> Add-ons -> Add-on Store**.
3. Open the three-dot menu and choose **Repositories**.
4. Add the URL of this GitHub repository.
5. Find **Switcher2 Bridge** in the add-on store.
6. Install the add-on.
7. Open the add-on **Configuration** tab and adjust the `devices` list.
8. Start the add-on.
9. Check the add-on log for:

```text
Bridge ready: ESPHome native API on port 6053
```

10. In Home Assistant, open **Settings -> Devices & services -> Add integration**.
11. Choose **ESPHome**.
12. Enter the Home Assistant host address and port `6053`.

Use the Home Assistant host address, not `localhost`, unless you know Home
Assistant Core and the add-on resolve `localhost` to the same network namespace.

## Deploy Without GitHub

Copy the `switcher2_bridge` directory to the Home Assistant add-ons directory:

```text
/addons/switcher2_bridge
```

Then in Home Assistant:

1. Open **Settings -> Add-ons -> Add-on Store**.
2. Open the three-dot menu.
3. Choose **Check for updates** or reload add-ons.
4. Install **Switcher2 Bridge** from **Local add-ons**.

## Example Add-on Configuration

The default add-on configuration intentionally has an empty `devices` list. The add-on exits with a clear error until you add at least one Modbus device.

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
    serial:
      port: /dev/serial/by-id/usb-your-adapter
      baud: 19200
      slave_addr: 22
      parity: E
      bytesize: 8
      stopbits: 1
      timeout: 0.2
```

Supported `type` values:

- `switcher2`
- `dds1946_power_meter`
- `rolettini_blinds`

For power meters and Rolettini controllers, use type-specific options such as
`model`, `wordorder`, `read_fc`, `parameters`, and `readable_attributes`.

## Local Build Test

From the repository root:

```sh
docker build -t switcher2-bridge-addon:local switcher2_bridge
```

Create `/tmp/switcher2-addon-data/options.json` with JSON equivalent to the
YAML configuration above, then run:

```sh
docker run --rm \
  --name switcher2-bridge-addon \
  --device /dev/serial/by-id/usb-your-adapter \
  -v /tmp/switcher2-addon-data:/data \
  -p 6053:6053 \
  -p 8090:8090 \
  switcher2-bridge-addon:local
```

If your local serial device is `/dev/ttyUSB0`, replace the `--device` argument
and the configured serial `port` with `/dev/ttyUSB0`.

## Web UI

The add-on exposes the bridge web UI through Home Assistant ingress. Open the
**Switcher2** sidebar item after the add-on starts.

For local Docker testing, open:

```text
http://localhost:8090
```

## Updating the Add-on

After pushing a new commit:

1. Bump `version` in `switcher2_bridge/config.yaml`.
2. Push the repository.
3. In Home Assistant, reload the add-on repository from the add-on store.
4. Install the update.

Home Assistant Supervisor uses the add-on version to decide whether an update is
available.

## Troubleshooting

If Home Assistant cannot connect to the ESPHome device:

- Confirm the add-on is running.
- Confirm the add-on log says the bridge is ready on port `6053`.
- Confirm port `6053` is mapped in the add-on configuration.
- Add ESPHome manually; mDNS discovery is disabled.
- Use the Home Assistant host IP or hostname instead of `localhost`.

If Modbus communication fails:

- Confirm the serial adapter path exists in the add-on logs or host terminal.
- Prefer `/dev/serial/by-id/...` paths.
- Check baud rate, parity, slave address, stop bits, and timeout.
- Check that no other add-on or process is using the same serial device.

If entities are missing:

- Check the configured `devices` list.
- For `switcher2`, verify channel configuration on the hardware; unassigned
  channels are not exposed as lights or covers.
- For `dds1946_power_meter`, verify the `parameters` list.
- For `rolettini_blinds`, verify `readable_attributes`.
