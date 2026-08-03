from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.const import Platform
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo, async_get as async_get_device_registry

from .const import (
    DOMAIN,
    CONF_SWITCH, CONF_POWER, CONF_HUMIDITY,
    CONF_FULL_THRESHOLD, CONF_HUMIDITY_ON, CONF_HUMIDITY_OFF,
    CONF_START_TIME, CONF_END_TIME,
    CONF_NAME,
)
from .coordinator import DehumidifierCoordinator
from .models import DehumidifierConfig
from .utils import slugify

PLATFORMS: list[Platform] = [Platform.NUMBER, Platform.SENSOR, Platform.SWITCH, Platform.TIME]

# (platform, old-unique-id suffix, new-unique-id key). The old unique_id was
# f"dehumidifier_{slugify(f'{name}_{suffix}')}"; the new one is
# f"{entry_id}_{key}" so it no longer depends on the (renameable) name.
_UNIQUE_ID_MIGRATIONS = [
    ("sensor", "status", "status"),
    ("switch", "control", "auto_control"),
    ("number", "humidity_on_threshold", "humidity_on_threshold"),
    ("number", "humidity_off_threshold", "humidity_off_threshold"),
    ("time", "start_time", "start_time"),
    ("time", "end_time", "end_time"),
]


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

    # Migrate any pre-1.2 name-based unique_ids before the platforms register,
    # so the entities are recognised (not duplicated) under the stable scheme.
    _migrate_unique_ids(hass, entry, config)

    coordinator = DehumidifierCoordinator(hass, config)
    await coordinator.async_config_entry_first_refresh()

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "device_info": _build_device_info(hass, entry, config),
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


def _build_device_info(hass: HomeAssistant, entry: ConfigEntry, config: DehumidifierConfig) -> DeviceInfo:
    """Build a device for this instance, named after the config entry.

    The control/status/threshold/schedule entities belong to the dehumidifier
    automation, not to the plug hardware, so they live on their own device
    (named after the instance) and are linked to the controlled plug's device
    via ``via_device`` rather than inheriting its name.
    """
    info = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=config.name,
        manufacturer="Dehumidifier Plug",
    )

    # Link under the controlled plug's device if we can resolve it.
    entity_registry = er.async_get(hass)
    device_registry = async_get_device_registry(hass)
    switch_entry = entity_registry.async_get(config.switch_entity)
    plug_device = device_registry.async_get(switch_entry.device_id) if switch_entry and switch_entry.device_id else None
    if plug_device and plug_device.identifiers:
        info["via_device"] = next(iter(plug_device.identifiers))

    return info


def _migrate_unique_ids(hass: HomeAssistant, entry: ConfigEntry, config: DehumidifierConfig) -> None:
    """One-time migration from name-based unique_ids to entry_id-based ones."""
    registry = er.async_get(hass)
    for domain, old_suffix, new_key in _UNIQUE_ID_MIGRATIONS:
        old_uid = f"dehumidifier_{slugify(f'{config.name}_{old_suffix}')}"
        new_uid = f"{entry.entry_id}_{new_key}"
        entity_id = registry.async_get_entity_id(domain, DOMAIN, old_uid)
        if entity_id is None:
            continue  # already migrated or never existed
        if registry.async_get_entity_id(domain, DOMAIN, new_uid) is not None:
            continue  # target already exists; leave the old one for manual cleanup
        registry.async_update_entity(entity_id, new_unique_id=new_uid)


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
