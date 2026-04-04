"""Отправка email через Brevo (приоритет) или Resend/SMTP (fallback)."""
import logging
from app.config import settings

logger = logging.getLogger(__name__)


# ── Brevo HTTP API ────────────────────────────────────────────────
async def _send_via_brevo(to_email: str, code: str) -> bool:
    try:
        import httpx
        headers = {
            "api-key": settings.BREVO_API_KEY,
            "Content-Type": "application/json",
        }
        payload = {
            "sender": {"name": "CaucasHub", "email": "noreply@caucashub.ge"},
            "to": [{"email": to_email}],
            "subject": "CaucasHub — код для сброса пароля",
            "htmlContent": _reset_html(code),
            "textContent": f"Ваш код для сброса пароля: {code}\n\nКод действует 15 минут.\n\ncaucashub.ge",
        }
        async with httpx.AsyncClient() as client:
            r = await client.post("https://api.brevo.com/v3/smtp/email", json=payload, headers=headers, timeout=10)
        if r.status_code == 201:
            logger.info(f"[Brevo] Sent to {to_email}")
            return True
        logger.error(f"[Brevo] Error {r.status_code}: {r.text}")
        return False
    except Exception as e:
        logger.error(f"[Brevo] Exception: {e}")
        return False

# ── HTML шаблон письма ────────────────────────────────────────────
def _reset_html(code: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:40px 16px">
      <table width="480" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.08)">
        <tr><td style="background:#1a1a2e;padding:24px;text-align:center">
          <span style="color:#fff;font-weight:900;font-size:24px">Caucas<span style="color:#f7b731">Hub</span></span>
          <span style="color:#888;font-size:13px;margin-left:4px">.ge</span>
        </td></tr>
        <tr><td style="padding:32px 28px">
          <p style="margin:0 0 16px;font-size:16px;color:#333">
            Вы запросили сброс пароля на <strong>CaucasHub.ge</strong>
          </p>
          <p style="margin:0 0 24px;font-size:14px;color:#666">Ваш код подтверждения:</p>
          <div style="background:#f8f9fa;border:2px solid #f7b731;border-radius:12px;
                      padding:24px;text-align:center;margin-bottom:24px">
            <div style="font-size:44px;font-weight:900;letter-spacing:14px;color:#1a1a2e">
              {code}
            </div>
          </div>
          <p style="margin:0 0 8px;font-size:13px;color:#888">⏱ Код действует <strong>15 минут</strong></p>
          <p style="margin:0;font-size:13px;color:#aaa">
            Если вы не запрашивали сброс — просто проигнорируйте это письмо.
          </p>
        </td></tr>
        <tr><td style="background:#f8f9fa;padding:16px 28px;text-align:center">
          <p style="margin:0;font-size:12px;color:#aaa">© 2026 CaucasHub.ge — Биржа грузов Кавказа</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


# ── Resend ────────────────────────────────────────────────────────
async def _send_via_resend(to_email: str, code: str) -> bool:
    try:
        import resend
        resend.api_key = settings.RESEND_API_KEY
        params = {
            "from": settings.EMAIL_FROM,
            "to": [to_email],
            "subject": "CaucasHub — код для сброса пароля",
            "html": _reset_html(code),
            "text": f"Ваш код для сброса пароля: {code}\n\nКод действует 15 минут.\n\ncaucashub.ge",
        }
        r = resend.Emails.send(params)
        logger.info(f"[Resend] Sent to {to_email}, id={r.get('id')}")
        return True
    except Exception as e:
        logger.error(f"[Resend] Error: {e}")
        return False


# ── Gmail SMTP fallback ───────────────────────────────────────────
async def _send_via_smtp(to_email: str, code: str) -> bool:
    if not settings.SMTP_USER or not settings.SMTP_PASS:
        return False
    try:
        import aiosmtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "CaucasHub — код для сброса пароля"
        msg["From"]    = settings.EMAIL_FROM
        msg["To"]      = to_email
        msg.attach(MIMEText(f"Ваш код: {code}\n\nКод действует 15 минут.", "plain", "utf-8"))
        msg.attach(MIMEText(_reset_html(code), "html", "utf-8"))

        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASS,
            start_tls=True,
        )
        logger.info(f"[SMTP] Sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"[SMTP] Error: {e}")
        return False


# ── Публичная функция ─────────────────────────────────────────────
async def send_reset_code(to_email: str, code: str) -> bool:
    """Отправляет код сброса. Brevo → Resend → SMTP."""
    if settings.BREVO_API_KEY:
        return await _send_via_brevo(to_email, code)
    if settings.RESEND_API_KEY:
        return await _send_via_resend(to_email, code)
    if settings.SMTP_USER and settings.SMTP_PASS:
        return await _send_via_smtp(to_email, code)
    logger.warning("Email не настроен")
    return False
