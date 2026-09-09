from datetime import datetime, timezone
from statistics import mean
from uuid import uuid4

from bson.objectid import ObjectId
from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, session, url_for

from models import mongo
from ml.model_manager import ModelManager
from utils.decorators import role_required
from services.alert_service import AlertService
from services.academic_data_service import AcademicDataService
from services.audit_service import AuditService


teacher_bp = Blueprint("teacher", __name__, url_prefix="/teacher")


def _teacher_courses():
    teacher_id = str(session.get("user_id"))
    return list(mongo.db.courses.find({"teacher_id": teacher_id, "status": {"$ne": "inactive"}}).sort("created_at", -1))


def _teacher_student_ids(courses):
    return AcademicDataService.student_ids_for_courses([str(course["_id"]) for course in courses])


def _authorized_enrollment(course_id, student_id):
    """Return true only for an active student in one of this teacher's courses."""
    course_id = str(course_id)
    student_id = str(student_id)
    course_ids = {str(course["_id"]) for course in _teacher_courses()}
    if course_id not in course_ids:
        return False
    return any(
        str(row.get("course_id")) == course_id and str(row.get("student_id")) == student_id
        for row in AcademicDataService.active_enrollments(course_ids=[course_id])
    )


def _normalize_attendance_status(value):
    status = str(value or "").strip().lower()
    if status in {"true", "1", "yes"}:
        return "present"
    if status in {"false", "0", "no"}:
        return "absent"
    return status if status in {"present", "absent", "late", "excused"} else None


@teacher_bp.route("/dashboard")
@role_required("teacher")
def dashboard():
    courses = _teacher_courses()
    return render_template("teacher/dashboard.html", dashboard_data=_teacher_dashboard_data(courses))


@teacher_bp.route("/api/dashboard")
@role_required("teacher")
def dashboard_data():
    """Return only the authenticated teacher's operational overview."""
    return jsonify(_teacher_dashboard_data(_teacher_courses()))


def _teacher_dashboard_data(courses):
    student_ids = _teacher_student_ids(courses)
    teacher_id = str(session.get("user_id"))
    course_ids = [str(course["_id"]) for course in courses]
    scoped = {"student_id": {"$in": list(student_ids)}, "course_id": {"$in": course_ids}}
    attendance = list(mongo.db.attendance.find(scoped, {"student_id": 1, "present": 1}).limit(10000))
    grades = list(mongo.db.grades.find(scoped, {"student_id": 1, "score": 1}).limit(10000))
    attendance_rate = [sum(bool(row.get("present")) for row in attendance if row.get("student_id") == student_id) / len([row for row in attendance if row.get("student_id") == student_id]) * 100 for student_id in student_ids if any(row.get("student_id") == student_id for row in attendance)]
    scores = [float(row["score"]) for row in grades if isinstance(row.get("score"), (int, float))]
    high_risk = list(mongo.db.predictions.find({"student_id": {"$in": list(student_ids)}, "model_type": "dropout", "risk_score": {"$gte": 0.5}}).sort("created_at", -1).limit(8))
    attention_ids = {str(row.get("student_id")) for row in high_risk}
    students = list(mongo.db.users.find({"_id": {"$in": [ObjectId(value) for value in student_ids if ObjectId.is_valid(value)]}}, {"password": 0, "password_hash": 0}).limit(1000))
    student_by_id = {str(student["_id"]): student for student in students}
    attention = []
    for student_id in attention_ids:
        student = student_by_id.get(student_id)
        prediction = next((row for row in high_risk if str(row.get("student_id")) == student_id), {})
        if student:
            attention.append({"id": student_id, "name": student.get("name", "Student"), "department": student.get("department", "-"), "risk": round(float(prediction.get("risk_score", 0)) * 100), "concern": "Elevated dropout-risk signal", "updated": prediction.get("created_at", "")})
    pending = mongo.db.assignments.count_documents({"teacher_id": teacher_id, "status": {"$in": ["pending", "open", "upcoming"]}})
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "teacher": {"name": session.get("user_name", "Teacher"), "semester": "Current semester", "academic_year": str(datetime.now(timezone.utc).year)},
        "stats": {"students": len(student_ids), "attendance": round(mean(attendance_rate), 1) if attendance_rate else None, "performance": round(mean(scores), 1) if scores else None, "at_risk": len(high_risk), "pending_assignments": pending, "courses": len(courses)},
        "courses": [{"id": str(course["_id"]), "code": course.get("code", "-"), "title": course.get("title", "Untitled course"), "semester": course.get("semester", "-"), "students": AcademicDataService.course_student_counts(course_ids).get(str(course["_id"]), 0)} for course in courses],
        "attention": attention,
        "insights": _teacher_insights(len(high_risk), attendance_rate, scores),
        "alerts": _serialize_teacher_documents(mongo.db.notifications.find({"user_id": teacher_id}).sort("created_at", -1).limit(5)),
    }


