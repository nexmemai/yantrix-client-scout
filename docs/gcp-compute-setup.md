# Yantrix Client Scout — GCP Compute Engine Setup

Since you have Google Cloud credits, we recommend launching an **e2-medium** instance (2 vCPU, 4 GB RAM). This will run the headless Playwright browsers much faster and more reliably than a 1 GB Free Tier instance.

### 1. Launch the VM

1. Go to the [Google Cloud Console](https://console.cloud.google.com/compute/instances).
2. Click **Create Instance**.
3. **Name**: `yantrix-client-scout`
4. **Region**: Pick the one closest to you (e.g., `asia-south1` for Mumbai or `us-central1` for USA).
5. **Machine Configuration**:
   * Series: **E2**
   * Machine type: **e2-medium** (2 vCPU, 4 GB memory)
6. **Boot Disk**:
   * Click **Change**.
   * OS: **Ubuntu**
   * Version: **Ubuntu 24.04 LTS** (or 22.04 LTS)
   * Size: **30 GB** (Standard persistent disk or Balanced)
   * Click **Select**.
7. **Firewall**:
   * Check **Allow HTTP traffic** (opens Port 80)
   * Check **Allow HTTPS traffic** (opens Port 443)
8. Click **Create**.

### 2. Connect via SSH

Google Cloud has a built-in SSH button.
1. Once the VM is running, click the **SSH** button next to your instance in the Compute Engine dashboard. It will open a terminal in your browser.

### 3. Open Port 8000 (Optional, for API direct access)

By default, GCP opens port 80 when you check the HTTP box. If you also want to hit the API docs directly on port 8000 from outside:

1. Go to **VPC Network** > **Firewall**.
2. Click **Create Firewall Rule**.
3. Name: `allow-api-8000`
4. Targets: `All instances in the network`
5. Source IPv4 ranges: `0.0.0.0/0`
6. Specified protocols and ports: `tcp: 8000`
7. Click **Create**.

### 4. Install Docker & Clone the Repo

Inside the browser SSH terminal, run:

```bash
# 1. Install Docker & Git
sudo apt update
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# IMPORTANT: log out and back in for the docker group to take effect
exit
# (then SSH back in)

# 2. Clone the repository
git clone https://github.com/nexmemai/yantrix-client-scout.git
cd yantrix-client-scout

# 3. Setup Environment Variables
cp .env.example .env
nano .env
```

### 5. Configure .env

**Crucial `.env` edits for GCP:**

```env
# Since scraper is on the Docker network, this MUST stay as Docker DNS:
GMAPS_SCRAPER_URL=http://gmaps-scraper:8080

# Change the Dashboard port to 80 so you can access it via the VM's public IP:
DASHBOARD_PORT=80
VITE_API_BASE_URL=http://<YOUR_GCP_PUBLIC_IP>:8000
CORS_ORIGINS=http://<YOUR_GCP_PUBLIC_IP>,http://localhost:3000

# Database — use local Postgres (runs as a container):
DB_HOST=db
DB_PORT=5432
DB_NAME=clientscout
DB_USER=scout
DB_PASSWORD=<pick-a-strong-password>

# Since you have 4 GB RAM on e2-medium, you can bump concurrency up:
AUDIT_CONCURRENCY=4
SCRAPER_CONCURRENCY=2
```

Save (`Ctrl+O`, `Enter`, `Ctrl+X`).

### 6. Build and Launch

```bash
# Build the API image (includes Playwright Chromium — no manual install needed)
docker compose build --no-cache api

# Start all services with local Postgres
COMPOSE_PROFILES=local-db docker compose up -d

# Wait for services to become healthy
sleep 15

# Verify everything is running
docker compose ps
```

### 7. Verify with Smoke Test

```bash
bash scripts/smoke-test.sh
```

Or manually:

```bash
# API health
curl http://127.0.0.1:8000/health

# Scraper docs (localhost only)
curl http://127.0.0.1:8080/api/docs | head

# Run a scout pipeline
curl -X POST http://127.0.0.1:8000/api/v1/run-scout \
  -H "Content-Type: application/json" \
  -d '{"niche":"dental","city":"Jaipur","depth":1,"max_businesses":5}'
```

### 8. Access the Dashboard

Your dashboard will be live at: `http://<YOUR_GCP_PUBLIC_IP>`

API docs (Swagger UI): `http://<YOUR_GCP_PUBLIC_IP>:8000/docs`

### 9. Ongoing Operations

See `scripts/runbook.md` for the full operations guide covering:
- Build, start, restart, logs, teardown
- Troubleshooting common issues
- Database schema reference (tables: `businesses`, `audits`, `scores`, `pitches`, `discovery_jobs`, `niche_configs`)
