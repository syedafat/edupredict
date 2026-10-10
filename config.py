import os
import secrets
import warnings
from datetime import timedelta
from email.utils import parseaddr
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
try:
    from dotenv import load_dotenv
except ImportError:  # requirements.txt installs it; keep imports usable for minimal smoke tests
    load_dotenv = lambda: None

load_dotenv()

_configured_environments = {
    os.environ.get('APP_ENV', '').strip().lower(),
    os.environ.get('FLASK_ENV', '').strip().lower(),
}
IS_DEPLOYMENT = bool(_configured_environments & {'staging', 'production'})
if IS_DEPLOYMENT:
    required_production_variables = (
        'APP_ENV', 'FLASK_ENV', 'FLASK_DEBUG', 'SECRET_KEY', 'MONGO_URI',
        'TRUSTED_HOSTS', 'SESSION_COOKIE_SECURE', 'SESSION_COOKIE_HTTPONLY',
        'SESSION_COOKIE_SAMESITE', 'RATELIMIT_STORAGE_URI',
    )
    missing_production_variables = [name for name in required_production_variables if not os.environ.get(name)]
    if missing_production_variables:
        raise RuntimeError('Required production configuration is missing: ' + ', '.join(missing_production_variables))
    app_environment = os.environ.get('APP_ENV', '').strip().lower()
    flask_environment = os.environ.get('FLASK_ENV', '').strip().lower()
    if app_environment not in {'staging', 'production'}:
        raise RuntimeError('APP_ENV must be explicitly set to staging or production')
    if flask_environment != app_environment:
        raise RuntimeError('FLASK_ENV must match APP_ENV in deployment environments')
    if os.environ.get('FLASK_DEBUG', '').strip().lower() != 'false':
        raise RuntimeError('FLASK_DEBUG must be explicitly set to false in deployment')
APP_ENV = os.environ.get(
    'APP_ENV',
    os.environ.get('FLASK_ENV', 'development')
).strip().lower()

_secret_key = os.environ.get('SECRET_KEY')
if not _secret_key:
    # In production we require an explicit secret key; fail fast.
    if IS_DEPLOYMENT:
        raise RuntimeError('SECRET_KEY must be set in deployment environment')
    # For development we fall back to a random key with a warning.
    warnings.warn(
        "SECRET_KEY environment variable is not set. "
        "A temporary random key is being used. Sessions will not persist across restarts. "
        "Set SECRET_KEY in deployment.",
        stacklevel=2
    )
    _secret_key = secrets.token_hex(32)

if (
    IS_DEPLOYMENT
    and len(_secret_key.encode('utf-8')) < 32
):
    raise RuntimeError('SECRET_KEY must contain at least 32 bytes in deployment')


def _validate_production_mongo_uri(uri):
    """Require an explicitly configured authenticated TLS MongoDB URI."""
    try:
        from pymongo.uri_parser import parse_uri
        parsed = parse_uri(uri, validate=True)
        options = {str(key).lower(): value for key, value in parsed.get('options', {}).items()}
        scheme = urlsplit(uri).scheme.lower()
        uses_tls = scheme == 'mongodb+srv' or str(
            options.get('tls', options.get('ssl', 'false'))
        ).lower() in {'true', '1'}
        uses_auth = bool(parsed.get('username')) or bool(options.get('authmechanism'))
        allows_invalid_cert = str(options.get('tlsallowinvalidcertificates', 'false')).lower() in {'true', '1'}
        allows_invalid_host = str(options.get('tlsallowinvalidhostnames', 'false')).lower() in {'true', '1'}
        allows_insecure_tls = str(options.get('tlsinsecure', 'false')).lower() in {'true', '1'}
        hosts = {host.lower() for host, _ in parsed.get('nodelist', [])}
        database_name = str(parsed.get('database') or '').lower()
        local_hosts = {'localhost', '127.0.0.1', '::1', 'mongo'}
        if (
            scheme not in {'mongodb', 'mongodb+srv'}
            or not parsed.get('database')
            or database_name in {'edupredict', 'demo', 'edupredict_demo', 'edupredict_test'}
            or not uses_tls
            or not uses_auth
            or hosts & local_hosts
            or allows_invalid_cert
            or allows_invalid_host
            or allows_insecure_tls
        ):
            raise ValueError
    except Exception:
        # Do not include the URI or parser exception; either may contain credentials.
        raise RuntimeError('Deployment MONGO_URI must use authenticated TLS with certificate validation enabled') from None


def _configure_mongo_pool(uri):
    """Apply bounded PyMongo pool/network defaults without exposing the URI."""
    parts = urlsplit(uri)
    query = parse_qsl(parts.query, keep_blank_values=True)
    existing = {key.lower() for key, _ in query}
    configured = (
        ('maxPoolSize', os.environ.get('MONGO_MAX_POOL_SIZE', '50')),
        ('minPoolSize', os.environ.get('MONGO_MIN_POOL_SIZE', '0')),
        ('serverSelectionTimeoutMS', os.environ.get('MONGO_SERVER_SELECTION_TIMEOUT_MS', '5000')),
        ('connectTimeoutMS', os.environ.get('MONGO_CONNECT_TIMEOUT_MS', '5000')),
        ('socketTimeoutMS', os.environ.get('MONGO_SOCKET_TIMEOUT_MS', '20000')),
    )
    for name, value in configured:
        if name.lower() not in existing:
            query.append((name, value))
    try:
        options = {name: int(value) for name, value in configured}
    except ValueError:
        raise RuntimeError('MongoDB pool and timeout configuration must be integers') from None
    if options['maxPoolSize'] < 1 or options['minPoolSize'] < 0 or options['minPoolSize'] > options['maxPoolSize']:
        raise RuntimeError('MongoDB pool sizes are invalid')
    if any(options[name] < 1 for name in ('serverSelectionTimeoutMS', 'connectTimeoutMS', 'socketTimeoutMS')):
        raise RuntimeError('MongoDB timeouts must be positive')
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _valid_trusted_host(host):
    return not (
        any(char in host for char in '/\\?#@')
        or any(char.isspace() for char in host)
        or host.startswith('.')
        or host.endswith('.')
    )


