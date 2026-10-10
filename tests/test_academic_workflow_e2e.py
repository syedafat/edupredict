import pytest
from werkzeug.security import generate_password_hash

from models import mongo


@pytest.fixture
def seeded_workflow_users():
    password_hash = generate_password_hash("Password123")
    users = [
        {
            "name": "Admin User",
            "email": "admin.workflow@test.local",
            "password_hash": password_hash,
            "role": "admin",
            "status": "approved",
            "department": "Administration",
        },
        {
            "name": "Teacher User",
            "email": "teacher.workflow@test.local",
            "password_hash": password_hash,
            "role": "teacher",
            "status": "approved",
            "department": "Computer Science",
        },
        {
            "name": "Student User",
            "email": "student.workflow@test.local",
            "password_hash": password_hash,
            "role": "student",
            "status": "approved",
            "department": "Computer Science",
        },
    ]
    mongo.db.users.delete_many({})
    mongo.db.courses.delete_many({})
    mongo.db.departments.delete_many({})
    mongo.db.subjects.delete_many({})
    mongo.db.enrollments.delete_many({})
    mongo.db.attendance.delete_many({})
    mongo.db.grades.delete_many({})
    mongo.db.assignments.delete_many({})
    mongo.db.submissions.delete_many({})
    mongo.db.predictions.delete_many({})
    mongo.db.notifications.delete_many({})
    mongo.db.users.insert_many(users)
    return users


def test_academic_workflow_smoke(client, seeded_workflow_users):
    admin = seeded_workflow_users[0]

    login_response = client.post(
        "/login",
        data={"email": admin["email"], "password": "Password123"},
        follow_redirects=True,
    )
    assert login_response.status_code == 200
    assert b"Logged in successfully" in login_response.data or b"Dashboard" in login_response.data

    admin_dashboard = client.get("/admin/dashboard")
    assert admin_dashboard.status_code == 200

    teacher = mongo.db.users.find_one({"email": "teacher.workflow@test.local"})
    student = mongo.db.users.find_one({"email": "student.workflow@test.local"})

    assert teacher is not None
    assert student is not None

    with client.session_transaction() as session:
        session["user_id"] = str(teacher["_id"])
        session["role"] = "teacher"
        session["logged_in"] = True

    teacher_dashboard = client.get("/teacher/dashboard")
    assert teacher_dashboard.status_code == 200

    with client.session_transaction() as session:
        session["user_id"] = str(student["_id"])
        session["role"] = "student"
        session["logged_in"] = True

    student_dashboard = client.get("/student/dashboard")
    assert student_dashboard.status_code == 200


def test_student_course_page_lists_subjects(client):
    student = mongo.db.users.insert_one({
        "name": "Student Subject Viewer",
        "email": "student.subjects@test.local",
        "password_hash": generate_password_hash("Password123"),
        "role": "student",
        "status": "approved",
        "department": "Computer Science",
    })
    course = mongo.db.courses.insert_one({
        "code": "CS-101",
        "title": "Introduction to Programming",
        "department": "Computer Science",
        "credits": 4,
        "semester": "Fall 2026",
        "status": "active",
    })
    mongo.db.subjects.insert_many([
        {"name": "Programming Fundamentals", "code": "CS101-PF", "course_id": course.inserted_id, "status": "active"},
        {"name": "Data Structures", "code": "CS101-DS", "course_id": course.inserted_id, "status": "active"},
    ])
    mongo.db.enrollments.insert_one({
        "student_id": str(student.inserted_id),
        "course_id": course.inserted_id,
        "status": "active",
    })

    with client.session_transaction() as session:
        session["user_id"] = str(student.inserted_id)
        session["role"] = "student"
        session["logged_in"] = True

    response = client.get("/student/courses")
    assert response.status_code == 200
    assert b"Programming Fundamentals" in response.data
    assert b"Data Structures" in response.data
    assert b"CS101-PF" in response.data
