# Changelog

## 0.1.13

- Re-read a light's authoritative channel-state register 50 ms after a
  successful command so Home Assistant receives prompt, verified feedback.
- Wake the ESPHome asyncio writer safely when Modbus workers publish changes,
  avoiding event-loop-dependent notification delays.

## 0.1.12

- Resolve web UI requests beneath the active Home Assistant ingress path so
  API calls reach the add-on instead of Home Assistant Core.
- Show API failures as connection errors rather than claiming that no devices
  are configured.

## 0.1.11

- Replace the long controller forms with compact channel and input selectors,
  plain-language labels, guided editors, and a separate advanced section.
- Move the input-action register base from 350 to 700 to match current
  firmware and avoid the OTA register range.

## 0.1.10

- Move routine serial profile changes, serial connection timing, and ESPHome
  client lifecycle messages from `INFO` to `DEBUG`.
- Report unavailable-device connection closures and rejections as warnings.

## 0.1.9

- Advertise cumulative power-meter energy counters as `total_increasing` so
  Home Assistant records long-term energy statistics without requiring
  `last_reset`.

## 0.1.8

- Set `init: false` so s6-overlay runs as PID 1 under Home Assistant Supervisor.

## 0.1.7

- Run the add-on service without `with-contenv`/`bashio` to avoid s6 suexec PID errors.

## 0.1.6

- Replace file-based config with flattened Supervisor options.
- Rebuild nested bridge device config at startup from flat device fields.

## 0.1.5

- Move bridge configuration to a normal YAML file in the add-on config directory.
- Replace raw `config_yaml` option with a simple `config_file` path option.

## 0.1.4

- Replace nested Supervisor device schema with a raw `config_yaml` option.
- Parse full bridge configuration inside the add-on to support type-specific keys.

## 0.1.3

- Simplify Supervisor schema to avoid unsupported optional dictionary fields.

## 0.1.2

- Fix optional Supervisor schema fields so device configs can be saved.

## 0.1.1

- Fix add-on service runner path for current Home Assistant base images.
- Add an explicit Supervisor options schema so edited configuration is retained.
- Keep the default `devices` list empty until configured by the user.

## 0.1.0

- Initial Home Assistant add-on packaging.
- Runs the existing ESPHome-native Modbus bridge in a supervised container.
- Disables mDNS discovery in add-on mode.
