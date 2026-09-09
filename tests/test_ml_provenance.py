import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.academic_data_service import AcademicDataService
from ml.model_manager import ModelManager


class ScopedCollection:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query, projection=None):
        return [
            row for row in self.rows
            if all(
                row.get(key) in value["$in"] if isinstance(value, dict) and "$in" in value else row.get(key) == value
                for key, value in query.items()
            )
        ]

    def count_documents(self, query):
        return len(self.find(query))

    def find_one(self, query, projection=None):
        rows = self.find(query)
        return rows[0] if rows else None


class FeatureDatabase:
    def __init__(self):
        self.attendance = ScopedCollection([
            {"student_id": "student-1", "course_id": "course-a", "present": True},
            {"student_id": "student-1", "course_id": "course-b", "present": False},
        ])
        self.grades = ScopedCollection([
            {"student_id": "student-1", "course_id": "course-a", "score": 90},
            {"student_id": "student-1", "course_id": "course-b", "score": 10},
        ])
        self.lms_records = ScopedCollection([])
        self.assignments = ScopedCollection([])
        self.submissions = ScopedCollection([])
        self.users = ScopedCollection([])


class MlProvenanceTests(unittest.TestCase):
    def test_course_scope_excludes_other_course_records(self):
        database = FeatureDatabase()
        with patch("services.academic_data_service.mongo") as mongo:
            mongo.db = database
            values = AcademicDataService._feature_values("student-1", course_id="course-a")

        self.assertEqual(values["attendance_rate"], 100.0)
        self.assertEqual(values["average_score"], 90.0)

    def test_artifact_hash_matches_exact_file(self):
        with tempfile.TemporaryDirectory() as directory:
            artifact = Path(directory) / "model.joblib"
            artifact.write_bytes(b"model-artifact")
            expected = hashlib.sha256(b"model-artifact").hexdigest()
            with patch("ml.model_manager._model_path", return_value=str(artifact)):
                actual = ModelManager.artifact_hash("performance")
                self.assertEqual(actual, expected)
                self.assertTrue(ModelManager.artifact_matches("performance", {"artifact_hash": expected}))
                self.assertFalse(ModelManager.artifact_matches("performance", {"artifact_hash": "wrong"}))

    def test_assignment_completion_features_are_course_scoped(self):
        database = FeatureDatabase()
        assignment_id = "assignment-a"
        database.assignments = ScopedCollection([
            {"_id": assignment_id, "student_id": "student-1", "course_id": "course-a", "due_date": "2026-09-01"},
            {"_id": "assignment-b", "student_id": "student-1", "course_id": "course-b", "due_date": "2026-09-01"},
        ])
        database.submissions = ScopedCollection([
            {"assignment_id": assignment_id, "student_id": "student-1", "course_id": "course-a", "status": "graded", "submitted_at": "2026-09-01T12:00:00+00:00"},
        ])
        with patch("services.academic_data_service.mongo") as mongo:
            mongo.db = database
            values = AcademicDataService._feature_values("student-1", course_id="course-a")

        self.assertEqual(values["assignments_assigned"], 1.0)
        self.assertEqual(values["assignments_submitted"], 1.0)
        self.assertEqual(values["assignment_completion_rate"], 100.0)


if __name__ == "__main__":
    unittest.main()
