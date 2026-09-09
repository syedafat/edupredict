from datetime import datetime, timezone
from functools import wraps
import os
import re
from statistics import mean

from bson import ObjectId
from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    jsonify,
    session,
    url_for,
)
from pymongo.errors import DuplicateKeyError
from werkzeug.security import generate_password_hash

from models import mongo
from services.ingestion_service import IngestionService
from services.report_service import ReportService
from services.alert_service import AlertService
from services.hadoop_service import HadoopService
from services.academic_data_service import AcademicDataService
from services.audit_service import AuditService


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login to continue.", "error")
            return redirect(url_for("auth.login"))
        if session.get("role") != "admin":
            flash("Admin access required.", "error")
            role = session.get("role")
            if role == "teacher":
                return redirect(url_for("teacher.dashboard"))
            if role == "student":
                return redirect(url_for("student.dashboard"))
            if role == "analyst":
                return redirect(url_for("analyst.dashboard"))
            return redirect(url_for("auth.login"))
        try:
            user = mongo.db.users.find_one({"_id": ObjectId(session["user_id"])})
        except Exception:
            user = None
        if not user or user.get("role") != "admin" or user.get("status") in {"suspended", "deleted"}:
            session.clear()
            flash("Your account has been deactivated or no longer exists.", "error")
            return redirect(url_for("auth.login"))
        return view_func(*args, **kwargs)

    return wrapped_view


def get_collection(name):
    return mongo.db[name]


def parse_object_id(value):
    try:
        return ObjectId(value)
    except Exception:
        return None


def utc_now():
    return datetime.now(timezone.utc)


@admin_bp.route("/dashboard")
@admin_required
def dashboard():
    dashboard_data = _dashboard_data()
    return render_template(
        "admin/dashboard.html",
        dashboard_data=dashboard_data,
    )


@admin_bp.route("/api/dashboard")
@admin_required
def dashboard_data():
    """Return the admin overview for refreshes and API consumers."""
    return jsonify(_dashboard_data())


def _dashboard_data():
    users = get_collection("users")
    courses = get_collection("courses")
    predictions = get_collection("predictions")
    enrollments = get_collection("enrollments")
    datasets = get_collection("datasets")
    logs = get_collection("system_logs")
    alerts = get_collection("notifications")
    active_user = {"$nin": ["deleted", "suspended"]}
    thresholds = AlertService.thresholds()

    attendance_records = list(get_collection("attendance").find({}, {"present": 1}).limit(10000))
    attendance_values = [100.0 if row.get("present") else 0.0 for row in attendance_records]
    performance_values = [
        float(row.get("score"))
        for row in get_collection("grades").find({"score": {"$type": "number"}}, {"score": 1}).limit(5000)
        if row.get("score") is not None
    ]
    high_risk_query = {"model_type": "dropout", "risk_score": {"$gte": thresholds["dropout_high"]}}
    model_status = _model_status()
    hdfs_status = HadoopService.status()

    return {
        "generated_at": utc_now().isoformat(),
        "stats": {
            "students": users.count_documents({"role": "student", "status": active_user}),
            "teachers": users.count_documents({"role": "teacher", "status": active_user}),
            "courses": courses.count_documents({"status": {"$ne": "inactive"}}),
            "enrollments": enrollments.count_documents({"status": {"$in": ["active", "enrolled"]}}),
            "datasets": datasets.count_documents({}),
            "at_risk": predictions.count_documents(high_risk_query),
            "average_performance": round(mean(performance_values), 1) if performance_values else None,
            "average_attendance": round(mean(attendance_values), 1) if attendance_values else None,
            "active_models": sum(model_status.values()),
            "pending_teachers": users.count_documents({"role": "teacher", "status": "pending"}),
        },
        "recent_logs": _serialize_documents(logs.find().sort("created_at", -1).limit(6)),
        "recent_alerts": _serialize_documents(alerts.find({"status": {"$nin": ["resolved", "closed"]}}).sort("created_at", -1).limit(6)),
        "model_status": model_status,
        "hdfs": hdfs_status,
        "services": {
            "MongoDB": {"status": "Healthy", "detail": "Operational database connected"},
            "HDFS": {"status": "Healthy" if hdfs_status.get("reachable") else "Warning", "detail": hdfs_status.get("message")},
            "ML models": {"status": "Healthy" if model_status else "Warning", "detail": f"{sum(model_status.values())} active model(s)"},
        },
    }


