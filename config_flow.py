"""Config flow pour l'intégration Tempo."""
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
