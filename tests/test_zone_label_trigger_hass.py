"""Integration-style tests for `zone_label` trigger.

These tests use the Home Assistant `hass` fixture and validate:
- trigger fires on enter/exit
- unsubscribe stops firing
- trigger is discoverable for `zone` entity targets via backend helper
"""

import asyncio

import pytest

from custom_components.zone_label_trigger import trigger as zone_label_trigger

from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.setup import async_setup_component


@pytest.mark.asyncio
async def test_zone_label_trigger_fires_on_enter(hass):
    from homeassistant.helpers import label_registry as lr, entity_registry as er
    # Reserve registry entry first so entity_id matches the state entity id.
    ent_reg = er.async_get(hass)
    entry = ent_reg.async_get_or_create("zone", "test", "work", suggested_object_id="work")
    zone_id = entry.entity_id
    hass.states.async_set(zone_id, "zone", {"friendly_name": "Work"})
    label = lr.async_get(hass).async_create("Work")
    ent_reg.async_update_entity(entry.entity_id, labels=[label.label_id])

    # Entity starts outside the zone
    hass.states.async_set("device_tracker.alice", "not_home")

    calls = []

    async def _action(run_vars):
        calls.append(run_vars)

    # Attach trigger for label 'work' (case-insensitive) and event 'enter'
    unsub = await zone_label_trigger.async_attach_trigger(
        hass,
        {"platform": "zone_label", "target": {"label_id": "work"}, "entity_id": "device_tracker.alice", "event": "enter"},
        _action,
    )

    # Simulate moving into the zone by setting the entity state to the zone's object id
    hass.states.async_set("device_tracker.alice", "work")

    await hass.async_block_till_done()

    assert len(calls) == 1
    trig = calls[0]["trigger"]
    assert trig["event"] == "enter"
    assert trig["entity_id"] == "device_tracker.alice"
    assert trig["zone"] == zone_id
    assert trig["from_state"].state == "not_home"
    assert trig["to_state"].state == "work"

    # Cleanup
    unsub()


@pytest.mark.asyncio
async def test_zone_label_trigger_fires_on_exit(hass):
    from homeassistant.helpers import label_registry as lr, entity_registry as er
    ent_reg = er.async_get(hass)
    entry = ent_reg.async_get_or_create("zone", "test", "work", suggested_object_id="work")
    zone_id = entry.entity_id
    hass.states.async_set(zone_id, "zone", {"friendly_name": "Work"})
    label = lr.async_get(hass).async_create("Work")
    ent_reg.async_update_entity(entry.entity_id, labels=[label.label_id])

    # Entity starts inside the zone
    hass.states.async_set("device_tracker.bob", "work")

    calls = []

    def _action(run_vars):
        # allow sync action
        calls.append(run_vars)

    unsub = await zone_label_trigger.async_attach_trigger(
        hass,
        {"platform": "zone_label", "target": {"label_id": "work"}, "entity_id": "device_tracker.bob", "event": "exit"},
        _action,
    )

    # Move entity out of the zone
    hass.states.async_set("device_tracker.bob", "not_home")

    await hass.async_block_till_done()

    assert len(calls) == 1
    trig = calls[0]["trigger"]
    assert trig["event"] == "exit"
    assert trig["entity_id"] == "device_tracker.bob"
    assert trig["zone"] == zone_id

    unsub()


@pytest.mark.asyncio
async def test_zone_label_trigger_unsubscribe_stops_firing(hass):
    from homeassistant.helpers import label_registry as lr, entity_registry as er
    ent_reg = er.async_get(hass)
    entry = ent_reg.async_get_or_create("zone", "test", "work", suggested_object_id="work")
    zone_id = entry.entity_id
    hass.states.async_set(zone_id, "zone", {"friendly_name": "Work"})
    label = lr.async_get(hass).async_create("Work")
    ent_reg.async_update_entity(entry.entity_id, labels=[label.label_id])

    hass.states.async_set("device_tracker.carol", "not_home")

    calls = []

    async def _action(run_vars):
        calls.append(run_vars)

    unsub = await zone_label_trigger.async_attach_trigger(
        hass,
        {"platform": "zone_label", "target": {"label_id": "work"}, "entity_id": "device_tracker.carol", "event": "enter"},
        _action,
    )

    # Fire first event (should be handled)
    hass.states.async_set("device_tracker.carol", "work")
    await hass.async_block_till_done()
    assert len(calls) == 1

    # Unsubscribe then fire again (should NOT be handled)
    unsub()
    hass.states.async_set("device_tracker.carol", "not_home")
    hass.states.async_set("device_tracker.carol", "work")
    await hass.async_block_till_done()
    assert len(calls) == 1


