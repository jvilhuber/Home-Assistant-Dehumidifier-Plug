from homeassistant.config_entries import ConfigEntry, ConfigEntryError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.const import Platform
from homeassistant.helpers.storage import Store
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry

from .const import (
    DOMAIN,
    CONF_SWITCH, CONF_POWER, CONF_HUMIDITY,
    CONF_FULL_THRESHOLD, CONF_HUMIDITY_ON, CONF_HUMIDITY_OFF,
    CONF_START_TIME, CONF_END_TIME,
    CONF_NAME,
)
from .coordinator import DehumidifierCoordinator
from .models import merge_entry_settings
from .utils import slugify

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.SWITCH, Platform.NUMBER, Platform.TIME]

# (entity-platform domain, unique_id suffix) for every entity this integration
# creates. Used to migrate legacy name-derived unique_ids to stable entry_id ones.
_UNIQUE_ID_SUFFIXES = [
    ("sensor", "status"),
    ("switch", "control"),
    ("number", "humidity_on"),
    ("number", "humidity_off"),
    ("time", "schedule_start"),
    ("time", "schedule_end"),
]


def _migrate_unique_ids(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Move name-derived unique_ids to stable entry_id-based ones.

    Only the unique_id changes; each entity keeps its entity_id, so dashboards
    and automations that reference it keep working. Idempotent and collision-safe.
    """
    registry = async_get_entity_registry(hass)
    for domain, suffix in _UNIQUE_ID_SUFFIXES:
        old_uid = f"dehumidifier_{slugify(f'{entry.title}_{suffix}')}"
        new_uid = f"dehumidifier_{entry.entry_id}_{suffix}"
        if old_uid == new_uid:
            continue
        entity_id = registry.async_get_entity_id(domain, DOMAIN, old_uid)
        if entity_id and registry.async_get_entity_id(domain, DOMAIN, new_uid) is None:
            registry.async_update_entity(entity_id, new_unique_id=new_uid)


async def _migrate_store(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Move the coordinator Store from a name-derived key to the entry_id key."""
    new_store = Store(hass, 1, f"{DOMAIN}_{entry.entry_id}")
    if await new_store.async_load() is not None:
        return
    old_store = Store(hass, 1, f"{DOMAIN}_{slugify(entry.title)}")
    old_data = await old_store.async_load()
    if old_data is not None:
        await new_store.async_save(old_data)
        await old_store.async_remove()


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Initialize the integration (not used for YAML setup)."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration from a config entry."""

    # Register before a failed setup so correcting Options can recover it.
    entry.async_on_unload(entry.add_update_listener(update_listener))
    settings = {**merge_entry_settings(entry.data, entry.options), CONF_NAME: entry.title}
    missing = [key for key in (CONF_SWITCH, CONF_POWER, CONF_HUMIDITY) if not settings.get(key)]
    if missing:
        raise ConfigEntryError(
            f"Missing configuration: {', '.join(missing)}. Open Configure to select entities."
        )

    # One-time migrations to stable entry_id-based identity (before entities are
    # created and before the Store is read), so a future entry rename is safe.
    _migrate_unique_ids(hass, entry)
    await _migrate_store(hass, entry)

    coordinator = DehumidifierCoordinator(hass, settings, entry.entry_id)
    # Loads persisted dashboard overrides and rebuilds config with them applied.
    await coordinator.load_persistent_data()

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # An unavailable dependency must not prevent the entry and its controls
    # from loading; the regular coordinator refresh will retry automatically.
    await coordinator.async_refresh()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the config entry and its platforms."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok


async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Apply changed options live, without reloading the integration.

    Saving the Configure dialog is authoritative: new settings replace the live
    config and any dashboard overrides are cleared. No platform reload, so the
    entities never flicker unavailable.
    """
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if not entry_data:
        return
    coordinator = entry_data["coordinator"]
    settings = {**merge_entry_settings(entry.data, entry.options), CONF_NAME: entry.title}
    coordinator.update_settings(settings)
    await coordinator.clear_overrides()
    await coordinator.async_request_refresh()