class Config:
    APP_ENV = APP_ENV
    SECRET_KEY = _secret_key
    DEBUG = os.environ.get('FLASK_DEBUG', 'false').strip().lower() == 'true'
    PASSWORD_RESET_EXPOSE_LINK = os.environ.get(
        'PASSWORD_RESET_EXPOSE_LINK', 'false'
    ).lower() == 'true'
    if IS_DEPLOYMENT and PASSWORD_RESET_EXPOSE_LINK:
        raise RuntimeError('PASSWORD_RESET_EXPOSE_LINK must be disabled in deployment')

    MAIL_PROVIDER = os.environ.get('MAIL_PROVIDER', 'smtp').strip().lower()
    if MAIL_PROVIDER not in {'smtp', 'resend'}:
        raise RuntimeError('MAIL_PROVIDER must be smtp or resend')
    RESEND_API_KEY = os.environ.get('RESEND_API_KEY', '').strip()
    MAIL_SERVER = os.environ.get('MAIL_SERVER', '').strip()
    try:
        MAIL_PORT = int(os.environ.get('MAIL_PORT', '587'))
    except ValueError:
        raise RuntimeError('MAIL_PORT must be a valid TCP port') from None
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
    MAIL_USE_TLS = os.environ.get('MAIL_USE_TLS', 'false').strip().lower() in {'true', '1'}
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', '').strip()
    PASSWORD_RESET_BASE_URL = os.environ.get('PASSWORD_RESET_BASE_URL', '').strip().rstrip('/')
    MAIL_TIMEOUT = 10
    if not 1 <= MAIL_PORT <= 65535:
        raise RuntimeError('MAIL_PORT must be between 1 and 65535')

    if IS_DEPLOYMENT:
        configured_trusted_hosts = [
            host.strip()
            for host in os.environ.get('TRUSTED_HOSTS', '').split(',')
            if host.strip()
        ]
        if not configured_trusted_hosts:
            raise RuntimeError('TRUSTED_HOSTS must be configured in deployment')
        if any('*' in host for host in configured_trusted_hosts):
            raise RuntimeError('TRUSTED_HOSTS must list explicit hostnames in deployment')
        if not all(_valid_trusted_host(host) for host in configured_trusted_hosts):
            raise RuntimeError('TRUSTED_HOSTS contains an invalid hostname')
        required_mail_settings = {
            'MAIL_DEFAULT_SENDER': MAIL_DEFAULT_SENDER,
            'PASSWORD_RESET_BASE_URL': PASSWORD_RESET_BASE_URL,
        }
        if MAIL_PROVIDER == 'smtp':
            required_mail_settings.update({
                'MAIL_SERVER': MAIL_SERVER,
                'MAIL_PORT': os.environ.get('MAIL_PORT', '').strip(),
                'MAIL_USERNAME': MAIL_USERNAME,
                'MAIL_PASSWORD': MAIL_PASSWORD,
            })
        elif not RESEND_API_KEY:
            required_mail_settings['RESEND_API_KEY'] = RESEND_API_KEY
        if not all(required_mail_settings.values()):
            missing_mail_settings = ', '.join(
                name for name, value in required_mail_settings.items() if not value
            )
            raise RuntimeError(f"Deployment password reset requires: {missing_mail_settings}")
        if MAIL_PROVIDER == 'smtp' and not MAIL_USE_TLS:
            raise RuntimeError('MAIL_USE_TLS must be enabled in deployment')
        sender_address = parseaddr(MAIL_DEFAULT_SENDER)[1]
        reset_base = urlsplit(PASSWORD_RESET_BASE_URL)
        trusted_hosts = {host.lower() for host in configured_trusted_hosts}
        if (
            not sender_address
            or '@' not in sender_address
            or reset_base.scheme != 'https'
            or not reset_base.hostname
            or reset_base.hostname.lower() not in trusted_hosts
            or reset_base.username
            or reset_base.password
            or reset_base.query
            or reset_base.fragment
            or reset_base.path not in {'', '/'}
        ):
            raise RuntimeError('Deployment mail sender and password reset base URL must be valid and trusted')

    # MongoDB
    # Never commit credentials to source control. Set MONGO_URI in the
    # environment for a real deployment; the local URI keeps development
    # usable without exposing a remote database.
    MONGO_URI = os.environ.get(
        'MONGO_URI',
        'mongodb://localhost:27017/edupredict'
        '?serverSelectionTimeoutMS=3000&connectTimeoutMS=3000'
    )
    MONGO_URI = _configure_mongo_pool(MONGO_URI)
    if IS_DEPLOYMENT:
        if not os.environ.get('MONGO_URI'):
            raise RuntimeError('MONGO_URI must be explicitly set in deployment environment')
        _validate_production_mongo_uri(MONGO_URI)

    # Hadoop
    HADOOP_NAMENODE_URL = os.environ.get('HADOOP_NAMENODE_URL', 'http://localhost:50070')
    HADOOP_ALLOWED_HOSTS = {
        host.strip().lower()
        for host in os.environ.get('HADOOP_ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')
        if host.strip()
    }

    TRUSTED_HOSTS = [
        host.strip()
        for host in os.environ.get('TRUSTED_HOSTS', '').split(',')
        if host.strip()
    ] or None
    if IS_DEPLOYMENT:
        if not TRUSTED_HOSTS:
            raise RuntimeError('TRUSTED_HOSTS must be configured in deployment')
        if any('*' in host for host in TRUSTED_HOSTS):
            raise RuntimeError('TRUSTED_HOSTS must list explicit hostnames in deployment')
        # Permit only loopback names needed by the in-container health probe.
        TRUSTED_HOSTS = list(dict.fromkeys([*TRUSTED_HOSTS, 'localhost', '127.0.0.1']))

    PROXY_FIX_X_FOR = int(os.environ.get('PROXY_FIX_X_FOR', '0'))
    PROXY_FIX_X_PROTO = int(os.environ.get('PROXY_FIX_X_PROTO', '0'))
    if min(PROXY_FIX_X_FOR, PROXY_FIX_X_PROTO) < 0:
        raise RuntimeError('ProxyFix forwarded-header counts cannot be negative')
    if IS_DEPLOYMENT and max(PROXY_FIX_X_FOR, PROXY_FIX_X_PROTO) > 1:
        raise RuntimeError('Deployment ProxyFix counts may trust at most one configured proxy')
    PREFERRED_URL_SCHEME = 'https' if IS_DEPLOYMENT else 'http'

    # File storage — anchored to project directory, not cwd
    _base_dir = os.path.dirname(os.path.abspath(__file__))
    UPLOAD_FOLDER = os.path.join(_base_dir, 'uploads')
    MODEL_FOLDER  = os.path.join(_base_dir, 'models')

    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB
    ALLOWED_DATASET_EXTENSIONS = {'csv', 'xlsx', 'xls', 'json', 'txt'}
    VALID_DATASET_TYPES = {'academic', 'attendance', 'lms', 'demographics', 'general'}
    HADOOP_ENABLED = os.environ.get('HADOOP_ENABLED', 'false').lower() == 'true'
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')
    if IS_DEPLOYMENT:
        rate_limit_storage = urlsplit(RATELIMIT_STORAGE_URI)
        if rate_limit_storage.scheme not in {'redis', 'rediss'} or not rate_limit_storage.hostname:
            raise RuntimeError('RATELIMIT_STORAGE_URI must use a reachable shared Redis host in deployment')
    STREAM_BACKEND = os.environ.get('STREAM_BACKEND', 'local').lower()
    KAFKA_BOOTSTRAP_SERVERS = os.environ.get('KAFKA_BOOTSTRAP_SERVERS', '')

    # Session security
    SESSION_COOKIE_HTTPONLY = os.environ.get('SESSION_COOKIE_HTTPONLY', 'true').strip().lower() == 'true'
    if IS_DEPLOYMENT and not SESSION_COOKIE_HTTPONLY:
        raise RuntimeError('SESSION_COOKIE_HTTPONLY must be true in deployment')
    SESSION_COOKIE_SAMESITE = os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax').strip()
    if SESSION_COOKIE_SAMESITE not in {'Lax', 'Strict', 'None'}:
        raise RuntimeError('SESSION_COOKIE_SAMESITE must be Lax, Strict, or None')
    # Set SESSION_COOKIE_SECURE=true in deployment (requires HTTPS)
    SESSION_COOKIE_SECURE = os.getenv('SESSION_COOKIE_SECURE', 'false').lower() == 'true'
    # Enforce secure cookie in deployment
    if IS_DEPLOYMENT:
        if not SESSION_COOKIE_SECURE:
            raise RuntimeError('SESSION_COOKIE_SECURE must be true in deployment')
        if SESSION_COOKIE_SAMESITE == 'None':
            raise RuntimeError('SESSION_COOKIE_SAMESITE must not be None in deployment')

    # Session lifetime for remember-me
    PERMANENT_SESSION_LIFETIME = timedelta(days=14)

    # WTF / CSRF
    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600  # 1 hour token validity