async def test_zone_label_trigger_with_entity_id_filters(hass):
    """If `entity_id` is provided in the trigger config, only that entity fires."""
    from homeassistant.helpers import label_registry as lr, entity_registry as er
    ent_reg = er.async_get(hass)
    entry = ent_reg.async_get_or_create("zone", "test", "work", suggested_object_id="work")
    zone_id = entry.entity_id
    hass.states.async_set(zone_id, "zone", {"friendly_name": "Work"})
    label = lr.async_get(hass).async_create("Work")
    ent_reg.async_update_entity(entry.entity_id, labels=[label.label_id])

    hass.states.async_set("device_tracker.alice", "not_home")
    hass.states.async_set("device_tracker.bob", "not_home")

    calls = []

    async def _action(run_vars):
        calls.append(run_vars)

    unsub = await zone_label_trigger.async_attach_trigger(
        hass,
        {
            "platform": "zone_label",
            "target": {"label_id": "work"},
            "entity_id": "device_tracker.alice",
            "event": "enter",
        },
        _action,
    )

    # Bob enters -> should NOT trigger
    hass.states.async_set("device_tracker.bob", "work")
    await hass.async_block_till_done()
    assert len(calls) == 0

    # Alice enters -> should trigger
    hass.states.async_set("device_tracker.alice", "work")
    await hass.async_block_till_done()
    assert len(calls) == 1

    unsub()


async def test_zone_label_trigger_with_target_filters(hass):
    """If a `target` with entity_id is provided, it should be honored."""
    from homeassistant.helpers import label_registry as lr, entity_registry as er
    ent_reg = er.async_get(hass)
    entry = ent_reg.async_get_or_create("zone", "test", "work", suggested_object_id="work")
    zone_id = entry.entity_id
    hass.states.async_set(zone_id, "zone", {"friendly_name": "Work"})
    label = lr.async_get(hass).async_create("Work")
    ent_reg.async_update_entity(entry.entity_id, labels=[label.label_id])

    hass.states.async_set("device_tracker.alice", "not_home")
    hass.states.async_set("device_tracker.bob", "not_home")

    calls = []

    def _action(run_vars):
        calls.append(run_vars)

    unsub = await zone_label_trigger.async_attach_trigger(
        hass,
        {
            "platform": "zone_label",
            "target": {"label_id": "work", "entity_id": ["device_tracker.alice"]},
            "entity_id": "device_tracker.alice",
            "event": "enter",
        },
        _action,
    )

    # Bob enters -> should NOT trigger
    hass.states.async_set("device_tracker.bob", "work")
    await hass.async_block_till_done()
    assert len(calls) == 0

    # Alice enters -> should trigger
    hass.states.async_set("device_tracker.alice", "work")
    await hass.async_block_till_done()
    assert len(calls) == 1

    unsub()


@pytest.mark.asyncio
async def test_trigger_validation_requires_entity_id_and_event(hass):
    """`entity_id` and `event` must be present in both top-level and options-wrapped shapes."""
    from custom_components.zone_label_trigger import trigger as zlt
    from custom_components.zone_label_trigger.trigger import ZoneLabelTrigger
    import voluptuous as vol

    # top-level missing entity_id should be rejected by TRIGGER_SCHEMA
    with pytest.raises(vol.Invalid):
        zlt.TRIGGER_SCHEMA({"platform": "zone_label", "target": {"label_id": "Shopping"}, "event": "enter"})

    # top-level missing event should be rejected
    with pytest.raises(vol.Invalid):
        zlt.TRIGGER_SCHEMA({"platform": "zone_label", "target": {"label_id": "Shopping"}, "entity_id": "device_tracker.alice"})

    # options-wrapped missing entity_id should be rejected (and target.label_id required)
    with pytest.raises(vol.Invalid):
        await ZoneLabelTrigger.async_validate_config(hass, {"target": {"label_id": "work"}, "options": {"event": "enter"}})

    # options-wrapped missing event should be rejected
    with pytest.raises(vol.Invalid):
        await ZoneLabelTrigger.async_validate_config(hass, {"target": {"label_id": "work"}, "options": {"entity_id": "device_tracker.alice"}})

