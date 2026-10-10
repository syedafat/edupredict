# EduPredict

EduPredict is a Flask application for student analytics, dynamic academic
management, dataset ingestion, support tickets, notifications, reporting, and
persisted scikit-learn models.

## Project Overview

- **Purpose**: Provide teachers and administrators with analytics on student
  performance, course engagement, and predictive modelling of outcomes.
- **Core Features**:
  - Authentication & role‑based access (students, teachers, admins)
  - MongoDB‑backed data storage
  - ML model training & inference pipelines
  - CSV / Excel data ingestion
  - Dashboard visualisations and reporting
- **Architecture**: See `ARCHITECTURE.md` for a diagram of the Flask app,
  MongoDB, optional Redis for rate‑limiting, and optional Kafka/Spark
  components.

## Environment Variables

`.env.example` is a development-only reference. Production requires an explicit
secret key, authenticated TLS MongoDB URI, trusted host list, secure cookies,
and shared rate-limit storage. See
[docs/deployment/DEPLOYMENT.md](docs/deployment/DEPLOYMENT.md) for the production
contract and Gunicorn/reverse-proxy instructions.

## Run locally

1. Create a virtual environment and install dependencies:

   ```bash
   python -m venv .venv
   .venv\Scripts\activate  # on Windows
  pip install -r requirements-dev.txt
   ```

2. Copy `.env.example` to `.env` and set local development values. The
   `.env` file is intentionally excluded from source control and ZIP releases.

3. Start a local MongoDB instance, then run the development server:

   ```bash
   python app.py
   ```

The application now calculates user, course, dataset, prediction, report, log,
teacher, and student views from MongoDB rather than seeded demo values.
Teacher registrations start as `pending`; an administrator can approve or
reject them from the Teachers page. Courses support create, edit, assign, and
deactivate actions.

## Optional Features

- HDFS uploads are disabled by default so local ingestion still works when
  Hadoop is not running. Set `HADOOP_ENABLED=true` and `HADOOP_NAMENODE_URL`
  to enable WebHDFS uploads.
- Password-reset delivery uses SMTP settings from the environment. Configure
  the `MAIL_*` variables and `PASSWORD_RESET_BASE_URL` for production. For
  local testing only, `PASSWORD_RESET_EXPOSE_LINK=true` displays a reset URL;
  never enable that setting in production.

## Architecture and operations

Read `ARCHITECTURE.md` for the local/production boundary, `DEVELOPER_GUIDE.md`
for the data and ML flows, `USER_GUIDE.md` for role workflows, and
`OPERATIONS.md` for health checks and MongoDB backup/recovery. `DEMO_GUIDE.md`
is a recordable end‑to‑end walkthrough. `REQUIREMENTS_TRACEABILITY.md`
maps each project requirement to implementation and verification status.

The local streaming contract is `POST /data/stream`. It is durable and
database‑backed, and shares validation/alert processing with batch ingestion.
Deployments with Kafka can put a consumer in front of this contract; Kafka and
Spark are not falsely bundled or claimed to be running by the application.

HDFS uses WebHDFS `MKDIRS` plus `CREATE` and partitions files under
`/edupredict/<dataset_type>/<YYYY>/<MM>`. If HDFS is disabled or unreachable,
the upload remains available from the local fallback and the dataset metadata
records the actual HDFS status.