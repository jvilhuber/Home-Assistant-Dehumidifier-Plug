from homeassistant import config_entries
from homeassistant.core import callback
import voluptuous as vol
from homeassistant.helpers import selector

from .const import (
    DOMAIN, CONF_NAME, CONF_SWITCH, CONF_POWER, CONF_HUMIDITY,
    CONF_FULL_THRESHOLD, CONF_HUMIDITY_ON, CONF_HUMIDITY_OFF,
    CONF_START_TIME, CONF_END_TIME,
    DEFAULT_FULL_THRESHOLD, DEFAULT_HUMIDITY_ON, DEFAULT_HUMIDITY_OFF,
    DEFAULT_START_TIME, DEFAULT_END_TIME,
)

class DehumidifierConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return DehumidifierOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data=user_input
            )

        # Display the setup form with default values and selectors
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_NAME): selector.TextSelector(),
                vol.Required(CONF_SWITCH): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Required(CONF_POWER): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(CONF_HUMIDITY): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(CONF_FULL_THRESHOLD, default=DEFAULT_FULL_THRESHOLD): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=0.1, mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(CONF_HUMIDITY_ON, default=DEFAULT_HUMIDITY_ON): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=1, unit_of_measurement="%", mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(CONF_HUMIDITY_OFF, default=DEFAULT_HUMIDITY_OFF): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=1, unit_of_measurement="%", mode=selector.NumberSelectorMode.BOX)
                ),
                vol.Optional(CONF_START_TIME, default=DEFAULT_START_TIME): selector.TimeSelector(),
                vol.Optional(CONF_END_TIME, default=DEFAULT_END_TIME): selector.TimeSelector(),
            })
        )

class DehumidifierOptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry):
        self._config_entry = config_entry

    def _current(self, key, fallback=None):
        """Return the effective value for a field, preferring options over data."""
        options = self.config_entry.options
        if key in options:
            return options[key]
        return self.config_entry.data.get(key, fallback)

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # The humidity thresholds and schedule are edited via the number/time
        # entities on the device, so the options flow only covers the wiring:
        # which plug and sensors this instance controls, plus the full-tank
        # power threshold.
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_SWITCH,
                    default=self._current(CONF_SWITCH)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Required(
                    CONF_POWER,
                    default=self._current(CONF_POWER)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(
                    CONF_HUMIDITY,
                    default=self._current(CONF_HUMIDITY)
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    CONF_FULL_THRESHOLD,
                    default=self._current(CONF_FULL_THRESHOLD, DEFAULT_FULL_THRESHOLD)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=0.1, mode=selector.NumberSelectorMode.BOX)
                ),
            })
        )

