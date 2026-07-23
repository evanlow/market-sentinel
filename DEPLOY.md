# Deploy Market Sentinel to AWS

This guide explains, step by step, how to deploy Market Sentinel to AWS in a secure and maintainable way.

The recommended deployment uses:

- **Amazon Route 53** for DNS;
- **AWS Certificate Manager (ACM)** for a managed TLS certificate;
- **Application Load Balancer (ALB)** for HTTPS termination and health checks;
- **Amazon EC2** running Ubuntu and Docker Compose;
- **Amazon RDS for PostgreSQL** for persistent application and research history;
- **AWS Systems Manager Session Manager** for administrative access without exposing SSH;
- **Amazon S3** for optional versioned research exports and backup artifacts;
- a host **cron job** for the daily Market Sentinel run.

> [!IMPORTANT]
> Market Sentinel is a risk-monitoring application, not a crash-prediction or investment-advice system. Deployment does not remove data-provider limitations, false positives, false negatives, or model risk.

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

The application itself continues to listen on port `8000` inside the VPC. Only the ALB is publicly reachable on ports `80` and `443`.

---

## 2. Recommended sizing

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

---

## 3. Cost awareness

The following resources normally incur ongoing charges:

- Application Load Balancer;
- EC2 instance and EBS volume;
- public IPv4 address attached to EC2;
- RDS instance, storage, backups beyond included allowances, and data transfer;
- Route 53 hosted zone and DNS queries;
- S3 storage and requests;
- CloudWatch logs, metrics, and alarms beyond included allowances.

For a temporary demonstration, see [Appendix A: Lower-cost single-EC2 deployment](#appendix-a-lower-cost-single-ec2-deployment).

---

## 4. Prerequisites

Before starting, prepare the following:

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

---

## 5. Fill in the deployment worksheet

Choose your values before provisioning resources.

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

The examples in this guide use:

```text
AWS Region: ap-southeast-1
Domain: sentinel.example.com
Application directory: /opt/market-sentinel
Container port: 8000
PostgreSQL port: 5432
```

Replace example values with your own values.

---

# Part I - Prepare AWS networking and access

## 6. Choose the VPC approach

### Approach 1: Existing or default VPC

This is the simplest first deployment.

Confirm that the VPC has:

- at least two subnets in different Availability Zones for the ALB;
- an internet gateway;
- a route to the internet from the subnets used by the ALB;
- DNS resolution and DNS hostnames enabled.

The EC2 instance can be placed in one public subnet with a public IPv4 address for outbound access. RDS must be set to **Public access: No**.

### Approach 2: Dedicated production VPC

A more isolated design uses:

- two public subnets in different Availability Zones for the ALB;
- one public application subnet for the first EC2 instance, or private application subnets with NAT;
- two private database subnets for RDS;
- separate route tables by tier.

This guide works for either design. The most important rules are:

1. ALB, EC2, and RDS must be in the same VPC unless you intentionally design cross-VPC connectivity.
2. RDS should not be publicly accessible.
3. Security groups should reference one another instead of allowing broad public access.

---

## 7. Create the three security groups

Open **AWS Console -> EC2 -> Network & Security -> Security Groups**.

Create all three groups in the same VPC.

### 7.1 ALB security group

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

- TCP `8000` to `market-sentinel-ec2-sg` if your console permits selecting the EC2 security group as the destination; or
- temporarily retain the default outbound rule and tighten it after the target is healthy.

### 7.2 EC2 application security group

Name:

```text
market-sentinel-ec2-sg
```

Inbound rules:

| Type | Port | Source | Purpose |
|---|---:|---|---|
| Custom TCP | 8000 | `market-sentinel-alb-sg` | ALB traffic and health checks |

Do **not** allow port `8000` from `0.0.0.0/0`.

Administrative access options:

- **Recommended:** use Systems Manager Session Manager and do not add port `22`.
- **Fallback:** add SSH port `22` from **My IP** only, never from the whole internet.

For the initial deployment, leaving the default outbound rule is simplest because the application needs outbound HTTPS access to market-data providers, FRED, OpenAI, Mailgun, GitHub, Docker registries, and Ubuntu repositories.

### 7.3 RDS security group

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

## 8. Create an EC2 IAM role

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

Later, attach this role to the EC2 instance.

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

## 9. Launch the EC2 instance

Open **EC2 -> Instances -> Launch instances**.

### 9.1 Name and operating system

Name:

```text
market-sentinel-app
```

Choose:

```text
Ubuntu Server 24.04 LTS, 64-bit (x86)
```

### 9.2 Instance type

Recommended starting point:

```text
t3.small
```

A smaller instance may be used for a short demonstration, but monitor memory and build reliability.

### 9.3 Key pair

When using Session Manager only, a key pair is not technically required. Keeping a securely stored recovery key pair can still be useful.

When using PuTTY:

- create or select a key pair;
- download the private key once;
- convert a `.pem` file to `.ppk` with PuTTYgen when required;
- never email or commit the private key.

### 9.4 Network settings

Select:

- the selected VPC;
- a subnet with outbound internet access;
- **Auto-assign public IP: Enable** for the simple public-subnet design;
- existing security group: `market-sentinel-ec2-sg`.

The public IP is for outbound connectivity and administration. Application users will access the ALB, not the EC2 public IP.

An Elastic IP is optional. It is not needed for the public application endpoint when Route 53 points to the ALB.

### 9.5 Storage

Configure approximately:

```text
30 GiB gp3, encrypted
```

Enable delete-on-termination only when your backup and recovery plan is understood.

### 9.6 Advanced details

Select IAM instance profile:

```text
MarketSentinelEC2Role
```

Do not place API keys or passwords in EC2 user data.

### 9.7 Tags

Suggested tags:

```text
Project = market-sentinel
Environment = production
Owner = YOUR-NAME
```

Launch the instance and wait for both EC2 status checks to pass.

---

## 10. Connect to EC2

### Recommended: Systems Manager Session Manager

Open:

```text
EC2 -> Instances -> market-sentinel-app -> Connect -> Session Manager
```

Choose **Connect**.

If Session Manager is unavailable, check:

- the IAM role is attached;
- the instance has outbound HTTPS access;
- the SSM agent is installed and running;
- the instance and Systems Manager are in the same AWS Region view.

### Fallback: SSH

Ubuntu uses the username:

```text
ubuntu
```

Example OpenSSH command:

```bash
ssh -i /safe/path/market-sentinel.pem ubuntu@EC2_PUBLIC_IP
```

For PuTTY, use the EC2 public IP, port `22`, username `ubuntu`, and the `.ppk` key under **Connection -> SSH -> Auth -> Credentials**.

Restrict the SSH security-group rule to your current public IP.

---

## 11. Update Ubuntu and set the timezone

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

Use a different IANA timezone when the operator is not in Singapore.

Reboot when Ubuntu reports that a restart is required:

```bash
sudo reboot
```

Reconnect after the instance returns to the running state.

---

## 12. Install Docker Engine and Docker Compose

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

Allow the `ubuntu` user to run Docker:

```bash
sudo usermod -aG docker ubuntu
```

End the session and reconnect so the group membership is refreshed.

Then verify without `sudo`:

```bash
docker version
docker compose version
```

> [!CAUTION]
> Membership in the Docker group grants powerful host-level capabilities. Limit administrative access to trusted operators.

---

## 13. Clone Market Sentinel

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

Verify the branch and commit:

```bash
git status
git branch --show-current
git log -1 --oneline
```

The production deployment should normally use the `main` branch after the desired pull requests have been reviewed and merged.

---

# Part III - Create PostgreSQL on Amazon RDS

## 14. Create the RDS PostgreSQL database

Open **RDS -> Databases -> Create database**.

### 14.1 Creation method and engine

Choose:

- **Standard create**;
- engine: **PostgreSQL**;
- a currently supported PostgreSQL major version.

Do not select an engine version solely because it is the newest. Confirm that it is generally available in your Region and supported by your operational policy.

### 14.2 Template

Choose:

- **Dev/Test** or the smallest eligible option for a demonstration;
- **Production** for a production-critical deployment.

### 14.3 Settings

DB instance identifier:

```text
market-sentinel-db
```

Master username:

```text
market_sentinel_admin
```

Generate a strong password and store it in a password manager. Do not put it into GitHub or resource tags.

### 14.4 Availability and durability

- Single-AZ is sufficient for a personal MVP.
- Multi-AZ is recommended when database availability is business-critical.

### 14.5 Instance and storage

Choose a small instance class suitable for the workload.

Suggested initial storage:

```text
20 GiB gp3, encrypted
```

Enable storage autoscaling and choose a sensible maximum.

### 14.6 Connectivity

Configure:

- VPC: the same VPC as EC2;
- public access: **No**;
- VPC security group: `market-sentinel-rds-sg`;
- database port: `5432`.

If the console offers **Connect to an EC2 compute resource**, selecting the Market Sentinel EC2 instance can automatically configure connectivity. Review the resulting security groups and make sure the effective rule remains PostgreSQL `5432` from the EC2 security group only.

### 14.7 Additional configuration

Initial database name:

```text
market_sentinel
```

Recommended settings:

- automated backups enabled;
- retention: at least 7 days for an MVP, longer when required;
- deletion protection enabled for production;
- automatic minor-version upgrades according to your maintenance policy;
- Performance Insights or Enhanced Monitoring when operationally useful;
- CloudWatch log exports when needed.

Create the database and wait until its status is **Available**.

---

## 15. Record the RDS endpoint

Open the database and choose **Connectivity & security**.

Copy:

- endpoint, for example `market-sentinel-db.xxxxxxxxx.ap-southeast-1.rds.amazonaws.com`;
- port `5432`.

The endpoint is a DNS name. Do not substitute an IP address.

---

## 16. Test RDS connectivity from EC2

On EC2, install the PostgreSQL client:

```bash
sudo apt-get install -y postgresql-client
```

Connect without putting the password into shell history:

```bash
psql \
  "host=YOUR_RDS_ENDPOINT port=5432 dbname=market_sentinel user=market_sentinel_admin sslmode=require"
```

Enter the password at the prompt.

Inside `psql`, run:

```sql
SELECT current_database(), current_user, version();
```

Exit:

```text
\q
```

If the connection times out, check the RDS security group, EC2 security group, VPC, and route tables before changing the application.

---

# Part IV - Configure and start Market Sentinel

## 17. Create the production environment file

Go to the repository:

```bash
cd /opt/market-sentinel
```

Create `.env` securely:

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

Open the file:

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

### 17.1 URL-encode the database password

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

### 17.2 Start with optional integrations disabled

For the first deployment, keep:

```dotenv
OPENAI_ENABLED=false
DAILY_EMAIL_ENABLED=false
ALERTS_ENABLED=false
```

First prove that market collection, scoring, persistence, the dashboard, and RDS work. Enable optional services one at a time afterward.

### 17.3 Recheck file permissions

```bash
ls -l .env
```

The file should not be readable by other users.

---

## 18. Validate the Compose configuration

Run:

```bash
cd /opt/market-sentinel
docker compose config
```

Review the output for:

- the `web` service;
- port mapping `8000:8000`;
- the expected environment variables;
- no unexpected paths.

`docker compose config` can display resolved environment values. Do not paste its output into tickets, screenshots, or chat messages because it may contain secrets.

---

## 19. Build the Docker image

```bash
cd /opt/market-sentinel
docker compose build --pull
```

The first build can take several minutes.

Verify that the image exists:

```bash
docker images | head
```

---

## 20. Initialize the database

Create the operational and research-history tables:

```bash
docker compose run --rm web \
  flask --app wsgi sentinel init-db
```

For an existing installation containing legacy `snapshots`, run the idempotent migration:

```bash
docker compose run --rm web \
  flask --app wsgi sentinel migrate-history
```

On a brand-new database, the migration can safely report zero migrated rows.

---

## 21. Start the application

```bash
docker compose up -d
```

Check container status:

```bash
docker compose ps
```

Check logs:

```bash
docker compose logs --tail=100 web
```

Follow logs live when troubleshooting:

```bash
docker compose logs -f web
```

Exit live logs with `Ctrl+C`; this does not stop the container.

---

## 22. Test the application on EC2

Health check:

```bash
curl -fsS http://127.0.0.1:8000/healthz
```

Expected response:

```json
{"status":"ok"}
```

Test the dashboard headers:

```bash
curl -I http://127.0.0.1:8000/
```

Test the current status API:

```bash
curl -fsS http://127.0.0.1:8000/api/status
```

A fresh deployment may return a no-data response until the first refresh is completed.

Do not open EC2 port `8000` publicly just to perform this test. Test locally on the host.

---

## 23. Run the first market refresh

Run without OpenAI first:

```bash
docker compose run --rm web \
  flask --app wsgi sentinel refresh --no-ai
```

Then check:

```bash
curl -fsS http://127.0.0.1:8000/api/status
```

Inspect history:

```bash
docker compose run --rm web \
  flask --app wsgi sentinel history --limit 10
```

If FRED is not configured, the application can still calculate available market indicators, but data coverage will be reduced.

---

## 24. Optionally enter FINRA margin debt

FINRA margin debt is monthly and is stored as an auditable manual observation.

Example:

```bash
docker compose run --rm web \
  flask --app wsgi sentinel set-margin-debt \
  --value 1000000 \
  --as-of 2026-05-31 \
  --source-url "https://www.finra.org/rules-guidance/key-topics/margin-accounts/margin-statistics" \
  --notes "Entered from the FINRA monthly margin statistics release"
```

Replace the value and date with the actual published observation.

Run another refresh after updating the monthly value.

---

# Part V - Put the application behind HTTPS

## 25. Create the ALB target group

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

Health check settings:

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

Register the `market-sentinel-app` EC2 instance on port `8000`.

Wait for the target to become **Healthy**.

If it remains unhealthy, see [Troubleshooting ALB health checks](#alb-target-is-unhealthy).

---

## 26. Request an ACM certificate

Open **AWS Certificate Manager** in the **same Region as the ALB**.

1. Choose **Request a certificate**.
2. Choose **Request a public certificate**.
3. Enter the fully qualified domain name, for example:

```text
sentinel.example.com
```

4. Choose **DNS validation**.
5. Request the certificate.
6. Open the certificate details.
7. When Route 53 hosts the domain, choose **Create records in Route 53**.
8. Wait for status **Issued**.

For a wildcard certificate such as `*.example.com`, remember that the wildcard does not automatically cover the apex `example.com`.

---

## 27. Create the Application Load Balancer

Open **EC2 -> Load Balancing -> Load Balancers -> Create load balancer -> Application Load Balancer**.

Configure:

| Setting | Value |
|---|---|
| Name | `market-sentinel-alb` |
| Scheme | Internet-facing |
| IP address type | IPv4, or Dualstack when IPv6 is intentionally configured |
| VPC | Same VPC as EC2 |
| Mappings | At least two public subnets in different Availability Zones |
| Security group | `market-sentinel-alb-sg` |

Listeners:

### HTTPS listener

- protocol: HTTPS;
- port: `443`;
- default action: forward to `market-sentinel-tg`;
- certificate: the issued ACM certificate;
- security policy: use the current AWS recommended policy unless your organization requires another approved policy.

### HTTP listener

- protocol: HTTP;
- port: `80`;
- default action: redirect to HTTPS;
- destination port: `443`;
- status code: `HTTP_301`.

Create the load balancer.

Wait for the ALB state to become **Active** and confirm the target group remains healthy.

---

## 28. Test the ALB DNS name

Open the ALB details and copy its DNS name.

Test HTTP redirection:

```bash
curl -I http://YOUR_ALB_DNS_NAME
```

Test HTTPS after the custom domain is configured. Browsers will not consider the ALB's AWS DNS name to match a certificate issued only for your custom domain.

---

## 29. Create the Route 53 alias record

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

Create the record.

When using dual-stack, also create the appropriate AAAA alias record.

If DNS is hosted outside Route 53, create the provider's equivalent CNAME for a subdomain. Apex-domain handling varies by DNS provider.

---

## 30. Verify the public deployment

Run from your computer:

```bash
curl -I https://sentinel.example.com/
curl -fsS https://sentinel.example.com/healthz
curl -fsS https://sentinel.example.com/api/status
```

Open in a browser:

```text
https://sentinel.example.com
```

Confirm:

- the browser shows a valid certificate;
- HTTP redirects to HTTPS;
- the dashboard loads;
- `/healthz` returns `200`;
- the ALB target remains healthy;
- port `8000` is not reachable directly from the public internet.

---

# Part VI - Enable optional integrations

## 31. Enable OpenAI commentary

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

Recreate the web container so the changed environment is loaded:

```bash
docker compose up -d --force-recreate web
```

Test a refresh:

```bash
docker compose run --rm web \
  flask --app wsgi sentinel refresh
```

OpenAI commentary explains deterministic results. It does not set or alter the score.

---

## 32. Configure Mailgun

Edit `.env` and set:

```dotenv
MAILGUN_API_KEY=YOUR_MAILGUN_API_KEY
MAILGUN_DOMAIN=YOUR_VERIFIED_MAILGUN_DOMAIN
MAILGUN_FROM_EMAIL="Market Sentinel <alerts@YOUR_VERIFIED_MAILGUN_DOMAIN>"
MAILGUN_RECIPIENTS=recipient1@example.com,recipient2@example.com
MAILGUN_API_BASE=https://api.mailgun.net
DAILY_EMAIL_ENABLED=false
ALERTS_ENABLED=false
```

For a Mailgun EU-region domain, use:

```dotenv
MAILGUN_API_BASE=https://api.eu.mailgun.net
```

Reload the container:

```bash
docker compose up -d --force-recreate web
```

Test the daily email without permanently enabling it:

```bash
docker compose run --rm web \
  flask --app wsgi sentinel send-daily --force
```

Test an alert:

```bash
docker compose run --rm web \
  flask --app wsgi sentinel evaluate-alert --force
```

Only after both tests succeed, decide whether to enable:

```dotenv
DAILY_EMAIL_ENABLED=true
ALERTS_ENABLED=true
```

Reload the container again after editing `.env`.

Mailgun sandbox domains normally restrict recipients. Use a verified sending domain for normal operations.

---

# Part VII - Schedule daily collection and emails

## 33. Create the daily runner script

Confirm command locations:

```bash
command -v docker
command -v flock
```

Create the script:

```bash
sudo tee /usr/local/bin/market-sentinel-daily >/dev/null <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail

cd /opt/market-sentinel

exec /usr/bin/flock -n /var/lock/market-sentinel-daily.lock \
  /usr/bin/docker compose run --rm web \
  flask --app wsgi sentinel run-daily
EOF
```

Make it executable:

```bash
sudo chmod 755 /usr/local/bin/market-sentinel-daily
```

Test it manually as the `ubuntu` user:

```bash
/usr/local/bin/market-sentinel-daily
```

Check the dashboard and logs before scheduling it.

---

## 34. Create the cron log

```bash
sudo touch /var/log/market-sentinel-daily.log
sudo chown ubuntu:ubuntu /var/log/market-sentinel-daily.log
```

---

## 35. Add the cron schedule

Open the `ubuntu` user's crontab:

```bash
crontab -e
```

Add:

```cron
0 7 * * 2-6 /usr/local/bin/market-sentinel-daily >> /var/log/market-sentinel-daily.log 2>&1
```

This runs at **07:00 Singapore time, Tuesday through Saturday** after the corresponding completed US trading sessions.

Confirm the host timezone:

```bash
timedatectl
```

Confirm the cron entry:

```bash
crontab -l
```

Check the log after the first scheduled run:

```bash
tail -n 200 /var/log/market-sentinel-daily.log
```

The `flock` lock prevents overlapping daily jobs.

> [!NOTE]
> A public holiday or provider delay may mean the latest market date has not advanced. Market Sentinel's input hashing and revision logic prevents identical data from creating duplicate research runs.

---

# Part VIII - Backups and research retention

## 36. Configure RDS backups

In **RDS -> Databases -> market-sentinel-db -> Modify**, confirm:

- automated backups are enabled;
- backup retention meets your recovery objective;
- deletion protection is enabled for production;
- the preferred backup window is documented;
- storage autoscaling is configured;
- final snapshot behavior is understood before deletion.

Create a manual snapshot before:

- major application upgrades;
- database-related code changes;
- credential rotation;
- destructive maintenance.

RDS point-in-time recovery creates a new database instance. Test the complete restore and reconnection process periodically.

---

## 37. Create an optional S3 backup bucket

Open **S3 -> Create bucket**.

Recommended configuration:

- unique bucket name;
- same Region as the application when practical;
- Block Public Access: all enabled;
- bucket versioning: enabled;
- default encryption: enabled;
- lifecycle rules for older noncurrent versions when appropriate;
- no public website hosting.

Example bucket name:

```text
YOUR-ACCOUNT-market-sentinel-backups
```

Attach the narrowly scoped S3 policy from [Create an EC2 IAM role](#8-create-an-ec2-iam-role) to the EC2 role.

---

## 38. Install AWS CLI v2 for S3 uploads

On x86_64 Ubuntu:

```bash
cd /tmp
curl -fsS "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" \
  -o awscliv2.zip
unzip -q awscliv2.zip
sudo ./aws/install
rm -rf aws awscliv2.zip
```

Verify that the EC2 IAM role is being used:

```bash
aws sts get-caller-identity
```

Do not configure long-lived AWS access keys on EC2 when an instance role can provide the required permissions.

---

## 39. Export research history

Create a host export directory:

```bash
sudo mkdir -p /opt/market-sentinel/exports
sudo chown ubuntu:ubuntu /opt/market-sentinel/exports
```

Create a full JSON Lines export:

```bash
cd /opt/market-sentinel
STAMP=$(date +%Y%m%d-%H%M%S)

docker compose run --rm \
  -v /opt/market-sentinel/exports:/exports \
  web \
  flask --app wsgi sentinel export-history \
  --output "/exports/score-history-${STAMP}.jsonl" \
  --format jsonl \
  --include-lineage \
  --include-revisions
```

Create a checksum:

```bash
cd /opt/market-sentinel/exports
sha256sum "score-history-${STAMP}.jsonl" \
  > "score-history-${STAMP}.jsonl.sha256"
```

Upload both files:

```bash
aws s3 cp \
  "score-history-${STAMP}.jsonl" \
  "s3://YOUR-BACKUP-BUCKET/market-sentinel/exports/"

aws s3 cp \
  "score-history-${STAMP}.jsonl.sha256" \
  "s3://YOUR-BACKUP-BUCKET/market-sentinel/exports/"
```

Verify:

```bash
aws s3 ls "s3://YOUR-BACKUP-BUCKET/market-sentinel/exports/"
```

Research exports complement RDS backups; they do not replace database backups.

---

## 40. Suggested backup policy

A practical starting policy is:

- daily RDS automated backups;
- RDS point-in-time recovery retained according to the recovery objective;
- a manual RDS snapshot before each significant deployment;
- monthly lineage export to versioned S3;
- checksum stored beside every export;
- quarterly restore test;
- indefinite retention of research history unless data licensing requires otherwise.

Document who owns restore testing and how success is recorded.

---

# Part IX - Monitoring and operations

## 41. Create CloudWatch alarms

At minimum, consider alarms for:

### EC2

- `StatusCheckFailed` greater than zero;
- sustained high CPU;
- low disk space through the CloudWatch agent;
- memory pressure through the CloudWatch agent.

### ALB

- unhealthy host count;
- elevated HTTP 5xx responses;
- increased target response time.

### RDS

- low free storage;
- high CPU;
- high database connections;
- low freeable memory;
- replica or Multi-AZ events when applicable.

Send alarm notifications through an SNS topic to an operational email address.

---

## 42. Useful operational commands

### Container status

```bash
cd /opt/market-sentinel
docker compose ps
```

### Recent logs

```bash
docker compose logs --tail=200 web
```

### Live logs

```bash
docker compose logs -f web
```

### Health check

```bash
curl -fsS http://127.0.0.1:8000/healthz
```

### Disk space

```bash
df -h
docker system df
```

### Research history

```bash
docker compose run --rm web \
  flask --app wsgi sentinel history --limit 20
```

### Latest public status

```bash
curl -fsS https://sentinel.example.com/api/status
```

---

## 43. Log rotation

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

Test the configuration:

```bash
sudo logrotate -d /etc/logrotate.d/market-sentinel
```

The Docker logging driver also needs a retention policy for long-running production use. Configure Docker daemon log rotation or send logs to a centralized logging service.

---

# Part X - Safe application upgrades

## 44. Standard upgrade procedure

### 44.1 Check the current state

```bash
cd /opt/market-sentinel
git status
docker compose ps
curl -fsS http://127.0.0.1:8000/healthz
```

Do not continue when there are unexplained local Git changes.

### 44.2 Create a backup

- create a manual RDS snapshot;
- optionally export research history to S3;
- record the currently deployed commit:

```bash
git rev-parse HEAD
```

### 44.3 Pull reviewed code

```bash
git fetch origin
git switch main
git pull --ff-only origin main
```

### 44.4 Update `APP_GIT_SHA`

```bash
git rev-parse HEAD
nano .env
```

Paste the new commit SHA into `APP_GIT_SHA`.

### 44.5 Build the new image

```bash
docker compose build --pull
```

### 44.6 Apply additive database setup

```bash
docker compose run --rm web \
  flask --app wsgi sentinel init-db

docker compose run --rm web \
  flask --app wsgi sentinel migrate-history
```

The current migration is additive and idempotent. Future releases may introduce a dedicated migration framework; always read release notes before upgrading.

### 44.7 Recreate the application

```bash
docker compose up -d
```

### 44.8 Verify

```bash
docker compose ps
docker compose logs --tail=100 web
curl -fsS http://127.0.0.1:8000/healthz
curl -fsS https://sentinel.example.com/healthz
```

Confirm the ALB target is healthy.

### 44.9 Clean unused images carefully

After the new deployment has been stable:

```bash
docker image prune
```

Do not run aggressive Docker prune commands without understanding which volumes and images will be removed.

---

## 45. Rollback outline

When an application-only deployment fails:

1. record the failing commit and logs;
2. switch to the previously recorded known-good commit;
3. rebuild and restart;
4. verify health locally and through the ALB.

Example:

```bash
cd /opt/market-sentinel
git switch --detach PREVIOUS_GOOD_COMMIT
docker compose build
docker compose up -d
curl -fsS http://127.0.0.1:8000/healthz
```

When database state must be rolled back, restore the RDS snapshot or point-in-time backup to a **new RDS instance**, validate it, update `DATABASE_URL`, and recreate the container.

Do not assume that checking out old code automatically reverses database changes.

---

# Part XI - Troubleshooting

## ALB target is unhealthy

Check in this order:

1. Container is running:

```bash
cd /opt/market-sentinel
docker compose ps
```

2. Local health check succeeds:

```bash
curl -v http://127.0.0.1:8000/healthz
```

3. Docker is listening on port 8000:

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

5. EC2 security group allows port `8000` from the ALB security group.
6. ALB and EC2 are in the same VPC.
7. The target is registered in an Availability Zone enabled on the ALB.

Do not solve an unhealthy target by opening port `8000` to the whole internet.

---

## ALB returns 502 Bad Gateway

Check:

```bash
docker compose logs --tail=200 web
curl -v http://127.0.0.1:8000/
```

Common causes:

- container exited;
- application startup failed because of database configuration;
- target group points to the wrong port;
- EC2 security group blocks ALB traffic;
- Gunicorn is still starting or has insufficient memory.

---

## RDS connection times out

Check:

- RDS status is **Available**;
- EC2 and RDS use the same VPC;
- RDS is associated with `market-sentinel-rds-sg`;
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
- URL encoding of special password characters;
- `DATABASE_URL` does not contain accidental spaces or quotation marks;
- the environment was reloaded after editing `.env`.

Recreate the container after environment changes:

```bash
docker compose up -d --force-recreate web
```

---

## Docker permission denied

Confirm group membership:

```bash
id
```

If `docker` is missing:

```bash
sudo usermod -aG docker ubuntu
```

Log out and reconnect. Do not repeatedly use unsafe permission workarounds on the Docker socket.

---

## FRED indicators are unavailable

Check:

- `FRED_API_KEY` is present;
- EC2 can reach the internet over HTTPS;
- the provider has published the requested observation;
- application logs show the exact series status.

A missing FRED key reduces coverage but does not prevent all available indicators from being calculated.

---

## OpenAI commentary is missing

Check:

```dotenv
OPENAI_ENABLED=true
OPENAI_API_KEY=...
```

Then inspect logs:

```bash
docker compose logs --tail=200 web
```

The deterministic score is stored before commentary generation. An OpenAI outage should not erase the quantitative result.

---

## Mailgun email is not delivered

Check:

- Mailgun domain is verified;
- the sending address belongs to the verified domain;
- API base matches the Mailgun region;
- sandbox recipient restrictions;
- recipient spelling;
- Mailgun activity logs;
- Market Sentinel application logs.

Keep daily email and alerts disabled until forced test sends work.

---

## HTTPS certificate warning

Check:

- ACM certificate is **Issued**;
- certificate and ALB are in the same AWS Region;
- the certificate includes the exact public hostname;
- the HTTPS listener uses that certificate;
- Route 53 points the hostname to the correct ALB;
- DNS changes have propagated.

The ALB AWS DNS name will not match a certificate issued only for `sentinel.example.com`.

---

## Cron did not run

Check:

```bash
timedatectl
crontab -l
systemctl status cron
tail -n 200 /var/log/market-sentinel-daily.log
```

Run the script manually:

```bash
/usr/local/bin/market-sentinel-daily
```

Confirm the cron user belongs to the Docker group and that the script uses absolute command paths.

---

## Disk space is low

Check:

```bash
df -h
docker system df
```

Review old Docker images and logs. Expand the EBS volume when appropriate, then extend the partition and filesystem according to the current EC2 volume documentation.

Do not delete Docker volumes blindly; the SQLite fallback database and other persistent data may reside in a volume.

---

# Part XII - Security hardening checklist

Before calling the deployment production-ready, confirm:

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
- [ ] The ACM certificate is set for automatic managed renewal through supported AWS integration.
- [ ] S3 Block Public Access is enabled on backup buckets.
- [ ] S3 versioning is enabled for backup artifacts.
- [ ] CloudWatch alarms have an owned notification destination.
- [ ] Application and cron logs have retention controls.
- [ ] Restore procedures have been tested.
- [ ] Provider licensing permits the retained data and exports.

For stronger secret management, add a deployment process that retrieves values from AWS Secrets Manager or Systems Manager Parameter Store and writes the runtime environment securely. The current application reads standard environment variables and does not directly call those services.

---

# Part XIII - Final deployment checklist

## AWS resources

- [ ] IAM EC2 role created and attached.
- [ ] ALB, EC2, and RDS security groups created.
- [ ] EC2 launched and patched.
- [ ] Docker Engine and Compose installed.
- [ ] RDS PostgreSQL created privately.
- [ ] Target group created with `/healthz`.
- [ ] ACM certificate issued.
- [ ] ALB created with HTTPS and HTTP redirect.
- [ ] Route 53 alias points to the ALB.

## Market Sentinel

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
- [ ] Cron schedule tested manually and installed.
- [ ] Backups and alarms configured.

---

# Appendix A: Lower-cost single-EC2 deployment

For a temporary demonstration, you can omit ALB and RDS and use:

- one EC2 instance;
- the existing Docker Compose SQLite volume;
- an Elastic IP;
- Caddy or Nginx with an automatically managed certificate;
- Route 53 pointing directly to the Elastic IP.

This reduces infrastructure cost but has important limitations:

- one server is a single point of failure;
- the SQLite volume requires deliberate backups;
- TLS certificate management occurs on EC2 rather than through ALB + ACM;
- scaling to multiple app instances is not straightforward;
- direct public ports `80` and `443` must be opened on the EC2 security group;
- careful reverse-proxy configuration is required.

The recommended ALB + RDS design is more suitable for durable research history and operational growth.

---

# Appendix B: Why an Elastic IP is optional

When Route 53 points to an Application Load Balancer:

- the public application endpoint is the ALB;
- the ALB DNS name remains the routing target;
- the EC2 public IP is not published to users;
- replacing the EC2 instance does not require changing public DNS when the new instance is registered in the target group.

An Elastic IP can still be useful for a stable administrative address in a simple public-subnet deployment, but Session Manager is preferred for administration.

---

# Appendix C: AWS-native scheduling alternative

A host cron job is the simplest single-instance scheduler.

A more AWS-native design can use EventBridge Scheduler to invoke one of the following:

- Systems Manager Run Command on the EC2 instance;
- an ECS task running the Market Sentinel CLI;
- a Lambda wrapper where runtime and dependency constraints are addressed.

Do not run APScheduler inside every Gunicorn worker. Multiple web workers can cause the same job to execute more than once.

---

# Appendix D: Teardown

To avoid unexpected costs when the environment is no longer required:

1. export research history and verify the backup;
2. create a final RDS snapshot when retention is required;
3. delete or stop scheduled jobs;
4. delete the ALB and target group;
5. terminate the EC2 instance;
6. delete the RDS instance only after confirming final-snapshot requirements;
7. release any Elastic IP not in use;
8. delete unused EBS snapshots and volumes according to retention policy;
9. remove Route 53 records and optionally the hosted zone;
10. delete ACM certificates no longer attached to resources;
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
