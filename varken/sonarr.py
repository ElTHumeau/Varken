"""
Module Sonarr avec support API v3
Compatible avec les versions v1 et v3 de l'API Sonarr
"""
from logging import getLogger
from requests import Session, Request
from datetime import datetime, timezone, date, timedelta

from varken.structures import SonarrEpisode, SonarrTVShow, SonarrQueue, QueuePages
from varken.helpers import hashit, connection_handler


class SonarrAPI(object):
    def __init__(self, server, dbmanager):
        self.dbmanager = dbmanager
        self.server = server
        # Create session to reduce server web thread load, and globally define pageSize for all requests
        self.session = Session()
        self.session.headers = {'X-Api-Key': self.server.api_key}
        self.session.params = {'pageSize': 1000}
        self.logger = getLogger()

    def __repr__(self):
        return f"<sonarr-{self.server.id}>"

    def get_episode(self, id):
        endpoint = '/api/v3/episode'
        params = {'episodeIds': id}

        req = self.session.prepare_request(Request('GET', self.server.url + endpoint, params=params))
        get = connection_handler(self.session, req, self.server.verify_ssl)

        if not get:
            return

        return SonarrEpisode(**get[0])

    def get_calendar(self, query="Missing"):
        endpoint = '/api/v3/calendar/'
        today = str(date.today())
        last_days = str(date.today() - timedelta(days=self.server.missing_days))
        future = str(date.today() + timedelta(days=self.server.future_days))
        now = datetime.now(timezone.utc).astimezone().isoformat()
        if query == "Missing":
            params = {'start': last_days, 'end': today, 'includeSeries': True}
        else:
            params = {'start': today, 'end': future, 'includeSeries': True}
        influx_payload = []
        air_days = []
        missing = []

        req = self.session.prepare_request(Request('GET', self.server.url + endpoint, params=params))
        get = connection_handler(self.session, req, self.server.verify_ssl)

        if not get:
            return

        tv_shows = []
        for show in get:
            try:
                tv_shows.append(SonarrEpisode(**show))
            except TypeError as e:
                self.logger.error('TypeError has occurred : %s while creating SonarrEpisode structure for show. Data '
                                  'attempted is: %s', e, show)

        for episode in tv_shows:
            tvShow = episode.series
            sxe = f'S{episode.seasonNumber:0>2}E{episode.episodeNumber:0>2}'
            if episode.hasFile:
                downloaded = 1
            else:
                downloaded = 0
            if query == "Missing":
                if episode.monitored and not downloaded:
                    missing.append((tvShow['title'], downloaded, sxe, episode.title,
                                    episode.airDateUtc, episode.seriesId))
            else:
                air_days.append((tvShow['title'], downloaded, sxe, episode.title, episode.airDateUtc, episode.seriesId))

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
                        "downloaded": dl_status
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
            self.logger.warning("No data to send to influx for sonarr-calendar instance, discarding.")

    def get_queue(self):
        endpoint = '/api/v3/queue'
        now = datetime.now(timezone.utc).astimezone().isoformat()
        influx_payload = []
        pageSize = 250
        params = {'pageSize': pageSize, 'includeEpisode': True, 'includeSeries': True, 'includeUnknownSeriesItems': False}
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
            params = {'pageSize': pageSize, 'page': page, 'includeEpisode': True, 'includeSeries': True, 'includeUnknownSeriesItems': False}
            req = self.session.prepare_request(Request('GET', self.server.url + endpoint, params=params))
            get = connection_handler(self.session, req, self.server.verify_ssl)
            if not get:
                return

            response = QueuePages(**get)
            queueResponse.extend(response.records)

        for item in queueResponse:
            try:
                queue.append(SonarrQueue(**item))
            except TypeError as e:
                self.logger.error('TypeError has occurred : %s while creating SonarrQueue structure for queue item. Data '
                                  'attempted is: %s', e, item)

        for item in queue:
            if item.episode:
                episode = item.episode
                series = item.series
                sxe = f'S{episode.seasonNumber:0>2}E{episode.episodeNumber:0>2}'
                hash_id = hashit(f'{self.server.id}{series["title"]}{sxe}')
                influx_payload.append(
                    {
                        "measurement": "Sonarr",
                        "tags": {
                            "type": "queue",
                            "sonarrId": series["id"],
                            "server": self.server.id,
                            "name": series["title"],
                            "epname": episode.title,
                            "sxe": sxe,
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
            self.logger.warning("No data to send to influx for sonarr-queue instance, discarding.")
