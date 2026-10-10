# EduPredict Client Handover

This guide collects the existing deployment and operating instructions for an institution that will own its EduPredict environment. It does not certify this workspace as production-ready. The release gate must be `READY FOR HANDOVER` for a production handoff; the current gate remains blocked while credentials, infrastructure, browser QA, image build, and release approval are outstanding.

## Handover document set

- [Production deployment](DEPLOYMENT.md): runtime configuration, dependency lock workflow, Docker/Compose, Gunicorn, and HTTPS proxy.
- [Operations](OPERATIONS.md): backup invocation, migration notes, health endpoints, monitoring.
- [Backup and restore](BACKUP_RESTORE.md): protected BSON backup and isolated, non-destructive restore drill.
- [User guide](../guides/USER_GUIDE.md): role workflows and product use.
- [Developer guide](../guides/DEVELOPER_GUIDE.md): data flow, collections, and ML integration.
- [Demo guide](../guides/DEMO_GUIDE.md): product walkthrough.
- [Manual QA checklist](../qa-reports/MANUAL_QA_CHECKLIST.md): browser and environment checks.
- [Production release gate](RELEASE_GATE.md): evidence-based final acceptance record.

The intended handover package is this file plus the linked repository documentation, approved source manifest, reviewed dependency lock, and versioned image. Do not include `.env`, database dumps, student data, model artifacts, uploads, logs, or credentials in a client archive.

## Deployment prerequisites and install

The supported production container is Python 3.12 on Linux. Production needs a dedicated MongoDB database, a secret manager, a public hostname and HTTPS reverse proxy, shared Redis, and a configured mail provider. MongoDB, Redis persistence, DNS, certificates, and email delivery are client-owned services.

1. Obtain the owner-approved source version and verify its commit/tag. Do not use an unreviewed working tree.
2. Create protected staging and production secret sets from [`.env.staging.example`](../../.env.staging.example) and [`.env.production.example`](../../.env.production.example). The files contain placeholders; populate values in the institution’s secret manager. Do not use `.env.example` for deployment.
3. Generate and review the Python 3.12 Linux production lock, then build and identify the versioned image. The exact commands are in the [release gate](RELEASE_GATE.md). The image build is blocked until `requirements-prod.lock` exists.
4. Configure the external HTTPS proxy and DNS before enabling public access. Publish the app container only to loopback behind that proxy, as configured in Compose.
5. Provide the approved environment file through a protected deployment mechanism and follow [DEPLOYMENT.md](DEPLOYMENT.md) for Compose startup. Keep secrets out of shell history, tickets, logs, and build artifacts.
6. Check container liveness at `/health` and database readiness at `/health/ready`. Readiness requires MongoDB connectivity; a passing liveness response alone does not mean the service is ready.
7. Retain the previous approved image and matching configuration for rollback. Do not deploy until every mandatory gate row passes.

Example client-side deployment commands, after the release image and protected configuration are ready:

```bash
docker compose --env-file .env.production config
docker compose --env-file .env.production build
docker compose --env-file .env.production up -d
curl --fail http://127.0.0.1:5000/health
curl --fail https://<PUBLIC_HOST>/health/ready
```

`docker compose config` can render interpolated settings. Run it only in a protected terminal and never paste its output into tickets or chat. Substitute the institution’s approved public host for `<PUBLIC_HOST>`.

## Environment template

Use the placeholder-only [`production environment example`](../../.env.production.example) as the variable-name reference. It includes environment mode, image tag, secret key, MongoDB URI, trusted host, session settings, Redis, proxy count, and password-reset mail settings. The staging example follows the same contract with separate database and hostname placeholders.

Required production values include `APP_ENV=production`, `FLASK_ENV=production`, `FLASK_DEBUG=false`, `SECRET_KEY`, authenticated TLS `MONGO_URI` with a dedicated database name, explicit `TRUSTED_HOSTS`, secure/HttpOnly session cookies, shared Redis, `MAIL_DEFAULT_SENDER`, and an HTTPS `PASSWORD_RESET_BASE_URL`. Configure either SMTP with TLS or Resend with its API key in the secret manager. `PASSWORD_RESET_EXPOSE_LINK` must remain false. Never copy local `.env` values into production.

## Database setup and migrations

Create separate staging and production databases and least-privilege application users. Configure MongoDB TLS and network allowlisting. The application needs its normal collection permissions and permission to create declared indexes; backup access should use a separate identity. Do not point a production service at a demo or development database.

Startup creates indexes; it does not automatically run data migrations. Review the migration impact and complete a verified backup before any migration:

