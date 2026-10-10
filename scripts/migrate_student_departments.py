"""
migrate_student_departments.py
==============================
One-time migration: iterate every course and call
AcademicDataService.sync_student_departments() so that enrolled
students automatically inherit the correct department from their course.

Run from the project root:
    python scripts/migrate_student_departments.py

The script is idempotent -- running it multiple times is safe because
sync_student_departments() skips students whose department is already correct.
"""

import sys
import os

# ---------------------------------------------------------------------------
# Make sure the project root is on sys.path so imports resolve correctly
# regardless of where the script is launched from.
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Load .env BEFORE importing anything that reads environment variables.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    print("[*] .env loaded")
except ImportError:
    print("[!] python-dotenv not installed -- relying on shell environment variables")

# ---------------------------------------------------------------------------
# Bootstrap Flask app context
# ---------------------------------------------------------------------------
from app import create_app  # noqa: E402  (import after sys.path fix)
from models import mongo  # noqa: E402
from services.academic_data_service import AcademicDataService  # noqa: E402

app = create_app()

# ---------------------------------------------------------------------------
# Migration logic
# ---------------------------------------------------------------------------
def run_migration():
    total_courses = 0
    total_students_updated = 0
    skipped_no_dept = 0

    print("\n[*] Starting student department migration ...\n")

    courses = list(mongo.db.courses.find({}))
    print(f"[*] Found {len(courses)} course(s) in MongoDB.\n")

    for course in courses:
        course_id   = str(course.get("_id", ""))
        code        = course.get("code", "?")
        title       = course.get("title", "Untitled")
        dept_name   = course.get("department", "")
        dept_id     = course.get("department_id")

        # Skip courses that have no department information at all.
        if not dept_name and not dept_id:
            print(f"  [!] SKIP  [{code}] {title} -- no department set on course")
            skipped_no_dept += 1
            continue

        updated = AcademicDataService.sync_student_departments(course)
        total_courses += 1
        total_students_updated += updated

        dept_label = dept_name or str(dept_id)
        if updated:
            print(f"  [+] UPDATED {updated:>3} student(s)  |  [{code}] {title}  ->  {dept_label}")
        else:
            print(f"  [-] No changes needed  |  [{code}] {title}  ->  {dept_label}")

    print("\n" + "=" * 60)
    print(f"  Courses processed        : {total_courses}")
    print(f"  Courses skipped (no dept): {skipped_no_dept}")
    print(f"  Student records updated  : {total_students_updated}")
    print("=" * 60)
    print("[*] Migration complete.\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    with app.app_context():
        run_migration()

