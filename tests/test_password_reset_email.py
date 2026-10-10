from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock, patch

from flask import Flask

from models import mongo
from routes.auth_routes import hash_reset_token
from services.email_service import EmailService
from werkzeug.security import generate_password_hash


def _configure_test_mail(app):
    app.config.update(
        MAIL_SERVER="smtp.example.test",
        MAIL_PORT=587,
        MAIL_USERNAME="synthetic-mail-user",
        MAIL_PASSWORD="synthetic-mail-password",
        MAIL_USE_TLS=True,
        MAIL_DEFAULT_SENDER="EduPredict <noreply@example.test>",
        MAIL_TIMEOUT=5,
        PASSWORD_RESET_BASE_URL="https://portal.example.test",
        PASSWORD_RESET_EXPOSE_LINK=False,
    )


def _insert_user(email="student@example.edu"):
    mongo.db.users.delete_many({})
    return mongo.db.users.insert_one({
        "name": "Test Student",
        "email": email,
        "password_hash": generate_password_hash("InitialSecret123"),
        "role": "student",
        "status": "approved",
    }).inserted_id


def test_password_reset_sends_tls_email_and_stores_only_token_hash(test_app, client, monkeypatch):
    _configure_test_mail(test_app)
    _insert_user()
    sent = []
    monkeypatch.setattr(EmailService, "send_password_reset", lambda recipient, url: sent.append((recipient, url)))

    response = client.post(
        "/auth/forgot-password",
        data={"email": "student@example.edu"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"If an account exists with this email address" in response.data
    assert b"reset-password?token=" not in response.data
    assert len(sent) == 1
    assert sent[0][0] == "student@example.edu"
    parsed = urlsplit(sent[0][1])
    token = parse_qs(parsed.query)["token"][0]
    assert parsed.scheme == "https"
    assert parsed.netloc == "portal.example.test"
    user = mongo.db.users.find_one({"email": "student@example.edu"})
    expiry = user["reset_token_expiry"]
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    assert user["reset_token_hash"] == hash_reset_token(token)
    assert expiry > datetime.now(timezone.utc)
    assert "reset_token" not in user


def test_smtp_sender_uses_starttls_and_sends_plain_text_reset(test_app):
    _configure_test_mail(test_app)
    smtp = Mock()
    manager = Mock()
    manager.__enter__ = Mock(return_value=smtp)
    manager.__exit__ = Mock(return_value=False)

    with test_app.app_context(), patch("services.email_service.smtplib.SMTP", return_value=manager) as smtp_factory:
        EmailService.send_password_reset("student@example.edu", "https://portal.example.test/auth/reset-password?token=synthetic-token")

    smtp_factory.assert_called_once_with("smtp.example.test", 587, timeout=5)
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("synthetic-mail-user", "synthetic-mail-password")
    message = smtp.send_message.call_args.args[0]
    assert message["To"] == "student@example.edu"
    assert "synthetic-token" in message.get_content()
    assert message.get_content_subtype() == "plain"


def test_resend_sender_uses_runtime_api_key_and_sends_reset_email(test_app):
    _configure_test_mail(test_app)
    test_app.config.update(MAIL_PROVIDER="resend", RESEND_API_KEY="synthetic-resend-key")
    response = Mock()

    with test_app.app_context(), patch("services.email_service.requests.post", return_value=response) as post:
        EmailService.send_password_reset(
            "student@example.edu",
            "https://portal.example.test/auth/reset-password?token=synthetic-token",
        )

    post.assert_called_once()
    args, kwargs = post.call_args
    assert args == ("https://api.resend.com/emails",)
    assert kwargs["headers"]["Authorization"] == "Bearer synthetic-resend-key"
    assert kwargs["json"]["to"] == ["student@example.edu"]
    assert "synthetic-token" in kwargs["json"]["text"]
    assert kwargs["timeout"] == 5
    response.raise_for_status.assert_called_once()


def test_email_delivery_failure_is_generic_and_invalidates_its_token(test_app, client, monkeypatch, caplog):
    _configure_test_mail(test_app)
    _insert_user()

    def fail_delivery(_recipient, _url):
        raise RuntimeError("synthetic smtp credential detail")

    monkeypatch.setattr(EmailService, "send_password_reset", fail_delivery)
    response = client.post(
        "/auth/forgot-password",
        data={"email": "student@example.edu"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"If an account exists with this email address" in response.data
    assert b"synthetic smtp credential detail" not in response.data
    assert "synthetic smtp credential detail" not in caplog.text
    user = mongo.db.users.find_one({"email": "student@example.edu"})
    assert "reset_token_hash" not in user
    assert "reset_token_expiry" not in user
