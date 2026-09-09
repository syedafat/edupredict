# EduPredict operations

## MongoDB backup

Set `MONGO_URI` and run:

```bash
python scripts/backup_mongodb.py --output ./backups
```

The command invokes `mongodump` and refuses to run without an explicit URI. Restore with `mongorestore --uri "$MONGO_URI" ./backups/<timestamp>`.

Schedule the command with a protected cron/systemd timer in production. Keep backups encrypted, access-controlled and outside the application ZIP. Test restoration regularly; an untested backup is not a recovery guarantee.

## Health and monitoring

`GET /monitoring/health` reports MongoDB and HDFS reachability. Authorized admins/analysts can call `GET /monitoring/metrics` for request counts, errors, processing duration and collection counts. Request logs are written to `system_logs`; application errors are sent to the Flask logger.

The project does not claim measured 99% uptime. Uptime, alerting, backups, load balancing and retention policies belong to the deployment environment.