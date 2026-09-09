# EduPredict developer guide

## Flow

`routes/data_routes.py` accepts a file or stream event. `IngestionService` validates and records metadata, `ProcessingService` loads and cleans records, typed Mongo collections receive normalized rows, and `HadoopService` optionally writes the same file to WebHDFS. Model training consumes matrices or processed datasets and persists both artifacts and metrics. `AlertService` evaluates persisted student signals and writes deduplicated notifications.

## Database collections

Core collections are `users`, `courses`, `datasets`, `academic_records`, `attendance`, `lms_records`, `demographics`, `educational_records`, `grades`, `predictions`, `model_training`, `anomalies`, `notifications`, `support_tickets`, `reports`, `stream_events`, `system_logs`, `analytics_results` and `settings`.

## Adding a model

Add a model class under `ml/`, register it in `ModelManager.SUPPORTED_MODEL_TYPES` and `get_model`, then add the prediction method branch in `routes/ml_routes.py`. Training must validate shape and labels, return metrics, and never silently return a fake model.

## Real-time architecture

The HTTP `/data/stream` endpoint is a durable local consumer boundary. A production Kafka consumer can deserialize a message and call `ProcessingService.process_stream_event`, then persist to `stream_events` and invoke `AlertService`. Batch uploads and stream events therefore share validation and alert behavior. Kafka/Spark are intentionally not claimed as running services.

## Security and deployment

Credentials come from environment variables. Set a persistent random `SECRET_KEY`, `SESSION_COOKIE_SECURE=true` behind HTTPS, a production MongoDB URI, and a non-memory rate-limit store. Run multiple stateless Flask workers behind a reverse proxy and use MongoDB replica sets for production reliability. Do not archive `.env`, `uploads`, `models`, caches or generated reports.