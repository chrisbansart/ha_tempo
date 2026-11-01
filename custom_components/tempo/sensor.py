"""
Integration Home Assistant pour EDF Tempo
Une seule entité sensor avec tous les états et attributs
Version robuste avec gestion des données instables

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
import json
import logging
from datetime import datetime, timedelta
import aiohttp
import async_timeout
import asyncio
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
from homeassistant.util.ssl import get_default_no_verify_context

_LOGGER = logging.getLogger(__name__)

DOMAIN = "tempo"
API_URL = "https://www.services-rte.com/cms/open_data/v1/tempoLight"
API_URL_SEASON = "https://www.services-rte.com/cms/open_data/v1/tempo"

COLORS = {
    "BLUE": {"code": 1, "name": "Bleu", "name_en": "blue", "emoji":"🔵"},
    "WHITE": {"code": 2, "name": "Blanc", "name_en": "white","emoji":"⚪"},
    "RED": {"code": 3, "name": "Rouge", "name_en": "red","emoji":"🔴"},
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configuration de l'entité depuis une config entry."""
    coordinator = TempoDataCoordinator(hass)
    await coordinator.async_config_entry_first_refresh()

    async_add_entities([TempoSensor(coordinator, entry)])


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
        
        # Contexte SSL asynchrone recommandé par Home Assistant
        self._ssl_context = get_default_no_verify_context()

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
    
    def get_color_emoji(self, date: str) -> str:
        """Retourne l'emoji de la couleur pour une date donnée (avec cache)."""
        color = self.tempo_data.get(date, "")
        if color and color in COLORS:
            return COLORS[color]["emoji"]
        
        color = self._cached_data.get(date, "")
        if color and color in COLORS:
            return COLORS[color]["emoji"]
        
        return "❓"  # Changez "unknown" par un emoji

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

        # À 7h05 : récupération API pour couleur J+1 (décalé de 5min pour éviter la congestion)
        async_track_time_change(
            self.hass,
            self._trigger_api_refresh,
            hour=7,
            minute=5,
            second=0
        )

        # Retries à 9h05, 11h05, 13h05 si données non récupérées
        for retry_hour in [9, 11, 13]:
            async_track_time_change(
                self.hass,
                self._trigger_api_retry,
                hour=retry_hour,
                minute=5,
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

        _LOGGER.info("Mises à jour programmées: 6h (J HP), 7h05 (API J+1), 9h05/11h05/13h05 (retries), 22h (J HC)")

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
        
        _LOGGER.info("7h05 - Récupération API pour couleur J+1")
        self._last_api_call = today_date
        await self.async_refresh()

    async def _trigger_api_retry(self, _now=None):
        """Retry aux heures programmées si données non récupérées."""
        now = dt_util.now().astimezone(dt_util.get_time_zone("Europe/Paris"))
        current_hour = now.hour

        if not self._data_fetched_today:
            _LOGGER.info(f"{current_hour}h - Retry récupération API (données non récupérées)")
            await self.async_refresh()
        else:
            _LOGGER.debug(f"{current_hour}h - Retry ignoré, données déjà récupérées")

    def _validate_and_cache_data(self, new_data: dict) -> bool:
        """Valide les nouvelles données et met à jour le cache si valides."""
        if not new_data:
            _LOGGER.warning("[Validation] Données vides reçues de l'API (dict vide ou None)")
            return False

        today = self.get_tempo_date(0)
        tomorrow = self.get_tempo_date(1)

        _LOGGER.debug(f"[Validation] Date J calculée: {today}, Date J+1: {tomorrow}")
        _LOGGER.debug(f"[Validation] Nombre total d'entrées reçues: {len(new_data)}")

        # Vérifie que les données essentielles sont présentes
        today_color = new_data.get(today)
        tomorrow_color = new_data.get(tomorrow)

        _LOGGER.debug(f"[Validation] Couleur J ({today}): {today_color}")
        _LOGGER.debug(f"[Validation] Couleur J+1 ({tomorrow}): {tomorrow_color}")

        if not today_color:
            _LOGGER.warning(f"[Validation] Date J ({today}) absente des données API")
            _LOGGER.debug(f"[Validation] Dates disponibles (dernières 10): {sorted(new_data.keys())[-10:]}")
            return False

        if today_color not in COLORS:
            _LOGGER.warning(f"[Validation] Couleur J invalide: '{today_color}' (attendu: {list(COLORS.keys())})")
            return False

        # J+1 peut ne pas encore être disponible (avant 7h)
        if tomorrow_color and tomorrow_color not in COLORS:
            _LOGGER.warning(f"[Validation] Couleur J+1 invalide: '{tomorrow_color}' (attendu: {list(COLORS.keys())})")

        # Mise à jour du cache avec les données valides
        cached_count = 0
        for date, color in new_data.items():
            if color in COLORS:
                self._cached_data[date] = color
                cached_count += 1

        _LOGGER.info(f"[Validation] Cache mis à jour ({cached_count} entrées) - J: {today_color}, J+1: {tomorrow_color or 'N/A'}")
        return True

    async def _fetch_values(self, session, url: str) -> dict:
        """Appelle une URL de l'API RTE et retourne les couleurs {date: couleur}."""
        _LOGGER.debug(f"[API] Appel API - URL: {url}")

        async with async_timeout.timeout(15):
            async with session.get(url) as response:
                _LOGGER.debug(f"[API] Status HTTP: {response.status}")

                response_text = await response.text()
                if response.status != 200:
                    _LOGGER.error(
                        f"[API] Erreur HTTP {response.status} - Réponse: {response_text[:500]}"
                    )
                    return {}

                _LOGGER.debug(f"[API] Réponse brute (500 premiers chars): {response_text[:500]}")

                try:
                    data = json.loads(response_text)
                except json.JSONDecodeError as json_err:
                    _LOGGER.error(f"[API] Erreur parsing JSON: {json_err}")
                    _LOGGER.error(f"[API] Contenu reçu: {response_text[:1000]}")
                    return {}

                values = data.get("values", {})
                if not values:
                    _LOGGER.warning(f"[API] Clé 'values' vide ou absente - Structure complète: {data}")

                # L'API renvoie aussi des clés "AAAA-MM-JJ-fallback": "false" qui ne sont pas des couleurs
                return {d: c for d, c in values.items() if c in COLORS}

    async def _async_update_data(self):
        """Récupération des données depuis l'API RTE (tempoLight, puis saison en secours)."""
        now = dt_util.now().astimezone(dt_util.get_time_zone("Europe/Paris"))
        _LOGGER.debug(f"[API] Mise à jour à {now.strftime('%H:%M:%S')}")

        try:
            # Utiliser le contexte SSL pré-créé
            connector = aiohttp.TCPConnector(ssl=self._ssl_context)

            async with aiohttp.ClientSession(connector=connector) as session:
                new_data = await self._fetch_values(session, API_URL)

                # tempoLight renvoie parfois {"values": {}} : on se rabat sur l'API complète de la saison
                if self.get_tempo_date(0) not in new_data:
                    season_url = f"{API_URL_SEASON}?season={self.get_current_season()}"
                    _LOGGER.warning("[API] Date J absente de tempoLight, tentative via l'API saison")
                    season_data = await self._fetch_values(session, season_url)
                    if season_data:
                        new_data = season_data

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
                _LOGGER.warning("[API] Données invalides, conservation du cache")
                return self._cached_data

            return self.tempo_data

        except asyncio.TimeoutError:
            _LOGGER.error("[API] Timeout (15s) lors de la récupération des données")
            return self._cached_data
        except aiohttp.ClientError as err:
            _LOGGER.error(f"[API] Erreur de connexion: {err}")
            return self._cached_data
        except Exception as err:
            _LOGGER.error(f"[API] Erreur inattendue: {err}", exc_info=True)
            return self._cached_data


class TempoSensor(CoordinatorEntity, SensorEntity):
    """Sensor principal représentant l'état Tempo."""

    def __init__(self, coordinator: TempoDataCoordinator, entry: ConfigEntry) -> None:
        """Initialisation du sensor."""
        super().__init__(coordinator)

        self._attr_unique_id = f"tempo_edf_{entry.entry_id}"
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
        
        today_color_emoji = self.coordinator.get_color_emoji(today)
        tomorrow_color_emoji = self.coordinator.get_color_emoji(tomorrow)

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
            "today_color_emoji":today_color_emoji,
            "today_is_blue": today_color_code == 1,
            "today_is_white": today_color_code == 2,
            "today_is_red": today_color_code == 3,
            
            # Jour J+1
            "tomorrow_date": tomorrow,
            "tomorrow_color": tomorrow_color,
            "tomorrow_color_en": tomorrow_color_en,
            "tomorrow_color_code": tomorrow_color_code,
            "tomorrow_color_emoji":tomorrow_color_emoji,
            "tomorrow_is_blue": tomorrow_color_code == 1,
            "tomorrow_is_white": tomorrow_color_code == 2,
            "tomorrow_is_red": tomorrow_color_code == 3,
            
            # Combinaisons pratiques pour automatisations J (dépendent de l'heure actuelle)
            "today_is_red_hp": today_color_code == 3 and not is_hc,
            "today_is_red_hc": today_color_code == 3 and is_hc,
            "today_is_white_hp": today_color_code == 2 and not is_hc,
            "today_is_white_hc": today_color_code == 2 and is_hc,
            "today_is_blue_hp": today_color_code == 1 and not is_hc,
            "today_is_blue_hc": today_color_code == 1 and is_hc,
            
            # Saison
            "season": self.coordinator.get_current_season(),
            
            # Info système
            "data_source": "cache" if today not in self.coordinator.tempo_data else "api",
        }