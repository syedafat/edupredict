import unittest
from unittest.mock import patch

from routes.teacher_routes import _authorized_enrollment, _normalize_attendance_status


class TeacherWorkflowContractTests(unittest.TestCase):
    def test_attendance_status_contract(self):
        self.assertEqual(_normalize_attendance_status("present"), "present")
        self.assertEqual(_normalize_attendance_status("false"), "absent")
        self.assertEqual(_normalize_attendance_status("late"), "late")
        self.assertEqual(_normalize_attendance_status("excused"), "excused")
        self.assertIsNone(_normalize_attendance_status("unknown"))

    @patch("routes.teacher_routes.AcademicDataService.active_enrollments")
    @patch("routes.teacher_routes._teacher_courses")
    def test_teacher_can_only_write_to_active_enrollment(self, teacher_courses, active_enrollments):
        teacher_courses.return_value = [{"_id": "course-a"}]
        active_enrollments.return_value = [{"course_id": "course-a", "student_id": "student-a", "status": "active"}]

        self.assertTrue(_authorized_enrollment("course-a", "student-a"))
        self.assertFalse(_authorized_enrollment("course-b", "student-a"))
        self.assertFalse(_authorized_enrollment("course-a", "student-b"))


if __name__ == "__main__":
    unittest.main()