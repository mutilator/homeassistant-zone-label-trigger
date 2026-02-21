"""Zone Label Trigger integration.

Provides a custom automation trigger that watches for enter/exit events
for zones filtered by a `label` attribute.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.helpers import config_validation as cv

_LOGGER = logging.getLogger(__name__)

SERVICE_MOVE_DEMO_TO_ZONE = "move_tracker_to_zone"

__all__ = ["async_setup"]


async def async_setup(hass, config: dict[str, Any]) -> bool:
    """Set up the integration.

    Import the trigger module proactively (like `clockwork` imports its
    `condition` module) so that the trigger platform is registered and any
    import errors are surfaced early in logs. Custom integrations that expose
    automation triggers should import the platform module here to aid
    discovery and diagnostics.
    """

    # Try to import the trigger platform to surface errors and ensure the
    # platform module-level registration (if any) runs during setup.
    try:
        from . import trigger as trigger_module  # noqa: F401

        _LOGGER.info(
            "zone_label_trigger: trigger module loaded: async_attach_trigger=%s, TRIGGER_SCHEMA=%s",
            hasattr(trigger_module, "async_attach_trigger"),
            hasattr(trigger_module, "TRIGGER_SCHEMA"),
        )
    except Exception as err:  # pragma: no cover - defensive for runtime
        _LOGGER.exception("Failed importing trigger module for zone_label_trigger: %s", err)

    # Register our trigger key in Home Assistant's trigger registry so the
    # Automation Editor and backend discovery will treat this integration as
    # providing triggers even if no configuration entry exists.
    try:
        from homeassistant.helpers.trigger import TRIGGERS

        hass.data.setdefault(TRIGGERS, {})
        # Register the absolute trigger description key used in our
        # `triggers.yaml` so the Automation Editor can load the UI
        # description for `zone_label` when the integration is present.
        hass.data[TRIGGERS]["zone_label_trigger.zone_label"] = "zone_label_trigger"
        _LOGGER.debug("zone_label_trigger.zone_label registered in hass.data[TRIGGERS]")
    except Exception:  # pragma: no cover - defensive
        _LOGGER.exception("Failed to register trigger in hass.data[TRIGGERS]")

    # Store marker so integration presence is easy to verify in hass.data
    hass.data.setdefault("zone_label_trigger", {})

    # --- register helper service for testing/dev ---
    async def _move_demo_tracker_to_zone(call):
        """Move a demo device_tracker to the GPS coords of a zone.

        Service payload:
          - zone (required): zone entity_id (zone.xxx)
          - entity_id (required): device_tracker entity to set (caller must provide)
        """
        zone_ent = call.data.get("zone")

        # entity_id is required now (no default)
        if "entity_id" not in call.data:
            _LOGGER.warning("%s called without an 'entity_id' argument", SERVICE_MOVE_DEMO_TO_ZONE)
            return
        device_ent = call.data["entity_id"]

        if not zone_ent:
            _LOGGER.warning("%s called without a 'zone' argument", SERVICE_MOVE_DEMO_TO_ZONE)
            return

        zone_state = hass.states.get(zone_ent)
        if zone_state is None:
            _LOGGER.warning("Zone %s not found", zone_ent)
            return

        # Prefer standard attributes; fall back gracefully
        attrs = zone_state.attributes or {}
        lat = attrs.get("latitude") or attrs.get("lat")
        lon = attrs.get("longitude") or attrs.get("lon")

        # Use zone object id (without domain) as the device_tracker state value
        zone_obj = zone_ent.split(".", 1)[1] if "." in zone_ent else zone_ent

        new_attrs = {
            "latitude": lat,
            "longitude": lon,
            "gps": (lat, lon) if lat is not None and lon is not None else None,
            "gps_accuracy": attrs.get("radius", 5),
        }

        hass.states.async_set(device_ent, zone_obj, new_attrs)
        _LOGGER.debug("Moved %s -> %s (gps=%s,%s)", device_ent, zone_ent, lat, lon)

    service_schema = vol.Schema(
        {vol.Required("zone"): cv.entity_id, vol.Required("entity_id"): cv.entity_id}
    )

    hass.services.async_register(
        "zone_label_trigger", SERVICE_MOVE_DEMO_TO_ZONE, _move_demo_tracker_to_zone, schema=service_schema
    )

    return True


async def async_setup_entry(hass, entry) -> bool:
    """Set up the integration from a config entry."""
    return await async_setup(hass, {})


async def async_unload_entry(hass, entry) -> bool:
    """Unload a config entry created for this integration."""
    # Remove hass.data marker
    hass.data.pop("zone_label_trigger", None)

    # Cleanup TRIGGERS registry entry if present
    try:
        from homeassistant.helpers.trigger import TRIGGERS

        if TRIGGERS in hass.data and "zone_label_trigger.zone_label" in hass.data[TRIGGERS]:
            hass.data[TRIGGERS].pop("zone_label_trigger.zone_label", None)
    except Exception:
        pass

    # Remove our debug/dev service if registered
    try:
        hass.services.async_remove("zone_label_trigger", SERVICE_MOVE_DEMO_TO_ZONE)
    except Exception:
        pass

    return True
