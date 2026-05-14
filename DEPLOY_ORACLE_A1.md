# Deploy Yantrix Client Scout on Oracle Cloud A1 Flex

Target host: Ubuntu 22.04 on Oracle Cloud A1 Flex (`arm64`).

Target domain: `scout.yantrixlabs.com`.

This guide runs the Docker stack from `docker-compose.yml` and uses host-level Nginx as the public reverse proxy with Let's Encrypt TLS.

## 1. Provision the VM

Create an Oracle Cloud A1 Flex instance with Ubuntu 22.04.

Recommended shape:

- 4 OCPU
- 24 GB RAM
- 100 GB or larger boot volume
- Public IPv4 address

Point DNS before requesting TLS:

```bash
scout.yantrixlabs.com A <ORACLE_VM_PUBLIC_IP>
```

Verify DNS from your local machine:

```bash
dig +short scout.yantrixlabs.com
```

## 2. Open Oracle Network Ingress

In Oracle Cloud Console:

1. Go to `Networking` -> `Virtual Cloud Networks`.
2. Open the VCN used by the VM.
3. Open the subnet or attached Network Security Group / Security List.
4. Add ingress rules:

| Source CIDR | Protocol | Destination Port | Purpose |
| --- | --- | --- | --- |
| `0.0.0.0/0` | TCP | `80` | HTTP / Let's Encrypt challenge |
| `0.0.0.0/0` | TCP | `443` | HTTPS |
| `<your-office-ip>/32` | TCP | `22` | SSH admin access |

Keep app ports such as `8000`, `3000`, `5432`, `5678`, and `8080` closed publicly. Nginx should be the only public app entry point.

If `ufw` is enabled inside Ubuntu:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw status
```

## 3. SSH Into the VM

```bash
ssh ubuntu@scout.yantrixlabs.com
```

Update base packages:

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y git curl ca-certificates gnupg lsb-release make nginx snapd
```

## 4. Install Docker and Compose

Use Docker's official apt repository:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Allow the `ubuntu` user to run Docker:

```bash
sudo usermod -aG docker "$USER"
newgrp docker
```

Verify:

```bash
docker --version
docker compose version
```

## 5. Clone the Repo

```bash
mkdir -p ~/apps
cd ~/apps
git clone <REPO_URL> yantrix-client-scout
cd yantrix-client-scout
```

Replace `<REPO_URL>` with the Git remote for this repository.

## 6. Configure Environment Variables

Create the runtime `.env`:

```bash
cp .env.example .env
nano .env
```

Set the public URL and CORS:

```env
VITE_API_BASE_URL=https://scout.yantrixlabs.com
CORS_ORIGINS=https://scout.yantrixlabs.com
```

Keep internal service ports bound locally or behind Nginx:

```env
API_PORT=8000
DASHBOARD_PORT=3000
GMAPS_HOST_PORT=127.0.0.1:8080
```

### Option A: Local Postgres Container

Use this for a self-contained VM deployment:

```env
USE_LOCAL_POSTGRES=true
DB_HOST=db
DB_PORT=5432
DB_NAME=clientscout
DB_USER=scout
DB_PASSWORD=<strong-random-password>
```

The local Postgres container loads `client-scout-api/migrations/001_initial_schema.sql` on first boot.

### Option B: Supabase or External Postgres

Use this when the database is hosted elsewhere:

```env
USE_LOCAL_POSTGRES=false
DB_HOST=<supabase-or-postgres-host>
DB_PORT=5432
DB_NAME=postgres
DB_USER=<db-user>
DB_PASSWORD=<db-password>
```

If your provider requires SSL, update the backend database settings before using this mode. The current backend builds `postgresql+asyncpg://user:password@host:port/db` from the individual DB env vars.

### LLM and API Keys

At minimum, set one LLM provider key:

```env
LLM_PROVIDER=nvidia
NVIDIA_NIM_API_KEY=<nvidia-key>
GROQ_API_KEY=<groq-key>
```

Optional:

```env
PSI_API_KEY=<google-pagespeed-key>
HUBSPOT_ACCESS_TOKEN=<hubspot-private-app-token>
ZOHO_CLIENT_ID=
ZOHO_CLIENT_SECRET=
ZOHO_REFRESH_TOKEN=
```

Worker tuning for A1 Flex:

```env
AUDIT_CONCURRENCY=3
GMAPS_CONCURRENCY=2
SCRAPER_CONCURRENCY=2
JUSTDIAL_ENABLED=false
```

Optional n8n:

