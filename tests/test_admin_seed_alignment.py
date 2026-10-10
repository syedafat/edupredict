import os

from werkzeug.security import check_password_hash, generate_password_hash

from app import create_default_admin
from models import mongo


def test_create_default_admin_uses_env_credentials_even_when_other_admin_exists(test_app):
    mongo.db.users.delete_many({})

    os.environ["ADMIN_NAME"] = "Env Admin"
    os.environ["ADMIN_EMAIL"] = "admin@example.com"
    os.environ["ADMIN_PASSWORD"] = "Secret123"

    mongo.db.users.insert_one({
        "name": "Unrelated Admin",
        "email": "other-admin@example.com",
        "password_hash": "placeholder",
        "role": "admin",
        "status": "approved",
    })

    with test_app.app_context():
        create_default_admin()

    doc = mongo.db.users.find_one({"email": "admin@example.com"})
    assert doc is not None
    assert doc["role"] == "admin"
    assert doc["status"] == "approved"
    assert check_password_hash(doc["password_hash"], "Secret123")


def test_create_default_admin_is_disabled_in_production(test_app, monkeypatch):
    mongo.db.users.delete_many({})
    monkeypatch.setenv("ADMIN_NAME", "Env Admin")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "Secret123")
    monkeypatch.setitem(test_app.config, "APP_ENV", "production")

    with test_app.app_context():
        create_default_admin()

    assert mongo.db.users.find_one({"email": "admin@example.com"}) is None


def test_create_default_admin_does_not_reset_existing_password(test_app, monkeypatch):
    mongo.db.users.delete_many({})
    mongo.db.users.insert_one({
        "name": "Existing Admin",
        "email": "admin@example.com",
        "password_hash": generate_password_hash("ExistingSecret123"),
        "role": "admin",
        "status": "approved",
    })
    monkeypatch.setenv("ADMIN_NAME", "Env Admin")
    monkeypatch.setenv("ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ADMIN_PASSWORD", "NewEnvironmentSecret123")

    with test_app.app_context():
        create_default_admin()

    stored_hash = mongo.db.users.find_one({"email": "admin@example.com"})["password_hash"]
    assert check_password_hash(stored_hash, "ExistingSecret123")
    assert not check_password_hash(stored_hash, "NewEnvironmentSecret123")
