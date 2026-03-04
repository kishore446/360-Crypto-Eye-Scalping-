# VPS Setup Guide — 360 Crypto Eye Scalping Bot

Complete step-by-step guide to deploy the 360 Crypto Eye Scalping bot on a fresh VPS.

---

## VPS Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 1 vCPU | 2 vCPUs |
| RAM | 1 GB | 2 GB |
| Disk | 20 GB SSD | 40 GB SSD |
| OS | Ubuntu 22.04 LTS | Ubuntu 24.04 LTS |
| Network | 100 Mbps | 1 Gbps |
| Open Ports | 22 (SSH), 5000 (webhook) | — |

---

## Step 1: Deep Clean (Optional — Recommended for Existing VPS)

If you are redeploying on a VPS that already has Docker or old bot installations, run the deep clean script first to start from a completely clean slate.

```bash
# Download and run the deep clean script
chmod +x vps-deep-clean.sh
sudo ./vps-deep-clean.sh
```

The script will:
- Show current disk usage before cleaning
- Ask for confirmation before making any changes
- Stop and remove **all** Docker containers, images, volumes, networks, and build cache
- Remove old bot installation directories (`/opt/360-crypto-eye`, `/root/360*`, etc.)
- Disable and remove old systemd services
- Remove old Python virtual environments
- Clear pip cache
- Remove old log files and stale data files
- Clean apt package cache
- Optionally run `apt upgrade`
- Show disk usage after cleaning and a full summary

> **Note:** Stale `.env` files are **not** auto-removed — the script will list them for manual review.

---

## Step 2: Fresh Install

### Option A — Automated (Recommended)

```bash
# Clone the repository
git clone https://github.com/kishore446/360-Crypto-Eye-Scalping-.git /opt/360-crypto-eye
cd /opt/360-crypto-eye

# Run the one-command deployment script
chmod +x deploy.sh
sudo ./deploy.sh
```

The `deploy.sh` script will:
1. Check and install Docker + Docker Compose plugin if not present
2. Configure UFW firewall (allow ports 22 and 5000)
3. Clone or update the repository
4. Create `.env` from `.env.example` and prompt you to edit it
5. Create the `data/` directory for persistent storage
6. Build Docker images with `--no-cache`
7. Start all services with `docker compose up -d`
8. Install and enable the systemd auto-start service
9. Configure Docker log rotation
10. Run a health check and print a summary

### Option B — Manual Steps

```bash
# 1. Install Docker
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# 2. Clone repository
git clone https://github.com/kishore446/360-Crypto-Eye-Scalping-.git /opt/360-crypto-eye
cd /opt/360-crypto-eye

# 3. Create data directory
mkdir -p data

# 4. Configure environment (see Step 3 below)
cp .env.example .env
nano .env

# 5. Build and start
docker compose build --no-cache
docker compose up -d
```

---

## Step 3: Configure

Edit the `.env` file with your credentials before starting the bot:

```bash
nano /opt/360-crypto-eye/.env
```

### Required Settings

