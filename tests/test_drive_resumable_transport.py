"""Real loopback HTTP response: Drive's 308 is upload progress, not a redirect."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'server'))
from vault_drive import GoogleDriveAdapter


class ResumableTransportTests(unittest.TestCase):
    def test_308_without_location_reaches_the_upload_handler(self):
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_PUT(self):
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(308)
                self.send_header('Range','bytes=0-3')
                self.send_header('Content-Length','0')
                self.end_headers()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with patch('googleapiclient.discovery.build',side_effect=lambda *args,**kwargs:kwargs['http']):
                authorized=GoogleDriveAdapter._build(object())
            self.assertEqual(authorized.http.timeout,30)
            authorized.http.proxy_info=None
            response,body=authorized.http.request(f'http://127.0.0.1:{server.server_port}/upload',method='PUT',body=b'data')
            self.assertEqual(response.status,308)
            self.assertEqual(response['range'],'bytes=0-3')
            self.assertEqual(body,b'')
        finally:
            server.shutdown();server.server_close();thread.join()
