from bson import ObjectId
import logging
import os
import subprocess
import sys
from app import _ensure_dataset_indexes


def test_security_headers_limit_scripts_styles_and_assets_to_self(client):
    response = client.get("/auth/login")
    policy = response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "'unsafe-eval'" not in policy
    assert "'unsafe-inline'" not in policy
    assert "style-src-attr 'none'" in policy
    assert "https://" not in policy
    assert "object-src 'none'" in policy
    assert response.headers["Permissions-Policy"] == "camera=(), microphone=(), geolocation=()"


def test_self_hosted_frontend_assets_are_available(client):
    for path in (
        "/static/css/tailwind.css",
        "/static/css/fonts.css",
        "/static/css/metrics.css",
        "/static/vendor/fontawesome/all.min.css",
        "/static/vendor/chart.umd.min.js",
        "/static/vendor/fonts/dm-sans-latin-400-normal.woff2",
        "/static/vendor/webfonts/fa-solid-900.woff2",
    ):
        response = client.get(path)
        assert response.status_code == 200, path


def test_dataset_index_setup_preserves_legacy_records_and_deduplicates_hashed_records():
    class ExistingDataCollection:
        def __init__(self):
            self.documents = [
                {"dataset_type": "academic", "legacy": 1},
                {"dataset_type": "academic", "legacy": 2},
            ]
            self.indexes = []

        def create_index(self, keys, **options):
            self.indexes.append((keys, options))

    collection = ExistingDataCollection()
    _ensure_dataset_indexes(collection, logging.getLogger("test"))

    assert len(collection.documents) == 2
    assert collection.indexes[1][1]["unique"] is True
    assert collection.indexes[1][1]["partialFilterExpression"] == {
        "source_hash": {"$type": "string"}
    }


def test_registration_rate_limit_is_active(client):
    responses = [
        client.post("/auth/register", data={})
        for _ in range(11)
    ]
    assert all(response.status_code == 200 for response in responses[:10])
    assert responses[-1].status_code == 429


def test_stream_ingestion_has_an_active_request_limit(client):
    user_id = ObjectId()
    mongo.db.users.insert_one({
        "_id": user_id,
        "email": f"stream-limit-{user_id}@test.invalid",
        "role": "admin",
        "status": "approved",
    })
    with client.session_transaction() as sess:
        sess["user_id"] = str(user_id)
        sess["role"] = "admin"

    responses = [client.post("/data/stream", json={"student_id": ""}) for _ in range(121)]
    assert all(response.status_code == 400 for response in responses[:120])
    assert responses[-1].status_code == 429


def test_notification_broadcast_has_an_active_post_limit(client):
    user_id = ObjectId()
    mongo.db.users.insert_one({
        "_id": user_id,
        "email": f"broadcast-limit-{user_id}@test.invalid",
        "role": "admin",
        "status": "approved",
    })
    with client.session_transaction() as sess:
        sess["user_id"] = str(user_id)
        sess["role"] = "admin"

    responses = [client.post("/notifications/broadcast", data={}) for _ in range(11)]
    assert all(response.status_code == 200 for response in responses[:10])
    assert responses[-1].status_code == 429


def test_csrf_is_enabled_for_non_authentication_post_routes(client, monkeypatch):
    monkeypatch.setitem(client.application.config, "WTF_CSRF_ENABLED", True)
    response = client.post(f"/notifications/mark-read/{ObjectId()}")
    assert response.status_code == 400


def test_production_config_rejects_reset_link_exposure():
    env = os.environ.copy()
    env.update({
        "APP_ENV": "production",
        "FLASK_ENV": "production",
        "FLASK_DEBUG": "false",
        "SECRET_KEY": "test-only-secret-not-for-deployment",
        "MONGO_URI": "mongodb://test-user:test-password@db.example.invalid/edupredict?tls=true",
        "SESSION_COOKIE_SECURE": "true",
        "SESSION_COOKIE_HTTPONLY": "true",
        "SESSION_COOKIE_SAMESITE": "Lax",
        "TRUSTED_HOSTS": "portal.example.test",
        "RATELIMIT_STORAGE_URI": "redis://redis.example.test:6379/0",
        "PASSWORD_RESET_EXPOSE_LINK": "true",
    })
    result = subprocess.run(
        [sys.executable, "-c", "from config import Config"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "PASSWORD_RESET_EXPOSE_LINK must be disabled in deployment" in result.stderr
    assert "test-password" not in result.stderr


def test_production_config_rejects_short_secret_key():
    env = os.environ.copy()
    env.update({
        "APP_ENV": "production",
        "FLASK_ENV": "production",
        "FLASK_DEBUG": "false",
        "SECRET_KEY": "short-test-key",
        "MONGO_URI": "mongodb://test-user:test-password@db.example.invalid/edupredict?tls=true",
        "SESSION_COOKIE_SECURE": "true",
        "SESSION_COOKIE_HTTPONLY": "true",
        "SESSION_COOKIE_SAMESITE": "Lax",
        "TRUSTED_HOSTS": "portal.example.test",
        "RATELIMIT_STORAGE_URI": "redis://redis.example.test:6379/0",
        "PASSWORD_RESET_EXPOSE_LINK": "false",
    })
    result = subprocess.run(
        [sys.executable, "-c", "from config import Config"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "SECRET_KEY must contain at least 32 bytes in deployment" in result.stderr
    assert "short-test-key" not in result.stderr

from models import mongo


def _login(client, user_id, role):
    with client.session_transaction() as sess:
        sess["user_id"] = str(user_id)
        sess["role"] = role


def test_authenticated_non_admin_gets_403(client):
    user_id = ObjectId()
    mongo.db.users.insert_one({"_id": user_id, "email": f"{user_id}@test.invalid", "role": "teacher", "status": "approved"})
    _login(client, user_id, "teacher")

    response = client.get("/admin/reports")

    assert response.status_code == 403


def test_report_download_rejects_file_outside_reports_directory(client, test_app, tmp_path):
    admin_id = ObjectId()
    mongo.db.users.insert_one({"_id": admin_id, "email": f"{admin_id}@test.invalid", "role": "admin", "status": "approved"})
    _login(client, admin_id, "admin")
    outside_file = tmp_path / "private.txt"
    outside_file.write_text("private", encoding="utf-8")
    report_id = ObjectId()
    mongo.db.reports.insert_one({"_id": report_id, "path": str(outside_file), "name": "private.txt"})

    response = client.get(f"/admin/reports/{report_id}/download")

    assert response.status_code == 302
    assert b"private" not in response.data


def test_report_download_allows_file_inside_reports_directory(client, test_app, tmp_path, monkeypatch):
    admin_id = ObjectId()
    mongo.db.users.insert_one({"_id": admin_id, "email": f"{admin_id}@test.invalid", "role": "admin", "status": "approved"})
    _login(client, admin_id, "admin")
    reports_dir = tmp_path / "uploads" / "historical"
    reports_dir.mkdir(parents=True)
    report_file = reports_dir / "report.csv"
    report_file.write_text("id,value\n1,ok\n", encoding="utf-8")
    monkeypatch.setitem(test_app.config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    report_id = ObjectId()
    mongo.db.reports.insert_one({"_id": report_id, "path": str(report_file), "name": "report.csv"})

    response = client.get(f"/admin/reports/{report_id}/download")

    assert response.status_code == 200
    assert response.data.replace(b"\r\n", b"\n") == b"id,value\n1,ok\n"
