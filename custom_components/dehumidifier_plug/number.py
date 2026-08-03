from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.device_registry import async_get as async_get_device_registry

from .const import DOMAIN
from .utils import slugify

# Config attribute -> presentation. Each entry becomes a slider that owns the
# corresponding value on the coordinator's live config.
NUMBER_TYPES: dict[str, dict] = {
    "humidity_on_threshold": {"name": "Turn On Above", "icon": "mdi:water-percent"},
    "humidity_off_threshold": {"name": "Turn Off Below", "icon": "mdi:water-percent-alert"},
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entity_registry = async_get_entity_registry(hass)
    device_registry = async_get_device_registry(hass)
    entity_entry = entity_registry.async_get(coordinator.config.switch_entity)
    device_entry = device_registry.async_get(entity_entry.device_id) if entity_entry else None
    device_identifiers = device_entry.identifiers if device_entry else None

    async_add_entities([
        DehumidifierThresholdNumber(coordinator, entry, config_key, meta, device_identifiers)
        for config_key, meta in NUMBER_TYPES.items()
    ])


class DehumidifierThresholdNumber(NumberEntity):
    """A humidity threshold that can be adjusted from the dashboard or a service call.

    The config entry is the single source of truth: the value is seeded from it
    on setup and written straight back to it on every change, so the first
    control cycle after a restart always runs with the current value.
    """

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(self, coordinator, entry, config_key, meta, device_identifiers):
        self.coordinator = coordinator
        self._entry = entry
        self._config_key = config_key
        object_id = slugify(f"{coordinator.config.name}_{config_key}")
        self._attr_name = f"{coordinator.config.name} {meta['name']}"
        self._attr_unique_id = f"dehumidifier_{object_id}"
        self._attr_icon = meta["icon"]
        self._device_identifiers = device_identifiers
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

    @property
    def device_info(self):
        if self._device_identifiers:
            return {"identifiers": self._device_identifiers}
        return None
