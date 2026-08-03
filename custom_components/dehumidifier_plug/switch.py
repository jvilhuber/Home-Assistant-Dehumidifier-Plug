from homeassistant.components.switch import SwitchEntity
from homeassistant.helpers.restore_state import RestoreEntity
from .const import DOMAIN

AUTO_CONTROL_SWITCH_KEY = "auto_control"

async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    device_info = data["device_info"]

    async_add_entities([
        DehumidifierAutoControlSwitch(coordinator, entry, device_info)
    ])

class DehumidifierAutoControlSwitch(SwitchEntity, RestoreEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, device_info):
        self.coordinator = coordinator
        self._attr_name = "Control"
        self._attr_unique_id = f"{entry.entry_id}_{AUTO_CONTROL_SWITCH_KEY}"
        self._attr_is_on = True  # Default to on unless restored from previous state
        self._attr_device_info = device_info

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        # Restore previous state after Home Assistant restarts
        old_state = await self.async_get_last_state()
        if old_state is not None:
            self._attr_is_on = old_state.state == "on"

    @property
    def is_on(self):
        return self._attr_is_on

    def turn_on(self, **kwargs):
        self._attr_is_on = True
        self.schedule_update_ha_state()

    def turn_off(self, **kwargs):
        self._attr_is_on = False
        self.schedule_update_ha_state()