def _teacher_insights(at_risk, attendance_rate, scores):
    insights = []
    if at_risk:
        insights.append(f"{at_risk} student(s) currently require academic attention.")
    if attendance_rate and mean(attendance_rate) < AlertService.thresholds()["attendance_minimum"]:
        insights.append("Average attendance is below the configured support threshold.")
    if scores:
        insights.append(f"The assigned cohort average performance is {mean(scores):.1f}%.")
    return insights or ["Insights will appear as assigned student activity is recorded."]


def _serialize_teacher_documents(documents):
    serialized = []
    for document in documents:
        item = {}
        for key, value in document.items():
            item[key] = str(value) if isinstance(value, ObjectId) else value.isoformat() if hasattr(value, "isoformat") else value
        serialized.append(item)
    return serialized


@teacher_bp.route("/students")
@role_required("teacher")
def student_performance():
    courses = _teacher_courses()
    student_ids = _teacher_student_ids(courses)
    if student_ids:
        students = list(mongo.db.users.find({"_id": {"$in": [ObjectId(value) for value in student_ids if ObjectId.is_valid(value)]}}, {"password": 0, "password_hash": 0}))
    else:
        students = []
    return render_template("teacher/students.html", students=students, courses=courses)


@teacher_bp.route("/courses")
@role_required("teacher")
def courses():
    assigned_courses = _teacher_courses()
    student_ids = _teacher_student_ids(assigned_courses)
    students = list(mongo.db.users.find(
        {"_id": {"$in": [ObjectId(value) for value in student_ids if ObjectId.is_valid(value)]}},
        {"password": 0, "password_hash": 0},
    ).sort("name", 1)) if student_ids else []
    return render_template("teacher/courses.html", courses=assigned_courses, students=students)


