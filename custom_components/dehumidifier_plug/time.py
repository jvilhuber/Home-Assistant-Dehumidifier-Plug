"""Dashboard-adjustable schedule window.

These expose the start/end of the dehumidifying schedule as Time entities so
they can be changed from a dashboard instead of only from the Configure dialog.

A change is applied *live* via a coordinator runtime override (persisted to the
coordinator's Store, immediate refresh) — no config-entry write, no reload.

The underlying model supports multiple time windows plus weekdays; these two
entities edit the *first* window only. A single-window setup (the common case)
is fully covered here; multi-window and weekday editing stay in the Configure
dialog.
"""
import logging
from datetime import time

from homeassistant.components.time import TimeEntity
from homeassistant.helpers.entity_registry import async_get as async_get_entity_registry
from homeassistant.helpers.device_registry import async_get as async_get_device_registry

from .const import DOMAIN, CONF_TIME_WINDOWS, DEFAULT_START_TIME, DEFAULT_END_TIME
from .models import parse_time

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entity_registry = async_get_entity_registry(hass)
    device_registry = async_get_device_registry(hass)
    entity_entry = entity_registry.async_get(coordinator.config.switch_entity)
    device_entry = device_registry.async_get(entity_entry.device_id) if entity_entry else None
    device_identifiers = device_entry.identifiers if device_entry else None

    async_add_entities([
        DehumidifierScheduleTime(
            coordinator, entry.entry_id, device_identifiers,
            edge="start", suffix="schedule_start",
            name="Schedule Start", icon="mdi:clock-start",
        ),
        DehumidifierScheduleTime(
            coordinator, entry.entry_id, device_identifiers,
            edge="end", suffix="schedule_end",
            name="Schedule End", icon="mdi:clock-end",
        ),
    ])


class DehumidifierScheduleTime(TimeEntity):
    """One edge (start or end) of the first schedule window."""

    def __init__(self, coordinator, entry_id, device_identifiers, edge, suffix, name, icon):
        self.coordinator = coordinator
        self._edge = edge  # "start" or "end"
        self._attr_icon = icon
        self._attr_name = f"{coordinator.config.name} {name}"
        self._attr_unique_id = f"dehumidifier_{entry_id}_{suffix}"
        self._device_identifiers = device_identifiers

    def _first_window(self):
        windows = self.coordinator.config.time_windows
        if windows:
            return windows[0]
        return (parse_time(DEFAULT_START_TIME), parse_time(DEFAULT_END_TIME))

    @property
    def native_value(self) -> time | None:
        start, end = self._first_window()
        return start if self._edge == "start" else end

    async def async_set_value(self, value: time) -> None:
        windows = list(self.coordinator.config.time_windows) or [self._first_window()]
        start, end = windows[0]
        if self._edge == "start":
            start = value
        else:
            end = value
        if start == end:
            # schedule.py treats start == end as "all day on"; reject it here so
            # a mistaken equal setting can't silently run the dehumidifier 24/7.
            _LOGGER.warning(
                "%s: start and end must differ (equal would run it all day); ignoring %s",
                self._attr_name, value,
            )
            self.async_write_ha_state()  # snap the picker back to the stored value
            return
        windows[0] = (start, end)
        serialized = [{"start": s.isoformat(), "end": e.isoformat()} for s, e in windows]

        # Live: no config-entry write, no reload.
        await self.coordinator.set_override(CONF_TIME_WINDOWS, serialized)
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
