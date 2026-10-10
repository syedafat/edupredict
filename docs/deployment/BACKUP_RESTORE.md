# MongoDB Backup and Restore

## Backup

The backup utility uses MongoDB Database Tools (`mongodump`) and writes a BSON directory dump. It reads `MONGO_URI` from the process environment, writes to a timestamped directory under `./backups` by default, and suppresses command output that could disclose connection details.

Run it only with a protected environment pointing to the intended source database:

```bash
python scripts/backup_mongodb.py --output /secure/backups
```

Protect the backup directory, encrypt backups at rest, copy them to approved off-site storage, and define retention in the institution's operations policy. The script does not encrypt backup contents or provide scheduling by itself.

## Restore drill

Do not restore over production as a release check. Restore into a disposable, isolated database using a protected MongoDB tools config whose URI targets that isolated database. The URI must not be passed as a command-line argument or written to a shared log.

Example namespace remap:

```bash
mongorestore --config /secure/path/mongo-tools.yml \
  --nsFrom='edupredict.*' \
  --nsTo='edupredict_restore_check.*' \
  /secure/backups/<timestamp>/edupredict
```

Replace the source path with the database directory created by `mongodump`. Confirm the protected config targets only the isolated restore-check database before running the command. Do not add `--drop`. Afterward, verify expected collections, representative records, and indexes in the isolated database, then remove that disposable database through the approved database-operations process.

Production backup and restore readiness is not established until an operator completes and records a restore drill against an isolated target.