@teacher_bp.route("/attendance", methods=["POST"])
@role_required("teacher")
def record_attendance():
    course_id = request.form.get("course_id", "").strip()
    student_id = request.form.get("student_id", "").strip()
    date_value = request.form.get("date", "").strip()
    attendance_status = _normalize_attendance_status(request.form.get("status", request.form.get("present", "false")))
    if attendance_status is None:
        flash("Attendance status is invalid.", "danger")
        return redirect(url_for("teacher.courses"))
    present = attendance_status == "present"
    try:
        datetime.strptime(date_value, "%Y-%m-%d")
    except ValueError:
        flash("Attendance requires a valid date.", "danger")
        return redirect(url_for("teacher.courses"))
    if not _authorized_enrollment(course_id, student_id):
        flash("You may only record attendance for enrolled students in your courses.", "danger")
        return redirect(url_for("teacher.courses"))
    now = datetime.now(timezone.utc)
    mongo.db.attendance.update_one(
        {"student_id": student_id, "course_id": course_id, "date": date_value},
        {"$set": {"present": present, "status": attendance_status, "teacher_id": str(session["user_id"]), "updated_at": now},
         "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    AcademicDataService.refresh_student(student_id, changed_by=session["user_id"], reason="attendance_changed", course_id=course_id)
    AuditService.record("attendance_recorded", "attendance", f"{student_id}:{course_id}:{date_value}", session["user_id"], session.get("role"), metadata={"status": attendance_status})
    flash("Attendance saved and academic signals refreshed.", "success")
    return redirect(url_for("teacher.courses"))


@teacher_bp.route("/grades", methods=["POST"])
@role_required("teacher")
def record_grade():
    course_id = request.form.get("course_id", "").strip()
    student_id = request.form.get("student_id", "").strip()
    assessment = request.form.get("assessment", "").strip()[:160]
    feedback = request.form.get("feedback", "").strip()[:5000]
    try:
        score = float(request.form.get("score", ""))
    except ValueError:
        score = -1
    if not assessment or not 0 <= score <= 100 or not _authorized_enrollment(course_id, student_id):
        flash("Provide an assessment, a score from 0 to 100, and an enrolled student in your course.", "danger")
        return redirect(url_for("teacher.courses"))
    now = datetime.now(timezone.utc)
    mongo.db.grades.update_one(
        {"student_id": student_id, "course_id": course_id, "assessment": assessment},
        {"$set": {"score": score, "feedback": feedback, "teacher_id": str(session["user_id"]), "updated_at": now},
         "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    AcademicDataService.refresh_student(student_id, changed_by=session["user_id"], reason="grade_changed", course_id=course_id)
    AuditService.record("grade_recorded", "grade", f"{student_id}:{course_id}:{assessment}", session["user_id"], session.get("role"), metadata={"score": score})
    flash("Grade saved and academic signals refreshed.", "success")
    return redirect(url_for("teacher.courses"))


@teacher_bp.route("/assignments", methods=["POST"])
@role_required("teacher")
def create_assignment():
    course_id = request.form.get("course_id", "").strip()
    title = request.form.get("title", "").strip()[:160]
    description = request.form.get("description", "").strip()[:5000]
    due_date = request.form.get("due_date", "").strip()
    try:
        max_marks = float(request.form.get("max_marks", "100") or 100)
    except ValueError:
        max_marks = -1
    assigned_course = next((course for course in _teacher_courses() if str(course["_id"]) == course_id), None)
    if not assigned_course or not title or not 0 < max_marks <= 1000:
        flash("Select an assigned course and provide an assignment title.", "danger")
        return redirect(url_for("teacher.courses"))
    if due_date:
        try:
            datetime.strptime(due_date, "%Y-%m-%d")
        except ValueError:
            flash("Assignment due date is invalid.", "danger")
            return redirect(url_for("teacher.courses"))
    now = datetime.now(timezone.utc)
    assignment_key = f"{course_id}:{title}:{due_date or 'none'}"
    records = [
        {
            "student_id": str(row["student_id"]),
            "course_id": course_id,
            "assignment_key": assignment_key,
            "title": title,
            "description": description,
            "max_marks": max_marks,
            "due_date": due_date or None,
            "status": "pending",
            "teacher_id": str(session["user_id"]),
            "created_at": now,
            "updated_at": now,
        }
        for row in AcademicDataService.active_enrollments(course_ids=[course_id])
        if row.get("student_id")
    ]
    if records:
        created = 0
        for record in records:
            result = mongo.db.assignments.update_one(
                {"student_id": record["student_id"], "assignment_key": assignment_key},
                {"$setOnInsert": {**record, "assignment_id": uuid4().hex}},
                upsert=True,
            )
            created += int(result.upserted_id is not None)
            if result.upserted_id is not None:
                AcademicDataService.refresh_student(record["student_id"], changed_by=session["user_id"], reason="assignment_created", course_id=course_id)
        AuditService.record("assignment_created", "assignment", course_id, session["user_id"], session.get("role"), metadata={"title": title, "recipients": len(records), "created": created})
        flash(f"Assignment published to {len(records)} enrolled student(s); {created} new record(s).", "success")
    else:
        flash("The course has no active enrolled students.", "warning")
    return redirect(url_for("teacher.courses"))


@teacher_bp.route("/submissions")
@role_required("teacher")
def submissions():
    course_ids = [str(course["_id"]) for course in _teacher_courses()]
    records = list(mongo.db.submissions.find({"course_id": {"$in": course_ids}}).sort("submitted_at", -1).limit(500)) if course_ids else []
    return render_template("teacher/submissions.html", submissions=records)


@teacher_bp.route("/submissions/<submission_id>/grade", methods=["POST"])
@role_required("teacher")
def grade_submission(submission_id):
    if not ObjectId.is_valid(submission_id):
        flash("Invalid submission.", "danger")
        return redirect(url_for("teacher.submissions"))
    submission = mongo.db.submissions.find_one({"_id": ObjectId(submission_id)})
    if not submission or not _authorized_enrollment(submission.get("course_id"), submission.get("student_id")):
        flash("You may only grade submissions from enrolled students in your courses.", "danger")
        return redirect(url_for("teacher.submissions"))
    try:
        score = float(request.form.get("score", ""))
    except ValueError:
        score = -1
    if not 0 <= score <= 100:
        flash("A grade must be between 0 and 100.", "danger")
        return redirect(url_for("teacher.submissions"))
    now = datetime.now(timezone.utc)
    feedback = request.form.get("feedback", "").strip()[:5000]
    mongo.db.submissions.update_one(
        {"_id": submission["_id"]},
        {"$set": {"score": score, "feedback": feedback, "graded_by": str(session["user_id"]), "graded_at": now, "status": "graded"}},
    )
    mongo.db.grades.update_one(
        {"student_id": str(submission["student_id"]), "course_id": str(submission["course_id"]), "assessment": submission.get("assignment_title", "Assignment")},
        {"$set": {"score": score, "teacher_id": str(session["user_id"]), "updated_at": now}, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    AcademicDataService.refresh_student(str(submission["student_id"]), changed_by=session["user_id"], reason="submission_graded", course_id=str(submission["course_id"]))
    AuditService.record("submission_graded", "submission", submission["_id"], session["user_id"], session.get("role"), metadata={"score": score})
    flash("Submission graded and academic signals refreshed.", "success")
    return redirect(url_for("teacher.submissions"))


@teacher_bp.route("/predict-risk", methods=["POST"])
@role_required("teacher")
def predict_risk():
    student_id = request.form.get("student_id", "").strip()
    course_id = request.form.get("course_id", "").strip()
    if not student_id:
        flash("A student ID is required.", "danger")
        return redirect(url_for("teacher.dashboard"))
    assigned_courses = _teacher_courses()
    assigned_student_ids = _teacher_student_ids(assigned_courses)
    if student_id not in assigned_student_ids or (course_id and not _authorized_enrollment(course_id, student_id)):
        flash("You may only analyze students assigned to your courses.", "danger")
        return redirect(url_for("teacher.dashboard"))
    model = ModelManager.load_model("dropout")
    student = AcademicDataService.current_features(student_id, course_id=course_id or None)
    if model is None or not student or not isinstance(student.get("features"), list):
        flash("Risk analysis requires a trained dropout model and student feature record.", "warning")
        return redirect(url_for("teacher.dashboard"))
    try:
        risk = model.predict_risk(student["features"])
        training = mongo.db.model_training.find_one({"model_type": "dropout", "status": "active"}, sort=[("trained_at", -1)]) or {}
        if not ModelManager.artifact_matches("dropout", training):
            flash("Risk analysis requires a verified active dropout model.", "warning")
            return redirect(url_for("teacher.dashboard"))
        mongo.db.predictions.insert_one({
            "prediction_id": uuid4().hex,
            "student_id": student_id,
            "course_id": course_id or student.get("course_id"),
            "model_type": "dropout",
            "risk_score": risk,
            "prediction": risk,
            "model_version": training.get("model_version", "unversioned"),
            "feature_version": student.get("feature_version", "unknown"),
            "created_at": datetime.now(timezone.utc),
            "created_by": session.get("user_id"),
        })
        AlertService.evaluate_student(student_id)
        AuditService.record("prediction_generated", "prediction", student_id, session.get("user_id"), session.get("role"), metadata={"model_type": "dropout", "model_version": training.get("model_version", "unversioned")})
    except (TypeError, ValueError, RuntimeError) as exc:
        current_app.logger.warning("Risk prediction failed for %s: %s", student_id, exc)
        flash("The student record could not be scored.", "danger")
        return redirect(url_for("teacher.dashboard"))
    flash(f"Risk analysis generated for {student_id}: {risk:.1%}.", "success")
    return redirect(url_for("teacher.dashboard"))