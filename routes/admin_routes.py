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
    abort,
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
from extensions import limiter


admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def admin_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login to continue.", "error")
            return redirect(url_for("auth.login"))
        if session.get("role") != "admin":
            abort(403)
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
    anomalies_list = list(get_collection("anomalies").find().sort("created_at", -1).limit(100))
    student_ids = []
    for a in anomalies_list:
        sid = a.get("student_id")
        if sid and ObjectId.is_valid(str(sid)):
            student_ids.append(ObjectId(str(sid)))
    users_map = {str(u["_id"]): u.get("name", "Student") for u in get_collection("users").find({"_id": {"$in": student_ids}}, {"name": 1, "department": 1})}

    for a in anomalies_list:
        a["student_name"] = users_map.get(str(a.get("student_id")), f"Student {a.get('student_id', '')}")
    return render_template("admin/anomalies.html", anomalies=anomalies_list)


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
    from ml.model_manager import ModelManager, SUPPORTED_MODEL_TYPES
    training_docs = {
        doc["model_type"]: doc
        for doc in get_collection("model_training").find({"status": "active"}).sort("trained_at", -1)
    }

    model_cards = []
    for mtype in sorted(SUPPORTED_MODEL_TYPES):
        exists = ModelManager.model_exists(mtype)
        rec = training_docs.get(mtype)
        valid_artifact = bool(rec and ModelManager.artifact_matches(mtype, rec))

        model_cards.append({
            "name": mtype,
            "title": mtype.replace("_", " ").title(),
            "exists": exists,
            "status": "Active & Verified" if (exists and valid_artifact) else ("Unregistered Artifact" if exists else "Not Trained"),
            "is_active": bool(exists and valid_artifact),
            "algorithm": rec.get("algorithm", "Scikit-Learn Standard") if rec else "None",
            "version": rec.get("model_version", "None") if rec else "None",
            "metrics": rec.get("metrics", {}) if rec else {},
            "samples": rec.get("samples", 0) if rec else 0,
            "trained_at": rec.get("trained_at") if rec else None,
            "endpoint": f"/ml/predict/{mtype}",
        })
    return render_template("admin/ml_models.html", models=model_cards, model_status=_model_status())


@admin_bp.route("/ml-models/retrain", methods=["POST"])
@admin_required
def retrain_models():
    try:
        from train_models import train_and_save_all_models
        train_and_save_all_models()
        flash("Machine Learning models retrained and registered successfully.", "success")
    except Exception as exc:
        current_app.logger.error("Model retraining failed (error type: %s).", type(exc).__name__)
        flash("Model retraining failed. Check the server logs for details.", "error")
    return redirect(url_for("admin.ml_models"))


def _model_status():
    from ml.model_manager import ModelManager, SUPPORTED_MODEL_TYPES
    return {model_type: ModelManager.model_exists(model_type) for model_type in sorted(SUPPORTED_MODEL_TYPES)}


def standardize_department_name(dept):
    """Normalize legacy shortcodes (cs, se, it, general) to standardized department names."""
    if not dept or not isinstance(dept, str):
        return ""
    clean = dept.strip()
    lower = clean.lower()
    if lower in ("general", "none", "n/a", "-", "null", "all"):
        return ""
    if lower in ("se", "software engineer", "software engineering"):
        return "Software Engineering"
    if lower in ("cs", "computer science"):
        return "Computer Science"
    if lower in ("it", "information technology"):
        return "Information Technology"
    if lower in ("ai", "artificial intelligence"):
        return "Artificial Intelligence"
    if lower in ("ds", "data science"):
        return "Data Science"
    return clean


def _available_departments():
    """Fetch all unique active department names dynamically from the new departments collection and fallback to legacy strings."""
    depts = set()
    try:
        if hasattr(mongo.db, "departments"):
            for doc in get_collection("departments").find({}, {"name": 1}):
                name = doc.get("name")
                if name:
                    depts.add(name)
    except Exception:
        pass
    try:
        if hasattr(mongo.db, "courses"):
            for doc in get_collection("courses").find({"status": {"$ne": "inactive"}, "department": {"$nin": ["", None]}}, {"department": 1}):
                val = standardize_department_name(doc.get("department"))
                if val:
                    depts.add(val)
        if hasattr(mongo.db, "users"):
            for doc in get_collection("users").find({"department": {"$nin": ["", None]}}, {"department": 1}):
                val = standardize_department_name(doc.get("department"))
                if val:
                    depts.add(val)
    except Exception:
        pass
    if not depts:
        depts = {"Artificial Intelligence", "Computer Science", "Data Science", "Information Technology", "Software Engineering"}
    return sorted(depts, key=lambda x: x.lower())


