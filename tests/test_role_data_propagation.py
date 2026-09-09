import unittest
from unittest.mock import patch

from bson import ObjectId

from routes.student_routes import _owned_assignment
from routes.teacher_routes import _authorized_enrollment
from services.academic_data_service import AcademicDataService


class PropagationCollection:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query, projection=None):
        result = []
        for row in self.rows:
            matches = True
            for key, expected in query.items():
                actual = row.get(key)
                if isinstance(expected, dict) and "$in" in expected:
                    matches = actual in expected["$in"]
                elif actual != expected:
                    matches = False
                if not matches:
                    break
            if matches:
                result.append(row)
        return result

    def find_one(self, query, projection=None):
        rows = self.find(query, projection)
        return rows[0] if rows else None


class PropagationDatabase:
    def __init__(self):
        self.courses = PropagationCollection([
            {"_id": "course-1", "teacher_id": "teacher-a", "status": "active"},
            {"_id": "course-2", "teacher_id": "teacher-a", "status": "active"},
            {"_id": "course-3", "teacher_id": "teacher-b", "status": "active"},
        ])
        self.enrollments = PropagationCollection([
            {"course_id": "course-1", "student_id": "student-1", "status": "active"},
            {"course_id": "course-2", "student_id": "student-2", "status": "active"},
            {"course_id": "course-3", "student_id": "student-3", "status": "active"},
        ])


class RoleDataPropagationTests(unittest.TestCase):
    def test_teacher_sees_only_students_from_assigned_courses(self):
        database = PropagationDatabase()
        with patch("services.academic_data_service.mongo") as service_mongo:
            service_mongo.db = database
            teacher_a_courses = [course for course in database.courses.rows if course["teacher_id"] == "teacher-a"]
            teacher_a_students = AcademicDataService.student_ids_for_courses([course["_id"] for course in teacher_a_courses])
            teacher_b_students = AcademicDataService.student_ids_for_courses(["course-3"])

        self.assertEqual(teacher_a_students, {"student-1", "student-2"})
        self.assertEqual(teacher_b_students, {"student-3"})
        self.assertTrue(teacher_a_students.isdisjoint(teacher_b_students))

    @patch("routes.teacher_routes.AcademicDataService.active_enrollments")
    @patch("routes.teacher_routes._teacher_courses")
    def test_teacher_course_and_student_authorization_are_both_required(self, teacher_courses, active_enrollments):
        teacher_courses.return_value = [{"_id": "course-1"}]
        active_enrollments.return_value = [{"course_id": "course-1", "student_id": "student-1", "status": "active"}]

        self.assertTrue(_authorized_enrollment("course-1", "student-1"))
        self.assertFalse(_authorized_enrollment("course-2", "student-1"))
        self.assertFalse(_authorized_enrollment("course-1", "student-3"))

    def test_student_assignment_lookup_is_owner_scoped(self):
        assignment_id = ObjectId()
        assignments = PropagationCollection([
            {"_id": assignment_id, "student_id": "student-1", "course_id": "course-1"},
        ])
        database = type("Database", (), {"assignments": assignments})()
        with patch("routes.student_routes.mongo") as route_mongo:
            route_mongo.db = database
            owned = _owned_assignment(str(assignment_id), "student-1")
            foreign = _owned_assignment(str(assignment_id), "student-2")

        self.assertIsNotNone(owned)
        self.assertIsNone(foreign)

    def test_idempotent_write_keys_are_relationship_scoped(self):
        attendance_key = {"student_id": "student-1", "course_id": "course-1", "date": "2026-09-08"}
        grade_key = {"student_id": "student-1", "course_id": "course-1", "assessment": "Quiz 1"}
        assignment_key = {"student_id": "student-1", "assignment_key": "course-1:Quiz:none"}
        self.assertEqual(len(attendance_key), 3)
        self.assertEqual(len(grade_key), 3)
        self.assertEqual(len(assignment_key), 2)


if __name__ == "__main__":
    unittest.main()