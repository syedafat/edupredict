from flask import Blueprint, render_template, request, flash, redirect, url_for, session, abort
from utils.decorators import role_required
from models import mongo
from bson import ObjectId
from datetime import datetime, timezone

support_bp = Blueprint('support', __name__, url_prefix='/support')

@support_bp.route('/tickets', methods=['GET'])
@role_required('admin', 'teacher', 'student', 'analyst')
def list_tickets():
    query = {}
    if session.get('role') == 'student':
        query['created_by'] = session.get('user_id')
    try:
        tickets = list(mongo.db.support_tickets.find(query).sort('created_at', -1).limit(100))
    except Exception:
        tickets = []
    return render_template('support/tickets.html', tickets=tickets)

@support_bp.route('/ticket/<ticket_id>', methods=['GET'])
@role_required('admin', 'teacher', 'student', 'analyst')
def ticket_detail(ticket_id):
    try:
        ticket = mongo.db.support_tickets.find_one({'_id': ObjectId(ticket_id)})
    except Exception:
        abort(404)
    if not ticket or (
        session.get('role') == 'student'
        and ticket.get('created_by') != session.get('user_id')
    ):
        abort(404)
    return render_template('support/ticket_detail.html', ticket=ticket, ticket_id=ticket_id)

@support_bp.route('/create', methods=['GET', 'POST'])
@role_required('admin', 'teacher', 'student', 'analyst')
def create_ticket():
    if request.method == 'POST':
        subject = request.form.get('subject', '').strip()
        message = request.form.get('message', '').strip()
        if not subject or not message:
            flash('Subject and message are required.', 'danger')
            return render_template('support/create_ticket.html')
        mongo.db.support_tickets.insert_one({
            'subject': subject[:200],
            'message': message[:10000],
            'status': 'open',
            'created_by': session.get('user_id'),
            'created_at': datetime.now(timezone.utc),
        })
        flash('Support ticket created successfully.', 'success')
        return redirect(url_for('support.list_tickets'))
    return render_template('support/create_ticket.html')


@support_bp.route('/ticket/<ticket_id>/respond', methods=['POST'])
@role_required('admin', 'teacher', 'analyst')
def respond_ticket(ticket_id):
    try:
        object_id = ObjectId(ticket_id)
    except Exception:
        abort(404)
    message = request.form.get('message', '').strip()
    status = request.form.get('status', 'open').strip().lower()
    if not message and status not in {'open', 'in_progress', 'resolved', 'closed'}:
        flash('A response or valid status is required.', 'danger')
        return redirect(url_for('support.ticket_detail', ticket_id=ticket_id))
    update = {'updated_at': datetime.now(timezone.utc), 'updated_by': session.get('user_id')}
    if status in {'open', 'in_progress', 'resolved', 'closed'}:
        update['status'] = status
    if message:
        update['$push'] = {'responses': {
            'message': message[:10000],
            'author_id': session.get('user_id'),
            'created_at': datetime.now(timezone.utc),
        }}
    set_data = {key: value for key, value in update.items() if key != '$push'}
    mongo.db.support_tickets.update_one({'_id': object_id}, {'$set': set_data, **({'$push': update['$push']} if '$push' in update else {})})
    flash('Ticket updated successfully.', 'success')
    return redirect(url_for('support.ticket_detail', ticket_id=ticket_id))