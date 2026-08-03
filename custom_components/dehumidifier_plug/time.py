from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN

# Config attribute -> presentation. Each entry becomes a time picker that owns
# the corresponding schedule boundary on the coordinator's live config.
TIME_TYPES: dict[str, dict] = {
    "start_time": {"name": "Start Time", "icon": "mdi:clock-start"},
    "end_time": {"name": "End Time", "icon": "mdi:clock-end"},
}


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    device_info = data["device_info"]

    async_add_entities([
        DehumidifierScheduleTime(coordinator, entry, config_key, meta, device_info)
        for config_key, meta in TIME_TYPES.items()
    ])


class DehumidifierScheduleTime(TimeEntity):
    """A schedule boundary (start/end) adjustable from the dashboard or a service call.

    The config entry is the single source of truth: the value is seeded from it
    on setup and written straight back to it on every change, so the first
    control cycle after a restart always runs with the current value.
    """

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(self, coordinator, entry, config_key, meta, device_info):
        self.coordinator = coordinator
        self._entry = entry
        self._config_key = config_key
        self._attr_name = meta["name"]
        self._attr_unique_id = f"{entry.entry_id}_{config_key}"
        self._attr_icon = meta["icon"]
        self._attr_device_info = device_info
        self._attr_native_value = getattr(coordinator.config, config_key)

    async def async_set_value(self, value: time) -> None:
        self._attr_native_value = value
        # Apply live so control reacts immediately...
        setattr(self.coordinator.config, self._config_key, value)
        # ...and persist to the config entry (as HH:MM:SS, matching from_dict)
        # so a restart seeds the same value.
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, self._config_key: value.strftime("%H:%M:%S")},
        )
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
