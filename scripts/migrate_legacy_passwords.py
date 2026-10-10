"""Safely migrate legacy plaintext user passwords to password_hash.

Dry-run by default. Use --apply only after taking a database backup. This
utility does not print password values or hashes and is never run at startup.
"""
import argparse
import os

from pymongo import MongoClient
from werkzeug.security import generate_password_hash


def _is_werkzeug_hash(value):
    return isinstance(value, str) and value.startswith(("pbkdf2:", "scrypt:"))


def migrate_users(collection, apply=False):
    """Return counts; update only users carrying a legacy ``password`` field."""
    scanned = migrated = removed = 0
    for user in collection.find(
        {"password": {"$exists": True}},
        {"password": 1, "password_hash": 1},
    ):
        scanned += 1
        legacy = user.get("password")
        update = {"$unset": {"password": ""}}
        if not user.get("password_hash") and legacy:
            update["$set"] = {
                "password_hash": legacy if _is_werkzeug_hash(legacy)
                else generate_password_hash(str(legacy))
            }
            migrated += 1
        else:
            removed += 1
        if apply:
            collection.update_one({"_id": user["_id"]}, update)
    return {"scanned": scanned, "migrated": migrated, "legacy_fields_removed": removed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (requires a prior backup)")
    args = parser.parse_args()
    uri = os.environ.get("MONGO_URI")
    if not uri:
        parser.error("Set MONGO_URI in the environment; credentials are never printed.")
    client = MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
    try:
        database = client.get_default_database()
        if database is None:
            parser.error("MONGO_URI must include a database name.")
        counts = migrate_users(database.users, apply=args.apply)
        mode = "Applied" if args.apply else "Dry run"
        print(f"{mode}: scanned {counts['scanned']}; would migrate {counts['migrated']}; "
              f"would remove legacy fields {counts['legacy_fields_removed']}.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
