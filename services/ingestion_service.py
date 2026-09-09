import os
import uuid
import hashlib
from datetime import datetime, timezone
from flask import current_app
from werkzeug.utils import secure_filename
from services.hadoop_service import HadoopService
from services.processing_service import ProcessingService

def allowed_file(filename):
    allowed = current_app.config.get(
        'ALLOWED_DATASET_EXTENSIONS',
        {'csv', 'xlsx', 'xls', 'json', 'txt'}
    )
    return bool(filename) and '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed


def _dataset_type(value):
    value = (value or 'general').strip().lower()
    valid_types = current_app.config.get(
        'VALID_DATASET_TYPES',
        {'academic', 'attendance', 'lms', 'demographics', 'general'}
    )
    return value if value in valid_types else None

class IngestionService:
    @staticmethod
    def process_and_store_dataset(file_storage, dataset_type, uploaded_by=None, title=None):
        dataset_type = _dataset_type(dataset_type)
        if not dataset_type:
            return {'success': False, 'error': 'Invalid dataset type.'}
        return IngestionService.save_and_record(
            file_storage,
            dataset_type=dataset_type,
            uploaded_by=uploaded_by,
            title=title,
        )

    @staticmethod
    def save_and_record(
        file_storage,
        dataset_type='general',
        uploaded_by=None,
        upload_folder=None,
        title=None,
    ):
        """
        Shared upload helper used by multiple routes.
        1. Validates file type
        2. Generates unique safe filename (UUID + secure_filename)
        3. Saves to the appropriate directory
        4. Records metadata to MongoDB 'datasets' collection
        5. Calls HDFS upload (non-blocking on failure)
        6. Returns result dict: success, path, filename, hdfs_success
        """
        from flask import current_app
        from models import mongo
        dataset_type = _dataset_type(dataset_type)
        if not dataset_type:
            return {'success': False, 'error': 'Invalid dataset type.'}
        if not file_storage or not getattr(file_storage, 'filename', ''):
            return {'success': False, 'error': 'Please select a dataset file.'}
        if not allowed_file(file_storage.filename):
            return {'success': False, 'error': 'Invalid file format.'}

        safe_base = secure_filename(file_storage.filename)
        if not safe_base:
            return {'success': False, 'error': 'Invalid filename.'}

        filename = f"{uuid.uuid4().hex}_{safe_base}"
        extension = safe_base.rsplit('.', 1)[-1].lower() if '.' in safe_base else ''

        # Determine save directory
        if upload_folder is None:
            upload_folder = os.path.join(
                current_app.config.get('UPLOAD_FOLDER', 'uploads'),
                'datasets'
            )
        os.makedirs(upload_folder, exist_ok=True)

        file_path = os.path.join(upload_folder, filename)
        file_storage.save(file_path)
        with open(file_path, "rb") as handle:
            source_hash = hashlib.sha256(handle.read()).hexdigest()
        duplicate = mongo.db.datasets.find_one({"source_hash": source_hash, "dataset_type": dataset_type}, {"_id": 1})
        if duplicate:
            os.remove(file_path)
            return {'success': False, 'error': 'This dataset has already been uploaded for the selected dataset type.'}

        # Record metadata in MongoDB
        try:
            inserted = mongo.db.datasets.insert_one({
                'title': (title or safe_base)[:160],
                'original_filename': file_storage.filename,
                'stored_filename': filename,
                'file_path': file_path,
                'extension': extension,
                'file_size': os.path.getsize(file_path),
                'source_hash': source_hash,
                'dataset_type': dataset_type,
                'uploaded_by': uploaded_by,
                'uploaded_at': datetime.now(timezone.utc),
                'status': 'uploaded',
                'hdfs_status': 'pending',
            })
        except Exception as e:
            current_app.logger.exception("Could not record dataset metadata: %s", e)
            try:
                os.remove(file_path)
            except OSError:
                pass
            return {'success': False, 'error': 'The dataset could not be recorded.'}

        # HDFS upload — non-blocking on failure. The local copy is still a
        # successful ingest when HDFS is unavailable or disabled.
        partition = datetime.now(timezone.utc).strftime("%Y/%m")
        hdfs_destination = f"{dataset_type}/{partition}"
        hdfs_success = False
        try:
            hdfs_success = HadoopService.upload_to_hdfs(file_path, hdfs_destination)
        except Exception as e:
            current_app.logger.warning(f"HDFS upload failed (non-fatal): {e}")

        processing = ProcessingService.process_dataset(file_path)
        persisted_records = {}
        quality_failed = processing.get("quality_status") == "INVALID"
        processing_accepted = processing.get("success") and not quality_failed
        if processing_accepted:
            try:
                persisted_records = ProcessingService.records_for_storage(
                    processing["processed_path"], dataset_type, inserted.inserted_id
                )
            except Exception as exc:
                current_app.logger.exception("Processed records could not be persisted: %s", exc)
                processing["records_persist_error"] = str(exc)
        elif quality_failed:
            mongo.db.rejected_records.insert_one({
                "dataset_id": inserted.inserted_id,
                "dataset_type": dataset_type,
                "quality_report": processing,
                "created_at": datetime.now(timezone.utc),
                "reason": "data_quality_validation_failed",
            })
        mongo.db.datasets.update_one(
            {'_id': inserted.inserted_id},
            {'$set': {
                'hdfs_status': 'uploaded' if hdfs_success else (
                    'disabled' if not current_app.config.get('HADOOP_ENABLED') else 'unavailable'
                ),
                'status': 'processed' if processing_accepted else 'validation_failed',
                'processing_summary': processing if processing.get('success') else {'error': processing.get('error')},
                'processed_path': processing.get('processed_path') if processing.get('success') else None,
                'persisted_records': persisted_records,
                'hdfs_path': f"/edupredict/{hdfs_destination}/{filename}" if hdfs_success else None,
            }}
        )
        return {
            'success': bool(processing_accepted),
            'dataset_id': str(inserted.inserted_id),
            'path': file_path,
            'filename': filename,
            'hdfs_success': hdfs_success,
            'processing': processing,
            'persisted_records': persisted_records,
            'error': None if processing_accepted else ('Dataset failed data-quality validation.' if quality_failed else processing.get('error', 'Dataset processing failed.')),
        }
