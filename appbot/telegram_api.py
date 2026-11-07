"""Мінімальний клієнт Telegram Bot API на urllib (без сторонніх залежностей).

Токен ніколи не потрапляє в логи: URL не логується, помилки містять лише опис від Telegram.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional


class TelegramError(Exception):
    def __init__(self, description: str, code: Optional[int] = None, retry_after: int = 0):
        super().__init__(description)
        self.description = description
        self.code = code
        self.retry_after = retry_after

    @property
    def not_modified(self) -> bool:
        return "message is not modified" in self.description.lower()


class TelegramNetworkError(Exception):
    pass


class TelegramAPI:
    def __init__(self, token: str, base_url: str = "https://api.telegram.org", timeout: int = 40):
        self._url = f"{base_url}/bot{token}/"
        self._timeout = timeout
        # macOS Python installs may not automatically use the system CA bundle.
        # Forma uses this same bundle; SSL_CERT_FILE can override it when needed.
        cafile = os.environ.get("SSL_CERT_FILE")
        system_ca = Path("/etc/ssl/cert.pem")
        if not cafile and sys.platform == "darwin" and system_ca.is_file():
            cafile = str(system_ca)
        self._ssl_context = ssl.create_default_context(cafile=cafile)

    def call(self, method: str, params: Optional[dict] = None, timeout: Optional[int] = None) -> Any:
        body = json.dumps(params or {}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self._url + method, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(
                req, timeout=timeout or self._timeout, context=self._ssl_context
            ) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
            except Exception:
                raise TelegramError(f"HTTP {exc.code}", exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise TelegramNetworkError(type(exc).__name__) from None
        if not payload.get("ok"):
            retry = (payload.get("parameters") or {}).get("retry_after", 0)
            raise TelegramError(payload.get("description", "unknown error"), payload.get("error_code"), retry)
        return payload["result"]

    # -- зручні обгортки ------------------------------------------------
    def get_updates(self, offset: int, poll_timeout: int = 30) -> list:
        return self.call(
            "getUpdates",
            {"offset": offset, "timeout": poll_timeout, "allowed_updates": ["message", "callback_query"]},
            timeout=poll_timeout + 10,
        )

    def send_message(self, chat_id: int, text: str, reply_markup: Optional[dict] = None) -> dict:
        params: dict = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        if reply_markup:
            params["reply_markup"] = reply_markup
        return self.call("sendMessage", params)

    def edit_message_text(self, chat_id: int, message_id: int, text: str, reply_markup: Optional[dict] = None) -> Any:
        params: dict = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": "HTML",
            "link_preview_options": {"is_disabled": True},
        }
        if reply_markup:
            params["reply_markup"] = reply_markup
        return self.call("editMessageText", params)

    def remove_keyboard(self, chat_id: int, message_id: int) -> Any:
        return self.call(
            "editMessageReplyMarkup",
            {"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []}},
        )

    def answer_callback(self, callback_id: str, text: Optional[str] = None, alert: bool = False) -> Any:
        params: dict = {"callback_query_id": callback_id}
        if text:
            params["text"] = text
            params["show_alert"] = alert
        return self.call("answerCallbackQuery", params)

    def set_commands(self, commands: list) -> Any:
        return self.call("setMyCommands", {"commands": commands})


def backoff_sleep(attempt: int) -> None:
    time.sleep(min(30, 2 ** min(attempt, 5)))
