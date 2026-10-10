import unittest
from unittest.mock import patch, MagicMock
from bson import ObjectId

from routes.admin_routes import _available_departments


class FakeCollection:
    def __init__(self, docs):
        self.docs = docs

    def create_index(self, *args, **kwargs):
        pass

    def find(self, query=None, projection=None):
        query = query or {}
        results = []
        for doc in self.docs:
            match = True
            for k, v in query.items():
                if isinstance(v, dict):
                    if "$ne" in v and doc.get(k) == v["$ne"]:
                        match = False
                        break
                    if "$nin" in v and doc.get(k) in v["$nin"]:
                        match = False
                        break
                    if "$in" in v and doc.get(k) not in v["$in"]:
                        match = False
                        break
                elif doc.get(k) != v:
                    match = False
                    break
            if match:
                if projection:
                    if all(v == 0 for v in projection.values()):
                        projected = {k: v for k, v in doc.items() if k not in projection}
                    else:
                        projected = {k: v for k, v in doc.items() if k in projection}
                    results.append(projected)
                else:
                    results.append(doc)

        class Cursor(list):
            def sort(self, *args, **kwargs):
                return self
            def limit(self, *args, **kwargs):
                return self

        return Cursor(results)


class FakeDatabase:
    def __init__(self, courses=None, users=None):
        self.courses = FakeCollection(courses or [])
        self.users = FakeCollection(users or [])

    def __getitem__(self, name):
        return getattr(self, name)


