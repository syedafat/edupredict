"""
seed_data.py
============
Enterprise Database Seeding Script for EduPredict Platform.

Populates a pristine B2B demo environment for 'Demo University':
1. Academic Departments (CS, SE, DS, AI, BA).
2. Faculty / Teachers with course and department assignments.
3. Courses linked to departments and teachers.
4. Modular Subjects / Labs linked directly to courses.
5. Students with active enrollments and distinct academic profiles:
   - Alex Turner (High Performer: ~96% attendance, ~92% grade)
   - Fatima Noor (Strong Performer: ~90% attendance, ~84% grade)
   - Marcus Chen (Moderate Performer: ~80% attendance, ~72% grade)
   - Liam Wilson (At-Risk Student: ~56% attendance, ~42% grade)
   - Sophia Rodriguez (Anomaly Profile: ~95% attendance, ~35% assignment completion)
6. Authentic academic records: Attendance, Grades, Assignments, and Submissions.
7. Executes canonical ML training and generates real baseline predictions.
"""

import os
import sys
import zipfile
from uuid import uuid4
from datetime import datetime, timezone, timedelta
from pathlib import Path
from bson import ObjectId
from werkzeug.security import generate_password_hash

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

from pymongo import MongoClient
from models import mongo
from services.academic_data_service import AcademicDataService
from train_models import train_and_save_all_models


def get_database():
    uri = os.environ.get("MONGO_URI")
    confirmed_database = os.environ.get("DEMO_SEED_DATABASE", "").strip()
    if not uri or not confirmed_database:
        raise RuntimeError("MONGO_URI and DEMO_SEED_DATABASE are required for demo seeding.")
    from pymongo.uri_parser import parse_uri
    database_name = parse_uri(uri, validate=True).get("database")
    if not database_name or database_name != confirmed_database:
        raise RuntimeError("DEMO_SEED_DATABASE must exactly match the database named in MONGO_URI.")
    client = MongoClient(uri)
    return client.get_database(database_name)


