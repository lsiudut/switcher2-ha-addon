# Changelog

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
