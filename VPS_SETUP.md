# 360 Crypto Eye — VPS Setup Guide

## Minimum VPS Requirements

| Resource | Minimum |
|----------|---------|
| CPU | 2 vCPU |
| RAM | 2 GB |
| Disk | 20 GB SSD |
| OS | Ubuntu 22.04 LTS or newer |

---

## 1. Install Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
newgrp docker
```

Verify installation:

```bash
docker --version
docker compose version
```

---

## 2. Configure Firewall (UFW)

```bash
sudo ufw allow 22/tcp    # SSH
sudo ufw allow 5000/tcp  # Webhook
sudo ufw enable
sudo ufw status
```

---

## 3. Clone the Repository

```bash
git clone https://github.com/kishore446/360-Crypto-Eye-Scalping-.git /opt/360-crypto-eye
cd /opt/360-crypto-eye
```

---

## 4. Configure Environment

```bash
cp .env.example .env
nano .env
```

Fill in all required values (see `.env.example` for descriptions):

- `TELEGRAM_BOT_TOKEN` — from [@BotFather](https://t.me/BotFather)
- `TELEGRAM_CHANNEL_ID` — your channel ID (e.g. `-100xxxxxxxxxx`)
- `ADMIN_CHAT_ID` — your Telegram user ID
- `WEBHOOK_SECRET` — a strong random string (e.g. `openssl rand -hex 32`)

---

## 5. Clean VPS Before Fresh Deploy (Optional)

If your VPS has a previous installation or failed deployment, clean it first before running `deploy.sh`.

### Quick Clean (Docker-level only)

Stops containers, removes 360-related images, and prunes unused Docker resources — does **not** touch systemd or delete the repo:

```bash
./deploy.sh --clean
```

### Full Clean (removes containers, images, volumes, app data, and systemd service)

```bash
chmod +x vps-clean.sh
./vps-clean.sh
```

You will be prompted before destructive actions. To skip all prompts (for automation/CI):

```bash
./vps-clean.sh --force
```

### Nuclear Option (removes repo too — start completely from scratch)

```bash
./vps-clean.sh --force
# Then re-clone and deploy fresh:
git clone https://github.com/kishore446/360-Crypto-Eye-Scalping-.git /opt/360-crypto-eye
cd /opt/360-crypto-eye
cp .env.example .env && nano .env
chmod +x deploy.sh && ./deploy.sh
```

---

## 6. Deploy

```bash
chmod +x deploy.sh
./deploy.sh
```

The script will:
1. Check Docker is installed
2. Verify `.env` exists
3. Create the `data/` directory
4. Build and start all containers

---

## 7. Set Up Systemd Auto-Start

Copy the service file and enable it so the bot restarts automatically after a VPS reboot:

```bash
sudo cp 360eye.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable 360eye.service
sudo systemctl start 360eye.service
```

Check status:

```bash
sudo systemctl status 360eye.service
```

---

## 8. Monitoring Commands

```bash
# View running containers
docker compose ps

# Follow bot logs
docker compose logs -f bot

# Follow webhook logs
docker compose logs -f webhook

# Check container resource usage
docker stats
```

---

## 9. Updating the Bot

```bash
cd /opt/360-crypto-eye
git pull
docker compose up -d --build
```

Or use the deploy script for a clean rebuild:

```bash
./deploy.sh
```

---

## 10. Troubleshooting

### Bot container keeps restarting
```bash
docker compose logs bot --tail=50
```

### Webhook not reachable
```bash
# Check the port is open
curl http://localhost:5000/health

# Check firewall
sudo ufw status
```

### Out of disk space
```bash
# Remove unused Docker images and containers
docker system prune -f
```

### View data directory
```bash
ls -lh /var/lib/docker/volumes/360-crypto-eye_360eye-data/_data/
```

### Restart a specific service
```bash
docker compose restart bot
docker compose restart webhook
```

### Stop everything
```bash
docker compose down
```

### Stop and remove volumes (⚠️ deletes all data)
```bash
docker compose down -v
```
