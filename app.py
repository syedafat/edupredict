import os
from flask import (
    Flask,
    render_template,
    redirect,
    url_for,
    jsonify,
    flash,
    request,
    g,
    session,
)
from config import Config
from models import mongo
from flask_wtf.csrf import (
    CSRFProtect,
    CSRFError
)
from extensions import limiter
from services.academic_data_service import AcademicDataService
from werkzeug.security import generate_password_hash
from datetime import datetime, timezone
import time
try:
    import resource
except ImportError:  # Windows does not provide the POSIX resource module.
    resource = None

csrf = CSRFProtect()

# ==================================================
# DEFAULT ADMIN
# ==================================================
def create_default_admin():
    """
    Create the initial admin account from .env
    if no admin account already exists.
    """
    admin_name = os.environ.get("ADMIN_NAME")
    admin_email = os.environ.get("ADMIN_EMAIL")
    admin_password = os.environ.get("ADMIN_PASSWORD")

    # Never use a hard-coded/default admin password.
    if not admin_name or not admin_email or not admin_password:
        print(
            "Admin was not created. Please set "
            "ADMIN_NAME, ADMIN_EMAIL and ADMIN_PASSWORD "
            "in the .env file."
        )
        return

    admin_name = admin_name.strip()
    admin_email = admin_email.strip().lower()

    try:
        # Check whether an admin already exists.
        existing_admin = mongo.db.users.find_one({
            "role": "admin"
        })

        if existing_admin:
            return

        admin_data = {
            "name": admin_name,
            "email": admin_email,
            "password_hash": generate_password_hash(
                admin_password
            ),
            "role": "admin",
            "department": "Management",
            "status": "approved",
            "created_at": datetime.now(
                timezone.utc
            )
        }

        mongo.db.users.insert_one(
            admin_data
        )

        print(
            f"Admin account created successfully: "
            f"{admin_email}"
        )

    except Exception as exc:
        print(
            f"Could not create initial admin: {exc}"
        )

