# EduPredict

EduPredict is a Flask application for student analytics, dynamic academic
management, dataset ingestion, support tickets, notifications, reporting, and
persisted scikit-learn models.

## Run locally

1. Create a virtual environment and install dependencies:

   ```bash
   python -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and replace its placeholder values. The
   `.env` file is intentionally excluded from source control and ZIP releases.

3. Start MongoDB, then run:

   ```bash
   python app.py
   ```

The application now calculates user, course, dataset, prediction, report, log,
teacher, and student views from MongoDB rather than seeded demo values.
Teacher registrations start as `pending`; an administrator can approve or
reject them from the Teachers page. Courses support create, edit, assign, and
deactivate actions.

HDFS uploads are disabled by default so local ingestion still works when
Hadoop is not running. Set `HADOOP_ENABLED=true` and `HADOOP_NAMENODE_URL` to
enable WebHDFS uploads.

Password-reset email delivery still requires an email provider integration.
For local testing only, set `PASSWORD_RESET_EXPOSE_LINK=true` to expose a
generated reset URL. Never enable that setting in production.

## Architecture and operations

Read `ARCHITECTURE.md` for the local/production boundary, `DEVELOPER_GUIDE.md`
for the data and ML flows, `USER_GUIDE.md` for role workflows, and
`OPERATIONS.md` for health checks and MongoDB backup/recovery. `DEMO_GUIDE.md`
is a recordable end-to-end walkthrough. `REQUIREMENTS_TRACEABILITY.md` maps
each project requirement to implementation and verification status.

The local streaming contract is `POST /data/stream`. It is durable and
database-backed, and shares validation/alert processing with batch ingestion.
Deployments with Kafka can put a consumer in front of this contract; Kafka and
Spark are not falsely bundled or claimed to be running by the application.

HDFS uses WebHDFS `MKDIRS` plus `CREATE` and partitions files under
`/edupredict/<dataset_type>/<YYYY>/<MM>`. If HDFS is disabled or unreachable,
the upload remains available from the local fallback and the dataset metadata
records the actual HDFS status.