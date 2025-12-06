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
from homeassistant.core import callback

DOMAIN = "tempo"


class TempoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow pour Tempo."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Étape initiale de configuration."""
        if user_input is not None:
            return self.async_create_entry(title="EDF Tempo", data={})

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            description_placeholders={
                "description": "Cette intégration récupère les couleurs Tempo depuis l'API RTE et crée une entité unique avec tous les états."
            },
        )