# ==================================================
# CREATE APP
# ==================================================
def create_app(config_class=Config):
    app = Flask(__name__)

    app.config.from_object(
        config_class
    )

    @app.context_processor
    def global_template_values():
        return {
            "max_upload_mb": round(app.config["MAX_CONTENT_LENGTH"] / (1024 * 1024), 1),
            "allowed_dataset_extensions": sorted(app.config["ALLOWED_DATASET_EXTENSIONS"]),
            "valid_dataset_types": sorted(app.config["VALID_DATASET_TYPES"]),
            "hdfs_enabled": app.config.get("HADOOP_ENABLED", False),
        }

    # ==================================================
    # INITIALIZE EXTENSIONS
    # ==================================================

    mongo.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    # ==================================================
    # DATABASE INITIALIZATION
    # ==================================================

    app.extensions[
        "edupredict_indexes_ready"
    ] = False

    @app.before_request
    def ensure_db_indexes():
        g.request_started_at = time.perf_counter()
        if app.extensions[
            "edupredict_indexes_ready"
        ]:
            return

        try:
            # Users
            mongo.db.users.create_index(
                "email",
                unique=True
            )

            # Notifications
            mongo.db.notifications.create_index(
                [
                    ("user_id", 1),
                    ("created_at", -1)
                ]
            )

            # Support tickets
            mongo.db.support_tickets.create_index(
                [
                    ("created_by", 1),
                    ("created_at", -1)
                ]
            )
            mongo.db.datasets.create_index([("dataset_type", 1), ("uploaded_at", -1)])
            mongo.db.datasets.create_index([("source_hash", 1), ("dataset_type", 1)])
            mongo.db.rejected_records.create_index([("dataset_id", 1), ("created_at", -1)])
            mongo.db.predictions.create_index([("student_id", 1), ("model_type", 1), ("created_at", -1)])
            mongo.db.attendance.create_index([("student_id", 1), ("date", -1)])
            mongo.db.grades.create_index([("student_id", 1), ("created_at", -1)])
            mongo.db.assignments.create_index([("student_id", 1), ("status", 1), ("due_date", 1)])
            mongo.db.assignments.create_index([("student_id", 1), ("assignment_key", 1)], unique=True, sparse=True)
            mongo.db.submissions.create_index([("student_id", 1), ("assignment_id", 1)], unique=True)
            mongo.db.enrollments.create_index([("student_id", 1), ("status", 1)])
            mongo.db.enrollments.create_index([("course_id", 1), ("status", 1)])
            AcademicDataService.migrate_legacy_course_rosters()
            mongo.db.enrollments.create_index(
                [("student_id", 1), ("course_id", 1)],
                unique=True,
                name="unique_student_course_enrollment",
            )
            mongo.db.stream_events.create_index([("student_id", 1), ("received_at", -1)])
            mongo.db.system_logs.create_index([("event_type", 1), ("created_at", -1)])
            mongo.db.audit_logs.create_index([("target_type", 1), ("target_id", 1), ("timestamp", -1)])
            mongo.db.audit_logs.create_index([("user_id", 1), ("timestamp", -1)])

            # Create initial admin only after
            # MongoDB has responded successfully.
            create_default_admin()

            app.extensions[
                "edupredict_indexes_ready"
            ] = True

        except Exception as exc:
            app.logger.warning(
                "Database initialization failed: %s",
                exc
            )

            # Keep this False so the application can
            # retry when MongoDB becomes available.
            app.extensions[
                "edupredict_indexes_ready"
            ] = False

    @app.after_request
    def record_request_metrics(response):
        started = getattr(g, "request_started_at", None)
        if started is not None and request.path != "/monitoring/health":
            try:
                usage = resource.getrusage(resource.RUSAGE_SELF) if resource else None
                mongo.db.system_logs.insert_one({
                    "event_type": "request",
                    "path": request.path,
                    "method": request.method,
                    "status_code": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    "cpu_user_seconds": round(usage.ru_utime, 4) if usage else None,
                    "cpu_system_seconds": round(usage.ru_stime, 4) if usage else None,
                    "role": session.get("role"),
                    "created_at": datetime.now(timezone.utc),
                    "level": "ERROR" if response.status_code >= 500 else "INFO",
                })
            except Exception:
                pass
        return response

    # ==================================================
    # STORAGE DIRECTORIES
    # ==================================================

    os.makedirs(
        app.config["UPLOAD_FOLDER"],
        exist_ok=True
    )

    os.makedirs(
        app.config["MODEL_FOLDER"],
        exist_ok=True
    )

    # ==================================================
    # REGISTER BLUEPRINTS
    # ==================================================

    from routes.auth_routes import auth_bp
    from routes.admin_routes import admin_bp
    from routes.teacher_routes import teacher_bp
    from routes.student_routes import student_bp
    from routes.analyst_routes import analyst_bp
    from routes.data_routes import data_bp
    from routes.ml_routes import ml_bp
    from routes.notification_routes import notification_bp
    from routes.support_routes import support_bp
    from routes.monitoring_routes import monitoring_bp

    app.register_blueprint(
        auth_bp,
        url_prefix="/auth"
    )

    app.register_blueprint(
        admin_bp,
        url_prefix="/admin"
    )

    app.register_blueprint(
        teacher_bp,
        url_prefix="/teacher"
    )

    app.register_blueprint(
        student_bp,
        url_prefix="/student"
    )

    app.register_blueprint(
        analyst_bp,
        url_prefix="/analyst"
    )

    app.register_blueprint(
        data_bp,
        url_prefix="/data"
    )

    app.register_blueprint(
        ml_bp,
        url_prefix="/ml"
    )

    app.register_blueprint(
        notification_bp,
        url_prefix="/notifications"
    )

    app.register_blueprint(
        support_bp,
        url_prefix="/support"
    )
    app.register_blueprint(
        monitoring_bp,
        url_prefix="/monitoring"
    )

    # ==================================================
    # ERROR HANDLERS
    # ==================================================

    @app.errorhandler(403)
    def forbidden_error(error):
        return render_template(
            "403.html"
        ), 403

    @app.errorhandler(404)
    def not_found_error(error):
        return render_template(
            "404.html"
        ), 404

    @app.errorhandler(500)
    def internal_error(error):
        return render_template(
            "500.html"
        ), 500

    @app.errorhandler(429)
    def rate_limit_error(error):
        if (
            request.accept_mimetypes.accept_json
            and not request.accept_mimetypes.accept_html
        ):
            return jsonify({
                "status": "error",
                "message": (
                    "Too many requests. "
                    "Please try again later."
                )
            }), 429

        flash(
            "Too many attempts. "
            "Please wait a moment and try again.",
            "danger"
        )

        return redirect(
            url_for("auth.login")
        ), 429

    @app.errorhandler(CSRFError)
    def csrf_error(error):
        app.logger.info(
            "Rejected request with invalid CSRF token: %s",
            error.description
        )

        if (
            request.accept_mimetypes.accept_json
            and not request.accept_mimetypes.accept_html
        ):
            return jsonify({
                "status": "error",
                "message": (
                    "The form expired. "
                    "Please try again."
                )
            }), 400

        return render_template(
            "400.html",
            message=(
                "The form expired. "
                "Please try again."
            )
        ), 400

    # ==================================================
    # HOME
    # ==================================================

    @app.route("/")
    def index():
        return redirect(
            url_for("auth.login")
        )

    return app

# ==================================================
# APPLICATION
# ==================================================
app = create_app()

if __name__ == "__main__":
    debug_mode = (
        os.environ.get(
            "FLASK_DEBUG",
            "false"
        ).lower()
        == "true"
    )

    app.run(
        debug=debug_mode,
        host="0.0.0.0",
        port=5000
    )