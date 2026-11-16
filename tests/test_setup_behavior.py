"""Behavioral tests for setup, options recovery, and entry reloads."""
import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "dehumidifier_plug"


def load_module(name):
    module_name = "dehumidifier_plug." + name
    spec = importlib.util.spec_from_file_location(module_name, ROOT / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class SetupTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        package = sys.modules.setdefault("dehumidifier_plug", types.ModuleType("dehumidifier_plug"))
        package.__path__ = [str(ROOT)]
        config_entries = sys.modules.setdefault("homeassistant.config_entries", types.ModuleType("homeassistant.config_entries"))
        config_entries.ConfigEntry = object
        config_entries.ConfigEntryError = type("ConfigEntryError", (Exception,), {})
        core = sys.modules.setdefault("homeassistant.core", types.ModuleType("homeassistant.core"))
        core.HomeAssistant = object
        typing_module = sys.modules.setdefault("homeassistant.helpers.typing", types.ModuleType("homeassistant.helpers.typing"))
        typing_module.ConfigType = dict
        const = sys.modules.setdefault("homeassistant.const", types.ModuleType("homeassistant.const"))
        const.Platform = SimpleNamespace(SENSOR="sensor", SWITCH="switch", NUMBER="number", TIME="time")

        class _FakeStore:
            def __init__(self, *args, **kwargs):
                pass
            async def async_load(self):
                return None
            async def async_save(self, data):
                pass
            async def async_remove(self):
                pass
        storage = sys.modules.setdefault("homeassistant.helpers.storage", types.ModuleType("homeassistant.helpers.storage"))
        storage.Store = _FakeStore
        registry_module = sys.modules.setdefault("homeassistant.helpers.entity_registry", types.ModuleType("homeassistant.helpers.entity_registry"))
        registry_module.async_get = lambda hass: SimpleNamespace(
            async_get_entity_id=lambda *a, **k: None,
            async_update_entity=lambda *a, **k: None,
        )
        utils_module = sys.modules.setdefault("dehumidifier_plug.utils", types.ModuleType("dehumidifier_plug.utils"))
        utils_module.slugify = lambda value: value.lower().replace(" ", "_")

        load_module("const")
        load_module("models")
        fake_coordinator = types.ModuleType("dehumidifier_plug.coordinator")
        fake_coordinator.DehumidifierCoordinator = Mock()
        sys.modules["dehumidifier_plug.coordinator"] = fake_coordinator
        cls.module = load_module("__init__")
        cls.error_type = config_entries.ConfigEntryError

    def entry(self, **overrides):
        data = {
            "switch_entity": "switch.plug", "power_sensor": "sensor.power",
            "humidity_sensor": "sensor.humidity", "full_power_threshold": 2,
            "humidity_on_threshold": 60, "humidity_off_threshold": 50,
            "start_time": "09:00:00", "end_time": "20:00:00",
        }
        data.update(overrides)
        entry = SimpleNamespace(
            data=data, options={}, title="Bathroom", entry_id="entry-1",
            add_update_listener=Mock(return_value=Mock()),
            async_on_unload=Mock(),
        )
        hass = SimpleNamespace(
            data={}, config_entries=SimpleNamespace(
                async_forward_entry_setups=AsyncMock(),
                async_unload_platforms=AsyncMock(return_value=True),
                async_reload=AsyncMock(),
            ),
        )
        return hass, entry

    async def test_setup_loads_and_merges_options(self):
        hass, entry = self.entry()
        entry.options = {"power_sensor": "sensor.new", "weekdays": ["mon"],
                         "time_windows": [{"start": "11:00", "end": "12:00"}]}
        with patch.object(self.module, "DehumidifierCoordinator") as factory:
            factory.return_value.load_persistent_data = AsyncMock()
            factory.return_value.async_refresh = AsyncMock()
            self.assertTrue(await self.module.async_setup_entry(hass, entry))
            self.assertEqual(factory.call_args.args[1]["power_sensor"], "sensor.new")
            self.assertEqual(factory.call_args.args[1]["weekdays"], ["mon"])
        hass.config_entries.async_forward_entry_setups.assert_awaited_once()
        entry.add_update_listener.assert_called_once()

    async def test_missing_power_registers_listener_before_error(self):
        hass, entry = self.entry(power_sensor=None)
        with self.assertRaises(self.error_type):
            await self.module.async_setup_entry(hass, entry)
        entry.async_on_unload.assert_called_once()
        hass.config_entries.async_forward_entry_setups.assert_not_awaited()

    async def test_none_option_does_not_override_valid_sensor(self):
        hass, entry = self.entry()
        entry.options = {"power_sensor": None}
        with patch.object(self.module, "DehumidifierCoordinator") as factory:
            factory.return_value.load_persistent_data = AsyncMock()
            factory.return_value.async_refresh = AsyncMock()
            await self.module.async_setup_entry(hass, entry)
            self.assertEqual(factory.call_args.args[1]["power_sensor"], "sensor.power")

    async def test_update_listener_applies_live_without_reload(self):
        hass, entry = self.entry()
        coord = SimpleNamespace(
            update_settings=Mock(), clear_overrides=AsyncMock(),
            async_request_refresh=AsyncMock(),
        )
        hass.data["dehumidifier_plug"] = {"entry-1": {"coordinator": coord}}
        await self.module.update_listener(hass, entry)
        coord.update_settings.assert_called_once()
        coord.clear_overrides.assert_awaited_once()
        coord.async_request_refresh.assert_awaited_once()
        hass.config_entries.async_reload.assert_not_awaited()

    async def test_unload_removes_coordinator(self):
        hass, entry = self.entry()
        hass.data["dehumidifier_plug"] = {"entry-1": {"coordinator": object()}}
        self.assertTrue(await self.module.async_unload_entry(hass, entry))
        self.assertNotIn("entry-1", hass.data["dehumidifier_plug"])

    async def test_failed_unload_preserves_coordinator(self):
        hass, entry = self.entry()
        hass.data["dehumidifier_plug"] = {"entry-1": {"coordinator": object()}}
        hass.config_entries.async_unload_platforms.return_value = False
        self.assertFalse(await self.module.async_unload_entry(hass, entry))
        self.assertIn("entry-1", hass.data["dehumidifier_plug"])

    async def test_migration_renames_unique_ids_and_copies_store(self):
        hass, entry = self.entry()
        updated = []
        registry = SimpleNamespace(
            # Old name-based "status" uid resolves to an entity; its new uid is free.
            async_get_entity_id=lambda domain, platform, uid: (
                "sensor.old" if uid.endswith("_status") and "entry-1" not in uid else None
            ),
            async_update_entity=lambda eid, new_unique_id: updated.append((eid, new_unique_id)),
        )
        saved = {}

        class CopyStore:
            def __init__(self, hass, version, key):
                self.key = key
            async def async_load(self):
                # Old (name-based) store holds data; the new entry_id store is empty.
                return {"manual_override": True} if "entry-1" not in self.key else None
            async def async_save(self, data):
                saved["data"] = data
            async def async_remove(self):
                saved["removed"] = True

        with patch.object(self.module, "async_get_entity_registry", lambda hass: registry), \
             patch.object(self.module, "Store", CopyStore), \
             patch.object(self.module, "DehumidifierCoordinator") as factory:
            factory.return_value.load_persistent_data = AsyncMock()
            factory.return_value.async_refresh = AsyncMock()
            await self.module.async_setup_entry(hass, entry)

        self.assertTrue(any(nu.endswith("_status") and "entry-1" in nu for _, nu in updated))
        self.assertEqual(saved.get("data"), {"manual_override": True})
        self.assertTrue(saved.get("removed"))


if __name__ == "__main__":
    unittest.main()
