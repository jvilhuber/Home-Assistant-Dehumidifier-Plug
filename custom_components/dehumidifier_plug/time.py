from datetime import datetime, time

from homeassistant.components.time import TimeEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.device_registry import async_get as async_get_device_registry

from .const import DOMAIN
from .utils import slugify

# Config attribute -> presentation. Each entry becomes a time picker that owns
# the corresponding schedule boundary on the coordinator's live config.
TIME_TYPES: dict[str, dict] = {
    "start_time": {"name": "Start Time", "icon": "mdi:clock-start"},
    "end_time": {"name": "End Time", "icon": "mdi:clock-end"},
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entity_registry = async_get_entity_registry(hass)
    device_registry = async_get_device_registry(hass)
    entity_entry = entity_registry.async_get(coordinator.config.switch_entity)
    device_entry = device_registry.async_get(entity_entry.device_id) if entity_entry else None
    device_identifiers = device_entry.identifiers if device_entry else None

    async_add_entities([
        DehumidifierScheduleTime(coordinator, config_key, meta, device_identifiers)
        for config_key, meta in TIME_TYPES.items()
    ])


class DehumidifierScheduleTime(TimeEntity, RestoreEntity):
    """A schedule boundary (start/end) that can be adjusted from the dashboard or a service call."""

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
        self._attr_native_value = getattr(coordinator.config, config_key)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if last_state is not None and last_state.state not in (None, "unknown", "unavailable"):
            try:
                self._attr_native_value = datetime.strptime(last_state.state, "%H:%M:%S").time()
            except ValueError:
                pass
        # The entity is the source of truth for this value at runtime.
        setattr(self.coordinator.config, self._config_key, self._attr_native_value)

    async def async_set_value(self, value: time) -> None:
        self._attr_native_value = value
        setattr(self.coordinator.config, self._config_key, value)
        self.async_write_ha_state()
        await self.coordinator.async_request_refresh()

    @property
    def device_info(self):
        if self._device_identifiers:
            return {"identifiers": self._device_identifiers}
        return None
