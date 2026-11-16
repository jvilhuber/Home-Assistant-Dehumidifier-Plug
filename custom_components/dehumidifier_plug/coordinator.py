from datetime import timedelta
import math
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.entity_component import DEFAULT_SCAN_INTERVAL
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
import logging

from .const import *
from .models import DehumidifierConfig
from .schedule import is_in_schedule
from .utils import _safe_parse_dt

_LOGGER = logging.getLogger(__name__)

class DehumidifierCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, settings: dict, entry_id: str):
        self.hass = hass
        self._entry_id = entry_id
        # `settings` is the merged entry data+options (+name); `_overrides` holds
        # the values adjusted live from the dashboard (number/time entities),
        # persisted in this coordinator's Store. `config` is the two merged.
        self._settings = settings
        self._overrides: dict = {}
        self.config = DehumidifierConfig.from_dict(settings)
        # Key the Store on the stable entry_id, never the user-editable title,
        # so renaming the entry cannot orphan the persisted state.
        self.storage = Store(hass, 1, f"{DOMAIN}_{entry_id}")
        self._last_auto_on = None
        self._power_low_since = None
        self._manual_override = False
        self._last_switch_state = None
        self._auto_turning_on = False
        self._is_full_latched = False
        self._auto_control_enabled = None
        self.unavailable_reason = None

        super().__init__(
            hass,
            _LOGGER,
            name=f"DehumidifierCoordinator_{self.config.name}",
            update_interval=DEFAULT_SCAN_INTERVAL,
        )

        # Restored before the first refresh by async_setup_entry.
        self.auto_control = None

    def rebuild_config(self) -> None:
        """Recompute `config` from the entry settings plus dashboard overrides."""
        self.config = DehumidifierConfig.from_dict({**self._settings, **self._overrides})

    def update_settings(self, settings: dict) -> None:
        """Apply new entry data/options live (no reload)."""
        self._settings = settings
        self.rebuild_config()

    async def set_override(self, key: str, value) -> None:
        """Set one dashboard-adjustable value live and persist it."""
        self._overrides[key] = value
        self.rebuild_config()
        await self.save_persistent_data()

    async def clear_overrides(self) -> None:
        """Drop all dashboard overrides (the Configure dialog is authoritative)."""
        if self._overrides:
            self._overrides = {}
            self.rebuild_config()
            await self.save_persistent_data()

    async def _async_update_data(self):
        try:
            # Snapshot config once so a live override/options change cannot swap
            # thresholds, schedule, window sensors, or the target switch mid-cycle.
            cfg = self.config
            state_switch = self.hass.states.get(cfg.switch_entity)
            state_power = self.hass.states.get(cfg.power_sensor)
            state_humidity = self.hass.states.get(cfg.humidity_sensor)

            # A known opening takes priority over all other dependency faults.
            # Only a positively observed running switch can receive a stop command.
            window_states = {
                entity: self.hass.states.get(entity)
                for entity in (cfg.window_sensors or [])
            }
            windows_open = any(
                state is not None and state.state in ("on", "open")
                for state in window_states.values()
            )
            auto_control = getattr(self, "auto_control", None)
            auto_enabled = auto_control is not None and auto_control.ready and auto_control.is_on
            window_stop_sent = False
            if windows_open and auto_enabled and state_switch and state_switch.state == "on":
                await self.hass.services.async_call("switch", "turn_off", {"entity_id": cfg.switch_entity}, blocking=True)
                window_stop_sent = True
                self._manual_override = False
                self._auto_turning_on = False
                await self.save_persistent_data()

            if not state_switch or not state_power or not state_humidity:
                missing = [entity for entity, state in ((cfg.switch_entity, state_switch), (cfg.power_sensor, state_power), (cfg.humidity_sensor, state_humidity)) if not state]
                raise UpdateFailed(f"Missing entity states: {', '.join(missing)}")

            unavailable = [entity for entity, state in ((cfg.switch_entity, state_switch), (cfg.power_sensor, state_power), (cfg.humidity_sensor, state_humidity)) if state.state in ("unavailable", "unknown")]
            if unavailable:
                raise UpdateFailed(f"Unavailable entities: {', '.join(unavailable)}")
            if state_switch.state not in ("on", "off"):
                raise UpdateFailed(f"Invalid switch state: {cfg.switch_entity}={state_switch.state}")

            if not windows_open:
                faulty_windows = [
                    entity for entity, state in window_states.items()
                    if state is None or state.state not in ("off", "closed")
                ]
                if faulty_windows:
                    raise UpdateFailed(f"Unavailable or invalid window sensors: {', '.join(faulty_windows)}")

            is_on = state_switch.state == "on"
            power = float(state_power.state)
            humidity = float(state_humidity.state)
            if not math.isfinite(power) or not math.isfinite(humidity) or not 0 <= humidity <= 100:
                raise UpdateFailed("Invalid power or humidity reading")
            power_unit = state_power.attributes.get("unit_of_measurement")
            humidity_unit = state_humidity.attributes.get("unit_of_measurement")
            if power_unit == "kW":
                power *= 1000
            elif power_unit not in (None, "W"):
                raise UpdateFailed(f"Unsupported power unit: {power_unit}")
            if humidity_unit not in (None, "%"):
                raise UpdateFailed(f"Unsupported humidity unit: {humidity_unit}")

            now_utc = dt_util.utcnow()
            inside_schedule = is_in_schedule(
                dt_util.now(), cfg.weekdays, cfg.time_windows
            )

            humidity_low = humidity < cfg.humidity_off_threshold
            humidity_high = humidity > cfg.humidity_on_threshold

            # Manual override detection
            previous_state = self._last_switch_state
            self._last_switch_state = state_switch.state

            if previous_state is not None and previous_state != state_switch.state:
                if state_switch.state == "on" and not self._auto_turning_on and not window_stop_sent:
                    self._manual_override = True
                    _LOGGER.debug(f"{self.config.name} - Manual override detected: switch turned on manually.")
                elif state_switch.state == "off":
                    self._manual_override = False
                    _LOGGER.debug(f"{self.config.name} - Switch turned off. Clearing manual override.")
                await self.save_persistent_data()

            # Full detection logic and latching
            is_full = False
            if is_on and not window_stop_sent and power < cfg.full_power_threshold:
                if not self._power_low_since:
                    self._power_low_since = now_utc
                    _LOGGER.debug(f"{self.config.name} - Power dropped below threshold. Starting full timer...")
                    await self.save_persistent_data()
            else:
                if self._power_low_since:
                    _LOGGER.debug(f"{self.config.name} - Power no longer low. Clearing full timer.")
                    self._power_low_since = None
                    await self.save_persistent_data()
                if self._is_full_latched:
                    _LOGGER.debug(f"{self.config.name} - Tank no longer full. Clearing latched full state.")
                    self._is_full_latched = False
                    await self.save_persistent_data()

            if self._power_low_since:
                elapsed = now_utc - self._power_low_since
                if elapsed >= timedelta(seconds=cfg.full_timeout):
                    is_full = True
                    if not self._is_full_latched:
                        _LOGGER.debug(f"{self.config.name} - Power has been low for {elapsed}. Marking as full and latching.")
                        self._is_full_latched = True
                        await self.save_persistent_data()
                        if cfg.notifications_enabled:
                            self.hass.async_create_task(self._notify_full())
                else:
                    _LOGGER.debug(f"{self.config.name} - Power low for {elapsed.total_seconds():.0f}s but threshold not yet met.")

            if self._is_full_latched:
                is_full = True

            _LOGGER.debug(
                f"{self.config.name} - Conditions: auto_enabled={auto_enabled}, inside_schedule={inside_schedule}, "
                f"is_on={is_on}, humidity_low={humidity_low}, humidity_high={humidity_high}, "
                f"is_full={is_full}, manual_override={self._manual_override}, windows_open={windows_open}"
            )

            # Automatic control logic
            if auto_enabled:
                self._auto_turning_on = False
                if windows_open:
                    # Stop was handled before dependency validation. Do not
                    # remember an interrupted cycle: closing uses normal hysteresis.
                    _LOGGER.debug(f"{self.config.name} - Window open. Automatic start blocked.")
                elif inside_schedule:
                    if humidity_high and not is_full and not is_on:
                        _LOGGER.info(f"{self.config.name} - Turning on dehumidifier...")
                        self._auto_turning_on = True
                        await self.hass.services.async_call("switch", "turn_on", {"entity_id": cfg.switch_entity}, blocking=True)
                        self._last_auto_on = now_utc
                        self._manual_override = False
                        await self.save_persistent_data()
                    elif humidity_low and is_on:
                        _LOGGER.info(f"{self.config.name} - Humidity below threshold. Turning off dehumidifier...")
                        await self.hass.services.async_call("switch", "turn_off", {"entity_id": cfg.switch_entity}, blocking=True)
                        self._manual_override = False
                        await self.save_persistent_data()
                else:
                    if is_on:
                        if humidity_low:
                            _LOGGER.info(f"{self.config.name} - Outside schedule and humidity low. Turning off dehumidifier...")
                            await self.hass.services.async_call("switch", "turn_off", {"entity_id": cfg.switch_entity}, blocking=True)
                            self._manual_override = False
                            await self.save_persistent_data()
                        elif self._manual_override:
                            _LOGGER.debug(f"{self.config.name} - Outside schedule. Manually turned on. Leaving dehumidifier on.")
                        elif is_full:
                            _LOGGER.debug(f"{self.config.name} - Outside schedule and latched full. Leaving dehumidifier on.")
                        else:
                            _LOGGER.info(f"{self.config.name} - Outside schedule. Turning off dehumidifier...")
                            await self.hass.services.async_call("switch", "turn_off", {"entity_id": cfg.switch_entity}, blocking=True)

            _LOGGER.debug(
                f"{self.config.name} - Dehumidifier data: is_on={is_on}, power={power:.2f}, humidity={humidity:.2f}, "
                f"inside_schedule={inside_schedule}, humidity_low={humidity_low}, humidity_high={humidity_high}, "
                f"is_full={is_full}, windows_open={windows_open}"
            )

            # Refresh the observed switch state after any command. The
            # service may have completed without the device reporting yet.
            latest_switch = self.hass.states.get(cfg.switch_entity)
            if latest_switch and latest_switch.state in ("on", "off"):
                is_on = latest_switch.state == "on"
            self.unavailable_reason = None
            return {
                "is_on": is_on,
                "is_full": is_full,
                "inside_schedule": inside_schedule,
                "humidity_low": humidity_low,
                "humidity_high": humidity_high,
                "manual_override": self._manual_override,
                "auto_enabled": auto_enabled,
                "windows_open": windows_open,
            }

        except Exception as e:
            self.unavailable_reason = str(e)
            # An observation gap cannot prove that low power was continuous.
            if self._power_low_since is not None and not self._is_full_latched:
                self._power_low_since = None
                await self.save_persistent_data()
            raise UpdateFailed(f"Error updating dehumidifier data: {e}")

    async def _notify_full(self):
        """Notify each mobile app once on entry into the possible-full state."""
        from homeassistant.helpers.translation import async_get_translations

        try:
            translations = await async_get_translations(
                self.hass, self.hass.config.language or "en", "common", {DOMAIN}
            )
            message = translations[f"component.{DOMAIN}.common.possible_full"].format(name=self.config.name)
        except (KeyError, ValueError, TypeError):
            message = f"{self.config.name}: the water tank may be full"
        for target in dict.fromkeys(self.config.notification_targets):
            if not isinstance(target, str) or not target.startswith("notify.mobile_app_"):
                _LOGGER.warning("Invalid notification recipient %s", target)
                continue
            try:
                await self.hass.services.async_call("notify", target.removeprefix("notify."), {"message": message}, blocking=True)
            except Exception:
                _LOGGER.exception("Could not notify %s about %s", target, self.config.name)

    async def load_persistent_data(self):
        data = await self.storage.async_load()
        if not data:
            _LOGGER.debug("%s - No persistent data found; starting fresh.", self.config.name)
            return

        # NOTE: Defensive parsing. Values might be None/empty or even already datetime.
        self._last_auto_on = _safe_parse_dt(data.get("last_auto_on"))
        # Do not count downtime towards a continuous low-power observation.
        self._power_low_since = None
        self._manual_override = bool(data.get("manual_override", False))
        self._last_switch_state = data.get("last_switch_state", None)
        self._is_full_latched = bool(data.get("is_full_latched", False))
        self._auto_control_enabled = data.get("auto_control_enabled")
        # Dashboard-adjusted thresholds/schedule survive restarts. Guard against
        # a corrupt/incompatible persisted value bricking setup on every boot.
        self._overrides = data.get("overrides") or {}
        try:
            self.rebuild_config()
        except Exception as err:
            _LOGGER.warning(
                "%s - Ignoring invalid persisted overrides %s: %s",
                self.config.name, self._overrides, err,
            )
            self._overrides = {}
            self.rebuild_config()

        _LOGGER.debug(
            "%s - Loaded persistent: last_auto_on=%s, power_low_since=%s, manual_override=%s, "
            "last_switch_state=%s, is_full_latched=%s",
            self.config.name,
            self._last_auto_on,
            self._power_low_since,
            self._manual_override,
            self._last_switch_state,
            self._is_full_latched,
        )

    async def save_persistent_data(self):
        try:
            await self.storage.async_save({
                "last_auto_on": self._last_auto_on.isoformat() if self._last_auto_on else None,
                "power_low_since": self._power_low_since.isoformat() if self._power_low_since else None,
                "manual_override": self._manual_override,
                "last_switch_state": self._last_switch_state,
                "is_full_latched": self._is_full_latched,
                "auto_control_enabled": self._auto_control_enabled,
                "overrides": self._overrides,
            })
        except Exception as err:
            _LOGGER.warning("%s - Failed to save persistent data: %s", self.config.name, err)
