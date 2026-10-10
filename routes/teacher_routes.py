from datetime import datetime, timezone
from statistics import mean
from uuid import uuid4

from bson.objectid import ObjectId
import os
from flask import Blueprint, flash, redirect, render_template, request, session, url_for, send_file, current_app

from models import mongo
from ml.model_manager import ModelManager
from utils.decorators import role_required
from services.alert_service import AlertService
from services.academic_data_service import AcademicDataService
from services.audit_service import AuditService


teacher_bp = Blueprint("teacher", __name__, url_prefix="/teacher")


def _teacher_courses():
    teacher_id = str(session.get("user_id"))
    teacher_ids = [teacher_id]
    if ObjectId.is_valid(teacher_id):
        teacher_ids.append(ObjectId(teacher_id))
    return list(mongo.db.courses.find({"teacher_id": {"$in": teacher_ids}, "status": {"$ne": "inactive"}}).sort("created_at", -1))


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
    course_ids = [str(course["_id"]) for course in assigned_courses]
    student_ids = _teacher_student_ids(assigned_courses)
    students = list(mongo.db.users.find(
        {"_id": {"$in": [ObjectId(value) for value in student_ids if ObjectId.is_valid(value)]}},
        {"password": 0, "password_hash": 0},
    ).sort("name", 1)) if student_ids else []

    # Query all active subjects for the teacher's assigned courses
    subjects_by_course = AcademicDataService.get_subjects_by_courses(course_ids)
    all_subjects = []
    for s_list in subjects_by_course.values():
        all_subjects.extend(s_list)

    return render_template(
        "teacher/courses.html",
        courses=assigned_courses,
        students=students,
        subjects_by_course=subjects_by_course,
        subjects=all_subjects,
    )


