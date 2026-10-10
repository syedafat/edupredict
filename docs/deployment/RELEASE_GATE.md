# EduPredict Production Release Gate

**Current gate: BLOCKED**  
**Release version: not assigned**  
**Decision rule: fail closed.** The release is READY FOR HANDOVER only when every mandatory check below is marked `PASS` and has reviewable evidence for the same release version. `FAIL`, `BLOCKED`, blank, or untested checks keep the release blocked. A documented external dependency is still a blocker; documenting it does not pass the check.

This checklist is the release record. Update a status only after performing the check against the exact candidate build and recording evidence that does not contain credentials, personal student data, or other secrets. Never infer a pass from code presence, tests that mock an integration, or an earlier release.

## Mandatory checks

| ID | Check | Status | Evidence / exact blocker |
|---|---|---|---|
| 1a | Exposed MongoDB credential rotated; new credential confirmed and exposed credential revoked | **BLOCKED** | On 2026-10-10 the user reported that an authorized operator completed rotation. No non-secret provider change reference, revocation confirmation, or secret-version evidence was supplied in this workspace, and no provider session is available to verify it. No connection attempt was made. Required: record an auditable non-secret provider change reference and confirmation that the replacement is active and the exposed credential revoked. |
| 1b | Exposed Flask `SECRET_KEY` replaced in the deployment secret store | **BLOCKED** | On 2026-10-10 the user reported that an authorized operator completed rotation. No secret-manager version/change reference or deployment confirmation was supplied in this workspace, and no secret-manager session is available to verify it. No key was read, generated, or changed. Required: record the non-secret version/change reference and confirmation that the deployment uses the replacement. |
| 1c | Exposed admin password changed for the canonical account | **BLOCKED** | On 2026-10-10 the user reported that an authorized operator completed rotation. No non-secret account-change confirmation was supplied, and the canonical admin email remains unconfirmed (the earlier `.env` and browser values differed). No account was queried or modified. Required: record an approved account-change confirmation and confirm the canonical email, without sending any password. |
| 2a | Authorized target database confirmed and connectivity verified safely | **BLOCKED** | The local `.env` was inspected in the prior audit and points to an authenticated TLS SRV URI with database name `edupredict`; connectivity was not tested. Its credential is compromised. An authorized operator must first provide a rotated credential and confirm the intended environment/database. Then record a read-only connectivity check against that target. No remote database was contacted. |
| 2b | Canonical admin account and login identifier verified safely | **BLOCKED** | The `.env` admin email (`admin@example.com`) differed from the browser login email (`admin@edupredict.com`). The account in the target database was not queried, and live login was not attempted. The client must identify the canonical email; an authorized operator must verify the account’s role/status and login after credential rotation. Do not reset or seed an account as part of verification. |
| 3 | Full existing test suite passes and Python compilation succeeds | **PASS** | Fresh local run on 2026-10-10: with `MONGO_URI` explicitly overridden to `mongodb://127.0.0.1:27017/edupredict_test?serverSelectionTimeoutMS=100&connectTimeoutMS=100`, `python -m pytest -q --tb=short` completed **117 passed in 27.19s**; `python -m compileall -q .` exited 0. These tests do not verify live services; rerun against the owner-approved versioned candidate. |
| 4a | `requirements-prod.lock` generated for the production build platform and reviewed | **BLOCKED** | Static inspection confirms the generator requires Linux and Python 3.12 and calls `pip-compile --generate-hashes`. This host is Windows/Python 3.12; `pip-compile`, `pip-tools`, WSL, and `requirements-prod.lock` are absent. No packages were installed or downloaded. Required: run the documented workflow in supported Linux/Python 3.12 CI, review pinned versions/hashes, and record the lock hash/commit. |
| 4b | Docker image builds successfully from the reviewed release files | **BLOCKED** | Static YAML parse passed for Compose (`web` and `redis` services; web publication is loopback-only), and Dockerfile references the required lock. Docker is not installed and the lock is absent, so no image build was possible. Required: build the versioned image in an approved Docker environment after 4a; record the image digest and build result. |
| 5 | Real browser demo: admin login, dashboard, authorized role workflow, one ML prediction, logout | **BLOCKED** | Reviewed `docs/guides/DEMO_GUIDE.md` and the manual QA checklist; no real browser demo was run. Use the checklist below against an isolated staging/demo target only, after checks 1–2 are cleared. Record the candidate version, browser, synthetic fixture, and results; do not use production student data. |
| 6a | Production email delivery verified | **BLOCKED** | Production configuration requires mail provider settings. The production example selects Resend but leaves its API key empty; no provider delivery test was run. Required: inject the approved provider credential through the deployment secret manager and verify a delivered reset email without recording the token or credential. |
| 6b | Public HTTPS, proxy behavior, secure cookies, and HSTS verified | **BLOCKED** | Static review confirms HTTPS is terminated by the external proxy; deployment settings require secure cookies and trusted hosts. No hostname, certificate, proxy, or live response was tested. Required: verify redirect, certificate, forwarded scheme, cookie flags, and HSTS at the actual staging/production edge. |
| 6c | Shared production Redis rate-limit backend verified | **BLOCKED** | Static Compose YAML defines a private Redis service and points the app limiter to it; YAML parsed successfully. No Redis service or multi-worker deployment was run. Required: verify shared rate limiting across deployed workers in the target environment. |
| 6d | Production backup completed and protected | **BLOCKED** | Static review confirms `scripts/backup_mongodb.py` uses `mongodump` through a temporary protected tools config and suppresses tool details on failure. No production backup was run. Required: authorized operator backs up the confirmed target, then verifies encryption/access controls, off-host copy, and retention evidence. |
| 6e | Restore procedure successfully tested against an isolated database | **BLOCKED** | `BACKUP_RESTORE.md` documents an isolated BSON restore drill. Corrected `OPERATIONS.md` to point to that procedure and remove its unsafe direct restore to `$MONGO_URI`. No restore was run. Required: authorized operator completes the drill against a disposable target and verifies collections/indexes; do not use `--drop` or production. |
| 7 | Release files reviewed and committed with a version identifier | **BLOCKED** | Read-only workspace review found 72 tracked paths modified/deleted plus untracked files. Potential release candidates include core Flask/config/ML/routes/services/templates/tests; Docker and Compose files plus env examples; requirements and frontend lock/build assets; admin/migration/backup scripts; WSGI entrypoint; and `docs/`. Root guide files are deleted while a replacement `docs/` tree is untracked. No approved file manifest or version exists. `.env` is ignored and not tracked; no commit was made. Required: owner reviews the full diff, confirms the intended file manifest and doc moves, excludes local secrets/data, then authorizes a versioned commit. |

