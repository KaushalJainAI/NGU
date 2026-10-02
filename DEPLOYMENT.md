# NGU E-commerce - EC2 Deployment Guide

Complete step-by-step guide for deploying to **Amazon Linux 2023 on ARM64 (t4g)** instances.

---

## Overview

This deployment uses:
- **Pre-built Docker images** from Docker Hub
- **Amazon Linux 2023** on ARM64 (Graviton) EC2
- **nginx** as reverse proxy

```
 Your Local Machine                    EC2 (Amazon Linux ARM64)
 ├── Build ARM64 images      ──────►   Pull from Docker Hub
 └── Push to Docker Hub                ├── Frontend Container (Gateway :80)
                                       │   ├── / → Frontend Assets
                                       │   ├── /api/ → Backend (:8000)
                                       │   └── /panel/ → Admin Panel (:80)
                                       └── Docker containers (Internal Network)
```

### Port Architecture

| Host Port | Service | Notes |
|-----------|---------|-------|
| 80 | Frontend Container | Gateway: Handles traffic for `/`, `/api/`, and `/panel/` |
| 22 | SSH | Remote access |

> 💡 Containers use internal ports mapped to host ports. nginx on port 80 proxies requests to these internal ports. No port conflicts occur.

---

## Server Topology (current production)

> ⚠️ **Superseded 2026-10-01 — production no longer runs on AWS.** NGU now runs on a
> Google Cloud VM shared with the AIAAS project:
>
> | | |
> |---|---|
> | VM | GCP e2-medium (2 vCPU, 4 GB), Ubuntu 24.04, `asia-south2-b`, static IP `34.0.5.162` |
> | SSH | `ssh -i ~/.ssh/id_ed25519 kaushaljain7000@34.0.5.162` (the AWS `.pem` keys are refused) |
> | Stack | `~/NGU/docker-compose.yml` (not `docker-compose.prod.yml`); same `ngu-*` container names |
> | Proxy / TLS | shared `edge-caddy` container, config in `~/edge/Caddyfile` — no host nginx, no certbot |
> | Database | `ngu-postgres` + `ngu-pgbouncer` in the same compose file; backups via `~/NGU/pg_backup.sh` |
>
> HTTPS was enabled in `~/edge/Caddyfile` on 2026-10-01 for `nidhigrahudyog.com` and
> `www.nidhigrahudyog.com` only. `nidhimasala.com` / `www.` are left out until their
> A records point at `34.0.5.162`; then add them to the NGU site line and run
> `docker exec edge-caddy caddy reload --config /etc/caddy/Caddyfile`. The Caddyfile
> is a single-file bind mount — edit it in place, never with `sed -i`.
> Full VM details: `../AIAAS/DEPLOYMENT.md` → "Where production runs". The EC2
> topology, security groups, nginx and certbot sections below are kept for history
> and do not describe the live server.

Production ran on **two x86_64 EC2 instances** in the **same VPC** (`172.31.0.0/16`):

| Role | Public IP | Private IP | Runs |
|------|-----------|------------|------|
| **Deploy (app)** | `13.235.238.99` | `172.31.39.82` | backend, frontend, admin, redis (`docker-compose.prod.yml`) + host nginx (80/443) |
| **Database** | `13.201.33.243` | `172.31.39.8` | `postgres:17` (internal `:5432`) + PgBouncer (`:6432`) — `~/ngu-db/docker-compose.yml` |

> The app connects to the DB at the **private IP** `172.31.39.8:6432` (in-VPC traffic uses private IPs — see Security Groups). Postgres `5432` is bound to `127.0.0.1` on the DB box and is **not** exposed; only PgBouncer `6432` is reachable from the app server.

---

## Security Group Rules (REQUIRED — get these right or the deploy fails)

Security groups are **stateful**: you only open the side that *initiates* a connection; replies return automatically. A connection needs the initiator's **outbound** AND the receiver's **inbound** to both allow it. ⚠️ Two instances in the same VPC reach each other over their **private IPs**, so DB rules must reference the app server's **private** IP (`172.31.39.82`), never its public IP.

### Deploy server (app) — SG e.g. `ec2-rds-1`

