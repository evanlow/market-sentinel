# Deploy Market Sentinel to AWS

This guide explains, step by step, how to deploy Market Sentinel to AWS in a secure and maintainable way.

The recommended deployment uses:

- **Amazon Route 53** for DNS;
- **AWS Certificate Manager (ACM)** for a managed TLS certificate;
- **Application Load Balancer (ALB)** for HTTPS termination and health checks;
- **Amazon EC2** running Ubuntu and Docker Compose;
- **Amazon RDS for PostgreSQL** for persistent operational and research history;
- **AWS Systems Manager Session Manager** for administration without publicly exposing SSH;
- **Amazon S3** for optional versioned research exports;
- a host **cron job** for the daily Market Sentinel run.

> [!IMPORTANT]
> Market Sentinel is a risk-monitoring application, not a crash-prediction or investment-advice system. Deployment does not remove data-provider limitations, false positives, false negatives, or model risk.

---

## Table of contents

1. [Deployment outcome](#1-deployment-outcome)
2. [Recommended sizing and cost awareness](#2-recommended-sizing-and-cost-awareness)
3. [Prerequisites and deployment worksheet](#3-prerequisites-and-deployment-worksheet)
4. [Prepare networking and IAM](#part-i---prepare-networking-and-iam)
5. [Launch and prepare EC2](#part-ii---launch-and-prepare-ec2)
6. [Create RDS PostgreSQL](#part-iii---create-rds-postgresql)
7. [Configure and start Market Sentinel](#part-iv---configure-and-start-market-sentinel)
8. [Configure HTTPS, ALB, and Route 53](#part-v---configure-https-alb-and-route-53)
9. [Enable OpenAI and Mailgun](#part-vi---enable-optional-integrations)
10. [Schedule the daily run](#part-vii---schedule-the-daily-run)
11. [Backups and research retention](#part-viii---backups-and-research-retention)
12. [Monitoring and operations](#part-ix---monitoring-and-operations)
13. [Safe upgrades and rollback](#part-x---safe-upgrades-and-rollback)
14. [Troubleshooting](#part-xi---troubleshooting)
15. [Security and final checklists](#part-xii---security-and-final-checklists)
16. [Lower-cost and advanced alternatives](#appendices)

---

## 1. Deployment outcome

At the end of this guide, traffic flows as follows:

```text
Internet user
    |
    v
Route 53 DNS: sentinel.example.com
    |
    v
Application Load Balancer
- HTTP 80 redirects to HTTPS 443
- ACM certificate terminates TLS
- /healthz checks the application
    |
    v
EC2 security group permits port 8000 only from the ALB
    |
    v
Ubuntu EC2 instance
- Docker Engine + Docker Compose
- Market Sentinel Gunicorn container on port 8000
- scheduled daily CLI job
    |
    v
Private RDS PostgreSQL
- port 5432 permitted only from the EC2 security group
- automated backups enabled
```

The application listens on port `8000` inside the VPC. Only the ALB is publicly reachable on ports `80` and `443`.

---

## 2. Recommended sizing and cost awareness

The following is a practical starting point for a personal or small-team deployment.

| Resource | Suggested starting configuration |
|---|---|
| AWS Region | `ap-southeast-1` (Singapore), or the region closest to the operator |
| EC2 operating system | Ubuntu Server 24.04 LTS, x86_64 |
| EC2 instance | `t3.small` or equivalent, 2 GiB RAM |
| EC2 storage | 25-30 GiB encrypted gp3 |
| RDS engine | PostgreSQL |
| RDS deployment | Single-AZ for development; Multi-AZ for production-critical use |
| RDS instance | Smallest eligible class that meets the workload |
| RDS storage | 20 GiB or more, encrypted, storage autoscaling enabled |
| ALB | Internet-facing Application Load Balancer |
| Domain | A subdomain such as `sentinel.example.com` |

A `t3.micro` can work for light experimentation, but 1 GiB of memory can be uncomfortable during Docker image builds and Python package installation. `t3.small` is a safer first deployment.

> [!NOTE]
> AWS instance classes, free-tier eligibility, prices, and console wording can change. Use the current AWS console and AWS Pricing Calculator before provisioning.

Resources that normally incur ongoing charges include:

- Application Load Balancer;
- EC2 instance, public IPv4 address, and EBS storage;
- RDS instance, storage, backups beyond included allowances, and data transfer;
- Route 53 hosted zone and DNS queries;
- S3 storage and requests;
- CloudWatch logs, metrics, and alarms beyond included allowances.

For a temporary demonstration, see [Appendix A: Lower-cost single-EC2 deployment](#appendix-a-lower-cost-single-ec2-deployment).

---

## 3. Prerequisites and deployment worksheet

### Prerequisites

Prepare the following before starting:

- an AWS account with MFA enabled;
- permission to create IAM, EC2, RDS, ELB, ACM, Route 53, and optionally S3 resources;
- a registered domain, preferably with DNS hosted in Route 53;
- access to this public GitHub repository;
- a FRED API key if the FRED indicators are required;
- an OpenAI API key only if AI commentary will be enabled;
- a Mailgun domain and API key only if emails will be enabled;
- a safe password manager for generated credentials.

Do not paste secrets into:

- GitHub files;
- EC2 user-data scripts;
- screenshots;
- AWS resource names or tags;
- shell commands that will remain in command history;
- application logs.

### Deployment worksheet

| Item | Example | Your value |
|---|---|---|
| AWS Region | `ap-southeast-1` | |
| VPC | `default` or a dedicated VPC | |
| Application domain | `sentinel.example.com` | |
| EC2 name | `market-sentinel-app` | |
| EC2 security group | `market-sentinel-ec2-sg` | |
| ALB security group | `market-sentinel-alb-sg` | |
| RDS security group | `market-sentinel-rds-sg` | |
| Target group | `market-sentinel-tg` | |
| Load balancer | `market-sentinel-alb` | |
| RDS identifier | `market-sentinel-db` | |
| PostgreSQL database | `market_sentinel` | |
| PostgreSQL user | `market_sentinel_admin` | |
| Optional S3 bucket | `your-account-market-sentinel-backups` | |

Examples in this guide use:

```text
AWS Region: ap-southeast-1
Domain: sentinel.example.com
Application directory: /opt/market-sentinel
Container port: 8000
PostgreSQL port: 5432
Linux application user: ubuntu
```

Replace all example values with your own values.

---

# Part I - Prepare networking and IAM

## 4. Choose the VPC approach

### Approach 1: Existing or default VPC

This is the simplest first deployment.

Confirm the VPC has:

- at least two subnets in different Availability Zones for the ALB;
- an internet gateway;
- a route to the internet from the subnets used by the ALB;
- DNS resolution and DNS hostnames enabled.

The EC2 instance can be placed in a public subnet with a public IPv4 address for outbound access. RDS must be set to **Public access: No**.

### Approach 2: Dedicated production VPC

A more isolated design uses:

- two public subnets in different Availability Zones for the ALB;
- one public application subnet for the first EC2 instance, or private application subnets with NAT;
- two private database subnets for RDS;
- separate route tables by tier.

The critical rules are:

1. ALB, EC2, and RDS must be in the same VPC unless you intentionally design cross-VPC connectivity.
2. RDS should not be publicly accessible.
3. Security groups should reference one another instead of allowing broad public access.
4. An EC2 instance in a private subnet needs NAT or suitable VPC endpoints for package downloads and external APIs.

---

## 5. Create the three security groups

Open **AWS Console -> EC2 -> Network & Security -> Security Groups**.

Create the following groups in the same VPC.

### 5.1 ALB security group

Name:

```text
market-sentinel-alb-sg
```

Inbound rules:

| Type | Port | Source | Purpose |
|---|---:|---|---|
| HTTP | 80 | `0.0.0.0/0` | Redirect visitors to HTTPS |
| HTTPS | 443 | `0.0.0.0/0` | Public application traffic |
| HTTP | 80 | `::/0` | Optional IPv6 redirect when using dual-stack |
| HTTPS | 443 | `::/0` | Optional IPv6 application traffic |

Outbound rule:

- TCP `8000` to `market-sentinel-ec2-sg` when your console permits selecting the EC2 security group as the destination; or
- temporarily retain the default outbound rule and tighten it after the target is healthy.

### 5.2 EC2 application security group

Name:

```text
market-sentinel-ec2-sg
```

Inbound rule:

| Type | Port | Source | Purpose |
|---|---:|---|---|
| Custom TCP | 8000 | `market-sentinel-alb-sg` | ALB traffic and health checks |

Do **not** allow port `8000` from `0.0.0.0/0`.

Administrative access options:

- **Recommended:** use Systems Manager Session Manager and do not add port `22`.
- **Fallback:** add SSH port `22` from **My IP** only, never from the whole internet.

For the initial deployment, retaining the default outbound rule is simplest because the application needs outbound HTTPS access to market-data providers, FRED, OpenAI, Mailgun, GitHub, Docker registries, and Ubuntu repositories.

### 5.3 RDS security group

Name:

```text
market-sentinel-rds-sg
```

Inbound rule:

| Type | Port | Source | Purpose |
|---|---:|---|---|
| PostgreSQL | 5432 | `market-sentinel-ec2-sg` | Database access from the application only |

Do not add your home IP or `0.0.0.0/0` unless you deliberately need temporary database administration and understand the risk.

---

## 6. Create an EC2 IAM role

Systems Manager lets you administer EC2 without opening SSH to the internet.

Open **IAM -> Roles -> Create role**.

1. Trusted entity type: **AWS service**.
2. Use case: **EC2**.
3. Add managed policy:

```text
AmazonSSMManagedInstanceCore
```

4. Name the role:

```text
MarketSentinelEC2Role
```

5. Create the role.

Attach this role to the EC2 instance during launch.

### Optional S3 backup permission

When using an S3 backup bucket, add a narrowly scoped inline policy similar to the following. Replace the bucket name.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ListMarketSentinelBackupPrefix",
      "Effect": "Allow",
      "Action": ["s3:ListBucket"],
      "Resource": "arn:aws:s3:::YOUR-BACKUP-BUCKET",
      "Condition": {
        "StringLike": {
          "s3:prefix": ["market-sentinel/*"]
        }
      }
    },
    {
      "Sid": "WriteMarketSentinelBackups",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:AbortMultipartUpload"
      ],
      "Resource": "arn:aws:s3:::YOUR-BACKUP-BUCKET/market-sentinel/*"
    }
  ]
}
```

Do not grant `s3:*` across all buckets.

---

# Part II - Launch and prepare EC2

## 7. Launch the EC2 instance

Open **EC2 -> Instances -> Launch instances**.

### Name and operating system

Name:

```text
market-sentinel-app
```

Choose:

```text
Ubuntu Server 24.04 LTS, 64-bit (x86)
```

### Instance type

Recommended starting point:

```text
t3.small
```

### Key pair

When using Session Manager only, a key pair is not technically required. A securely stored recovery key can still be useful.

When using PuTTY:

- create or select a key pair;
- download the private key once;
- convert `.pem` to `.ppk` with PuTTYgen when required;
- never email or commit the private key.

### Network settings

Select:

- the chosen VPC;
- a subnet with outbound internet access;
- **Auto-assign public IP: Enable** for the simple public-subnet design;
- existing security group: `market-sentinel-ec2-sg`.

Users will access the ALB, not the EC2 public IP.

An Elastic IP is optional. It is not required for the public application endpoint when Route 53 points to the ALB.

### Storage

Configure approximately:

```text
30 GiB gp3, encrypted
```

Understand the backup implications before enabling delete-on-termination.

### Advanced details

Select IAM instance profile:

```text
MarketSentinelEC2Role
```

Do not place API keys or passwords in EC2 user data.

### Tags

Suggested tags:

```text
Project = market-sentinel
Environment = production
Owner = YOUR-NAME
```

Launch the instance and wait for both EC2 status checks to pass.

---

## 8. Connect to EC2 and standardize the shell user

### Recommended: Systems Manager Session Manager

Open:

```text
EC2 -> Instances -> market-sentinel-app -> Connect -> Session Manager
```

Choose **Connect**.

Session Manager commonly opens as `ssm-user`. This guide standardizes all application files and scheduled jobs under the Ubuntu AMI user `ubuntu`.

Check the current user:

```bash
whoami
```

When the result is not `ubuntu`, switch to the Ubuntu user:

```bash
sudo -iu ubuntu
whoami
```

The second command should return:

```text
ubuntu
```

Run the remaining host commands in this guide as `ubuntu`, using `sudo` only where shown.

If Session Manager is unavailable, check:

- the IAM role is attached;
- the instance has outbound HTTPS access;
- the SSM agent is installed and running;
- the instance and Systems Manager console are in the same AWS Region.

### Fallback: SSH

Ubuntu uses username:

```text
ubuntu
```

Example:

```bash
ssh -i /safe/path/market-sentinel.pem ubuntu@EC2_PUBLIC_IP
```

For PuTTY, use the EC2 public IP, port `22`, username `ubuntu`, and the `.ppk` key under **Connection -> SSH -> Auth -> Credentials**.

Restrict the SSH security-group rule to your current public IP.

---

## 9. Update Ubuntu and set the timezone

Run:

```bash
sudo apt-get update
sudo apt-get upgrade -y
sudo apt-get install -y ca-certificates curl git gnupg openssl unzip
```

Set the host timezone to Singapore so the daily schedule is easy to interpret:

```bash
sudo timedatectl set-timezone Asia/Singapore
```

Verify:

```bash
date
timedatectl
```

Use another IANA timezone when appropriate.

Reboot only when Ubuntu reports a restart is required:

```bash
sudo reboot
```

Reconnect and switch back to `ubuntu` when using Session Manager.

---

## 10. Install Docker Engine and Docker Compose

Use Docker's official Ubuntu repository rather than the older distribution package.

Remove conflicting packages if present:

```bash
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do
  sudo apt-get remove -y "$pkg" 2>/dev/null || true
done
```

Add Docker's signing key and repository:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt-get update
```

Install Docker:

```bash
sudo apt-get install -y \
  docker-ce \
  docker-ce-cli \
  containerd.io \
  docker-buildx-plugin \
  docker-compose-plugin
```

Enable and verify Docker:

```bash
sudo systemctl enable --now docker
sudo docker run --rm hello-world
sudo docker compose version
```

Allow `ubuntu` to run Docker:

```bash
sudo usermod -aG docker ubuntu
```

End the session and reconnect so group membership is refreshed. When using Session Manager, switch again with `sudo -iu ubuntu`.

Verify without `sudo`:

```bash
id
docker version
docker compose version
```

The `id` output should include the `docker` group.

> [!CAUTION]
> Docker group membership grants powerful host-level capabilities. Limit administrative access to trusted operators.

---

## 11. Clone Market Sentinel

Create the application directory:

```bash
sudo mkdir -p /opt/market-sentinel
sudo chown ubuntu:ubuntu /opt/market-sentinel
```

Clone the repository:

```bash
git clone https://github.com/evanlow/market-sentinel.git /opt/market-sentinel
cd /opt/market-sentinel
```

Verify:

```bash
git status
git branch --show-current
git log -1 --oneline
```

Production should normally use `main` after the desired pull requests have been reviewed and merged.

---

# Part III - Create RDS PostgreSQL

## 12. Create the database

Open **RDS -> Databases -> Create database**.

### Creation method and engine

Choose:

- **Standard create**;
- engine: **PostgreSQL**;
- a currently supported PostgreSQL major version.

Confirm the selected version is generally available in your Region and compatible with your maintenance policy.

### Template

Choose:

- **Dev/Test** or the smallest eligible option for a demonstration;
- **Production** for a production-critical deployment.

### Settings

DB identifier:

```text
market-sentinel-db
```

Master username:

```text
market_sentinel_admin
```

Generate a strong password and store it in a password manager.

### Availability and durability

- Single-AZ is sufficient for a personal MVP.
- Multi-AZ is recommended when database availability is business-critical.

### Instance and storage

Choose a small instance class suitable for the workload.

Suggested starting storage:

```text
20 GiB gp3, encrypted
```

Enable storage autoscaling and select a sensible maximum.

### Connectivity

Configure:

- VPC: same VPC as EC2;
- public access: **No**;
- VPC security group: `market-sentinel-rds-sg`;
- port: `5432`.

If the console offers **Connect to an EC2 compute resource**, selecting the Market Sentinel EC2 instance can automatically configure connectivity. Review the resulting security groups and ensure the effective rule remains PostgreSQL `5432` from the EC2 security group only.

### Additional configuration

Initial database name:

```text
market_sentinel
```

Recommended settings:

- automated backups enabled;
- retention of at least 7 days for an MVP, longer when required;
- deletion protection for production;
- automatic minor-version upgrades according to policy;
- Performance Insights or Enhanced Monitoring when useful;
- CloudWatch log exports when needed.

Create the database and wait until status is **Available**.

---

## 13. Record the endpoint and test connectivity

Open the database's **Connectivity & security** page and copy:

- endpoint, for example `market-sentinel-db.xxxxxxxxx.ap-southeast-1.rds.amazonaws.com`;
- port `5432`.

The endpoint is a DNS name. Do not substitute an IP address.

On EC2, install the PostgreSQL client:

```bash
sudo apt-get install -y postgresql-client
```

Connect without placing the password in shell history:

```bash
psql \
  "host=YOUR_RDS_ENDPOINT port=5432 dbname=market_sentinel user=market_sentinel_admin sslmode=require"
```

Enter the password at the prompt.

Inside `psql`:

```sql
SELECT current_database(), current_user, version();
```

Exit:

```text
\q
```

If the connection times out, check networking and security groups before changing application code.

---

# Part IV - Configure and start Market Sentinel

## 14. Create the production `.env`

Go to the repository:

```bash
cd /opt/market-sentinel
```

Create the environment file securely:

```bash
umask 077
cp .env.example .env
chmod 600 .env
```

Generate a Flask secret key:

```bash
openssl rand -hex 32
```

Record the deployed Git commit:

```bash
git rev-parse HEAD
```

Open the environment file:

```bash
nano .env
```

Use a configuration similar to this:

```dotenv
# Flask
APP_ENV=production
APP_GIT_SHA=PASTE_OUTPUT_OF_GIT_REV_PARSE_HEAD
SECRET_KEY=PASTE_LONG_RANDOM_SECRET
DATABASE_URL=postgresql://market_sentinel_admin:URL_ENCODED_PASSWORD@YOUR_RDS_ENDPOINT:5432/market_sentinel?sslmode=require

# Market and economic data
MARKET_DATA_PERIOD=2y
FRED_API_KEY=YOUR_FRED_API_KEY

# Optional OpenAI commentary
OPENAI_ENABLED=false
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-mini
OPENAI_TIMEOUT_SECONDS=30

# Optional Mailgun delivery
MAILGUN_API_KEY=
MAILGUN_DOMAIN=
MAILGUN_FROM_EMAIL="Market Sentinel <alerts@YOUR_MAILGUN_DOMAIN>"
MAILGUN_RECIPIENTS=YOUR_EMAIL_ADDRESS
MAILGUN_API_BASE=https://api.mailgun.net
MAILGUN_TIMEOUT_SECONDS=20
DAILY_EMAIL_ENABLED=false
ALERTS_ENABLED=false

# Alert policy
ALERT_MIN_COVERAGE=0.70
ALERT_COOLDOWN_HOURS=18

# Research-history API
HISTORY_API_MAX_LIMIT=5000
```

### URL-encode the database password

Special characters in the PostgreSQL password must be URL-encoded in `DATABASE_URL`.

Use this without exposing the password in shell history:

```bash
python3 - <<'PY'
from getpass import getpass
from urllib.parse import quote_plus

print(quote_plus(getpass("Database password: ")))
PY
```

Paste the encoded output into `DATABASE_URL`.

### Start with integrations disabled

Initially retain:

```dotenv
OPENAI_ENABLED=false
DAILY_EMAIL_ENABLED=false
ALERTS_ENABLED=false
```

First prove that collection, scoring, persistence, dashboard, and RDS work. Enable optional services one at a time later.

Verify permissions:

```bash
ls -l .env
```

The file should not be readable by other users.

---

## 15. Validate and build the Compose application

Validate without printing resolved secrets to the terminal:

```bash
cd /opt/market-sentinel
docker compose config >/dev/null && echo "Compose configuration is valid."
```

Build:

```bash
docker compose build --pull
```

The first build can take several minutes.

---

## 16. Initialize the database

Create operational and research-history tables:

```bash
docker compose run --rm web \
  flask --app wsgi sentinel init-db
```

For an existing installation with legacy `snapshots`, run the idempotent migration:

```bash
docker compose run --rm web \
  flask --app wsgi sentinel migrate-history
```

On a new database, migration can safely report zero migrated rows.

---

## 17. Start and test the application

Start:

```bash
docker compose up -d
```

Check status and logs:

```bash
docker compose ps
docker compose logs --tail=100 web
```

Local health check:

```bash
curl -fsS http://127.0.0.1:8000/healthz
```

Expected:

```json
{"status":"ok"}
```

Test the dashboard and API:

```bash
curl -I http://127.0.0.1:8000/
curl -fsS http://127.0.0.1:8000/api/status
```

A new deployment may return a no-data response until the first refresh.

Do not open port `8000` publicly to perform these tests.

---

## 18. Run the first refresh

Run without OpenAI first:

```bash
docker compose run --rm web \
  flask --app wsgi sentinel refresh --no-ai
```

Check status:

```bash
curl -fsS http://127.0.0.1:8000/api/status
```

Inspect history:

```bash
docker compose run --rm web \
  flask --app wsgi sentinel history --limit 10
```

A missing FRED key reduces coverage but does not prevent all available indicators from being calculated.

---

## 19. Optionally enter FINRA margin debt

Example:

```bash
docker compose run --rm web \
  flask --app wsgi sentinel set-margin-debt \
  --value 1000000 \
  --as-of 2026-05-31 \
  --source-url "https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics" \
  --notes "Entered from the FINRA monthly margin statistics release"
```

Replace the value and date with the actual published observation, then run another refresh.

---

# Part V - Configure HTTPS, ALB, and Route 53

## 20. Create the target group

Open **EC2 -> Load Balancing -> Target Groups -> Create target group**.

Configure:

| Setting | Value |
|---|---|
| Target type | Instances |
| Name | `market-sentinel-tg` |
| Protocol | HTTP |
| Port | `8000` |
| IP address type | IPv4 |
| VPC | Same VPC as EC2 |
| Protocol version | HTTP1 |

Health check:

| Setting | Value |
|---|---|
| Protocol | HTTP |
| Port | Traffic port |
| Path | `/healthz` |
| Success code | `200` |
| Healthy threshold | 2 or the console default |
| Unhealthy threshold | 2 |
| Timeout | 5 seconds |
| Interval | 30 seconds |

Register `market-sentinel-app` on port `8000` and wait for **Healthy**.

---

## 21. Request an ACM certificate

Open **AWS Certificate Manager** in the **same Region as the ALB**.

1. Choose **Request a certificate**.
2. Choose **Request a public certificate**.
3. Enter the hostname, for example:

```text
sentinel.example.com
```

4. Choose **DNS validation**.
5. Request the certificate.
6. Open its details.
7. When Route 53 hosts the domain, choose **Create records in Route 53**.
8. Wait for **Issued**.

A wildcard such as `*.example.com` does not automatically cover the apex `example.com`.

---

## 22. Create the Application Load Balancer

Open **EC2 -> Load Balancing -> Load Balancers -> Create load balancer -> Application Load Balancer**.

Configure:

| Setting | Value |
|---|---|
| Name | `market-sentinel-alb` |
| Scheme | Internet-facing |
| IP address type | IPv4, or Dualstack when intentionally configured |
| VPC | Same VPC as EC2 |
| Mappings | At least two public subnets in different Availability Zones |
| Security group | `market-sentinel-alb-sg` |

### HTTPS listener

- protocol: HTTPS;
- port: `443`;
- default action: forward to `market-sentinel-tg`;
- certificate: issued ACM certificate;
- security policy: current AWS recommended policy unless organizational policy requires another.

### HTTP listener

- protocol: HTTP;
- port: `80`;
- default action: redirect to HTTPS;
- destination port: `443`;
- status code: `HTTP_301`.

Create the ALB, wait for **Active**, and confirm the target remains healthy.

---

## 23. Create the Route 53 alias

Open **Route 53 -> Hosted zones -> your domain -> Create record**.

For `sentinel.example.com`:

| Setting | Value |
|---|---|
| Record name | `sentinel` |
| Record type | A |
| Alias | On |
| Route traffic to | Alias to Application and Classic Load Balancer |
| Region | Same Region as the ALB |
| Load balancer | `market-sentinel-alb` |
| Routing policy | Simple |
| Evaluate target health | Yes |

Create the record. When using dual-stack, also create the appropriate AAAA alias.

When DNS is outside Route 53, create the provider's equivalent CNAME for a subdomain. Apex-domain handling varies by provider.

---

## 24. Verify the public deployment

Run from your computer:

```bash
curl -I https://sentinel.example.com/
curl -fsS https://sentinel.example.com/healthz
curl -fsS https://sentinel.example.com/api/status
```

Open:

```text
https://sentinel.example.com
```

Confirm:

- valid browser certificate;
- HTTP redirects to HTTPS;
- dashboard loads;
- `/healthz` returns `200`;
- ALB target remains healthy;
- port `8000` is not directly reachable from the public internet.

---

# Part VI - Enable optional integrations

## 25. Enable OpenAI commentary

Edit `.env`:

```bash
cd /opt/market-sentinel
nano .env
```

Set:

```dotenv
OPENAI_ENABLED=true
OPENAI_API_KEY=YOUR_OPENAI_API_KEY
OPENAI_MODEL=gpt-5-mini
```

Reload the container environment:

```bash
docker compose up -d --force-recreate web
```

Test:

```bash
docker compose run --rm web \
  flask --app wsgi sentinel refresh
```

OpenAI commentary explains deterministic results. It does not set or alter the score.

---

## 26. Configure Mailgun

Set in `.env`:

```dotenv
MAILGUN_API_KEY=YOUR_MAILGUN_API_KEY
MAILGUN_DOMAIN=YOUR_VERIFIED_MAILGUN_DOMAIN
MAILGUN_FROM_EMAIL="Market Sentinel <alerts@YOUR_VERIFIED_MAILGUN_DOMAIN>"
MAILGUN_RECIPIENTS=recipient1@example.com,recipient2@example.com
MAILGUN_API_BASE=https://api.mailgun.net
DAILY_EMAIL_ENABLED=false
ALERTS_ENABLED=false
```

For Mailgun EU:

```dotenv
MAILGUN_API_BASE=https://api.eu.mailgun.net
```

Reload:

```bash
docker compose up -d --force-recreate web
```

Test daily email:

```bash
docker compose run --rm web \
  flask --app wsgi sentinel send-daily --force
```

Test alert:

```bash
docker compose run --rm web \
  flask --app wsgi sentinel evaluate-alert --force
```

Only after both tests succeed, decide whether to enable:

```dotenv
DAILY_EMAIL_ENABLED=true
ALERTS_ENABLED=true
```

Reload the container after editing `.env`.

Mailgun sandbox domains normally restrict recipients. Use a verified sending domain for normal operations.

---

# Part VII - Schedule the daily run

## 27. Create the runner script

Confirm command paths:

```bash
command -v docker
command -v flock
```

The following assumes both are under `/usr/bin`, which is normal for this installation. Use the paths returned above when different.

Create the script:

```bash
sudo tee /usr/local/bin/market-sentinel-daily >/dev/null <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail

cd /opt/market-sentinel

exec /usr/bin/flock -n /opt/market-sentinel/.daily-run.lock \
  /usr/bin/docker compose run --rm web \
  flask --app wsgi sentinel run-daily
EOF
```

Make it executable and ensure the lock path is owned by `ubuntu`:

```bash
sudo chmod 755 /usr/local/bin/market-sentinel-daily
sudo touch /opt/market-sentinel/.daily-run.lock
sudo chown ubuntu:ubuntu /opt/market-sentinel/.daily-run.lock
```

Test as `ubuntu`:

```bash
/usr/local/bin/market-sentinel-daily
```

Check the dashboard and logs before scheduling.

---

## 28. Create the cron log and schedule

Create the log:

```bash
sudo touch /var/log/market-sentinel-daily.log
sudo chown ubuntu:ubuntu /var/log/market-sentinel-daily.log
```

Open the `ubuntu` crontab:

```bash
crontab -e
```

Add:

```cron
0 7 * * 2-6 /usr/local/bin/market-sentinel-daily >> /var/log/market-sentinel-daily.log 2>&1
```

This runs at **07:00 Singapore time, Tuesday through Saturday** after the corresponding completed US sessions.

Verify:

```bash
timedatectl
crontab -l
systemctl status cron
```

After the first scheduled run:

```bash
tail -n 200 /var/log/market-sentinel-daily.log
```

The lock prevents overlapping jobs. A holiday or provider delay may mean the latest market date has not advanced; identical inputs are idempotent and do not create duplicate research runs.

---

# Part VIII - Backups and research retention

## 29. Configure RDS backups

In **RDS -> Databases -> market-sentinel-db -> Modify**, confirm:

- automated backups enabled;
- retention meets the recovery objective;
- deletion protection enabled for production;
- preferred backup window documented;
- storage autoscaling configured;
- final snapshot behavior understood before deletion.

Create a manual snapshot before:

- major upgrades;
- database-related changes;
- credential rotation;
- destructive maintenance.

RDS point-in-time recovery creates a new database instance. Periodically test the complete restore and reconnection process.

---

## 30. Create an optional versioned S3 bucket

Open **S3 -> Create bucket**.

Recommended configuration:

- unique name;
- same Region as the application when practical;
- all Block Public Access controls enabled;
- versioning enabled;
- default encryption enabled;
- lifecycle rules for older noncurrent versions when appropriate;
- no public website hosting.

Example:

```text
YOUR-ACCOUNT-market-sentinel-backups
```

Attach the narrowly scoped S3 policy from [Create an EC2 IAM role](#6-create-an-ec2-iam-role).

---

## 31. Install AWS CLI v2

For x86_64 Ubuntu:

```bash
cd /tmp
curl -fsS "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" \
  -o awscliv2.zip
unzip -q awscliv2.zip
sudo ./aws/install
rm -rf aws awscliv2.zip
```

Verify the EC2 instance role:

```bash
aws sts get-caller-identity
```

Do not configure long-lived AWS access keys on EC2 when an instance role can provide the required permissions.

---

## 32. Export history and upload it to S3

Create a protected host directory:

```bash
sudo mkdir -p /opt/market-sentinel/exports
sudo chown ubuntu:ubuntu /opt/market-sentinel/exports
chmod 700 /opt/market-sentinel/exports
```

Run the export, checksum, and upload in the same shell block so the timestamp remains consistent:

```bash
cd /opt/market-sentinel
STAMP=$(date +%Y%m%d-%H%M%S)
FILE="score-history-${STAMP}.jsonl"

# Export through a one-off bind mount.
docker compose run --rm \
  -v /opt/market-sentinel/exports:/exports \
  web \
  flask --app wsgi sentinel export-history \
  --output "/exports/${FILE}" \
  --format jsonl \
  --include-lineage \
  --include-revisions

# Create checksum.
cd /opt/market-sentinel/exports
sha256sum "${FILE}" > "${FILE}.sha256"

# Upload both files.
aws s3 cp \
  "${FILE}" \
  "s3://YOUR-BACKUP-BUCKET/market-sentinel/exports/${FILE}"

aws s3 cp \
  "${FILE}.sha256" \
  "s3://YOUR-BACKUP-BUCKET/market-sentinel/exports/${FILE}.sha256"

# Verify the prefix listing.
aws s3 ls "s3://YOUR-BACKUP-BUCKET/market-sentinel/exports/"
```

Research exports complement RDS backups; they do not replace database backups.

### Suggested backup policy

- daily RDS automated backups;
- point-in-time recovery retained according to the recovery objective;
- manual RDS snapshot before significant deployments;
- monthly lineage export to versioned S3;
- checksum beside every export;
- quarterly restore test;
- indefinite research-history retention unless licensing requires otherwise.

Document who owns restore testing and how success is recorded.

---

# Part IX - Monitoring and operations

## 33. Create CloudWatch alarms

Consider alarms for:

### EC2

- `StatusCheckFailed` greater than zero;
- sustained high CPU;
- low disk space through the CloudWatch agent;
- memory pressure through the CloudWatch agent.

### ALB

- unhealthy host count;
- HTTP 5xx responses;
- target response time.

### RDS

- low free storage;
- high CPU;
- high database connections;
- low freeable memory;
- replication or Multi-AZ events when applicable.

Send alarm notifications through SNS to an owned operational address.

---

## 34. Useful commands

Container status:

```bash
cd /opt/market-sentinel
docker compose ps
```

Recent logs:

```bash
docker compose logs --tail=200 web
```

Live logs:

```bash
docker compose logs -f web
```

Local health:

```bash
curl -fsS http://127.0.0.1:8000/healthz
```

Disk usage:

```bash
df -h
docker system df
```

Research history:

```bash
docker compose run --rm web \
  flask --app wsgi sentinel history --limit 20
```

Public status:

```bash
curl -fsS https://sentinel.example.com/api/status
```

---

## 35. Rotate the cron log

Create `/etc/logrotate.d/market-sentinel`:

```bash
sudo tee /etc/logrotate.d/market-sentinel >/dev/null <<'EOF'
/var/log/market-sentinel-daily.log {
    weekly
    rotate 12
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
EOF
```

Dry-run the configuration:

```bash
sudo logrotate -d /etc/logrotate.d/market-sentinel
```

Docker container logs also need retention controls for long-running production use. Configure Docker daemon log rotation or centralized logging.

---

# Part X - Safe upgrades and rollback

## 36. Standard upgrade procedure

### Check the current state

```bash
cd /opt/market-sentinel
git status
docker compose ps
curl -fsS http://127.0.0.1:8000/healthz
```

Do not continue when unexplained local Git changes exist.

### Back up

- create a manual RDS snapshot;
- optionally export research history to S3;
- record the current commit:

```bash
git rev-parse HEAD
```

### Pull reviewed code

```bash
git fetch origin
git switch main
git pull --ff-only origin main
```

### Update code lineage

```bash
git rev-parse HEAD
nano .env
```

Paste the new SHA into `APP_GIT_SHA`.

### Build and apply additive setup

```bash
docker compose build --pull

docker compose run --rm web \
  flask --app wsgi sentinel init-db

docker compose run --rm web \
  flask --app wsgi sentinel migrate-history
```

The current setup is additive and idempotent. Future releases may introduce a dedicated migration framework; always read release notes.

### Recreate and verify

```bash
docker compose up -d
docker compose ps
docker compose logs --tail=100 web
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS https://sentinel.example.com/healthz
```

Confirm the ALB target is healthy.

After the deployment is stable, remove only unused images:

```bash
docker image prune
```

Do not use aggressive prune commands without understanding which volumes and images will be removed.

---

## 37. Rollback outline

For an application-only failure:

1. record the failing commit and logs;
2. switch to the previous known-good commit;
3. rebuild and restart;
4. verify locally and through the ALB.

Example:

```bash
cd /opt/market-sentinel
git switch --detach PREVIOUS_GOOD_COMMIT
docker compose build
docker compose up -d
curl -fsS http://127.0.0.1:8000/healthz
```

For database rollback, restore an RDS snapshot or point-in-time backup to a **new RDS instance**, validate it, update `DATABASE_URL`, and recreate the container.

Checking out old code does not automatically reverse database changes.

---

# Part XI - Troubleshooting

## ALB target is unhealthy

Check in order:

1. Container is running:

```bash
cd /opt/market-sentinel
docker compose ps
```

2. Local health succeeds:

```bash
curl -v http://127.0.0.1:8000/healthz
```

3. Port `8000` is listening:

```bash
sudo ss -lntp | grep 8000
```

4. Target group uses:

```text
Protocol: HTTP
Port: 8000
Path: /healthz
Success code: 200
```

5. EC2 security group allows `8000` from the ALB security group.
6. ALB and EC2 use the same VPC.
7. The target is in an Availability Zone enabled on the ALB.

Do not open port `8000` to the whole internet as a workaround.

---

## ALB returns 502

Check:

```bash
docker compose logs --tail=200 web
curl -v http://127.0.0.1:8000/
```

Common causes:

- container exited;
- startup failed because of database configuration;
- target group uses the wrong port;
- security group blocks ALB traffic;
- Gunicorn is still starting or memory is insufficient.

---

## RDS connection times out

Check:

- RDS status is **Available**;
- EC2 and RDS use the same VPC;
- RDS uses `market-sentinel-rds-sg`;
- RDS security group permits `5432` from `market-sentinel-ec2-sg`;
- endpoint and port are correct;
- network ACLs are not blocking traffic.

Test with `psql` before changing application code.

---

## PostgreSQL authentication fails

Check:

- username;
- password;
- initial database name;
- URL encoding of special characters;
- accidental spaces or quotes in `DATABASE_URL`;
- environment reloaded after editing `.env`.

Reload:

```bash
docker compose up -d --force-recreate web
```

---

## Docker permission denied

Check:

```bash
whoami
id
```

This guide expects `ubuntu` with membership in `docker`.

Fix membership:

```bash
sudo usermod -aG docker ubuntu
```

Log out and reconnect. When using Session Manager, switch with `sudo -iu ubuntu`.

---

## FRED indicators are unavailable

Check:

- `FRED_API_KEY` is present;
- EC2 has outbound HTTPS;
- the series observation has been published;
- application logs show series status.

A missing FRED key reduces coverage but does not prevent all available indicators from being calculated.

---

## OpenAI commentary is missing

Check:

```dotenv
OPENAI_ENABLED=true
OPENAI_API_KEY=...
```

Inspect:

```bash
docker compose logs --tail=200 web
```

The deterministic score is stored before commentary generation. An OpenAI outage should not erase the quantitative result.

---

## Mailgun email is not delivered

Check:

- domain verification;
- sender belongs to verified domain;
- API base matches Mailgun region;
- sandbox recipient restrictions;
- recipient spelling;
- Mailgun activity logs;
- application logs.

Keep email and alerts disabled until forced test sends work.

---

## HTTPS certificate warning

Check:

- ACM status is **Issued**;
- certificate and ALB are in the same Region;
- certificate includes the exact hostname;
- HTTPS listener uses the certificate;
- Route 53 points to the correct ALB;
- DNS has propagated.

The ALB AWS DNS name does not match a certificate issued only for `sentinel.example.com`.

---

## Cron did not run

Check:

```bash
whoami
timedatectl
crontab -l
systemctl status cron
tail -n 200 /var/log/market-sentinel-daily.log
```

Run manually as `ubuntu`:

```bash
/usr/local/bin/market-sentinel-daily
```

Confirm:

- cron belongs to the `ubuntu` user;
- `ubuntu` belongs to `docker`;
- the lock file is writable by `ubuntu`;
- the script uses the actual absolute paths returned by `command -v`.

---

## Disk space is low

Check:

```bash
df -h
docker system df
```

Review old images and logs. Expand the EBS volume when appropriate, then extend the partition and filesystem according to current EC2 documentation.

Do not delete Docker volumes blindly; the SQLite fallback database and other persistent data may reside in a volume.

---

# Part XII - Security and final checklists

## Security hardening checklist

- [ ] AWS root user has MFA and is not used for daily administration.
- [ ] EC2 uses an IAM role instead of stored AWS access keys.
- [ ] SSH is disabled or restricted to a known IP.
- [ ] EC2 port `8000` is allowed only from the ALB security group.
- [ ] RDS port `5432` is allowed only from the EC2 security group.
- [ ] RDS public access is disabled.
- [ ] RDS storage encryption is enabled.
- [ ] RDS backups and deletion protection are configured.
- [ ] `.env` is mode `600` and not committed.
- [ ] OpenAI, Mailgun, FRED, and database secrets are stored in a password manager.
- [ ] HTTPS is enforced at the ALB.
- [ ] ACM certificate uses supported managed renewal.
- [ ] S3 Block Public Access is enabled.
- [ ] S3 versioning is enabled for backup artifacts.
- [ ] CloudWatch alarms have an owned destination.
- [ ] Application and cron logs have retention controls.
- [ ] Restore procedures have been tested.
- [ ] Provider licensing permits retained data and exports.

For stronger secret management, add a deployment process that retrieves values from AWS Secrets Manager or Systems Manager Parameter Store and writes the runtime environment securely. The application currently reads standard environment variables and does not directly call those services.

## Final deployment checklist

### AWS resources

- [ ] IAM EC2 role created and attached.
- [ ] ALB, EC2, and RDS security groups created.
- [ ] EC2 launched and patched.
- [ ] Docker Engine and Compose installed.
- [ ] RDS PostgreSQL created privately.
- [ ] Target group created with `/healthz`.
- [ ] ACM certificate issued.
- [ ] ALB created with HTTPS and HTTP redirect.
- [ ] Route 53 alias points to the ALB.

### Market Sentinel

- [ ] Session standardized to the `ubuntu` user.
- [ ] Repository cloned into `/opt/market-sentinel`.
- [ ] `.env` configured and protected.
- [ ] RDS connection tested with `psql`.
- [ ] Docker image built.
- [ ] `sentinel init-db` completed.
- [ ] `sentinel migrate-history` completed.
- [ ] Container is healthy.
- [ ] First refresh completed.
- [ ] Public dashboard and APIs verified.
- [ ] Optional OpenAI test completed.
- [ ] Optional Mailgun test completed.
- [ ] Daily script tested manually and cron installed.
- [ ] Backups and alarms configured.

---

# Appendices

## Appendix A: Lower-cost single-EC2 deployment

For a temporary demonstration, you can omit ALB and RDS and use:

- one EC2 instance;
- the Docker Compose SQLite volume;
- an Elastic IP;
- Caddy or Nginx with an automatically managed certificate;
- Route 53 pointing directly to the Elastic IP.

Limitations:

- single point of failure;
- SQLite volume requires deliberate backups;
- TLS management occurs on EC2 rather than ALB + ACM;
- scaling to multiple instances is not straightforward;
- EC2 ports `80` and `443` must be public;
- reverse-proxy configuration is required.

ALB + RDS is more suitable for durable research history and operational growth.

---

## Appendix B: Why an Elastic IP is optional

When Route 53 points to an ALB:

- the public endpoint is the ALB;
- the ALB DNS name is the routing target;
- the EC2 public IP is not published;
- replacing EC2 does not require public DNS changes when the new instance is registered in the target group.

An Elastic IP can be useful for a stable administrative address in a simple public-subnet deployment, but Session Manager is preferred.

---

## Appendix C: AWS-native scheduling alternative

A host cron job is simplest for one instance.

A more AWS-native design can use EventBridge Scheduler to invoke:

- Systems Manager Run Command on EC2;
- an ECS task running the CLI;
- a Lambda wrapper where runtime and dependency constraints are addressed.

Do not run APScheduler inside every Gunicorn worker. Multiple workers can execute the same job more than once.

---

## Appendix D: Teardown

To avoid unexpected costs:

1. export research history and verify the backup;
2. create a final RDS snapshot when required;
3. delete or stop scheduled jobs;
4. delete the ALB and target group;
5. terminate EC2;
6. delete RDS only after confirming final-snapshot requirements;
7. release unused Elastic IPs;
8. delete unused EBS snapshots and volumes according to policy;
9. remove Route 53 records and optionally the hosted zone;
10. delete unused ACM certificates;
11. empty and delete S3 buckets only when retention obligations permit;
12. remove unused IAM roles and policies;
13. review AWS Cost Explorer for remaining resources.

Deletion protection must be disabled before deleting a protected RDS instance.

---

# Official references

- EC2 security groups: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/creating-security-group.html
- Systems Manager instance permissions: https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-getting-started-instance-profile.html
- RDS PostgreSQL getting started: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/CHAP_GettingStarted.CreatingConnecting.PostgreSQL.html
- Automatic EC2-to-RDS connectivity: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/ec2-rds-connect.html
- RDS automated backups: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_WorkingWithAutomatedBackups.html
- Create an Application Load Balancer: https://docs.aws.amazon.com/elasticloadbalancing/latest/application/create-application-load-balancer.html
- Create a target group: https://docs.aws.amazon.com/elasticloadbalancing/latest/application/create-target-group.html
- ALB target health checks: https://docs.aws.amazon.com/elasticloadbalancing/latest/application/target-group-health-checks.html
- Create an HTTPS listener: https://docs.aws.amazon.com/elasticloadbalancing/latest/application/create-https-listener.html
- Request an ACM public certificate: https://docs.aws.amazon.com/acm/latest/userguide/acm-public-certificates.html
- ACM DNS validation: https://docs.aws.amazon.com/acm/latest/userguide/dns-validation.html
- Route 53 alias to an ELB load balancer: https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/routing-to-elb-load-balancer.html
- S3 bucket versioning: https://docs.aws.amazon.com/AmazonS3/latest/userguide/manage-versioning-examples.html
- AWS CLI installation: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html
- CloudWatch agent: https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Install-CloudWatch-Agent.html
- Docker Engine on Ubuntu: https://docs.docker.com/engine/install/ubuntu/
- Docker Compose plugin: https://docs.docker.com/compose/install/linux/
