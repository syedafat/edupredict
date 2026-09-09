from datetime import datetime, timezone, timedelta

from flask import Blueprint, jsonify, render_template

from models import mongo
from utils.decorators import role_required
from services.academic_data_service import AcademicDataService


analyst_bp = Blueprint("analyst", __name__, url_prefix="/analyst")


def _date_key(value):
    if isinstance(value, datetime):
        return value.date().isoformat()
    return str(value)[:10] if value else "unknown"


def _analytics():
    users = mongo.db.users
    predictions = mongo.db.predictions
    attendance = mongo.db.attendance
    datasets = mongo.db.datasets
    grades = mongo.db.grades
    courses = mongo.db.courses

    risk_counts = {"low": 0, "medium": 0, "high": 0}
    for row in predictions.find({"model_type": "dropout"}, {"risk_score": 1}):
        score = float(row.get("risk_score", 0) or 0)
        risk_counts["high" if score >= 0.7 else "medium" if score >= 0.4 else "low"] += 1

    attendance_by_day = {}
    for row in attendance.find({}, {"date": 1, "present": 1}).sort("date", 1).limit(10000):
        key = _date_key(row.get("date"))
        bucket = attendance_by_day.setdefault(key, {"present": 0, "absent": 0})
        bucket["present" if row.get("present") else "absent"] += 1

    grade_values = [float(row["score"]) for row in grades.find({}, {"score": 1}).limit(10000)
                    if isinstance(row.get("score"), (int, float))]
    course_demand = []
    for course in courses.find({"status": {"$ne": "inactive"}}, {"code": 1, "title": 1}):
        course_demand.append({
            "code": course.get("code", "—"),
            "title": course.get("title", "Untitled"),
            "enrollment": AcademicDataService.course_student_counts([str(course["_id"])]).get(str(course["_id"]), 0),
        })
    course_demand.sort(key=lambda item: item["enrollment"], reverse=True)

    return {
        "counts": {
            "students": users.count_documents({"role": "student", "status": {"$nin": ["deleted", "suspended"]}}),
            "teachers": users.count_documents({"role": "teacher", "status": {"$nin": ["deleted", "suspended"]}}),
            "datasets": datasets.count_documents({}),
            "predictions": predictions.count_documents({}),
            "attendance_records": attendance.count_documents({}),
        },
        "risk_counts": risk_counts,
        "attendance_by_day": [{"date": key, **value} for key, value in sorted(attendance_by_day.items())[-30:]],
        "course_demand": course_demand[:20],
        "average_score": round(sum(grade_values) / len(grade_values), 2) if grade_values else None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@analyst_bp.route("/dashboard")
@role_required("analyst", "admin")
def dashboard():
    return render_template("analyst/dashboard.html", analytics=_analytics())


@analyst_bp.route("/data")
@role_required("analyst", "admin")
def data():
    return jsonify({"status": "success", "analytics": _analytics()})