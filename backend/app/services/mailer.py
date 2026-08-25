"""Outbound email delivery (password reset / email verification).

`ConsoleMailer` is the development default: it logs that a message WOULD be
delivered and the secure link path — never any credential. `SmtpMailer` uses
environment-configured SMTP. Actual deliverability is a deployment concern
and is explicitly NOT PROVEN until exercised against a real provider.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from ..config import settings

logger = logging.getLogger("recycle.mail")


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class ConsoleMailer:
    def send(self, to: str, subject: str, body: str) -> None:
        logger.info("[MAIL:console] to=%s subject=%r (delivery not configured)", to, subject)


class SmtpMailer:
    def send(self, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["From"] = settings.smtp_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        assert settings.smtp_host  # guarded by validate_production / factory
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password or "")
            smtp.send_message(msg)


def get_mailer() -> Mailer:
    if settings.email_provider == "smtp" and settings.smtp_host:
        return SmtpMailer()
    return ConsoleMailer()
