import pytest
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from unittest.mock import Mock, patch
from config import _validate_production_mongo_uri
from flask import Flask
from scripts import backup_mongodb
from routes.monitoring_routes import health
from seed_data import get_database, seed_demo_environment


def test_production_mongo_validation_rejects_local_fallback():
    with pytest.raises(RuntimeError):
        _validate_production_mongo_uri(
            "mongodb://synthetic-user:synthetic-password@localhost:27017/production?tls=true"
        )


def test_production_mongo_validation_accepts_authenticated_tls_uri():
    _validate_production_mongo_uri(
        "mongodb://synthetic-user:synthetic-password@db.example.test:27017/production?tls=true"
    )


def test_demo_seed_requires_explicit_opt_in_before_database_access(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("ALLOW_DEMO_SEED", raising=False)
    monkeypatch.setattr("seed_data.get_database", lambda: pytest.fail("database must not be opened"))

    with pytest.raises(RuntimeError, match="explicitly authorize"):
        seed_demo_environment()


def test_demo_seed_refuses_production_even_with_opt_in(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("ALLOW_DEMO_SEED", "true")
    monkeypatch.setenv("DEMO_SEED_PASSWORD", "synthetic-long-demo-password")
    monkeypatch.setattr("seed_data.get_database", lambda: pytest.fail("database must not be opened"))

    with pytest.raises(RuntimeError, match="disabled in production"):
        seed_demo_environment()


def test_demo_seed_requires_database_confirmation(monkeypatch):
    monkeypatch.setenv("MONGO_URI", "mongodb://synthetic-user:synthetic-password@localhost:27017/demo")
    monkeypatch.setenv("DEMO_SEED_DATABASE", "another-database")

    with pytest.raises(RuntimeError, match="must exactly match"):
        get_database()


def test_backup_uri_is_not_passed_on_process_command_line(monkeypatch, tmp_path):
    uri = "mongodb://synthetic-user:synthetic-password@db.example.test:27017/backup?tls=true"
    captured = {}
    monkeypatch.setenv("MONGO_URI", uri)
    monkeypatch.setattr(backup_mongodb.shutil, "which", lambda _: "mongodump")
    monkeypatch.setattr(sys, "argv", ["backup_mongodb.py", "--output", str(tmp_path)])

    def fake_run(command, **kwargs):
        captured["command"] = command
        config_path = command[command.index("--config") + 1]
        with open(config_path, encoding="utf-8") as config_file:
            captured["uri_in_config"] = json.load(config_file)["uri"]
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(backup_mongodb.subprocess, "run", fake_run)
    backup_mongodb.main()

    assert uri not in captured["command"]
    assert captured["uri_in_config"] == uri

def test_health_response_suppresses_database_exception_details():
    app = Flask(__name__)
    fake_mongo = SimpleNamespace(
        cx=SimpleNamespace(
            admin=SimpleNamespace(command=Mock(side_effect=RuntimeError("synthetic-private-detail")))
        )
    )
    with app.test_request_context("/monitoring/health"), patch(
        "routes.monitoring_routes.mongo", fake_mongo
    ), patch(
        "routes.monitoring_routes.HadoopService.status",
        return_value={"enabled": False, "reachable": False, "message": "HDFS disabled."},
    ):
        response, status_code = health()

    body = response.get_data(as_text=True)
    assert status_code == 503
    assert "degraded" in body
    assert "unavailable" in body
    assert "synthetic-private-detail" not in body


def test_inline_scripts_use_response_nonce_without_script_unsafe_inline(client):
    response = client.get("/auth/register")
    script_policy = next(
        directive.strip()
        for directive in response.headers["Content-Security-Policy"].split(";")
        if directive.strip().startswith("script-src ")
    )
    nonce_match = re.search(r"'nonce-([^']+)'", script_policy)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert nonce_match
    assert "'unsafe-inline'" not in script_policy
    assert f'<script nonce="{nonce_match.group(1)}">' in html


def test_template_scripts_have_nonces_and_no_inline_event_handlers():
    for path in Path("templates").rglob("*.html"):
        template = path.read_text(encoding="utf-8")
        for attributes in re.findall(r"<script\b([^>]*)>", template, re.IGNORECASE):
            if not re.search(r"\bsrc\s*=", attributes, re.IGNORECASE):
                assert re.search(r"\bnonce\s*=", attributes, re.IGNORECASE), str(path)
        assert not re.search(
            r"\son(?:submit|change|click|load|error)\s*=", template, re.IGNORECASE
        ), str(path)
        assert not re.search(r"\sstyle\s*=", template, re.IGNORECASE), str(path)
        assert not re.search(r"https://(?:cdn\.tailwindcss\.com|cdn\.jsdelivr\.net|cdnjs\.cloudflare\.com|fonts\.googleapis\.com)", template), str(path)


def _production_config_environment():
    env = os.environ.copy()
    env.update({
        "APP_ENV": "production",
        "FLASK_ENV": "production",
        "FLASK_DEBUG": "false",
        "SECRET_KEY": "synthetic-production-secret-value-32-bytes-minimum",
        "MONGO_URI": "mongodb://synthetic-user:synthetic-password@db.example.test:27017/production?tls=true",
        "TRUSTED_HOSTS": "portal.example.test",
        "SESSION_COOKIE_SECURE": "true",
        "SESSION_COOKIE_HTTPONLY": "true",
        "SESSION_COOKIE_SAMESITE": "Lax",
        "RATELIMIT_STORAGE_URI": "redis://redis.example.test:6379/0",
        "PASSWORD_RESET_EXPOSE_LINK": "false",
    })
    for name in (
        "MAIL_PROVIDER", "RESEND_API_KEY",
        "MAIL_SERVER", "MAIL_PORT", "MAIL_USERNAME", "MAIL_PASSWORD",
        "MAIL_USE_TLS", "MAIL_DEFAULT_SENDER", "PASSWORD_RESET_BASE_URL",
    ):
        env.pop(name, None)
    return env


def _complete_production_environment():
    env = _production_config_environment()
    env.update({
        "MAIL_SERVER": "smtp.example.test",
        "MAIL_PORT": "587",
        "MAIL_USERNAME": "synthetic-user",
        "MAIL_PASSWORD": "synthetic-password",
        "MAIL_USE_TLS": "true",
        "MAIL_DEFAULT_SENDER": "EduPredict <noreply@example.test>",
        "PASSWORD_RESET_BASE_URL": "https://portal.example.test",
    })
    return env


def test_production_configuration_requires_smtp_settings():
    result = subprocess.run(
        [sys.executable, "-c", "from config import Config"],
        env=_production_config_environment(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "Deployment password reset requires" in result.stderr
    assert "MAIL_SERVER" in result.stderr
    assert "MAIL_PASSWORD" in result.stderr
    assert "synthetic-password" not in result.stderr


def test_complete_synthetic_smtp_configuration_is_accepted():
    env = _complete_production_environment()
    result = subprocess.run(
        [sys.executable, "-c", "from config import Config; from pymongo.uri_parser import parse_uri; from urllib.parse import urlsplit; assert Config.MAIL_USE_TLS and not Config.DEBUG; assert Config.SESSION_COOKIE_SECURE and Config.SESSION_COOKIE_HTTPONLY and Config.SESSION_COOKIE_SAMESITE == 'Lax'; assert urlsplit(Config.RATELIMIT_STORAGE_URI).scheme in {'redis', 'rediss'}; opts=parse_uri(Config.MONGO_URI)['options']; assert opts['maxPoolSize'] == 50 and opts['serverSelectionTimeoutMS'] == 5.0"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_complete_synthetic_resend_configuration_is_accepted():
    env = _production_config_environment()
    env.update({
        "MAIL_PROVIDER": "resend",
        "RESEND_API_KEY": "synthetic-resend-key",
        "MAIL_DEFAULT_SENDER": "EduPredict <noreply@example.test>",
        "PASSWORD_RESET_BASE_URL": "https://portal.example.test",
    })
    result = subprocess.run(
        [sys.executable, "-c", "from config import Config; assert Config.MAIL_PROVIDER == 'resend' and Config.RESEND_API_KEY == 'synthetic-resend-key'"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_staging_configuration_keeps_deployment_security_enforced():
    env = _complete_production_environment()
    env.update({"APP_ENV": "staging", "FLASK_ENV": "staging"})
    result = subprocess.run(
        [sys.executable, "-c", "from config import Config; assert Config.APP_ENV == 'staging' and Config.SESSION_COOKIE_SECURE and Config.DEBUG is False"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("name", ["SECRET_KEY", "MONGO_URI"])
def test_production_requires_explicit_secrets_and_database(name):
    env = _complete_production_environment()
    env[name] = ""
    result = subprocess.run(
        [sys.executable, "-c", "from config import Config"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert name in result.stderr
    assert "synthetic-password" not in result.stderr


@pytest.mark.parametrize(("name", "value", "message"), [
    ("FLASK_DEBUG", "true", "FLASK_DEBUG"),
    ("SESSION_COOKIE_SECURE", "false", "SESSION_COOKIE_SECURE"),
    ("SESSION_COOKIE_HTTPONLY", "false", "SESSION_COOKIE_HTTPONLY"),
    ("SESSION_COOKIE_SAMESITE", "None", "SESSION_COOKIE_SAMESITE"),
    ("TRUSTED_HOSTS", "*.example.test", "TRUSTED_HOSTS"),
    ("TRUSTED_HOSTS", "portal.example.test/path", "TRUSTED_HOSTS"),
    ("MONGO_URI", "mongodb://u:p@localhost:27017/production?tls=true", "MONGO_URI"),
    ("MONGO_URI", "mongodb://u:p@db.example.test:27017/edupredict?tls=true", "MONGO_URI"),
    ("RATELIMIT_STORAGE_URI", "memory://", "RATELIMIT_STORAGE_URI"),
    ("PROXY_FIX_X_FOR", "2", "ProxyFix"),
])
def test_production_rejects_unsafe_configuration(name, value, message):
    env = _complete_production_environment()
    env[name] = value
    result = subprocess.run(
        [sys.executable, "-c", "from config import Config"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert message in result.stderr
    assert "synthetic-password" not in result.stderr


def test_health_liveness_does_not_require_mongodb(client, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "routes.monitoring_routes.mongo",
        SimpleNamespace(cx=SimpleNamespace(admin=SimpleNamespace(command=lambda *_args, **_kwargs: pytest.fail("liveness must not ping MongoDB")))),
    )
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_readiness_returns_503_without_database(client, monkeypatch):
    from types import SimpleNamespace

    def unavailable(*_args, **_kwargs):
        raise RuntimeError("private")

    monkeypatch.setattr(
        "routes.monitoring_routes.mongo",
        SimpleNamespace(cx=SimpleNamespace(admin=SimpleNamespace(command=unavailable))),
    )
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert "private" not in response.get_data(as_text=True)


def test_readiness_reports_database_success(client, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "routes.monitoring_routes.mongo",
        SimpleNamespace(cx=SimpleNamespace(admin=SimpleNamespace(command=lambda *_args, **_kwargs: {"ok": 1}))),
    )
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ready", "database": "ok"}


def test_production_admin_bootstrap_is_disabled():
    from app import create_default_admin

    test_app = Flask(__name__)
    test_app.config["APP_ENV"] = "production"
    with test_app.app_context(), patch("app.mongo.db.users.find_one", side_effect=AssertionError("database must not be touched")):
        create_default_admin()


def test_runtime_index_setup_does_not_run_legacy_roster_migration(client, monkeypatch):
    from services.academic_data_service import AcademicDataService

    monkeypatch.setattr(
        AcademicDataService,
        "migrate_legacy_course_rosters",
        lambda: pytest.fail("legacy migration must be an explicit operation"),
    )
    response = client.get("/auth/login")
    assert response.status_code == 200


def test_database_error_details_are_not_written_to_application_logs(test_app, monkeypatch, caplog):
    from app import create_default_admin
    from models import mongo

    monkeypatch.setenv("ADMIN_NAME", "Synthetic Admin")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.test")
    monkeypatch.setenv("ADMIN_PASSWORD", "synthetic-password")
    with test_app.app_context(), patch.object(
        mongo.db.users, "find_one", side_effect=RuntimeError("synthetic-private-uri")
    ):
        create_default_admin()
    assert "synthetic-private-uri" not in caplog.text


def test_unhandled_request_exception_logs_no_exception_message(caplog):
    from flask import Flask
    from app import _log_exception_safely

    test_app = Flask("sanitized_exception_logging_test")
    test_app.log_exception = lambda exc_info: _log_exception_safely(test_app, exc_info)

    def fail_with_sensitive_message():
        raise RuntimeError("synthetic-private-request-body-and-token")

    test_app.add_url_rule("/_test/sanitized-error", view_func=fail_with_sensitive_message)
    response = test_app.test_client().get("/_test/sanitized-error")

    assert response.status_code == 500
    assert "RuntimeError" in caplog.text
    assert "synthetic-private-request-body-and-token" not in caplog.text


def test_production_dockerfile_uses_gunicorn_and_non_root_healthcheck():
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "USER appuser" in dockerfile
    assert "gunicorn" in dockerfile
    assert "HEALTHCHECK" in dockerfile and "/health" in dockerfile
    assert "SECRET_KEY" not in dockerfile
    assert "MONGO_URI" not in dockerfile
