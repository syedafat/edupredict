# tests/auth/test_login.py
"""Authentication login tests."""
import pytest
from werkzeug.security import generate_password_hash
from models import mongo

@pytest.fixture(autouse=True)
def setup_test_user():
    # Insert a test admin user into mongomock db
    mongo.db.users.delete_many({})
    mongo.db.users.insert_one({
        "name": "Test Admin",
        "email": "admin@example.com",
        "password_hash": generate_password_hash("Secret123"),
        "role": "admin",
        "status": "approved",
    })
    yield
    mongo.db.users.delete_many({})

def test_login_get_page(client):
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert b"Login" in response.data

def test_login_success_redirect(client):
    response = client.post(
        "/auth/login",
        data={"email": "admin@example.com", "password": "Secret123"},
        follow_redirects=False,
    )
    # Successful login redirects to admin dashboard endpoint
    assert response.status_code == 302
    assert "/admin" in response.headers["Location"]


def test_login_discards_preexisting_session_values(client):
    with client.session_transaction() as sess:
        sess["pre_auth_marker"] = "must-not-survive-login"

    response = client.post(
        "/auth/login",
        data={"email": "admin@example.com", "password": "Secret123"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    with client.session_transaction() as sess:
        assert "pre_auth_marker" not in sess
        assert sess["role"] == "admin"

def test_login_invalid_password(client):
    response = client.post(
        "/auth/login",
        data={"email": "admin@example.com", "password": "WrongPass"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    # Flash message contains "Invalid email or password"
    assert b"Invalid email or password" in response.data

def test_login_missing_fields(client):
    response = client.post(
        "/auth/login",
        data={"email": ""},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Please enter both email and password" in response.data

def test_logout_post_only(client):
    # First login to set session
    client.post(
        "/auth/login",
        data={"email": "admin@example.com", "password": "Secret123"},
        follow_redirects=False,
    )
    # POST logout should clear session and redirect
    resp_post = client.post("/auth/logout", follow_redirects=False)
    assert resp_post.status_code == 302
    # GET logout should return 405 Method Not Allowed
    resp_get = client.get("/auth/logout")
    assert resp_get.status_code == 405
