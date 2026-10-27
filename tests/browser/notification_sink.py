"""Test-only HTTP sink for actual Telegram/email adapters; never opens a socket."""
from collections import defaultdict, deque
from contextlib import contextmanager
import json
from unittest.mock import patch

import httpx


class NotificationProviderSink:
    def __init__(self):
        self.telegram_ids = set()
        self.emails = set()
        self.attempts = []
        self.unexpected = []
        self.outcomes = defaultdict(deque)

    def allow(self, *, telegram_ids=(), emails=()):
        self.telegram_ids.update(str(value) for value in telegram_ids)
        self.emails.update(emails)

    def fail_next(self, channel, recipient, status=503):
        self.outcomes[(channel, str(recipient))].append(status)

    def handle(self, request):
        host = request.url.host
        try:
            payload = json.loads(request.content)
        except (ValueError, UnicodeDecodeError):
            payload = {}
        channel = recipient = None
        if host == "api.telegram.org" and request.url.path.endswith("/sendMessage"):
            channel = "telegram"
            recipient = str(payload.get("chat_id", ""))
            allowed = recipient in self.telegram_ids
        elif host in {"api.brevo.com", "api.resend.com"}:
            channel = "email"
            recipients = payload.get("to") or []
            if host == "api.brevo.com":
                recipients = [item.get("email") for item in recipients]
            recipient = recipients[0] if len(recipients) == 1 else None
            allowed = recipient in self.emails
        else:
            allowed = False
        if not allowed:
            # Deliberately omit URL paths, query strings and auth headers:
            # Telegram tokens are embedded in its URL path.
            detail = {"host": host, "channel": channel, "recipient": recipient}
            self.unexpected.append(detail)
            raise AssertionError("Unexpected provider/recipient in isolated notification fixture")
        status = self.outcomes[(channel, str(recipient))].popleft() if self.outcomes[(channel, str(recipient))] else 200
        self.attempts.append({
            "channel": channel, "recipient": recipient, "status": status,
            "provider_id": (str(len(self.attempts) + 1) if channel == "telegram" else "isolated-" + str(len(self.attempts) + 1)) if status < 400 else None,
            "text": payload.get("text"),
            "subject": payload.get("subject"),
            "html": payload.get("htmlContent", payload.get("html")),
        })
        if status >= 400:
            return httpx.Response(status, json={"ok": False, "message": "isolated provider failure"})
        if channel == "telegram":
            return httpx.Response(200, json={"ok": True, "result": {"message_id": len(self.attempts)}})
        return httpx.Response(200, json={"id": "isolated-" + str(len(self.attempts)), "messageId": "isolated-" + str(len(self.attempts))})

    @contextmanager
    def intercept_httpx(self):
        """Keep explicit ASGI transports; force every other HTTPX client into the sink."""
        original_init = httpx.AsyncClient.__init__
        transport = httpx.MockTransport(self.handle)

        def isolated_init(client, *args, **kwargs):
            if not isinstance(kwargs.get("transport"), httpx.ASGITransport):
                kwargs["transport"] = transport
            return original_init(client, *args, **kwargs)

        with patch.object(httpx.AsyncClient, "__init__", isolated_init):
            yield self
