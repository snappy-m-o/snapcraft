# -*- Mode:Python; indent-tabs-mode:nil; tab-width:4 -*-
#
# Copyright (C) 2016 Canonical Ltd
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 3 as
# published by the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import json
import logging
import http.server
import os
import urllib.parse

import snapcraft.tests


logger = logging.getLogger(__name__)


class FakeSSOServer(http.server.HTTPServer):

    def __init__(self, server_address):
        super().__init__(
            server_address, FakeSSORequestHandler)


class FakeSSORequestHandler(http.server.BaseHTTPRequestHandler):

    _API_PATH = '/api/v2/'

    def do_POST(self):
        parsed_path = urllib.parse.urlparse(self.path)
        tokens_discharge_path = self._API_PATH + 'tokens/discharge'
        if parsed_path.path.startswith(tokens_discharge_path):
            self._handle_tokens_discharge_request()
        else:
            logger.error('Not implemented path in fake SSO server: {}'.format(
                self.path))
            raise NotImplementedError(self.path)

    def _handle_tokens_discharge_request(self):
        string_data = self.rfile.read(
            int(self.headers['Content-Length'])).decode('utf8')
        data = json.loads(string_data)
        logger.debug(
            'Handling tokens discharge request with content {}'.format(
                data))
        if data['password'] == 'test correct password':
            self._send_tokens_discharge(data)
        else:
            self._send_invalid_credentials_error()

    def _send_tokens_discharge(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        macaroons = data['macaroons']
        discharge_macaroons = [
            [permission, 'discharge macaroon for {}'.format(permission)] for
            permission, _ in macaroons]
        response = {
            'discharge_macaroons': discharge_macaroons}
        self.wfile.write(
            json.dumps(response).encode())

    def _send_invalid_credentials_error(self):
        self.send_response(401)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        response = {
            'code': 'INVALID_CREDENTIALS',
            'message': 'Provided email/password is not correct.',
            'extra': {}
        }
        self.wfile.write(json.dumps(response).encode())


class FakeStoreAPIServer(http.server.HTTPServer):

    def __init__(self, server_address):
        super().__init__(
            server_address, FakeStoreAPIRequestHandler)


class FakeStoreAPIRequestHandler(http.server.BaseHTTPRequestHandler):

    _API_PATH = '/api/2.0/'
    _DEV_API_PATH = '/dev/'

    def do_POST(self):
        parsed_path = urllib.parse.urlparse(self.path)
        acl_path = self._API_PATH + 'acl/'
        register_path = self._DEV_API_PATH + 'register-name/'
        upload_path = self._DEV_API_PATH + 'snap-upload/'
        if parsed_path.path.startswith(acl_path):
            permission = parsed_path.path[len(acl_path):].strip('/')
            self._handle_acl_request(permission)
        elif parsed_path.path.startswith(register_path):
            self._handle_registration_request()
        elif parsed_path.path.startswith(upload_path):
            self._handle_upload_request()
        else:
            logger.error(
                'Not implemented path in fake Store API server: {}'.format(
                    self.path))
            raise NotImplementedError(self.path)

    def _handle_acl_request(self, permission):
        logger.debug(
            'Handling ACL request for {}'.format(permission))
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        response = {'macaroon': 'test-fake-macaroon for {}'.format(permission)}
        self.wfile.write(json.dumps(response).encode())

    def _handle_registration_request(self):
        string_data = self.rfile.read(
            int(self.headers['Content-Length'])).decode('utf8')
        data = json.loads(string_data)
        logger.debug(
            'Handling registration request with content {}'.format(
                data))
        self.send_response(201)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        response = {'snap_id': 'test-snap-id'}
        self.wfile.write(json.dumps(response).encode())

    def _handle_upload_request(self):
        logger.debug('Handling upload request')
        self.send_response(202)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        response = {
            'status_url': urllib.parse.urljoin(
                'http://localhost:{}/'.format(self.server.server_port),
                'dev/api/click-scan-complete/updown/test-upload-id'),
            'success': True
        }
        self.wfile.write(json.dumps(response).encode())

    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        scan_complete_path = (
            self._DEV_API_PATH + 'api/click-scan-complete/updown/')
        if parsed_path.path.startswith(scan_complete_path):
            self._handle_scan_complete_request()
        else:
            logger.error(
                'Not implemented path in fake Store API server: {}'.format(
                    self.path))
            raise NotImplementedError(self.path)

    def _handle_scan_complete_request(self):
        logger.debug('Handling scan complete request')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        response = {
             'message': '',
             'application_url': 'test-application-url',
             'revision': 'test-revision',
             'completed': True
        }
        self.wfile.write(json.dumps(response).encode())


class FakeStoreSearchServer(http.server.HTTPServer):

    def __init__(self, server_address):
        super().__init__(
            server_address, FakeStoreSearchRequestHandler)


class FakeStoreSearchRequestHandler(http.server.BaseHTTPRequestHandler):

    # XXX This fake server as reused as download server, to avoid passing a
    # port as an argument. --elopio - 2016-05-01

    _API_PATH = '/api/v1/'

    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        search_path = self._API_PATH + 'search'
        download_path = '/download-snap/'
        if parsed_path.path.startswith(search_path):
            self._handle_search_request(
                urllib.parse.parse_qs(parsed_path.query)['q'])
        elif parsed_path.path.startswith(download_path):
            self._handle_download_request(parsed_path[len(download_path):])
        else:
            logger.error(
                'Not implemented path in fake Store Search server: {}'.format(
                    self.path))
            raise NotImplementedError(self.path)

    def _handle_search_request(self, query):
        if len(query) > 1 or 'package_name:' not in query[0]:
            logger.error(
                'Not implemented query in fake Store Search server: {}'.format(
                    query))
            raise NotImplementedError(query)
        query = query[0]
        package = query.split('package_name:')[1].strip('"')
        logger.debug(
            'Handling search request for package {}, with headers {}'.format(
                package, self.headers))
        self.send_response(200)
        self.send_header('Content-Type', 'application/hal+json')
        self.end_headers()
        if package == 'test-snap':
            response = {'_embedded': {
                'clickindex:package': [
                    {'download_url': urllib.parse.urljoin(
                        'http://localhost:{}'.format(self.server.server_port),
                        'download-snap/test-snap.snap'),
                     # sha512sum snapcraft/tests/data/test-snap.snap
                     'download_sha512': (
                        '69d57dcacf4f126592d4e6ff689ad8bb8a083c7b9fe44f6e738ef'
                        'd22a956457f14146f7f067b47bd976cf0292f2993ad864ccb498b'
                        'fda4128234e4c201f28fe9')}]}}
        else:
            response = {}
        self.wfile.write(json.dumps(response).encode())

    def _handle_download_request(self, snap):
        logger.debug('Handling download request for snap {}'.format(snap))
        self.send_response(200)
        self.send_header('Content-Type', 'application/octet-stream')
        self.end_headers()
        # TODO create a test snap during the test. --elopio - 2016-05-01
        snap_path = os.path.join(
            os.path.dirname(snapcraft.tests.__file__), 'data',
            'test-snap.snap')
        with open(snap_path, 'rb') as snap_file:
            self.wfile.write(snap_file.read())


class FakeStoreUploadServer(http.server.HTTPServer):

    def __init__(self, server_address):
        super().__init__(
            server_address, FakeStoreUploadRequestHandler)


class FakeStoreUploadRequestHandler(http.server.BaseHTTPRequestHandler):

    def do_POST(self):
        parsed_path = urllib.parse.urlparse(self.path)
        if parsed_path.path.startswith('/unscanned-upload/'):
            self._handle_upload_request()
        else:
            logger.error(
                'Not implemented path in fake Store Search server: {}'.format(
                    self.path))
            raise NotImplementedError(self.path)

    def _handle_upload_request(self):
        logger.info('Handling upload request')
        self.send_response(200)
        self.send_header('Content-Type', 'application/octet-stream')
        self.end_headers()
        response = {
            'successful': True,
            'upload_id': 'test-upload-id'
        }
        self.wfile.write(json.dumps(response).encode())