**Inbound**
| Type | Protocol | Port | Source | Why |
|------|----------|------|--------|-----|
| SSH | TCP | 22 | your IP (or `0.0.0.0/0`) | admin/SSH access |
| HTTP | TCP | 80 | `0.0.0.0/0` | site + Let's Encrypt HTTP-01 |
| HTTPS | TCP | 443 | `0.0.0.0/0` | site over TLS (Cloudflare origin pulls) |

**Outbound**
| Type | Protocol | Port | Destination | Why |
|------|----------|------|-------------|-----|
| **All traffic** | All | All | `0.0.0.0/0` | **REQUIRED.** Restricting outbound breaks the DB connection (`6432`), SMTP email (`587`), Cloudinary/S3/LLM/Razorpay APIs, and Docker Hub pulls. Keep the AWS default allow-all. |

> 🐞 A common failure: outbound narrowed to only 80/443 — the server can pull images and reach the web, but **cannot reach the DB on 6432 or send email**. Symptoms: backend unhealthy / 502, connection timeouts to the DB. Fix: restore **All traffic** outbound.

### Database server — SG e.g. `launch-wizard-1`

**Inbound**
| Type | Protocol | Port | Source | Why |
|------|----------|------|--------|-----|
| SSH | TCP | 22 | your IP | admin/SSH access |
| Custom TCP | TCP | 6432 | **`172.31.39.82/32`** (app server **private** IP) — or the app server's SG, or `172.31.0.0/16` | PgBouncer; only the app server may reach it |

**Outbound:** leave AWS default **All traffic → `0.0.0.0/0`** (needed for Docker pulls, etc.).

> 🐞 A rule allowing `6432` from the app server's **public** IP (`13.235.238.99/32`) will **not** match — in-VPC traffic arrives from the **private** IP. Use `172.31.39.82/32` (or the SG / VPC CIDR).
> 🔒 Do **not** expose Postgres `5432` publicly; it stays bound to `127.0.0.1` on the DB box.

---

## Gotchas that will silently break the deploy (learned the hard way)

| Symptom | Cause | Fix |
|---------|-------|-----|
| `Failed to fetch ... Unexpected token '<'` / API calls return HTML | Frontend/admin built **without `/api`** in `VITE_API_URL` (build-arg overrides `.env`) | Build with `VITE_API_URL=https://nidhimasala.com/api` |
| `/panel/assets/*.js|css` → **404** | nginx **regex** asset-cache location outranks the `/panel/` **prefix** location | Use `location ^~ /panel/ { … }` in the frontend `nginx.conf` |
| backend crash-loops on boot | missing `CLOUDINARY_*` (hard dependency) | set Cloudinary vars in `.env.backend` |
| backend stuck at `collectstatic` with **S3 403** | S3 bucket not accessible from this AWS account | set `USE_S3=False` (static served locally; media stays on Cloudinary) — Django admin will be unstyled until WhiteNoise is added |
| Cloudflare **521** on HTTPS | origin has no listener on `443` while CF SSL mode is Full/Full(strict) | configure nginx `:443` with a cert (see SSL section) + open inbound 443 |
| env change not taking effect | compose caches env | `docker-compose -f docker-compose.prod.yml up -d` (recreate) — a `restart` keeps the old values |

---

## Docker Deployment (Unified)

This section covers how to deploy all three applications (Backend, Frontend, and Admin Panel) using Docker Compose.

### Port Mapping Summary

| Service | Container Port | Host Port | Access URL |
|---------|----------------|-----------|------------|
| Host Gateway (Nginx) | 80/443 | 80/443 | `https://nidhimasala.com` |
| Frontend Container | 80 | 3000 | `http://localhost:3000` |
| Backend API | 8000 | Internal | `https://nidhimasala.com/api/` |
| Admin Panel | 80 | Internal | `https://nidhimasala.com/panel/` |
| Redis | 6379 | 6379 | Internal only |

---

## 1. Local Development (Build from Source)

Use this method when you want to build the images locally from the source code.

### Step 1.1: Environment Setup

Create a `.env` file in the root directory (copy from `.env.backend.example` if available) and ensure the following variables are set:

```env
# Security & Main
SECRET_KEY=your_secret_key
DEBUG=True
ALLOWED_HOSTS=localhost,127.0.0.1
CORS_ALLOWED_ORIGINS=http://localhost:5173,http://localhost:3000

# Backend Services (Google & Email)
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret
EMAIL_HOST_USER=your-email@gmail.com
EMAIL_HOST_PASSWORD=your-gmail-app-password

# Frontend Build Envs (Required for UI)
# VITE_GOOGLE_CLIENT_ID is used by the customer storefront AND the admin panel
# (staff-only Google sign-in; it never creates an account).
VITE_API_URL=http://localhost:8000/api
VITE_GOOGLE_CLIENT_ID=your_google_client_id
```

### Step 1.2: Launch the Stack

```bash
docker-compose up --build -d
```

This command will:
1. Build the Backend image using `Backend/Dockerfile`.
2. Build the Frontend image using `Frontend/nidhi-brand-forge/Dockerfile`.
3. Build the Admin Panel image using `Admin Panel/e-commerce-command-center/Dockerfile`.
4. Start Redis and all three apps.

---

## 2. Production Deployment (Use Pre-built Images)

Use this method on your EC2 instance or production server to pull images from Docker Hub.

### Step 2.1: Prepare Production Environment

On the server, create a directory for the project and a `.env.backend` file:

```bash
mkdir -p ~/NGU && cd ~/NGU
nano .env.backend
```

### Step 2.2: Launch with Production Config

```bash
# Set your Docker Hub username
export DOCKER_USERNAME=your_username

# Pull and start
docker-compose -f docker-compose.prod.yml pull
docker-compose -f docker-compose.prod.yml up -d
```

---

## 3. Managing the Stack

### Common Commands

| Action | Command |
|--------|---------|
| View status | `docker-compose ps` |
| View logs (all) | `docker-compose logs -f` |
| View logs (specific) | `docker-compose logs -f backend` |
| Stop all | `docker-compose down` |
| Restart a service | `docker-compose restart frontend` |
| Run migrations | `docker-compose exec backend python manage.py migrate` |

---

## Part 1: Build and Push Docker Images (Local Machine/CI)

> ⚠️ **IMPORTANT**: You must build images for ARM64 architecture since t4g uses Graviton (ARM) processors.

### Step 1.1: Login to Docker Hub

```cmd
docker login
```

### Step 1.2: Setup Docker Buildx for ARM64

```cmd
docker buildx create --name mybuilder --use
docker buildx inspect --bootstrap
```

### Step 1.3: Build and Push Images

Replace `YOUR_DOCKERHUB_USERNAME` and `YOUR_EC2_IP` with your actual values:

```cmd
cd c:\path\to\your\project

# Build and push Backend
docker buildx build --platform linux/arm64 --push -t kaushaljainai/ngu-backend:latest ./Backend

# Build and push Frontend
docker buildx build --platform linux/arm64 --build-arg VITE_API_URL=https://nidhimasala.com --build-arg VITE_GOOGLE_CLIENT_ID=860732387709-osb9oeant94oa302egqqqvqdj4jmkiuh.apps.googleusercontent.com --push -t kaushaljainai/ngu-frontend:latest "./Frontend/nidhi-brand-forge"

# Build and push Admin Panel (Google sign-in for existing staff accounts only)
docker buildx build --platform linux/arm64 --build-arg VITE_API_URL=https://nidhimasala.com --build-arg VITE_GOOGLE_CLIENT_ID=860732387709-osb9oeant94oa302egqqqvqdj4jmkiuh.apps.googleusercontent.com --push -t kaushaljainai/ngu-admin:latest "./Admin Panel/e-commerce-command-center"
```

> 💡 Building ARM64 images on x86_64 machines is slow due to QEMU emulation. Be patient!

---

## Part 2: Launch EC2 Instance (AWS Console)

### Step 2.1: Create EC2 Instance

1. Go to **EC2 Dashboard** → **Launch Instance**
2. **Name**: `ngu-production`
3. **AMI**: Amazon Linux 2023 (ARM64)
4. **Instance Type**: `t4g.small` (2 vCPU, 2GB RAM)
5. **Key Pair**: Create or select existing `.pem` file
6. **Network Settings** → Edit Security Group:
   - Port 22 (SSH)
   - Port 80 (HTTP)
   - Port 443 (HTTPS)
