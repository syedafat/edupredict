from flask import Blueprint, jsonify, current_app, session
from services.hadoop_service import HadoopService

from models import mongo
from utils.decorators import role_required


monitoring_bp = Blueprint("monitoring", __name__, url_prefix="/monitoring")


@monitoring_bp.route("/health", endpoint="liveness")
def liveness():
    """Cheap process check; intentionally independent of external services."""
    return jsonify({"status": "ok"}), 200


@monitoring_bp.route("/health/ready", endpoint="readiness")
def readiness():
    """Check that the application can reach its required database dependency."""
    try:
        mongo.cx.admin.command("ping")
    except Exception:
        return jsonify({"status": "not_ready", "database": "unavailable"}), 503
    return jsonify({"status": "ready", "database": "ok"}), 200


@monitoring_bp.route("/health")
def health():
    database = {"status": "unavailable"}
    try:
        mongo.cx.admin.command("ping")
        database = {"status": "ok"}
    except Exception:
        database = {"status": "unavailable"}
    try:
        hdfs = HadoopService.status()
    except Exception:
        hdfs = {"enabled": current_app.config.get("HADOOP_ENABLED", False), "reachable": False, "message": "HDFS status unavailable"}
    return jsonify({
        "status": "ok" if database["status"] == "ok" else "degraded",
        "database": database,
        "hdfs": hdfs,
    }), 200 if database["status"] == "ok" else 503


@monitoring_bp.route("/metrics")
@role_required("admin", "analyst")
def metrics():
    return jsonify({
        "status": "success",
        "request_metrics": {
            "total": mongo.db.system_logs.count_documents({"event_type": "request"}),
            "errors": mongo.db.system_logs.count_documents({"event_type": "request", "status_code": {"$gte": 400}}),
            "average_duration_ms": _average_duration(),
        },
        "collections": {
            "users": mongo.db.users.count_documents({}),
            "datasets": mongo.db.datasets.count_documents({}),
            "stream_events": mongo.db.stream_events.count_documents({}),
        },
    })


def _average_duration():
    rows = list(mongo.db.system_logs.find({"event_type": "request"}, {"duration_ms": 1}).sort("created_at", -1).limit(1000))
    values = [float(row["duration_ms"]) for row in rows if isinstance(row.get("duration_ms"), (int, float))]
    return round(sum(values) / len(values), 2) if values else 0
