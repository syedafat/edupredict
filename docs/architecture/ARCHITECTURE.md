# EduPredict architecture

```text
Browser / API client
        |
Flask routes + CSRF + role_required
        |
MongoDB metadata, users, typed records, alerts, reports and logs
        |                         |
ProcessingService             ModelManager + scikit-learn
        |                         |
Local upload fallback      models/*.joblib (deployment volume)
        |
Optional WebHDFS /edupredict/<type>/<YYYY>/<MM>
```

The application is stateless at the Flask layer except for MongoDB-backed session data in the signed session cookie. A production deployment should use a reverse proxy/load balancer, several Flask workers, MongoDB indexes/replica set, an object/HDFS storage volume, and an external queue or Kafka consumer for high-volume streams. The local fallback is functional but synchronous; it is not a replacement for a distributed processing cluster.