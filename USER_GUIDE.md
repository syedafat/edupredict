# EduPredict user guide

## Roles

- **Administrator:** manages users, teacher approvals, courses, datasets, reports, settings and support.
- **Teacher:** views assigned rosters, records attendance and marks, publishes assignments, grades submissions, uploads data, runs permitted student predictions and manages support responses.
- **Student:** views enrolled courses, grades, attendance, assignments, submissions, predictions, notifications and own tickets.
- **Analyst:** explores live analytics, uploads/inspects data, uses analysis and model endpoints, and works with support.

## First login

Copy `.env.example` to `.env`, set `MONGO_URI`, `SECRET_KEY`, and the three `ADMIN_*` bootstrap values, start MongoDB, then run `python app.py`. The bootstrap admin is created on the first successful database connection.

## Data upload

Open Data Management, choose a dataset type, title and CSV/JSON/XLSX/XLS/TXT file. The application validates the file, normalizes columns, fills missing values, removes duplicates, stores typed records in MongoDB, records a processing summary, and redirects to the dataset detail page. With `HADOOP_ENABLED=true`, it also attempts WebHDFS storage under `/edupredict/<dataset-type>/<year>/<month>`; otherwise the local storage fallback is shown honestly.

## Analytics and models

Analysts can use the Analytics Workspace. Administrators or analysts can train a model from JSON matrices through `/ml/run-model/<model_type>` or from a processed dataset through `/ml/train-from-dataset/<dataset_id>/<model_type>`. The workflow stores metrics in `model_training`; predictions are stored in `predictions`.

## Alerts and support

Administrators configure attendance, dropout-risk and score thresholds in Settings. Alerts are generated when student records or predictions are processed. Every user can create and track a support ticket. Staff can post responses and update its status.

## Academic workflows

Teachers can record attendance and marks only for students actively enrolled in their assigned courses. Both changes refresh the student's feature record, persisted predictions when trained models are available, and alerts. Teachers can publish assignments to all active course enrollments; students submit from My Assignments, and teachers grade submissions. Graded submissions are stored in the existing grades collection and feed performance analytics.

## FAQ

**Why is HDFS unavailable locally?** HDFS is an external service. Keep it disabled for local development; the dataset remains in the configured local upload directory and metadata records the fallback.

**Why is a model not available?** A model is only marked trained after a real training request succeeds. Supply a numeric feature matrix and appropriate target labels, or train from a processed dataset.

**Where are passwords stored?** Only Werkzeug password hashes are stored. Reset email delivery is intentionally not enabled unless an email provider is added.