@teacher_bp.route("/attendance", methods=["POST"])
@role_required("teacher")
def record_attendance():
    course_id = request.form.get("course_id", "").strip()
    subject_id = request.form.get("subject_id", "").strip()
    student_id = request.form.get("student_id", "").strip()
    date_value = request.form.get("date", "").strip()
    attendance_status = _normalize_attendance_status(request.form.get("status", request.form.get("present", "false")))
    if attendance_status is None:
        flash("Attendance status is invalid.", "danger")
        return redirect(url_for("teacher.courses"))
    present = attendance_status in {"present", "late", "excused"}
    try:
        datetime.strptime(date_value, "%Y-%m-%d")
    except ValueError:
        flash("Attendance requires a valid date.", "danger")
        return redirect(url_for("teacher.courses"))
    if not _authorized_enrollment(course_id, student_id):
        flash("You may only record attendance for enrolled students in your courses.", "danger")
        return redirect(url_for("teacher.courses"))

    # Resolve subject metadata if provided
    subject_name = None
    subject_code = None
    if subject_id:
        if not ObjectId.is_valid(subject_id):
            flash("The selected subject is invalid for this course.", "danger")
            return redirect(url_for("teacher.courses"))
        sub_doc = mongo.db.subjects.find_one({
            "_id": ObjectId(subject_id),
            "course_id": {"$in": [course_id, ObjectId(course_id)]},
        })
        if not sub_doc:
            flash("The selected subject is not part of this course.", "danger")
            return redirect(url_for("teacher.courses"))
        if sub_doc:
            subject_name = sub_doc.get("name")
            subject_code = sub_doc.get("code")

    now = datetime.now(timezone.utc)
    query_filter = {"student_id": student_id, "course_id": course_id, "date": date_value}
    if subject_id:
        query_filter["subject_id"] = subject_id

    update_payload = {
        "present": present,
        "status": attendance_status,
        "teacher_id": str(session["user_id"]),
        "updated_at": now,
    }
    if subject_id:
        update_payload["subject_id"] = subject_id
        update_payload["subject_name"] = subject_name
        update_payload["subject_code"] = subject_code

    mongo.db.attendance.update_one(
        query_filter,
        {"$set": update_payload, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    AcademicDataService.refresh_student(student_id, changed_by=session["user_id"], reason="attendance_changed", course_id=course_id)
    AuditService.record("attendance_recorded", "attendance", f"{student_id}:{course_id}:{subject_id or 'all'}:{date_value}", session["user_id"], session.get("role"), metadata={"status": attendance_status, "subject_id": subject_id})
    flash(f"Attendance saved for {subject_name or 'course'} and academic signals refreshed.", "success")
    return redirect(url_for("teacher.courses"))


@teacher_bp.route("/grades", methods=["POST"])
@role_required("teacher")
def record_grade():
    course_id = request.form.get("course_id", "").strip()
    subject_id = request.form.get("subject_id", "").strip()
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

    # Resolve subject metadata if provided
    subject_name = None
    subject_code = None
    if subject_id:
        if not ObjectId.is_valid(subject_id):
            flash("The selected subject is invalid for this course.", "danger")
            return redirect(url_for("teacher.courses"))
        sub_doc = mongo.db.subjects.find_one({
            "_id": ObjectId(subject_id),
            "course_id": {"$in": [course_id, ObjectId(course_id)]},
        })
        if not sub_doc:
            flash("The selected subject is not part of this course.", "danger")
            return redirect(url_for("teacher.courses"))
        if sub_doc:
            subject_name = sub_doc.get("name")
            subject_code = sub_doc.get("code")

    now = datetime.now(timezone.utc)
    query_filter = {"student_id": student_id, "course_id": course_id, "assessment": assessment}
    if subject_id:
        query_filter["subject_id"] = subject_id

    update_payload = {
        "score": score,
        "feedback": feedback,
        "teacher_id": str(session["user_id"]),
        "updated_at": now,
    }
    if subject_id:
        update_payload["subject_id"] = subject_id
        update_payload["subject_name"] = subject_name
        update_payload["subject_code"] = subject_code

    mongo.db.grades.update_one(
        query_filter,
        {"$set": update_payload, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )
    AcademicDataService.refresh_student(student_id, changed_by=session["user_id"], reason="grade_changed", course_id=course_id)
    AuditService.record("grade_recorded", "grade", f"{student_id}:{course_id}:{subject_id or 'all'}:{assessment}", session["user_id"], session.get("role"), metadata={"score": score, "subject_id": subject_id})
    flash(f"Marks recorded for {subject_name or 'course'} and academic signals refreshed.", "success")
    return redirect(url_for("teacher.courses"))


@teacher_bp.route("/assignments", methods=["POST"])
@role_required("teacher")
def create_assignment():
    course_id = request.form.get("course_id", "").strip()
    subject_id = request.form.get("subject_id", "").strip()
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

    # Resolve subject metadata if provided
    subject_name = None
    subject_code = None
    if subject_id:
        if not ObjectId.is_valid(subject_id):
            flash("The selected subject is invalid for this course.", "danger")
            return redirect(url_for("teacher.courses"))
        sub_doc = mongo.db.subjects.find_one({
            "_id": ObjectId(subject_id),
            "course_id": {"$in": [course_id, ObjectId(course_id)]},
        })
        if not sub_doc:
            flash("The selected subject is not part of this course.", "danger")
            return redirect(url_for("teacher.courses"))
        subject_name = sub_doc.get("name")
        subject_code = sub_doc.get("code")

    now = datetime.now(timezone.utc)
    assignment_key = f"{course_id}:{subject_id or 'all'}:{title}:{due_date or 'none'}"
    records = [
        {
            "student_id": str(row["student_id"]),
            "course_id": course_id,
            "subject_id": subject_id or None,
            "subject_name": subject_name or None,
            "subject_code": subject_code or None,
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
        AuditService.record("assignment_created", "assignment", course_id, session["user_id"], session.get("role"), metadata={"title": title, "subject_id": subject_id, "recipients": len(records), "created": created})
        subject_label = f" under '{subject_name}'" if subject_name else ""
        flash(f"Assignment published{subject_label} to {len(records)} enrolled student(s); {created} new record(s).", "success")
    else:
        flash("The course has no active enrolled students.", "warning")
    return redirect(url_for("teacher.courses"))


@teacher_bp.route("/submissions")
@role_required("teacher")
def submissions():
    """Show all submissions AND pending (not-yet-submitted) students per assignment."""
    courses = _teacher_courses()
    course_ids = [str(c["_id"]) for c in courses]

    if not course_ids:
        return render_template(
            "teacher/submissions.html",
            assignment_groups=[],
            total_submitted=0,
            total_pending=0,
        )

    # ------------------------------------------------------------------
    # 1. All assignments issued by this teacher across their courses
    # ------------------------------------------------------------------
    all_assignments = list(
        mongo.db.assignments.find(
            {"course_id": {"$in": course_ids}},
        ).sort("created_at", -1).limit(1000)
    )

    # ------------------------------------------------------------------
    # 2. All actual submissions for those courses
    # ------------------------------------------------------------------
    all_submissions = list(
        mongo.db.submissions.find(
            {"course_id": {"$in": course_ids}}
        ).sort("submitted_at", -1).limit(2000)
    )

    # ------------------------------------------------------------------
    # 3. All enrolled student IDs per course (to find pending students)
    # ------------------------------------------------------------------
    enrolled_by_course = {}   # course_id_str -> set of student_id_str
    for cid in course_ids:
        enrolled_by_course[cid] = {
            str(row["student_id"])
            for row in AcademicDataService.active_enrollments(course_ids=[cid])
            if row.get("student_id")
        }

    # ------------------------------------------------------------------
    # 4. Batch-resolve all student names we'll need
    # ------------------------------------------------------------------
    all_student_ids = set()
    for row in all_assignments:
        all_student_ids.add(str(row.get("student_id", "")))
    for row in all_submissions:
        all_student_ids.add(str(row.get("student_id", "")))
    for sid_set in enrolled_by_course.values():
        all_student_ids.update(sid_set)
    all_student_ids.discard("")

    valid_oids = [ObjectId(sid) for sid in all_student_ids if ObjectId.is_valid(sid)]
    users_map = {
        str(u["_id"]): u.get("name", "Unknown Student")
        for u in mongo.db.users.find({"_id": {"$in": valid_oids}}, {"name": 1})
    }

    # ------------------------------------------------------------------
    # 5. Batch-resolve course info
    # ------------------------------------------------------------------
    course_info_map = {str(c["_id"]): c for c in courses}

    # ------------------------------------------------------------------
    # 6. Index submissions by (assignment_key, student_id) and by
    #    (course_id, student_id) for assignments that have no key.
    # ------------------------------------------------------------------
    # submission keyed by (assignment_key, student_id_str)
    sub_by_key = {}
    # fallback index by (course_id_str, student_id_str)
    sub_by_course_student = {}
    for s in all_submissions:
        sid = str(s.get("student_id", ""))
        akey = s.get("assignment_key") or s.get("assignment_id", "")
        cid = str(s.get("course_id", ""))
        file_path = s.get("file_path")
        s["has_valid_zip"] = bool(
            file_path
            and str(file_path).lower().endswith(".zip")
            and os.path.isfile(file_path)
        )
        s["_id_str"] = str(s["_id"])
        if akey:
            sub_by_key[(akey, sid)] = s
        sub_by_course_student.setdefault((cid, sid), s)

    # ------------------------------------------------------------------
    # 7. Group assignments; for each assignment collect submitted+pending
    # ------------------------------------------------------------------
    # Deduplicate by assignment_key (one logical assignment → many student rows)
    seen_keys = {}
    for a in all_assignments:
        akey = a.get("assignment_key") or str(a["_id"])
        if akey not in seen_keys:
            seen_keys[akey] = a

    assignment_groups = []
    total_submitted = 0
    total_pending = 0

    for akey, assignment in seen_keys.items():
        cid = str(assignment.get("course_id", ""))
        course_doc = course_info_map.get(cid, {})
        enrolled_ids = enrolled_by_course.get(cid, set())

        submitted_rows = []
        pending_rows = []

        for sid in sorted(enrolled_ids):
            student_name = users_map.get(sid, f"Student ({sid[:8]}…)")
            # Look up submission
            sub = sub_by_key.get((akey, sid)) or sub_by_course_student.get((cid, sid))

            if sub:
                sub["student_name"] = student_name
                sub["course_code"] = course_doc.get("code", "")
                sub["course_title"] = course_doc.get("title", "")
                submitted_rows.append(sub)
                total_submitted += 1
            else:
                pending_rows.append({
                    "student_id": sid,
                    "student_name": student_name,
                    "status": "pending",
                })
                total_pending += 1

        assignment_groups.append({
            "assignment_key": akey,
            "title": assignment.get("title", "Assignment"),
            "subject_name": assignment.get("subject_name"),
            "subject_code": assignment.get("subject_code"),
            "due_date": assignment.get("due_date", ""),
            "course_code": course_doc.get("code", "—"),
            "course_title": course_doc.get("title", ""),
            "course_id": cid,
            "submitted": submitted_rows,
            "pending": pending_rows,
            "submitted_count": len(submitted_rows),
            "pending_count": len(pending_rows),
            "total_enrolled": len(enrolled_ids),
        })

    # Sort: assignments with most pending first so teacher sees gaps immediately
    assignment_groups.sort(key=lambda g: g["pending_count"], reverse=True)

    return render_template(
        "teacher/submissions.html",
        assignment_groups=assignment_groups,
        total_submitted=total_submitted,
        total_pending=total_pending,
    )


@teacher_bp.route("/submissions/<submission_id>/download")
@role_required("teacher")
def download_submission_file(submission_id):
    if not ObjectId.is_valid(submission_id):
        flash("Invalid submission ID.", "danger")
        return redirect(url_for("teacher.submissions"))
    submission = mongo.db.submissions.find_one({"_id": ObjectId(submission_id)})
    if not submission or not _authorized_enrollment(submission.get("course_id"), submission.get("student_id")):
        flash("You are not authorized to download this submission file.", "danger")
        return redirect(url_for("teacher.submissions"))
    file_path = submission.get("file_path")
    if not file_path or not str(file_path).lower().endswith(".zip") or not os.path.isfile(file_path):
        flash("Submitted ZIP file was not found on the server.", "danger")
        return redirect(url_for("teacher.submissions"))
    download_name = submission.get("original_filename") or f"{submission.get('assignment_title', 'assignment')}_{submission.get('student_id')}.zip"
    return send_file(file_path, as_attachment=True, download_name=download_name)


@teacher_bp.route("/submissions/<submission_id>/grade", methods=["POST"])
@role_required("teacher")
def grade_submission(submission_id):
    if not ObjectId.is_valid(submission_id):
        flash("Invalid submission.", "danger")
        return redirect(url_for("teacher.submissions"))
    submission = mongo.db.submissions.find_one({"_id": ObjectId(submission_id)})
    if not submission:
        flash("Submission not found.", "danger")
        return redirect(url_for("teacher.submissions"))

    # Strictly enforce that grading is locked unless a valid ZIP file exists
    file_path = submission.get("file_path")
    if not file_path or not str(file_path).lower().endswith(".zip") or not os.path.isfile(file_path):
        flash("Grading locked: Cannot grade assignment without a valid student ZIP submission.", "danger")
        return redirect(url_for("teacher.submissions"))

    if not _authorized_enrollment(submission.get("course_id"), submission.get("student_id")):
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
        current_app.logger.warning("Risk prediction failed (error type: %s).", type(exc).__name__)
        flash("The student record could not be scored.", "danger")
        return redirect(url_for("teacher.dashboard"))
    flash(f"Risk analysis generated for {student_id}: {risk:.1%}.", "success")
    return redirect(url_for("teacher.dashboard"))


@teacher_bp.route("/predictions")
@role_required("teacher")
def predictions():
    """Show all ML predictions for the teacher's assigned students, with names resolved."""
    courses = _teacher_courses()
    student_ids = _teacher_student_ids(courses)  # set of str IDs

    if not student_ids:
        return render_template("teacher/predictions.html", predictions=[], total=0)

    # Fetch predictions scoped to this teacher's students (latest 300).
    raw = list(
        mongo.db.predictions.find(
            {"student_id": {"$in": list(student_ids)}}
        ).sort("created_at", -1).limit(300)
    )

    # --- Batch-resolve student names ----------------------------------------
    valid_oids = [ObjectId(sid) for sid in student_ids if ObjectId.is_valid(sid)]
    users_map = {
        str(u["_id"]): u.get("name", "Unknown Student")
        for u in mongo.db.users.find(
            {"_id": {"$in": valid_oids}},
            {"name": 1},
        )
    }

    # --- Batch-resolve course codes/titles -----------------------------------
    course_id_strings = list({
        str(p["course_id"]) for p in raw if p.get("course_id")
    })
    course_oids = [ObjectId(cid) for cid in course_id_strings if ObjectId.is_valid(cid)]
    courses_map = {
        str(c["_id"]): c
        for c in mongo.db.courses.find(
            {"_id": {"$in": course_oids}},
            {"code": 1, "title": 1},
        )
    }

    # --- Enrich each prediction record --------------------------------------
    enriched = []
    for p in raw:
        sid = str(p.get("student_id", ""))
        cid = str(p.get("course_id", "")) if p.get("course_id") else ""

        # Numeric score: prefer risk_score for dropout model, else prediction.
        raw_score = p.get("risk_score") if p.get("model_type") == "dropout" else p.get("prediction")
        try:
            score_pct = round(float(raw_score) * 100, 1)
        except (TypeError, ValueError):
            score_pct = None

        # Severity badge
        if score_pct is None:
            level = "Unknown"
            badge_class = "bg-slate-100 text-slate-600"
        elif score_pct >= 70:
            level = "High"
            badge_class = "bg-red-50 text-red-700"
        elif score_pct >= 40:
            level = "Moderate"
            badge_class = "bg-amber-50 text-amber-700"
        else:
            level = "Low"
            badge_class = "bg-emerald-50 text-emerald-700"

        course_info = courses_map.get(cid, {})

        enriched.append({
            "_id": str(p["_id"]),
            "student_name": users_map.get(sid, f"Student ({sid[:8]}…)"),
            "student_id": sid,
            "model_type": p.get("model_type", "—").replace("_", " ").title(),
            "score_pct": score_pct,
            "level": level,
            "badge_class": badge_class,
            "course_code": course_info.get("code", "—"),
            "course_title": course_info.get("title", ""),
            "model_version": p.get("model_version", "—"),
            "created_at": p.get("created_at", ""),
        })

    return render_template(
        "teacher/predictions.html",
        predictions=enriched,
        total=len(enriched),
    )
