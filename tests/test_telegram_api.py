"""Перевіряє HTTP-клієнт проти локального підробленого сервера Telegram."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from appbot.telegram_api import TelegramAPI, TelegramError, TelegramNetworkError


class FakeTelegram(BaseHTTPRequestHandler):
    requests = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeTelegram.requests.append((self.path, body))
        if self.path.endswith("/editMessageText"):
            payload, code = {"ok": False, "error_code": 400,
                             "description": "Bad Request: message is not modified"}, 400
        elif self.path.endswith("/getUpdates"):
            payload, code = {"ok": True, "result": [{"update_id": 7}]}, 200
        else:
            payload, code = {"ok": True, "result": {"message_id": 1}}, 200
        data = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class TelegramAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeTelegram)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.api = TelegramAPI("TOKEN123", base_url=f"http://127.0.0.1:{cls.server.server_port}")

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_send_message_payload(self):
        self.api.send_message(5, "Привіт", {"inline_keyboard": []})
        path, body = FakeTelegram.requests[-1]
        self.assertEqual(path, "/botTOKEN123/sendMessage")
        self.assertEqual((body["chat_id"], body["text"], body["parse_mode"]), (5, "Привіт", "HTML"))

    def test_get_updates(self):
        self.assertEqual(self.api.get_updates(0, poll_timeout=1), [{"update_id": 7}])
        self.assertEqual(FakeTelegram.requests[-1][1]["allowed_updates"], ["message", "callback_query"])

    def test_not_modified_error(self):
        with self.assertRaises(TelegramError) as ctx:
            self.api.edit_message_text(1, 2, "x")
        self.assertTrue(ctx.exception.not_modified)

    def test_network_error_does_not_leak_token(self):
        api = TelegramAPI("SECRET_TOKEN", base_url="http://127.0.0.1:1", timeout=1)
        with self.assertRaises(TelegramNetworkError) as ctx:
            api.send_message(1, "x")
        self.assertNotIn("SECRET_TOKEN", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
