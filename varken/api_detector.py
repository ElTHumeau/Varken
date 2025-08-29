from logging import getLogger
from requests import Session, Request
from os import getenv
from varken.helpers import connection_handler


class APIVersionDetector(object):
    _version_cache = {}
    
    def __init__(self):
        self.logger = getLogger()
    
    def detect_radarr_version(self, server_url, api_key, verify_ssl=False, server_id=None):
        cache_key = f"radarr_{server_url}_{server_id}"
        if cache_key in self._version_cache:
            self.logger.debug(f"Version API Radarr from cache: {self._version_cache[cache_key]}")
            return self._version_cache[cache_key]
        
        # Check for forced version via environment variable
        if server_id:
            env_var = f'VRKN_RADARR_{server_id}_API_VERSION'
            forced_version = getenv(env_var)
            if forced_version:
                if forced_version in ['1', 'v1']:
                    self.logger.info(f"Radarr API forced to v1 via {env_var}")
                    self._version_cache[cache_key] = 'v1'
                    return 'v1'
                elif forced_version in ['3', 'v3']:
                    self.logger.info(f"Radarr API forced to v3 via {env_var}")
                    self._version_cache[cache_key] = 'v3'
                    return 'v3'
                else:
                    self.logger.warning(f"Invalid Radarr API version in {env_var}: {forced_version}")
        
        # Auto-detect if no forced version
        session = Session()
        session.headers = {'X-Api-Key': api_key}
        
        endpoints_to_test = [
            ('/api/v3/system/status', 'v3'),
            ('/api/system/status', 'v1'),
        ]
        
        for endpoint, version in endpoints_to_test:
            try:
                req = session.prepare_request(Request('GET', server_url + endpoint))
                response = connection_handler(session, req, verify_ssl)
                
                if response:
                    self.logger.info(f"Radarr API {version} detected on {server_url}")
                    if 'version' in response:
                        app_version = response.get('version', '')
                        self.logger.info(f"Radarr version {app_version}")
                    self._version_cache[cache_key] = version
                    return version
            except Exception as e:
                self.logger.debug(f"Failed to test Radarr {version}: {e}")
                continue
        
        self.logger.error(f"Unable to detect Radarr API version on {server_url}")
        return None
    
    def detect_sonarr_version(self, server_url, api_key, verify_ssl=False, server_id=None):
        cache_key = f"sonarr_{server_url}_{server_id}"
        if cache_key in self._version_cache:
            self.logger.debug(f"Sonarr API version from cache: {self._version_cache[cache_key]}")
            return self._version_cache[cache_key]
        
        # Check for forced version via environment variable
        if server_id:
            env_var = f'VRKN_SONARR_{server_id}_API_VERSION'
            forced_version = getenv(env_var)
            if forced_version:
                if forced_version in ['1', 'v1']:
                    self.logger.info(f"Sonarr API forced to v1 via {env_var}")
                    self._version_cache[cache_key] = 'v1'
                    return 'v1'
                elif forced_version in ['3', 'v3']:
                    self.logger.info(f"Sonarr API forced to v3 via {env_var}")
                    self._version_cache[cache_key] = 'v3'
                    return 'v3'
                else:
                    self.logger.warning(f"Invalid Sonarr API version in {env_var}: {forced_version}")
        
        # Auto-detect if no forced version
        session = Session()
        session.headers = {'X-Api-Key': api_key}
        
        endpoints_to_test = [
            ('/api/v3/system/status', 'v3'),
            ('/api/system/status', 'v1'),
        ]
        
        for endpoint, version in endpoints_to_test:
            try:
                req = session.prepare_request(Request('GET', server_url + endpoint))
                response = connection_handler(session, req, verify_ssl)
                
                if response:
                    self.logger.info(f"Sonarr API {version} detected on {server_url}")
                    if version == 'v3' and 'version' in response:
                        app_version = response.get('version', '')
                        if app_version.startswith('4.'):
                            self.logger.info(f"Sonarr v4 detected, uses API v3")
                    self._version_cache[cache_key] = version
                    return version
            except Exception as e:
                self.logger.debug(f"Failed to test Sonarr {version}: {e}")
                continue
        
        self.logger.error(f"Unable to detect Sonarr API version on {server_url}")
        return None
    
    def detect_lidarr_version(self, server_url, api_key, verify_ssl=False, server_id=None):
        cache_key = f"lidarr_{server_url}_{server_id}"
        if cache_key in self._version_cache:
            self.logger.debug(f"Lidarr API version from cache: {self._version_cache[cache_key]}")
            return self._version_cache[cache_key]
        
        # Check for forced version via environment variable
        if server_id:
            env_var = f'VRKN_LIDARR_{server_id}_API_VERSION'
            forced_version = getenv(env_var)
            if forced_version:
                if forced_version in ['1', 'v1']:
                    self.logger.info(f"Lidarr API forced to v1 via {env_var}")
                    self._version_cache[cache_key] = 'v1'
                    return 'v1'
                elif forced_version in ['3', 'v3']:
                    self.logger.info(f"Lidarr API forced to v3 via {env_var}")
                    self._version_cache[cache_key] = 'v3'
                    return 'v3'
                else:
                    self.logger.warning(f"Invalid Lidarr API version in {env_var}: {forced_version}")
        
        # Auto-detect if no forced version
        session = Session()
        session.headers = {'X-Api-Key': api_key}
        
        endpoints_to_test = [
            ('/api/v3/system/status', 'v3'),
            ('/api/v1/system/status', 'v1'),
        ]
        
        for endpoint, version in endpoints_to_test:
            try:
                req = session.prepare_request(Request('GET', server_url + endpoint))
                response = connection_handler(session, req, verify_ssl)
                
                if response:
                    self.logger.info(f"Lidarr API {version} detected on {server_url}")
                    self._version_cache[cache_key] = version
                    return version
            except Exception as e:
                self.logger.debug(f"Failed to test Lidarr {version}: {e}")
                continue
        
        self.logger.error(f"Unable to detect Lidarr API version on {server_url}")
        return None
