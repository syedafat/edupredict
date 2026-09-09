from datetime import datetime, timezone

from models import mongo
from services.notification_service import NotificationService


class AlertService:
    """Evaluate persisted academic signals and create deduplicated alerts."""

    @staticmethod
    def thresholds():
        settings = mongo.db.settings.find_one({"_id": "platform"}) or {}
        def number(key, default):
            try:
                return float(settings.get(key, default))
            except (TypeError, ValueError):
                return default
        return {
            "attendance_minimum": number("attendance_minimum", 75),
            "dropout_high": number("dropout_high", 0.7),
            "score_minimum": number("score_minimum", 50),
        }

    @staticmethod
    def _notify_once(user_id, title, message, alert_type, dedupe_key):
        if mongo.db.notifications.find_one({"user_id": str(user_id), "dedupe_key": dedupe_key}):
            return False
        return NotificationService.create_notification(
            str(user_id), title, message, alert_type=alert_type, dedupe_key=dedupe_key
        )

    @classmethod
    def evaluate_student(cls, student_id):
        student_id = str(student_id)
        limits = cls.thresholds()
        created = []
        attendance = list(mongo.db.attendance.find({"student_id": student_id}, {"present": 1}).limit(5000))
        if attendance:
            rate = sum(bool(row.get("present")) for row in attendance) / len(attendance) * 100
            if rate < limits["attendance_minimum"]:
                key = f"attendance:{student_id}:{datetime.now(timezone.utc).strftime('%Y-%m')}"
                if cls._notify_once(student_id, "Low attendance alert", f"Your attendance is {rate:.1f}%, below the configured {limits['attendance_minimum']:.0f}% threshold.", "warning", key):
                    created.append("attendance")
        latest = mongo.db.predictions.find_one({"student_id": student_id, "model_type": "dropout"}, sort=[("created_at", -1)])
        if latest and float(latest.get("risk_score", 0) or 0) >= limits["dropout_high"]:
            key = f"dropout:{student_id}:{latest.get('_id')}"
            if cls._notify_once(student_id, "High dropout-risk alert", "A recent model prediction indicates elevated dropout risk. Please contact your advisor.", "danger", key):
                created.append("dropout")
        low_grade = mongo.db.grades.find_one({"student_id": student_id, "score": {"$lt": limits["score_minimum"]}})
        if low_grade:
            key = f"grade:{student_id}:{low_grade.get('_id')}"
            if cls._notify_once(student_id, "Academic performance alert", "A recorded assessment is below the configured academic threshold.", "warning", key):
                created.append("grade")
        return created

    @classmethod
    def evaluate_all(cls):
        results = []
        for user in mongo.db.users.find({"role": "student", "status": {"$nin": ["deleted", "suspended"]}}, {"_id": 1}):
            results.extend(cls.evaluate_student(user["_id"]))
        return len(results)