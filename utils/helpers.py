import os
from flask import current_app
from werkzeug.utils import secure_filename

def save_temp_file(file_storage):
    if file_storage and file_storage.filename:
        filename = secure_filename(file_storage.filename)
        if not filename:
            return None
        try:
            upload_folder = current_app.config['UPLOAD_FOLDER']
        except RuntimeError:
            upload_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'uploads')
        temp_dir = os.path.join(upload_folder, 'temporary')
        os.makedirs(temp_dir, exist_ok=True)
        path = os.path.join(temp_dir, filename)
        file_storage.save(path)
        return path
    return None