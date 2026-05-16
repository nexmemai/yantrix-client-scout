# Deploy Yantrix Client Scout on AWS EC2 t3.micro

This guide explains how to deploy the Client Scout platform on an AWS Free Tier instance (t3.micro).

## 1. Create the EC2 Instance

1. Go to the AWS EC2 Console.
2. Click **Launch instances**.
3. **Name**: `yantrix-client-scout`
4. **AMI**: Select **Ubuntu 22.04 LTS** (64-bit x86).
5. **Instance type**: Select `t3.micro` (Free tier eligible).
6. **Key pair**: Select your existing key pair or create a new one to allow SSH access.
7. **Network Settings**:
   - Allow **SSH traffic** (port 22).
   - Allow **HTTP traffic** (port 80).
   - Allow **HTTPS traffic** (port 443).
   - *Optional*: Allow Custom TCP (port 8000) if you want direct API access without Nginx.
8. **Storage**: Configure up to **30 GB** (Free tier maximum) General Purpose SSD (gp3).
9. Click **Launch instance**.

## 2. Connect and Install Dependencies

Once the instance is running, copy its Public IPv4 address and SSH into it:

```bash
ssh -i /path/to/your-key.pem ubuntu@<EC2_PUBLIC_IP>
```

Update packages and install Docker:

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y docker.io docker-compose-plugin git
sudo usermod -aG docker $USER
```
*Note: You may need to log out (`exit`) and log back in for the docker group to take effect, or just prefix docker commands with `sudo`.*

## 3. Clone and Configure

Clone the repository:

```bash
git clone https://github.com/yantrix-labs/client-scout.git
cd client-scout
```

Create and edit the `.env` file:

```bash
cp .env.example .env
nano .env
```

Add your API keys (Groq, NVIDIA NIM, HubSpot, etc.).
Set generic hostnames if needed:
```env
CLIENT_SCOUT_PUBLIC_URL=http://<EC2_PUBLIC_IP>
N8N_PUBLIC_URL=http://<EC2_PUBLIC_IP>:5678
```

> [!WARNING]
> **Strict Memory Constraints**: A t3.micro only has 1GB of RAM. The Playwright worker and Scrapers will cause Out Of Memory (OOM) crashes if concurrency is too high.
>
> In your `.env`, ensure you have:
> `AUDIT_CONCURRENCY=2` (or even `1`)
> `SCRAPER_CONCURRENCY=1`

## 4. Deploy

Launch the stack:

```bash
sudo docker compose up -d
```

Run database migrations:

```bash
sudo docker compose exec api python -m app.migrate
```

## 5. Verify

- Check container status: `sudo docker compose ps`
- Check API logs: `sudo docker compose logs -f api`
- Access the dashboard at `http://<EC2_PUBLIC_IP>:3000`
- Access the API docs at `http://<EC2_PUBLIC_IP>:8000/docs`