def _department_records():
    try:
        if hasattr(mongo.db, "departments"):
            return list(get_collection("departments").find().sort("name", 1))
    except Exception:
        pass
    return []


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
        dept_lower = department.lower()
        if dept_lower in ("software engineering", "software engineer", "se"):
            query["department"] = {"$in": ["Software Engineering", "software engineering", "software engineer", "se"]}
        elif dept_lower in ("computer science", "cs"):
            query["department"] = {"$in": ["Computer Science", "computer science", "cs"]}
        elif dept_lower in ("information technology", "it"):
            query["department"] = {"$in": ["Information Technology", "information technology", "it"]}
        elif dept_lower in ("artificial intelligence", "ai"):
            query["department"] = {"$in": ["Artificial Intelligence", "artificial intelligence", "ai"]}
        elif dept_lower in ("data science", "ds"):
            query["department"] = {"$in": ["Data Science", "data science", "ds"]}
        else:
            query["department"] = {"$regex": f"^{re.escape(department)}$", "$options": "i"}

    student_list = list(
        get_collection("users").find(query, {"password": 0, "password_hash": 0})
        .sort("created_at", -1)
        .limit(500)
    )
    for student in student_list:
        raw_dept = student.get("department")
        std_dept = standardize_department_name(raw_dept)
        if std_dept:
            student["department"] = std_dept
        elif raw_dept and raw_dept.lower() == "general":
            student["department"] = "General Studies"

    departments = _available_departments()
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
        raw_dept = teacher.get("department")
        std_dept = standardize_department_name(raw_dept)
        if std_dept:
            teacher["department"] = std_dept
    departments = _available_departments()
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


@admin_bp.route("/teacher-attendance", methods=["GET", "POST"])
@admin_required
def teacher_attendance():
    attendance_col = get_collection("teacher_attendance")

    if request.method == "POST":
        date_str = request.form.get("date", "").strip()
        records = {}  # teacher_id -> status
        for key, value in request.form.items():
            if key.startswith("status_"):
                tid = key[len("status_"):]
                records[tid] = value.strip().lower()

        if not date_str:
            flash("Please select a date before saving attendance.", "error")
            return redirect(url_for("admin.teacher_attendance"))

        # Validate date format
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            flash("Invalid date format.", "error")
            return redirect(url_for("admin.teacher_attendance"))

        if not records:
            flash("No attendance data submitted.", "error")
            return redirect(url_for("admin.teacher_attendance") + f"?date={date_str}")

        # Fetch teacher names for denormalization
        teacher_names = {}
        for teacher in get_collection("users").find({"role": "teacher"}, {"_id": 1, "name": 1}):
            teacher_names[str(teacher["_id"])] = teacher.get("name", "Unknown")

        saved = 0
        for tid, status in records.items():
            if status not in ("present", "absent", "leave"):
                continue
            attendance_col.update_one(
                {"teacher_id": tid, "date": date_str},
                {
                    "$set": {
                        "status": status,
                        "teacher_name": teacher_names.get(tid, "Unknown"),
                        "marked_by": session.get("user_id"),
                        "marked_at": utc_now(),
                    }
                },
                upsert=True,
            )
            saved += 1

        flash(f"Attendance saved for {saved} teacher(s) on {date_str}.", "success")
        return redirect(url_for("admin.teacher_attendance") + f"?date={date_str}")

    # GET — default to today
    date_str = request.args.get("date", "").strip()
    if not date_str:
        date_str = utc_now().strftime("%Y-%m-%d")

    teacher_list = list(
        get_collection("users")
        .find({"role": "teacher"}, {"password": 0, "password_hash": 0})
        .sort("name", 1)
    )
    for t in teacher_list:
        raw_dept = t.get("department")
        std = standardize_department_name(raw_dept)
        if std:
            t["department"] = std

    # Fetch already-saved attendance records for this date
    existing = {
        rec["teacher_id"]: rec["status"]
        for rec in attendance_col.find({"date": date_str})
    }

    # Compute summary counts for the selected date
    summary = {
        "present": sum(1 for s in existing.values() if s == "present"),
        "absent": sum(1 for s in existing.values() if s == "absent"),
        "leave": sum(1 for s in existing.values() if s == "leave"),
        "unmarked": sum(1 for t in teacher_list if str(t["_id"]) not in existing),
    }

    return render_template(
        "admin/teacher_attendance.html",
        teachers=teacher_list,
        existing=existing,
        date_str=date_str,
        summary=summary,
    )


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
@limiter.limit("10 per hour", methods=["POST"])
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
    for u in user_list:
        raw_dept = u.get("department")
        std_dept = standardize_department_name(raw_dept)
        if std_dept:
            u["department"] = std_dept
        elif raw_dept and raw_dept.lower() == "general":
            u["department"] = "General Studies"
    counts = {
        "total": users_collection.count_documents({}),
        "students": users_collection.count_documents({"role": "student"}),
            "staff": users_collection.count_documents({"role": {"$in": ["teacher", "admin", "analyst"]}}),
    }
    return render_template("admin/users.html", users=user_list, counts=counts, search=search)