## Browser demo checklist (check 5)

Run only against an isolated staging/demo database with synthetic accounts/data and a known candidate build. Stop on a failed step; retain only non-secret evidence.

- [ ] Record build/tag, browser/version, target environment, and synthetic fixture identifier.
- [ ] Sign in with the confirmed canonical admin account; verify redirect and admin dashboard access.
- [ ] Use admin workflow to create/approve a synthetic teacher, then sign in as that teacher and verify only authorized role workflow/data is available.
- [ ] Run one supported ML prediction for a synthetic record; verify result and persisted demo result in the UI.
- [ ] Log out; verify protected pages require authentication and the session is cleared.
- [ ] Save pass/fail and sanitized screenshots/log references; do not include credentials, reset tokens, database URIs, or student data.

## Proposed release manifest — awaiting owner approval

This is a review proposal from the current read-only Git status, not an approved staging list. Do not stage or commit these files until the release owner approves the exact paths and diffs.

### Required application and security fixes (proposed)

- `app.py`, `config.py`, `extensions.py`, `utils/decorators.py`
- `routes/auth_routes.py`, `routes/monitoring_routes.py`, `services/email_service.py`, `services/audit_service.py`
- `scripts/backup_mongodb.py`

These paths align with production configuration validation, authentication/session controls, readiness checks, mail/reset delivery, audit handling, and protected backup behavior. Related tests belong in the test group below. Large route changes outside auth/monitoring include mixed product behavior and need owner review before inclusion.

