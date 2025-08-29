
from logging import getLogger
from requests import Session, Request
from datetime import datetime, timezone

from varken.structures import RadarrMovie, Queue
from varken.helpers import hashit, connection_handler
from varken.api_detector import APIVersionDetector


class RadarrAPIv3(object):
    def __init__(self, server, dbmanager):
        self.dbmanager = dbmanager
        self.server = server
        self.session = Session()
        self.session.headers = {'X-Api-Key': self.server.api_key}
        self.logger = getLogger()
        
        detector = APIVersionDetector()
        self.api_version = detector.detect_radarr_version(
            self.server.url, 
            self.server.api_key, 
            self.server.verify_ssl,
            self.server.id
        )
        
        if not self.api_version:
            self.logger.error(f"Unable to detect API version for {self.server.url}, defaulting to v1")
            self.api_version = 'v1'
        
        self.api_prefix = f'/api/{self.api_version}' if self.api_version == 'v3' else '/api'
        
        if self.api_version == 'v3':
            self.session.params = {'pageSize': 1000}
    
    def __repr__(self):
        return f"<radarr-{self.server.id}-{self.api_version}>"
    
    def get_missing(self):
        """Récupère les films manquants/surveillés"""
        endpoint = f'{self.api_prefix}/movie'
        now = datetime.now(timezone.utc).astimezone().isoformat()
        influx_payload = []
        missing = []
        
        req = self.session.prepare_request(Request('GET', self.server.url + endpoint))
        get = connection_handler(self.session, req, self.server.verify_ssl)
        
        if not get:
            return
        
        # Pour API v3, gérer la pagination si nécessaire
        movies_data = get
        if self.api_version == 'v3' and isinstance(get, dict) and 'records' in get:
            movies_data = get['records']
            # TODO: Implémenter la pagination complète si totalRecords > pageSize
        
        try:
            movies = []
            for movie_data in movies_data:
                try:
                    # Adapter les données selon la version API
                    if self.api_version == 'v3':
                        # API v3 peut avoir des champs différents
                        movie_data = self._adapt_v3_movie_data(movie_data)
                    movies.append(RadarrMovie(**movie_data))
                except TypeError as e:
                    self.logger.debug(f'Erreur création RadarrMovie: {e}')
                    continue
        except Exception as e:
            self.logger.error('Erreur lors du traitement des films : %s', e)
            return
        
        for movie in movies:
            if movie.monitored and not movie.downloaded:
                if movie.isAvailable:
                    ma = 0
                else:
                    ma = 1
                
                movie_name = f'{movie.title} ({movie.year})'
                missing.append((movie_name, ma, movie.tmdbId, movie.titleSlug))
        
        for title, ma, mid, title_slug in missing:
            hash_id = hashit(f'{self.server.id}{title}{mid}')
            influx_payload.append(
                {
                    "measurement": "Radarr",
                    "tags": {
                        "Missing": True,
                        "Missing_Available": ma,
                        "tmdbId": mid,
                        "server": self.server.id,
                        "name": title,
                        "titleSlug": title_slug,
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
        endpoint = f'{self.api_prefix}/queue'
        now = datetime.now(timezone.utc).astimezone().isoformat()
        influx_payload = []
        queue = []
        
        # Pour API v3, ajouter des paramètres supplémentaires
        params = {}
        if self.api_version == 'v3':
            params = {
                'pageSize': 1000,
                'includeUnknownMovieItems': False,
                'includeMovie': True
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
        
        for item in queue_data:
            try:
                # Adapter les données selon la version API
                if self.api_version == 'v3':
                    item = self._adapt_v3_queue_data(item)
                
                if 'movie' in item:
                    item['movie'] = RadarrMovie(**item['movie'])
            except TypeError as e:
                self.logger.error('Erreur création structure RadarrMovie : %s', e)
                continue
        
        try:
            download_queue = []
            for item in queue_data:
                try:
                    download_queue.append(Queue(**item))
                except TypeError as e:
                    self.logger.debug(f'Erreur création Queue: {e}')
                    continue
        except Exception as e:
            self.logger.error('Erreur création structure Queue : %s', e)
            return
        
        for queue_item in download_queue:
            if not queue_item.movie:
                continue
                
            movie = queue_item.movie
            name = f'{movie.title} ({movie.year})'
            
            if queue_item.protocol.upper() == 'USENET':
                protocol_id = 1
            else:
                protocol_id = 0
            
            quality_name = 'Unknown'
            if queue_item.quality and 'quality' in queue_item.quality:
                quality_name = queue_item.quality['quality'].get('name', 'Unknown')
            
            queue.append((name, quality_name, queue_item.protocol.upper(),
                         protocol_id, queue_item.id, movie.titleSlug))
        
        for name, quality, protocol, protocol_id, qid, title_slug in queue:
            hash_id = hashit(f'{self.server.id}{name}{quality}')
            influx_payload.append(
                {
                    "measurement": "Radarr",
                    "tags": {
                        "type": "Queue",
                        "tmdbId": qid,
                        "server": self.server.id,
                        "name": name,
                        "quality": quality,
                        "protocol": protocol,
                        "protocol_id": protocol_id,
                        "titleSlug": title_slug,
                        "api_version": self.api_version
                    },
                    "time": now,
                    "fields": {
                        "hash": hash_id
                    }
                }
            )
        
        self.dbmanager.write_points(influx_payload)
    
    def _adapt_v3_movie_data(self, movie_data):
        """Adapte les données de film v3 pour compatibilité avec la structure existante"""
        # API v3 peut avoir des noms de champs différents
        # Mapper les nouveaux champs vers les anciens si nécessaire
        
        # Exemple de mappings potentiels (à ajuster selon les vrais changements)
        if 'hasFile' not in movie_data and 'movieFile' in movie_data:
            movie_data['hasFile'] = movie_data['movieFile'] is not None
        
        if 'downloaded' not in movie_data:
            movie_data['downloaded'] = movie_data.get('hasFile', False)
        
        # S'assurer que isAvailable existe
        if 'isAvailable' not in movie_data:
            movie_data['isAvailable'] = movie_data.get('status', '') == 'released'
        
        return movie_data
    
    def _adapt_v3_queue_data(self, queue_data):
        """Adapte les données de queue v3 pour compatibilité avec la structure existante"""
        # Adapter la structure si nécessaire pour API v3
        
        # S'assurer que les champs requis existent
        if 'protocol' not in queue_data and 'downloadClient' in queue_data:
            # Deviner le protocole depuis le client de téléchargement
            client = queue_data['downloadClient'].lower()
            if 'nzb' in client or 'sab' in client or 'usenet' in client:
                queue_data['protocol'] = 'usenet'
            else:
                queue_data['protocol'] = 'torrent'
        
        return queue_data