@admin_bp.route("/add-user", methods=["GET", "POST"])
@admin_required
def add_user():
    departments = _available_departments()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "").strip().lower()
        if not name or not email or not re.fullmatch(r"^[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}$", email) or not password or role not in {"student", "teacher", "admin", "analyst"}:
            flash("Name, email, password, and a valid role are required.", "error")
            return render_template("admin/add_user.html", departments=departments, form_data=request.form)
        if len(password) < 8 or not re.search(r"[A-Z]", password) or not re.search(r"[a-z]", password) or not re.search(r"\d", password):
            flash("Password must contain at least 8 characters, uppercase, lowercase and a number.", "error")
            return render_template("admin/add_user.html", departments=departments, form_data=request.form)
        document = {
            "name": name[:100],
            "email": email,
            "password_hash": generate_password_hash(password),
            "role": role,
            "department": request.form.get("department", "").strip()[:100],
            "status": "active" if role == "student" else request.form.get("status", "approved"),
            "created_at": utc_now(),
            "created_by": session.get("user_id"),
        }
        try:
            get_collection("users").insert_one(document)
        except DuplicateKeyError:
            flash("A user with this email already exists.", "error")
            return render_template("admin/add_user.html", departments=departments, form_data=request.form)
        flash("New user profile registered successfully.", "success")
        return redirect(url_for("admin.users"))
    return render_template("admin/add_user.html", departments=departments)


