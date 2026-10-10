# Production Deployment

## Readiness and Scope

The example environment is development-only. Do not deploy the existing demo database as production. A dedicated production MongoDB URI, secret-manager values, trusted hostname, SMTP provider, and HTTPS reverse proxy must be provisioned by the operator. No external deployment is performed by this guide.

## Production Environment

Supply these environment variable names through the service manager or secret manager; never commit populated values:

| Variable | Purpose |
| --- | --- |
| `APP_ENV` | Must identify the production environment |
| `FLASK_ENV` | Set consistently to production |
| `FLASK_DEBUG` | Must remain disabled |
| `EDUPREDICT_IMAGE` | Versioned Compose image tag for this deployment |
| `SECRET_KEY` | Random secret with at least 32 UTF-8 bytes |
| `MONGO_URI` | Dedicated database, explicit database name, authenticated TLS, certificate validation |
| `TRUSTED_HOSTS` | Exact public hostnames, no wildcard |
| `SESSION_COOKIE_SECURE` | Secure-only session cookie |
| `SESSION_COOKIE_SAMESITE` | `Lax` or `Strict` |
| `RATELIMIT_STORAGE_URI` | Shared Redis storage for direct Gunicorn deployments |
| `PASSWORD_RESET_EXPOSE_LINK` | Disabled in production |
| `MAIL_PROVIDER` | `smtp` or `resend` |
| `RESEND_API_KEY` | Resend API key from the secret manager (Resend only) |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD` | SMTP settings when `MAIL_PROVIDER=smtp` |
| `MAIL_USE_TLS` | Must be enabled for SMTP; Resend uses HTTPS API delivery |
| `MAIL_DEFAULT_SENDER` | Verified sender address |
| `PASSWORD_RESET_BASE_URL` | HTTPS origin listed in `TRUSTED_HOSTS` |

When behind exactly one trusted reverse proxy, set `PROXY_FIX_X_FOR=1` and `PROXY_FIX_X_PROTO=1` to trust one forwarded client address and scheme. Gunicorn does not trust forwarded host, port, or prefix headers. Do not expose Gunicorn directly to untrusted networks. Optional integration names are `HADOOP_ENABLED`, `HADOOP_NAMENODE_URL`, and `HADOOP_ALLOWED_HOSTS`.

Use a secret manager or a protected runtime environment file (never commit it) with values shaped like these placeholders:

```dotenv
APP_ENV=production
FLASK_ENV=production
FLASK_DEBUG=false
SECRET_KEY=<GENERATE_AT_LEAST_32_RANDOM_BYTES>
MONGO_URI=mongodb+srv://<PRODUCTION_DB_USER>:<URL_ENCODED_PASSWORD>@<ATLAS_CLUSTER_HOST>/edupredict_prod?retryWrites=true&w=majority&tls=true
TRUSTED_HOSTS=<PUBLIC_DNS_HOSTNAME>
SESSION_COOKIE_SECURE=true
SESSION_COOKIE_HTTPONLY=true
SESSION_COOKIE_SAMESITE=Lax
RATELIMIT_STORAGE_URI=<PRIVATE_REDIS_URL>
PROXY_FIX_X_FOR=1
PROXY_FIX_X_PROTO=1
MAIL_PROVIDER=resend
RESEND_API_KEY=<RESEND_SECRET_FROM_SECRET_MANAGER>
MAIL_DEFAULT_SENDER=EduPredict <verified-sender@your-domain.example>
PASSWORD_RESET_BASE_URL=https://<PUBLIC_DNS_HOSTNAME>
```

Use `.env.staging.example` and `.env.production.example` as placeholders. The staging URI names `edupredict_staging`; production names `edupredict_prod`. Create separate Atlas database users scoped to each database, and replace all placeholder values before use. Staging and production both use deployment-grade startup validation and secure cookies.

For example, generate a key with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and deliver it through your deployment secret store. Never put the generated output in shell history or source files.

Deployment startup rejects weak/missing keys, unsafe Mongo URIs, missing trusted hosts, memory-only rate limits, insecure cookies, reset-link exposure, and missing/invalid provider settings. The development `.env.example` is not a deployment template. Docker excludes `.env` and `.env.*` from its build context.

## Production Dependency Lock

`requirements.txt` contains runtime dependency ranges; `requirements-dev.txt` adds test tools and `pip-tools`. Generate a hash-pinned production lock in Linux/Python 3.12 release CI:

```bash
python -m pip install -r requirements-dev.txt
python scripts/generate_requirements_lock.py
```

Commit the generated `requirements-prod.lock` for each release. The Dockerfile installs it with `pip install --require-hashes`; a Docker build intentionally fails until that target-platform lock is generated and present. The application also has a pinned frontend toolchain in `package-lock.json`; run `npm ci && npm run build:assets` when changing templates or frontend dependencies, then commit the generated local assets under `static/`.

## Password Reset Email

Password reset supports standard-library SMTP with STARTTLS or the Resend HTTPS API, selected by `MAIL_PROVIDER`. Credentials come only from the runtime environment. Both send a plain-text message and use a generic response, a cryptographically random token stored only as a hash, and the existing 30-minute token expiry. The link uses `PASSWORD_RESET_BASE_URL`, not the inbound Host header. API keys, SMTP credentials, passwords, and reset tokens are not logged. If delivery fails, that request's reset token is invalidated and the response remains generic. Verify delivery and sender-domain policy with the chosen provider before enabling production account recovery.

## MongoDB and Indexes

Use a dedicated production database and a least-privilege application identity scoped to that database. The application needs read/write operations for normal workflows and permission to create its declared indexes; it does not require cluster-wide administration. Use a separate backup identity with only the backup/read privileges required by your MongoDB deployment. Restrict network access, require TLS, rotate credentials, and never copy demo data automatically.

The application initializes indexes without dropping collections. The current index set includes:

- `users.email` unique.
- `notifications(user_id, created_at)` and `support_tickets(created_by, created_at)`.
- `datasets(dataset_type, uploaded_at)` and a partial unique `datasets(source_hash, dataset_type)` index.
- `rejected_records(dataset_id, created_at)`, `predictions(student_id, model_type, created_at)`, `attendance(student_id, date)`, and `grades(student_id, created_at)`.
- `assignments(student_id, status, due_date)`, sparse unique `assignments(student_id, assignment_key)`, and unique `submissions(student_id, assignment_id)`.
- `enrollments(student_id, status)`, `enrollments(course_id, status)`, and unique `enrollments(student_id, course_id)`.
- `stream_events(student_id, received_at)`, `system_logs(event_type, created_at)`, and audit-log indexes on `(target_type, target_id, timestamp)` and `(user_id, timestamp)`.

Startup creates the non-destructive application indexes only. Legacy embedded course-roster migration is now an explicit one-time operation, never an app-startup action. Review its impact and take a verified backup before running it against a deployment database:

```bash
RUN_LEGACY_ROSTER_MIGRATION=true python -m scripts.migrate_legacy_rosters
```

Do not point startup or migration at the demo database to validate production settings.

## Backups and Restore

`scripts/backup_mongodb.py` reads `MONGO_URI` from the environment, writes it to a short-lived mode-restricted MongoDB tools config file, invokes `mongodump --config`, suppresses tool output on failure, and removes the config file. The URI is not passed as a process argument. Backups contain sensitive institutional data: encrypt them at rest and in transit, restrict access, store an off-host copy, set retention, and run scheduled restore drills.

A safe restore drill must target an isolated database and must not use `--drop` or point at the demo/production database. Create a protected MongoDB tools config file containing only the restore URI, with owner-only permissions. Example namespace remap for a disposable restore target:

```bash
mongorestore --config /secure/path/mongo-tools.yml \
  --nsFrom='edupredict.*' \
  --nsTo='edupredict_restore_check.*' \
  /secure/backups/<timestamp>/edupredict
```

The target URI in the protected config must identify the isolated restore-check database. Validate collections and indexes there, then remove that isolated target through the approved database-operations process. No restore was run during this task.

## WSGI and HTTPS Proxy

Use Gunicorn on Linux, bound to loopback when Nginx runs on the same host:

```bash
gunicorn --bind 127.0.0.1:8000 --workers 4 --threads 2 --timeout 120 \
  --access-logfile - \
  --access-logformat '%(h)s %(t)s "%(m)s %(U)s %(H)s" %(s)s %(b)s' \
  wsgi:app
```

The access-log format omits query strings. `python app.py` is development-only. The production Compose service uses Gunicorn, an unprivileged user, a read-only root filesystem, loopback-only app port publication, private Redis, and `/health` as its liveness check. `/health/ready` checks MongoDB readiness and returns 503 when it is unavailable. MongoDB remains external.

Build and launch with secrets supplied to Compose through the protected deployment environment (or its secret injection mechanism):

```bash
docker compose --env-file .env.production config
docker compose --env-file .env.production build
docker compose --env-file .env.production up -d
curl --fail http://127.0.0.1:5000/health
curl --fail https://<PUBLIC_DNS_HOSTNAME>/health/ready
```

Use a versioned image tag for each release rather than relying on `latest`; retain the previous known-good image and configuration for rollback. Roll back by redeploying that image and its matching non-destructive application configuration. Take and verify a database backup before production changes that alter persisted data. Admin creation/reset is an explicit operator action via `scripts/seed_admin.py` or `scripts/reset_admin_user.py`, with `ALLOW_ADMIN_SEED=true` and credentials injected only for that invocation; neither is called by application startup.

Example Nginx structure; provide the actual host and certificate paths through operator configuration. Define the log format in the Nginx `http` block; `$uri` omits query parameters. Ensure inbound access to Gunicorn is restricted to the proxy; the sample forwards one proxy hop, matching the `ProxyFix` counts above.

```nginx
log_format edupredict '$remote_addr [$time_local] "$request_method $uri $server_protocol" $status $body_bytes_sent';

