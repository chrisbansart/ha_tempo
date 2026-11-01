"""
Config flow for EDF Tempo integration
Copyright (C) 2025 Christophe Bansart

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""
import voluptuous as vol
from homeassistant import config_entries

DOMAIN = "tempo"


class TempoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow pour Tempo."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Étape initiale de configuration."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")

        if user_input is not None:
            return self.async_create_entry(title="EDF Tempo", data={})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
        )