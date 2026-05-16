# Yantrix Client Scout - GCP Compute Engine Setup

Since you have Google Cloud credits, we recommend launching an **e2-medium** instance (2 vCPU, 4 GB RAM). This will run the headless Playwright browsers much faster and more reliably than a 1GB Free Tier instance.

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

### 4. Run the Bootstrap Script
Inside the browser SSH terminal, run:

```bash
# 1. Install Docker & Git
sudo apt update
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# 2. Clone the repository
git clone https://github.com/yantrix-labs/client-scout.git
cd client-scout

# 3. Setup Environment Variables
cp .env.example .env
nano .env
```

**Crucial `.env` Edits for GCP:**
Change the Dashboard port to 80 so you can access it via the IP:
```env
DASHBOARD_PORT=80
VITE_API_BASE_URL=http://<YOUR_GCP_PUBLIC_IP>:8000/api/v1
CORS_ORIGINS=["http://<YOUR_GCP_PUBLIC_IP>", "http://localhost:3000"]

# Since you have 4GB RAM on e2-medium, you can bump concurrency up!
AUDIT_CONCURRENCY=4
SCRAPER_CONCURRENCY=2
```

Save (Ctrl+O, Enter, Ctrl+X).

### 5. Launch
```bash
sudo docker compose up -d --build dashboard api
sleep 10
sudo docker compose exec -T api python -m app.migrate
```

Your dashboard will be live at `http://<YOUR_GCP_PUBLIC_IP>`.