@admin_bp.route("/add-teacher", methods=["GET", "POST"])
@admin_required
def add_teacher():
    departments = _available_departments()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name:
            flash("Teacher name is required.", "error")
            return render_template("admin/add_user.html", teacher_mode=True, form_data=request.form, departments=departments)
        if not re.fullmatch(r"^[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}$", email):
            flash("Enter a valid teacher email address.", "error")
            return render_template("admin/add_user.html", teacher_mode=True, form_data=request.form, departments=departments)
        if len(password) < 8 or not re.search(r"[A-Z]", password) or not re.search(r"[a-z]", password) or not re.search(r"\d", password):
            flash("Password must contain at least 8 characters, uppercase, lowercase, and a number.", "error")
            return render_template("admin/add_user.html", teacher_mode=True, form_data=request.form, departments=departments)
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
            return render_template("admin/add_user.html", teacher_mode=True, form_data=request.form, departments=departments)
        flash("Instructor registered and approved successfully.", "success")
        return redirect(url_for("admin.teachers"))
    return render_template("admin/add_user.html", teacher_mode=True, departments=departments)


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
    departments = _department_records()
    dept_map = {str(d["_id"]): d.get("name", "Unknown") for d in departments}

    # Count subjects per course for quick visibility
    subject_counts = {}
    for sub in get_collection("subjects").find({}, {"course_id": 1}):
        cid_str = str(sub.get("course_id", ""))
        subject_counts[cid_str] = subject_counts.get(cid_str, 0) + 1

    for course in course_list:
        teacher = get_collection("users").find_one({"_id": parse_object_id(course.get("teacher_id"))}) if course.get("teacher_id") else None
        course["teacher_name"] = teacher.get("name") if teacher else "Unassigned"
        dept_id = course.get("department_id")
        if dept_id and str(dept_id) in dept_map:
            course["department_name"] = dept_map[str(dept_id)]
        else:
            course["department_name"] = course.get("department") or "Unassigned"
        counts = AcademicDataService.course_student_counts([str(course["_id"])])
        course["active_student_count"] = counts.get(str(course["_id"]), 0)
        course["inactive_student_count"] = get_collection("enrollments").count_documents({"course_id": str(course["_id"]), "status": {"$nin": ["active", "enrolled"]}})
        course["subject_count"] = subject_counts.get(str(course["_id"]), 0)
    return render_template("admin/courses.html", courses=course_list, teachers=teachers, departments=departments)


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
            return render_template("admin/course_form.html", course=course, teachers=_approved_teachers(), students=_students(), departments=_department_records())
        
        # Check duplicate course code
        code_filter = {"code": code}
        if course:
            code_filter["_id"] = {"$ne": course["_id"]}
        if collection.find_one(code_filter):
            flash(f"A course with code '{code}' already exists.", "error")
            return render_template("admin/course_form.html", course=course, teachers=_approved_teachers(), students=_students(), departments=_department_records())
        teacher_id = request.form.get("teacher_id", "").strip()
        student_ids = request.form.getlist("student_ids")
        enrollment_errors = AcademicDataService.validate_enrollment_students(student_ids)
        if enrollment_errors:
            for error in enrollment_errors:
                flash(error, "error")
            return render_template("admin/course_form.html", course=course, teachers=_approved_teachers(), students=_students(), departments=_department_records())
        if teacher_id:
            teacher = get_collection("users").find_one({
                "_id": parse_object_id(teacher_id),
                "role": "teacher",
                "status": "approved",
            })
            if not teacher:
                flash("Select an approved teacher.", "error")
                return render_template("admin/course_form.html", course=course, teachers=_approved_teachers(), students=_students(), departments=_department_records())
        try:
            credits = max(0, min(30, int(request.form.get("credits", "0") or 0)))
        except ValueError:
            credits = 0

        department_id_raw = request.form.get("department_id", "").strip()
        dept_obj_id = parse_object_id(department_id_raw) if department_id_raw else None
        dept_doc = get_collection("departments").find_one({"_id": dept_obj_id}) if dept_obj_id else None
        dept_name = dept_doc.get("name") if dept_doc else request.form.get("department", "").strip()[:100]

        data = {
            "code": code,
            "title": title,
            "department_id": dept_obj_id,
            "department": dept_name,
            "credits": credits,
            "semester": request.form.get("semester", "").strip()[:80],
            "teacher_id": teacher_id,
            "status": request.form.get("status", "active").strip().lower() or "active",
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
            student_ids,
            changed_by=session.get("user_id"),
        )
        # Auto-inherit department: update every enrolled student's department
        # fields to match this course so admins never need to do it manually.
        saved_course_doc = get_collection("courses").find_one({"_id": saved_course_id})
        dept_updated = AcademicDataService.sync_student_departments(saved_course_doc)
        if dept_updated:
            flash(
                f"{dept_updated} student(s) automatically updated to department: {dept_name or 'Unknown'}.",
                "info",
            )
        AuditService.record(
            "course_updated" if course else "course_created",
            "course",
            saved_course_id,
            user_id=session.get("user_id"),
            role=session.get("role"),
            metadata={
                "teacher_id": teacher_id,
                "enrollment_count": len(request.form.getlist("student_ids")),
                "dept_students_updated": dept_updated,
            },
        )
        return redirect(url_for("admin.courses"))
    return render_template("admin/course_form.html", course=course, teachers=_approved_teachers(), students=_students(), departments=_department_records())


def _approved_teachers():
    return list(get_collection("users").find({"role": "teacher", "status": "approved"}, {"name": 1}).sort("name", 1))


def _students():
    return list(get_collection("users").find({"role": "student", "status": {"$nin": ["deleted", "suspended"]}}, {"name": 1, "email": 1}).sort("name", 1).limit(1000))


