"""
scripts/seed_admin.py
=====================
Seed / Reset the configured admin account in MongoDB with a valid Werkzeug hash.
"""
import os
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

def seed_all_admins():
    if os.environ.get("ALLOW_ADMIN_SEED", "").lower() != "true":
        print("[ERROR] Set ALLOW_ADMIN_SEED=true to explicitly authorize admin seeding.")
        return False

    name = (os.environ.get("ADMIN_NAME") or "").strip()
    email = (os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD") or ""
    if not name or not email or len(password) < 12:
        print("[ERROR] ADMIN_NAME, ADMIN_EMAIL, and an ADMIN_PASSWORD of at least 12 characters are required.")
        return False

    uri = os.environ.get("MONGO_URI")
    if not uri:
        print("[ERROR] MONGO_URI is not set in environment.")
        return False

    print(f"[*] Connecting to MongoDB...")
    client = MongoClient(uri, serverSelectionTimeoutMS=8000, connectTimeoutMS=8000)
    try:
        client.admin.command("ping")

        db = client.get_default_database()
        if db is None:
            print("[ERROR] MONGO_URI must specify the intended database.")
            return False
        client.admin.command("ping")

        admin_account = {
            "name": name,
            "email": email,
            "password": password,
            "role": "admin",
            "department": "Management",
            "status": "approved"
        }
        existing = db.users.find_one({"email": email})
        if existing and existing.get("role") != "admin":
            print("[ERROR] The configured email is already assigned to a non-admin account.")
            return False

        password_hash = generate_password_hash(password)
        doc = {
            "name": name,
            "email": email,
            "username": email,
            "password_hash": password_hash,
            "role": admin_account["role"],
            "department": admin_account["department"],
            "status": admin_account["status"],
            "updated_at": datetime.now(timezone.utc),
        }
        db.users.update_one(
            {"email": email},
            {"$set": doc, "$setOnInsert": {"created_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        fetched = db.users.find_one({"email": email})
        assert fetched is not None and check_password_hash(fetched["password_hash"], password)

        print("\n" + "=" * 65)
        print(f"Configured admin account is ready in database '{db.name}'.")
        print("=" * 65 + "\n")
        return True
    except Exception as error:
        print(f"[ERROR] Database operation failed ({type(error).__name__}).")
        return False
    finally:
        client.close()

if __name__ == "__main__":
    seed_all_admins()

