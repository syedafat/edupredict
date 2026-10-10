# conftest.py
"""Test fixtures for EduPredict application.

Creates a Flask application instance configured for testing and injects a
mongomock in‑memory database so that tests do not touch a real MongoDB.
"""
import os
import pytest
from flask import Flask
from app import create_app
from models import mongo
import mongomock

@pytest.fixture(scope="session")
def test_app():
    # Ensure testing environment variables
    os.environ.setdefault("FLASK_ENV", "development")
    # Use a dummy secret key for tests
    os.environ.setdefault("SECRET_KEY", "test-secret-key")
    # Disable secure cookie requirement in tests
    os.environ.setdefault("SESSION_COOKIE_SECURE", "false")
    app = create_app()
    # Disable CSRF protection for auth routes in tests
    from app import csrf
    from routes.auth_routes import auth_bp
    csrf.exempt(auth_bp)
    # Disable CSRF protection for tests
    app.config['WTF_CSRF_ENABLED'] = False
    # Override the mongo client with mongomock
    client = mongomock.MongoClient()
    mongo.db = client["edupredict_test"]
    # Initialize indexes manually if needed (optional)
    with app.app_context():
        # Ensure indexes are created
        mongo.db.users.create_index("email", unique=True)
    yield app

@pytest.fixture
def client(test_app: Flask):
    from extensions import limiter
    limiter.reset()
    return test_app.test_client()
