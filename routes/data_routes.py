import os
from flask import Blueprint, render_template, request, flash, redirect, url_for, abort, session, jsonify
from utils.decorators import role_required
from services.ingestion_service import IngestionService
from models import mongo
from bson import ObjectId
from services.alert_service import AlertService
from services.hadoop_service import HadoopService

data_bp = Blueprint('data', __name__, url_prefix='/data')

@data_bp.route('/upload', methods=['GET', 'POST'])
@role_required('admin', 'teacher', 'analyst')
def upload_dataset():
    if request.method == 'POST':
        dataset_type = (request.form.get('dataset_type') or '').strip().lower()
        file = request.files.get('file') or request.files.get('dataset_file')
        
        if not file:
            flash('No file selected.', 'danger')
            return redirect(request.url)
            
        result = IngestionService.process_and_store_dataset(
            file,
            dataset_type,
            uploaded_by=session.get('user_id'),
            title=request.form.get('title', '').strip(),
        )
        if result['success']:
            if result.get('hdfs_success'):
                flash('Dataset uploaded and forwarded to HDFS successfully.', 'success')
            else:
                flash('Dataset saved locally. HDFS is unavailable or disabled.', 'warning')
        else:
            flash(result.get('error', 'Upload failed.'), 'danger')
            
        if result['success']:
            return redirect(url_for('data.dataset_detail', dataset_id=result['dataset_id']))
        return redirect(url_for('data.upload_dataset'))
        
    return render_template('data/upload.html')

@data_bp.route('/dataset/<dataset_id>', methods=['GET'])
@role_required('admin', 'teacher', 'analyst')
def dataset_detail(dataset_id):
    try:
        dataset = mongo.db.datasets.find_one({'_id': ObjectId(dataset_id)})
    except Exception:
        abort(404)
    if not dataset:
        abort(404)
    return render_template('data/dataset_detail.html', dataset=dataset, dataset_id=dataset_id)


@data_bp.route('/dataset/<dataset_id>/download', methods=['GET'])
@role_required('admin', 'teacher', 'analyst')
def download_dataset(dataset_id):
    from flask import current_app, send_file
    dataset = mongo.db.datasets.find_one({'_id': ObjectId(dataset_id)}) if ObjectId.is_valid(dataset_id) else None
    if not dataset:
        abort(404)
    path = os.path.abspath(dataset.get('file_path', ''))
    root = os.path.abspath(os.path.join(current_app.config['UPLOAD_FOLDER'], 'datasets'))
    if not path or os.path.commonpath([root, path]) != root or not os.path.isfile(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=dataset.get('original_filename', 'dataset'))

@data_bp.route('/processing', methods=['GET'])
@role_required('admin', 'teacher', 'analyst')
def processing():
    datasets = list(mongo.db.datasets.find({}, {
        "original_filename": 1, "dataset_type": 1, "status": 1,
        "processing_summary": 1, "uploaded_at": 1, "hdfs_status": 1,
    }).sort("uploaded_at", -1).limit(100))
    return render_template('data/processing.html', datasets=datasets)

@data_bp.route('/streaming', methods=['GET'])
@role_required('admin', 'teacher')
def streaming():
    events = list(mongo.db.stream_events.find({}, {"_id": 0}).sort("received_at", -1).limit(50))
    return render_template('data/streaming.html', events=events, hdfs_status=HadoopService.status())


@data_bp.route('/stream', methods=['POST'])
@role_required('admin', 'teacher', 'analyst')
def ingest_stream_event():
    from services.processing_service import ProcessingService
    payload = request.get_json(silent=True) or {}
    try:
        event = ProcessingService.process_stream_event(payload)
        event["ingested_by"] = session.get("user_id")
        mongo.db.stream_events.insert_one(event)
        if event.get("student_id"):
            AlertService.evaluate_student(event["student_id"])
        return jsonify({"status": "success", "message": "Event accepted by the local stream processor."}), 201
    except ValueError as exc:
        return jsonify({"status": "error", "message": str(exc)}), 400


@data_bp.route('/hdfs-status')
@role_required('admin', 'teacher', 'analyst')
def hdfs_status():
    return jsonify({"status": "success", "hdfs": HadoopService.status()})