class AdminDepartmentDropdownTests(unittest.TestCase):
    def test_available_departments_dynamic_from_courses_and_users(self):
        fake_courses = [
            {"_id": ObjectId(), "code": "AI-101", "department": "Artificial Intelligence", "status": "active"},
            {"_id": ObjectId(), "code": "DS-201", "department": "Data Science", "status": "active"},
            {"_id": ObjectId(), "code": "CS-101", "department": "Computer Science", "status": "active"},
            {"_id": ObjectId(), "code": "OLD-99", "department": "Archived Studies", "status": "inactive"},
        ]
        fake_users = [
            {"_id": ObjectId(), "name": "Prof A", "department": "se", "role": "teacher"},
            {"_id": ObjectId(), "name": "Student B", "department": "Information Technology", "role": "student"},
        ]
        fake_db = FakeDatabase(courses=fake_courses, users=fake_users)

        with patch("routes.admin_routes.mongo") as mock_mongo:
            mock_mongo.db = fake_db
            depts = _available_departments()

        # Should include active courses and user departments (with 'se' expanded to 'Software Engineering')
        self.assertIn("Artificial Intelligence", depts)
        self.assertIn("Data Science", depts)
        self.assertIn("Computer Science", depts)
        self.assertIn("Information Technology", depts)
        self.assertIn("Software Engineering", depts)
        # Inactive course department should not be included if no one else has it
        self.assertNotIn("Archived Studies", depts)

    def test_newly_added_course_department_immediately_reflected(self):
        fake_courses = [
            {"_id": ObjectId(), "code": "AI-101", "department": "Artificial Intelligence", "status": "active"},
        ]
        fake_db = FakeDatabase(courses=fake_courses, users=[])

        with patch("routes.admin_routes.mongo") as mock_mongo:
            mock_mongo.db = fake_db
            depts_before = _available_departments()
            self.assertIn("Artificial Intelligence", depts_before)
            self.assertNotIn("Cybersecurity", depts_before)

            # Simulate adding a new course with a new department
            fake_courses.append({
                "_id": ObjectId(),
                "code": "CYBER-500",
                "department": "Cybersecurity",
                "status": "active"
            })

            depts_after = _available_departments()
            self.assertIn("Cybersecurity", depts_after)
            self.assertIn("Artificial Intelligence", depts_after)

    def test_fallback_defaults_when_empty_database(self):
        fake_db = FakeDatabase(courses=[], users=[])

        with patch("routes.admin_routes.mongo") as mock_mongo:
            mock_mongo.db = fake_db
            depts = _available_departments()

        self.assertEqual(depts, ["Artificial Intelligence", "Computer Science", "Data Science", "Information Technology", "Software Engineering"])

    def test_add_user_template_renders_departments(self):
        import os
        from flask import Flask, render_template
        template_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "templates"))
        app = Flask(__name__, template_folder=template_dir)
        app.secret_key = "test_secret"
        app.jinja_env.globals["csrf_token"] = lambda: "mock_csrf"
        app.jinja_env.globals["url_for"] = lambda endpoint, **kwargs: f"/{endpoint}"

        with app.test_request_context("/admin/add-user"):
            html = render_template(
                "admin/add_user.html",
                departments=["Artificial Intelligence", "Data Science", "Software Engineering"]
            )
            # Verify dynamic departments are rendered as options
            self.assertIn("Artificial Intelligence", html)
            self.assertIn("Data Science", html)
            self.assertIn("Software Engineering", html)
            # Verify old hardcoded static value="se", "cs", "it" are gone
            self.assertNotIn('value="se"', html)
            self.assertNotIn('value="cs"', html)
            self.assertNotIn('value="it"', html)

    def test_add_user_route_get_returns_dynamic_departments(self):
        from app import create_app
        admin_id = ObjectId()
        fake_courses = [
            {"_id": ObjectId(), "code": "AI-101", "department": "Artificial Intelligence", "status": "active"},
            {"_id": ObjectId(), "code": "DS-201", "department": "Data Science", "status": "active"},
        ]
        fake_users = [
            {"_id": admin_id, "name": "Admin", "email": "admin@test.com", "role": "admin", "status": "active"},
        ]
        fake_db = FakeDatabase(courses=fake_courses, users=fake_users)
        fake_db.users.find_one = lambda query, projection=None: fake_users[0] if query.get("_id") == admin_id else None

        app = create_app()
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False

        with patch("routes.admin_routes.mongo") as mock_mongo, \
             patch("models.mongo.db", fake_db):
            mock_mongo.db = fake_db
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess["user_id"] = str(admin_id)
                    sess["role"] = "admin"

                response = client.get("/admin/add-user")
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)
                self.assertIn("Artificial Intelligence", html)
                self.assertIn("Data Science", html)
                self.assertNotIn('value="se"', html)
                self.assertNotIn('value="cs"', html)
                self.assertNotIn('value="it"', html)

    def test_students_route_filter_uses_dynamic_standardized_departments(self):
        from app import create_app
        admin_id = ObjectId()
        fake_courses = [
            {"_id": ObjectId(), "code": "AI-101", "department": "Artificial Intelligence", "status": "active"},
            {"_id": ObjectId(), "code": "DS-201", "department": "Data Science", "status": "active"},
        ]
        fake_users = [
            {"_id": admin_id, "name": "Admin", "email": "admin@test.com", "role": "admin", "status": "active"},
            {"_id": ObjectId(), "name": "Student Legacy SE", "email": "se@test.com", "role": "student", "department": "se", "status": "active"},
            {"_id": ObjectId(), "name": "Student Legacy General", "email": "gen@test.com", "role": "student", "department": "general", "status": "active"},
        ]
        fake_db = FakeDatabase(courses=fake_courses, users=fake_users)
        fake_db.users.find_one = lambda query, projection=None: fake_users[0] if query.get("_id") == admin_id else None

        app = create_app()
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False

        with patch("routes.admin_routes.mongo") as mock_mongo, \
             patch("models.mongo.db", fake_db):
            mock_mongo.db = fake_db
            with app.test_client() as client:
                with client.session_transaction() as sess:
                    sess["user_id"] = str(admin_id)
                    sess["role"] = "admin"

                response = client.get("/admin/students")
                self.assertEqual(response.status_code, 200)
                html = response.get_data(as_text=True)

                # Filter dropdown should contain standardized names from DB
                self.assertIn("Artificial Intelligence", html)
                self.assertIn("Data Science", html)
                self.assertIn("Software Engineering", html)

                # Filter dropdown must NOT contain raw legacy shortcodes
                self.assertNotIn('<option value="cs"', html)
                self.assertNotIn('<option value="se"', html)
                self.assertNotIn('<option value="it"', html)
                self.assertNotIn('<option value="general"', html)

                # Table rows should standardize legacy departments
                self.assertIn("Software Engineering", html)
                self.assertIn("General Studies", html)
                self.assertNotIn('>se<', html)
                self.assertNotIn('>general<', html)


if __name__ == "__main__":
    unittest.main()
