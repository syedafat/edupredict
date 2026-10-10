# EduPredict Manual QA Checklist

Mark a check PASS only after testing it in the named target environment. Record build/version, browser, role/account fixture, date, and result in the release QA log. Do not put real credentials or student data in screenshots or logs.

## Status key

- `NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED`: not performed by the local automated suite.
- Record `PASS` or `FAIL` only with observed evidence.

## Authentication and sessions

- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Student and teacher registration, password policy, duplicate email behavior, and approval status.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Valid login for each role; invalid login gives a generic response.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Logout is POST-only and clears the session.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Password reset delivery, token expiration, one-time use, and changed-password login.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Expired session and suspended/deleted account lose access.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: CSRF missing/invalid token rejects state-changing forms.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Login, registration, reset, and expensive operations enforce rate limits.

## Student

- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Dashboard, profile, courses, attendance, marks/grades, assignments, and own prediction data.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Create and respond to own support ticket.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Another student's records and ticket cannot be viewed or changed by changing IDs.

## Teacher

- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Dashboard, active assigned courses, enrolled students, attendance, grades, assignments, submissions, and predictions.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Writes reject a student/course/subject outside the teacher's active scope.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Teacher support ticket visibility and response scope.

## Analyst

- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Authorized analytics, students/courses, predictions, and support ticket scope.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Out-of-scope student/course/ticket IDs are rejected before processing or writes.

## Admin

- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Dashboard, users, departments/courses/subjects, datasets, reports, and support management.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Generate/list/download report; traversal and invalid report identifiers do not disclose files.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Admin-only endpoints reject unauthenticated and non-admin users server-side.

## Files and uploads

- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Valid supported dataset upload processes and downloads only in authorized scope.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Oversized, invalid extension, malformed content, and traversal-style filenames are rejected or safely normalized.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Unauthorized upload does not create files or database records.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Assignment/submission/report downloads cannot escape their configured roots or ownership scope.

## Browser and security configuration

- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: CSP permits required UI assets and blocks disallowed content in supported browsers; inspect browser console.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: HTTPS, Secure/HttpOnly/SameSite cookies, HSTS at the TLS edge, and proxy behavior.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Rate limits work across all production workers with shared backend storage.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Production errors do not disclose stack traces, internal paths, credentials, or private records.

## Integrations and operations

- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: MongoDB authenticated TLS connection, certificate validation, indexes, backup, and restore.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Email/password reset provider, delivery, bounce handling, and no reset-link exposure in production.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Hadoop/WebHDFS host allowlist, auth/TLS requirements, timeout, upload, and unavailable-service behavior.
- [ ] NOT VERIFIED — MANUAL/ENVIRONMENT REQUIRED: Production startup, health monitoring, logs, persistent uploads/models, and deployment rollback.
