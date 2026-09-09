from flask import Blueprint, render_template, jsonify, current_app, request, session
from datetime import datetime, timezone
import os
from uuid import uuid4
from bson import ObjectId
from models import mongo
from utils.decorators import role_required
from ml.model_manager import ModelManager, SUPPORTED_MODEL_TYPES
from services.alert_service import AlertService
from services.academic_data_service import AcademicDataService
from services.audit_service import AuditService

ml_bp = Blueprint('ml', __name__, url_prefix='/ml')

# Keep this in sync with ModelManager.SUPPORTED_MODEL_TYPES
VALID_MODEL_TYPES = SUPPORTED_MODEL_TYPES


@ml_bp.route('/predictions', methods=['GET'])
@role_required('admin', 'teacher', 'student')
def view_predictions():
    query = {}
    if session.get('role') == 'student':
        query['student_id'] = session.get('user_id')
    elif session.get('role') == 'teacher':
        course_ids = [str(course['_id']) for course in mongo.db.courses.find({
            'teacher_id': str(session.get('user_id')),
            'status': {'$ne': 'inactive'},
        }, {'_id': 1})]
        assigned_students = AcademicDataService.student_ids_for_courses(course_ids)
        query['student_id'] = {'$in': list(assigned_students)}
    predictions = list(mongo.db.predictions.find(query).sort('created_at', -1).limit(200))
    return render_template('admin/predictions.html', predictions=predictions)


@ml_bp.route('/run-model/<model_type>', methods=['POST'])
@role_required('admin', 'analyst')
def run_model(model_type):
    """
    Train and persist a model from a JSON body containing X/y (or data for
    anomaly detection).
    """
    if model_type not in VALID_MODEL_TYPES:
        return jsonify({
            'status': 'error',
            'message': (
                f"Unknown model type: '{model_type}'. "
                f"Valid types: {sorted(VALID_MODEL_TYPES)}"
            )
        }), 400

    payload = request.get_json(silent=True) or {}
    X = payload.get('X', payload.get('data'))
    y = payload.get('y')
    if not isinstance(X, list) or not X:
        return jsonify({
            'status': 'error',
            'message': 'JSON body must include a non-empty X (or data) matrix.'
        }), 400

    try:
        model = ModelManager.get_model(model_type)
        if model_type == 'anomaly':
            metrics = model.train(X)
        else:
            if not isinstance(y, list):
                return jsonify({
                    'status': 'error',
                    'message': 'JSON body must include y for this model type.'
                }), 400
            metrics = model.train(X, y)
        if not ModelManager.save_model(model_type, model):
            raise RuntimeError('The trained model could not be saved.')
    except (TypeError, ValueError, RuntimeError) as exc:
        return jsonify({'status': 'error', 'message': str(exc)}), 400

    model_version = f"{model_type}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
    artifact_path = os.path.abspath(os.path.join(current_app.config.get("MODEL_FOLDER", "models"), f"{model_type}.joblib"))
    mongo.db.model_training.insert_one({
        "model_type": model_type,
        "model_version": model_version,
        "algorithm": type(model.model).__name__,
        "artifact_path": artifact_path,
        "artifact_hash": ModelManager.artifact_hash(model_type),
        "status": "active",
        "feature_set": payload.get("feature_names"),
        "feature_schema_version": payload.get("feature_schema_version", AcademicDataService.FEATURE_SCHEMA_VERSION),
        "metrics": metrics,
        "samples": len(X),
        "trained_by": session.get("user_id"),
        "trained_at": datetime.now(timezone.utc),
    })
    AuditService.record("model_trained", "model", model_version, session.get("user_id"), session.get("role"), metadata={"model_type": model_type, "metrics": metrics})
    return jsonify({
        'status': 'success',
        'message': f"Model '{model_type}' trained successfully.",
        'metrics': metrics
    })


@ml_bp.route('/model-status', methods=['GET'])
@role_required('admin')
def model_status():
    """Return persistence status of all supported models."""
    status = {}
    for mt in sorted(VALID_MODEL_TYPES):
        status[mt] = 'available' if ModelManager.model_exists(mt) else 'not_trained'
    return jsonify({'status': 'success', 'models': status})


