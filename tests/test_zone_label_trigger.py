"""Unit tests for the zone_label_trigger helper functions."""

from types import SimpleNamespace

from custom_components.zone_label_trigger import trigger


class DummyState:
    def __init__(self, entity_id, state, attributes=None):
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes or {}


def test_zone_identifiers_contains_expected():
    z = DummyState("zone.work", "zone.work", {"friendly_name": "Work"})
    ids = trigger._zone_identifiers(z)
    assert "zone.work" in ids
    assert "work" in ids
    assert "Work" in ids or "work" in ids


def test_get_matching_zone_entity_ids_filters_by_label(hass):
    """_get_matching_zone_entity_ids should consult the Entity Registry labels."""
    from homeassistant.helpers import label_registry as lr, entity_registry as er

    # Reserve registry entry for the zone BEFORE setting the state so the
    # registry entry's entity_id matches the state entity_id (avoid suffixes).
    ent_reg = er.async_get(hass)
    entry = ent_reg.async_get_or_create("zone", "test", "one", suggested_object_id="one")

    hass.states.async_set("zone.one", "zone", {"friendly_name": "One"})
    hass.states.async_set("zone.two", "zone", {"friendly_name": "Two"})

    # Create label and attach to the registry entry
    label = lr.async_get(hass).async_create("Work")
    ent_reg.async_update_entity(entry.entity_id, labels=[label.label_id])

    matches = trigger._get_matching_zone_entity_ids(hass, "work")
    assert matches == ["zone.one"]


import pytest


@pytest.mark.asyncio
async def test_async_get_trigger_capabilities():
    """async_get_trigger_capabilities returns UI field/select metadata."""
    caps = await trigger.async_get_trigger_capabilities(None, {"platform": "zone_label", "target": {"label_id": "work"}})

    assert "extra_fields" in caps
    extra = caps["extra_fields"]

    # `label` is not an editable field (the selected Label is provided via Target)
    assert "label" not in extra

    # Editor should expose `entity_id` (person/device) and `event` selectors
    assert "entity_id" in extra
    assert extra["entity_id"]["selector"] == {"entity": {"domain": ["person", "device_tracker"]}}
    assert extra["entity_id"].get("required") is True

    assert "event" in extra
    assert extra["event"].get("required") is True
    options = extra["event"]["selector"]["select"]["options"]
    assert any(o["value"] == "enter" for o in options)
    assert any(o["value"] == "exit" for o in options)
    assert any(o["value"] == "both" for o in options)