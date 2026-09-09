# EduPredict demonstration guide

1. Start MongoDB, set `.env`, run `python app.py`, and show `/monitoring/health`.
2. Log in as the bootstrap administrator and show the live admin dashboard.
3. Create a teacher from the admin panel; separately submit the teacher registration form and show its pending state.
4. Approve the pending teacher, log in as that teacher, and show the role-specific dashboard.
5. Create a student and analyst account, assign a course and students, and show each role's restricted navigation.
6. Upload a small CSV or JSON attendance/academic dataset. Show validation, processing summary, MongoDB record counts and the dataset detail/download page.
7. Open Streaming, submit a real JSON event, and show it in the persisted event feed. Explain that local fallback is active unless WebHDFS/Kafka is configured.
8. Train a dropout/performance/anomaly/trend model from the processed dataset or API payload, show metrics, then run a prediction and show the persisted result.
9. Configure alert thresholds, trigger a low-attendance/high-risk test record, and show the database-backed notification.
10. Open analyst charts, generate a CSV report, inspect system logs/metrics, and create/respond/resolve a support ticket.

Use non-sensitive demonstration accounts and datasets. Do not record `.env`, passwords, database URIs or personal student data.