server {
    listen 80;
    server_name <configured-hostname>;
    server_tokens off;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name <configured-hostname>;
    server_tokens off;
    ssl_certificate <certificate-path>;
    ssl_certificate_key <private-key-path>;
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Referrer-Policy "no-referrer" always;
    access_log /var/log/nginx/edupredict_access.log edupredict;
    client_max_body_size 16m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_redirect off;
    }
}
```

The configured host must be included in `TRUSTED_HOSTS`. Restrict network access so only the proxy reaches the loopback-bound Gunicorn listener. The app trusts only the configured proxy count. The proxy and HTTPS behavior were not exercised here.

## CSP and Security Headers

Tailwind is compiled locally from templates; Chart.js, Font Awesome, and the DM Sans/Space Grotesk font files are self-hosted. Dynamic progress widths and dashboard rings use bounded local CSS classes instead of style attributes. Inline scripts retain per-response nonces. CSP disallows `unsafe-inline`, `unsafe-eval`, inline style attributes, remote asset origins, and plugin objects; it also restricts forms to same-origin. Standard response security headers remain enabled, with HSTS emitted only for HTTPS requests.

## Security and Verification

CSRF, password hashing, rate limits, authorization/object-scope checks, upload size/type/path checks, generic error responses, security headers, and the sanitized health endpoint remain enabled. CORS is not enabled. The app retains its existing request-size limit.

Run before release:

```bash
python -m pytest -q --tb=short
python -m compileall -q .
```

This workspace has no Docker executable, so YAML/static validation is possible but a container build is not. Production MongoDB permissions/connectivity, SMTP delivery, backup restore, domain/host values, and real HTTPS proxy behavior require operator infrastructure and remain unverified. Do not perform an external deployment until those checks pass.