| Variable | Description | Example |
|----------|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Bot token from [@BotFather](https://t.me/BotFather) | `123456:ABC-DEF...` |
| `TELEGRAM_CHANNEL_ID` | Channel/group ID to post signals | `-1001234567890` |
| `ADMIN_CHAT_ID` | Your Telegram user ID for admin commands | `987654321` |
| `WEBHOOK_SECRET` | Random secret for webhook security | `use openssl rand -hex 32` |

### Optional but Recommended

| Variable | Description |
|----------|-------------|
| `COINMARKETCAL_API_KEY` | For news-based signal filtering |
| `ALLOWED_WEBHOOK_IPS` | Comma-separated IPs to restrict webhook access |

### Generate a Secure Webhook Secret

```bash
openssl rand -hex 32
```

Copy the output into `WEBHOOK_SECRET=` in your `.env` file.

---

## Step 4: Deploy

```bash
cd /opt/360-crypto-eye

# Start all services in the background
docker compose up -d

# Confirm services are running
docker compose ps
```

---

## Step 5: Verify

### Check Service Status

```bash
docker compose ps
```

Expected output shows both `360eye-bot` and `360eye-webhook` as `running`.

### Check Webhook Health Endpoint

```bash
curl http://localhost:5000/health
```

Should return `200 OK`.

### View Logs

```bash
# All services
docker compose logs -f

# Bot only
docker compose logs -f bot

# Webhook only
docker compose logs -f webhook
```

---

## Step 6: Auto-Start on Reboot (systemd)

The `deploy.sh` script installs and enables the systemd service automatically. To set it up manually:

```bash
# Copy the service file
cp /opt/360-crypto-eye/360eye.service /etc/systemd/system/

# Update WorkingDirectory if your install path differs
sed -i 's|WorkingDirectory=.*|WorkingDirectory=/opt/360-crypto-eye|' /etc/systemd/system/360eye.service

# Enable and start
systemctl daemon-reload
systemctl enable 360eye.service
systemctl start 360eye.service
```

### Check systemd Service Status

```bash
systemctl status 360eye.service
```

---

## Monitoring Commands

```bash
# Real-time logs for all services
docker compose logs -f

# Bot container resource usage
docker stats 360eye-bot 360eye-webhook

# Check health status
docker inspect --format='{{.State.Health.Status}}' 360eye-bot
docker inspect --format='{{.State.Health.Status}}' 360eye-webhook

# View last 100 log lines
docker compose logs --tail=100

# systemd journal logs
journalctl -u 360eye.service -f
```

---

## Updating

Pull the latest code and rebuild:

```bash
cd /opt/360-crypto-eye

# Stop services
docker compose down

# Pull latest changes
git pull --ff-only

# Rebuild images (no cache to ensure fresh build)
docker compose build --no-cache

# Restart
docker compose up -d

# Verify
docker compose ps
docker compose logs -f
```

---

## Troubleshooting

### Bot container keeps restarting

```bash
docker compose logs bot --tail=50
```

Common causes:
- Missing or invalid `TELEGRAM_BOT_TOKEN` in `.env`
- Missing `TELEGRAM_CHANNEL_ID` or `ADMIN_CHAT_ID`
- Network connectivity issues from the VPS

### Webhook returns 502 / not reachable

```bash
docker compose logs webhook --tail=50
```

Common causes:
- Port 5000 blocked by firewall — run: `ufw allow 5000/tcp`
- Webhook service still starting — wait 30 seconds and retry
- Gunicorn failed to bind — check logs for bind errors

### Docker build fails

```bash
# Rebuild with verbose output
docker compose build --no-cache --progress=plain
```

Common causes:
- No internet access on VPS during build
- Outdated base image — run `docker pull python:3.12-slim` first

### Disk space full

```bash
# Check disk usage
df -h /

# Clean Docker resources
docker system prune -f
docker volume prune -f

# Or run the full deep clean
sudo ./vps-deep-clean.sh
```

### systemd service fails to start

```bash
journalctl -u 360eye.service -n 50 --no-pager
systemctl status 360eye.service
```

Ensure Docker is running: `systemctl status docker`

### Reset everything and start fresh

```bash
docker compose down -v        # Stop and remove volumes
sudo ./vps-deep-clean.sh      # Full clean
sudo ./deploy.sh              # Fresh deploy
```

---

## File Reference

| File | Purpose |
|------|---------|
| `vps-deep-clean.sh` | Deep clean script — wipe everything before fresh deploy |
| `deploy.sh` | One-command automated deployment |
| `Dockerfile` | Production Docker image (non-root, UTC, healthcheck) |
| `docker-compose.yml` | Service orchestration with resource limits and logging |
| `requirements-prod.txt` | Production-only Python dependencies |
| `.env.example` | Configuration template — copy to `.env` and edit |
| `360eye.service` | systemd unit for auto-start on reboot |
| `.dockerignore` | Prevents secrets and dev files from entering the image |