def _serialize_documents(documents):
    serialized = []
    for document in documents:
        item = {}
        for key, value in document.items():
            if isinstance(value, ObjectId):
                item[key] = str(value)
            elif hasattr(value, "isoformat"):
                item[key] = value.isoformat()
            else:
                item[key] = value
        serialized.append(item)
    return serialized


@admin_bp.route("/anomalies")
@admin_required
def anomalies():
    anomalies = list(get_collection("anomalies").find().sort("created_at", -1).limit(100))
    return render_template("admin/anomalies.html", anomalies=anomalies)


@admin_bp.route("/datasets")
@admin_required
def datasets():
    collection = get_collection("datasets")
    dataset_list = list(collection.find().sort("uploaded_at", -1).limit(200))
    total_bytes = sum(os.path.getsize(d["file_path"]) for d in dataset_list if os.path.isfile(d.get("file_path", "")))
    return render_template(
        "admin/datasets.html",
        datasets=dataset_list,
        dataset_count=collection.count_documents({}),
        total_bytes=total_bytes,
        hdfs_status=HadoopService.status(),
    )


@admin_bp.route("/datasets/<dataset_id>/download")
@admin_required
def download_dataset(dataset_id):
    object_id = parse_object_id(dataset_id)
    dataset = get_collection("datasets").find_one({"_id": object_id}) if object_id else None
    if not dataset:
        flash("Dataset not found.", "error")
        return redirect(url_for("admin.datasets"))
    path = os.path.abspath(dataset.get("file_path", ""))
    root = os.path.abspath(os.path.join(current_app.config["UPLOAD_FOLDER"], "datasets"))
    if not path or os.path.commonpath([root, path]) != root or not os.path.isfile(path):
        flash("The dataset file is no longer available.", "error")
        return redirect(url_for("admin.datasets"))
    return send_file(path, as_attachment=True, download_name=dataset.get("original_filename", "dataset"))


@admin_bp.route("/ml-models")
@admin_required
def ml_models():
    return render_template("admin/ml_models.html", model_status=_model_status())


def _model_status():
    from ml.model_manager import ModelManager, SUPPORTED_MODEL_TYPES
    return {model_type: ModelManager.model_exists(model_type) for model_type in sorted(SUPPORTED_MODEL_TYPES)}


@admin_bp.route("/students")
@admin_required
def students():
    query = {"role": "student"}
    search = request.args.get("q", "").strip()
    department = request.args.get("department", "").strip()
    if search:
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
            {"student_id": {"$regex": search, "$options": "i"}},
        ]
    if department:
        query["department"] = department
    student_list = list(
        get_collection("users").find(query, {"password": 0, "password_hash": 0})
        .sort("created_at", -1)
        .limit(500)
    )
    departments = sorted({s.get("department") for s in get_collection("users").find({"role": "student"}, {"department": 1}) if s.get("department")})
    return render_template("admin/students.html", students=student_list, departments=departments, search=search, department=department)


@admin_bp.route("/teachers")
@admin_required
def teachers():
    teacher_list = list(
        get_collection("users").find({"role": "teacher"}, {"password": 0, "password_hash": 0})
        .sort("created_at", -1)
        .limit(500)
    )
    courses = get_collection("courses")
    for teacher in teacher_list:
        teacher["course_count"] = courses.count_documents({"teacher_id": str(teacher["_id"]), "status": {"$ne": "inactive"}})
    departments = sorted({t.get("department") for t in teacher_list if t.get("department")})
    return render_template("admin/teachers.html", teachers=teacher_list, departments=departments)


