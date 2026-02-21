"""Config flow for Zone Label Trigger (minimal, creates a dummy entry).

This allows the integration to appear under Settings → Integrations so users
can add it from the UI. The integration doesn't require any user input, so
we create an empty config entry.
"""
from __future__ import annotations

from homeassistant import config_entries

DOMAIN = "zone_label_trigger"


class ZoneLabelTriggerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Zone Label Trigger."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step (user initiated).

        We don't need any configuration; create a dummy entry so the integration
        appears in the Integrations UI and `async_setup_entry` will be called.
        """
        return self.async_create_entry(title="Zone Label Trigger", data={})