```env
ENABLE_N8N=true
N8N_HOST=scout.yantrixlabs.com
N8N_PROTOCOL=https
N8N_WEBHOOK_URL=https://scout.yantrixlabs.com/n8n/
N8N_ENCRYPTION_KEY=<strong-random-secret>
N8N_BASIC_AUTH_USER=admin
N8N_BASIC_AUTH_PASSWORD=<strong-random-password>
```

Optional Scrapy worker:

```env
ENABLE_SCRAPY=true
SCRAPY_WORKER_IMAGE=<your-scrapy-worker-image>
SCRAPY_WORKER_COMMAND=scrapy crawl justdial
```

## 7. Build and Run the Stack

The deploy script installs Docker if needed, builds images, and starts Compose:

```bash
bash deploy.sh
```

Or run Compose directly:

```bash
docker compose --env-file .env build
docker compose --env-file .env up -d
```

Check services:

```bash
docker compose --env-file .env ps
docker compose --env-file .env logs -f --tail=100 api
```

Expected default services:

- `gmaps-scraper`
- `api`
- `dashboard`

If `USE_LOCAL_POSTGRES=true`, the `db` profile is enabled by `deploy.sh`. If you run Compose manually, use:

```bash
COMPOSE_PROFILES=local-db docker compose --env-file .env up -d
```

Smoke test from the VM:

```bash
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:3000/health
```

## 8. Configure Host Nginx Reverse Proxy

Create an Nginx server block:

```bash
sudo nano /etc/nginx/sites-available/scout.yantrixlabs.com
```

Paste:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name scout.yantrixlabs.com;

    client_max_body_size 20m;

    location /api/ {
        proxy_pass http://127.0.0.1:8000/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /docs {
        proxy_pass http://127.0.0.1:8000/docs;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /openapi.json {
        proxy_pass http://127.0.0.1:8000/openapi.json;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /health {
        proxy_pass http://127.0.0.1:8000/health;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        proxy_pass http://127.0.0.1:3000/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable it:

```bash
sudo ln -s /etc/nginx/sites-available/scout.yantrixlabs.com /etc/nginx/sites-enabled/scout.yantrixlabs.com
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

Check HTTP:

```bash
curl -I http://scout.yantrixlabs.com
curl -fsS http://scout.yantrixlabs.com/health
```

## 9. Install Let's Encrypt TLS

Install Certbot through Snap:

```bash
sudo snap install core
sudo snap refresh core
sudo apt-get remove -y certbot || true
sudo snap install --classic certbot
sudo ln -sf /snap/bin/certbot /usr/local/bin/certbot
```

Request and install the certificate:

```bash
sudo certbot --nginx -d scout.yantrixlabs.com
```

Choose the redirect-to-HTTPS option when prompted.

Test renewal:

```bash
sudo certbot renew --dry-run
```

Check HTTPS:

```bash
curl -I https://scout.yantrixlabs.com
curl -fsS https://scout.yantrixlabs.com/health
```

## 10. Operations

View running services:

```bash
make ps
```

Follow logs:

```bash
make logs
```

Deploy after pulling changes:

```bash
git pull
bash deploy.sh
```

Restart one service:

```bash
docker compose --env-file .env restart api
```

Stop the stack:

```bash
docker compose --env-file .env down
```

Back up local Postgres:

```bash
docker compose --env-file .env exec db pg_dump -U "$DB_USER" "$DB_NAME" > clientscout-backup.sql
```

## 11. Common Checks

If TLS fails:

- Confirm `scout.yantrixlabs.com` resolves to the VM public IP.
- Confirm OCI ingress has TCP `80` and `443` open.
- Confirm host Nginx is running: `sudo systemctl status nginx`.
- Confirm HTTP works before running Certbot.

If the API cannot reach Postgres:

- For local Postgres, confirm `USE_LOCAL_POSTGRES=true` and `DB_HOST=db`.
- For Supabase/external Postgres, confirm hostname, password, and network allow-list.
- Check logs: `docker compose --env-file .env logs --tail=100 api`.

If Playwright audits fail:

- Keep `AUDIT_CONCURRENCY=3` or lower.
- Confirm the API image has Chromium dependencies.
- Check API logs for site-level timeouts before increasing resources.

## References

- Docker Engine Ubuntu install: https://docs.docker.com/installation/ubuntulinux/
- Docker Compose plugin install: https://docs.docker.com/compose/install/linux/
- Certbot Nginx instructions: https://certbot.eff.org/instructions?ws=nginx&os=snap
- Oracle security list docs: https://docs.oracle.com/en-us/iaas/Content/Network/Concepts/getting_details-securitylist.htm