@admin_bp.route("/teachers/<teacher_id>/status", methods=["POST"])
@admin_required
def update_teacher_status(teacher_id):
    object_id = parse_object_id(teacher_id)
    status = request.form.get("status", "").strip().lower()
    if not object_id or status not in {"approved", "rejected", "suspended"}:
        flash("Invalid teacher status update.", "error")
        return redirect(url_for("admin.teachers"))
    result = get_collection("users").update_one(
        {"_id": object_id, "role": "teacher"},
        {"$set": {"status": status, "updated_at": utc_now(), "updated_by": session.get("user_id")}},
    )
    flash("Teacher status updated." if result.modified_count else "Teacher not found.", "success" if result.modified_count else "error")
    return redirect(url_for("admin.teachers"))


@admin_bp.route("/system-logs")
@admin_required
def system_logs():
    logs = get_collection("system_logs")
    log_list = list(logs.find().sort("created_at", -1).limit(200))
    return render_template(
        "admin/system_logs.html",
        logs=log_list,
        total_events=logs.count_documents({}),
        warnings=logs.count_documents({"level": {"$in": ["WARNING", "WARN", "warning", "warn"]}}),
        critical=logs.count_documents({"level": {"$in": ["ERROR", "CRITICAL", "error", "critical"]}}),
    )


@admin_bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    settings_collection = get_collection("settings")
    if request.method == "POST":
        platform_name = request.form.get("platform_name", "").strip()[:120]
        admin_email = request.form.get("admin_email", "").strip().lower()[:254]
        academic_term = request.form.get("academic_term", "").strip()[:80]
        namenode_url = request.form.get("namenode_url", "").strip()[:300]
        try:
            replication_factor = max(1, min(20, int(request.form.get("replication_factor", "3") or 3)))
        except ValueError:
            replication_factor = 3
        spark_master_url = request.form.get("spark_master_url", "").strip()[:300]
        try:
            attendance_minimum = max(0, min(100, float(request.form.get("attendance_minimum", "75") or 75)))
            dropout_high = max(0, min(1, float(request.form.get("dropout_high", "0.7") or 0.7)))
            score_minimum = max(0, min(100, float(request.form.get("score_minimum", "50") or 50)))
        except ValueError:
            attendance_minimum, dropout_high, score_minimum = 75, 0.7, 50
        maintenance_mode = request.form.get("maintenance_mode") == "on"
        settings_collection.update_one(
            {"_id": "platform"},
            {"$set": {
                "platform_name": platform_name,
                "admin_email": admin_email,
                "academic_term": academic_term,
                "namenode_url": namenode_url,
                "replication_factor": replication_factor,
                "spark_master_url": spark_master_url,
                "maintenance_mode": maintenance_mode,
                 "attendance_minimum": attendance_minimum,
                 "dropout_high": dropout_high,
                 "score_minimum": score_minimum,
                "updated_at": utc_now(),
                "updated_by": session.get("user_id"),
            }},
            upsert=True,
        )
        flash("Platform settings saved successfully.", "success")
        return redirect(url_for("admin.settings"))
    settings_data = settings_collection.find_one({"_id": "platform"}) or {}
    return render_template("admin/settings.html", settings=settings_data)


@admin_bp.route("/upload-data", methods=["GET", "POST"])
@admin_required
def upload_data():
    if request.method == "POST":
        uploaded_file = request.files.get("dataset_file") or request.files.get("file")
        result = IngestionService.save_and_record(
            file_storage=uploaded_file,
            dataset_type=request.form.get("dataset_type", "general"),
            uploaded_by=session.get("user_id"),
            title=request.form.get("title", "").strip(),
        )
        if not result.get("success"):
            flash(result.get("error", "File upload failed."), "error")
            return redirect(url_for("admin.upload_data"))
        flash("Dataset successfully uploaded.", "success")
        return redirect(url_for("data.dataset_detail", dataset_id=result["dataset_id"]))
    return render_template("admin/upload_data.html")


@admin_bp.route("/users")
@admin_required
def users():
    users_collection = get_collection("users")
    search = request.args.get("q", "").strip()
    query = {}
    if search:
        search = re.escape(search[:100])
        query["$or"] = [
            {"name": {"$regex": search, "$options": "i"}},
            {"email": {"$regex": search, "$options": "i"}},
        ]
    user_list = list(users_collection.find(query, {"password": 0, "password_hash": 0, "reset_token_hash": 0, "reset_token_expiry": 0}).sort("created_at", -1).limit(500))
    counts = {
        "total": users_collection.count_documents({}),
        "students": users_collection.count_documents({"role": "student"}),
            "staff": users_collection.count_documents({"role": {"$in": ["teacher", "admin", "analyst"]}}),
    }
    return render_template("admin/users.html", users=user_list, counts=counts, search=search)


