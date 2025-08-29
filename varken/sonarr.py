"""
Module Sonarr avec support API v3
Compatible avec les versions v1 et v3 de l'API Sonarr
"""
from logging import getLogger
from requests import Session, Request
from datetime import datetime, timezone, date, timedelta

from varken.structures import Queue, SonarrTVShow
from varken.helpers import hashit, connection_handler
from varken.api_detector import APIVersionDetector


class SonarrAPIv3:
    """Classe Sonarr compatible avec API v1 et v3"""

    def __init__(self, server, dbmanager):
        self.dbmanager = dbmanager
        self.server = server
        self.session = Session()
        self.session.headers = {'X-Api-Key': self.server.api_key}
        self.logger = getLogger()

        # Détection automatique de la version API (ou utilisation de la version forcée)
        detector = APIVersionDetector()
        self.api_version = detector.detect_sonarr_version(
            self.server.url,
            self.server.api_key,
            self.server.verify_ssl,
            self.server.id  # Passer l'ID du serveur pour les variables d'environnement
        )

        if not self.api_version:
            self.logger.error(f"Impossible de détecter la version API pour {self.server.url}")
            self.api_version = 'v1'  # Fallback sur v1

        # Définir le préfixe API selon la version
        self.api_prefix = f'/api/{self.api_version}' if self.api_version == 'v3' else '/api'

        # Pour API v3, ajouter la pagination par défaut
        if self.api_version == 'v3':
            self.session.params = {'pageSize': 1000}
        else:
            # Pour v1, garder la compatibilité
            self.session.params = {'pageSize': 1000}

    def __repr__(self):
        return f"<sonarr-{self.server.id}-{self.api_version}>"

    def get_calendar(self, query="Missing"):
        """Récupère les épisodes du calendrier (manquants ou futurs)"""
        endpoint = f'{self.api_prefix}/calendar'
        today = str(date.today())
        last_days = str(date.today() - timedelta(days=self.server.missing_days))
        future = str(date.today() + timedelta(days=self.server.future_days))
        now = datetime.now(timezone.utc).astimezone().isoformat()

        if query == "Missing":
            params = {'start': last_days, 'end': today}
        else:
            params = {'start': today, 'end': future}

        influx_payload = []
        air_days = []
        missing = []

        req = self.session.prepare_request(Request('GET', self.server.url + endpoint, params=params))
        get = connection_handler(self.session, req, self.server.verify_ssl)

        if not get:
            return

        # Pour API v3, gérer la pagination si nécessaire
        calendar_data = get
        if self.api_version == 'v3' and isinstance(get, dict) and 'records' in get:
            calendar_data = get['records']

        tv_shows = []
        for show in calendar_data:
            try:
                # Adapter les données selon la version API
                if self.api_version == 'v3':
                    show = self._adapt_v3_episode_data(show)
                tv_shows.append(SonarrTVShow(**show))
            except TypeError as e:
                self.logger.error('Erreur création SonarrTVShow : %s. Données: %s', e, show)

        for show in tv_shows:
            sxe = f'S{show.seasonNumber:0>2}E{show.episodeNumber:0>2}'
            if show.hasFile:
                downloaded = 1
            else:
                downloaded = 0

            if query == "Missing":
                if show.monitored and not downloaded:
                    missing.append((show.series['title'], downloaded, sxe, show.title, show.airDateUtc, show.id))
            else:
                air_days.append((show.series['title'], downloaded, sxe, show.title, show.airDateUtc, show.id))

        for series_title, dl_status, sxe, episode_title, air_date_utc, sonarr_id in (air_days or missing):
            hash_id = hashit(f'{self.server.id}{series_title}{sxe}')
            influx_payload.append(
                {
                    "measurement": "Sonarr",
                    "tags": {
                        "type": query,
                        "sonarrId": sonarr_id,
                        "server": self.server.id,
                        "name": series_title,
                        "epname": episode_title,
                        "sxe": sxe,
                        "airsUTC": air_date_utc,
                        "downloaded": dl_status,
                        "api_version": self.api_version
                    },
                    "time": now,
                    "fields": {
                        "hash": hash_id
                    }
                }
            )

        self.dbmanager.write_points(influx_payload)

    def get_missing_v3(self):
        """Récupère les épisodes manquants via l'endpoint v3 wanted/missing"""
        if self.api_version != 'v3':
            # Pour v1, utiliser get_calendar avec query="Missing"
            return self.get_calendar(query="Missing")

        endpoint = f'{self.api_prefix}/wanted/missing'
        now = datetime.now(timezone.utc).astimezone().isoformat()
        influx_payload = []
        missing = []

        params = {
            'pageSize': 1000,
            'sortKey': 'airDateUtc',
            'sortDirection': 'desc',
            'includeSeries': True
        }

        req = self.session.prepare_request(Request('GET', self.server.url + endpoint, params=params))
        get = connection_handler(self.session, req, self.server.verify_ssl)

        if not get:
            return

        # API v3 retourne une structure paginée
        missing_data = get.get('records', []) if isinstance(get, dict) else get

        for episode in missing_data:
            try:
                # Adapter si nécessaire
                episode = self._adapt_v3_episode_data(episode)

                series_title = episode.get('series', {}).get('title', 'Unknown')
                sxe = f"S{episode.get('seasonNumber', 0):0>2}E{episode.get('episodeNumber', 0):0>2}"
                episode_title = episode.get('title', 'Unknown')
                air_date = episode.get('airDateUtc', '')
                episode_id = episode.get('id', 0)

                missing.append((series_title, 0, sxe, episode_title, air_date, episode_id))
            except Exception as e:
                self.logger.error('Erreur traitement épisode manquant : %s', e)
                continue

        for series_title, dl_status, sxe, episode_title, air_date_utc, sonarr_id in missing:
            hash_id = hashit(f'{self.server.id}{series_title}{sxe}')
            influx_payload.append(
                {
                    "measurement": "Sonarr",
                    "tags": {
                        "type": "Missing",
                        "sonarrId": sonarr_id,
                        "server": self.server.id,
                        "name": series_title,
                        "epname": episode_title,
                        "sxe": sxe,
                        "airsUTC": air_date_utc,
                        "downloaded": dl_status,
                        "api_version": self.api_version
                    },
                    "time": now,
                    "fields": {
                        "hash": hash_id
                    }
                }
            )

        self.dbmanager.write_points(influx_payload)

    def get_queue(self):
        """Récupère la file d'attente de téléchargement"""
        influx_payload = []
        endpoint = f'{self.api_prefix}/queue'
        now = datetime.now(timezone.utc).astimezone().isoformat()
        queue = []

        # Pour API v3, ajouter des paramètres supplémentaires
        params = {}
        if self.api_version == 'v3':
            params = {
                'pageSize': 1000,
                'includeUnknownSeriesItems': False,
                'includeSeries': True,
                'includeEpisode': True
            }

        req = self.session.prepare_request(
            Request('GET', self.server.url + endpoint, params=params)
        )
        get = connection_handler(self.session, req, self.server.verify_ssl)

        if not get:
            return

        # Pour API v3, gérer la structure de réponse différente
        queue_data = get
        if self.api_version == 'v3' and isinstance(get, dict) and 'records' in get:
            queue_data = get['records']

        download_queue = []
        for show in queue_data:
            try:
                # Adapter les données selon la version API
                if self.api_version == 'v3':
                    show = self._adapt_v3_queue_data(show)
                download_queue.append(Queue(**show))
            except TypeError as e:
                self.logger.error('Erreur création Queue : %s. Données: %s', e, show)

        if not download_queue:
            return

        for show in download_queue:
            try:
                sxe = f"S{show.episode['seasonNumber']:0>2}E{show.episode['episodeNumber']:0>2}"
            except (TypeError, KeyError) as e:
                self.logger.error('Erreur traitement queue : %s', e)
                continue

            if show.protocol.upper() == 'USENET':
                protocol_id = 1
            else:
                protocol_id = 0

            quality_name = 'Unknown'
            if show.quality and 'quality' in show.quality:
                quality_name = show.quality['quality'].get('name', 'Unknown')

            series_title = show.series.get('title', 'Unknown') if show.series else 'Unknown'
            episode_title = show.episode.get('title', 'Unknown') if show.episode else 'Unknown'

            queue.append((series_title, episode_title, show.protocol.upper(),
                         protocol_id, sxe, show.id, quality_name))

        for series_title, episode_title, protocol, protocol_id, sxe, sonarr_id, quality in queue:
            hash_id = hashit(f'{self.server.id}{series_title}{sxe}')
            influx_payload.append(
                {
                    "measurement": "Sonarr",
                    "tags": {
                        "type": "Queue",
                        "sonarrId": sonarr_id,
                        "server": self.server.id,
                        "name": series_title,
                        "epname": episode_title,
                        "sxe": sxe,
                        "protocol": protocol,
                        "protocol_id": protocol_id,
                        "quality": quality,
                        "api_version": self.api_version
                    },
                    "time": now,
                    "fields": {
                        "hash": hash_id
                    }
                }
            )

        if influx_payload:
            self.dbmanager.write_points(influx_payload)
        else:
            self.logger.debug("Aucune donnée à envoyer à InfluxDB pour Sonarr")

    def _adapt_v3_episode_data(self, episode_data):
        """Adapte les données d'épisode v3 pour compatibilité avec la structure existante"""
        # S'assurer que les champs requis existent
        if 'hasFile' not in episode_data and 'episodeFile' in episode_data:
            episode_data['hasFile'] = episode_data['episodeFile'] is not None

        # Pour v3, la structure peut être différente
        if 'episodeFileId' not in episode_data and 'episodeFile' in episode_data:
            if isinstance(episode_data['episodeFile'], dict):
                episode_data['episodeFileId'] = episode_data['episodeFile'].get('id')

        return episode_data

    def _adapt_v3_queue_data(self, queue_data):
        """Adapte les données de queue v3 pour compatibilité avec la structure existante"""
        # S'assurer que les champs requis existent
        if 'protocol' not in queue_data and 'downloadClient' in queue_data:
            # Deviner le protocole depuis le client de téléchargement
            client = queue_data.get('downloadClient', '').lower()
            if 'nzb' in client or 'sab' in client or 'usenet' in client:
                queue_data['protocol'] = 'usenet'
            else:
                queue_data['protocol'] = 'torrent'

        # S'assurer que series et episode existent
        if 'series' not in queue_data and 'seriesId' in queue_data:
            # Pour v3, les infos de série peuvent être dans un champ différent
            queue_data['series'] = queue_data.get('series', {})

        if 'episode' not in queue_data and 'episodeId' in queue_data:
            # Pour v3, les infos d'épisode peuvent être dans un champ différent
            queue_data['episode'] = queue_data.get('episode', {})

        return queue_data