### Deployment and operations files (proposed)

- `.dockerignore`, `.env.example`, `.env.production.example`, `.env.staging.example`, `.gitignore`
- `Dockerfile`, `docker-compose.yml`, `requirements.txt`, `requirements-dev.txt`, `scripts/generate_requirements_lock.py`, `wsgi.py`
- `package.json`, `package-lock.json`, `tailwind.config.cjs`, `scripts/build_frontend_assets.mjs`, `static/**`
- `docs/deployment/**`

The production Python lock is still missing. Review bundled frontend/vendor assets and licenses before approving them for release.

### Tests and documentation (proposed)

- `tests/**`
- `docs/**`, `README.md`
- Root guide deletions (`ARCHITECTURE.md`, `DATA_LINEAGE_AUDIT.md`, `DEMO_GUIDE.md`, `DEVELOPER_GUIDE.md`, `OPERATIONS.md`, `REQUIREMENTS_TRACEABILITY.md`, `USER_GUIDE.md`) paired with the untracked replacements under `docs/`

Confirm the root-to-`docs/` moves preserve every referenced file and are intentional. Do not treat the test or documentation files as release approval by themselves.

### Unrelated or uncertain pending owner review

- Broad academic/product workflow changes across `ml/**`, `routes/**` beyond the auth/monitoring candidates above, `services/**` beyond the named security/operations candidates, and `templates/**`
- New department/subject/roster/static-data migration and seed utilities: `scripts/migrate_departments.py`, `scripts/migrate_legacy_rosters.py`, `scripts/migrate_static_to_dynamic.py`, `scripts/migrate_student_departments.py`, `scripts/seed_admin.py`, `seed_data.py`, `scripts/seed_subjects.py`, `scripts/verify_admin_login.py`, `scripts/verify_subjects_feature.py`, `scripts/reset_admin_user.py`, `scripts/migrate_legacy_passwords.py`
- New/changed feature tests whose scope does not match a confirmed release requirement

`routes/admin_routes.py`, `routes/data_routes.py`, `routes/ml_routes.py`, `routes/student_routes.py`, `routes/support_routes.py`, and `routes/teacher_routes.py` have substantial mixed changes; classify them hunk-by-hunk with the owner rather than assuming the entire files belong in the required security set. This manifest does not stage, discard, or commit anything.

## Linux/Python 3.12 lock and image commands

Run only in approved Linux/Python 3.12 release CI, after the owner approves the source tree. The virtual environment is outside the Docker build context. These commands install the repository's declared tools in CI; they were not run in this Windows workspace.

```bash
python3.12 -m venv /tmp/edupredict-release-venv
/tmp/edupredict-release-venv/bin/python -m pip install -r requirements-dev.txt
/tmp/edupredict-release-venv/bin/python scripts/generate_requirements_lock.py
sha256sum requirements-prod.lock
docker build --tag edupredict:<release-tag> .
docker image inspect --format='{{.Id}}' edupredict:<release-tag>
```

Replace `<release-tag>` with the owner-approved version. Review and commit the generated lock only with the approved manifest. Record the lock SHA-256, build result, and image ID. Do not use a populated production env file for image building.

## Independent local review (2026-10-10)