@admin_bp.route("/add-user", methods=["GET", "POST"])
@admin_required
def add_user():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "").strip().lower()
        if not name or not email or not re.fullmatch(r"^[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}$", email) or not password or role not in {"student", "teacher", "admin", "analyst"}:
            flash("Name, email, password, and a valid role are required.", "error")
            return render_template("admin/add_user.html")
        if len(password) < 8 or not re.search(r"[A-Z]", password) or not re.search(r"[a-z]", password) or not re.search(r"\d", password):
            flash("Password must contain at least 8 characters, uppercase, lowercase and a number.", "error")
            return render_template("admin/add_user.html")
        document = {
            "name": name[:100],
            "email": email,
            "password_hash": generate_password_hash(password),
            "role": role,
            "department": request.form.get("department", "").strip()[:100],
            "status": "approved" if role != "teacher" else request.form.get("status", "approved"),
            "created_at": utc_now(),
            "created_by": session.get("user_id"),
        }
        try:
            get_collection("users").insert_one(document)
        except DuplicateKeyError:
            flash("A user with this email already exists.", "error")
            return render_template("admin/add_user.html")
        flash("New user profile registered successfully.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/add_user.html")


@admin_bp.route("/add-teacher", methods=["GET", "POST"])
@admin_required
def add_teacher():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name:
            flash("Teacher name is required.", "error")
            return render_template("admin/add_user.html", teacher_mode=True, form_data=request.form)
        if not re.fullmatch(r"^[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}$", email):
            flash("Enter a valid teacher email address.", "error")
            return render_template("admin/add_user.html", teacher_mode=True, form_data=request.form)
        if len(password) < 8 or not re.search(r"[A-Z]", password) or not re.search(r"[a-z]", password) or not re.search(r"\d", password):
            flash("Password must contain at least 8 characters, uppercase, lowercase, and a number.", "error")
            return render_template("admin/add_user.html", teacher_mode=True, form_data=request.form)
        try:
            get_collection("users").insert_one({
                "name": name[:100],
                "email": email,
                "password_hash": generate_password_hash(password),
                "role": "teacher",
                "department": request.form.get("department", "").strip()[:100],
                "status": "approved",
                "created_at": utc_now(),
                "created_by": session.get("user_id"),
            })
        except DuplicateKeyError:
            flash("A user with this email already exists. Use a different email.", "error")
            return render_template("admin/add_user.html", teacher_mode=True, form_data=request.form)
        flash("Instructor registered and approved successfully.", "success")
        return redirect(url_for("admin.teachers"))
    return render_template("admin/add_user.html", teacher_mode=True)


@admin_bp.route("/edit-user", methods=["GET", "POST"])
@admin_required
def edit_user():
    object_id = parse_object_id(request.args.get("id") or request.form.get("user_id"))
    if not object_id:
        flash("Invalid user ID.", "error")
        return redirect(url_for("admin.users"))
    collection = get_collection("users")
    user = collection.find_one({"_id": object_id})
    if not user:
        flash("User not found.", "error")
        return redirect(url_for("admin.users"))
    if request.method == "POST":
        update_data = {
            "name": request.form.get("name", "").strip()[:100],
            "email": request.form.get("email", "").strip().lower(),
            "role": request.form.get("role", "").strip().lower(),
            "department": request.form.get("department", "").strip()[:100],
            "status": request.form.get("status", user.get("status", "approved")).strip().lower(),
            "updated_at": utc_now(),
            "updated_by": session.get("user_id"),
        }
        if not update_data["name"] or not re.fullmatch(r"^[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}$", update_data["email"]) or update_data["role"] not in {"student", "teacher", "admin", "analyst"}:
            flash("Name, valid email and a valid role are required.", "error")
            return render_template("admin/edit_user.html", user=user)
        password = request.form.get("password", "")
        if password:
            if len(password) < 8:
                flash("Password must contain at least 8 characters.", "error")
                return render_template("admin/edit_user.html", user=user)
            update_data["password_hash"] = generate_password_hash(password)
        try:
            collection.update_one({"_id": object_id}, {"$set": update_data})
        except DuplicateKeyError:
            flash("Another user already uses this email.", "error")
            return render_template("admin/edit_user.html", user=user)
        flash("User profile updated successfully.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/edit_user.html", user=user)


