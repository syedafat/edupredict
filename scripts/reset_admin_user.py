"""
scripts/reset_admin_user.py
===========================
Force-create or update the configured admin account from .env in MongoDB.
"""
import os
from pathlib import Path
from datetime import datetime, timezone
from dotenv import load_dotenv
from pymongo import MongoClient
from werkzeug.security import generate_password_hash, check_password_hash

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")

def reset_admin():
    if os.environ.get("ALLOW_ADMIN_SEED", "").lower() != "true":
        print("[ERROR] Set ALLOW_ADMIN_SEED=true to explicitly authorize an admin credential reset.")
        return False

    email = (os.environ.get("ADMIN_EMAIL") or "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD") or ""
    name = (os.environ.get("ADMIN_NAME") or "").strip()
    if not email or not name or len(password) < 12:
        print("[ERROR] ADMIN_NAME, ADMIN_EMAIL, and an ADMIN_PASSWORD of at least 12 characters are required.")
        return False
    role = "admin"
    status = "approved"

    uri = os.environ.get("MONGO_URI")
    if not uri:
        print("[ERROR] MONGO_URI is not set in environment.")
        return False

    print(f"[*] Connecting to MongoDB...")
    client = MongoClient(uri, serverSelectionTimeoutMS=8000, connectTimeoutMS=8000)
    try:
        client.admin.command("ping")

        pwd_hash = generate_password_hash(password)

        admin_doc = {
            "name": name,
            "email": email.strip().lower(),
            "username": email.strip().lower(),
            "password_hash": pwd_hash,
            "role": role,
            "department": "Administration",
            "status": status,
            "updated_at": datetime.now(timezone.utc),
        }

        db = client.get_default_database()
        if db is None:
            print("[ERROR] MONGO_URI must specify the intended database.")
            return False
        client.admin.command("ping")
        existing = db.users.find_one({"email": email})
        if existing and existing.get("role") != "admin":
            print("[ERROR] The configured email is already assigned to a non-admin account.")
            return False
        result = db.users.update_one(
            {"email": email},
            {
                "$set": admin_doc,
                "$unset": {"password": ""},
                "$setOnInsert": {"created_at": datetime.now(timezone.utc)}
            },
            upsert=True
        )
        fetched = db.users.find_one({"email": email})
        assert fetched is not None and check_password_hash(fetched["password_hash"], password)
        print(f"[+] Configured admin reset in database '{db.name}' ({result.modified_count} modified).")

        print("\n" + "=" * 60)
        print("SUCCESS! CONFIGURED ADMIN USER IS READY FOR LOGIN:")
        print(f"  Email:    {email}")
        print(f"  Role:     {role}")
        print(f"  Status:   {status}")
        print("  Password: stored from ADMIN_PASSWORD in the active .env file")
        print("=" * 60 + "\n")
        return True
    except Exception as error:
        print(f"[ERROR] Admin reset failed ({type(error).__name__}).")
        return False
    finally:
        client.close()

if __name__ == "__main__":
    reset_admin()
