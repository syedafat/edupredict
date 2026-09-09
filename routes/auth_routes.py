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
        identifier = request.form.get(
            "email",
            request.form.get("username", "")
        ).strip()
        email = identifier.lower()

        password = request.form.get(
            "password",
            ""
        )

        if not email or not password:
            flash(
                "Please enter both email and password.",
                "danger"
            )
            return render_template(
                "auth/login.html"
            )

        user = mongo.db.users.find_one({
            "$or": [
                {"email": email},
                {"username": identifier},
                {"username": email},
            ]
        })

        if not user:
            flash(
                "Invalid email or password.",
                "danger"
            )
            return render_template(
                "auth/login.html"
            )

        # Supports both:
        # password      -> normal registered users
        # password_hash  -> admin seeded from .env
        legacy_password = user.get("password")
        stored_password = user.get("password_hash") or legacy_password or ""

        if (
            not stored_password
            or not check_password_hash(
                stored_password,
                password
            )
        ):
            flash(
                "Invalid email or password.",
                "danger"
            )
            return render_template(
                "auth/login.html"
            )
        if legacy_password and not user.get("password_hash"):
            mongo.db.users.update_one(
                {"_id": user["_id"]},
                {"$set": {"password_hash": legacy_password}, "$unset": {"password": ""}},
            )

        role = user.get(
            "role",
            "student"
        )

        if role not in VALID_ROLES:
            session.clear()
            flash(
                "Invalid account role. Please contact the administrator.",
                "danger"
            )
            return redirect(
                url_for("auth.login")
            )

        # ==================================================
        # TEACHER APPROVAL CHECK
        # ==================================================

        if role == "teacher":
            teacher_status = user.get(
                "status",
                "pending"
            )

            if teacher_status == "pending":
                flash(
                    "Your teacher account is waiting for admin approval.",
                    "warning"
                )
                return redirect(
                    url_for("auth.login")
                )

            if teacher_status == "rejected":
                flash(
                    "Your teacher registration has been rejected by the administrator.",
                    "danger"
                )
                return redirect(
                    url_for("auth.login")
                )

            if teacher_status != "approved":
                flash(
                    "Your teacher account is currently unavailable.",
                    "danger"
                )
                return redirect(
                    url_for("auth.login")
                )

        # ==================================================
        # ACCOUNT STATUS CHECK
        # ==================================================

        if user.get("status") in {
            "suspended",
            "deleted"
        }:
            flash(
                "This account is currently unavailable.",
                "danger"
            )
            return render_template(
                "auth/login.html"
            )

        dashboard_endpoint = get_dashboard_endpoint(
            role
        )

        if not dashboard_endpoint:
            session.clear()
            flash(
                "Unable to determine user dashboard.",
                "danger"
            )
            return redirect(
                url_for("auth.login")
            )

        # Clear old session
        session.clear()

        session["user_id"] = str(
            user["_id"]
        )
        session["role"] = role
        session["user_name"] = user.get(
            "name",
            "User"
        )

        remember = (
            request.form.get("remember")
            == "true"
        )
        session.permanent = remember

        flash(
            "Logged in successfully.",
            "success"
        )

        return redirect(
            url_for(dashboard_endpoint)
        )

    return render_template(
        "auth/login.html"
    )

# ==================================================
# STUDENT REGISTER
# ==================================================

@auth_bp.route(
    "/register",
    methods=["GET", "POST"]
)
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
            "password": hashed_password,
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
                "Email already registered. Please log in.",
                "warning"
            )
            return redirect(
                url_for("auth.login")
            )

        flash(
            "Student account created successfully. Please log in.",
            "success"
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
            "password": hashed_password,
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
                "Email already registered.",
                "warning"
            )
            return redirect(
                url_for("auth.login")
            )

        flash(
            "Teacher registration submitted successfully. "
            "Please wait for admin approval.",
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
                    "password": new_password_hash,
                    "password_changed_at": now
                },
                "$unset": {
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

@auth_bp.route("/logout")
def logout():
    session.clear()

    flash(
        "You have been logged out.",
        "info"
    )

    return redirect(
        url_for("auth.login")
    )