@admin_bp.route("/courses/<course_id>/delete", methods=["POST"])
@admin_required
def delete_course(course_id):
    object_id = parse_object_id(course_id)
    course = get_collection("courses").find_one({"_id": object_id}, {"status": 1}) if object_id else None
    if not course:
        flash("Course not found.", "error")
        return redirect(url_for("admin.courses"))
    next_status = "active" if course.get("status") == "inactive" else "inactive"
    result = get_collection("courses").update_one({"_id": object_id}, {"$set": {"status": next_status, "updated_at": utc_now()}})
    action = "activated" if next_status == "active" else "deactivated"
    flash(f"Course {action}." if result.modified_count else "Course was not changed.", "success" if result.modified_count else "error")
    return redirect(url_for("admin.courses"))


@admin_bp.route("/predictions")
@admin_required
def predictions():
    prediction_list = list(get_collection("predictions").find().sort("created_at", -1).limit(200))
    student_ids = []
    for p in prediction_list:
        sid = p.get("student_id")
        if sid and ObjectId.is_valid(str(sid)):
            student_ids.append(ObjectId(str(sid)))
    users_map = {str(u["_id"]): u.get("name", "Student") for u in get_collection("users").find({"_id": {"$in": student_ids}}, {"name": 1, "student_id": 1, "department": 1})}

    for p in prediction_list:
        p["student_name"] = users_map.get(str(p.get("student_id")), f"Student {p.get('student_id', '')}")
        risk = p.get("risk_score")
        if risk is None and isinstance(p.get("prediction"), (int, float)):
            risk = float(p.get("prediction"))

        if risk is not None:
            p["risk_percent"] = f"{round(risk * 100, 1)}%" if risk <= 1.0 else f"{round(risk, 1)}%"
            if risk >= 0.7:
                p["risk_level"] = "High Risk"
                p["risk_badge"] = "bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300"
            elif risk >= 0.4:
                p["risk_level"] = "Moderate Risk"
                p["risk_badge"] = "bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300"
            else:
                p["risk_level"] = "Low Risk"
                p["risk_badge"] = "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
        else:
            p["risk_percent"] = "—"
            p["risk_level"] = "Normal"
            p["risk_badge"] = "bg-slate-50 text-slate-700 dark:bg-slate-800 dark:text-slate-300"

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
    reports_root = os.path.realpath(
        os.path.join(current_app.config["UPLOAD_FOLDER"], "historical")
    )
    report_path = os.path.realpath(report.get("path", "")) if report else ""
    try:
        confined = bool(report_path) and os.path.commonpath(
            [reports_root, report_path]
        ) == reports_root
    except (ValueError, OSError):
        confined = False
    if not report or not confined or not os.path.isfile(report_path):
        flash("Report file is not available.", "error")
        return redirect(url_for("admin.reports"))
    return send_file(report_path, as_attachment=True, download_name=report.get("name", "report.csv"))


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

# ----------------------------------------------------------------------
# Department CRUD routes
# ----------------------------------------------------------------------
@admin_bp.route("/departments")
@admin_required
def departments():
    try:
        dept_coll = get_collection("departments")
        dept_list = list(dept_coll.find().sort("name", 1))
    except Exception as exc:
        current_app.logger.error("Could not load departments (error type: %s).", type(exc).__name__)
        flash("Unable to load departments.", "error")
        dept_list = []
    return render_template("admin/departments.html", departments=dept_list)