7. **Storage**: 16 GB gp3
8. Click **Launch Instance**

### Step 2.2: Connect to EC2

```bash
chmod 400 your-key.pem
ssh -i your-key.pem ec2-user@YOUR_EC2_IP
```

---

## Part 3: Install Docker (On EC2)

Run each command one by one:

```bash
# Update system packages
sudo yum update -y

# Install Docker
sudo yum install -y docker

# Start Docker and enable on boot
sudo systemctl start docker
sudo systemctl enable docker

# Add your user to docker group (so you don't need sudo)
sudo usermod -aG docker ec2-user

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# IMPORTANT: Log out and log back in
exit
```

SSH back in:
```bash
ssh -i your-key.pem ec2-user@YOUR_EC2_IP
```

Verify installation:
```bash
docker --version
docker-compose --version
```

---

## Part 4: Deploy Application (On EC2)

### Step 4.1: Create Project Directory

```bash
mkdir -p /home/ec2-user/NGU
cd /home/ec2-user/NGU
```

### Step 4.2: Create docker-compose.prod.yml

```bash
nano docker-compose.prod.yml
```

Paste this (replace `YOUR_DOCKERHUB_USERNAME`):

```yaml
services:
  redis:
    image: redis:7-alpine
    container_name: ngu-redis
    restart: unless-stopped
    command: redis-server --appendonly yes --maxmemory 50mb --maxmemory-policy allkeys-lru
    volumes:
      - redis_data:/data
    networks:
      - ngu-network

  backend:
    image: kaushaljainai/ngu-backend:latest
    container_name: ngu-backend
    restart: unless-stopped
    env_file:
      - .env.backend
    environment:
      - REDIS_URL=redis://redis:6379/0
    ports:
      - "8000:8000"
    networks:
      - ngu-network
    depends_on:
      - redis

  frontend:
    image: kaushaljainai/ngu-frontend:latest
    container_name: ngu-frontend
    restart: unless-stopped
    ports:
      - "3000:80" # Host Nginx proxies to this port
    networks:
      - ngu-network

  admin-panel:
    image: kaushaljainai/ngu-admin:latest
    container_name: ngu-admin-panel
    restart: unless-stopped
    # ports:
    #   - "3001:80" # Internal only, accessed via /panel/ on frontend
    networks:
      - ngu-network

networks:
  ngu-network:
    driver: bridge

volumes:
  redis_data:
```

Save: `Ctrl+X`, then `Y`, then `Enter`

### Step 4.3: Create Backend Environment File

```bash
nano .env.backend
```

Add your production secrets (Google, Email, Database, etc.):

```env
DEBUG=False
SECRET_KEY=your-50-character-random-secret-key
ALLOWED_HOSTS=nidhimasala.com,localhost

# Google OAuth
GOOGLE_CLIENT_ID=860732387709-osb9oeant94oa302egqqqvqdj4jmkiuh.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-google-client-secret

# Email Configuration (SMTP)
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=kaushaljain7000@gmail.com
EMAIL_HOST_PASSWORD=your-16-char-app-password
EMAIL_USE_TLS=True

# Database (self-hosted Postgres 17 + PgBouncer on the dedicated DB EC2 instance)
# DB server: 13.201.33.243  — Postgres internal :5432, PgBouncer exposed :6432
DB_ENGINE=django.db.backends.postgresql
DB_NAME=ngu_db
DB_USER=KaushalJainAI
DB_PASSWORD=your_db_password
DB_HOST=13.201.33.243
DB_PORT=6432

# --- Media storage (Cloudinary) ---
# REQUIRED: USE_CLOUDINARY defaults to True and the CLOUDINARY_* values have no
# fallback — if they are missing the Django process WILL FAIL TO START. Cloudinary
# is now the default backend for media (product/category/profile images, chat
# attachments). See "Part 7" for the one-time migration of existing S3 media.
USE_CLOUDINARY=True
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-cloudinary-api-key
CLOUDINARY_API_SECRET=your-cloudinary-api-secret

# --- AWS S3 (static files + reading legacy media during the Cloudinary migration) ---
USE_S3=True
AWS_ACCESS_KEY_ID=your-aws-access-key-id
AWS_SECRET_ACCESS_KEY=your-aws-secret-key
AWS_STORAGE_BUCKET_NAME=ngu-static-files0

# Payment
RAZORPAY_KEY_ID=your-razorpay-key
RAZORPAY_KEY_SECRET=your-razorpay-secret

# --- AI (search synonyms + shopping assistant) ---
# Without LLM_API_KEY the assistant and synonym generation degrade gracefully
# (assistant returns a fallback reply; search falls back to deterministic terms).
LLM_API_KEY=sk-or-v1-...
MODEL_PROVIDER=openrouter
LLM_MODEL=minimax/minimax-m2.5
# Optional: give the assistant a stronger chat model than the synonym generator.
# Falls back to MODEL_PROVIDER / LLM_MODEL when unset.
ASSISTANT_MODEL_PROVIDER=openrouter
ASSISTANT_LLM_MODEL=openai/gpt-4o-mini
```

> ⚠️ **Cloudinary is a hard startup dependency now.** If `CLOUDINARY_CLOUD_NAME`,
> `CLOUDINARY_API_KEY`, or `CLOUDINARY_API_SECRET` are missing, the backend
> container will crash-loop on boot. Set them before pulling the new image.

Set file permissions:
```bash
chmod 600 .env.backend
```

### Step 4.4: Pull and Start Containers

```bash
docker-compose -f docker-compose.prod.yml pull
docker-compose -f docker-compose.prod.yml up -d
```

### Step 4.5: Verify Containers Running

```bash
docker-compose -f docker-compose.prod.yml ps
```

Expected output:
```
NAME              STATUS    PORTS
ngu-backend       Up        0.0.0.0:8000->8000/tcp
ngu-frontend      Up        0.0.0.0:3000->80/tcp
ngu-admin-panel   Up        0.0.0.0:3001->80/tcp
ngu-redis         Up        6379/tcp
```

### Step 4.6: Test Direct Access

Open in browser:
- Frontend: `http://YOUR_EC2_IP:3000`
- Admin: `http://YOUR_EC2_IP:3001`
- API: `http://YOUR_EC2_IP:8000/api/`

---

## Part 5: Final Verification

| URL | What it serves |
|-----|----------------|
| `http://YOUR_EC2_IP/` | Frontend (customer site) |
| `http://YOUR_EC2_IP/api/` | Backend API |
| `http://YOUR_EC2_IP/admin/` | Django Admin |
| `http://YOUR_EC2_IP/panel/` | Admin Panel |

> [!NOTE]
> All traffic now flows through the Frontend container on port 80. Ensure no other service (like host-level Nginx) is listening on port 80.

---

## Part 6: SSL Configuration (Amazon Linux 2023)

> **Both storefront domains resolve directly to the origin — there is no Cloudflare
> proxy in front of them** (verified 2026-07-17: `nidhimasala.com`, `www.`,
> `nidhigrahudyog.com` and `www.` all resolve to `13.235.238.99`). The host nginx
> terminates TLS itself with Let's Encrypt certs. Certs are issued with the
> **dockerized certbot + webroot** challenge; `certbot --nginx` is **not** used.

Current cert layout (one lineage per domain — see Step 6.3 for why they are kept separate):

| Lineage | Covers |
|---------|--------|
| `nidhimasala.com` | `nidhimasala.com`, `www.nidhimasala.com` |
| `nidhigrahudyog.com` | `nidhigrahudyog.com`, `www.nidhigrahudyog.com` |

### Step 6.1: Install and Start Host Nginx (AL2023)

```bash
sudo dnf install -y nginx
# Move the stock default server off :80 so it doesn't shadow ours
sudo sed -i 's/listen       80 default_server;/listen       8081 default_server;/' /etc/nginx/nginx.conf
sudo systemctl enable --now nginx
```

### Step 6.2: Create `/etc/nginx/conf.d/ngu.conf`

The block order matters: `conf.d/*.conf` is included **before** the stock `server` in
`nginx.conf`, so the **first** `listen 80` block here becomes the implicit default server
for `:80`. Keep the bare-IP block first so unknown hosts keep proxying instead of being
redirected to an HTTPS URL no cert covers.

```nginx
# Default for :80 — bare IP and unknown hosts keep proxying (no redirect;
# the TLS certs do not cover the IP literal).
server {
    listen 80;
    server_name 13.235.238.99;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
        default_type "text/plain";
        try_files $uri =404;
    }

    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
        client_max_body_size 500M;
    }
}

# Named domains on :80 — ACME challenge stays served, everything else goes to HTTPS.
server {
    listen 80;
    server_name nidhimasala.com www.nidhimasala.com nidhigrahudyog.com www.nidhigrahudyog.com;

    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
        default_type "text/plain";
        try_files $uri =404;
    }

    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    http2 on;
    server_name nidhimasala.com www.nidhimasala.com;

    ssl_certificate     /etc/letsencrypt/live/nidhimasala.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/nidhimasala.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;

    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_cache_bypass $http_upgrade;
        client_max_body_size 500M;
    }
}

# Same block again for nidhigrahudyog.com / www., pointing at
# /etc/letsencrypt/live/nidhigrahudyog.com/.
```

> ⚠️ Add each `443` server block **only after** its cert exists (Step 6.3), or `nginx -t`
> fails on the missing cert files. First deploy with the `80` blocks only, issue the cert,
> then add the `443` block and reload.

### Step 6.3: Issue the Cert (dockerized certbot, webroot)

```bash
sudo mkdir -p /var/www/certbot
sudo nginx -t && sudo systemctl reload nginx   # 80-only config must be live first

# Dry-run against staging (no rate-limit burn):
sudo docker run --rm \
  -v /etc/letsencrypt:/etc/letsencrypt -v /var/lib/letsencrypt:/var/lib/letsencrypt \
  -v /var/www/certbot:/var/www/certbot \
  certbot/certbot certonly --webroot -w /var/www/certbot \
  --cert-name nidhimasala.com -d nidhimasala.com -d www.nidhimasala.com \
  --dry-run --agree-tos -m kaushaljain7000@gmail.com --no-eff-email -n

# Real issuance (drop --dry-run):
sudo docker run --rm \
  -v /etc/letsencrypt:/etc/letsencrypt -v /var/lib/letsencrypt:/var/lib/letsencrypt \
  -v /var/www/certbot:/var/www/certbot \
  certbot/certbot certonly --webroot -w /var/www/certbot \
  --cert-name nidhimasala.com -d nidhimasala.com -d www.nidhimasala.com \
  --agree-tos -m kaushaljain7000@gmail.com --no-eff-email -n
```

Then add the `443` block (Step 6.2) and `sudo nginx -t && sudo systemctl reload nginx`.

> Only hostnames whose DNS actually points at this origin can be validated.

> ⚠️ **Never bundle a hostname you might retire onto another domain's cert, and always
> pass `--cert-name`.** HTTP-01 renewal must re-validate *every* SAN on a cert; if one
> name stops resolving, the **whole** renewal fails and every domain on that cert loses
> its certificate at expiry. This bit us once: the cert was originally issued as
> `-d nidhimasala.kaushaljain.com -d nidhimasala.com -d www.nidhimasala.com`, which both
> named the lineage after the throwaway subdomain and tied the primary domain's renewal
> to it. When `nidhimasala.kaushaljain.com` went NXDOMAIN, renewal was set to start
> failing ~30 days before the 2026-09-27 expiry and take `nidhimasala.com` down with it.
> Fixed 2026-07-17 by issuing a clean per-domain lineage and deleting the old one
> (`certbot delete --cert-name <old>`). Keep one lineage per domain.

#### Additional domain: `nidhigrahudyog.com`

A second storefront domain served by the same app stack. **Live since 2026-07-17** — DNS
points at `13.235.238.99`, its cert is issued, and its `443` block is active. The backend
`ALLOWED_HOSTS` / `CORS_ALLOWED_ORIGINS` / `CSRF_TRUSTED_ORIGINS` list it plus `www.`.

The procedure used (reusable for any further domain):

```bash
# 1. Confirm DNS resolves here first:
dig +short nidhigrahudyog.com          # must return 13.235.238.99

# 2. Issue the cert (webroot; the 80 block already serves /.well-known/acme-challenge/):
sudo docker run --rm \
  -v /etc/letsencrypt:/etc/letsencrypt -v /var/lib/letsencrypt:/var/lib/letsencrypt \
  -v /var/www/certbot:/var/www/certbot \
  certbot/certbot certonly --webroot -w /var/www/certbot \
  --cert-name nidhigrahudyog.com -d nidhigrahudyog.com -d www.nidhigrahudyog.com \
  --agree-tos -m kaushaljain7000@gmail.com --no-eff-email -n

# 3. Add the nidhigrahudyog.com 443 server block to /etc/nginx/conf.d/ngu.conf, add the
#    hostnames to the :80 redirect block's server_name, then:
sudo nginx -t && sudo systemctl reload nginx
```

The auto-renewal timer (Step 6.5) renews all certs, so no extra timer is needed.

### Step 6.4: Open 443

- Open **inbound 443** on the deploy server SG (see Security Group Rules above).

> **No Cloudflare.** Earlier revisions of this doc described a Cloudflare proxy in front of
> `nidhimasala.com` with SSL mode *Full (strict)*, and a `kaushaljain.com` zone. Neither
> applies: as of 2026-07-17 both storefront domains resolve straight to the origin and the
> host nginx is the only TLS terminator. If Cloudflare is ever put back in front, set the
> zone to **Full (strict)** so it validates this origin cert.

### Step 6.5: Auto-Renewal (systemd timer running dockerized certbot)

```bash
sudo tee /etc/systemd/system/certbot-renew.service >/dev/null <<'SVC'
[Unit]
Description=Renew Let's Encrypt certificates (dockerized certbot)
[Service]
Type=oneshot
ExecStart=/usr/bin/docker run --rm -v /etc/letsencrypt:/etc/letsencrypt -v /var/lib/letsencrypt:/var/lib/letsencrypt -v /var/www/certbot:/var/www/certbot certbot/certbot renew --webroot -w /var/www/certbot --quiet
ExecStartPost=/usr/bin/systemctl reload nginx
SVC
sudo tee /etc/systemd/system/certbot-renew.timer >/dev/null <<'TMR'
[Unit]
Description=Run certbot-renew twice daily
[Timer]
OnCalendar=*-*-* 03,15:00:00
RandomizedDelaySec=3600
Persistent=true
[Install]
WantedBy=timers.target
TMR
sudo systemctl daemon-reload
sudo systemctl enable --now certbot-renew.timer
sudo systemctl list-timers certbot-renew.timer --no-pager
```

---

## Part 7: First Deploy of the AI Search / Recommendations / Cloudinary Release

This release adds the **AI shopping assistant**, **behavioral analytics**,
**personalized recommendations**, **admin-ordered homepage sections**, fixes the
**combo & coupon order 500s**, and switches media storage to **Cloudinary**. It
introduces new apps, new DB migrations, new env vars, and a one-time media move.
Do this the **first time** you deploy this version (subsequent deploys: see
"Updating Application").

> ⚠️ Run the DB and media migrations against a **clone/backup of the production
> database and bucket first**. Migration `products/0016` alters a live table
> (`ALTER TABLE products_product_sections ADD COLUMN position`), and the media
> migration rewrites file references on rows.

### Step 7.1: Pre-flight (before touching prod)

- [ ] New env vars set in `.env.backend`: `USE_CLOUDINARY=True`, `CLOUDINARY_CLOUD_NAME/API_KEY/API_SECRET`, `LLM_API_KEY` (see Step 4.3).
- [ ] Cloudinary account/bucket reachable; AWS S3 creds still valid (needed to *read* legacy media during the move).
- [ ] Database backup / snapshot taken (RDS snapshot).
- [ ] New images built & pushed (deps like `cloudinary`, `django-admin-sortable2` are baked into the image at build time — see Part 1 / Updating).

### Step 7.2: Deploy the new backend image

```bash
cd /home/ec2-user/NGU
docker-compose -f docker-compose.prod.yml pull
docker-compose -f docker-compose.prod.yml up -d
```

If the backend crash-loops on boot, it's almost always missing `CLOUDINARY_*`
env vars — check `docker logs ngu-backend`.

### Step 7.3: Apply database migrations

Includes the new `analytics` and `assistant` apps plus `products/0015` & `0016`:

```bash
docker-compose -f docker-compose.prod.yml exec backend python manage.py migrate
```

