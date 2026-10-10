# tests/auth/test_register.py
"""Registration route tests for student and teacher registration."""
import pytest
from werkzeug.security import check_password_hash
from models import mongo

@pytest.fixture(autouse=True)
def clean_users():
    mongo.db.users.delete_many({})
    yield
    mongo.db.users.delete_many({})

def test_student_register_success(client):
    response = client.post(
        "/auth/register",
        data={
            "name": "Student One",
            "email": "student@example.com",
            "password": "StrongPass1",
            "confirm_password": "StrongPass1",
            "department": "Science",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"If an account can be created for this address" in response.data
    # Verify user stored with password_hash only
    user = mongo.db.users.find_one({"email": "student@example.com"})
    assert user is not None
    assert "password_hash" in user
    assert "password" not in user
    assert check_password_hash(user["password_hash"], "StrongPass1")

def test_teacher_register_pending(client):
    response = client.post(
        "/auth/teacher/register",
        data={
            "name": "Teacher One",
            "email": "teacher@example.com",
            "password": "TeachPass2",
            "confirm_password": "TeachPass2",
            "department": "Math",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"If a teacher account can be created for this address" in response.data
    teacher = mongo.db.users.find_one({"email": "teacher@example.com"})
    assert teacher is not None
    assert teacher["role"] == "teacher"
    assert teacher["status"] == "pending"
    # Ensure password stored securely
    assert "password_hash" in teacher
    assert check_password_hash(teacher["password_hash"], "TeachPass2")


def test_student_registration_does_not_disclose_duplicate_email(client):
    mongo.db.users.insert_one({"email": "existing-student@example.com", "role": "student"})
    response = client.post(
        "/auth/register",
        data={
            "name": "Student One",
            "email": "existing-student@example.com",
            "password": "StrongPass1",
            "confirm_password": "StrongPass1",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"If an account can be created for this address" in response.data
    assert b"Email already registered" not in response.data
    assert mongo.db.users.count_documents({"email": "existing-student@example.com"}) == 1


def test_teacher_registration_does_not_disclose_duplicate_email(client):
    mongo.db.users.insert_one({"email": "existing-teacher@example.com", "role": "teacher"})
    response = client.post(
        "/auth/teacher/register",
        data={
            "name": "Teacher One",
            "email": "existing-teacher@example.com",
            "password": "TeachPass2",
            "confirm_password": "TeachPass2",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"If a teacher account can be created for this address" in response.data
    assert b"Email already registered" not in response.data
    assert mongo.db.users.count_documents({"email": "existing-teacher@example.com"}) == 1

def test_register_password_mismatch(client):
    response = client.post(
        "/auth/register",
        data={
            "name": "User",
            "email": "u@example.com",
            "password": "Pass1234",
            "confirm_password": "Different",
            "department": "General",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Passwords do not match" in response.data
    assert mongo.db.users.find_one({"email": "u@example.com"}) is None
