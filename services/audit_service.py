from datetime import datetime, timezone

from flask import current_app, request

from models import mongo


class AuditService:
    """Persist security-relevant business actions without storing secrets."""

    @staticmethod
    def record(action, target_type, target_id=None, user_id=None, role=None, result="success", metadata=None):
        document = {
            "user_id": str(user_id) if user_id else None,
            "role": role,
            "action": str(action)[:120],
            "target_type": str(target_type)[:80],
            "target_id": str(target_id) if target_id is not None else None,
            "timestamp": datetime.now(timezone.utc),
            "result": str(result)[:40],
            "ip_address": request.headers.get("X-Forwarded-For", request.remote_addr) if request else None,
            "metadata": metadata or {},
        }
        try:
            mongo.db.audit_logs.insert_one(document)
            return document
        except Exception as exc:
            current_app.logger.warning("Audit event could not be persisted: %s", exc)
            return None
