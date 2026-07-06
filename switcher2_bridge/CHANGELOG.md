# Changelog

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