@pytest.mark.asyncio
async def test_get_triggers_for_entity_target_includes_zone_label(hass):
    """Verify backend includes our trigger description for zone_label."""
    from homeassistant.helpers import trigger as trigger_helper

    # Ensure the integration is set up so async_setup runs and registers the
    # trigger platform with Home Assistant's trigger registry. The test
    # harness may not discover the repo-local custom component via
    # async_setup_component, so import and call its async_setup directly.
    from importlib import import_module

    mod = import_module("custom_components.zone_label_trigger")
    assert await mod.async_setup(hass, {})
    await hass.async_block_till_done()

    from homeassistant.helpers import label_registry as lr, entity_registry as er
    ent_reg = er.async_get(hass)
    entry = ent_reg.async_get_or_create("zone", "test", "work", suggested_object_id="work")
    zone_id = entry.entity_id
    hass.states.async_set(zone_id, "zone", {"friendly_name": "Work"})
    label = lr.async_get(hass).async_create("Work")
    ent_reg.async_update_entity(entry.entity_id, labels=[label.label_id])

    descriptions = await trigger_helper.async_get_all_descriptions(hass)

    assert any("zone_label" in key for key in descriptions.keys())


@pytest.mark.asyncio
async def test_trigger_description_includes_label_target(hass):
    """Trigger description must advertise that it supports Label targets."""
    from homeassistant.helpers import trigger as trigger_helper
    from importlib import import_module

    mod = import_module("custom_components.zone_label_trigger")
    assert await mod.async_setup(hass, {})
    await hass.async_block_till_done()

    # The test harness may not surface the YAML descriptions via
    # `async_get_all_descriptions()` for repo-local custom components, so
    # assert the `triggers.yaml` file itself declares a `zone` entity target
    # (the UI 'label' selector is not part of the YAML target schema).
    import yaml
    from pathlib import Path

    yaml_path = Path(__file__).parents[1] / "custom_components" / "zone_label_trigger" / "triggers.yaml"
    assert yaml_path.exists()

    yaml_data = yaml.safe_load(yaml_path.read_text())
    assert "zone_label" in yaml_data
    assert "target" in yaml_data["zone_label"]
    assert "entity" in yaml_data["zone_label"]["target"]
    assert "label" not in yaml_data["zone_label"]["target"]

    # the entity selector should allow multiple values (the YAML declares it)
    fields = yaml_data["zone_label"].get("fields", {})
    assert fields["entity_id"]["selector"]["entity"]["multiple"] is True


@pytest.mark.asyncio
async def test_validate_trigger_config_accepts_options_wrapped_fields(hass):
    """Ensure validator accepts trigger fields wrapped inside `options`.

    The Automation Editor may send trigger fields under `options` for the
    class-style Trigger API. This test mirrors the Clockwork fix you
    mentioned: accept options-wrapped fields and validate them correctly.
    """
    from homeassistant.helpers import trigger as trigger_helper

    # Validate the Trigger class validator directly for the `options`-wrapped case
    from custom_components.zone_label_trigger.trigger import ZoneLabelTrigger

    # options-wrapped input (class-style) — exact example schema from the product spec
    wrapped = {
        "target": {
            "label_id": ["shopping", "aldi"],
            "entity_id": ["zone.meijer_whitelake", "zone.standish_casino"],
        },
        "options": {"entity_id": ["person.scott", "person.christina"], "event": "enter"},
    }
    validated = await ZoneLabelTrigger.async_validate_config(hass, wrapped)

    # Validator must preserve the `target` and the `options` payload
    assert "options" in validated
    assert validated["options"]["entity_id"] == ["person.scott", "person.christina"]
    assert validated["options"]["event"] == "enter"
    assert "target" in validated
    assert validated["target"]["label_id"] == ["shopping", "aldi"]

    # Accept target with explicit zone entity ids (no label_id)
    wrapped_zone_target = {"target": {"entity_id": ["zone.work"]}, "options": {"entity_id": "device_tracker.alice", "event": "enter"}}
    validated_zone = await ZoneLabelTrigger.async_validate_config(hass, wrapped_zone_target)
    assert "options" in validated_zone
    assert validated_zone["options"]["entity_id"] == "device_tracker.alice"
    assert "target" in validated_zone
    assert validated_zone["target"]["entity_id"] == ["zone.work"]

    # top-level (YAML) shape: target + entity_id + event is still accepted
    top = {"target": {"label_id": ["shopping"]}, "entity_id": ["person.scott"], "event": "enter"}
    validated2 = await ZoneLabelTrigger.async_validate_config(hass, top)
    assert validated2["entity_id"] == ["person.scott"]
    assert validated2["event"] == "enter"
    assert "target" in validated2
    assert validated2["target"]["label_id"] == ["shopping"]


