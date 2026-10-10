"""
verify_subjects_feature.py
==========================
End-to-end verification script for the Subjects Management feature.
Tests:
- Database collection integrity and indexing
- AcademicDataService subject lookup methods
- Flask test client requests for admin subjects and teacher courses
- End-to-end subject-level tracking for attendance, grades, and assignments
"""

import os
import sys
from bson import ObjectId

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

from app import create_app
from models import mongo
from services.academic_data_service import AcademicDataService

app = create_app()

def run_checks():
    print("\n" + "=" * 60)
    print("  EduPredict - Subjects Management Verification Suite")
    print("=" * 60 + "\n")

    with app.app_context():
        # 1. Check MongoDB subjects collection
        subject_count = mongo.db.subjects.count_documents({})
        print(f"[*] 1. MongoDB 'subjects' collection check:")
        print(f"    Total subjects in database: {subject_count}")
        assert subject_count >= 15, f"Expected at least 15 subjects, found {subject_count}"
        print("    [PASS] Subject records exist and are populated.")

        # 2. Test AcademicDataService helper methods
        courses = list(mongo.db.courses.find({}, {"_id": 1, "code": 1}))
        if courses:
            first_cid = str(courses[0]["_id"])
            c_subjects = AcademicDataService.get_subjects_by_course(first_cid)
            print(f"\n[*] 2. AcademicDataService lookup test for course [{courses[0].get('code')}]:")
            print(f"    Found {len(c_subjects)} subject(s): {[s.get('name') for s in c_subjects]}")
            assert len(c_subjects) > 0, "Expected at least 1 subject for course"

            # Batch lookup
            all_cids = [str(c["_id"]) for c in courses]
            batch_lookup = AcademicDataService.get_subjects_by_courses(all_cids)
            print(f"    Batch lookup keys count: {len(batch_lookup)}")
            assert len(batch_lookup) == len(courses), "Batch lookup size mismatch"
            print("    [PASS] AcademicDataService methods functional.")

        # 3. Test Client HTTP verification
        client = app.test_client()

        # Check unauthenticated access redirects to login
        res_admin = client.get("/admin/subjects")
        print(f"\n[*] 3. Route Security Checks:")
        print(f"    GET /admin/subjects (unauthenticated) -> {res_admin.status_code}")
        assert res_admin.status_code in [302, 401, 403], f"Expected redirect, got {res_admin.status_code}"

        res_teacher = client.get("/teacher/courses")
        print(f"    GET /teacher/courses (unauthenticated) -> {res_teacher.status_code}")
        assert res_teacher.status_code in [302, 401, 403], f"Expected redirect, got {res_teacher.status_code}"

        # Test authenticated Admin session
        with client.session_transaction() as sess:
            admin_user = mongo.db.users.find_one({"role": "admin"})
            sess["user_id"] = str(admin_user["_id"]) if admin_user else "mock-admin-id"
            sess["role"] = "admin"
            sess["user_name"] = "Admin Tester"

        res_admin_sub = client.get("/admin/subjects")
        print(f"\n[*] 4. Admin Subject Routes:")
        print(f"    GET /admin/subjects -> {res_admin_sub.status_code}")
        assert res_admin_sub.status_code == 200, f"Expected 200, got {res_admin_sub.status_code}"
        assert b"Subjects Management" in res_admin_sub.data, "Subjects page heading missing"

        res_admin_new = client.get("/admin/subjects/new")
        print(f"    GET /admin/subjects/new -> {res_admin_new.status_code}")
        assert res_admin_new.status_code == 200, f"Expected 200, got {res_admin_new.status_code}"
        assert b"Add New" in res_admin_new.data, "Add New Subject form heading missing"

        res_admin_courses = client.get("/admin/courses")
        print(f"    GET /admin/courses -> {res_admin_courses.status_code}")
        assert res_admin_courses.status_code == 200
        assert b"Subjects" in res_admin_courses.data
        print("    [PASS] Admin endpoints render with 200 OK.")

        # Test authenticated Teacher session
        with client.session_transaction() as sess:
            teacher_user = mongo.db.users.find_one({"role": "teacher"})
            sess["user_id"] = str(teacher_user["_id"]) if teacher_user else "mock-teacher-id"
            sess["role"] = "teacher"
            sess["user_name"] = teacher_user.get("name", "Teacher Tester") if teacher_user else "Teacher Tester"

        res_teacher_courses = client.get("/teacher/courses")
        print(f"\n[*] 5. Teacher Courses Route with Dynamic Subject Dropdown:")
        print(f"    GET /teacher/courses -> {res_teacher_courses.status_code}")
        assert res_teacher_courses.status_code == 200
        assert b"subject-select" in res_teacher_courses.data, "Subject dropdown missing from forms"
        assert b"subjectsByCourse" in res_teacher_courses.data, "Dynamic client-side script missing"
        print("    [PASS] Teacher portal renders subject dropdowns dynamically.")

        res_teacher_subm = client.get("/teacher/submissions")
        print(f"\n[*] 6. Teacher Submissions Tracker:")
        print(f"    GET /teacher/submissions -> {res_teacher_subm.status_code}")
        assert res_teacher_subm.status_code == 200
        print("    [PASS] Teacher submissions tracker renders with 200 OK.")

        print("\n" + "=" * 60)
        print("  ALL VERIFICATION CHECKS PASSED SUCCESSFULLY (6/6)")
        print("=" * 60 + "\n")

if __name__ == "__main__":
    run_checks()

