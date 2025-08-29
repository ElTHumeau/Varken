
from logging import getLogger
from requests import Session, Request
from datetime import datetime, timezone

from varken.structures import QueuePages, RadarrMovie, RadarrQueue
from varken.helpers import hashit, connection_handler


class RadarrAPI(object):
    def __init__(self, server, dbmanager):
        self.dbmanager = dbmanager
        self.server = server
        # Create session to reduce server web thread load, and globally define pageSize for all requests
        self.session = Session()
        self.session.headers = {'X-Api-Key': self.server.api_key}
        self.logger = getLogger()

    def __repr__(self):
        return f"<radarr-{self.server.id}>"

    def get_missing(self):
        endpoint = '/api/v3/movie'
        now = datetime.now(timezone.utc).astimezone().isoformat()
        influx_payload = []
        missing = []

        req = self.session.prepare_request(Request('GET', self.server.url + endpoint))
        get = connection_handler(self.session, req, self.server.verify_ssl)

        if not get:
            return

        try:
            # Filtrer les champs qui ne sont pas dans RadarrMovie
            movies = []
            for movie in get:
                try:
                    movie_data = {k: v for k, v in movie.items() if k in RadarrMovie._fields}
                    movies.append(RadarrMovie(**movie_data))
                except TypeError as e:
                    self.logger.error('TypeError has occurred : %s while creating RadarrMovie structure for movie: %s', e, movie.get('title', 'Unknown'))
                    # Log les champs problématiques pour debug
                    problematic_fields = [k for k in movie.keys() if k not in RadarrMovie._fields]
                    if problematic_fields:
                        self.logger.debug('Champs non reconnus dans RadarrMovie: %s', problematic_fields)
                        self.logger.debug('Champs disponibles dans RadarrMovie: %s', list(RadarrMovie._fields))
                    continue
        except Exception as e:
            self.logger.error('Error processing Radarr movies: %s', e)
            return

        for movie in movies:
            if movie.monitored and not movie.hasFile:
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
                        "titleSlug": title_slug
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
            self.logger.warning("No data to send to influx for radarr-missing instance, discarding.")

    def get_queue(self):
        endpoint = '/api/v3/queue'
        now = datetime.now(timezone.utc).astimezone().isoformat()
        influx_payload = []
        pageSize = 250
        params = {'pageSize': pageSize, 'includeMovie': True, 'includeUnknownMovieItems': False}
        queueResponse = []
        queue = []

        req = self.session.prepare_request(Request('GET', self.server.url + endpoint, params=params))
        get = connection_handler(self.session, req, self.server.verify_ssl)

        if not get:
            return

        response = QueuePages(**get)
        queueResponse.extend(response.records)

        while response.totalRecords > response.page * response.pageSize:
            page = response.page + 1
            params = {'pageSize': pageSize, 'page': page, 'includeMovie': True, 'includeUnknownMovieItems': False}
            req = self.session.prepare_request(Request('GET', self.server.url + endpoint, params=params))
            get = connection_handler(self.session, req, self.server.verify_ssl)
            if not get:
                return

            response = QueuePages(**get)
            queueResponse.extend(response.records)

        for item in queueResponse:
            try:
                # Filtrer les champs qui ne sont pas dans RadarrQueue
                queue_data = {k: v for k, v in item.items() if k in RadarrQueue._fields}
                queue.append(RadarrQueue(**queue_data))
            except TypeError as e:
                self.logger.error('TypeError has occurred : %s while creating RadarrQueue structure for queue item. Data '
                                  'attempted is: %s', e, item)
                # Log les champs problématiques pour debug
                problematic_fields = [k for k in item.keys() if k not in RadarrQueue._fields]
                if problematic_fields:
                    self.logger.debug('Champs non reconnus dans RadarrQueue: %s', problematic_fields)

        for item in queue:
            if item.movie:
                movie = item.movie
                hash_id = hashit(f'{self.server.id}{movie.title}{movie.tmdbId}')
                influx_payload.append(
                    {
                        "measurement": "Radarr",
                        "tags": {
                            "type": "queue",
                            "tmdbId": movie.tmdbId,
                            "server": self.server.id,
                            "name": movie.title,
                            "quality": item.quality["quality"]["name"],
                            "size": item.size,
                            "title": item.title,
                            "timeleft": item.timeleft,
                            "estimatedCompletionTime": item.estimatedCompletionTime,
                            "status": item.status,
                            "trackedDownloadState": item.trackedDownloadState,
                            "trackedDownloadStatus": item.trackedDownloadStatus,
                            "downloadClient": item.downloadClient,
                            "protocol": item.protocol,
                            "indexer": item.indexer,
                            "outputPath": item.outputPath,
                            "id": item.id
                        },
                        "time": now,
                        "fields": {
                            "hash": hash_id,
                            "sizeleft": item.sizeleft,
                            "customFormatScore": item.customFormatScore
                        }
                    }
                )

        if influx_payload:
            self.dbmanager.write_points(influx_payload)
        else:
            self.logger.warning("No data to send to influx for radarr-queue instance, discarding.")
