"""Dashboard-adjustable humidity thresholds.

These expose the on/off humidity thresholds as Number entities so they can be
changed from a dashboard (e.g. by non-admin users) instead of only from the
integration's Configure dialog.

A change is applied *live*: it updates the coordinator's runtime override,
persists it to the coordinator's Store, and requests an immediate refresh.
There is no config-entry write and no integration reload, so none of the
entities flicker. Saving the Configure dialog clears these overrides (it is
authoritative) via the entry's update listener.
"""
from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.const import PERCENTAGE
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.device_registry import async_get as async_get_device_registry

from .const import DOMAIN, CONF_HUMIDITY_ON, CONF_HUMIDITY_OFF

# Keep at least this gap (in %) between the on and off thresholds so the two
# sliders can never cross and make the control logic oscillate.
MIN_GAP = 1.0


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entity_registry = async_get_entity_registry(hass)
    device_registry = async_get_device_registry(hass)
    entity_entry = entity_registry.async_get(coordinator.config.switch_entity)
    device_entry = device_registry.async_get(entity_entry.device_id) if entity_entry else None
    device_identifiers = device_entry.identifiers if device_entry else None

    async_add_entities([
        DehumidifierThreshold(
            coordinator, entry.entry_id, device_identifiers,
            key=CONF_HUMIDITY_ON, suffix="humidity_on",
            name="Humidity On", icon="mdi:water-percent",
        ),
        DehumidifierThreshold(
            coordinator, entry.entry_id, device_identifiers,
            key=CONF_HUMIDITY_OFF, suffix="humidity_off",
            name="Humidity Off", icon="mdi:water-percent-alert",
        ),
    ])


class DehumidifierThreshold(NumberEntity):
    """A humidity threshold, adjustable live from the dashboard."""

    _attr_native_min_value = 0
    _attr_native_max_value = 100
    _attr_native_step = 1
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator, entry_id, device_identifiers, key, suffix, name, icon):
        self.coordinator = coordinator
        self._key = key
        self._attr_icon = icon
        self._attr_name = f"{coordinator.config.name} {name}"
        self._attr_unique_id = f"dehumidifier_{entry_id}_{suffix}"
        self._device_identifiers = device_identifiers

    @property
    def native_value(self):
        if self._key == CONF_HUMIDITY_ON:
            return self.coordinator.config.humidity_on_threshold
        return self.coordinator.config.humidity_off_threshold

    async def async_set_native_value(self, value: float) -> None:
        on = self.coordinator.config.humidity_on_threshold
        off = self.coordinator.config.humidity_off_threshold
        if self._key == CONF_HUMIDITY_ON:
            # "On" must stay above "off" by at least MIN_GAP.
            value = max(value, off + MIN_GAP)
        else:
            # "Off" must stay below "on" by at least MIN_GAP.
            value = min(value, on - MIN_GAP)
        value = min(100.0, max(0.0, float(value)))

        # Live: no config-entry write, no reload.
        await self.coordinator.set_override(self._key, value)
        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()

    @property
    def device_info(self):
        if self._device_identifiers:
            return {"identifiers": self._device_identifiers}
        return None

    async def async_added_to_hass(self):
        # Reflect Configure-dialog changes (which refresh the coordinator).
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )
