# Deployment notes

## Docker on an EC2 host

1. Install Docker and Docker Compose.
2. Copy `.env.example` to `.env` and populate secrets on the host.
3. Build and initialize the database:

```bash
docker compose build
docker compose run --rm web flask --app wsgi sentinel init-db
```

4. Start the dashboard:

```bash
docker compose up -d
```

5. Put Nginx, Caddy, or an AWS Application Load Balancer with TLS in front of port 8000.

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

## Production database

SQLite is acceptable for one host and one scheduled writer. Use PostgreSQL when deploying multiple app
instances or when stronger backup/concurrency guarantees are required. Set `DATABASE_URL` to a
`postgresql://...` URI; the app normalizes it to the psycopg driver.

## Backups and logs

Back up the SQLite volume or PostgreSQL database. Treat email delivery logs and snapshots as operational
records. Never place API keys in Docker images, Git history, screenshots, or application logs.
