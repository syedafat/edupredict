# auth_routes.py

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    current_app
)

from models import mongo
from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from pymongo.errors import DuplicateKeyError
from extensions import limiter
from services.email_service import EmailService

from datetime import (
    datetime,
    timedelta,
    timezone
)

import hashlib
import secrets
import re

auth_bp = Blueprint("auth", __name__)

# ==================================================
# CONFIGURATION
# ==================================================

PASSWORD_MIN_LENGTH = 8
RESET_TOKEN_EXPIRY_MINUTES = 30

VALID_ROLES = {
    "admin",
    "teacher",
    "student",
    "analyst",
}

STUDENT_REGISTRATION_ACK = (
    "If an account can be created for this address, registration was received. "
    "If you already have an account, please sign in."
)
TEACHER_REGISTRATION_ACK = (
    "If a teacher account can be created for this address, registration was received. "
    "Teacher accounts require administrator approval. If you already have an account, please sign in."
)

# ==================================================
# HELPER FUNCTIONS
# ==================================================

def is_valid_email(email):
    """Validate email format."""
    pattern = r"^[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}$"
    return re.fullmatch(pattern, email) is not None

def is_strong_password(password):
    """
    Password requirements:
    - Minimum 8 characters
    - At least one uppercase letter
    - At least one lowercase letter
    - At least one number
    """
    if len(password) < PASSWORD_MIN_LENGTH:
        return False

    if not re.search(r"[A-Z]", password):
        return False

    if not re.search(r"[a-z]", password):
        return False

    if not re.search(r"\d", password):
        return False

    return True

def hash_reset_token(token):
    """Create SHA-256 hash of reset token."""
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()

def get_dashboard_endpoint(role):
    """Return dashboard endpoint based on role."""
    routes = {
        "admin": "admin.dashboard",
        "teacher": "teacher.dashboard",
        "student": "student.dashboard",
        "analyst": "analyst.dashboard",
    }
    return routes.get(role)

# ==================================================
# LOGIN
# ==================================================

@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")
def login():
    if request.method == "POST":
        raw_identifier = request.form.get("email", request.form.get("username", "")) or ""
        identifier = raw_identifier.strip()
        email = identifier.lower()
        password = request.form.get("password", "")

        if not email or not password:
            flash("Please enter both email and password.", "danger")
            return render_template("auth/login.html")

        # Database lookup by email or username
        user = mongo.db.users.find_one({
            "$or": [
                {"email": email},
                {"email": identifier},
                {"username": identifier},
                {"username": email},
            ]
        })

        if not user:
            flash("Invalid email or password.", "danger")
            return render_template("auth/login.html")

        user_id_str = str(user.get("_id"))
        raw_role = str(user.get("role", "student")).strip().lower()
        user_status = str(user.get("status", "approved")).strip().lower()
        # Secure authentication: verify password hash only
        stored_password_hash = user.get("password_hash")
        password_matches = False
        if stored_password_hash:
            try:
                password_matches = check_password_hash(stored_password_hash, password)
            except Exception:
                password_matches = False
        # Legacy plaintext passwords are not accepted; authentication relies solely on hash verification.

        if not password_matches:
            flash("Invalid email or password.", "danger")
            return render_template("auth/login.html")

        # Normalize role
        role = raw_role if raw_role in VALID_ROLES else "student"
        if raw_role not in VALID_ROLES:
            current_app.logger.debug(f"Invalid account role. Valid roles: {VALID_ROLES}")
            session.clear()
            flash("Invalid account role. Please contact the administrator.", "danger")
            return redirect(url_for("auth.login"))

        # Teacher approval check
        if role == "teacher":
            current_app.logger.debug("Evaluating teacher status.")
            if user_status == "pending":
                current_app.logger.warning("Teacher login blocked: pending approval.")
                flash("Your teacher account is waiting for admin approval.", "warning")
                return redirect(url_for("auth.login"))

            if user_status == "rejected":
                current_app.logger.warning("Teacher login blocked: rejected status.")
                flash("Your teacher registration has been rejected by the administrator.", "danger")
                return redirect(url_for("auth.login"))

            if user_status not in {"approved", "active"}:
                current_app.logger.warning(f"Teacher login blocked: status {user_status} unavailable.")
                flash("Your teacher account is currently unavailable.", "danger")
                return redirect(url_for("auth.login"))

        # Account status check (suspended or deleted)
        if user_status in {"suspended", "deleted"}:
            current_app.logger.warning(f"Account deactivated: status {user_status}")
            flash("This account is currently unavailable.", "danger")
            return render_template("auth/login.html")

        dashboard_endpoint = get_dashboard_endpoint(role)
        if not dashboard_endpoint:
            current_app.logger.warning(f"Could not determine dashboard endpoint for role {role}")
            session.clear()
            flash("Unable to determine user dashboard.", "danger")
            return redirect(url_for("auth.login"))

        # Setup user session
        session.clear()
        session["user_id"] = user_id_str
        session["role"] = role
        session["user_name"] = user.get("name", "User")
        session["logged_in"] = True

        remember = request.form.get("remember") == "true"
        session.permanent = remember

        current_app.logger.debug("Session initialized and redirecting to dashboard.")

        flash("Logged in successfully.", "success")
        return redirect(url_for(dashboard_endpoint))

    return render_template("auth/login.html")