@admin_bp.route("/delete-user/<user_id>", methods=["POST"])
@admin_required
def delete_user(user_id):
    object_id = parse_object_id(user_id)
    if not object_id or str(object_id) == str(session.get("user_id")):
        flash("Invalid request or you cannot delete your own account.", "error")
        return redirect(url_for("admin.users"))
    result = get_collection("users").update_one({"_id": object_id}, {"$set": {"status": "deleted", "deleted_at": utc_now()}})
    flash("User deactivated successfully." if result.modified_count else "User not found.", "success" if result.modified_count else "error")
    return redirect(url_for("admin.users"))


@admin_bp.route("/courses")
@admin_required
def courses():
    course_list = list(get_collection("courses").find().sort("created_at", -1).limit(500))
    teachers = list(get_collection("users").find({"role": "teacher", "status": "approved"}, {"name": 1, "department": 1}).sort("name", 1))
    for course in course_list:
        teacher = get_collection("users").find_one({"_id": parse_object_id(course.get("teacher_id"))}) if course.get("teacher_id") else None
        course["teacher_name"] = teacher.get("name") if teacher else "Unassigned"
    return render_template("admin/courses.html", courses=course_list, teachers=teachers)


@admin_bp.route("/courses/new", methods=["GET", "POST"])
@admin_required
def create_course():
    return _course_form()


