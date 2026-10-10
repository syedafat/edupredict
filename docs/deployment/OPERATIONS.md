# EduPredict operations

## MongoDB backup

After an authorized operator confirms the intended source database, set `MONGO_URI` through the protected runtime environment and run:

```bash
python scripts/backup_mongodb.py --output ./backups
```

The utility invokes `mongodump` using a short-lived protected tools config and refuses to run without an explicit URI. It creates a BSON directory dump. Do not restore with the application `MONGO_URI` or directly over production. For restore drills, follow [BACKUP_RESTORE.md](BACKUP_RESTORE.md) and use a separate protected config targeting an isolated restore-check database; do not use `--drop`.

## Legacy password migration

The application does not accept legacy plaintext passwords at login and never migrates them during authentication. After reviewing a database backup, set `MONGO_URI` through a protected environment/secret manager and run `python scripts/migrate_legacy_passwords.py` for a dry run. It reports only record counts. Apply changes only after reviewing that result and confirming the backup: `python scripts/migrate_legacy_passwords.py --apply`. The migration is never run automatically at startup.

Schedule the command with a protected cron/systemd timer in production. Keep backups encrypted, access-controlled and outside the application ZIP. Test restoration regularly; an untested backup is not a recovery guarantee.

## Health and monitoring

`GET /monitoring/health` reports MongoDB and HDFS reachability. Authorized admins/analysts can call `GET /monitoring/metrics` for request counts, errors, processing duration and collection counts. Request logs are written to `system_logs`; application errors are sent to the Flask logger.

The project does not claim measured 99% uptime. Uptime, alerting, backups, load balancing and retention policies belong to the deployment environment.
