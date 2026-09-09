import os
import secrets
import warnings
from datetime import timedelta
try:
    from dotenv import load_dotenv
except ImportError:  # requirements.txt installs it; keep imports usable for minimal smoke tests
    load_dotenv = lambda: None

load_dotenv()

_secret_key = os.environ.get('SECRET_KEY')
if not _secret_key:
    warnings.warn(
        "SECRET_KEY environment variable is not set. "
        "A temporary random key is being used. Sessions will not persist across restarts. "
        "Set SECRET_KEY in production.",
        stacklevel=2
    )
    _secret_key = secrets.token_hex(32)


class Config:
    SECRET_KEY = _secret_key

    # MongoDB
    # Never commit credentials to source control. Set MONGO_URI in the
    # environment for a real deployment; the local URI keeps development
    # usable without exposing a remote database.
    MONGO_URI = os.environ.get(
        'MONGO_URI',
        'mongodb://localhost:27017/edupredict'
        '?serverSelectionTimeoutMS=3000&connectTimeoutMS=3000'
    )

    # Hadoop
    HADOOP_NAMENODE_URL = os.environ.get('HADOOP_NAMENODE_URL', 'http://localhost:50070')
    HADOOP_ALLOWED_HOSTS = {
        host.strip().lower()
        for host in os.environ.get('HADOOP_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
        if host.strip()
    }

    # File storage — anchored to project directory, not cwd
    _base_dir = os.path.dirname(os.path.abspath(__file__))
    UPLOAD_FOLDER = os.path.join(_base_dir, 'uploads')
    MODEL_FOLDER  = os.path.join(_base_dir, 'models')

    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB
    ALLOWED_DATASET_EXTENSIONS = {'csv', 'xlsx', 'xls', 'json', 'txt'}
    VALID_DATASET_TYPES = {'academic', 'attendance', 'lms', 'demographics', 'general'}
    HADOOP_ENABLED = os.environ.get('HADOOP_ENABLED', 'false').lower() == 'true'
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')
    STREAM_BACKEND = os.environ.get('STREAM_BACKEND', 'local').lower()
    KAFKA_BOOTSTRAP_SERVERS = os.environ.get('KAFKA_BOOTSTRAP_SERVERS', '')

    # Session security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    # Set SESSION_COOKIE_SECURE=true in production (requires HTTPS)
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'false').lower() == 'true'

    # Session lifetime for remember-me
    PERMANENT_SESSION_LIFETIME = timedelta(days=14)

    # WTF / CSRF
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # 1 hour token validity
    # Email delivery is intentionally opt-in. In local development, setting
    # this to true displays the generated reset URL so the flow can be tested.
    PASSWORD_RESET_EXPOSE_LINK = os.environ.get(
        'PASSWORD_RESET_EXPOSE_LINK', 'false'
    ).lower() == 'true'