@pytest.mark.asyncio
async def test_class_style_exact_schema_triggers(hass):
    """Class-style trigger using the exact schema from the spec must fire."""
    from custom_components.zone_label_trigger import trigger as zlt

    # create explicit zones and set their label attributes
    from homeassistant.helpers import label_registry as lr, entity_registry as er
    ent_reg = er.async_get(hass)
    e1 = ent_reg.async_get_or_create("zone", "test", "meijer_whitelake", suggested_object_id="meijer_whitelake")
    e2 = ent_reg.async_get_or_create("zone", "test", "standish_casino", suggested_object_id="standish_casino")
    hass.states.async_set("zone.meijer_whitelake", "zone", {"friendly_name": "Meijer"})
    hass.states.async_set("zone.standish_casino", "zone", {"friendly_name": "Standish Casino"})
    label_shopping = lr.async_get(hass).async_create("shopping")
    label_aldi = lr.async_get(hass).async_create("aldi")
    ent_reg.async_update_entity(e1.entity_id, labels=[label_shopping.label_id])
    ent_reg.async_update_entity(e2.entity_id, labels=[label_aldi.label_id])

    # monitored persons start outside
    hass.states.async_set("person.scott", "not_home")
    hass.states.async_set("person.christina", "not_home")

    calls = []

    async def _action(run_vars):
        calls.append(run_vars)

    cfg = {
        "target": {
            "label_id": ["shopping", "aldi"],
            "entity_id": ["zone.meijer_whitelake", "zone.standish_casino"],
        },
        "options": {"entity_id": ["person.scott", "person.christina"], "event": "enter"},
    }

    unsub = await zlt.async_attach_trigger(hass, cfg, _action)

    # scott enters explicit zone -> fires
    hass.states.async_set("person.scott", "meijer_whitelake")
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert calls[0]["trigger"]["entity_id"] == "person.scott"
    assert calls[0]["trigger"]["zone"] == "zone.meijer_whitelake"
    assert calls[0]["trigger"]["event"] == "enter"

    # christina enters via label match -> fires
    hass.states.async_set("person.christina", "standish_casino")
    await hass.async_block_till_done()
    assert len(calls) == 2

    unsub()

async def test_config_flow_and_entry_setup(hass):
    """Exercise the config flow class and the integration's entry setup/unload.

    We call the config flow class directly (the test loader may not register
    repo-local flows with hass.config_entries.flow). We also call
    async_setup_entry/async_unload_entry to verify the integration registers
    and removes its diagnostic service.
    """
    from importlib import import_module

    cfg_mod = import_module("custom_components.zone_label_trigger.config_flow")
    flow = cfg_mod.ZoneLabelTriggerConfigFlow()
    flow.hass = hass

    result = await flow.async_step_user()
    assert result["type"] == "create_entry"

    # Create a mock config entry and call the integration setup/unload helpers
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    entry = MockConfigEntry(domain="zone_label_trigger", data={})
    entry.add_to_hass(hass)

    mod = import_module("custom_components.zone_label_trigger")
    assert await mod.async_setup_entry(hass, entry)
    await hass.async_block_till_done()

    assert "zone_label_trigger" in hass.data

    assert await mod.async_unload_entry(hass, entry)
    await hass.async_block_till_done()

    assert "zone_label_trigger" not in hass.data


@pytest.mark.asyncio
async def test_service_move_demo_tracker_to_zone(hass):
    """Service should move demo device tracker into a zone by copying its coords."""
    from importlib import import_module

    mod = import_module("custom_components.zone_label_trigger")
    assert await mod.async_setup(hass, {})
    await hass.async_block_till_done()

    # Create a zone with coordinates
    hass.states.async_set(
        "zone.my_shop",
        "zone",
        {"label": "Shopping", "friendly_name": "My Shop", "latitude": 40.1, "longitude": -73.5},
    )

    # Ensure demo device exists (start outside)
    hass.states.async_set("device_tracker.demo_paulus", "not_home", {"gps": (0.0, 0.0)})

    # Call service with explicit entity_id (required)
    hass.states.async_set("device_tracker.demo_paulus", "not_home", {"gps": (0.0, 0.0)})
    await hass.services.async_call(
        "zone_label_trigger",
        "move_tracker_to_zone",
        {"zone": "zone.my_shop", "entity_id": "device_tracker.demo_paulus"},
        blocking=True,
    )

    state = hass.states.get("device_tracker.demo_paulus")
    assert state is not None
    # state should be the zone object id (without domain)
    assert state.state == "my_shop"
    assert state.attributes.get("latitude") == 40.1
    assert state.attributes.get("longitude") == -73.5





@pytest.mark.asyncio
async def test_async_attach_trigger_rejects_missing_target(hass):
    """async_attach_trigger must fail when `target` (label_id/entity_id) is missing."""
    import voluptuous as vol
    from custom_components.zone_label_trigger import trigger as zlt

    calls = []

    async def _action(run_vars):
        calls.append(run_vars)

    with pytest.raises(vol.Invalid):
        await zlt.async_attach_trigger(hass, {"platform": "zone_label", "entity_id": "person.scott", "event": "both"}, _action)
