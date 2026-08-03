# Home Assistant Dehumidifier Plug Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Default-41BDF5.svg)](https://github.com/hacs/integration)

Integrate plug-controlled dehumidifiers into your Home Assistant. This integration allows you to automate their operation based on humidity levels, energy usage, and a custom schedule.

- [Home Assistant Dehumidifier Plug Integration](#home-assistant-dehumidifier-plug-integration)
  - [Installation](#installation)
  - [Configuration](#configuration)
  - [Entities](#entities)
  - [FAQ](#faq)

## Installation

This integration can be added as a custom repository in HACS. After installing it via HACS:

1. Go to **Settings → Devices & Services → Add Integration**.
2. Search for **Dehumidifier Plug**.
3. Follow the configuration wizard.

## Configuration

For each dehumidifier you want to control, you must add a configuration entry. During the setup flow, you will be asked to select:

- A name for the dehumidifier.
- The plug switch entity.
- The power sensor entity (used to determine if the tank is full).
- The humidity sensor entity.
- The power threshold that indicates a full tank (e.g. 2W).
- The humidity level to start dehumidifying.
- The humidity level to stop dehumidifying.
- The time range during which the dehumidifier is allowed to operate.

The humidity thresholds and the schedule are exposed as adjustable entities (see below), so you can change them at any time from the dashboard, an automation, or a service call — no need to re-open the setup wizard. The **Configure** button remains available to re-point the instance at a different plug or sensor.

## Entities

For each configured dehumidifier, the integration creates:

- `sensor.<name>_status`: shows one of the following states:
  - `Dehumidifying`
  - `Idle`
  - `Below target humidity`
  - `Outside dehumidifying hours`
  - `Full`

- `switch.<name>_control`: enables or disables automatic control logic for the dehumidifier.

- `number.<name>_turn_on_above`: humidity level (%) at which dehumidifying starts.
- `number.<name>_turn_off_below`: humidity level (%) at which dehumidifying stops.
- `time.<name>_start_time`: start of the daily operating window.
- `time.<name>_end_time`: end of the daily operating window.

The `number` and `time` entities are the live source of truth for the thresholds and schedule. Change them from the dashboard (slider / time picker) or from anywhere via `number.set_value` and `time.set_value` — the change takes effect on the next control cycle and persists across restarts. They are categorised as configuration entities.

These entities are grouped under their own device, named after the configuration entry (the dehumidifier instance), and linked to the controlled plug's device via `via_device`. The device and each entity's identity are keyed on the config entry, so renaming the instance keeps the same entities instead of orphaning them.

## FAQ

### How is the "Full" state detected?

When the plug is ON but the power consumption drops below the configured threshold (e.g. 2W), the integration assumes the tank is full.

### What happens if the dehumidifier is full?

The integration detects the "Full" state and stops issuing turn-off or turn-on commands until the user manually empties the tank. It will not automatically turn off the plug — it expects the device itself to stop drawing power.

### Can I change the humidity or schedule after setup?

Yes. Adjust the `number.<name>_turn_on_above` / `number.<name>_turn_off_below` sliders and the `time.<name>_start_time` / `time.<name>_end_time` pickers — from the device page, a dashboard card, or a `number.set_value` / `time.set_value` service call. Changes apply on the next control cycle and survive restarts. To re-point the instance at a different plug or sensor, use the **Configure** option.

### Does the integration support multiple dehumidifiers?

Yes. You can add multiple config entries, each with their own independent settings and entities.