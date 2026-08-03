from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.helpers.entity import EntityCategory
from .const import DOMAIN

SENSOR_TYPES: dict[str, SensorEntityDescription] = {
    "status": SensorEntityDescription(
        key="status",
        name="Status",
        icon="mdi:air-humidifier",
    ),
}

async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    device_info = data["device_info"]

    entities = [
        DehumidifierSensor(coordinator, entry, sensor_id, description, device_info)
        for sensor_id, description in SENSOR_TYPES.items()
    ]
    async_add_entities(entities)

class DehumidifierSensor(SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry, sensor_id, description, device_info):
        self.coordinator = coordinator
        self.sensor_id = sensor_id
        self.entity_description = description
        self._attr_name = description.name
        self._attr_unique_id = f"{entry.entry_id}_{sensor_id}"
        self._attr_device_info = device_info
        if sensor_id != "status":
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self):
        data = self.coordinator.data
        if not data:
            return None

        # Priority: Full > Dehumidifying > Outside hours > Below target > Idle
        if data.get("is_full"):
            return "Full"
        if data.get("is_on") or data.get("manual_override"):
            return "Dehumidifying"
        if not data.get("inside_schedule"):
            return "Outside dehumidifying hours"
        if data.get("humidity_low"):
            return "Below target humidity"
        return "Idle"

    @property
    def available(self):
        return self.coordinator.last_update_success

    async def async_update(self):
        await self.coordinator.async_request_refresh()

    async def async_added_to_hass(self):
        self.async_on_remove(
            self.coordinator.async_add_listener(self.async_write_ha_state)
        )
