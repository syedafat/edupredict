# WP-02 RBAC & IDOR Security Audit Report

**Project:** EduPredict Flask Application  
**Audit Phase:** WP-02 Authorization, RBAC & IDOR Remediation (Read-Only Audit)  
**Execution Date:** 2026-09-24  
**Audit Status:** COMPLETE — READ-ONLY BASELINE AUDIT  

---

## 1. Executive Summary

This report establishes the complete evidence-based authorization, Role-Based Access Control (RBAC), and Insecure Direct Object Reference (IDOR / BOLA) baseline for the EduPredict application.

The application implements a central `role_required(*allowed_roles)` decorator in `utils/decorators.py` and an administrative decorator `admin_required` in `routes/admin_routes.py`. These decorators validate the session, verify account status against the live MongoDB `users` collection, ensure user accounts are not deactivated (`suspended` or `deleted`), and enforce role constraints.

However, several object-level access control (IDOR / BOLA) vulnerabilities and authorization consistency gaps were identified:
1. **Unscoped Stream Event Ingestion (`POST /data/stream`):** Teachers can submit stream events for students outside their assigned courses.
2. **Unscoped Analyst Model Scoring (`POST /ml/predict/<model_type>`):** Analysts can generate prediction records and trigger automated alerts for any student without enrollment scoping.
3. **Analyst Access to Institutional Support Tickets (`GET /support/tickets`, `POST /support/ticket/<ticket_id>/respond`):** Data analysts have unrestricted read and status-change access to all support tickets across the platform.
4. **Student Inability to Respond to Own Tickets (`POST /support/ticket/<ticket_id>/respond`):** Students are blocked from replying to their own support tickets.
5. **Path Traversal Risk on Report Download (`GET /admin/reports/<report_id>/download`):** Report downloads do not enforce `commonpath` verification against the designated reports directory.
6. **Inconsistent Non-Admin Access Handling:** `admin_required` redirects non-admins with a 302 rather than returning an HTTP 403 Forbidden, whereas `role_required` properly aborts with 403.
7. **Role-Template Mismatch (`GET /ml/predictions`):** Students accessing `/ml/predictions` are rendered the administrative template containing links to admin-only views.

Zero source files or database records were modified during this read-only audit.

---

## 2. Scope

The audit covered all 68 route endpoints across 10 Flask blueprints and the application root:
- `routes/auth_routes.py` (Authentication & Session)
- `routes/admin_routes.py` (Platform Administration, Users, Courses, Subjects, Departments, Reports)
- `routes/teacher_routes.py` (Instructor Dashboard, Attendance, Grading, Assignments, Submissions)
- `routes/student_routes.py` (Student Dashboard, Attendance, Grades, Submissions, Profile)
- `routes/analyst_routes.py` (Data Analytics & Operational Metrics)
- `routes/ml_routes.py` (Machine Learning Training, Predictions, Model Registry)
- `routes/data_routes.py` (Dataset Ingestion, Batch Processing, Streaming Events, HDFS)
- `routes/support_routes.py` (Support Ticket Lifecycle)
- `routes/notification_routes.py` (Alerts, Announcements & Institutional Broadcasts)
- `routes/monitoring_routes.py` (System Health & Performance Metrics)
- `app.py` (Root redirections, error handlers, and security headers)
- `utils/decorators.py` (RBAC enforcement primitives)

---

## 3. Methodology

