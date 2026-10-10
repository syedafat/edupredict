# EduPredict Data Lineage, Seeding, and Cross-Dashboard Audit

Audit date: 2026-09-08
Scope: Flask routes, MongoDB operations, templates, services, ML modules, HDFS integration, processing path, and dashboard data flow.

## Executive Result

The application has a real MongoDB-backed operational path for users, courses, enrollments, attendance, grades, predictions, notifications, datasets, reports, and support tickets. The three dashboard home APIs read live MongoDB data and are not hardcoded.

The core teacher academic write workflow is implemented for attendance, grades, assignments, submissions, and grading. Local processing uses pandas, not PySpark. Kafka/Spark Streaming is configuration-only. HDFS is optional and currently a copy/fallback integration, not the source of dashboard analytics.

Production status: **NOT READY FOR THE COMPLETE DATA-LINEAGE ACCEPTANCE CRITERIA**.

## 1. Data Lineage Map

| Entity | Source / write path | MongoDB truth | Processing / HDFS / ML | Dashboard/read path | Refresh model |
|---|---|---|---|---|---|
| Users | Auth registration in `routes/auth_routes.py::register`, admin forms in `routes/admin_routes.py::add_user`, `add_teacher`, `edit_user` | `users` | Password hash only; no HDFS | Admin users/students/teachers; role dashboards; auth login | Request-time Mongo read |
| Roles | Registration/admin role fields; session set by `auth_routes.py::login` | `users.role` plus session role | `utils/decorators.py::role_required`, `admin_required` | All protected routes | Validated per request against Mongo |
| Students | Admin add-user or public student registration | `users` with `role=student`; optional `student_id`, profile fields | No automatic feature generation | `student_routes.py`, teacher assigned views, admin views | Request-time scoped query |
| Teachers | Admin `POST /admin/add-teacher` or teacher registration | `users` with `role=teacher`, status | No HDFS/ML dependency | Teacher routes and admin teacher list | Request-time Mongo read |
| Courses | Admin `POST /admin/courses/new`, edit, deactivate | `courses`; `teacher_id` is the teacher relationship source | No HDFS/ML dependency | Admin, teacher, student enrolled-course views | Request-time read; assignment changes visible on next request |
| Enrollments | Admin course form calls `AcademicDataService.upsert_enrollments` | `enrollments` is the student-course relationship source | Indexed by student/course; legacy embedded rosters are migrated once | Teacher dashboard/list and student course lookup | Request-time read; roster changes visible on next request |
| Attendance | Dataset ingestion or teacher `POST /teacher/attendance` | `attendance` | `AcademicDataService.refresh_student`; HDFS raw copy if upload/HDFS enabled | Student attendance page; teacher/admin aggregates | Date-keyed upsert; request-time dashboard reads |
| Grades/marks | Dataset ingestion or teacher `POST /teacher/grades` | `grades` | Feature refresh, predictions, alerts, dashboard aggregates | Student performance; teacher dashboard; admin analytics | Assessment-keyed upsert; request-time dashboard reads |
| Assignments | Teacher `POST /teacher/assignments` expands active enrollments | `assignments` | Student submission workflow | Student dashboard and My Assignments | Request-time read |
| Submissions | Student submit route; teacher grading route | `submissions`, then graded result in `grades` | Grading refreshes features, predictions, and alerts | Teacher submissions; student assignment history/performance | Upsert by student/assignment; request-time read |
| Performance | Derived from `grades.score` in student/teacher dashboards and analyst route | `grades` is source | `analytics_results` may store correlation output | Student/teacher/admin/analyst views | Recalculated on dashboard request; no dedicated performance API |
| Predictions | `POST /ml/predict/<model_type>` or teacher `POST /teacher/predict-risk`; ML training writes `model_training` | `predictions` | Model files in configured `MODEL_FOLDER`; model training metadata in `model_training` | Admin predictions; teacher scoped prediction listing; student scoped predictions | New request reads latest records; no push/live update |
| Dropout risk | ML prediction with `model_type=dropout`, `risk_score`; alert evaluation | `predictions` | `AlertService.evaluate_student` | Teacher attention, student support indicator, admin predictions | Recomputed only when prediction/alert flow runs |
| Course demand | Model support exists in `ml/demand_model.py` and `/ml/predict/demand`; no dashboard-specific demand persistence flow | `predictions` if posted; otherwise no dedicated truth | Model file, no HDFS dashboard path | Mostly admin/analyst capability, not fully wired to role dashboards | Request/ML dependent |
| Alerts | `AlertService` creates notifications; anomaly training writes anomaly notifications | `notifications`, plus `anomalies` | Thresholds from `settings` | Role-scoped notification pages and dashboard summaries | Request-time; dedupe by `dedupe_key` |
| Notifications | `NotificationService`, broadcast route, alert service, anomaly flow | `notifications` | None | Admin/teacher/student notifications | Near-request-time Mongo read; no Kafka push |
| Feedback/support | `POST /support/create`, responses/status updates | `support_tickets` | None | Support pages; admin support list | Request-time; student list scoped to creator |
| Reports | Admin `POST /admin/reports/generate` reads Mongo collections and writes CSV metadata | `reports`, file under report folder | CSV only through `ReportService`; no PDF/Excel flow | Admin report list/download | Explicit generation; no dashboard auto-refresh |
| Historical datasets | Admin upload or `/data/upload` through `IngestionService` | `datasets` metadata; processed operational records | pandas cleaning, local processed file; optional WebHDFS copy | Admin datasets/processing/analytics | Upload-time processing; no async job |
| HDFS data | `HadoopService.upload_to_hdfs` during ingestion | Metadata in `datasets.hdfs_status/hdfs_path` | WebHDFS path `/edupredict/{dataset_type}/{YYYY/MM}` | HDFS status endpoint/admin views | Optional; disabled by default |
| PySpark analytics | No PySpark job/service found | Not applicable | Local pandas `ProcessingService`; Spark config is stored but unused | Processing/analytics views | Synchronous local processing |
| ML outputs | Model manager route writes predictions/model_training | `predictions`, `model_training` | scikit-learn/joblib models in local model folder | Admin/teacher/student prediction pages | Request-time; no model version dashboard contract |

