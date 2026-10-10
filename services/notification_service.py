from models import mongo
from datetime import datetime, timezone
from flask import current_app

class NotificationService:
    @staticmethod
    def create_notification(user_id, title, message, alert_type='info', dedupe_key=None):
        try:
            notification = {
                'user_id': user_id,
                'title': title,
                'message': message,
                'type': alert_type, # info, warning, danger
                'is_read': False,
                'created_at': datetime.now(timezone.utc)
            }
            if dedupe_key:
                notification["dedupe_key"] = dedupe_key
            mongo.db.notifications.insert_one(notification)
            return True
        except Exception as e:
            current_app.logger.error("Notification could not be saved (error type: %s).", type(e).__name__)
            return False
