"""
seed_subjects.py
================
Seed initial subjects for courses in EduPredict.
Links subjects to courses and departments with codes and descriptions.

Usage:
    python scripts/seed_subjects.py
"""

import os
import sys
from datetime import datetime, timezone
from bson import ObjectId

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    print("[*] .env loaded")
except ImportError:
    print("[!] python-dotenv not installed -- reading environment")

from pymongo import MongoClient

DEFAULT_SUBJECTS_BY_COURSE_CODE = {
    "CS-101": [
        {
            "name": "Programming Fundamentals",
            "code": "CS101-PF",
            "description": "Core concepts of structured programming, control flow, loops, and functions.",
        },
        {
            "name": "Data Structures & Algorithms",
            "code": "CS101-DSA",
            "description": "Linear and hierarchical data structures, search and sort algorithms, complexity analysis.",
        },
        {
            "name": "Computer Architecture",
            "code": "CS101-CA",
            "description": "Digital logic, processor organization, memory hierarchy, and I/O systems.",
        },
    ],
    "2309B5": [
        {
            "name": "Software Requirements Engineering",
            "code": "SE-SRE",
            "description": "Requirements gathering, modeling, specification, and validation techniques.",
        },
        {
            "name": "Software Architecture & Design",
            "code": "SE-SAD",
            "description": "Architectural styles, design patterns, modularity, and microservices.",
        },
        {
            "name": "Software Quality Assurance & Testing",
            "code": "SE-SQA",
            "description": "Unit testing, integration testing, CI/CD pipelines, and automated test suites.",
        },
    ],
    "AI-401": [
        {
            "name": "Supervised & Unsupervised Learning",
            "code": "AI-SUL",
            "description": "Regression, classification, clustering, dimensionality reduction, and model evaluation.",
        },
        {
            "name": "Deep Learning & Neural Networks",
            "code": "AI-DNN",
            "description": "Feedforward networks, backpropagation, CNNs, RNNs, and Transformers.",
        },
        {
            "name": "Natural Language Processing",
            "code": "AI-NLP",
            "description": "Text tokenization, embeddings, language modeling, and sentiment analysis.",
        },
    ],
    "DS-302": [
        {
            "name": "Big Data Technologies & Spark",
            "code": "DS-BDT",
            "description": "Distributed computing, PySpark, MapReduce paradigms, and HDFS pipelines.",
        },
        {
            "name": "Statistical Inference & Modeling",
            "code": "DS-SIM",
            "description": "Probability distributions, hypothesis testing, Bayesian estimation, and ANOVA.",
        },
        {
            "name": "Data Visualization & Storytelling",
            "code": "DS-DVS",
            "description": "Exploratory data analysis, interactive dashboards, and visual analytics.",
        },
    ],
    "IT-101": [
        {
            "name": "Network Fundamentals & Protocols",
            "code": "IT-NFP",
            "description": "OSI and TCP/IP models, routing, switching, DNS, and IP addressing.",
        },
        {
            "name": "Database Management Systems",
            "code": "IT-DBMS",
            "description": "Relational data modeling, SQL queries, NoSQL systems, and indexing strategies.",
        },
        {
            "name": "Cybersecurity & Cloud Essentials",
            "code": "IT-CCE",
            "description": "Security postures, encryption, identity management, and cloud infrastructure.",
        },
    ],
}


def seed_subjects():
    environments = {
        os.environ.get("APP_ENV", "").lower(),
        os.environ.get("FLASK_ENV", "").lower(),
    }
    if "production" in environments or os.environ.get("ALLOW_DEMO_SEED", "").lower() != "true":
        print("[!] Subject seeding requires explicit non-production demo authorization.")
        return 0

    mongo_uri = os.environ.get("MONGO_URI")
    if not mongo_uri:
        print("[!] ERROR: MONGO_URI is missing from environment.")
        return 0

    from pymongo.uri_parser import parse_uri
    database_name = parse_uri(mongo_uri, validate=True).get("database")
    if not database_name or database_name != os.environ.get("DEMO_SEED_DATABASE", "").strip():
        print("[!] ERROR: DEMO_SEED_DATABASE must match the database named in MONGO_URI.")
        return 0

    client = MongoClient(mongo_uri)
    db = client.get_default_database()

    # Create indexes for subjects collection
    db.subjects.create_index([("course_id", 1), ("code", 1)], unique=True)
    db.subjects.create_index([("course_id", 1)])
    db.subjects.create_index([("department_id", 1)])
    print("[*] Subjects indexes verified.")

    courses = list(db.courses.find({}))
    print(f"[*] Found {len(courses)} course(s) in database.")

    total_created = 0
    total_existing = 0

    now = datetime.now(timezone.utc)

    for course in courses:
        code = course.get("code")
        title = course.get("title")
        course_id = course["_id"]
        dept_id = course.get("department_id")
        dept_name = course.get("department", "General Studies")

        # Resolve department_id if missing
        if not dept_id and dept_name:
            dept_doc = db.departments.find_one({"name": dept_name})
            if dept_doc:
                dept_id = dept_doc["_id"]

        subjects_to_seed = DEFAULT_SUBJECTS_BY_COURSE_CODE.get(code)
        if not subjects_to_seed:
            # Generate 2 generic subjects for courses without specific predefined items
            subjects_to_seed = [
                {
                    "name": f"{title} - Core Theory",
                    "code": f"{code}-TH",
                    "description": f"Theoretical principles and foundational knowledge for {title}.",
                },
                {
                    "name": f"{title} - Practical Lab",
                    "code": f"{code}-LAB",
                    "description": f"Practical exercises, labs, and applied projects for {title}.",
                },
            ]

        for s_data in subjects_to_seed:
            existing = db.subjects.find_one({"course_id": course_id, "code": s_data["code"]})
            if existing:
                total_existing += 1
                continue

            doc = {
                "name": s_data["name"],
                "code": s_data["code"],
                "description": s_data["description"],
                "course_id": course_id,
                "course_code": code,
                "course_title": title,
                "department_id": dept_id,
                "department_name": dept_name,
                "status": "active",
                "created_at": now,
                "updated_at": now,
            }
            db.subjects.insert_one(doc)
            total_created += 1
            print(f"  [+] Created Subject: [{s_data['code']}] {s_data['name']} (Course: {code})")

    print("\n" + "=" * 60)
    print(f"  New Subjects Created : {total_created}")
    print(f"  Existing Subjects    : {total_existing}")
    print(f"  Total Active Subjects: {db.subjects.count_documents({'status': 'active'})}")
    print("=" * 60)
    return total_created


if __name__ == "__main__":
    seed_subjects()