@ml_bp.route('/train-from-dataset/<dataset_id>/<model_type>', methods=['POST'])
@role_required('admin', 'analyst')
def train_from_dataset(dataset_id, model_type):
    if model_type not in VALID_MODEL_TYPES:
        return jsonify({"status": "error", "message": "Unsupported model type."}), 400
    from bson import ObjectId
    from services.processing_service import ProcessingService
    dataset = mongo.db.datasets.find_one({"_id": ObjectId(dataset_id)}) if ObjectId.is_valid(dataset_id) else None
    path = dataset.get("processed_path") if dataset else None
    if not path or not os.path.isfile(path):
        return jsonify({"status": "error", "message": "Dataset has no processed file available."}), 404
    payload = request.get_json(silent=True) or {}
    target = str(payload.get("target", "")).strip().lower()
    try:
        frame = ProcessingService.clean_dataframe(ProcessingService.load_dataframe(path))
        numeric = frame.select_dtypes(include=["number"])
        if model_type == "anomaly":
            X = numeric.values.tolist()
            y = None
        else:
            if target not in numeric.columns:
                return jsonify({"status": "error", "message": "target must name a numeric column in the dataset."}), 400
            X = numeric.drop(columns=[target]).values.tolist()
            y = numeric[target].values.tolist()
        model = ModelManager.get_model(model_type)
        metrics = model.train(X) if model_type == "anomaly" else model.train(X, y)
        if not ModelManager.save_model(model_type, model):
            raise RuntimeError("The trained model could not be saved.")
        if model_type == "anomaly" and "student_id" in frame.columns:
            for index, label in enumerate(model.model.predict(numeric.values)):
                if label == -1:
                    student_id = str(frame.iloc[index].get("student_id"))
                    mongo.db.anomalies.insert_one({
                        "student_id": student_id,
                        "type": "academic_anomaly",
                        "score": -1,
                        "dataset_id": dataset_id,
                        "created_at": datetime.now(timezone.utc),
                    })
                    mongo.db.notifications.update_one(
                        {"user_id": student_id, "dedupe_key": f"anomaly:{dataset_id}:{index}"},
                        {"$setOnInsert": {
                            "user_id": student_id, "title": "Academic anomaly detected",
                            "message": "An unusual academic record was detected and flagged for review.",
                            "type": "warning", "is_read": False,
                            "dedupe_key": f"anomaly:{dataset_id}:{index}",
                            "created_at": datetime.now(timezone.utc),
                        }},
                        upsert=True,
                    )
        model_version = f"{model_type}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid4().hex[:8]}"
        artifact_path = os.path.abspath(os.path.join(current_app.config.get("MODEL_FOLDER", "models"), f"{model_type}.joblib"))
        mongo.db.model_training.insert_one({
            "model_type": model_type, "model_version": model_version, "algorithm": type(model.model).__name__, "status": "active", "dataset_id": dataset_id, "target": target or None,
            "artifact_path": artifact_path, "artifact_hash": ModelManager.artifact_hash(model_type), "feature_schema_version": payload.get("feature_schema_version", AcademicDataService.FEATURE_SCHEMA_VERSION),
            "metrics": metrics, "trained_by": session.get("user_id"), "trained_at": datetime.now(timezone.utc),
        })
        AuditService.record("model_trained", "model", model_version, session.get("user_id"), session.get("role"), metadata={"model_type": model_type, "dataset_id": dataset_id, "metrics": metrics})
        return jsonify({"status": "success", "metrics": metrics, "dataset_id": dataset_id})
    except Exception as exc:
        current_app.logger.exception("Dataset model training failed: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 400


@ml_bp.route('/predict/<model_type>', methods=['POST'])
@role_required('admin', 'teacher', 'analyst')
def predict(model_type):
    """Load persisted model and run prediction on posted features."""
    if model_type not in VALID_MODEL_TYPES:
        return jsonify({
            'status': 'error',
            'message': f"Unknown model type: '{model_type}'."
        }), 400

    if not ModelManager.model_exists(model_type):
        return jsonify({
            'status': 'error',
            'message': f"Model '{model_type}' has not been trained yet."
        }), 404

    model = ModelManager.load_model(model_type)
    if model is None:
        current_app.logger.error("Failed to load model '%s' for prediction.", model_type)
        return jsonify({
            'status': 'error',
            'message': f"Model '{model_type}' could not be loaded. It may be corrupt."
        }), 500
    training = mongo.db.model_training.find_one({"model_type": model_type, "status": "active"}, sort=[("trained_at", -1)])
    if not training or not ModelManager.artifact_matches(model_type, training):
        return jsonify({'status': 'error', 'message': f"Model '{model_type}' has no verified active artifact."}), 409

    payload = request.get_json(silent=True) or {}
    features = payload.get('features')
    if not isinstance(features, list) or not features:
        return jsonify({
            'status': 'error',
            'message': 'JSON body must include a non-empty features list.'
        }), 400

    try:
        student_id = str(payload.get("student_id", "")).strip()
        if session.get("role") == "teacher":
            if not student_id:
                return jsonify({"status": "error", "message": "Teachers must specify an assigned student."}), 400
            if student_id not in AcademicDataService.teacher_student_ids(session.get("user_id")):
                return jsonify({"status": "error", "message": "You may only score students assigned to your courses."}), 403
        course_id = str(payload.get("course_id", "")).strip() or None
        if session.get("role") == "teacher" and course_id and not any(
            str(row.get("_id")) == course_id for row in mongo.db.courses.find({"teacher_id": str(session.get("user_id")), "status": {"$ne": "inactive"}}, {"_id": 1})
        ):
            return jsonify({"status": "error", "message": "You may only score students in your assigned courses."}), 403
        requested_feature_version = payload.get("feature_version")
        feature_doc = None
        if student_id:
            try:
                feature_doc = AcademicDataService.validate_feature_record(student_id, features, requested_feature_version, course_id=course_id)
            except ValueError as exc:
                return jsonify({"status": "error", "message": str(exc)}), 409
        if model_type == 'performance':
            prediction = model.predict(features)
        elif model_type == 'dropout':
            prediction = model.predict_risk(features)
        elif model_type == 'demand':
            prediction = model.predict_demand(features)
        elif model_type == 'trend':
            prediction = model.predict_trend(features)
        else:
            prediction = model.predict_single(features)
    except (TypeError, ValueError, RuntimeError) as exc:
        return jsonify({'status': 'error', 'message': str(exc)}), 400

    prediction_record = {
        "prediction_id": uuid4().hex,
        "model_type": model_type,
        "prediction": prediction,
        "student_id": student_id or None,
        "created_by": session.get("user_id"),
        "created_at": datetime.now(timezone.utc),
    }
    prediction_record["model_version"] = training.get("model_version") if training else "unversioned"
    prediction_record["feature_version"] = str(payload.get("feature_version") or "request-features")
    prediction_record["course_id"] = course_id
    prediction_record["feature_scope"] = feature_doc.get("feature_scope") if feature_doc else "request"
    if feature_doc and training.get("feature_schema_version", AcademicDataService.FEATURE_SCHEMA_VERSION) != feature_doc.get("feature_schema_version", AcademicDataService.FEATURE_SCHEMA_VERSION):
        return jsonify({'status': 'error', 'message': 'Model and feature schema versions are incompatible.'}), 409
    if model_type == "dropout":
        prediction_record["risk_score"] = float(prediction)
    mongo.db.predictions.insert_one(prediction_record)
    if student_id:
        AlertService.evaluate_student(student_id)
    AuditService.record("prediction_generated", "prediction", prediction_record["prediction_id"], session.get("user_id"), session.get("role"), metadata={"model_type": model_type, "student_id": student_id, "model_version": prediction_record["model_version"]})
    return jsonify({
        'status': 'success',
        'model_type': model_type,
        'prediction': prediction
    })


@ml_bp.route('/correlation', methods=['POST'])
@role_required('admin', 'analyst')
def correlation():
    payload = request.get_json(silent=True) or {}
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        return jsonify({"status": "error", "message": "rows must be a non-empty list of objects."}), 400
    from services.processing_service import ProcessingService
    import pandas as pd
    try:
        frame = pd.DataFrame(rows)
        summary = ProcessingService.summarize(frame)
        mongo.db.analytics_results.insert_one({
            "type": "correlation",
            "result": summary,
            "created_by": session.get("user_id"),
            "created_at": datetime.now(timezone.utc),
        })
        return jsonify({"status": "success", "correlations": summary["correlations"]})
    except Exception as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400