# ==================================================
# STUDENT REGISTER
# ==================================================

@auth_bp.route(
    "/register",
    methods=["GET", "POST"]
)
@limiter.limit("10 per hour", methods=["POST"])
def register():
    if request.method == "POST":
        name = request.form.get(
            "name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        department = request.form.get(
            "department",
            "general"
        ).strip()

        # Public registration creates STUDENT only
        role = "student"

        if not name or not email or not password:
            flash(
                "Name, email and password are required.",
                "danger"
            )
            return render_template(
                "auth/register.html"
            )

        if password != confirm_password:
            flash(
                "Passwords do not match.",
                "danger"
            )
            return render_template(
                "auth/register.html"
            )

        if len(name) > 100:
            flash(
                "Name is too long.",
                "danger"
            )
            return render_template(
                "auth/register.html"
            )

        if not is_valid_email(email):
            flash(
                "Please enter a valid email address.",
                "danger"
            )
            return render_template(
                "auth/register.html"
            )

        if not is_strong_password(password):
            flash(
                "Password must contain at least 8 characters, "
                "one uppercase letter, one lowercase letter "
                "and one number.",
                "danger"
            )
            return render_template(
                "auth/register.html"
            )

        hashed_password = generate_password_hash(
            password
        )

        user_data = {
            "name": name,
            "email": email,
            "password_hash": hashed_password,
            "role": role,
            "department": department,
            "status": "approved",
            "created_at": datetime.now(
                timezone.utc
            )
        }

        try:
            mongo.db.users.insert_one(
                user_data
            )
        except DuplicateKeyError:
            flash(
                STUDENT_REGISTRATION_ACK,
                "info"
            )
            return redirect(
                url_for("auth.login")
            )

        flash(
            STUDENT_REGISTRATION_ACK,
            "info"
        )

        return redirect(
            url_for("auth.login")
        )

    return render_template(
        "auth/register.html"
    )

# ==================================================
# TEACHER REGISTER
# ==================================================

@auth_bp.route(
    "/teacher/register",
    methods=["GET", "POST"]
)
@limiter.limit("10 per hour", methods=["POST"])
def teacher_register():
    if request.method == "POST":
        name = request.form.get(
            "name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        department = request.form.get(
            "department",
            "general"
        ).strip()

        if not name or not email or not password:
            flash(
                "Name, email and password are required.",
                "danger"
            )
            return render_template(
                "auth/teacher_register.html"
            )

        if password != confirm_password:
            flash(
                "Passwords do not match.",
                "danger"
            )
            return render_template(
                "auth/teacher_register.html"
            )

        if len(name) > 100:
            flash(
                "Name is too long.",
                "danger"
            )
            return render_template(
                "auth/teacher_register.html"
            )

        if not is_valid_email(email):
            flash(
                "Please enter a valid email address.",
                "danger"
            )
            return render_template(
                "auth/teacher_register.html"
            )

        if not is_strong_password(password):
            flash(
                "Password must contain at least 8 characters, "
                "one uppercase letter, one lowercase letter "
                "and one number.",
                "danger"
            )
            return render_template(
                "auth/teacher_register.html"
            )

        hashed_password = generate_password_hash(
            password
        )

        teacher_data = {
            "name": name,
            "email": email,
            "password_hash": hashed_password,
            "role": "teacher",
            "department": department,
            # IMPORTANT:
            # Teacher cannot access dashboard yet
            "status": "pending",
            "created_at": datetime.now(
                timezone.utc
            )
        }

        try:
            mongo.db.users.insert_one(
                teacher_data
            )
        except DuplicateKeyError:
            flash(
                TEACHER_REGISTRATION_ACK,
                "info"
            )
            return redirect(
                url_for("auth.login")
            )

        flash(
            TEACHER_REGISTRATION_ACK,
            "info"
        )

        return redirect(
            url_for("auth.login")
        )

    return render_template(
        "auth/teacher_register.html"
    )

