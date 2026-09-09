from functools import wraps
from flask import session, flash, redirect, url_for, abort, current_app
from bson.objectid import ObjectId
from models import mongo

def role_required(*allowed_roles):
    """
    Decorator to restrict route access based on user roles.
    Includes session validation, deleted user handling, and role enforcement.
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # 1. Session Validation: Check if user is logged in
            if 'user_id' not in session or 'role' not in session:
                flash('Please log in to access this secure resource.', 'warning')
                return redirect(url_for('auth.login'))
            
            # 2. Role Authorization Check
            if session['role'] not in allowed_roles:
                abort(403)
            
            # 3. Deleted User / Account State Handling (MongoDB Integration)
            user_id = session.get('user_id')
            try:
                object_id = ObjectId(user_id)
                user = mongo.db.users.find_one({'_id': object_id})
            except Exception:
                user = None
            if not user or user.get('status') in {'suspended', 'deleted'}:
                session.clear()
                flash('Your account has been deactivated or no longer exists.', 'error')
                return redirect(url_for('auth.login'))
            if user.get("role") != session.get("role"):
                session.clear()
                flash("Your account permissions changed. Please log in again.", "warning")
                return redirect(url_for("auth.login"))
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator