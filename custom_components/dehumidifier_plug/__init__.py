from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.const import Platform

from .const import (
    DOMAIN,
    CONF_SWITCH, CONF_POWER, CONF_HUMIDITY,
    CONF_FULL_THRESHOLD, CONF_HUMIDITY_ON, CONF_HUMIDITY_OFF,
    CONF_START_TIME, CONF_END_TIME,
    CONF_NAME,
)
from .coordinator import DehumidifierCoordinator
from .models import DehumidifierConfig

PLATFORMS: list[Platform] = [Platform.NUMBER, Platform.SENSOR, Platform.SWITCH, Platform.TIME]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Initialize the integration (not used for YAML setup)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration from a config entry."""

    # Merge config entry data and options
    data = {
        **entry.data,
        **entry.options,
        CONF_NAME: entry.title,  # Use the title as internal name
    }

    config = DehumidifierConfig.from_dict(data)
    coordinator = DehumidifierCoordinator(hass, config)
    await coordinator.async_config_entry_first_refresh()

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
    }

    # Reload entry automatically if options are updated
    entry.async_on_unload(entry.add_update_listener(update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the config entry and its platforms."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Reload only when the wiring (plug/sensors/full-power) changed.

    The humidity thresholds and schedule are owned by the number/time entities,
    which already apply their changes to the live config before persisting them
    to the entry. Reloading for those would needlessly tear down the entities,
    so we only reload when a field the entities do not manage has changed.
    """
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not entry_data:
        return

    config = entry_data["coordinator"].config
    merged = {**entry.data, **entry.options}
    wiring_changed = (
        merged.get(CONF_SWITCH) != config.switch_entity
        or merged.get(CONF_POWER) != config.power_sensor
        or merged.get(CONF_HUMIDITY) != config.humidity_sensor
        or float(merged.get(CONF_FULL_THRESHOLD, config.full_power_threshold)) != config.full_power_threshold
    )
    if wiring_changed:
        await hass.config_entries.async_reload(entry.entry_id)

