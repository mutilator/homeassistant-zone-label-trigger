"""Custom automation trigger: zone_label.

Configuration schema (automation trigger):

  platform: zone_label
  target:
    label_id: <label-to-match-on-zones>    # OR
    entity_id: [zone.<name>]                # explicit zone entity ids
  entity_id: <person|device_tracker>      # required (who to watch)
  event: enter|exit|both                   # required

When a state_changed event indicates an entity entered or exited any zone
whose `label` attribute matches the configured `target.label_id`, or when
an explicit zone entity in `target.entity_id` matches, the trigger fires.
The action will be called with the `trigger` dict containing at least:

  - platform: 'zone_label'
  - event: 'enter' | 'exit'
  - entity_id: <entity id that entered/exited>
  - zone: <zone entity_id matched>
  - from_state: previous state object
  - to_state: new state object

This module is intentionally conservative when matching zone membership:
it compares the entity's state value against several zone identifiers
(zone entity_id, zone object id, and friendly_name) to handle common
representations used by different integrations.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Iterable, List, Set

import voluptuous as vol

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.const import EVENT_STATE_CHANGED, CONF_ENTITY_ID, CONF_TARGET, CONF_OPTIONS
from homeassistant.helpers import entity_registry as er

# Trigger class/types used for the newer class-style trigger API
from homeassistant.helpers.trigger import (
    Trigger,
    TriggerConfig,
    TriggerActionRunner,
    CALLBACK_TYPE,
)
from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)

# Log module import (helps diagnose whether Home Assistant imports this file)
_LOGGER.debug("zone_label_trigger.trigger module imported")

TRIGGER_SCHEMA = vol.Schema(
    {
        vol.Required("platform"): cv.string,
        vol.Required(CONF_TARGET): cv.TARGET_FIELDS,
        vol.Required(CONF_ENTITY_ID): vol.Any(cv.entity_id, [cv.entity_id]),
        vol.Required("event"): vol.In(["enter", "exit", "both"]),
    }
)

# Schema for the inner `options` dict (used when the frontend sends a
# class-style trigger where fields are wrapped under `options`). This is
# the same as TRIGGER_SCHEMA without the required `platform` key — note
# that the label is now supplied via the trigger `target` (no top-level
# `label` in the schema for this new integration).
OPTIONS_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ENTITY_ID): vol.Any(cv.entity_id, [cv.entity_id]),
        vol.Optional(CONF_TARGET): cv.TARGET_FIELDS,
        vol.Required("event"): vol.In(["enter", "exit", "both"]),
    }
)


class ZoneLabelTrigger(Trigger):
    """Trigger class adapter for the `zone_label` trigger.

    This adapter allows the integration to support the newer Trigger class
    API while delegating actual work to the legacy `async_attach_trigger`
    implementation and `TRIGGER_SCHEMA` validation already present in this
    module.
    """

    @classmethod
    async def async_validate_config(cls, hass: HomeAssistant, config: ConfigType) -> ConfigType:
        """Validate config for class-style (`options`-wrapped) and top-level.

        New integration: `label` is provided via `target.label_id` only. We
        require the trigger `target` to include `label_id` and the options
        or top-level dict to include `entity_id` and `event`.
        """
        # class-style: expect `options` plus a `target` containing label_id
        if CONF_OPTIONS in config and isinstance(config[CONF_OPTIONS], dict):
            validated_options = OPTIONS_SCHEMA(config[CONF_OPTIONS])
            # ensure target includes either a label selector or explicit zone entity ids
            if (
                CONF_TARGET not in config
                or not isinstance(config[CONF_TARGET], dict)
                or (
                    "label_id" not in config[CONF_TARGET]
                    and "entity_id" not in config[CONF_TARGET]
                )
            ):
                raise vol.Invalid("`target` must include either `label_id` or `entity_id`")
            # IMPORTANT: return both `options` and `target` so the helper that
            # reconstructs the full trigger config preserves the `target` key
            return {CONF_OPTIONS: validated_options, CONF_TARGET: config[CONF_TARGET]}

        # top-level shape: validate required fields (target must include label_id or entity_id)
        validated = OPTIONS_SCHEMA(config)
        if (
            CONF_TARGET not in config
            or not isinstance(config[CONF_TARGET], dict)
            or (
                "label_id" not in config[CONF_TARGET]
                and "entity_id" not in config[CONF_TARGET]
            )
        ):
            raise vol.Invalid("`target` must include either `label_id` or `entity_id`")
        # Preserve the `target` in the returned config so TriggerConfig.target is set
        return {**validated, CONF_TARGET: config[CONF_TARGET]}

    def __init__(self, hass: HomeAssistant, config: TriggerConfig) -> None:
        super().__init__(hass, config)
        self._conf = config

    async def async_attach_runner(self, run_action: TriggerActionRunner) -> CALLBACK_TYPE:
        # Debug: show incoming TriggerConfig so we can see whether `target` was
        # set by the automation helper (it must be present for label matching).
        _LOGGER.debug(
            "ZoneLabelTrigger.async_attach_runner called: key=%s target=%s options=%s",
            self._conf.key,
            self._conf.target,
            self._conf.options,
        )

        # Reconstruct a raw trigger config dict (as expected by the legacy
        # `async_attach_trigger`) from the TriggerConfig wrapper.
        raw_conf: dict = {"platform": self._conf.key}
        if self._conf.options:
            raw_conf.update(self._conf.options)
        if self._conf.target:
            raw_conf[CONF_TARGET] = self._conf.target

        # Adapter action that converts the legacy `action(run_vars)` call to
        # the newer `run_action(extra_trigger_payload, description)` format.
        def _legacy_action(run_vars):
            # run_action expects (extra_trigger_payload, description, context=None)
            return run_action(run_vars.get("trigger"), self._conf.key)

        # Delegate to existing async_attach_trigger which sets up the bus
        # listener and returns an unsubscribe callable.
        return await async_attach_trigger(self._hass, raw_conf, _legacy_action)


async def async_get_triggers(hass: HomeAssistant) -> dict[str, type[Trigger]]:
    """Return available trigger keys and their Trigger classes.

    New-style API: return a mapping from trigger key to a Trigger subclass.
    The Automation helper will use these classes when initializing and
    validating triggers.
    """
    _LOGGER.debug("zone_label_trigger.async_get_triggers called (class-style)")
    return {"zone_label": ZoneLabelTrigger}


async def async_get_trigger_capabilities(hass: HomeAssistant, config: dict) -> dict:
    """Return trigger capabilities for the UI editor.

    The Automation Editor calls this to obtain field/selector metadata so the
    trigger can be edited entirely in the UI. We mirror the selectors defined
    in `triggers.yaml`/`strings.json` so the frontend can render the label
    picker and the event select control.
    """
    _LOGGER.debug("zone_label_trigger.async_get_trigger_capabilities called; config=%s", config)

    return {
        "extra_fields": {
            "entity_id": {
                "name": "Entity to watch",
                "required": True,
                "selector": {"entity": {"domain": ["person", "device_tracker"]}},
            },
            "event": {
                "name": "Event",
                "required": True,
                "selector": {
                    "select": {
                        "options": [
                            {"value": "enter", "label": "Enter"},
                            {"value": "exit", "label": "Exit"},
                            {"value": "both", "label": "Both"},
                        ]
                    }
                },
            },
        }
    }

def _zone_identifiers(zone_state) -> Set[str]:
    """Return a set of string identifiers for a zone state object.

    Includes the entity_id (e.g. 'zone.home'), the object_id part (e.g. 'home'),
    and the friendly_name attribute if present.
    """
    ids: Set[str] = set()
    entity_id = getattr(zone_state, "entity_id", None)
    if entity_id:
        ids.add(entity_id)
        # also add object id without domain
        if "." in entity_id:
            ids.add(entity_id.split(".", 1)[1])
    fn = (zone_state.attributes or {}).get("friendly_name")
    if fn:
        ids.add(str(fn))
    # also include lower-cased versions for loose matching
    lc = {s.lower() for s in ids}
    ids.update(lc)
    return ids


def _get_matching_zone_entity_ids(hass: HomeAssistant, label: str) -> List[str]:
    """Return list of zone entity_ids whose Entity Registry entry has the label.

    The editor/target selector provides a `label_id` that maps to labels stored
    in the Label/Entity registries — labels are not a State attribute. Match
    case-insensitively on the provided label_id and return any `zone.*`
    entities that have that label attached in the entity registry.
    """
    lc_label = label.lower()
    matches: List[str] = []

    ent_reg = er.async_get(hass)

    # Find registry entries that reference this label_id and keep only zones
    for entry in ent_reg.entities.get_entries_for_label(label):
        if entry.entity_id.startswith("zone."):
            matches.append(entry.entity_id)

    if not matches:
        # Debug: show available labels for zone entities from the registry so
        # it's obvious where labels are stored at runtime (helps troubleshooting).
        available: dict[str, list[str] | None] = {}
        for state in hass.states.async_all("zone"):
            reg_entry = ent_reg.async_get(state.entity_id)
            available[state.entity_id] = list(reg_entry.labels) if reg_entry and reg_entry.labels else None
        _LOGGER.debug(
            "zone_label: no zones matched label=%s; available zone registry labels=%s",
            lc_label,
            available,
        )

    return matches


async def async_attach_trigger(hass: HomeAssistant, config, action: Callable, vars=None):
    """Attach a trigger based on zones labeled with a given label.

    This function accepts the schema you specified (label(s) under the
    trigger `target`, optional zone entity_id targets, and monitored
    `options.entity_id` for person/device entities). Examples supported:

      - legacy: {"label": "Work", "entity_id": "device_tracker.alice"}
      - class-style: {"target": {"label_id": ["shopping"]}, "options": {"entity_id": ["person.scott"], "event": "enter"}}

    Behavior:
    - `target.label_id` selects which zones to match.
    - `target.entity_id` may include explicit zone entity_ids.
    - `options.entity_id` (or top-level `entity_id`) lists the person/device entities to monitor; **both `entity_id` and `event` are required**.
    """
    # --- normalize label(s) ---
    # Debug: dump the incoming `config` so we can see exactly what the
    # automation helper / Trigger adapter is passing into this function.
    _LOGGER.debug(
        "async_attach_trigger received config (type=%s) keys=%s target=%s config=%s",
        type(config),
        list(config.keys()) if isinstance(config, dict) else None,
        (config.get(CONF_TARGET) if isinstance(config, dict) else None),
        config,
    )
    

    # Label(s) MUST be supplied via the trigger `target` (target.label_id).
    labels: list[str] = []
    if isinstance(config, dict) and CONF_TARGET in config and isinstance(config[CONF_TARGET], dict):
        targ = config[CONF_TARGET]
        if "label_id" in targ:
            v = targ["label_id"]
            labels = v if isinstance(v, list) else [v]

    # `labels` may be empty when the caller supplied explicit zone entity ids
    # in the target (handled below). Validation of the target shape is
    # performed in `async_validate_config` so we don't raise here.

    # --- normalize event (required) ---
    event_type = None
    if isinstance(config, dict) and "event" in config:
        event_type = config["event"]
    elif isinstance(config, dict) and CONF_OPTIONS in config and isinstance(config[CONF_OPTIONS], dict) and "event" in config[CONF_OPTIONS]:
        event_type = config[CONF_OPTIONS]["event"]
    else:
        raise vol.Invalid("`event` is required for zone_label trigger")

    # --- determine which entities to watch (options.entity_id preferred; required) ---
    if isinstance(config, dict) and CONF_OPTIONS in config and isinstance(config[CONF_OPTIONS], dict) and "entity_id" in config[CONF_OPTIONS]:
        vals = config[CONF_OPTIONS]["entity_id"]
        allowed_entities = set(vals if isinstance(vals, list) else [vals])
    elif isinstance(config, dict) and CONF_ENTITY_ID in config:
        vals = config[CONF_ENTITY_ID]
        allowed_entities = set(vals if isinstance(vals, list) else [vals])
    else:
        raise vol.Invalid("`entity_id` is required for zone_label trigger")

    # --- build matching zone entity ids from target labels + explicit zones ---
    matching_zone_entity_ids: Set[str] = set()
    if isinstance(config, dict) and CONF_TARGET in config and isinstance(config[CONF_TARGET], dict):
        targ = config[CONF_TARGET]
        # include explicit zone entity_ids listed in the target (must be `entity_id`)
        if "entity_id" in targ:
            vals = targ["entity_id"]
            if isinstance(vals, str):
                vals = [vals]
            for ent in vals:
                if isinstance(ent, str) and ent.startswith("zone."):
                    matching_zone_entity_ids.add(ent)

    # Resolve zones by label(s)
    for lab in labels:
        matching_zone_entity_ids.update(_get_matching_zone_entity_ids(hass, lab))

    # Keep as list for iteration order
    matching_zone_entity_ids_list = list(matching_zone_entity_ids)

    # If neither a label nor explicit zone entity_ids were provided in the
    # trigger's `target`, the trigger cannot decide which zones to match —
    # treat this as a configuration error and fail early.
    if not labels and not matching_zone_entity_ids_list:
        _LOGGER.error(
            "zone_label trigger misconfigured: target must include `label_id` or `entity_id` (zone.*); config=%s",
            config,
        )
        raise vol.Invalid("`target` must include `label_id` or `entity_id` (zone.*)")

    target_conf = config.get(CONF_TARGET) if isinstance(config, dict) else None
    _LOGGER.debug(
        "async_attach_trigger called for zone_label (labels=%s, event=%s, target=%s, allowed_entities=%s, config=%s)",
        labels,
        event_type,
        target_conf,
        allowed_entities,
        config,
    )

    @callback
    def _state_changed_listener(event):
        
        data = event.data
        entity_id = data.get("entity_id")
        old_state = data.get("old_state")
        new_state = data.get("new_state")

        # If a monitored-entity filter was set on attach, ignore other entities
        if allowed_entities is not None and entity_id not in allowed_entities:
            return

        # Dump raw event and payload so we can inspect which attributes are
        # present (helps debug why label/zone matching may be empty).
        try:
            _LOGGER.debug("zone_label raw event object: %s", event)
            _LOGGER.debug("zone_label raw event.data keys: %s", list(getattr(event, "data", {}).keys()))
        except Exception:  # pragma: no cover - defensive
            _LOGGER.debug("zone_label failed to stringify event", exc_info=True)

        

        # Log state + attributes for easier inspection
        _LOGGER.debug(
            "zone_label event payload — entity=%s old_state=%s new_state=%s old_attrs=%s new_attrs=%s labels=%s",
            entity_id,
            getattr(old_state, "state", None),
            getattr(new_state, "state", None),
            getattr(old_state, "attributes", None),
            getattr(new_state, "attributes", None),
            labels,
        )

        # Only consider person/device entities when no explicit allowed_entities
        # filter is set (helps avoid handling irrelevant domain events).
        if allowed_entities is None:
            if "." in (entity_id or ""):
                domain = entity_id.split(".", 1)[0]
                if domain not in ("person", "device_tracker"):
                    return

        # We only care when a state's textual representation changes
        if old_state is None and new_state is None:
            return

        # Re-resolve matching zones on each event so newly-created/updated
        # zones with matching labels are respected without reload.
        # Build a *unique* list of matching zones (avoid firing the same
        # automation multiple times when a zone appears both in the label
        # lookup and as an explicit entity in the target).
        seen: set[str] = set()
        current_matching_zones: List[str] = []
        for lab in labels:
            for z in _get_matching_zone_entity_ids(hass, lab):
                if z not in seen:
                    seen.add(z)
                    current_matching_zones.append(z)
        # also include any explicit zones supplied in the target
        for z in matching_zone_entity_ids_list:
            if z not in seen:
                seen.add(z)
                current_matching_zones.append(z)

        # Debug: show which zones we're going to evaluate for this event
        _LOGGER.debug(
            "zone_label resolved matching zones=%s (label_match=%s explicit=%s)",
            current_matching_zones,
            labels,
            matching_zone_entity_ids_list,
        )

        if not current_matching_zones:
            return

        # For each matching zone, collect its identifiers and test membership
        for zone_entity_id in current_matching_zones:
            zone_state = hass.states.get(zone_entity_id)
            if zone_state is None:
                continue
            zone_ids = _zone_identifiers(zone_state)

            def _is_in_zone(state_obj):
                if state_obj is None:
                    return False
                s = state_obj.state
                if s is None:
                    return False
                return s in zone_ids or str(s).lower() in zone_ids

            entered = (not _is_in_zone(old_state)) and _is_in_zone(new_state)
            exited = _is_in_zone(old_state) and (not _is_in_zone(new_state))

            matched = False
            fired_event = None
            if event_type in ("enter", "both") and entered:
                matched = True
                fired_event = "enter"
            if event_type in ("exit", "both") and exited:
                matched = True
                fired_event = "exit"

            if not matched:
                continue

            trigger_data = {
                "platform": "zone_label",
                "event": fired_event,
                "entity_id": entity_id,
                "zone": zone_entity_id,
                "from_state": old_state,
                "to_state": new_state,
            }

            # Call the action. action may be sync or async; handle both.
            try:
                task = action({"trigger": trigger_data})
                if asyncio.iscoroutine(task):
                    hass.async_create_task(task)
            except Exception:  # pragma: no cover - defensive
                _LOGGER.exception("Error running action for zone_label trigger")

    unsub = hass.bus.async_listen(EVENT_STATE_CHANGED, _state_changed_listener)

    return unsub
