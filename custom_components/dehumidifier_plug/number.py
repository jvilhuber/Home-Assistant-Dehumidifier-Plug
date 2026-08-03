from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
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
        DehumidifierThresholdNumber(coordinator, config_key, meta, device_identifiers)
        for config_key, meta in NUMBER_TYPES.items()
    ])


class DehumidifierThresholdNumber(RestoreNumber):
    """A humidity threshold that can be adjusted from the dashboard or a service call."""

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER
    _attr_entity_category = EntityCategory.CONFIG
    _attr_should_poll = False

    def __init__(self, coordinator, config_key, meta, device_identifiers):
        self.coordinator = coordinator
        self._config_key = config_key
        object_id = slugify(f"{coordinator.config.name}_{config_key}")
        self._attr_name = f"{coordinator.config.name} {meta['name']}"
        self._attr_unique_id = f"dehumidifier_{object_id}"
        self._attr_icon = meta["icon"]
        self._device_identifiers = device_identifiers
        # Seed from the config entry; overridden by the restored value if present.
        self._attr_native_value = float(getattr(coordinator.config, config_key))

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._attr_native_value = last.native_value
        # The entity is the source of truth for this value at runtime.
        setattr(self.coordinator.config, self._config_key, float(self._attr_native_value))

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        setattr(self.coordinator.config, self._config_key, float(value))
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    @property
    def device_info(self):
        if self._device_identifiers:
            return {"identifiers": self._device_identifiers}
        return None
