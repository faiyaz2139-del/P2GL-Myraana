"""Outbound mail. The default is a log so a missing provider does not drop the link.

EMAIL_PROVIDER selects log (default), off, smtp, resend, postmark, or ses.
An unknown value falls back to log. Live providers do not log the message body.
"""
import logging
import os
import smtplib
from email.message import EmailMessage


log = logging.getLogger("myraana.mail")

_KNOWN = {"log", "off", "smtp", "resend", "postmark", "ses"}
_LIVE = {"smtp", "resend", "postmark", "ses"}


class MailError(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def email_provider():
    value = os.environ.get("EMAIL_PROVIDER", "log").strip().lower() or "log"
    if value not in _KNOWN:
        return "log"
    return value


def email_is_live():
    return email_provider() in _LIVE


def email_from_address():
    return os.environ.get("EMAIL_FROM", "Myraana <noreply@localhost>").strip() or "Myraana <noreply@localhost>"


def public_base(request=None):
    configured = os.environ.get("PUBLIC_APP_URL", "").strip().rstrip("/")
    if configured:
        return configured
    if request is None:
        return ""
    proto = request.headers.get("x-forwarded-proto") or request.url.scheme
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc
    return f"{proto}://{host}".rstrip("/")


def send_email(to, subject, text):
    provider = email_provider()
    if provider == "off":
        log.info("email not sent provider=off to=%s subject=%s", to, subject)
        return {"delivered": False, "provider": "off"}
    if provider == "log":
        log.info("email logged to=%s subject=%s\n%s", to, subject, text)
        return {"delivered": False, "provider": "log"}
    if provider == "smtp":
        _smtp(to, subject, text)
    elif provider == "resend":
        _resend(to, subject, text)
    elif provider == "postmark":
        _postmark(to, subject, text)
    else:
        _ses(to, subject, text)
    return {"delivered": True, "provider": provider}


def _smtp(to, subject, text):
    host = os.environ.get("SMTP_HOST", "").strip()
    if not host:
        raise MailError("SMTP is not configured.")
    port = int(os.environ.get("SMTP_PORT", "587") or "587")
    username = os.environ.get("SMTP_USERNAME", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    use_tls = os.environ.get("SMTP_TLS", "true").strip().lower() not in {"0", "false", "off", "no"}
    message = EmailMessage()
    message["From"] = email_from_address()
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    try:
        with smtplib.SMTP(host, port, timeout=20) as smtp:
            if use_tls:
                smtp.starttls()
            if username:
                smtp.login(username, password)
            smtp.send_message(message)
    except MailError:
        raise
    except Exception as error:
        raise MailError("Email could not be sent.") from error


def _resend(to, subject, text):
    key = os.environ.get("RESEND_API_KEY", "").strip()
    if not key:
        raise MailError("Resend is not configured.")
    import httpx

    try:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {key}"},
            json={"from": email_from_address(), "to": [to], "subject": subject, "text": text},
            timeout=20,
        )
    except Exception as error:
        raise MailError("Email could not be sent.") from error
    if response.status_code >= 400:
        raise MailError("Resend rejected the message.")


def _postmark(to, subject, text):
    token = os.environ.get("POSTMARK_SERVER_TOKEN", "").strip()
    if not token:
        raise MailError("Postmark is not configured.")
    import httpx

    try:
        response = httpx.post(
            "https://api.postmarkapp.com/email",
            headers={"X-Postmark-Server-Token": token, "Accept": "application/json"},
            json={
                "From": email_from_address(),
                "To": to,
                "Subject": subject,
                "TextBody": text,
            },
            timeout=20,
        )
    except Exception as error:
        raise MailError("Email could not be sent.") from error
    if response.status_code >= 400:
        raise MailError("Postmark rejected the message.")


def _ses(to, subject, text):
    region = os.environ.get("AWS_SES_REGION", "").strip()
    if not region:
        raise MailError("SES is not configured.")
    try:
        import boto3
    except ImportError as error:
        raise MailError("SES client is not installed.") from error
    try:
        client = boto3.client("ses", region_name=region)
        client.send_email(
            Source=email_from_address(),
            Destination={"ToAddresses": [to]},
            Message={
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Text": {"Data": text, "Charset": "UTF-8"}},
            },
        )
    except MailError:
        raise
    except Exception as error:
        raise MailError("Email could not be sent.") from error
