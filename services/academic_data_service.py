from datetime import datetime, timezone
from uuid import uuid4

from bson import ObjectId

from models import mongo
from ml.model_manager import ModelManager
from services.alert_service import AlertService


class AcademicDataService:
    """Own the educational data contract from enrollment through prediction."""

    FEATURE_ORDER = (
        "attendance_rate",
        "average_score",
        "lms_activity",
        "gpa",
        "assignments_assigned",
        "assignments_submitted",
        "assignment_completion_rate",
        "late_submissions",
        "average_submission_delay_days",
    )
    FEATURE_SCHEMA_VERSION = "academic-v2"

    @staticmethod
    def now():
        return datetime.now(timezone.utc)

    @staticmethod
    def active_enrollments(student_id=None, course_ids=None):
        query = {"status": {"$in": ["active", "enrolled"]}}
        if student_id is not None:
            query["student_id"] = str(student_id)
        if course_ids is not None:
            query["course_id"] = {"$in": [str(value) for value in course_ids]}
        return list(mongo.db.enrollments.find(query))

    @classmethod
    def course_ids_for_teacher(cls, teacher_id):
        return [str(row["_id"]) for row in mongo.db.courses.find(
            {"teacher_id": str(teacher_id), "status": {"$ne": "inactive"}},
            {"_id": 1},
        )]

    @classmethod
    def student_ids_for_courses(cls, course_ids):
        return {str(row["student_id"]) for row in cls.active_enrollments(course_ids=course_ids) if row.get("student_id")}

    @classmethod
    def teacher_student_ids(cls, teacher_id):
        return cls.student_ids_for_courses(cls.course_ids_for_teacher(teacher_id))

    @classmethod
    def course_student_counts(cls, course_ids):
        counts = {str(course_id): 0 for course_id in course_ids}
        for row in cls.active_enrollments(course_ids=course_ids):
            course_id = str(row.get("course_id", ""))
            if course_id in counts:
                counts[course_id] += 1
        return counts

    @classmethod
    def current_features(cls, student_id, course_id=None, semester=None):
        query = {
            "student_id": str(student_id),
            "feature_scope": "course_term" if course_id or semester else "student_global",
        }
        if course_id:
            query["course_id"] = str(course_id)
        if semester:
            query["semester"] = str(semester)
        return mongo.db.student_features.find_one(query, sort=[("updated_at", -1)])

    @classmethod
    def validate_feature_record(cls, student_id, features, feature_version, course_id=None, semester=None):
        record = cls.current_features(student_id, course_id=course_id, semester=semester)
        if not record or not feature_version or record.get("feature_version") != feature_version:
            raise ValueError("A current generated feature version is required.")
        try:
            supplied = [float(value) for value in features]
            registered = [float(value) for value in record.get("features", [])]
        except (TypeError, ValueError):
            raise ValueError("Feature values must be numeric.")
        if supplied != registered:
            raise ValueError("Submitted features do not match the registered feature version.")
        return record

    @classmethod
    def upsert_enrollments(cls, course_id, student_ids, academic_year=None, changed_by=None):
        """Make the submitted roster authoritative without storing course.student_ids."""
        course_id = str(course_id)
        requested = {str(value) for value in student_ids if value}
        valid_students = {
            str(row["_id"]) for row in mongo.db.users.find(
                {
                    "_id": {"$in": [ObjectId(value) for value in requested if ObjectId.is_valid(value)]},
                    "role": "student",
                    "status": {"$nin": ["deleted", "suspended"]},
                },
            )
        }
        existing = {str(row["student_id"]): row for row in cls.active_enrollments(course_ids=[course_id])}
        now = cls.now()
        for student_id in sorted(valid_students):
            mongo.db.enrollments.update_one(
                {"student_id": student_id, "course_id": course_id},
                {"$set": {"status": "active", "academic_year": academic_year or str(now.year), "updated_at": now, "updated_by": changed_by},
                 "$setOnInsert": {"enrollment_id": f"{student_id}:{course_id}", "enrolled_at": now}},
                upsert=True,
            )
        removed = set(existing) - valid_students
        if removed:
            mongo.db.enrollments.update_many(
                {"course_id": course_id, "student_id": {"$in": list(removed)}, "status": {"$in": ["active", "enrolled"]}},
                {"$set": {"status": "withdrawn", "updated_at": now, "updated_by": changed_by}},
            )
        return len(valid_students), len(removed)

    @classmethod
    def migrate_legacy_course_rosters(cls):
        """Move legacy embedded rosters into enrollments and remove the duplicate field."""
        migrated = 0
        for course in mongo.db.courses.find({"student_ids": {"$exists": True}}, {"student_ids": 1}):
            cls.upsert_enrollments(
                course["_id"],
                course.get("student_ids", []),
                changed_by="legacy-roster-migration",
            )
            mongo.db.courses.update_one({"_id": course["_id"]}, {"$unset": {"student_ids": ""}})
            migrated += 1
        return migrated

    @classmethod
    def _feature_values(cls, student_id, course_id=None, semester=None):
        scope = {"student_id": str(student_id)}
        if course_id:
            scope["course_id"] = str(course_id)
        if semester:
            scope["semester"] = str(semester)
        attendance = list(mongo.db.attendance.find(scope, {"present": 1}))
        grades = [float(row["score"]) for row in mongo.db.grades.find(scope, {"score": 1}) if isinstance(row.get("score"), (int, float))]
        lms_activity = mongo.db.lms_records.count_documents(scope)
        assignments = list(mongo.db.assignments.find(scope, {"_id": 1, "due_date": 1}))
        assignment_ids = {str(row["_id"]) for row in assignments if row.get("_id")}
        submissions = list(mongo.db.submissions.find(
            {**scope, "assignment_id": {"$in": list(assignment_ids)}},
            {"assignment_id": 1, "status": 1, "submitted_at": 1},
        )) if assignment_ids else []
        submitted = [row for row in submissions if row.get("status") in {"submitted", "graded"}]
        delays = []
        late_submissions = 0
        due_dates = {str(row["_id"]): row.get("due_date") for row in assignments if row.get("_id")}
        for submission in submitted:
            due_date = due_dates.get(str(submission.get("assignment_id")))
            submitted_at = submission.get("submitted_at")
            if due_date and submitted_at:
                try:
                    due = datetime.fromisoformat(str(due_date))
                    submitted_time = submitted_at if isinstance(submitted_at, datetime) else datetime.fromisoformat(str(submitted_at))
                    if due.tzinfo is None and submitted_time.tzinfo is not None:
                        due = due.replace(tzinfo=timezone.utc)
                    delay = (submitted_time - due).total_seconds() / 86400
                    delays.append(max(0.0, delay))
                    late_submissions += int(delay > 0)
                except (TypeError, ValueError):
                    continue
        assigned_count = len(assignments)
        submitted_count = len(submitted)
        profile = mongo.db.users.find_one({"_id": ObjectId(student_id)}) if ObjectId.is_valid(str(student_id)) else None
        return {
            "attendance_rate": round(sum(bool(row.get("present")) for row in attendance) / len(attendance) * 100, 4) if attendance else 0.0,
            "average_score": round(sum(grades) / len(grades), 4) if grades else 0.0,
            "lms_activity": float(lms_activity),
            "gpa": float(profile.get("gpa", 0) or 0) if profile else 0.0,
            "assignments_assigned": float(assigned_count),
            "assignments_submitted": float(submitted_count),
            "assignment_completion_rate": round(submitted_count / assigned_count * 100, 4) if assigned_count else 0.0,
            "late_submissions": float(late_submissions),
            "average_submission_delay_days": round(sum(delays) / len(delays), 4) if delays else 0.0,
        }

    @classmethod
    def refresh_student(cls, student_id, changed_by=None, reason="academic_data_changed", course_id=None, semester=None):
        student_id = str(student_id)
        values = cls._feature_values(student_id, course_id=course_id, semester=semester)
        now = cls.now()
        feature_key = f"{student_id}:{course_id or 'global'}:{semester or 'all'}"
        feature_doc = {
            "student_id": student_id,
            "course_id": str(course_id) if course_id else None,
            "semester": str(semester) if semester else None,
            "feature_scope": "course_term" if course_id or semester else "student_global",
            "feature_id": feature_key,
            "feature_schema_version": cls.FEATURE_SCHEMA_VERSION,
            "feature_version": uuid4().hex,
            "features": [values[key] for key in cls.FEATURE_ORDER],
            "feature_names": list(cls.FEATURE_ORDER),
            "values": values,
            "source_collections": ["users", "enrollments", "attendance", "grades", "lms_records", "demographics", "assignments", "submissions"],
            "processing_job": "AcademicDataService.refresh_student",
            "updated_at": now,
            "trigger": reason,
        }
        mongo.db.student_features.update_one({"feature_id": feature_key}, {"$set": feature_doc}, upsert=True)
        predictions = cls._predict_for_student(student_id, feature_doc, changed_by, reason)
        AlertService.evaluate_student(student_id)
        return {"student_id": student_id, "features": feature_doc, "predictions": predictions}

    @classmethod
    def _predict_for_student(cls, student_id, feature_doc, changed_by, reason):
        predictions = []
        for model_type, method_name, value_key in (
            ("performance", "predict", "prediction"),
            ("dropout", "predict_risk", "risk_score"),
            ("trend", "predict_trend", "prediction"),
            ("anomaly", "predict_single", "prediction"),
        ):
            if not ModelManager.model_exists(model_type):
                continue
            training = mongo.db.model_training.find_one({"model_type": model_type, "status": "active"}, sort=[("trained_at", -1)]) or {}
            if not ModelManager.artifact_matches(model_type, training) or training.get("feature_schema_version") != feature_doc["feature_schema_version"]:
                continue
            model = ModelManager.load_model(model_type)
            if model is None:
                continue
            try:
                value = getattr(model, method_name)(feature_doc["features"])
                record = {
                    "prediction_id": uuid4().hex,
                    "student_id": student_id,
                    "model_type": model_type,
                    value_key: float(value) if not isinstance(value, bool) else value,
                    "prediction": float(value) if not isinstance(value, bool) else value,
                    "feature_id": student_id,
                    "feature_version": feature_doc["feature_version"],
                    "model_version": training.get("model_version", "unversioned"),
                    "course_id": feature_doc.get("course_id"),
                    "semester": feature_doc.get("semester"),
                    "prediction_type": model_type,
                    "prediction_scope": feature_doc["feature_scope"],
                    "source": {"collections": feature_doc["source_collections"], "processing_job": feature_doc["processing_job"], "trigger": reason},
                    "created_by": changed_by,
                    "created_at": cls.now(),
                }
                if model_type == "dropout":
                    record["risk_score"] = float(value)
                mongo.db.predictions.insert_one(record)
                predictions.append(record)
            except (TypeError, ValueError, RuntimeError):
                continue
        return predictions

    @staticmethod
    def lineage_map():
        return {
            "enrolled_courses": {"source": "active enrollment records", "collection": "enrollments", "processing_job": "AcademicDataService.active_enrollments", "dashboard": "teacher/student"},
            "attendance_percentage": {"source": "attendance.present", "collection": "attendance", "hdfs": "/edupredict/processed/attendance", "processing_job": "PySpark/pandas fallback cleaning and aggregation", "feature": "attendance_rate", "model": "performance/dropout/trend", "dashboard": "admin/teacher/student"},
            "performance": {"source": "grades.score", "collection": "grades", "hdfs": "/edupredict/processed/academic", "processing_job": "feature aggregation", "feature": "average_score", "model": "performance", "dashboard": "admin/teacher/student"},
            "predictions": {"source": "student_features", "collection": "predictions", "processing_job": "AcademicDataService.refresh_student", "dashboard": "admin/teacher/student"},
            "course_demand": {"source": "active enrollments", "collection": "enrollments", "processing_job": "course enrollment aggregation", "model": "demand", "dashboard": "analyst/admin"},
        }