- Legacy course rosters: see the explicit, opt-in command in [DEPLOYMENT.md](DEPLOYMENT.md). It writes enrollment records.
- Legacy plaintext password fields: `scripts/migrate_legacy_passwords.py` is dry-run by default. Review its count-only output against the confirmed database and backup before any separately authorized `--apply`.
- Admin provisioning: production startup does not bootstrap an admin. `scripts/seed_admin.py` can create an admin and writes to MongoDB. An authorized operator may invoke it only after confirming the target environment/database, canonical email, and secret inputs through the secret manager, with `ALLOW_ADMIN_SEED=true` for that invocation. Do not use `scripts/reset_admin_user.py` for routine provisioning; it overwrites the configured account password. Never run either script against production without explicit client authorization and an approved change record.

Provisioning command shape (all required values must be supplied through the protected execution environment, not typed into this command):

```bash
ALLOW_ADMIN_SEED=true python scripts/seed_admin.py
```

After provisioning, verify the account’s role/status and perform a login test in the approved environment. Do not put passwords, hashes, reset tokens, or database URIs in evidence.

## Backup, restore, and ownership

Use [OPERATIONS.md](OPERATIONS.md) to run `scripts/backup_mongodb.py` against an explicitly confirmed target. Backups contain sensitive institutional data; encrypt them, restrict access, store an off-host copy, and define retention with the client. Follow [BACKUP_RESTORE.md](BACKUP_RESTORE.md) for restore drills to an isolated disposable database. Never use a production URI as a restore target or `--drop` during a release drill.

The client owns scheduled backups, monitoring/alerts, restore testing, retention, database availability, secret rotation, mail sender reputation, certificate renewal, access reviews, and incident response. The repository does not provide a managed SaaS control plane or an uptime/SLA commitment.

## Features and limitations

The documented application scope includes role-based admin, teacher, student, and analyst workflows; education data ingestion; dashboards and reports; notifications and support; and ML training/prediction paths for performance, dropout, demand, trends, and anomalies. See the [user guide](../guides/USER_GUIDE.md) for workflow detail.

Operational limits to disclose:

- The institution supplies and operates MongoDB, Redis, HTTPS, email, and any HDFS/WebHDFS infrastructure.
- Kafka and Spark are not bundled services. Local streaming fallback does not demonstrate a production Kafka deployment.
- Models need suitable institutional data and successful training. Model quality, fairness, and predictive accuracy are not certified by this handover; the client must validate them before decisions affecting students.
- Backup scheduling, encryption-at-rest policy, monitoring, alerting, support, and availability targets are deployment responsibilities.
- Browser, production email, HTTPS/proxy, multi-worker Redis, live database, backup, and restore checks remain unverified until evidence is recorded in the release gate.

## Troubleshooting

- **Application exits during startup:** check the named missing/invalid production settings in the sanitized startup error. Confirm production environment flags, secret injection, trusted host, MongoDB TLS URI, secure cookies, Redis URI, and complete mail settings. Do not share environment dumps.
- **`/health` passes but `/health/ready` fails:** investigate MongoDB DNS/network allowlisting, TLS certificate validation, database user permissions, and database availability. Do not expose the URI in diagnostic output.
- **Password reset does not arrive:** verify provider credentials in the secret manager, sender-domain verification, SMTP TLS if applicable, provider delivery/bounce logs, and HTTPS reset base URL. Keep reset tokens and provider secrets private.
- **Login fails:** verify the canonical email and account role/status through the institution’s approved account process. Do not seed/reset until the target database has been confirmed and a change is authorized.
- **Rate-limit errors or inconsistent throttling:** confirm the app uses the shared Redis service and all workers reach the same backend.
- **HDFS upload unavailable:** check whether HDFS is enabled and that the WebHDFS endpoint/allowlist is configured. Local fallback is expected when it is disabled.
- **Prediction unavailable:** verify a compatible model was trained and its artifacts/metrics are present; predictions are not guaranteed before training or without suitable inputs.

Inspect logs only in the protected operations environment. Redact before sharing; never send `.env`, full Compose interpolation output, database URIs, access tokens, passwords, or student records.

## Client ownership and deployment checklist

- [ ] Approve the exact source-file manifest, version/tag, and image digest.
- [ ] Own and rotate secret-manager entries; verify exposed credentials are revoked without recording secret values.
- [ ] Confirm canonical admin email and provision the initial admin through an approved change.
- [ ] Create isolated staging/production databases, users, network rules, and a documented migration plan.
- [ ] Configure and verify mail delivery, public DNS, HTTPS/HSTS, reverse proxy, and shared Redis.
- [ ] Complete the isolated staging browser demo and record sanitized evidence.
- [ ] Complete an encrypted backup and isolated restore drill; set schedule and retention.
- [ ] Assign operators for monitoring, access reviews, incident response, upgrades, and support.
- [ ] Confirm institution-specific privacy, security, data retention, and model governance requirements before loading student records.
- [ ] Confirm every mandatory release-gate check is PASS before production deployment or client acceptance.

## Current handover state

The package documentation is prepared, but this repository is not currently cleared for production handover. See [RELEASE_GATE.md](RELEASE_GATE.md) for evidence and blockers. Do not describe the product as production-ready until the gate is READY FOR HANDOVER.