# ==================================================
# FORGOT PASSWORD
# ==================================================

@auth_bp.route(
    "/forgot-password",
    methods=["GET", "POST"]
)
@limiter.limit("5 per minute")
def forgot_password():
    if request.method == "POST":
        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        generic_message = (
            "If an account exists with this email address, "
            "password reset instructions have been sent."
        )

        if is_valid_email(email):
            user = mongo.db.users.find_one({
                "email": email
            })

            if user:
                reset_token = secrets.token_urlsafe(
                    32
                )
                token_hash = hash_reset_token(
                    reset_token
                )

                expiry = (
                    datetime.now(
                        timezone.utc
                    )
                    +
                    timedelta(
                        minutes=RESET_TOKEN_EXPIRY_MINUTES
                    )
                )

                try:
                    mongo.db.users.update_one(
                        {
                            "_id": user["_id"]
                        },
                        {
                            "$set": {
                                "reset_token_hash": token_hash,
                                "reset_token_expiry": expiry
                            }
                        }
                    )
                    if current_app.config.get("PASSWORD_RESET_EXPOSE_LINK", False):
                        reset_url = url_for("auth.reset_password", token=reset_token, _external=True)
                        flash(f"Development reset link: {reset_url}", "warning")
                    else:
                        reset_base_url = current_app.config.get("PASSWORD_RESET_BASE_URL", "").rstrip("/")
                        reset_path = url_for("auth.reset_password", token=reset_token)
                        reset_url = f"{reset_base_url}{reset_path}" if reset_base_url else url_for(
                            "auth.reset_password", token=reset_token, _external=True
                        )
                        EmailService.send_password_reset(email, reset_url)
                except Exception:
                    try:
                        mongo.db.users.update_one(
                            {"_id": user["_id"], "reset_token_hash": token_hash},
                            {"$unset": {"reset_token_hash": "", "reset_token_expiry": ""}},
                        )
                    except Exception:
                        pass
                    current_app.logger.warning("Password reset delivery failed; no reset token was returned.")

        flash(
            generic_message,
            "info"
        )

        return redirect(
            url_for("auth.login")
        )

    return render_template(
        "auth/forgot_password.html"
    )

# ==================================================
# RESET PASSWORD
# ==================================================

@auth_bp.route(
    "/reset-password",
    methods=["GET", "POST"]
)
@limiter.limit("10 per hour", methods=["POST"])
def reset_password():
    token = request.args.get(
        "token",
        ""
    ).strip()

    if not token:
        flash(
            "Invalid or missing password reset token.",
            "danger"
        )
        return redirect(
            url_for("auth.forgot_password")
        )

    if request.method == "POST":
        new_password = request.form.get(
            "password",
            ""
        )
        confirm_password = request.form.get(
            "confirm_password",
            ""
        )

        if new_password != confirm_password:
            flash(
                "Passwords do not match.",
                "danger"
            )
            return render_template(
                "auth/reset_password.html",
                token=token
            )

        if not is_strong_password(
            new_password
        ):
            flash(
                "Password must contain at least 8 characters, "
                "one uppercase letter, one lowercase letter "
                "and one number.",
                "danger"
            )
            return render_template(
                "auth/reset_password.html",
                token=token
            )

        token_hash = hash_reset_token(
            token
        )
        now = datetime.now(
            timezone.utc
        )

        user = mongo.db.users.find_one({
            "reset_token_hash": token_hash,
            "reset_token_expiry": {
                "$gt": now
            }
        })

        if not user:
            flash(
                "This password reset link is invalid or has expired.",
                "danger"
            )
            return redirect(
                url_for("auth.forgot_password")
            )

        new_password_hash = generate_password_hash(
            new_password
        )

        mongo.db.users.update_one(
            {
                "_id": user["_id"]
            },
            {
                "$set": {
                    "password_hash": new_password_hash,
                    "password_changed_at": now
                },
                "$unset": {
                    "password": "",
                    "reset_token_hash": "",
                    "reset_token_expiry": ""
                }
            }
        )

        session.clear()

        flash(
            "Password has been reset successfully. "
            "Please log in with your new password.",
            "success"
        )

        return redirect(
            url_for("auth.login")
        )

    return render_template(
        "auth/reset_password.html",
        token=token
    )

# ==================================================
# LOGOUT
# ==================================================

@auth_bp.route("/logout", methods=["POST"])
def logout():
    session.clear()

    flash(
        "You have been logged out.",
        "info"
    )

    return redirect(
        url_for("auth.login")
    )
