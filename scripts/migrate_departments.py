import os
from pathlib import Path
from dotenv import load_dotenv
from bson import ObjectId
from datetime import datetime, timezone
from pymongo import MongoClient

# Load environment variables from .env
env_path = Path(__file__).resolve().parent.parent / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

def get_db():
    try:
        from flask import current_app
        if current_app:
            from models import mongo
            if mongo.db is not None:
                return mongo.db
    except Exception:
        pass

    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        raise RuntimeError("MONGO_URI must be explicitly set before running this migration.")
    client = MongoClient(mongo_uri)
    db = client.get_default_database()
    if db is None:
        client.close()
        raise RuntimeError("MONGO_URI must specify the intended database.")
    return db

def standardize_dept_name(name):
    if not name:
        return "General"
    cleaned = str(name).strip()
    mapping = {
        "cs": "Computer Science",
        "cse": "Computer Science",
        "comp sci": "Computer Science",
        "computer science": "Computer Science",
        "se": "Software Engineering",
        "software engineer": "Software Engineering",
        "software engineering": "Software Engineering",
        "ai": "Artificial Intelligence",
        "artificial intelligence": "Artificial Intelligence",
        "ds": "Data Science",
        "data science": "Data Science",
        "it": "Information Technology",
        "information technology": "Information Technology",
        "cyber": "Cybersecurity",
        "cybersecurity": "Cybersecurity",
    }
    return mapping.get(cleaned.lower(), cleaned)

def migrate_course_departments():
    db = get_db()
    departments_coll = db["departments"]
    courses_coll = db["courses"]
    
    # 1. Build lookup maps for existing departments
    dept_by_id = {}
    dept_by_name = {}
    dept_by_code = {}
    
    for d in departments_coll.find():
        d_id = d["_id"]
        name = d.get("name", "").strip()
        dept_by_id[d_id] = d
        if name:
            dept_by_name[name.lower()] = d
        for code in d.get("legacy_codes", []):
            if code:
                dept_by_code[str(code).strip().lower()] = d
                
    total_courses = courses_coll.count_documents({})
    updated_count = 0
    now = datetime.now(timezone.utc)
    
    for course in courses_coll.find():
        course_id = course["_id"]
        raw_dept_id = course.get("department_id")
        legacy_dept_str = str(course.get("department", "") or "").strip()
        
        target_dept = None
        
        # Check if department_id is already a valid ObjectId or valid string reference
        if raw_dept_id:
            try:
                obj_id = raw_dept_id if isinstance(raw_dept_id, ObjectId) else ObjectId(str(raw_dept_id))
                if obj_id in dept_by_id:
                    target_dept = dept_by_id[obj_id]
            except Exception:
                pass
                
        # If not resolved yet, match by legacy string name or code
        if not target_dept and legacy_dept_str:
            std_name = standardize_dept_name(legacy_dept_str)
            target_dept = dept_by_name.get(std_name.lower()) or dept_by_name.get(legacy_dept_str.lower()) or dept_by_code.get(legacy_dept_str.lower())
            
            # If still not found, create new department in departments collection
            if not target_dept:
                legacy_codes = []
                if legacy_dept_str.lower() != std_name.lower():
                    legacy_codes.append(legacy_dept_str.lower())
                if std_name == "Software Engineering" and "se" not in legacy_codes:
                    legacy_codes.append("se")
                elif std_name == "Computer Science" and "cs" not in legacy_codes:
                    legacy_codes.append("cs")
                elif std_name == "Artificial Intelligence" and "ai" not in legacy_codes:
                    legacy_codes.append("ai")
                elif std_name == "Data Science" and "ds" not in legacy_codes:
                    legacy_codes.append("ds")

                new_dept_doc = {
                    "name": std_name,
                    "legacy_codes": legacy_codes,
                    "created_at": now,
                    "updated_at": now,
                }
                res = departments_coll.insert_one(new_dept_doc)
                new_dept_doc["_id"] = res.inserted_id
                target_dept = new_dept_doc
                
                dept_by_id[target_dept["_id"]] = target_dept
                dept_by_name[std_name.lower()] = target_dept
                if legacy_dept_str:
                    dept_by_code[legacy_dept_str.lower()] = target_dept
                for c in legacy_codes:
                    dept_by_code[c] = target_dept
        
        if target_dept:
            new_dept_id = target_dept["_id"]
            new_dept_name = target_dept["name"]
            
            needs_update = (
                course.get("department_id") != new_dept_id or
                course.get("department") != new_dept_name
            )
            
            if needs_update:
                courses_coll.update_one(
                    {"_id": course_id},
                    {
                        "$set": {
                            "department_id": new_dept_id,
                            "department": new_dept_name,
                            "updated_at": now
                        }
                    }
                )
                updated_count += 1

    print(f"Migration completed: {updated_count} out of {total_courses} courses updated.")
    return {
        "status": "success",
        "updated": updated_count,
        "total": total_courses
    }

if __name__ == "__main__":
    migrate_course_departments()

