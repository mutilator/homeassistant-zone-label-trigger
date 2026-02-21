"""Simple import and schema tests for the zone_label_trigger integration."""

from importlib import import_module


def test_trigger_module_importable():
    mod = import_module("custom_components.zone_label_trigger.trigger")
    assert hasattr(mod, "async_attach_trigger")
    assert hasattr(mod, "TRIGGER_SCHEMA")
    # Expose async_get_triggers so Home Assistant can discover triggers at startup
    assert hasattr(mod, "async_get_triggers")


def test_init_module_importable():
    mod = import_module("custom_components.zone_label_trigger")
    assert hasattr(mod, "async_setup")