### Step 7.4: Migrate existing media S3 → Cloudinary (one-time, critical)

Because the default storage is now Cloudinary, rows that still point at S3 will
render **broken image URLs** until their files are copied over. The command is
**dry-run by default** and **idempotent** (safe to re-run):

```bash
# 1) Preview what would move (no writes):
docker-compose -f docker-compose.prod.yml exec backend python manage.py migrate_s3_to_cloudinary

# 2) Perform the migration:
docker-compose -f docker-compose.prod.yml exec backend python manage.py migrate_s3_to_cloudinary --apply
```

Covers Category/Product/ProductImage/ProductCombo images + thumbnails, user
profile pictures, and chat attachments.

### Step 7.5: Smoke test

- [ ] Product/category **images load** on the storefront (Cloudinary URLs).
- [ ] Place an order **containing a combo** → succeeds (was a 500 before this release).
- [ ] Place an order **with a coupon** → succeeds (was a 500 before this release).
- [ ] `GET /api/search/suggest/?q=haldi` returns suggestions.
- [ ] `GET /api/recommendations/` (logged in) returns products.
- [ ] `POST /api/assistant/chat/` returns a reply (or a graceful fallback if `LLM_API_KEY` is unset).
- [ ] `/admin/` → **Product Sections** → drag products to reorder a homepage section.

### Step 7.6: (Optional) Tidy homepage search knowledge base

Synonym KBs are generated lazily on product save, but you can warm them up:

```bash
docker-compose -f docker-compose.prod.yml exec backend python manage.py populate_search_kb
```

> 💡 **Cost/scale note:** synonym generation calls the LLM on every product/combo
> save (via a background thread). During **bulk catalog imports** this can fan out
> into many concurrent LLM calls — import during low-traffic windows, and consider
> moving this onto Celery before large imports.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `invalid reference format` | Set username: `export DOCKER_USERNAME=yourname` |
| `no matching manifest for linux/arm64` | Rebuild images with `--platform linux/arm64` |
| Container keeps restarting | Check logs: `docker logs ngu-backend` |
| 502 Bad Gateway | Backend not running: `docker ps` |
| CORS errors | Check `CORS_ALLOWED_ORIGINS` in `.env.backend` |
| Can't connect to database | Check RDS security group allows EC2 IP |
| nginx won't start | Check config: `sudo nginx -t` |
| Backend crash-loops on boot after upgrade | Missing `CLOUDINARY_*` env vars (now required). Check `docker logs ngu-backend`. |
| Images broken site-wide after upgrade | Run the media migration: `migrate_s3_to_cloudinary --apply` (Step 7.4). |
| `relation/column ... does not exist` 500s | Migrations not applied: `... exec backend python manage.py migrate` (Step 7.3). |
| Combo or coupon checkout 500 | Old image still running — pull/rebuild the latest backend image. |
| Assistant always returns the fallback reply | `LLM_API_KEY` not set (or invalid) in `.env.backend`. |

---

## Updating Application

When you make code changes:

### On Local Machine:
```cmd
# Rebuild and push new images
docker buildx build --platform linux/arm64 --push -t YOUR_USERNAME/ngu-backend:latest ./Backend
docker buildx build --platform linux/arm64 --build-arg VITE_API_URL=https://nidhimasala.com --build-arg VITE_GOOGLE_CLIENT_ID=860732387709-osb9oeant94oa302egqqqvqdj4jmkiuh.apps.googleusercontent.com --push -t YOUR_USERNAME/ngu-frontend:latest "./Frontend/nidhi-brand-forge"
docker buildx build --platform linux/arm64 --build-arg VITE_API_URL=https://nidhimasala.com --push -t YOUR_USERNAME/ngu-admin:latest "./Admin Panel/e-commerce-command-center"
```

### On EC2:
```bash
cd /home/ec2-user/NGU
docker-compose -f docker-compose.prod.yml pull
docker-compose -f docker-compose.prod.yml up -d
docker-compose -f docker-compose.prod.yml exec backend python manage.py migrate
```

> 📌 **Upgrading to the AI Search / Cloudinary release for the first time?** A
> plain pull + migrate is not enough — you also need the new env vars and the
> one-time S3 → Cloudinary media migration. Follow **Part 7** instead.
