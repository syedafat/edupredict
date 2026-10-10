from flask_pymongo import PyMongo
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
    has_app_context,
    current_app,
)
from config import Config
from models import mongo
from flask_wtf.csrf import (
    CSRFProtect,
    CSRFError
)
from werkzeug.middleware.proxy_fix import ProxyFix
from extensions import limiter
from services.academic_data_service import AcademicDataService
from werkzeug.security import generate_password_hash
from datetime import datetime, timezone
import time
import logging
import secrets
import traceback
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
    if current_app.config.get("APP_ENV") == "production":
        current_app.logger.info("Automatic admin bootstrap is disabled in production.")
        return

    # Never use a hard-coded/default admin password.
    if not admin_name or not admin_email or not admin_password:
        # Use logger instead of print to avoid stdout exposure
        current_app.logger.warning(
            "Admin was not created. Please set ADMIN_NAME, ADMIN_EMAIL and ADMIN_PASSWORD in the .env file."
        )
        return

    admin_name = admin_name.strip()
    admin_email = admin_email.strip().lower()
    logger = current_app.logger if has_app_context() else logging.getLogger(__name__)

    try:
        existing_admin = mongo.db.users.find_one({
            "email": admin_email
        })

        if existing_admin:
            return

        hashed_password = generate_password_hash(admin_password)
        admin_data = {
            "name": admin_name,
            "email": admin_email,
            "username": admin_email,
            "password_hash": hashed_password,
            "role": "admin",
            "department": "Management",
            "status": "approved",
            "updated_at": datetime.now(timezone.utc),
        }

        admin_data["created_at"] = datetime.now(timezone.utc)
        mongo.db.users.insert_one(admin_data)

        logger.info("Initial admin account created successfully.")

    except Exception as exc:
        logger.error("Could not create initial admin (error type: %s).", type(exc).__name__)


def _ensure_dataset_indexes(collection, logger):
    """Create dataset indexes without modifying or deleting existing records."""
    collection.create_index([("dataset_type", 1), ("uploaded_at", -1)])
    try:
        collection.create_index(
            [("source_hash", 1), ("dataset_type", 1)],
            unique=True,
            name="unique_dataset_source_type",
            partialFilterExpression={"source_hash": {"$type": "string"}},
        )
    except Exception:
        # Existing duplicate hashes can prevent this optional optimization.
        # Keep startup working and do not include database details in logs.
        logger.warning("Could not create the optional dataset source uniqueness index.")


def _log_exception_safely(app, exc_info):
    """Log useful exception locations without exception text or local values."""
    exception_type = exc_info[0]
    frames = traceback.extract_tb(exc_info[2]) if exc_info[2] else []
    locations = " > ".join(
        f"{os.path.basename(frame.filename)}:{frame.lineno}:{frame.name}"
        for frame in frames[-8:]
    )
    app.logger.error(
        "Unhandled request exception (type=%s; frames=%s).",
        getattr(exception_type, "__name__", "Exception"),
        locations or "unavailable",
    )

# ==================================================
# CREATE APP
# ==================================================
def create_app(config_class=Config):
    app = Flask(__name__)

    app.config.from_object(
        config_class
    )
    # Flask's default exception logger includes exception messages, which can
    # contain credentials or user supplied data. Keep stack locations only.
    app.log_exception = lambda exc_info: _log_exception_safely(app, exc_info)
    if app.config.get("PROXY_FIX_X_FOR") or app.config.get("PROXY_FIX_X_PROTO"):
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=app.config.get("PROXY_FIX_X_FOR", 0),
            x_proto=app.config.get("PROXY_FIX_X_PROTO", 0),
            x_host=0,
            x_port=0,
            x_prefix=0,
        )

    @app.context_processor
    def global_template_values():
        return {
            "max_upload_mb": round(app.config["MAX_CONTENT_LENGTH"] / (1024 * 1024), 1),
            "allowed_dataset_extensions": sorted(app.config["ALLOWED_DATASET_EXTENSIONS"]),
            "valid_dataset_types": sorted(app.config["VALID_DATASET_TYPES"]),
            "hdfs_enabled": app.config.get("HADOOP_ENABLED", False),
            "csp_nonce": getattr(g, "csp_nonce", ""),
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
        g.csp_nonce = secrets.token_urlsafe(18)
        # Health probes must remain cheap and must not initialize/migrate data.
        if request.path in {"/health", "/health/ready", "/monitoring/health"}:
            return
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
            _ensure_dataset_indexes(mongo.db.datasets, app.logger)

            mongo.db.rejected_records.create_index([("dataset_id", 1), ("created_at", -1)])
            mongo.db.predictions.create_index([("student_id", 1), ("model_type", 1), ("created_at", -1)])
            mongo.db.attendance.create_index([("student_id", 1), ("date", -1)])
            mongo.db.grades.create_index([("student_id", 1), ("created_at", -1)])
            mongo.db.assignments.create_index([("student_id", 1), ("status", 1), ("due_date", 1)])
            mongo.db.assignments.create_index([("student_id", 1), ("assignment_key", 1)], unique=True, sparse=True)
            mongo.db.submissions.create_index([("student_id", 1), ("assignment_id", 1)], unique=True)
            mongo.db.enrollments.create_index([("student_id", 1), ("status", 1)])
            mongo.db.enrollments.create_index([("course_id", 1), ("status", 1)])
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

        except Exception:
            app.logger.warning(
                "Database initialization failed; details suppressed to protect connection information."
            )

            # Keep this False so the application can
            # retry when MongoDB becomes available.
            app.extensions[
                "edupredict_indexes_ready"
            ] = False

    @app.after_request
    def record_request_metrics(response):
        started = getattr(g, "request_started_at", None)
        if started is not None and request.path not in {"/health", "/health/ready", "/monitoring/health"}:
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
        # Add security headers
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        # Inline scripts/styles use per-response nonces; third-party assets are self-hosted.
        response.headers['Content-Security-Policy'] = (
            f"default-src 'self'; script-src 'self' 'nonce-{getattr(g, 'csp_nonce', '')}'; "
            f"style-src 'self' 'nonce-{getattr(g, 'csp_nonce', '')}'; style-src-attr 'none'; "
            "font-src 'self'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'self'; frame-ancestors 'self'; form-action 'self'"
        )
        # HTTP Strict Transport Security (HSTS) for HTTPS only
        if request.is_secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'
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

    # Stable container/orchestrator endpoints outside the monitoring blueprint.
    from routes.monitoring_routes import liveness as health_liveness, readiness as health_readiness
    app.add_url_rule("/health", endpoint="health_liveness", view_func=health_liveness, methods=["GET"])
    app.add_url_rule("/health/ready", endpoint="health_readiness", view_func=health_readiness, methods=["GET"])

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

    @app.route("/login", methods=["GET", "POST"])
    def login_redirect():
        return redirect(
            url_for("auth.login"),
            code=307 if request.method == "POST" else 302,
        )

    return app

# ==================================================
# APPLICATION
# ==================================================
app = create_app()

if __name__ == "__main__":
    app.run(
        debug=app.config.get("DEBUG", False),
        host="0.0.0.0",
        port=5000
    )
