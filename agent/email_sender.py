"""Provider-agnostic email sending. Pick the provider with EMAIL_PROVIDER (resend or smtp)."""

import os
import smtplib
from email.message import EmailMessage

import httpx


PROVIDER_SETTINGS = {
    "resend": ["RESEND_API_KEY"],
    "smtp": ["SMTP_HOST"],
}


def email_provider() -> str:
    return (os.environ.get("EMAIL_PROVIDER") or "resend").lower()


def required_settings() -> list[str]:
    """Settings the configured provider needs, so callers can check them before doing any work."""
    provider = email_provider()
    if provider not in PROVIDER_SETTINGS:
        raise SystemExit(f"Unknown EMAIL_PROVIDER {provider!r}; use 'resend' or 'smtp'.")
    return PROVIDER_SETTINGS[provider]


def send_email(to: list[str], subject: str, text: str, html: str) -> None:
    provider = email_provider()
    if provider == "resend":
        _send_resend(to, subject, text, html)
    elif provider == "smtp":
        _send_smtp(to, subject, text, html)
    else:
        raise ValueError(f"Unknown EMAIL_PROVIDER {provider!r}; use 'resend' or 'smtp'.")


def _send_resend(to: list[str], subject: str, text: str, html: str) -> None:
    response = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY'].strip()}"},
        json={
            "from": os.environ.get("EMAIL_FROM") or "ApiAgentService2 Agent <onboarding@resend.dev>",
            "to": to,
            "subject": subject,
            "text": text,
            "html": html,
        },
        timeout=30,
    )
    response.raise_for_status()


def _send_smtp(to: list[str], subject: str, text: str, html: str) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT") or 587)
    username = os.environ.get("SMTP_USERNAME")
    password = os.environ.get("SMTP_PASSWORD")

    message = EmailMessage()
    message["From"] = os.environ.get("EMAIL_FROM") or username
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    # Port 465 expects TLS from the start; other ports (usually 587) upgrade with STARTTLS.
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        server.starttls()
    with server:
        if username and password:
            server.login(username, password)
        server.send_message(message)