- **Dependency lock workflow:** `scripts/generate_requirements_lock.py` requires Linux/Python 3.12 and invokes `pip-compile --generate-hashes`. This Windows host has Python 3.12 but no WSL, `pip-tools`, or `pip-compile`; `requirements-prod.lock` is absent. No packages were installed/downloaded and no lock was generated. The documented handoff is to run the generator in supported Linux/Python 3.12 CI, review exact pins/hashes, and retain its commit/hash evidence.
- **Docker/Compose static check:** PyYAML parsed `docker-compose.yml`; it declares `web` and `redis`, publishes the app only on loopback, and the Dockerfile installs the required lock with hash checking. Docker is unavailable and the lock is missing, so no image build occurred.
- **Health checks:** Code review confirms `/health` is a process liveness endpoint independent of external services and `/health/ready` performs a MongoDB ping. No live readiness request was made.
- **Production integrations:** Config requires secure cookies, explicit trusted hosts, shared Redis, and complete mail/reset settings. The production example has an empty Resend API key. HTTPS is provided by the external reverse proxy. These code/config checks do not verify delivery, network reachability, TLS, or multi-worker behavior.
- **Browser/demo:** Reviewed the demonstration guide and manual QA checklist. Added the isolated synthetic-data browser sequence above. No browser workflow was run.
- **Backup/restore docs:** Reviewed backup utility and restore guidance. Corrected `OPERATIONS.md` so it no longer suggests restoring directly to the app URI. No backup/restore operation was run.
- **Workspace/release scope:** `git diff --stat` reports 72 tracked paths changed/deleted; untracked application, test, deployment, script, asset, and documentation files are also present. `.env` is ignored and not tracked. These paths are candidates for owner review, not an approved commit set. No commit was made.
- **Fresh safe test:** `MONGO_URI` was overridden to localhost and `python -m pytest -q --tb=short tests\test_production_safety.py` completed with **33 passed in 17.42s**. The full suite result (`117 passed`) and compilation result remain from the earlier audit; neither was rerun in this continuation.

## Evidence record for the candidate

## Client handover package

**Documentation status: PASS (package assembled; not production approval).** `docs/deployment/CLIENT_HANDOVER.md` provides the install/deploy sequence, placeholder environment templates, guarded admin provisioning, database/index/migration notes, backup/restore procedure links, troubleshooting, feature scope and limitations, and client ownership checklist. The linked repo guides are part of the package. This documentation does not clear any blocked runtime or infrastructure check.

## Fresh local checks (2026-10-10)

- `MONGO_URI` was overridden to `mongodb://127.0.0.1:27017/edupredict_test?serverSelectionTimeoutMS=100&connectTimeoutMS=100`; `python -m pytest -q --tb=short`: **117 passed in 22.33s**.
- `python -m compileall -q .`: **PASS**, exit code 0.
- `git -c safe.directory='C:/Users/user/Downloads/EduPredict_final_complete/EduPredict_full_fixed' status --short`: completed read-only; reports broad modified/deleted/untracked work as summarized under check 7. No files were staged or committed.
- Same Git safe-directory override with `diff --check`: **FAIL** due trailing whitespace at `routes/admin_routes.py:770`; this is in an existing application diff and was not altered as part of handover documentation.
- A direct Git invocation without the per-command safe-directory override was rejected by Git's dubious-ownership safeguard. No global Git trust setting was changed.
- The handover document was added at `docs/deployment/CLIENT_HANDOVER.md`. Its status is documentary only; production DB, browser, email, HTTPS, Redis, backup/restore, lock, Docker, and versioned release checks remain blocked as applicable above.

## Final handover closure review (2026-10-10)

- **PASS ? local automated checks:** `MONGO_URI` was overridden to the loopback test URI recorded in check 3. The full existing suite returned **117 passed in 27.19s**; `python -m compileall -q .` exited 0. The test result is local and does not exercise external services.
- **PASS ? handover documentation:** `docs/deployment/CLIENT_HANDOVER.md` and this release gate are present. A relative Markdown link check over both files passed. The guide covers install/setup, deployment, environment templates, admin provisioning safeguards, database/migration notes, backups/restores, known limitations, troubleshooting, and client ownership.
- **BLOCKED ? Linux lock/image:** `requirements-prod.lock` is absent; current Windows environment reports `docker`, `wsl`, `python3.12`, and `pip-compile` unavailable. Linux lock generation and image build were not tested here.
- **BLOCKED ? security and target account:** no non-secret rotation references or canonical admin confirmation supplied; no remote database/account check was performed.
- **BLOCKED ? staging and operations:** real browser demo, production email, public HTTPS, shared Redis, protected backup, and isolated restore were not tested; target infrastructure/evidence is unavailable.
- **BLOCKED ? release approval:** source manifest/version/commit are not approved. Existing work remains untouched and uncommitted.

