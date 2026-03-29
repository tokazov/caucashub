"""Утилита отправки email через Gmail SMTP (aiosmtplib)."""
import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.config import settings
import logging

logger = logging.getLogger(__name__)


async def send_reset_code(to_email: str, code: str) -> bool:
    """Отправляет письмо с кодом сброса пароля. Возвращает True если успешно."""
    if not settings.SMTP_USER or not settings.SMTP_PASS:
        logger.warning("SMTP не настроен — письмо не отправлено")
        return False

    subject = "CaucasHub — код для сброса пароля"

    html_body = f"""
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f0f2f5;font-family:Arial,sans-serif">
  <table width="100%" cellpadding="0" cellspacing="0">
    <tr><td align="center" style="padding:40px 16px">
      <table width="480" cellpadding="0" cellspacing="0"
             style="background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,.08)">

        <!-- Header -->
        <tr><td style="background:#1a1a2e;padding:24px;text-align:center">
          <span style="color:#fff;font-weight:900;font-size:24px">
            Caucas<span style="color:#f7b731">Hub</span>
          </span>
          <span style="color:#888;font-size:13px;margin-left:4px">.ge</span>
        </td></tr>

        <!-- Body -->
        <tr><td style="padding:32px 28px">
          <p style="margin:0 0 16px;font-size:16px;color:#333">
            Вы запросили сброс пароля на <strong>CaucasHub.ge</strong>
          </p>
          <p style="margin:0 0 24px;font-size:14px;color:#666">
            Введите этот код на сайте:
          </p>

          <!-- Code box -->
          <div style="background:#f8f9fa;border:2px solid #f7b731;border-radius:12px;
                      padding:20px;text-align:center;margin-bottom:24px">
            <div style="font-size:42px;font-weight:900;letter-spacing:12px;color:#1a1a2e">
              {code}
            </div>
          </div>

          <p style="margin:0 0 8px;font-size:13px;color:#888">
            ⏱ Код действует <strong>15 минут</strong>
          </p>
          <p style="margin:0;font-size:13px;color:#aaa">
            Если вы не запрашивали сброс пароля — просто проигнорируйте это письмо.
          </p>
        </td></tr>

        <!-- Footer -->
        <tr><td style="background:#f8f9fa;padding:16px 28px;text-align:center">
          <p style="margin:0;font-size:12px;color:#aaa">
            © 2026 CaucasHub.ge — Биржа грузов и транспорта Кавказа
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>
"""

    text_body = f"Ваш код для сброса пароля на CaucasHub.ge: {code}\n\nКод действует 15 минут."

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = settings.EMAIL_FROM
    msg["To"]      = to_email
    msg.attach(MIMEText(text_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html",  "utf-8"))

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASS,
            start_tls=True,
        )
        logger.info(f"Reset code sent to {to_email}")
        return True
    except Exception as e:
        logger.error(f"SMTP error sending to {to_email}: {e}")
        return False
