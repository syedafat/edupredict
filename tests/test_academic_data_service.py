import unittest
from unittest.mock import patch

from bson import ObjectId

from services.academic_data_service import AcademicDataService


class FakeCollection:
    def __init__(self, documents):
        self.documents = documents
        self.updates = []

    def find(self, query, projection=None):
        if "role" in query:
            ids = set(query.get("_id", {}).get("$in", []))
            return [
                document for document in self.documents
                if document.get("_id") in ids
                and document.get("role") == query["role"]
                and document.get("status") not in query["status"]["$nin"]
            ]
        if "course_id" in query:
            return [
                document for document in self.documents
                if document.get("course_id") in query["course_id"]["$in"]
                and document.get("status") in query["status"]["$in"]
            ]
        return []

    def update_one(self, query, update, upsert=False):
        self.updates.append((query, update, upsert))

    def update_many(self, query, update):
        self.updates.append((query, update, False))


class FakeDatabase:
    def __init__(self, users, enrollments):
        self.users = FakeCollection(users)
        self.enrollments = FakeCollection(enrollments)


class AcademicDataServiceTests(unittest.TestCase):
    def test_upsert_enrollments_activates_valid_students_and_withdraws_removed(self):
        course_id = str(ObjectId())
        retained = ObjectId()
        removed = ObjectId()
        database = FakeDatabase(
            [
                {"_id": retained, "role": "student", "status": "approved"},
                {"_id": removed, "role": "student", "status": "approved"},
            ],
            [
                {"course_id": course_id, "student_id": str(removed), "status": "active"},
            ],
        )

        with patch.object(AcademicDataService, "now") as now, patch("services.academic_data_service.mongo") as mongo:
            now.return_value.year = 2026
            mongo.db = database
            result = AcademicDataService.upsert_enrollments(course_id, [str(retained)], changed_by="admin")

        self.assertEqual(result, (1, 1))
        self.assertEqual(len(database.enrollments.updates), 2)
        self.assertEqual(database.enrollments.updates[0][0]["student_id"], str(retained))
        self.assertEqual(database.enrollments.updates[1][0]["student_id"]["$in"], [str(removed)])


if __name__ == "__main__":
    unittest.main()