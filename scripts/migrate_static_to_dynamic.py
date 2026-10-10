import os
from bson import ObjectId
from models import mongo


def migrate():
    """Migrate legacy department strings in courses to a dedicated 'departments' collection.
    Creates departments for distinct legacy values, updates courses to reference the new
    department IDs, and optionally creates a placeholder subject for each existing course.
    """
    # 1. Gather distinct department strings from courses
    legacy_departments = set()
    for doc in mongo.db.courses.find({"department": {"$nin": ["", None]}}, {"department": 1}):
        dept = doc.get("department")
        if dept:
            legacy_departments.add(dept.strip())

    # 2. Create departments collection entries
    dept_name_to_id = {}
    for legacy in legacy_departments:
        # Use the existing standardization helper if available
        try:
            from routes.admin_routes import standardize_department_name
            std_name = standardize_department_name(legacy)
        except Exception:
            std_name = legacy
        # Avoid duplicates by name
        existing = mongo.db.departments.find_one({"name": std_name})
        if existing:
            dept_id = existing["_id"]
        else:
            dept_id = mongo.db.departments.insert_one({
                "name": std_name,
                "legacy_codes": [legacy],
                "created_at": mongo.db.command({"serverStatus": 1})["localTime"],
                "updated_at": mongo.db.command({"serverStatus": 1})["localTime"],
            }).inserted_id
        dept_name_to_id[legacy] = dept_id

    # 3. Update courses to reference department_id instead of string
    for course in mongo.db.courses.find({"department": {"$nin": ["", None]}}):
        legacy = course.get("department")
        dept_id = dept_name_to_id.get(legacy)
        if not dept_id:
            continue
        mongo.db.courses.update_one(
            {"_id": course["_id"]},
            {
                "$set": {"department_id": dept_id},
                "$unset": {"department": ""},
                "$setOnInsert": {"updated_at": mongo.db.command({"serverStatus": 1})["localTime"]},
            },
        )

    # 4. (Optional) Create a placeholder subject for each course if none exist
    for course in mongo.db.courses.find({"subject_ids": {"$exists": False}}):
        subject_id = mongo.db.subjects.insert_one({
            "course_id": course["_id"],
            "name": f"{course.get('title', 'Untitled')} - Primary",
            "created_at": mongo.db.command({"serverStatus": 1})["localTime"],
            "updated_at": mongo.db.command({"serverStatus": 1})["localTime"],
        }).inserted_id
        mongo.db.courses.update_one({"_id": course["_id"]}, {"$set": {"subject_ids": [subject_id]}})

    print(f"Migrated {len(legacy_departments)} departments and updated {mongo.db.courses.count_documents({})} courses.")

if __name__ == "__main__":
    migrate()

