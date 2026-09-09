from datetime import datetime, timezone
from statistics import mean

from bson import ObjectId
from flask import Blueprint, flash, jsonify, redirect, render_template, request, session, url_for

from models import mongo
from utils.decorators import role_required
from services.academic_data_service import AcademicDataService
from services.audit_service import AuditService


student_bp = Blueprint("student", __name__, url_prefix="/student")


def _student_id():
    return str(session.get("user_id"))


def _enrolled_courses():
    student_id = _student_id()
    enrolled_ids = [row.get("course_id") for row in AcademicDataService.active_enrollments(student_id=student_id) if row.get("course_id")]
    object_ids = [ObjectId(value) for value in enrolled_ids if ObjectId.is_valid(str(value))]
    courses = list(mongo.db.courses.find({"_id": {"$in": object_ids}, "status": {"$ne": "inactive"}})) if object_ids else []
    return sorted(courses, key=lambda course: course.get("created_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)


def _owned_assignment(assignment_id, student_id=None):
    if not ObjectId.is_valid(str(assignment_id)):
        return None
    owner_id = str(student_id if student_id is not None else _student_id())
    return mongo.db.assignments.find_one({"_id": ObjectId(assignment_id), "student_id": owner_id})


@student_bp.route("/dashboard")
@role_required("student")
def dashboard():
    return render_template("student/dashboard.html", dashboard_data=_student_dashboard_data())


@student_bp.route("/api/dashboard")
@role_required("student")
def dashboard_data():
    """Return only the authenticated student's academic overview."""
    return jsonify(_student_dashboard_data())


def _student_dashboard_data():
    student_id = _student_id()
    student = _student_profile()
    courses = _enrolled_courses()
    grades = list(mongo.db.grades.find({"student_id": student_id}, {"score": 1, "course_id": 1, "created_at": 1}).sort("created_at", -1).limit(5000))
    scores = [float(grade["score"]) for grade in grades if isinstance(grade.get("score"), (int, float))]
    attendance = list(mongo.db.attendance.find({"student_id": student_id}, {"present": 1, "date": 1}).sort("date", -1).limit(5000))
    attendance_rate = round(sum(bool(row.get("present")) for row in attendance) / len(attendance) * 100, 1) if attendance else None
    predictions = list(mongo.db.predictions.find({"student_id": student_id}).sort("created_at", -1).limit(20))
    performance_prediction = next((row for row in predictions if row.get("model_type") in {"performance", "student_performance"}), None)
    dropout_prediction = next((row for row in predictions if row.get("model_type") == "dropout"), None)
    assignments = list(mongo.db.assignments.find({"student_id": student_id, "status": {"$in": ["pending", "open", "upcoming"]}}).sort("due_date", 1).limit(5))
    stats = {
        "gpa": student.get("gpa") if student.get("gpa") is not None else round(mean(scores) / 25, 2) if scores else None,
        "performance": round(mean(scores), 1) if scores else None,
        "attendance": attendance_rate,
        "predicted_score": _prediction_value(performance_prediction, "predicted_score"),
        "dropout_risk": round(float(dropout_prediction.get("risk_score", 0)) * 100) if dropout_prediction else None,
        "courses": len(courses),
        "pending_assignments": len(assignments),
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "student": {"name": student.get("name", session.get("user_name", "Student")), "student_id": student.get("student_id", student_id), "department": student.get("department", "-"), "program": student.get("program", "-"), "semester": student.get("semester", "Current semester"), "academic_year": student.get("academic_year", str(datetime.now(timezone.utc).year))},
        "stats": stats,
        "courses": [{"id": str(course["_id"]), "code": course.get("code", "-"), "title": course.get("title", "Untitled course"), "semester": course.get("semester", "-"), "credits": course.get("credits", 0)} for course in courses],
        "assignments": _serialize_student_documents(assignments),
        "predictions": {"performance": _serialize_student_document(performance_prediction), "dropout": _serialize_student_document(dropout_prediction)},
        "insights": _student_insights(stats, assignments),
        "alerts": _serialize_student_documents(mongo.db.notifications.find({"user_id": student_id}).sort("created_at", -1).limit(5)),
    }


def _student_profile():
    try:
        object_id = ObjectId(_student_id())
    except Exception:
        object_id = None
    return mongo.db.users.find_one({"_id": object_id}, {"password": 0, "password_hash": 0}) if object_id else {}


def _prediction_value(prediction, key):
    if not prediction:
        return None
    value = prediction.get(key, prediction.get("prediction", prediction.get("predicted_value")))
    try:
        return round(float(value), 1) if value is not None else None
    except (TypeError, ValueError):
        return None


def _student_insights(stats, assignments):
    insights = []
    if stats["attendance"] is not None and stats["attendance"] < 75:
        insights.append("Your attendance is below the recommended threshold. Attending upcoming classes can help your progress.")
    if assignments:
        insights.append(f"You have {len(assignments)} assignment(s) requiring attention.")
    if stats["predicted_score"] is not None:
        insights.append(f"Your predicted final score is approximately {stats['predicted_score']}%; this is an estimate, not a guarantee.")
    return insights or ["Keep reviewing your course activity for personalized EduPredict guidance."]


def _serialize_student_document(document):
    if not document:
        return None
    return _serialize_student_documents([document])[0]


def _serialize_student_documents(documents):
    result = []
    for document in documents:
        item = {}
        for key, value in document.items():
            item[key] = str(value) if isinstance(value, ObjectId) else value.isoformat() if hasattr(value, "isoformat") else value
        result.append(item)
    return result


@student_bp.route("/grades")
@role_required("student")
def grades():
    return render_template("student/performance.html", grades=list(mongo.db.grades.find({"student_id": _student_id()}).sort("created_at", -1)))


@student_bp.route("/attendance")
@role_required("student")
def attendance():
    records = list(mongo.db.attendance.find({"student_id": _student_id()}).sort("date", -1))
    return render_template("student/attendance.html", attendance_records=records)


@student_bp.route("/courses")
@role_required("student")
def courses():
    return render_template("student/courses.html", courses=_enrolled_courses())


@student_bp.route("/notifications")
@role_required("student")
def notifications():
    records = list(mongo.db.notifications.find({"user_id": _student_id()}).sort("created_at", -1).limit(100))
    return render_template("student/notifications.html", notifications=records)


@student_bp.route("/predictions")
@role_required("student")
def predictions():
    records = list(mongo.db.predictions.find({"student_id": _student_id()}).sort("created_at", -1).limit(100))
    return render_template("student/predictions.html", predictions=records)


@student_bp.route("/assignments")
@role_required("student")
def assignments():
    student_id = _student_id()
    records = list(mongo.db.assignments.find({"student_id": student_id}).sort("due_date", 1).limit(100))
    submissions = list(mongo.db.submissions.find({"student_id": student_id}).sort("submitted_at", -1).limit(100))
    return render_template("student/assignments.html", assignments=records, submissions=submissions)


@student_bp.route("/assignments/<assignment_id>/submit", methods=["POST"])
@role_required("student")
def submit_assignment(assignment_id):
    if not ObjectId.is_valid(assignment_id):
        flash("Invalid assignment.", "danger")
        return redirect(url_for("student.assignments"))
    assignment = _owned_assignment(assignment_id)
    if not assignment or assignment.get("status") not in {"pending", "open", "upcoming"}:
        flash("Assignment is unavailable or already submitted.", "warning")
        return redirect(url_for("student.assignments"))
    enrolled = any(
        str(row.get("course_id")) == str(assignment.get("course_id"))
        for row in AcademicDataService.active_enrollments(student_id=_student_id())
    )
    if not enrolled:
        flash("You may only submit assignments for your active enrollments.", "danger")
        return redirect(url_for("student.assignments"))
    content = request.form.get("content", "").strip()[:10000]
    if not content:
        flash("A submission cannot be empty.", "danger")
        return redirect(url_for("student.assignments"))
    now = datetime.now(timezone.utc)
    mongo.db.submissions.update_one(
        {"assignment_id": str(assignment["_id"]), "student_id": _student_id()},
        {"$set": {"content": content, "status": "submitted", "submitted_at": now, "assignment_title": assignment.get("title", "Assignment"), "course_id": str(assignment.get("course_id", ""))}, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    mongo.db.assignments.update_one({"_id": assignment["_id"]}, {"$set": {"status": "submitted", "updated_at": now}})
    AcademicDataService.refresh_student(_student_id(), changed_by=session["user_id"], reason="assignment_submitted", course_id=str(assignment.get("course_id", "")))
    AuditService.record("assignment_submitted", "submission", assignment["_id"], session["user_id"], session.get("role"))
    flash("Assignment submitted.", "success")
    return redirect(url_for("student.assignments"))


@student_bp.route("/profile")
@role_required("student")
def profile():
    try:
        object_id = ObjectId(_student_id())
    except Exception:
        object_id = None
    user = mongo.db.users.find_one({"_id": object_id}, {"password": 0, "password_hash": 0}) if object_id else None
    return render_template("student/profile.html", user=user or {})


@student_bp.route("/support")
@role_required("student")
def support():
    return render_template("student/support.html")