1. **AST & Static Route Enumeration:** Parsed the Abstract Syntax Tree (AST) of every route module to extract route patterns, HTTP methods, decorator chains, and function signatures.
2. **Data-Flow & Query Tracing:** Traced database queries (`mongo.db.*`), session parameters (`session['user_id']`, `session['role']`), and user-controlled inputs (`request.args`, `request.form`, `request.json`).
3. **Ownership & Scope Analysis:** Evaluated whether database queries enforce object ownership (e.g. `user_id == session['user_id']`) or relational enrollment authorization (e.g. `student_id` in teacher's course roster).
4. **Boundary Testing Scenarios:** Modeled cross-role privilege escalation (e.g., student accessing teacher data, teacher accessing other courses, analyst accessing support/admin objects).

---

## 4. Complete Route Inventory

The application defines 68 total endpoints:

| Endpoint | Method | Path | Blueprint | Decorators | Scope / Object Parameters |
|---|---|---|---|---|---|
| `app.index` | GET | `/` | root | None | None |
| `app.login_redirect` | GET, POST | `/login` | root | None | None |
| `auth.login` | GET, POST | `/auth/login` | auth | limiter (5/min) | None |
| `auth.register` | GET, POST | `/auth/register` | auth | None | None |
| `auth.teacher_register` | GET, POST | `/auth/teacher/register` | auth | None | None |
| `auth.forgot_password` | GET, POST | `/auth/forgot-password` | auth | limiter (5/min) | None |
| `auth.reset_password` | GET, POST | `/auth/reset-password` | auth | None | `token` |
| `auth.logout` | POST | `/auth/logout` | auth | None | None |
| `admin.dashboard` | GET | `/admin/dashboard` | admin | admin_required | None |
| `admin.dashboard_data` | GET | `/admin/api/dashboard` | admin | admin_required | None |
| `admin.anomalies` | GET | `/admin/anomalies` | admin | admin_required | None |
| `admin.datasets` | GET | `/admin/datasets` | admin | admin_required | None |
| `admin.download_dataset` | GET | `/admin/datasets/<dataset_id>/download` | admin | admin_required | `dataset_id` |
| `admin.ml_models` | GET | `/admin/ml-models` | admin | admin_required | None |
| `admin.retrain_models` | POST | `/admin/ml-models/retrain` | admin | admin_required | None |
| `admin.students` | GET | `/admin/students` | admin | admin_required | None |
| `admin.teachers` | GET | `/admin/teachers` | admin | admin_required | None |
| `admin.update_teacher_status` | POST | `/admin/teachers/<teacher_id>/status` | admin | admin_required | `teacher_id` |
| `admin.teacher_attendance` | GET, POST | `/admin/teacher-attendance` | admin | admin_required | None |
| `admin.system_logs` | GET | `/admin/system-logs` | admin | admin_required | None |
| `admin.settings` | GET, POST | `/admin/settings` | admin | admin_required | None |
| `admin.upload_data` | GET, POST | `/admin/upload-data` | admin | admin_required | None |
| `admin.users` | GET | `/admin/users` | admin | admin_required | None |
| `admin.add_user` | GET, POST | `/admin/add-user` | admin | admin_required | None |
| `admin.add_teacher` | GET, POST | `/admin/add-teacher` | admin | admin_required | None |
| `admin.edit_user` | GET, POST | `/admin/edit-user` | admin | admin_required | `id` / `user_id` |
| `admin.delete_user` | POST | `/admin/delete-user/<user_id>` | admin | admin_required | `user_id` |
| `admin.courses` | GET | `/admin/courses` | admin | admin_required | None |
| `admin.create_course` | GET, POST | `/admin/courses/new` | admin | admin_required | None |
| `admin.edit_course` | GET, POST | `/admin/courses/<course_id>/edit` | admin | admin_required | `course_id` |
| `admin.delete_course` | POST | `/admin/courses/<course_id>/delete` | admin | admin_required | `course_id` |
| `admin.predictions` | GET | `/admin/predictions` | admin | admin_required | None |
| `admin.reports` | GET | `/admin/reports` | admin | admin_required | None |
| `admin.generate_report` | POST | `/admin/reports/generate` | admin | admin_required | None |
| `admin.download_report` | GET | `/admin/reports/<report_id>/download` | admin | admin_required | `report_id` |
| `admin.export_logs` | GET | `/admin/system-logs/export` | admin | admin_required | None |
| `admin.support` | GET | `/admin/support` | admin | admin_required | None |
| `admin.departments` | GET | `/admin/departments` | admin | admin_required | None |
| `admin.new_department` | GET, POST | `/admin/departments/new` | admin | admin_required | None |
| `admin.edit_department` | GET, POST | `/admin/departments/<department_id>/edit` | admin | admin_required | `department_id` |
| `admin.delete_department` | POST | `/admin/departments/<department_id>/delete` | admin | admin_required | `department_id` |
| `admin.migrate_course_departments` | POST | `/admin/departments/migrate` | admin | admin_required | None |
| `admin.subjects` | GET | `/admin/subjects` | admin | admin_required | None |
| `admin.new_subject` | GET, POST | `/admin/subjects/new` | admin | admin_required | None |
| `admin.edit_subject` | GET, POST | `/admin/subjects/<subject_id>/edit` | admin | admin_required | `subject_id` |
| `admin.delete_subject` | POST | `/admin/subjects/<subject_id>/delete` | admin | admin_required | `subject_id` |
| `teacher.dashboard` | GET | `/teacher/dashboard` | teacher | role_required('teacher') | None |
| `teacher.dashboard_data` | GET | `/teacher/api/dashboard` | teacher | role_required('teacher') | None |
| `teacher.student_performance` | GET | `/teacher/students` | teacher | role_required('teacher') | None |
| `teacher.courses` | GET | `/teacher/courses` | teacher | role_required('teacher') | None |
| `teacher.record_attendance` | POST | `/teacher/attendance` | teacher | role_required('teacher') | `course_id`, `student_id`, `subject_id` |
| `teacher.record_grade` | POST | `/teacher/grades` | teacher | role_required('teacher') | `course_id`, `student_id`, `subject_id` |
| `teacher.create_assignment` | POST | `/teacher/assignments` | teacher | role_required('teacher') | `course_id`, `subject_id` |
| `teacher.submissions` | GET | `/teacher/submissions` | teacher | role_required('teacher') | None |
| `teacher.download_submission_file` | GET | `/teacher/submissions/<submission_id>/download` | teacher | role_required('teacher') | `submission_id` |
| `teacher.grade_submission` | POST | `/teacher/submissions/<submission_id>/grade` | teacher | role_required('teacher') | `submission_id` |
| `teacher.predict_risk` | POST | `/teacher/predict-risk` | teacher | role_required('teacher') | `student_id`, `course_id` |
| `teacher.predictions` | GET | `/teacher/predictions` | teacher | role_required('teacher') | None |
| `student.dashboard` | GET | `/student/dashboard` | student | role_required('student') | None |
| `student.dashboard_data` | GET | `/student/api/dashboard` | student | role_required('student') | None |
| `student.grades` | GET | `/student/grades` | student | role_required('student') | None |
| `student.attendance` | GET | `/student/attendance` | student | role_required('student') | None |
| `student.courses` | GET | `/student/courses` | student | role_required('student') | None |
| `student.notifications` | GET | `/student/notifications` | student | role_required('student') | None |
| `student.predictions` | GET | `/student/predictions` | student | role_required('student') | None |
| `student.assignments` | GET | `/student/assignments` | student | role_required('student') | None |
| `student.submit_assignment` | POST | `/student/assignments/<assignment_id>/submit` | student | role_required('student') | `assignment_id` |
| `student.download_submission` | GET | `/student/assignments/<assignment_id>/download` | student | role_required('student') | `assignment_id` |
| `student.profile` | GET | `/student/profile` | student | role_required('student') | None |
| `student.support` | GET | `/student/support` | student | role_required('student') | None |
| `analyst.dashboard` | GET | `/analyst/dashboard` | analyst | role_required('analyst', 'admin') | None |
| `analyst.data` | GET | `/analyst/data` | analyst | role_required('analyst', 'admin') | None |
| `ml.view_predictions` | GET | `/ml/predictions` | ml | role_required('admin', 'teacher', 'student') | None |
| `ml.run_model` | POST | `/ml/run-model/<model_type>` | ml | role_required('admin', 'analyst') | `model_type` |
| `ml.model_status` | GET | `/ml/model-status` | ml | role_required('admin') | None |
| `ml.train_from_dataset` | POST | `/ml/train-from-dataset/<dataset_id>/<model_type>` | ml | role_required('admin', 'analyst') | `dataset_id`, `model_type` |
| `ml.predict` | POST | `/ml/predict/<model_type>` | ml | role_required('admin', 'teacher', 'analyst') | `model_type`, `student_id`, `course_id` |
| `ml.correlation` | POST | `/ml/correlation` | ml | role_required('admin', 'analyst') | None |
| `data.upload_dataset` | GET, POST | `/data/upload` | data | role_required('admin', 'teacher', 'analyst') | None |
| `data.dataset_detail` | GET | `/data/dataset/<dataset_id>` | data | role_required('admin', 'teacher', 'analyst') | `dataset_id` |
| `data.download_dataset` | GET | `/data/dataset/<dataset_id>/download` | data | role_required('admin', 'teacher', 'analyst') | `dataset_id` |
| `data.processing` | GET | `/data/processing` | data | role_required('admin', 'teacher', 'analyst') | None |
| `data.streaming` | GET | `/data/streaming` | data | role_required('admin', 'teacher') | None |
| `data.ingest_stream_event` | POST | `/data/stream` | data | role_required('admin', 'teacher', 'analyst') | None |
| `data.hdfs_status` | GET | `/data/hdfs-status` | data | role_required('admin', 'teacher', 'analyst') | None |
| `support.list_tickets` | GET | `/support/tickets` | support | role_required('admin', 'teacher', 'student', 'analyst') | None |
| `support.ticket_detail` | GET | `/support/ticket/<ticket_id>` | support | role_required('admin', 'teacher', 'student', 'analyst') | `ticket_id` |
| `support.create_ticket` | GET, POST | `/support/create` | support | role_required('admin', 'teacher', 'student', 'analyst') | None |
| `support.respond_ticket` | POST | `/support/ticket/<ticket_id>/respond` | support | role_required('admin', 'teacher', 'analyst') | `ticket_id` |
| `notifications.list_notifications` | GET | `/notifications/` | notification | role_required('admin', 'teacher', 'student', 'analyst') | None |
| `notifications.mark_read` | POST | `/notifications/mark-read/<notification_id>` | notification | role_required('admin', 'teacher', 'student', 'analyst') | `notification_id` |
| `notifications.broadcast` | GET, POST | `/notifications/broadcast` | notification | role_required('admin', 'teacher') | None |
| `monitoring.health` | GET | `/monitoring/health` | monitoring | None | None |
| `monitoring.metrics` | GET | `/monitoring/metrics` | monitoring | role_required('admin', 'analyst') | None |

---

## 5. RBAC Authorization Matrix

| Route | Anonymous | Student | Teacher | Analyst | Admin | Object Ownership Check | Status |
|---|---|---|---|---|---|---|---|
| `/auth/login` | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | N/A | SECURE |
| `/auth/register` | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | N/A | SECURE |
| `/auth/teacher/register` | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | N/A | SECURE |
| `/auth/forgot-password` | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | N/A | SECURE |
| `/auth/reset-password` | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | Token verified | SECURE |
| `/auth/logout` | DENY (POST only) | ALLOW | ALLOW | ALLOW | ALLOW | Session-scoped | SECURE |
| `/admin/*` (All 38 routes) | DENY | DENY | DENY | DENY | ALLOW | Role-scoped | WARNING (Redirect 302 vs 403) |
| `/teacher/dashboard` | DENY | DENY | ALLOW | DENY | DENY | Teacher courses scoped | SECURE |
| `/teacher/students` | DENY | DENY | ALLOW | DENY | DENY | Assigned student scoped | SECURE |
| `/teacher/courses` | DENY | DENY | ALLOW | DENY | DENY | Assigned courses scoped | SECURE |
| `/teacher/attendance` | DENY | DENY | ALLOW | DENY | DENY | `_authorized_enrollment()` checked | SECURE |
| `/teacher/grades` | DENY | DENY | ALLOW | DENY | DENY | `_authorized_enrollment()` checked | SECURE |
| `/teacher/assignments` | DENY | DENY | ALLOW | DENY | DENY | Course ownership checked | SECURE |
| `/teacher/submissions` | DENY | DENY | ALLOW | DENY | DENY | Course ownership checked | SECURE |
| `/teacher/submissions/<id>/download` | DENY | DENY | ALLOW | DENY | DENY | `_authorized_enrollment()` checked | SECURE |
| `/teacher/submissions/<id>/grade` | DENY | DENY | ALLOW | DENY | DENY | `_authorized_enrollment()` checked | SECURE |
| `/teacher/predict-risk` | DENY | DENY | ALLOW | DENY | DENY | `student_id in assigned_student_ids` | SECURE |
| `/teacher/predictions` | DENY | DENY | ALLOW | DENY | DENY | Scoped to assigned students | SECURE |
| `/student/dashboard` | DENY | ALLOW | DENY | DENY | DENY | Session `user_id` only | SECURE |
| `/student/grades` | DENY | ALLOW | DENY | DENY | DENY | Session `user_id` only | SECURE |
| `/student/attendance` | DENY | ALLOW | DENY | DENY | DENY | Session `user_id` only | SECURE |
| `/student/courses` | DENY | ALLOW | DENY | DENY | DENY | Active enrollments only | SECURE |
| `/student/predictions` | DENY | ALLOW | DENY | DENY | DENY | Session `user_id` only | SECURE |
| `/student/assignments` | DENY | ALLOW | DENY | DENY | DENY | Session `user_id` only | SECURE |
| `/student/assignments/<id>/submit` | DENY | ALLOW | DENY | DENY | DENY | `_owned_assignment()` checked | SECURE |
| `/student/assignments/<id>/download` | DENY | ALLOW | DENY | DENY | DENY | `student_id == _student_id()` | SECURE |
| `/student/profile` | DENY | ALLOW | DENY | DENY | DENY | Session `user_id` only | SECURE |
| `/analyst/dashboard` | DENY | DENY | DENY | ALLOW | ALLOW | System aggregates | SECURE |
| `/analyst/data` | DENY | DENY | DENY | ALLOW | ALLOW | System aggregates | SECURE |
| `/ml/predictions` | DENY | CONDITIONAL | CONDITIONAL | DENY | ALLOW | Student/Teacher scoped | WARNING (Template mismatch) |
| `/ml/run-model/<type>` | DENY | DENY | DENY | ALLOW | ALLOW | Functional | SECURE |
| `/ml/model-status` | DENY | DENY | DENY | DENY | ALLOW | Admin only | SECURE |
| `/ml/train-from-dataset/<d_id>/<type>`| DENY | DENY | DENY | ALLOW | ALLOW | Functional | SECURE |
| `/ml/predict/<type>` | DENY | DENY | CONDITIONAL | CONDITIONAL | ALLOW | Teacher scoped; Analyst UNSCOPED | HIGH IDOR RISK |
| `/ml/correlation` | DENY | DENY | DENY | ALLOW | ALLOW | Functional | SECURE |
| `/data/upload` | DENY | DENY | ALLOW | ALLOW | ALLOW | Recorded with `uploaded_by` | SECURE |
| `/data/dataset/<id>` | DENY | DENY | CONDITIONAL | ALLOW | ALLOW | Teacher limited to own upload | SECURE |
| `/data/dataset/<id>/download` | DENY | DENY | CONDITIONAL | ALLOW | ALLOW | Teacher limited to own upload | SECURE |
| `/data/processing` | DENY | DENY | CONDITIONAL | ALLOW | ALLOW | Teacher limited to own upload | SECURE |
| `/data/streaming` | DENY | DENY | ALLOW | DENY | ALLOW | Generic stream view | SECURE |
| `/data/stream` | DENY | DENY | ALLOW | ALLOW | ALLOW | **NO STUDENT SCOPING CHECK** | HIGH IDOR RISK |
| `/data/hdfs-status` | DENY | DENY | ALLOW | ALLOW | ALLOW | System status | SECURE |
| `/support/tickets` | DENY | CONDITIONAL | CONDITIONAL | ALLOW | ALLOW | Student/Teacher own; Analyst UNFILTERED | MEDIUM IDOR RISK |
| `/support/ticket/<id>` | DENY | CONDITIONAL | CONDITIONAL | ALLOW | ALLOW | Student/Teacher own; Analyst ANY | MEDIUM IDOR RISK |
| `/support/create` | DENY | ALLOW | ALLOW | ALLOW | ALLOW | User-scoped | SECURE |
| `/support/ticket/<id>/respond` | DENY | DENY | CONDITIONAL | ALLOW | ALLOW | Student BLOCKED; Analyst ANY | MEDIUM IDOR RISK |
| `/notifications/` | DENY | ALLOW | ALLOW | ALLOW | ALLOW | Filtered by `session['user_id']` | SECURE |
| `/notifications/mark-read/<id>` | DENY | ALLOW | ALLOW | ALLOW | ALLOW | Filtered by `session['user_id']` | SECURE |
| `/notifications/broadcast` | DENY | DENY | CONDITIONAL | DENY | ALLOW | Teacher scoped to assigned students | SECURE |
| `/monitoring/health` | ALLOW | ALLOW | ALLOW | ALLOW | ALLOW | System health | SECURE |
| `/monitoring/metrics` | DENY | DENY | DENY | ALLOW | ALLOW | System aggregates | SECURE |

---

## 6. IDOR / BOLA Findings (Evidence & Analysis)

### Finding IDOR-01 (Severity: HIGH)
- **Endpoint:** `POST /data/stream` (`routes/data_routes.py:93-107`)
- **Vulnerability:** Unscoped Streaming Event Ingestion (BOLA)
- **Evidence:**
  ```python
  @data_bp.route('/stream', methods=['POST'])
  @role_required('admin', 'teacher', 'analyst')
  def ingest_stream_event():
      payload = request.get_json(silent=True) or {}
      event = ProcessingService.process_stream_event(payload)
      event["ingested_by"] = session.get("user_id")
      mongo.db.stream_events.insert_one(event)
      if event.get("student_id"):
          AlertService.evaluate_student(event["student_id"])
  ```
- **Attack Scenario:** A teacher logs into the application and sends a POST request with `{"student_id": "<unauthorized_student_id>", "event_type": "lms_login"}`. The backend does not verify whether the teacher teaches this student. The event is persisted and triggers automated alert evaluations on an unauthorized student.
- **Recommended Remediation:** If `session.get('role') == 'teacher'`, verify that `event["student_id"]` belongs to `AcademicDataService.teacher_student_ids(session.get("user_id"))`.

---

### Finding IDOR-02 (Severity: HIGH)
- **Endpoint:** `POST /ml/predict/<model_type>` (`routes/ml_routes.py:202-257`)
- **Vulnerability:** Unscoped Prediction Execution by Analyst (BOLA)
- **Evidence:**
  ```python
  if session.get("role") == "teacher":
      if not student_id:
          return jsonify({"status": "error", "message": "Teachers must specify an assigned student."}), 400
      if student_id not in AcademicDataService.teacher_student_ids(session.get("user_id")):
          return jsonify({"status": "error", "message": "You may only score students assigned to your courses."}), 403
  ```
- **Attack Scenario:** An analyst account sends a request with any student's `student_id`. While teachers are strictly checked against their roster, analysts bypass this check completely, injecting predictions and triggering risk alerts on arbitrary student accounts.
- **Recommended Remediation:** Define institutional policy for analysts: either restrict `predict` to aggregate data or require administrative approval/scoping when scoring individual students.

---

### Finding IDOR-03 (Severity: MEDIUM)
- **Endpoint:** `GET /support/tickets` (`routes/support_routes.py:9-20`) & `GET /support/ticket/<ticket_id>` (`routes/support_routes.py:21-34`)
- **Vulnerability:** Analyst Access to All User Support Tickets
- **Evidence:**
  ```python
  query = {}
  if session.get('role') in {'student', 'teacher'}:
      query['created_by'] = session.get('user_id')
  tickets = list(mongo.db.support_tickets.find(query).sort('created_at', -1).limit(100))
  ```
- **Attack Scenario:** A user with role `analyst` logs in and browses to `/support/tickets`. Because `analyst` is omitted from the `{'student', 'teacher'}` filter, `query` remains empty `{}`. The analyst can view every ticket in the database, including private complaints or queries filed by other teachers and students.
- **Recommended Remediation:** Restrict ticket visibility so analysts only see their own tickets (`created_by == session['user_id']`), reserving platform-wide ticket viewing exclusively for administrators (`admin`).

---

### Finding IDOR-04 (Severity: MEDIUM)
- **Endpoint:** `POST /support/ticket/<ticket_id>/respond` (`routes/support_routes.py:56-83`)
- **Vulnerability:** Broken Authorization on Ticket Responses
- **Evidence:**
  ```python
  @support_bp.route('/ticket/<ticket_id>/respond', methods=['POST'])
  @role_required('admin', 'teacher', 'analyst')
  def respond_ticket(ticket_id):
      ticket = mongo.db.support_tickets.find_one({'_id': object_id}, {'created_by': 1})
      if not ticket or (session.get('role') == 'teacher' and ticket.get('created_by') != session.get('user_id')):
          abort(404)
  ```
- **Attack Scenario:** 
  1. An analyst can update or close any support ticket in the institution.
  2. A student who created a ticket cannot reply to their own ticket because `student` is omitted from the allowed roles of `respond_ticket`.
- **Recommended Remediation:** Allow ticket creators (including students) to append responses to their own tickets. Restrict status modifications (`closed`, `resolved`) to administrators. Disallow analysts from modifying tickets they did not author.

---

### Finding IDOR-05 (Severity: MEDIUM)
- **Endpoint:** `GET /admin/reports/<report_id>/download` (`routes/admin_routes.py:951-959`)
- **Vulnerability:** Missing Directory Confinement Check on Report Path
- **Evidence:**
  ```python
  @admin_bp.route("/reports/<report_id>/download")
  @admin_required
  def download_report(report_id):
      report = get_collection("reports").find_one({"_id": parse_object_id(report_id)})
      if not report or not os.path.isfile(report.get("path", "")):
          flash("Report file is not available.", "error")
          return redirect(url_for("admin.reports"))
      return send_file(report["path"], as_attachment=True, download_name=report.get("name", "report.csv"))
  ```
- **Attack Scenario:** If a report document in MongoDB contains a modified `path` (or path traversal reference), `send_file` will deliver any file on the filesystem that Python has permission to read. In contrast, `download_dataset` in the same file implements `os.path.commonpath([root, path]) == root`.
- **Recommended Remediation:** Enforce `os.path.commonpath([reports_root, path]) == reports_root` before invoking `send_file`.

---

### Finding IDOR-06 (Severity: LOW)
- **Endpoint:** `POST /teacher/attendance` (`routes/teacher_routes.py:180-187`) & `POST /teacher/grades` (`routes/teacher_routes.py:232-239`)
- **Vulnerability:** Unverified Subject-to-Course Association
- **Evidence:**
  ```python
  if subject_id and ObjectId.is_valid(subject_id):
      sub_doc = mongo.db.subjects.find_one({"_id": ObjectId(subject_id)})
  ```
- **Attack Scenario:** While `_authorized_enrollment(course_id, student_id)` prevents recording grades or attendance for students outside the teacher's course, a teacher can submit a `subject_id` belonging to a completely different course or department. The subject name/code will be stamped onto the attendance or grade record.
- **Recommended Remediation:** Ensure `mongo.db.subjects.find_one({"_id": ObjectId(subject_id), "course_id": {"$in": [course_id, ObjectId(course_id)]}})` matches the target course.

---

## 7. Ownership & Scope Analysis

1. **Student Scoping:** Strongly implemented. Student views (`/student/*`) exclusively query by `session['user_id']` via helper `_student_id()`. Assignment submissions and downloads verify `_owned_assignment()` and `student_id == _student_id()`.
2. **Teacher Scoping:** Consistently enforces `_teacher_courses()` and `_authorized_enrollment()`, except on the streaming endpoint (`/data/stream`).
3. **Notification Scoping:** Notifications (`/notifications/`, `/notifications/mark-read/<id>`) are strictly scoped by `session['user_id']`. Broadcast notifications by teachers are limited to active student enrollments.

---

## 8. Authentication vs Authorization Gaps

- **Redirect vs 403 Forbidden in `admin_required`:**
  In `routes/admin_routes.py:35-60`, when an authenticated non-admin accesses an admin endpoint, the decorator flashes an error and redirects to the user's role dashboard (`302 Found`).
  Standard security best practice and automated scanners require an explicit `403 Forbidden` response for unauthorized access to prevent silent redirect loops or automated detection bypasses.
- **Role Mismatch on `/ml/predictions`:**
  `routes/ml_routes.py:41-56` permits `student` role on `/ml/predictions` but renders `admin/predictions.html`, which contains administrative links and layout structures.

---

## 9. Finding Classification Summary

| ID | Title | Severity | Component | Recommended Package |
|---|---|---|---|---|
| IDOR-01 | Unscoped Stream Ingestion | HIGH | `routes/data_routes.py` | WP-02A |
| IDOR-02 | Unscoped Analyst Prediction | HIGH | `routes/ml_routes.py` | WP-02A |
| IDOR-03 | Analyst Support Ticket Disclosure | MEDIUM | `routes/support_routes.py` | WP-02B |
| IDOR-04 | Student Ticket Response Lockout | MEDIUM | `routes/support_routes.py` | WP-02B |
| IDOR-05 | Report Download Path Validation | MEDIUM | `routes/admin_routes.py` | WP-02C |
| IDOR-06 | Subject-Course Association Gap | LOW | `routes/teacher_routes.py` | WP-02B |
| AUTH-01 | Admin Decorator Redirect vs 403 | LOW | `routes/admin_routes.py` | WP-02C |
| AUTH-02 | Template Mismatch on `/ml/predictions` | LOW | `routes/ml_routes.py` | WP-02C |

---

## 10. NOT VERIFIED Items

1. **Third-party Identity Provider (IdP) integration:** EduPredict currently uses local database credentials. Federated SSO / OAuth token validation was not verified.
2. **HDFS WebHDFS Remote File Permission ACLs:** The audit evaluated the Flask application layer; backend POSIX permissions inside a remote Hadoop NameNode cluster were not verified.

---

## 11. Recommended Remediation Order

### Phase 1: High-Priority IDOR Fixes (WP-02A)
- Enforce teacher enrollment checks on `POST /data/stream`.
- Enforce student ID scoping or aggregate restrictions for analysts on `POST /ml/predict/<model_type>`.

### Phase 2: Support Ticket & Cross-Entity Authorization (WP-02B)
- Restrict `/support/tickets` and `/support/ticket/<id>` so analysts only view their own tickets.
- Update `/support/ticket/<id>/respond` to allow ticket authors (including students) to reply while restricting status transitions to administrators.
- Enforce course-level matching when resolving `subject_id` in teacher attendance and grading.

### Phase 3: Authorization Hardening & Consistency (WP-02C)
- Add `os.path.commonpath` verification to `download_report` in `admin_routes.py`.
- Standardize `admin_required` to return `abort(403)` on role mismatch.
- Adjust `/ml/predictions` role access and template rendering.

---

## 12. Regression & Test Requirements

Before and after applying WP-02 remediation, the following checks must remain 100% green:
1. `python -m py_compile ...` (Clean compilation across all files)
2. `python -c "from app import create_app; app=create_app(); print('APP_CREATE_OK')"`
3. `python -m pytest -q` (All 28 existing tests must pass)
4. `python -m unittest discover -v -s tests` (All 20 tests must pass)
5. Zero regression on password hashing, CSRF tokens, rate limits, and security headers.
6. New unit tests must be added to verify unauthorized access yields HTTP 403 on protected routes.

---

## 13. Final Readiness Assessment

- **Audit Completion:** The read-only audit of authorization, RBAC, and IDOR is **COMPLETE**.
- **Implementation Status:** No files have been modified.
- **Readiness:** The repository is ready to proceed to remediation.
- **First Recommended Work Package:** **WP-02A: Stream Ingestion & ML Prediction Scoping Remediation**.