## 2. Required Seed Data

### Must be manually seeded or created

- One approved admin user with hashed password.
- Approved teacher users.
- Approved student users with valid ObjectIds.
- Courses with `teacher_id`, status, semester.
- Enrollment documents for student-course membership.
- Attendance records for attendance KPIs and alerts.
- Grade records for performance KPIs and alerts.
- Assignment documents for student pending-work cards.
- Prediction records or trained model plus feature records.
- Platform settings for thresholds.

A reproducible safe fixture is stored in `tests/fixtures/lineage_seed.json`.

### Generated automatically

- Session fields after login.
- Default admin only when environment variables are set and no admin exists.
- Dataset metadata after upload.
- Processed file and processing summary after valid ingestion.
- Notifications generated by alert evaluation.
- Model training metadata after successful training.
- Report metadata after CSV creation.
- Request metrics in `system_logs`.

### Must come from uploaded data

- Large historical attendance, grades, academic, LMS, demographics, and general records.
- Dataset-derived operational collections populated by `records_for_storage`.

### Static/hardcoded or incomplete

- Teacher dashboard semester and academic year are generated as `Current semester` and current UTC year.
- Student dashboard fallback semester/year defaults are generated values.
- HDFS directory hierarchy is not provisioned as a managed tree.
- Spark/Kafka infrastructure is configuration/documentation only.
- Assignment and submission workflows are available through teacher/student role pages.
- Dashboard chart data is real for current aggregate values, but several chart series are single-snapshot KPI visualizations rather than historical analytics.

## 3. Cross-Dashboard Dependency Matrix

| Change | Admin | Teacher | Student | Actual propagation |
|---|---|---|---|---|
| Create teacher | Teacher list/KPI | Teacher can log in after approval | None | Mongo `users`; visible on next request |
| Edit teacher status/profile | Admin list | Login/role guard reflects status | None | Mongo `users`; request-time |
| Create/edit course assignment | Admin course list | Teacher dashboard/course list | Student course list when embedded/enrollment relation matches | Mongo `courses`; request-time |
| Add enrollment | Admin course form updates the authoritative roster | Teacher dashboard/list includes enrollment records | Student course lookup includes enrollment records | Mongo `enrollments`; visible on next request |
| Add attendance | Admin aggregate reads record | Teacher average reads it | Student attendance/dashboard reads it | Teacher route validates enrollment and refreshes signals |
| Add grade | Admin/analyst aggregates record | Teacher average reads it | Student performance/dashboard reads it | Teacher route validates enrollment and refreshes signals |
| Add assignment | No dashboard admin workflow | Pending-work KPI counts teacher assignments | Student dashboard and assignment page read materialized records | Teacher route expands active enrollment roster |
| Add prediction | Admin prediction list | Assigned teacher prediction list | Matching student prediction list | ML route writes `predictions`; scoped reads |
| Alert/notification | Role-specific notification list | Teacher notifications | Student notifications | `notifications.user_id`; teacher broadcast fixed to assigned students |
| Support ticket | Admin support list | Own/all according to current role policy | Student-created tickets only in list | Mongo support tickets |
| Dataset upload | Admin dataset/processing views | May upload through data route | No access | Local pandas processing; optional HDFS copy |
| Report generation | Admin only, CSV | No teacher reports route | No student reports route | Admin-only current implementation |

