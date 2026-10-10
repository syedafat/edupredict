"""Explicitly migrate embedded course rosters into enrollment records.

Run only after taking a verified backup and reviewing the target database.
"""
import os

from app import create_app
from models import mongo
from services.academic_data_service import AcademicDataService


def main():
    if os.environ.get("RUN_LEGACY_ROSTER_MIGRATION", "").lower() != "true":
        raise SystemExit("Set RUN_LEGACY_ROSTER_MIGRATION=true to authorize this migration.")
    app = create_app()
    with app.app_context():
        mongo.cx.admin.command("ping")
        count = AcademicDataService.migrate_legacy_course_rosters()
    print(f"Migrated {count} course roster record(s).")


if __name__ == "__main__":
    main()
