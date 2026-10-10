from flask import Blueprint, render_template, request, flash, redirect, url_for, jsonify, session
from utils.decorators import role_required
from models import mongo
from bson import ObjectId
from datetime import datetime, timezone
from extensions import limiter

notification_bp = Blueprint('notifications', __name__, url_prefix='/notifications')

@notification_bp.route('/', methods=['GET'])
@role_required('admin', 'teacher', 'student', 'analyst')
def list_notifications():
    """View all system alerts and notifications"""
    try:
        notifications = list(
            mongo.db.notifications.find(
                {'user_id': session.get('user_id')}
            ).sort('created_at', -1).limit(100)
        )
    except Exception:
        notifications = []
    return render_template(
        'notifications/notifications.html',
        notifications=notifications
    )

@notification_bp.route('/mark-read/<notification_id>', methods=['POST'])
@role_required('admin', 'teacher', 'student', 'analyst')
def mark_read(notification_id):
    """Mark a specific notification as read"""
    try:
        object_id = ObjectId(notification_id)
    except Exception:
        return jsonify({'status': 'error', 'message': 'Invalid notification id.'}), 400

    result = mongo.db.notifications.update_one(
        {'_id': object_id, 'user_id': session.get('user_id')},
        {'$set': {'is_read': True, 'read_at': datetime.now(timezone.utc)}}
    )
    if result.matched_count == 0:
        return jsonify({'status': 'error', 'message': 'Notification not found.'}), 404
    return jsonify({'status': 'success', 'message': 'Notification marked as read.'})

@notification_bp.route('/broadcast', methods=['GET', 'POST'])
@limiter.limit("10 per hour", methods=["POST"])
@role_required('admin', 'teacher')
def broadcast():
    """Broadcast an institutional notice to users"""
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        message = request.form.get('message', '').strip()
        audience = request.form.get('audience', 'all').strip().lower()
        if not title or not message or len(title) > 150:
            flash('A title and message are required.', 'danger')
            return render_template('notifications/broadcast.html')
        if audience not in {'all', 'student', 'teacher', 'admin', 'analyst'}:
            flash('Invalid audience selected.', 'danger')
            return render_template('notifications/broadcast.html')
        if session.get('role') == 'teacher' and audience != 'student':
            flash('Teachers may only notify students in their assigned courses.', 'danger')
            return render_template('notifications/broadcast.html')

        role_filter = {'student': 'student', 'teacher': 'teacher', 'admin': 'admin', 'analyst': 'analyst'}.get(audience)
        if session.get('role') == 'teacher':
            from routes.teacher_routes import _teacher_student_ids, _teacher_courses
            assigned_ids = _teacher_student_ids(_teacher_courses())
            users = mongo.db.users.find({'role': 'student', '_id': {'$in': [ObjectId(value) for value in assigned_ids if ObjectId.is_valid(value)]}}, {'_id': 1})
        else:
            users = mongo.db.users.find({'role': role_filter} if role_filter else {}, {'_id': 1})
        created_at = datetime.now(timezone.utc)
        notifications = [
            {
                'user_id': str(user['_id']),
                'title': title,
                'message': message,
                'type': 'info',
                'is_read': False,
                'created_at': created_at,
                'created_by': session.get('user_id'),
            }
            for user in users
        ]
        if notifications:
            mongo.db.notifications.insert_many(notifications)
        flash('Broadcast notification sent successfully.', 'success')
        return redirect(url_for('notifications.list_notifications'))
    return render_template('notifications/broadcast.html')