## 4. End-to-End Test Results

### Executed successfully

- Full Python compilation passed.
- Route inventory: 80 routes.
- Anonymous protected dashboard/API requests return redirects.
- Admin-created teacher POST with valid data redirects to `/admin/teachers` and stores `role=teacher` with hashed password.
- Approved teacher email/username login redirects to `/teacher/dashboard`.
- Student dashboard queries use authenticated session identity.
- Teacher prediction listing and risk scoring are assignment-scoped.
- Teacher notification broadcast is restricted to assigned students.
- Processing fixture: 3 raw rows including a duplicate and missing value produced 2 cleaned rows and a processed file.
- Dashboard templates render with representative API payloads.

### Not executable in this environment

- Live MongoDB CRUD and cross-dashboard persistence.
- HDFS upload/read/metadata verification.
- PySpark execution: no PySpark job exists in the repository.
- Kafka/Spark Streaming: only local HTTP/Mongo fallback exists.
- Real ML model training/prediction with persisted model files.
- Browser logout/login/reopen-cache test.
- Concurrent update/race-condition test.

### Not PASS because implementation is missing

- Teacher record attendance.
- Teacher update marks.
- Teacher create/edit assignment.
- Student submission and teacher grading.
- Teacher report generation.
- Student report generation.
- Historical chart filtering and recalculation APIs.

## 5. Hardcoded/Mock Data Report

- No fake Mongo dashboard KPI values were found in the three dashboard API payloads.
- Chart data is derived from payload values, but admin/teacher/student home charts are snapshot visualizations rather than historical series.
- Semester and academic year labels contain fallback/generated values.
- No mock users are created automatically except environment-driven default admin.
- HDFS/Spark/Kafka claims in documentation exceed currently implemented runtime services.

## 6. Broken or Incomplete Data Flows

1. **Teacher → attendance → student**: implemented with course/enrollment authorization and refresh propagation.
2. **Teacher → marks → student**: implemented with assessment upsert and refresh propagation.
3. **Teacher → assignment → student**: implemented with per-enrollment assignment records, student submission, and teacher grading.
4. **Teacher pending assignments KPI**: now counts pending/open/upcoming assignments.
5. **Enrollment migration boundary**: legacy `courses.student_ids` records are migrated during database initialization; new writes use only `enrollments`.
6. **Reports**: only admin CSV reporting is implemented; requested role-scoped PDF/Excel reports are absent.
7. **HDFS/PySpark**: HDFS is optional copy storage; PySpark is not implemented.
8. **Real-time updates**: Kafka/Spark Streaming is not implemented.
9. **Support privacy**: non-student roles can view broad ticket sets; teacher ticket scope is not restricted to assigned students.
10. **Processing scale**: upload processing remains synchronous pandas fallback and is not suitable for production-sized datasets.

## 7. Exact Files Requiring Fixes

- `routes/teacher_routes.py`: academic writes, submissions, and grading are implemented; scoped reports remain outstanding.
- `routes/student_routes.py`: assignment submission and own-assignment views are implemented; progress/report APIs remain outstanding.
- `routes/admin_routes.py`: course writes validate approved teachers and synchronize enrollment rosters.
- `routes/notification_routes.py`: teacher scope was fixed; add assignment/student targeting if needed.
- `services/processing_service.py`: introduce asynchronous job abstraction for large workloads.
- `services/hadoop_service.py`: add controlled metadata/read operations and URL allowlisting.
- `routes/ml_routes.py`: add feature-schema/size limits and model-version contracts.
- `templates/teacher/*`, `templates/student/*`: add forms for the currently missing write workflows.

## 8. Fixed and Retested Flows

- Fixed shared role authorization to use the initialized Flask-PyMongo instance.
- Fixed teacher prediction listing to include only assigned course/enrollment students.
- Fixed teacher risk scoring authorization.
- Fixed teacher broadcast targeting to assigned students only.
- Fixed teacher list to include enrollment-based students.
- Fixed failed ingestion reporting.
- Removed credential-looking values from `.env.example` during the audit.
- Made `enrollments` authoritative for admin rosters and analyst course demand.
- Added legacy roster migration and unique student/course enrollment indexes.
- Added a focused enrollment synchronization unit test.
- Added teacher attendance, marks, assignment, submission, and grading workflows.
- Added assignment/submission indexes and role navigation links.
- Retested compilation, protected route behavior, dashboard rendering, login redirect, teacher creation, and local processing.

## 9. Production Readiness

**NOT READY — MAJOR DATA-FLOW WORK REQUIRED**.

The operational read and core academic write paths are real and mostly session-scoped, but the complete requested lineage contract is not satisfied until role-scoped reports, real integration tests, async processing, and actual HDFS/PySpark/Kafka services are implemented and tested against live infrastructure.
