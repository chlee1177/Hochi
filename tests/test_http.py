import importlib.util
import json
from pathlib import Path
import sys
import threading
import unittest
from http.server import HTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('image_http', ROOT / 'image-summary/backend/server.py')
image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image)


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(('127.0.0.1', 0), image.ImageHandler)
        cls.address = f'http://127.0.0.1:{cls.server.server_port}'
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_readiness_returns_ai_availability(self):
        with urlopen(self.address + '/api/status') as response:
            status = json.load(response)
        self.assertTrue(status['ok'])
        self.assertIsInstance(status['ai'], bool)

    def test_invalid_image_has_meaningful_response(self):
        request = Request(self.address + '/api/analyze', data=b'{"mime":"image/png","data":"aGVsbG8="}', headers={'Content-Type': 'application/json'})
        with self.assertRaises(HTTPError) as error: urlopen(request)
        self.assertEqual(error.exception.code, 400)
        self.assertIn('이미지', json.load(error.exception)['error'])

    def test_foreign_origin_rejected(self):
        request = Request(self.address + '/api/analyze', data=b'{}', headers={'Content-Type': 'application/json', 'Origin': 'https://unrelated.example'})
        with self.assertRaises(HTTPError) as error: urlopen(request)
        self.assertEqual(error.exception.code, 403)


if __name__ == '__main__': unittest.main()
