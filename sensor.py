"""
Integration Home Assistant pour EDF Tempo
Une seule entité sensor avec tous les états et attributs
Version robuste avec gestion des données instables
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
            update_interval=None,  # Pas de mise à jour automatique, uniquement programmée
        )
        self.tempo_data = {}
        self._cached_data = {}  # Cache pour garder les dernières données valides
        self._last_period = None
        self._last_api_call = None
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
        """Retourne le code couleur pour une date donnée (avec cache)."""
        # Essaie d'abord les données actuelles
        color = self.tempo_data.get(date, "")
        if color and color in COLORS:
            return COLORS[color]["code"]
        
        # Sinon, utilise le cache
        color = self._cached_data.get(date, "")
        if color and color in COLORS:
            _LOGGER.debug(f"Utilisation du cache pour {date}: {color}")
            return COLORS[color]["code"]
        
        return 0

    def get_color_name(self, date: str) -> str:
        """Retourne le nom de la couleur pour une date donnée (avec cache)."""
        color = self.tempo_data.get(date, "")
        if color and color in COLORS:
            return COLORS[color]["name"]
        
        # Utilise le cache si disponible
        color = self._cached_data.get(date, "")
        if color and color in COLORS:
            return COLORS[color]["name"]
        
        return "Inconnu"

    def get_color_name_en(self, date: str) -> str:
        """Retourne le nom anglais de la couleur pour une date donnée (avec cache)."""
        color = self.tempo_data.get(date, "")
        if color and color in COLORS:
            return COLORS[color]["name_en"]
        
        color = self._cached_data.get(date, "")
        if color and color in COLORS:
            return COLORS[color]["name_en"]
        
        return "unknown"

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
        
        # Force la mise à jour des entités (sans appel API)
        self.async_set_updated_data(self.tempo_data)

    async def _trigger_api_refresh(self, _now=None):
        """Récupération API à 7h pour couleur J+1."""
        now = dt_util.now().astimezone(dt_util.get_time_zone("Europe/Paris"))
        today_date = now.strftime("%Y-%m-%d")
        
        # Évite les appels multiples le même jour
        if self._last_api_call == today_date and self._data_fetched_today:
            _LOGGER.info("Données J+1 déjà récupérées aujourd'hui, skip")
            return
        
        _LOGGER.info("7h - Récupération API pour couleur J+1")
        self._last_api_call = today_date
        await self.async_refresh()

    async def _trigger_api_retry(self, _now=None):
        """Retry à 8h si échec à 7h."""
        if not self._data_fetched_today:
            _LOGGER.info("8h - Retry récupération API (échec à 7h)")
            await self.async_refresh()

    def _validate_and_cache_data(self, new_data: dict) -> bool:
        """Valide les nouvelles données et met à jour le cache si valides."""
        if not new_data:
            _LOGGER.warning("Données vides reçues de l'API")
            return False
        
        today = self.get_tempo_date(0)
        tomorrow = self.get_tempo_date(1)
        
        # Vérifie que les données essentielles sont présentes
        today_color = new_data.get(today)
        tomorrow_color = new_data.get(tomorrow)
        
        if not today_color or today_color not in COLORS:
            _LOGGER.warning(f"Couleur invalide pour J ({today}): {today_color}")
            return False
        
        # J+1 peut ne pas encore être disponible (avant 7h)
        if tomorrow_color and tomorrow_color not in COLORS:
            _LOGGER.warning(f"Couleur invalide pour J+1 ({tomorrow}): {tomorrow_color}")
        
        # Mise à jour du cache avec les données valides
        for date, color in new_data.items():
            if color in COLORS:
                self._cached_data[date] = color
        
        _LOGGER.info(f"Cache mis à jour - J: {today_color}, J+1: {tomorrow_color if tomorrow_color else 'N/A'}")
        return True

    async def _async_update_data(self):
        """Récupération des données depuis l'API RTE."""
        season = self.get_current_season()
        url = f"{API_URL}?season={season}"
        
        try:
            # Créer un contexte SSL qui ignore la vérification du certificat
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE
            
            connector = aiohttp.TCPConnector(ssl=ssl_context)
            
            async with async_timeout.timeout(15):
                async with aiohttp.ClientSession(connector=connector) as session:
                    async with session.get(url) as response:
                        if response.status != 200:
                            _LOGGER.error(f"Erreur API HTTP {response.status}")
                            # En cas d'erreur, on garde les données du cache
                            return self._cached_data
                        
                        data = await response.json()
                        new_data = data.get("values", {})
                        
                        # Valide et met en cache les données
                        if self._validate_and_cache_data(new_data):
                            self.tempo_data = new_data
                            self._data_fetched_today = True
                            
                            today = self.get_tempo_date(0)
                            tomorrow = self.get_tempo_date(1)
                            
                            _LOGGER.info(
                                "✓ Données Tempo récupérées: J=%s (%s), J+1=%s (%s)",
                                self.get_color_name(today),
                                self.get_color_code(today),
                                self.get_color_name(tomorrow),
                                self.get_color_code(tomorrow)
                            )
                        else:
                            _LOGGER.warning("Données invalides, conservation du cache")
                            # On garde les données du cache
                            return self._cached_data
                        
                        return self.tempo_data
                        
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout lors de la récupération des données API")
            return self._cached_data
        except aiohttp.ClientError as err:
            _LOGGER.error(f"Erreur de connexion API: {err}")
            return self._cached_data
        except Exception as err:
            _LOGGER.error(f"Erreur inattendue: {err}", exc_info=True)
            return self._cached_data


class TempoSensor(CoordinatorEntity, SensorEntity):
    """Sensor principal représentant l'état Tempo."""

    def __init__(self, coordinator: TempoDataCoordinator) -> None:
        """Initialisation du sensor."""
        super().__init__(coordinator)
        
        self._attr_unique_id = "tempo_edf"
        self._attr_name = "EDF Tempo"
        self._attr_icon = "mdi:flash"
        self._attr_has_entity_name = True
        self._last_state = None

    @property
    def available(self) -> bool:
        """Le sensor est disponible si on a au moins des données en cache."""
        today = self.coordinator.get_tempo_date(0)
        return self.coordinator.get_color_code(today) != 0

    @property
    def native_value(self) -> str:
        """Retourne l'état actuel (couleur du jour actuel)."""
        today = self.coordinator.get_tempo_date(0)
        color_name = self.coordinator.get_color_name(today)
        period = self.coordinator.get_period()
        
        new_state = f"{color_name} {period}"
        
        # Log uniquement si l'état change réellement
        if new_state != self._last_state and self._last_state is not None:
            _LOGGER.info(f"Changement d'état: {self._last_state} → {new_state}")
        
        self._last_state = new_state
        return new_state

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
            
            # Combinaisons pratiques pour automatisations J (dépendent de l'heure actuelle)
            "today_red_hp": today_color_code == 3 and not is_hc,
            "today_red_hc": today_color_code == 3 and is_hc,
            "today_white_hp": today_color_code == 2 and not is_hc,
            "today_white_hc": today_color_code == 2 and is_hc,
            "today_blue_hp": today_color_code == 1 and not is_hc,
            "today_blue_hc": today_color_code == 1 and is_hc,
            
            # Saison
            "season": self.coordinator.get_current_season(),
            
            # Info système
            "data_source": "cache" if today not in self.coordinator.tempo_data else "api",
        }