### Assigned remaining actions

1. **Client security/database administrators:** provide non-secret references confirming MongoDB credential replacement and old-credential revocation, deployment `SECRET_KEY` replacement, admin password change, and canonical admin email. Identify the exact target database and authorize a read-only connectivity/account check.
2. **Release owner and Linux CI operator:** approve exact release paths/version, run the Linux/Python 3.12 lock generation and review; build the Docker image and record lock hash and image digest.
3. **Client staging/operations owners:** run the synthetic-data browser checklist; verify email, HTTPS/proxy, shared Redis, backup protection/retention, and an isolated restore drill. Attach sanitized evidence.
4. **Release owner:** review all remaining workspace changes and authorize a versioned release commit. No staging or commit has been done.

## Safe credential rotation procedure

These actions require the client’s database, secret-management, and account administrators. They were not performed from this workspace:

1. In the database provider, create a replacement application credential scoped only to the explicitly authorized EduPredict database. Update `MONGO_URI` in the approved deployment secret manager with the replacement value. After an authorized operator confirms the application can connect, revoke the exposed database credential. Do not put the URI in a command, ticket, screenshot, or log.
2. Create a new random Flask key directly in the approved secret manager and replace the deployment `SECRET_KEY`. Expect existing sessions to become invalid. Do not print, paste, or commit the key.
3. Have the client confirm the canonical admin email and environment. An authorized administrator changes that account’s password through the approved account-management process. Do not run the seed/reset scripts as a substitute for this verification; those scripts write to MongoDB.
4. Attach only non-secret evidence (provider change reference, secret version identifier, account-change confirmation, and date) to checks 1a–1c. Then proceed to the read-only database and account verification in checks 2a–2b.

Complete only for the release candidate under review:

| Field | Value |
|---|---|
| Version / tag | Not assigned |
| Source commit | Not assigned |
| Container image digest | Not built |
| Test run reference | 2026-10-10 local workspace: `python -m pytest -q --tb=short` 117 passed in 27.19s with loopback test URI; `python -m compileall -q .` exit 0; rerun for approved candidate |
| Browser demo record | Checklist prepared; not run |
| Reviewer and date | Local review 2026-10-10; release approver not recorded |
| Gate decision | **BLOCKED** |

## Required actions to unblock this candidate

1. Provide non-secret provider/secret-manager/account change references confirming checks 1a–1c and the canonical admin email; no credential values.
2. Explicitly authorize a read-only production database check and provide the exact target environment/database. Then verify connectivity and canonical admin role/status without writes or exposing account secrets.
3. Re-run the full tests and compilation for the candidate release.
4. Generate and review `requirements-prod.lock`, then build the Docker image and record its digest.
5. Run and record the real browser demo against the candidate deployment.
6. Configure and verify production email, HTTPS/proxy, and shared Redis. Complete a protected backup and isolated restore drill; attach evidence for each.
7. Have the owner review/select the intended release files, exclude local secrets/data, authorize the versioned commit, and update this checklist with candidate-specific evidence.

When all mandatory rows are `PASS` with candidate-specific evidence, update the header to **READY FOR HANDOVER** and record the approving reviewer and date. Otherwise, leave the gate **BLOCKED**.

## Local capability recheck (2026-10-10)

- Python 3.12.0 and pip are present on the Windows workstation.
- `pip-tools`/`pip-compile`, Docker, Docker Compose, and WSL are unavailable. The production lock generator explicitly requires Linux and Python 3.12, so no lock was generated and no image or container test was run.
- A read-only Git status check (using a per-command `safe.directory` override) confirms extensive modified, deleted, and untracked application and documentation files. Nothing was staged or committed; no release manifest or version is approved.
- No cloud, database, secret manager, browser staging target, mail provider, or HTTPS endpoint was accessed. No credentials were rotated and no deployment was performed.
- Result: checks 4a, 4b, and 7 remain **BLOCKED**. This environment recheck does not change any gate status or establish production readiness.
