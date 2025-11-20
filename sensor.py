"""
Integration Home Assistant pour EDF Tempo
Une seule entité sensor avec tous les états et attributs
"""
import logging
from datetime import datetime, timedelta
import aiohttp
import async_timeout
import ssl
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

DOMAIN = "tempo"
API_URL = "https://www.services-rte.com/cms/open_data/v1/tempo"

COLORS = {
    "BLUE": {"code": 1, "name": "Bleu", "name_en": "blue"},
    "WHITE": {"code": 2, "name": "Blanc", "name_en": "white"},
    "RED": {"code": 3, "name": "Rouge", "name_en": "red"},
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configuration de l'entité depuis une config entry."""
    coordinator = TempoDataCoordinator(hass)
    await coordinator.async_config_entry_first_refresh()

    async_add_entities([TempoSensor(coordinator)])


class TempoDataCoordinator(DataUpdateCoordinator):
    """Coordinateur pour récupérer les données Tempo."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialisation du coordinateur."""
        super().__init__(
            hass,
            _LOGGER,
            name="Tempo",
            update_interval=timedelta(hours=24),  # Mise à jour quotidienne par défaut
        )
        self.tempo_data = {}
        self._last_period = None
        self._last_update_attempt = None
        self._data_fetched_today = False
        self._schedule_updates()

    def get_current_season(self) -> str:
        """Retourne la saison actuelle (ex: 2024-2025)."""
        now = dt_util.now().astimezone(dt_util.get_time_zone("Europe/Paris"))
        year = now.year
        month = now.month
        
        if month >= 9:
            return f"{year}-{year + 1}"
        return f"{year - 1}-{year}"

    def get_tempo_date(self, offset_days: int = 0) -> str:
        """
        Retourne la date Tempo (en tenant compte du décalage 6h).
        offset_days: 0 pour J, 1 pour J+1
        """
        now = dt_util.now().astimezone(dt_util.get_time_zone("Europe/Paris"))
        
        # Si avant 6h du matin, on considère que c'est encore la veille
        if now.hour < 6:
            now = now - timedelta(days=1)
        
        target_date = now + timedelta(days=offset_days)
        return target_date.strftime("%Y-%m-%d")

    def get_color_code(self, date: str) -> int:
        """Retourne le code couleur pour une date donnée."""
        color = self.tempo_data.get(date, "")
        return COLORS.get(color, {}).get("code", 0)

    def get_color_name(self, date: str) -> str:
        """Retourne le nom de la couleur pour une date donnée."""
        color = self.tempo_data.get(date, "")
        return COLORS.get(color, {}).get("name", "Inconnu")

    def get_color_name_en(self, date: str) -> str:
        """Retourne le nom anglais de la couleur pour une date donnée."""
        color = self.tempo_data.get(date, "")
        return COLORS.get(color, {}).get("name_en", "unknown")

    def is_hc_time(self) -> bool:
        """Vérifie si on est en heures creuses (22h-6h)."""
        now = dt_util.now().astimezone(dt_util.get_time_zone("Europe/Paris"))
        hour = now.hour
        return hour >= 22 or hour < 6

    def get_period(self) -> str:
        """Retourne la période actuelle."""
        return "HC" if self.is_hc_time() else "HP"

    def _schedule_updates(self):
        """Programme les mises à jour aux heures clés."""
        from homeassistant.helpers.event import async_track_time_change
        
        # À 6h : passage HP + activation des détecteurs J
        async_track_time_change(
            self.hass,
            self._trigger_period_change,
            hour=6,
            minute=0,
            second=0
        )
        
        # À 7h : récupération API pour couleur J+1
        async_track_time_change(
            self.hass,
            self._trigger_api_refresh,
            hour=7,
            minute=0,
            second=0
        )
        
        # À 8h : retry si échec à 7h
        async_track_time_change(
            self.hass,
            self._trigger_api_retry,
            hour=8,
            minute=0,
            second=0
        )
        
        # À 22h : passage HC
        async_track_time_change(
            self.hass,
            self._trigger_period_change,
            hour=22,
            minute=0,
            second=0
        )
        
        _LOGGER.info("Mises à jour programmées: 6h (J HP), 7h (API J+1), 8h (retry), 22h (J HC)")

    async def _trigger_period_change(self, _now=None):
        """Changement de période HP/HC ou de jour."""
        now = dt_util.now().astimezone(dt_util.get_time_zone("Europe/Paris"))
        current_period = self.get_period()
        
        if now.hour == 6:
            _LOGGER.info("6h - Passage au jour J en mode HP")
            self._data_fetched_today = False  # Reset pour permettre la récupération à 7h
        elif now.hour == 22:
            _LOGGER.info("22h - Passage en heures creuses (HC)")
        
        if self._last_period != current_period:
            self._last_period = current_period
        
        # Force la mise à jour des entités
        self.async_set_updated_data(self.tempo_data)

    async def _trigger_api_refresh(self, _now=None):
        """Récupération API à 7h pour couleur J+1."""
        now = dt_util.now().astimezone(dt_util.get_time_zone("Europe/Paris"))
        today_date = now.strftime("%Y-%m-%d")
        
        # Évite les appels multiples le même jour
        if self._last_update_attempt == today_date and self._data_fetched_today:
            _LOGGER.info("Données J+1 déjà récupérées aujourd'hui, skip")
            return
        
        _LOGGER.info("7h - Récupération API pour couleur J+1")
        self._last_update_attempt = today_date
        await self.async_refresh()

    async def _trigger_api_retry(self, _now=None):
        """Retry à 8h si échec à 7h."""
        if not self._data_fetched_today:
            _LOGGER.info("8h - Retry récupération API (échec à 7h)")
            await self.async_refresh()

    async def _async_update_data(self):
        """Récupération des données depuis l'API RTE."""
        season = self.get_current_season()
        url = f"{API_URL}?season={season}"
        
        current_period = self.get_period()
        period_changed = self._last_period != current_period
        if period_changed:
            self._last_period = current_period
        
        try:
            # Créer un contexte SSL qui ignore la vérification du certificat
            # Note: Ce n'est pas idéal pour la sécurité, mais nécessaire si le certificat RTE a un problème
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            
            async with async_timeout.timeout(10):
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.get(url) as response:
                        if response.status != 200:
                            raise UpdateFailed(f"Erreur API: {response.status}")
                        
                        data = await response.json()
                        self.tempo_data = data.get("values", {})
                        self._data_fetched_today = True
                        
                        today = self.get_tempo_date(0)
                        tomorrow = self.get_tempo_date(1)
                        
                        _LOGGER.info(
                            "Données Tempo mises à jour: J=%s (%s), J+1=%s (%s)%s",
                            self.get_color_name(today),
                            self.get_color_code(today),
                            self.get_color_name(tomorrow),
                            self.get_color_code(tomorrow),
                            f" [Passage {current_period}]" if period_changed else ""
                        )
                        
                        return self.tempo_data
                        
        except Exception as err:
            _LOGGER.error(f"Erreur lors de la mise à jour: {err}")
            raise UpdateFailed(f"Erreur lors de la mise à jour: {err}")


class TempoSensor(CoordinatorEntity, SensorEntity):
    """Sensor principal représentant l'état Tempo."""

    def __init__(self, coordinator: TempoDataCoordinator) -> None:
        """Initialisation du sensor."""
        super().__init__(coordinator)
        
        self._attr_unique_id = "tempo_edf"
        self._attr_name = "EDF Tempo"
        self._attr_icon = "mdi:flash"
        self._attr_has_entity_name = True

    @property
    def native_value(self) -> str:
        """Retourne l'état actuel (couleur du jour actuel)."""
        today = self.coordinator.get_tempo_date(0)
        color_name = self.coordinator.get_color_name(today)
        period = self.coordinator.get_period()
        return f"{color_name} {period}"

    @property
    def extra_state_attributes(self):
        """Attributs détaillés de l'entité."""
        now = dt_util.now().astimezone(dt_util.get_time_zone("Europe/Paris"))
        today = self.coordinator.get_tempo_date(0)
        tomorrow = self.coordinator.get_tempo_date(1)
        
        today_color_code = self.coordinator.get_color_code(today)
        tomorrow_color_code = self.coordinator.get_color_code(tomorrow)
        
        today_color = self.coordinator.get_color_name(today)
        tomorrow_color = self.coordinator.get_color_name(tomorrow)
        
        today_color_en = self.coordinator.get_color_name_en(today)
        tomorrow_color_en = self.coordinator.get_color_name_en(tomorrow)
        
        is_hc = self.coordinator.is_hc_time()
        period = "HC" if is_hc else "HP"
        
        return {
            # État actuel
            "current_hour": now.hour,
            "current_period": period,
            "is_hc": is_hc,
            "is_hp": not is_hc,
            
            # Jour J
            "today_date": today,
            "today_color": today_color,
            "today_color_en": today_color_en,
            "today_color_code": today_color_code,
            "today_is_blue": today_color_code == 1,
            "today_is_white": today_color_code == 2,
            "today_is_red": today_color_code == 3,
            
            # Jour J+1
            "tomorrow_date": tomorrow,
            "tomorrow_color": tomorrow_color,
            "tomorrow_color_en": tomorrow_color_en,
            "tomorrow_color_code": tomorrow_color_code,
            "tomorrow_is_blue": tomorrow_color_code == 1,
            "tomorrow_is_white": tomorrow_color_code == 2,
            "tomorrow_is_red": tomorrow_color_code == 3,
            
            # Combinaisons pratiques pour automatisations J
            "today_red_hp": today_color_code == 3 and not is_hc,
            "today_red_hc": today_color_code == 3 and is_hc,
            "today_white_hp": today_color_code == 2 and not is_hc,
            "today_white_hc": today_color_code == 2 and is_hc,
            "today_blue_hp": today_color_code == 1 and not is_hc,
            "today_blue_hc": today_color_code == 1 and is_hc,
            
            # Combinaisons pratiques pour automatisations J+1
            "tomorrow_red_hp": tomorrow_color_code == 3 and not is_hc,
            "tomorrow_red_hc": tomorrow_color_code == 3 and is_hc,
            "tomorrow_white_hp": tomorrow_color_code == 2 and not is_hc,
            "tomorrow_white_hc": tomorrow_color_code == 2 and is_hc,
            "tomorrow_blue_hp": tomorrow_color_code == 1 and not is_hc,
            "tomorrow_blue_hc": tomorrow_color_code == 1 and is_hc,
            
            # Saison
            "season": self.coordinator.get_current_season(),
        }