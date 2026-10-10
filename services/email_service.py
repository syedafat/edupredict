"""Provider-agnostic SMTP delivery for account recovery email."""
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import parseaddr

from flask import current_app
import requests


class EmailService:
    @staticmethod
    def send_password_reset(recipient, reset_url):
        config = current_app.config
        sender = config.get("MAIL_DEFAULT_SENDER", "")
        recipient_address = parseaddr(recipient)[1]
        sender_address = parseaddr(sender)[1]
        if not recipient_address or "@" not in recipient_address or not sender_address:
            raise ValueError("Mail sender or recipient is invalid.")
        body = (
            "A password reset was requested for your EduPredict account.\n\n"
            f"Use this one-time link within {config.get('PASSWORD_RESET_TOKEN_MINUTES', 30)} minutes:\n"
            f"{reset_url}\n\n"
            "If you did not request this change, you can ignore this email."
        )

        provider = config.get("MAIL_PROVIDER", "smtp").lower()
        if provider == "resend":
            api_key = config.get("RESEND_API_KEY")
            if not api_key:
                raise RuntimeError("Resend is not configured.")
            response = requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "from": sender,
                    "to": [recipient_address],
                    "subject": "EduPredict password reset",
                    "text": body,
                },
                timeout=config.get("MAIL_TIMEOUT", 10),
            )
            response.raise_for_status()
            return
        if provider != "smtp":
            raise RuntimeError("Unsupported email provider.")
        if not config.get("MAIL_SERVER"):
            raise RuntimeError("SMTP is not configured.")
        if bool(config.get("MAIL_USERNAME")) != bool(config.get("MAIL_PASSWORD")):
            raise RuntimeError("SMTP authentication settings are incomplete.")

        message = EmailMessage()
        message["Subject"] = "EduPredict password reset"
        message["From"] = sender
        message["To"] = recipient_address
        message.set_content(body)

        with smtplib.SMTP(
            config["MAIL_SERVER"],
            config.get("MAIL_PORT", 587),
            timeout=config.get("MAIL_TIMEOUT", 10),
        ) as smtp:
            smtp.ehlo()
            if config.get("MAIL_USE_TLS"):
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if config.get("MAIL_USERNAME"):
                smtp.login(config["MAIL_USERNAME"], config["MAIL_PASSWORD"])
            smtp.send_message(message)
