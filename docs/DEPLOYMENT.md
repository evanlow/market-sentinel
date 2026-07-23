# Deployment notes

## Docker on an EC2 host

1. Install Docker and Docker Compose.
2. Copy `.env.example` to `.env` and populate secrets on the host.
3. Set `APP_GIT_SHA` to the deployed commit when possible so new score runs retain code lineage.
4. Build and initialize the database:

```bash
docker compose build
docker compose run --rm web flask --app wsgi sentinel init-db
```

5. When upgrading an installation that already has rows in `snapshots`, copy them into the additive
   research schema:

```bash
docker compose run --rm web flask --app wsgi sentinel migrate-history
```

The migration is idempotent, but create and verify a database backup before every production upgrade.

6. Start the dashboard:

```bash
docker compose up -d
```

7. Put Nginx, Caddy, or an AWS Application Load Balancer with TLS in front of port 8000.

## Daily scheduling

Do not run a scheduler inside every Gunicorn worker. Use one external scheduler. A host cron entry
for approximately 07:00 Singapore time, after the US session has completed, can run:

```cron
0 7 * * 2-6 cd /opt/market-sentinel && docker compose run --rm web flask --app wsgi sentinel run-daily >> /var/log/market-sentinel.log 2>&1
```

The exact UTC conversion changes neither in Singapore nor with daylight saving, but the US close does.
Choose a schedule that remains comfortably after all desired provider data has settled.

For AWS-native scheduling, EventBridge Scheduler can invoke an ECS task, Lambda wrapper, or Systems
Manager command that runs the same Flask CLI command.

The job is idempotent for identical inputs. If a provider corrects a same-day observation, the next run
creates a new revision and preserves the earlier score run.

## Production database

SQLite is acceptable for one host and one scheduled writer. PostgreSQL is recommended for persistent
research history, multiple application instances, point-in-time recovery, and stronger concurrency.
Set `DATABASE_URL` to a `postgresql://...` URI; the app normalizes it to the psycopg driver.

The history upgrade adds new tables rather than altering the original operational tables. Run
`sentinel init-db` after deploying each release so additive tables and indexes are created.

## Backups and retention

Treat score runs, indicator lineage, commentary versions, alert events, and manual observations as
long-lived records.

Recommended controls:

- automated daily PostgreSQL backups or snapshots of the SQLite volume;
- point-in-time recovery for PostgreSQL;
- monthly logical database dumps to versioned S3 storage;
- periodic `sentinel export-history` JSONL exports with checksums;
- quarterly restore tests;
- lifecycle rules that retain research history indefinitely unless licensing requires otherwise.

Example lineage export from the host:

```bash
mkdir -p /opt/market-sentinel/exports
docker compose run --rm web flask --app wsgi sentinel export-history \
  --output /app/exports/score-history.jsonl \
  --format jsonl \
  --include-lineage \
  --include-revisions
```

Ensure the host directory is mounted into the container before using that example path. The exporter
requires the destination parent directory to exist and writes atomically within it.

Never place API keys in Docker images, Git history, screenshots, exports, or application logs.