@admin_bp.route("/courses/<course_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_course(course_id):
    return _course_form(course_id)


def _course_form(course_id=None):
    collection = get_collection("courses")
    course = collection.find_one({"_id": parse_object_id(course_id)}) if course_id else None
    if course_id and not course:
        flash("Course not found.", "error")
        return redirect(url_for("admin.courses"))
    if course:
        course["enrolled_student_ids"] = [
            str(row.get("student_id"))
            for row in AcademicDataService.active_enrollments(course_ids=[str(course["_id"])])
            if row.get("student_id")
        ]
    if request.method == "POST":
        code = request.form.get("code", "").strip().upper()[:30]
        title = request.form.get("title", "").strip()[:160]
        if not code or not title:
            flash("Course code and title are required.", "error")
            return render_template("admin/course_form.html", course=course, teachers=_approved_teachers(), students=_students())
        teacher_id = request.form.get("teacher_id", "").strip()
        if teacher_id:
            teacher = get_collection("users").find_one({
                "_id": parse_object_id(teacher_id),
                "role": "teacher",
                "status": "approved",
            })
            if not teacher:
                flash("Select an approved teacher.", "error")
                return render_template("admin/course_form.html", course=course, teachers=_approved_teachers(), students=_students())
        try:
            credits = max(0, min(30, int(request.form.get("credits", "0") or 0)))
        except ValueError:
            credits = 0
        data = {
            "code": code,
            "title": title,
            "department": request.form.get("department", "").strip()[:100],
            "credits": credits,
            "semester": request.form.get("semester", "").strip()[:80],
            "teacher_id": teacher_id,
            "status": request.form.get("status", "active").strip().lower(),
            "updated_at": utc_now(),
        }
        if course:
            collection.update_one({"_id": course["_id"]}, {"$set": data})
            saved_course_id = course["_id"]
            flash("Course updated successfully.", "success")
        else:
            data["created_at"] = utc_now()
            data["created_by"] = session.get("user_id")
            saved_course_id = collection.insert_one(data).inserted_id
            flash("Course created successfully.", "success")
        AcademicDataService.upsert_enrollments(
            saved_course_id,
            request.form.getlist("student_ids"),
            changed_by=session.get("user_id"),
        )
        AuditService.record(
            "course_updated" if course else "course_created",
            "course",
            saved_course_id,
            user_id=session.get("user_id"),
            role=session.get("role"),
            metadata={"teacher_id": teacher_id, "enrollment_count": len(request.form.getlist("student_ids"))},
        )
        return redirect(url_for("admin.courses"))
    return render_template("admin/course_form.html", course=course, teachers=_approved_teachers(), students=_students())


def _approved_teachers():
    return list(get_collection("users").find({"role": "teacher", "status": "approved"}, {"name": 1}).sort("name", 1))


def _students():
    return list(get_collection("users").find({"role": "student", "status": {"$nin": ["deleted", "suspended"]}}, {"name": 1, "email": 1}).sort("name", 1).limit(1000))


@admin_bp.route("/courses/<course_id>/delete", methods=["POST"])
@admin_required
def delete_course(course_id):
    object_id = parse_object_id(course_id)
    result = get_collection("courses").update_one({"_id": object_id}, {"$set": {"status": "inactive", "updated_at": utc_now()}})
    flash("Course deactivated." if result.modified_count else "Course not found.", "success" if result.modified_count else "error")
    return redirect(url_for("admin.courses"))


@admin_bp.route("/predictions")
@admin_required
def predictions():
    prediction_list = list(get_collection("predictions").find().sort("created_at", -1).limit(200))
    return render_template("admin/predictions.html", predictions=prediction_list)


@admin_bp.route("/reports")
@admin_required
def reports():
    report_list = list(get_collection("reports").find().sort("created_at", -1).limit(100))
    return render_template("admin/reports.html", reports=report_list)


@admin_bp.route("/reports/generate", methods=["POST"])
@admin_required
def generate_report():
    report_type = request.form.get("report_type", "users").strip().lower()
    if report_type == "datasets":
        rows = list(get_collection("datasets").find({}, {"_id": 0, "file_path": 0}))
    elif report_type == "predictions":
        rows = list(get_collection("predictions").find({}, {"_id": 0}))
    elif report_type == "student_analytics":
        rows = list(get_collection("analytics_results").find({}, {"_id": 0}))
        if not rows:
            rows = list(get_collection("grades").find({}, {"_id": 0, "password": 0}))
    elif report_type == "attendance":
        rows = list(get_collection("attendance").find({}, {"_id": 0}))
    else:
        rows = list(get_collection("users").find({}, {"_id": 0, "password": 0, "password_hash": 0, "reset_token_hash": 0, "reset_token_expiry": 0}))
    if not rows:
        rows = [{"message": "No records available for this report."}]
    name = f"{report_type}_{utc_now().strftime('%Y%m%d_%H%M%S')}.csv"
    result = ReportService.generate_institutional_report(rows, name)
    if not result.get("success"):
        flash(result.get("error", "Report generation failed."), "error")
        return redirect(url_for("admin.reports"))
    report = {
        "name": name,
        "category": report_type,
        "path": result["path"],
        "created_at": utc_now(),
        "created_by": session.get("user_id"),
    }
    inserted = get_collection("reports").insert_one(report)
    flash("Report generated successfully.", "success")
    return redirect(url_for("admin.download_report", report_id=str(inserted.inserted_id)))


@admin_bp.route("/reports/<report_id>/download")
@admin_required
def download_report(report_id):
    report = get_collection("reports").find_one({"_id": parse_object_id(report_id)})
    if not report or not os.path.isfile(report.get("path", "")):
        flash("Report file is not available.", "error")
        return redirect(url_for("admin.reports"))
    return send_file(report["path"], as_attachment=True, download_name=report.get("name", "report.csv"))


@admin_bp.route("/system-logs/export")
@admin_required
def export_logs():
    logs = list(get_collection("system_logs").find({}, {"_id": 0}))
    result = ReportService.generate_institutional_report(logs or [{"message": "No logs recorded."}], "system_logs.csv")
    if not result.get("success"):
        flash("Log export failed.", "error")
        return redirect(url_for("admin.system_logs"))
    return send_file(result["path"], as_attachment=True, download_name="system_logs.csv")


@admin_bp.route("/support")
@admin_required
def support():
    tickets = list(get_collection("support_tickets").find().sort("created_at", -1).limit(200))
    return render_template("admin/support.html", tickets=tickets)