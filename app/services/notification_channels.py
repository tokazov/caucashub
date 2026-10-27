"""Provider adapters. No credentials or recipient addresses enter logs/errors."""
from dataclasses import dataclass
import os
import logging

class _RedactBotURL(logging.Filter):
    def filter(self, record):
        message = record.getMessage()
        if "api.telegram.org/bot" in message:
            record.msg = re.sub(r"(https://api\.telegram\.org/bot)[^/\s]+", r"\1[redacted]", message)
            record.args = ()
        return True

import re
from uuid import UUID, uuid4, uuid5, NAMESPACE_URL
import httpx
logging.getLogger("httpx").addFilter(_RedactBotURL())

@dataclass(frozen=True)
class DeliveryResult:
    status: str
    provider_id: str | None = None
    error: str | None = None
    retry_after: int | None = None

def _env(*names):
    return next((os.getenv(name, "").strip() for name in names if os.getenv(name, "").strip()), "")

def _key(value):
    text = str(value or uuid4())
    try:
        return str(UUID(text))
    except ValueError:
        return str(uuid5(NAMESPACE_URL, "caucashub-notification:" + text))

def _json(response):
    try:
        value = response.json()
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}

def _retry_after(response, body=None):
    value = response.headers.get("Retry-After")
    if value is None and body:
        value = body.get("parameters", {}).get("retry_after")
    try:
        return min(1800, max(1, int(value)))
    except (TypeError, ValueError):
        return 60

async def send_email(to, subject, html, *, idempotency_key=None):
    if not isinstance(to, str) or not re.fullmatch(r"[^@\s\r\n]+@[^@\s\r\n]+\.[^@\s\r\n]+", to):
        return DeliveryResult("skipped", error="invalid_email")
    brevo, resend = _env("BREVO_API_KEY"), _env("RESEND_API_KEY")
    if not brevo and not resend:
        return DeliveryResult("skipped", error="email_not_configured")
    key = _key(idempotency_key)
    sender = _env("NOTIFICATION_FROM_EMAIL") or "noreply@caucashub.ge"
    name = "CaucasHub"
    async with httpx.AsyncClient(timeout=12.0) as client:
        if brevo:
            try:
                response = await client.post("https://api.brevo.com/v3/smtp/email",
                    headers={"api-key": brevo, "Content-Type": "application/json"},
                    json={"sender": {"name": name, "email": sender}, "to": [{"email": to}],
                          "subject": subject, "htmlContent": html,
                          "headers": {"idempotencyKey": key}})
            except httpx.TransportError:
                # The provider may already have accepted it. Never cross-provider retry.
                return DeliveryResult("unknown", error="brevo_transport_uncertain")
            body = _json(response)
            if 200 <= response.status_code < 300:
                identifier = body.get("messageId")
                if isinstance(identifier, str) and identifier:
                    return DeliveryResult("sent", provider_id=identifier[:250])
                return DeliveryResult("unknown", error="brevo_invalid_success")
            if body.get("code") == "duplicate_parameter":
                return DeliveryResult("sent", error="brevo_idempotent_replay")
            if response.status_code == 429:
                return DeliveryResult("retry", error="brevo_rate_limit", retry_after=_retry_after(response, body))
            if response.status_code >= 500 or response.status_code in (408, 409):
                return DeliveryResult("unknown", error="brevo_http_" + str(response.status_code))
            if not 400 <= response.status_code < 500 or not resend:
                return DeliveryResult("failed", error="brevo_http_" + str(response.status_code))
            # Only a definite rejection can safely switch to the configured fallback.
        try:
            response = await client.post("https://api.resend.com/emails",
                headers={"Authorization": "Bearer " + resend, "Content-Type": "application/json",
                         "Idempotency-Key": key},
                json={"from": f"{name} <{sender}>", "to": [to], "subject": subject, "html": html})
        except httpx.TransportError:
            return DeliveryResult("unknown", error="resend_transport_uncertain")
        body = _json(response)
        if 200 <= response.status_code < 300:
            identifier = body.get("id")
            if isinstance(identifier, str) and identifier:
                return DeliveryResult("sent", provider_id=identifier[:250])
            return DeliveryResult("unknown", error="resend_invalid_success")
        if response.status_code == 429:
            return DeliveryResult("retry", error="resend_rate_limit", retry_after=_retry_after(response, body))
        if response.status_code >= 500 or response.status_code in (408, 409):
            return DeliveryResult("unknown", error="resend_http_" + str(response.status_code))
        return DeliveryResult("failed", error="resend_http_" + str(response.status_code))

async def send_telegram(chat_id, text, *, idempotency_key=None):
    del idempotency_key  # Telegram sendMessage has no client idempotency field.
    if not isinstance(chat_id, (str, int)) or isinstance(chat_id, bool):
        return DeliveryResult("skipped", error="telegram_not_linked")
    chat = str(chat_id).strip()
    if not re.fullmatch(r"-?[1-9]\d{0,19}", chat):
        return DeliveryResult("skipped", error="telegram_not_linked")
    token = _env("CAUCASHUB_TG_BOT_TOKEN", "TG_BOT_TOKEN", "TELEGRAM_BOT_TOKEN")
    if not token:
        return DeliveryResult("skipped", error="telegram_not_configured")
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            response = await client.post("https://api.telegram.org/bot" + token + "/sendMessage",
                json={"chat_id": chat, "text": str(text)[:4000], "disable_web_page_preview": True})
    except httpx.TransportError:
        return DeliveryResult("unknown", error="telegram_transport_uncertain")
    body = _json(response)
    if response.status_code == 200 and body.get("ok") is True:
        identifier = (body.get("result") or {}).get("message_id")
        if isinstance(identifier, int) and not isinstance(identifier, bool):
            return DeliveryResult("sent", provider_id=str(identifier))
        return DeliveryResult("unknown", error="telegram_invalid_success")
    error_code = body.get("error_code", response.status_code)
    if response.status_code == 429 or error_code == 429:
        return DeliveryResult("retry", error="telegram_rate_limit", retry_after=_retry_after(response, body))
    if response.status_code >= 500 or (isinstance(error_code, int) and error_code >= 500):
        return DeliveryResult("unknown", error="telegram_server_uncertain")
    return DeliveryResult("failed", error="telegram_http_" + str(response.status_code))

async def configuration_health():
    """Read-only provider probes; never send a test message or expose identities."""
    result = {"email": "not_configured", "telegram": "not_configured"}
    token = _env("CAUCASHUB_TG_BOT_TOKEN", "TG_BOT_TOKEN", "TELEGRAM_BOT_TOKEN")
    brevo, resend = _env("BREVO_API_KEY"), _env("RESEND_API_KEY")
    async with httpx.AsyncClient(timeout=8.0) as client:
        if token:
            try:
                response = await client.get("https://api.telegram.org/bot" + token + "/getMe")
                result["telegram"] = "ready" if response.status_code == 200 and _json(response).get("ok") is True else "unavailable"
            except httpx.TransportError:
                result["telegram"] = "unreachable"
        if brevo:
            try:
                response = await client.get("https://api.brevo.com/v3/account", headers={"api-key": brevo})
                result["email"] = "ready" if response.status_code == 200 else "unavailable"
            except httpx.TransportError:
                result["email"] = "unreachable"
        elif resend:
            # Sending-only keys may be unable to list domains; this is not a send failure.
            try:
                response = await client.get("https://api.resend.com/domains",
                                            headers={"Authorization": "Bearer " + resend})
                result["email"] = "ready" if response.status_code == 200 else "configured"
            except httpx.TransportError:
                result["email"] = "unreachable"
    return result