@admin_bp.route("/departments/new", methods=["GET", "POST"])
@admin_required
def new_department():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        legacy_codes = [code.strip() for code in request.form.get("legacy_codes", "").split(",") if code.strip()]
        if not name:
            flash("Department name is required.", "error")
            return render_template("admin/department_form.html")
        # Prevent duplicate department names
        existing = get_collection("departments").find_one({"name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}})
        if existing:
            flash("A department with this name already exists.", "error")
            return render_template("admin/department_form.html")
        get_collection("departments").insert_one({
            "name": name[:120],
            "legacy_codes": legacy_codes,
            "created_at": utc_now(),
            "created_by": session.get("user_id"),
        })
        flash("Department added.", "success")
        return redirect(url_for("admin.departments"))
    return render_template("admin/department_form.html")

@admin_bp.route("/departments/<department_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_department(department_id):
    obj_id = parse_object_id(department_id)
    if not obj_id:
        flash("Invalid department ID.", "error")
        return redirect(url_for("admin.departments"))
    coll = get_collection("departments")
    dept = coll.find_one({"_id": obj_id})
    if not dept:
        flash("Department not found.", "error")
        return redirect(url_for("admin.departments"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        legacy_codes = [code.strip() for code in request.form.get("legacy_codes", "").split(",") if code.strip()]
        if not name:
            flash("Department name is required.", "error")
            return render_template("admin/department_form.html", department=dept)
        existing = coll.find_one({
            "_id": {"$ne": obj_id},
            "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"},
        })
        if existing:
            flash("A department with this name already exists.", "error")
            return render_template("admin/department_form.html", department=dept)
        coll.update_one({"_id": obj_id}, {"$set": {
            "name": name[:120],
            "legacy_codes": legacy_codes,
            "updated_at": utc_now(),
            "updated_by": session.get("user_id"),
        }})
        flash("Department updated.", "success")
        return redirect(url_for("admin.departments"))
    return render_template("admin/department_form.html", department=dept)

@admin_bp.route("/departments/<department_id>/delete", methods=["POST"])
@admin_required
def delete_department(department_id):
    obj_id = parse_object_id(department_id)
    if not obj_id:
        flash("Invalid department ID.", "error")
        return redirect(url_for("admin.departments"))
    # Prevent deletion if any courses reference this department
    linked = get_collection("courses").count_documents({"department_id": obj_id})
    if linked:
        flash(f"Cannot delete – {linked} course(s) reference this department.", "error")
        return redirect(url_for("admin.departments"))
    get_collection("departments").delete_one({"_id": obj_id})
    flash("Department removed.", "success")
    return redirect(url_for("admin.departments"))

# Migration endpoint for legacy courses
@admin_bp.route("/departments/migrate", methods=["POST"])
@admin_required
def migrate_course_departments():
    from scripts.migrate_departments import migrate_course_departments as run_migration
    result = run_migration()
    flash(f"Migration complete – {result['updated']} courses updated.", "success" if result['updated'] else "warning")
    return redirect(url_for("admin.courses"))


# ----------------------------------------------------------------------
# Subject CRUD routes
# ----------------------------------------------------------------------
@admin_bp.route("/subjects")
@admin_required
def subjects():
    course_id_filter = request.args.get("course_id", "").strip()
    query = {}
    if course_id_filter:
        obj_id = parse_object_id(course_id_filter)
        if obj_id:
            query["course_id"] = {"$in": [str(course_id_filter), obj_id]}
        else:
            query["course_id"] = course_id_filter
    subject_list = list(get_collection("subjects").find(query).sort("name", 1).limit(500))
    all_courses = list(get_collection("courses").find({}, {"code": 1, "title": 1, "department": 1}).sort("code", 1))
    return render_template(
        "admin/subjects.html",
        subjects=subject_list,
        courses=all_courses,
        selected_course_id=course_id_filter,
    )


@admin_bp.route("/subjects/new", methods=["GET", "POST"])
@admin_required
def new_subject():
    all_courses = list(get_collection("courses").find({"status": "active"}).sort("code", 1))
    if request.method == "POST":
        course_id = request.form.get("course_id", "").strip()
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip().upper()
        description = request.form.get("description", "").strip()
        status = request.form.get("status", "active").strip().lower() or "active"

        if not course_id or not name or not code:
            flash("Course, Subject Name, and Subject Code are required.", "error")
            return render_template("admin/subject_form.html", courses=all_courses)

        course_obj_id = parse_object_id(course_id)
        course_doc = get_collection("courses").find_one({"_id": course_obj_id}) if course_obj_id else None
        if not course_doc:
            flash("Selected course could not be found.", "error")
            return render_template("admin/subject_form.html", courses=all_courses)

        # Check unique constraint within same course
        existing = get_collection("subjects").find_one({
            "course_id": {"$in": [course_obj_id, str(course_obj_id)]},
            "code": code,
        })
        if existing:
            flash(f"A subject with code '{code}' already exists under this course.", "error")
            return render_template("admin/subject_form.html", courses=all_courses)

        doc = {
            "name": name[:160],
            "code": code[:40],
            "description": description[:2000],
            "course_id": course_obj_id,
            "course_code": course_doc.get("code", ""),
            "course_title": course_doc.get("title", ""),
            "department_id": course_doc.get("department_id"),
            "department_name": course_doc.get("department", "General Studies"),
            "status": status,
            "created_at": utc_now(),
            "created_by": session.get("user_id"),
            "updated_at": utc_now(),
        }
        get_collection("subjects").insert_one(doc)
        flash(f"Subject '{name}' created successfully.", "success")
        return redirect(url_for("admin.subjects", course_id=str(course_obj_id)))

    return render_template("admin/subject_form.html", courses=all_courses)


@admin_bp.route("/subjects/<subject_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_subject(subject_id):
    obj_id = parse_object_id(subject_id)
    if not obj_id:
        flash("Invalid subject ID.", "error")
        return redirect(url_for("admin.subjects"))

    coll = get_collection("subjects")
    subject = coll.find_one({"_id": obj_id})
    if not subject:
        flash("Subject not found.", "error")
        return redirect(url_for("admin.subjects"))

    all_courses = list(get_collection("courses").find({"status": "active"}).sort("code", 1))

    if request.method == "POST":
        course_id = request.form.get("course_id", "").strip()
        name = request.form.get("name", "").strip()
        code = request.form.get("code", "").strip().upper()
        description = request.form.get("description", "").strip()
        status = request.form.get("status", "active").strip().lower() or "active"

        if not course_id or not name or not code:
            flash("Course, Subject Name, and Subject Code are required.", "error")
            return render_template("admin/subject_form.html", subject=subject, courses=all_courses)

        course_obj_id = parse_object_id(course_id)
        course_doc = get_collection("courses").find_one({"_id": course_obj_id}) if course_obj_id else None
        if not course_doc:
            flash("Selected course could not be found.", "error")
            return render_template("admin/subject_form.html", subject=subject, courses=all_courses)

        # Check duplicate code within course (excluding self)
        existing = coll.find_one({
            "_id": {"$ne": obj_id},
            "course_id": {"$in": [course_obj_id, str(course_obj_id)]},
            "code": code,
        })
        if existing:
            flash(f"A subject with code '{code}' already exists under this course.", "error")
            return render_template("admin/subject_form.html", subject=subject, courses=all_courses)

        coll.update_one({"_id": obj_id}, {"$set": {
            "name": name[:160],
            "code": code[:40],
            "description": description[:2000],
            "course_id": course_obj_id,
            "course_code": course_doc.get("code", ""),
            "course_title": course_doc.get("title", ""),
            "department_id": course_doc.get("department_id"),
            "department_name": course_doc.get("department", "General Studies"),
            "status": status,
            "updated_at": utc_now(),
            "updated_by": session.get("user_id"),
        }})
        flash(f"Subject '{name}' updated successfully.", "success")
        return redirect(url_for("admin.subjects", course_id=str(course_obj_id)))

    return render_template("admin/subject_form.html", subject=subject, courses=all_courses)


@admin_bp.route("/subjects/<subject_id>/delete", methods=["POST"])
@admin_required
def delete_subject(subject_id):
    obj_id = parse_object_id(subject_id)
    if not obj_id:
        flash("Invalid subject ID.", "error")
        return redirect(url_for("admin.subjects"))

    coll = get_collection("subjects")
    subject = coll.find_one({"_id": obj_id})
    if not subject:
        flash("Subject not found.", "error")
        return redirect(url_for("admin.subjects"))

    # Check if subject is referenced in grades, attendance, or assignments
    grades_count = get_collection("grades").count_documents({"subject_id": {"$in": [str(obj_id), obj_id]}})
    att_count = get_collection("attendance").count_documents({"subject_id": {"$in": [str(obj_id), obj_id]}})
    assign_count = get_collection("assignments").count_documents({"subject_id": {"$in": [str(obj_id), obj_id]}})

    if grades_count or att_count or assign_count:
        # Soft-deactivate to protect historical academic records
        coll.update_one({"_id": obj_id}, {"$set": {"status": "inactive", "updated_at": utc_now()}})
        flash(f"Subject has linked records ({grades_count} grades, {att_count} attendance, {assign_count} assignments). It has been marked Inactive.", "warning")
    else:
        coll.delete_one({"_id": obj_id})
        flash(f"Subject '{subject.get('name')}' removed.", "success")
    return redirect(url_for("admin.subjects"))