def seed_demo_environment():
    environments = {
        os.environ.get("APP_ENV", "").lower(),
        os.environ.get("FLASK_ENV", "").lower(),
    }
    if "production" in environments:
        raise RuntimeError("Demo seeding is disabled in production.")
    if os.environ.get("ALLOW_DEMO_SEED", "").lower() != "true":
        raise RuntimeError("Set ALLOW_DEMO_SEED=true to explicitly authorize destructive demo seeding.")
    demo_password = os.environ.get("DEMO_SEED_PASSWORD") or ""
    if len(demo_password) < 12:
        raise RuntimeError("DEMO_SEED_PASSWORD must be set and contain at least 12 characters.")

    db = get_database()
    mongo.db = db
    print("=" * 70)
    print("[*] Seeding Clean B2B Demo Environment: Demo University...")
    print("=" * 70)

    # 1. Clean previous demo data safely
    demo_collections = [
        "departments", "courses", "subjects", "enrollments",
        "grades", "attendance", "assignments", "submissions",
        "student_features", "predictions", "anomalies",
        "notifications", "support_tickets", "reports", "system_logs", "users"
    ]
    for col_name in demo_collections:
        db[col_name].delete_many({})
    print("[+] Cleared old ephemeral test collections.")

    now = datetime.now(timezone.utc)
    password_hash = generate_password_hash(demo_password)

    # 2. Seed Admin and Analyst
    admin_id = db.users.insert_one({
        "name": "System Administrator",
        "email": "admin@edupredict.com",
        "password_hash": password_hash,
        "role": "admin",
        "status": "approved",
        "department": "Institutional Administration",
        "created_at": now,
    }).inserted_id

    analyst_id = db.users.insert_one({
        "name": "Institutional Analyst",
        "email": "analyst@demouni.edu",
        "password_hash": password_hash,
        "role": "analyst",
        "status": "approved",
        "department": "All",
        "created_at": now,
    }).inserted_id
    print(f"[+] Admin and Analyst accounts provisioned.")

    # 3. Seed Departments
    departments_spec = [
        {"name": "Computer Science", "legacy_codes": ["cs", "cse"]},
        {"name": "Software Engineering", "legacy_codes": ["se", "swe"]},
        {"name": "Data Science", "legacy_codes": ["ds", "bda"]},
        {"name": "Artificial Intelligence", "legacy_codes": ["ai", "aiml"]},
        {"name": "Business Administration", "legacy_codes": ["ba", "bba"]},
    ]
    dept_map = {}
    for d in departments_spec:
        res = db.departments.insert_one({
            "name": d["name"],
            "legacy_codes": d["legacy_codes"],
            "created_at": now,
            "created_by": str(admin_id),
        })
        dept_map[d["name"]] = res.inserted_id
    print(f"[+] Seeded {len(dept_map)} Academic Departments.")

    # 4. Seed Faculty / Teachers
    teachers_spec = [
        {"name": "Prof. Ahmed Raza", "email": "ahmed.raza@demouni.edu", "department": "Computer Science"},
        {"name": "Dr. Zehra Malik", "email": "dr.zehra@demouni.edu", "department": "Software Engineering"},
        {"name": "Dr. John Smith", "email": "dr.smith@demouni.edu", "department": "Data Science"},
        {"name": "Dr. Maria Khan", "email": "dr.maria@demouni.edu", "department": "Business Administration"},
    ]
    teacher_map = {}
    for t in teachers_spec:
        res = db.users.insert_one({
            "name": t["name"],
            "email": t["email"],
            "password_hash": password_hash,
            "role": "teacher",
            "status": "approved",
            "department": t["department"],
            "department_id": dept_map.get(t["department"]),
            "created_at": now,
        })
        teacher_map[t["email"]] = res.inserted_id
    print(f"[+] Seeded {len(teacher_map)} Faculty Members.")

    # 5. Seed Students
    students_spec = [
        {
            "name": "Alex Turner",
            "email": "alex.turner@demouni.edu",
            "student_id": "STD-2026-001",
            "department": "Computer Science",
            "gpa": 3.85,
            "profile_type": "high_performer",
        },
        {
            "name": "Fatima Noor",
            "email": "fatima.noor@demouni.edu",
            "student_id": "STD-2026-002",
            "department": "Computer Science",
            "gpa": 3.50,
            "profile_type": "strong_performer",
        },
        {
            "name": "Marcus Chen",
            "email": "marcus.chen@demouni.edu",
            "student_id": "STD-2026-003",
            "department": "Software Engineering",
            "gpa": 2.95,
            "profile_type": "moderate_performer",
        },
        {
            "name": "Liam Wilson",
            "email": "liam.wilson@demouni.edu",
            "student_id": "STD-2026-004",
            "department": "Data Science",
            "gpa": 1.90,
            "profile_type": "at_risk",
        },
        {
            "name": "Sophia Rodriguez",
            "email": "sophia.rodriguez@demouni.edu",
            "student_id": "STD-2026-005",
            "department": "Business Administration",
            "gpa": 3.20,
            "profile_type": "anomaly_pattern",
        },
    ]
    student_map = {}
    for s in students_spec:
        res = db.users.insert_one({
            "name": s["name"],
            "email": s["email"],
            "password_hash": password_hash,
            "role": "student",
            "status": "approved",
            "student_id": s["student_id"],
            "department": s["department"],
            "department_id": dept_map.get(s["department"]),
            "gpa": s["gpa"],
            "created_at": now,
        })
        student_map[s["email"]] = {
            "id": res.inserted_id,
            "spec": s,
        }
    print(f"[+] Seeded {len(student_map)} Student Profiles.")

    # 6. Seed Courses
    courses_spec = [
        {
            "code": "CS-101",
            "title": "Introduction to Programming",
            "department": "Computer Science",
            "credits": 4,
            "semester": "Fall 2026",
            "teacher_email": "ahmed.raza@demouni.edu",
            "students": ["alex.turner@demouni.edu", "fatima.noor@demouni.edu", "marcus.chen@demouni.edu", "liam.wilson@demouni.edu"],
        },
        {
            "code": "CS-201",
            "title": "Database Systems",
            "department": "Computer Science",
            "credits": 4,
            "semester": "Fall 2026",
            "teacher_email": "ahmed.raza@demouni.edu",
            "students": ["alex.turner@demouni.edu", "fatima.noor@demouni.edu", "marcus.chen@demouni.edu"],
        },
        {
            "code": "SE-201",
            "title": "Software Engineering Principles",
            "department": "Software Engineering",
            "credits": 3,
            "semester": "Fall 2026",
            "teacher_email": "dr.zehra@demouni.edu",
            "students": ["alex.turner@demouni.edu", "marcus.chen@demouni.edu", "sophia.rodriguez@demouni.edu"],
        },
        {
            "code": "DS-301",
            "title": "Applied Machine Learning",
            "department": "Data Science",
            "credits": 4,
            "semester": "Fall 2026",
            "teacher_email": "dr.smith@demouni.edu",
            "students": ["fatima.noor@demouni.edu", "liam.wilson@demouni.edu"],
        },
        {
            "code": "BA-101",
            "title": "Business Analytics",
            "department": "Business Administration",
            "credits": 3,
            "semester": "Fall 2026",
            "teacher_email": "dr.maria@demouni.edu",
            "students": ["sophia.rodriguez@demouni.edu", "marcus.chen@demouni.edu"],
        },
    ]

    course_map = {}
    for c in courses_spec:
        teacher_id_val = teacher_map[c["teacher_email"]]
        dept_id_val = dept_map[c["department"]]
        c_res = db.courses.insert_one({
            "code": c["code"],
            "title": c["title"],
            "department": c["department"],
            "department_id": dept_id_val,
            "credits": c["credits"],
            "semester": c["semester"],
            "teacher_id": str(teacher_id_val),
            "status": "active",
            "created_at": now,
            "created_by": str(admin_id),
            "updated_at": now,
        })
        course_id = c_res.inserted_id
        course_map[c["code"]] = course_id

        # Enroll students
        student_obj_ids = [student_map[email]["id"] for email in c["students"]]
        AcademicDataService.upsert_enrollments(
            course_id,
            student_obj_ids,
            academic_year="2026",
            changed_by=str(admin_id),
        )
    print(f"[+] Seeded {len(course_map)} Courses with Active Enrollments.")

    # 7. Seed Subjects under each course
    subjects_spec = [
        # CS-101
        {"code": "CS-101-TH", "name": "Programming Fundamentals Theory", "course_code": "CS-101", "description": "Syntax, control flow, functions, OOP basics."},
        {"code": "CS-101-LAB", "name": "Programming Practical Lab", "course_code": "CS-101", "description": "Hands-on Python exercises and code debugging."},
        # CS-201
        {"code": "CS-201-TH", "name": "Relational Database Architecture", "course_code": "CS-201", "description": "Schema normalization, indexing, ER modeling."},
        {"code": "CS-201-SQL", "name": "SQL Query Design & Optimization", "course_code": "CS-201", "description": "Complex joins, subqueries, transaction locks."},
        # SE-201
        {"code": "SE-201-REQ", "name": "Requirements Engineering & Agile", "course_code": "SE-201", "description": "User stories, UML design, sprint backlogs."},
        {"code": "SE-201-QA", "name": "Software Quality Assurance & Testing", "course_code": "SE-201", "description": "Unit testing, CI pipelines, code audits."},
        # DS-301
        {"code": "DS-301-SUP", "name": "Supervised Learning & Evaluation", "course_code": "DS-301", "description": "Regression, classification, cross-validation."},
        {"code": "DS-301-EDA", "name": "Exploratory Data Analysis & Features", "course_code": "DS-301", "description": "Data cleaning, feature scaling, visualization."},
        # BA-101
        {"code": "BA-101-BI", "name": "Business Intelligence & Performance", "course_code": "BA-101", "description": "Enterprise KPIs, dashboard design, analytics."},
        {"code": "BA-101-FIN", "name": "Financial Decision Analytics", "course_code": "BA-101", "description": "Cash flow forecasting, risk metrics."},
    ]

    subject_map = {}
    for s in subjects_spec:
        cid = course_map[s["course_code"]]
        c_doc = db.courses.find_one({"_id": cid})
        s_res = db.subjects.insert_one({
            "name": s["name"],
            "code": s["code"],
            "description": s["description"],
            "course_id": cid,
            "course_code": s["course_code"],
            "course_title": c_doc.get("title", ""),
            "department_id": c_doc.get("department_id"),
            "department_name": c_doc.get("department", ""),
            "status": "active",
            "created_at": now,
            "created_by": str(admin_id),
            "updated_at": now,
        })
        subject_map[s["code"]] = s_res.inserted_id
    print(f"[+] Seeded {len(subject_map)} Modular Curriculum Subjects.")

    # 8. Create Realistic Academic Records (Attendance, Grades, Assignments, Submissions)
    print("\n[*] Generating authentic academic records across students and subjects...")
    dates = [(now - timedelta(days=i * 3)).strftime("%Y-%m-%d") for i in range(15)]

    # Submission uploads folder
    sub_folder = os.path.join(os.getcwd(), "uploads", "submissions")
    os.makedirs(sub_folder, exist_ok=True)

    for student_email, s_data in student_map.items():
        s_id = str(s_data["id"])
        profile = s_data["spec"]["profile_type"]

        # Determine target performance profiles
        if profile == "high_performer":
            att_prob = 0.96
            grade_range = (88.0, 96.0)
            submit_ratio = 1.0
            delay_days = 0.0
        elif profile == "strong_performer":
            att_prob = 0.90
            grade_range = (80.0, 88.0)
            submit_ratio = 1.0
            delay_days = 0.0
        elif profile == "moderate_performer":
            att_prob = 0.80
            grade_range = (68.0, 78.0)
            submit_ratio = 0.85
            delay_days = 1.2
        elif profile == "at_risk":
            att_prob = 0.55
            grade_range = (35.0, 48.0)
            submit_ratio = 0.40
            delay_days = 4.5
        elif profile == "anomaly_pattern":
            att_prob = 0.95
            grade_range = (65.0, 75.0)
            submit_ratio = 0.35  # High attendance but very low assignments
            delay_days = 3.0
        else:
            att_prob = 0.80
            grade_range = (70.0, 80.0)
            submit_ratio = 0.80
            delay_days = 0.0

        # Enrolled courses for this student
        enrolled_courses = AcademicDataService.get_active_student_courses(s_id)["courses"]

        for course in enrolled_courses:
            cid_str = str(course["_id"])
            teacher_id_str = str(course.get("teacher_id", admin_id))
            course_subs = AcademicDataService.get_subjects_by_course(cid_str)

            # 8a. Attendance
            for d_idx, date_val in enumerate(dates):
                sub_doc = course_subs[d_idx % len(course_subs)] if course_subs else None
                # Deterministic present check based on index & target probability
                is_present = ((d_idx * 7 + int(s_id[-2:], 16)) % 100) < (att_prob * 100)
                db.attendance.insert_one({
                    "student_id": s_id,
                    "course_id": cid_str,
                    "subject_id": str(sub_doc["_id"]) if sub_doc else None,
                    "subject_name": sub_doc.get("name") if sub_doc else None,
                    "subject_code": sub_doc.get("code") if sub_doc else None,
                    "date": date_val,
                    "present": is_present,
                    "status": "present" if is_present else "absent",
                    "teacher_id": teacher_id_str,
                    "created_at": now - timedelta(days=d_idx * 3),
                    "updated_at": now - timedelta(days=d_idx * 3),
                })

            # 8b. Grades / Assessments
            assessments = ["Quiz 1", "Midterm Exam", "Lab Assessment 1", "Assignment Evaluation"]
            for a_idx, ass_title in enumerate(assessments):
                sub_doc = course_subs[a_idx % len(course_subs)] if course_subs else None
                # Deterministic score in student's grade range
                score_val = round(grade_range[0] + ((a_idx * 11 + int(s_id[-2:], 16)) % int(grade_range[1] - grade_range[0] + 1)), 1)
                db.grades.insert_one({
                    "student_id": s_id,
                    "course_id": cid_str,
                    "subject_id": str(sub_doc["_id"]) if sub_doc else None,
                    "subject_name": sub_doc.get("name") if sub_doc else None,
                    "subject_code": sub_doc.get("code") if sub_doc else None,
                    "assessment": ass_title,
                    "score": score_val,
                    "feedback": f"Evaluated for {ass_title}.",
                    "teacher_id": teacher_id_str,
                    "created_at": now - timedelta(days=(4 - a_idx) * 7),
                    "updated_at": now - timedelta(days=(4 - a_idx) * 7),
                })

            # 8c. Assignments & Submissions
            assign_titles = ["Module Project 1", "Practical Implementation", "Research Case Study"]
            for as_idx, as_title in enumerate(assign_titles):
                sub_doc = course_subs[as_idx % len(course_subs)] if course_subs else None
                due_date_dt = now - timedelta(days=(3 - as_idx) * 5)
                due_date_str = due_date_dt.strftime("%Y-%m-%d")
                assign_key = f"{cid_str}:{str(sub_doc['_id']) if sub_doc else 'all'}:{as_title}:{due_date_str}"

                assign_doc = {
                    "student_id": s_id,
                    "course_id": cid_str,
                    "subject_id": str(sub_doc["_id"]) if sub_doc else None,
                    "subject_name": sub_doc.get("name") if sub_doc else None,
                    "subject_code": sub_doc.get("code") if sub_doc else None,
                    "assignment_key": assign_key,
                    "title": as_title,
                    "description": f"Practical assignment for {as_title}.",
                    "max_marks": 100.0,
                    "due_date": due_date_str,
                    "status": "pending",
                    "teacher_id": teacher_id_str,
                    "created_at": now - timedelta(days=20),
                    "updated_at": now - timedelta(days=20),
                }
                res_ass = db.assignments.insert_one(assign_doc)
                assign_id = res_ass.inserted_id

                # Submit if within student submit ratio
                should_submit = ((as_idx * 13 + int(s_id[-2:], 16)) % 100) < (submit_ratio * 100)
                if should_submit:
                    submitted_at = due_date_dt + timedelta(days=delay_days)
                    # Create dummy zip file
                    zip_name = f"submission_{s_id}_{assign_id}.zip"
                    zip_path = os.path.join(sub_folder, zip_name)
                    if not os.path.exists(zip_path):
                        with zipfile.ZipFile(zip_path, "w") as zf:
                            zf.writestr("solution.py", f"# Student {s_id} Solution for {as_title}\nprint('Solution')\n")

                    db.submissions.insert_one({
                        "assignment_id": str(assign_id),
                        "assignment_key": assign_key,
                        "student_id": s_id,
                        "course_id": cid_str,
                        "title": as_title,
                        "file_path": zip_path,
                        "status": "submitted",
                        "submitted_at": submitted_at,
                        "created_at": submitted_at,
                        "updated_at": submitted_at,
                    })
                    db.assignments.update_one({"_id": assign_id}, {"$set": {"status": "submitted"}})

        # Refresh student features in MongoDB
        AcademicDataService.refresh_student(s_id, changed_by=str(admin_id), reason="initial_seeding")

    print("[+] Academic records created and feature vectors generated.")

    # 9. Execute ML Training Pipeline and Generate Model Artifacts
    print("\n[*] Training ML Models on Canonical 9-Feature Dataset...")
    train_and_save_all_models()

    print("\n" + "=" * 70)
    print("[SUCCESS] B2B Demo Seeding & ML Pipeline Execution Completed!")
    print("=" * 70)


if __name__ == "__main__":
    try:
        seed_demo_environment()
    except Exception as error:
        print(f"[ERROR] Demo seeding aborted ({type(error).__name__}).")
        raise SystemExit(1) from None
