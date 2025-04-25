import requests
import time
import logging

class GenApiClient:
    BASE_URL = 'https://api.gen-api.ru/api/v1/networks'

    def __init__(self, token):
        self.token = token
        self.headers = {
            'Authorization': f'Bearer {self.token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }
        self.logger = logging.getLogger('api')

    def create_network_task(self, network_id, parameters):
        url = f'{self.BASE_URL}/{network_id}'
        self.logger.debug(f"POST {url} with parameters: {parameters}")
        try:
            response = requests.post(url, json=parameters, headers=self.headers, timeout=30)
            response.raise_for_status()
            result = response.json()
            self.logger.debug(f"Response: {result}")
            return result
        except requests.exceptions.HTTPError as http_err:
            self.logger.error(f"HTTP error: {http_err} - {response.text}")
            raise RuntimeError(f'HTTP error occurred: {http_err} - {response.text}') from http_err
        except requests.exceptions.RequestException as err:
            self.logger.error(f"Request error: {err}")
            raise RuntimeError(f'Error during request to GenAPI: {err}') from err

    def get_request_status(self, request_id):
        url = f'https://api.gen-api.ru/api/v1/request/get/{request_id}'
        self.logger.debug(f"GET {url}")
        try:
            response = requests.get(url, headers=self.headers, timeout=10)
            response.raise_for_status()
            result = response.json()
            self.logger.debug(f"Status response: {result}")
            return result
        except requests.exceptions.HTTPError as http_err:
            self.logger.error(f"HTTP error: {http_err} - {response.text}")
            raise RuntimeError(f'HTTP error occurred: {http_err} - {response.text}') from http_err
        except requests.exceptions.RequestException as err:
            self.logger.error(f"Request error: {err}")
            raise RuntimeError(f'Error during request to GenAPI: {err}') from err

    def wait_for_result(self, request_id, max_attempts=150, delay=3):
        self.logger.info(f"Start polling for request_id={request_id}")
        for attempt in range(max_attempts):
            status_response = self.get_request_status(request_id)
            status = status_response.get('status')
            if status == 'success':
                self.logger.info(f"Request {request_id} succeeded")
                return status_response
            elif status == 'processing':
                self.logger.debug(f"Request {request_id} processing, attempt {attempt+1}/{max_attempts}")
                time.sleep(delay)
            elif status == 'failed':
                self.logger.error(f"Request {request_id} failed: {status_response}")
                return status_response
            else:
                self.logger.warning(f"Request {request_id} unknown status: {status}")
                time.sleep(delay)
        self.logger.error(f"Request {request_id} polling timed out after {max_attempts} attempts")
        return None