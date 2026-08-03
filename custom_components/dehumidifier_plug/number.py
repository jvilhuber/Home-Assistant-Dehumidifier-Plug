from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN

# Config attribute -> presentation. Each entry becomes a slider that owns the
# corresponding value on the coordinator's live config.
NUMBER_TYPES: dict[str, dict] = {
    "humidity_on_threshold": {"name": "Turn On Above", "icon": "mdi:water-percent"},
    "humidity_off_threshold": {"name": "Turn Off Below", "icon": "mdi:water-percent-alert"},
}


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    device_info = data["device_info"]

    async_add_entities([
        DehumidifierThresholdNumber(coordinator, entry, config_key, meta, device_info)
        for config_key, meta in NUMBER_TYPES.items()
    ])


class DehumidifierThresholdNumber(NumberEntity):
    """A humidity threshold that can be adjusted from the dashboard or a service call.

    The config entry is the single source of truth: the value is seeded from it
    on setup and written straight back to it on every change, so the first
    control cycle after a restart always runs with the current value.
    """

    _attr_has_entity_name = True
    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
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
        self._attr_native_value = float(getattr(coordinator.config, config_key))

    async def async_set_native_value(self, value: float) -> None:
        value = float(value)
        self._attr_native_value = value
        # Apply live so control reacts immediately...
        setattr(self.coordinator.config, self._config_key, value)
        # ...and persist to the config entry so a restart seeds the same value.
        self.hass.config_entries.async_update_entry(
            self._entry,
            options={**self._entry.options, self._config_key: value},
        )
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()
