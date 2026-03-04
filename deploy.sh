#!/usr/bin/env bash
# ==============================================================================
# 360 Crypto Eye Scalping — Fresh VPS Deployment Script
# One-command deployment: installs Docker, clones repo, configures, and starts.
# ==============================================================================
set -euo pipefail

# ── Configuration ─────────────────────────────────────────────────────────────
REPO_URL="https://github.com/kishore446/360-Crypto-Eye-Scalping-.git"
INSTALL_DIR="/opt/360-crypto-eye"
SERVICE_NAME="360eye"
WEBHOOK_PORT=5000
SSH_PORT=22

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

# ── Helpers ───────────────────────────────────────────────────────────────────
section() { echo -e "\n${CYAN}${BOLD}══════════════════════════════════════════${RESET}"; echo -e "${CYAN}${BOLD}  $1${RESET}"; echo -e "${CYAN}${BOLD}══════════════════════════════════════════${RESET}"; }
info()    { echo -e "${GREEN}[INFO]${RESET}  $1"; }
warn()    { echo -e "${YELLOW}[WARN]${RESET}  $1"; }
error()   { echo -e "${RED}[ERROR]${RESET} $1"; exit 1; }
ok()      { echo -e "${GREEN}[OK]${RESET}    $1"; }

require_root() {
    if [[ "$EUID" -ne 0 ]]; then
        error "This script must be run as root. Try: sudo ./deploy.sh"
    fi
}

# ── 1. Root check ─────────────────────────────────────────────────────────────
require_root

section "360 Crypto Eye Scalping — VPS Deployment"
echo -e "Install directory: ${BOLD}${INSTALL_DIR}${RESET}"
echo -e "Webhook port:      ${BOLD}${WEBHOOK_PORT}${RESET}"
echo ""

# ── 2. Check & install prerequisites ─────────────────────────────────────────
section "Checking Prerequisites"

# git
if ! command -v git &>/dev/null; then
    info "Installing git..."
    apt-get update -y && apt-get install -y git
fi
ok "git $(git --version | awk '{print $3}')"

# Docker
if ! command -v docker &>/dev/null; then
    section "Installing Docker"
    apt-get update -y
    apt-get install -y ca-certificates curl gnupg lsb-release
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
        gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
        tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
    ok "Docker installed"
else
    ok "Docker $(docker --version | awk '{print $3}' | tr -d ',')"
fi

# Docker Compose plugin
if ! docker compose version &>/dev/null 2>&1; then
    section "Installing Docker Compose Plugin"
    apt-get update -y && apt-get install -y docker-compose-plugin
    ok "Docker Compose plugin installed"
else
    ok "Docker Compose $(docker compose version --short 2>/dev/null || echo 'available')"
fi

# ── 3. Configure UFW firewall ─────────────────────────────────────────────────
section "Configuring UFW Firewall"
if command -v ufw &>/dev/null; then
    ufw allow "${SSH_PORT}/tcp" comment "SSH" 2>/dev/null || true
    ufw allow "${WEBHOOK_PORT}/tcp" comment "360eye-webhook" 2>/dev/null || true
    ufw --force enable 2>/dev/null || true
    ok "UFW rules applied (SSH:${SSH_PORT}, Webhook:${WEBHOOK_PORT})"
else
    warn "ufw not installed — skipping firewall configuration"
fi

# ── 4. Clone or update repository ────────────────────────────────────────────
section "Setting Up Repository"
if [[ -d "${INSTALL_DIR}/.git" ]]; then
    info "Repository already exists at ${INSTALL_DIR} — pulling latest..."
    cd "${INSTALL_DIR}"
    git pull --ff-only
    ok "Repository updated"
else
    info "Cloning repository to ${INSTALL_DIR}..."
    git clone "${REPO_URL}" "${INSTALL_DIR}"
    ok "Repository cloned"
fi
cd "${INSTALL_DIR}"

# ── 5. Configure environment ──────────────────────────────────────────────────
section "Configuring Environment"
if [[ ! -f "${INSTALL_DIR}/.env" ]]; then
    cp "${INSTALL_DIR}/.env.example" "${INSTALL_DIR}/.env"
    warn ".env created from .env.example"
    warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    warn "ACTION REQUIRED: Edit .env with your credentials NOW:"
    warn "  nano ${INSTALL_DIR}/.env"
    warn "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
    read -rp "$(echo -e "${BOLD}Press Enter after editing .env to continue, or Ctrl+C to abort...${RESET}")" _
else
    ok ".env already exists — using existing configuration"
fi

# ── 6. Create data directory ──────────────────────────────────────────────────
section "Creating Data Directory"
mkdir -p "${INSTALL_DIR}/data"
chmod 755 "${INSTALL_DIR}/data"
ok "data/ directory ready"

# ── 7. Build Docker images ────────────────────────────────────────────────────
section "Building Docker Images (--no-cache)"
cd "${INSTALL_DIR}"
docker compose build --no-cache
ok "Docker images built"

# ── 8. Start services ─────────────────────────────────────────────────────────
section "Starting Services"
docker compose up -d --remove-orphans
ok "Services started"

# ── 9. Install systemd service ────────────────────────────────────────────────
section "Installing systemd Service (Auto-Start on Reboot)"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
if [[ -f "${INSTALL_DIR}/360eye.service" ]]; then
    cp "${INSTALL_DIR}/360eye.service" "${SERVICE_FILE}"
    # Patch WorkingDirectory to actual install dir
    sed -i "s|WorkingDirectory=.*|WorkingDirectory=${INSTALL_DIR}|g" "${SERVICE_FILE}"
    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}.service"
    ok "systemd service installed and enabled"
else
    warn "360eye.service not found in repo — creating inline service..."
    cat > "${SERVICE_FILE}" <<EOF
[Unit]
Description=360 Crypto Eye Scalping Bot
Documentation=https://github.com/kishore446/360-Crypto-Eye-Scalping-
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${INSTALL_DIR}
ExecStartPre=/usr/bin/docker compose pull
ExecStart=/usr/bin/docker compose up -d --remove-orphans
ExecStop=/usr/bin/docker compose down
ExecReload=/usr/bin/docker compose restart
TimeoutStartSec=300
Restart=on-failure
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}.service"
    ok "systemd service created and enabled"
fi

# ── 10. Set up log rotation ───────────────────────────────────────────────────
section "Configuring Log Rotation"
cat > /etc/logrotate.d/360eye-docker <<'EOF'
/var/lib/docker/containers/*/*-json.log {
    daily
    missingok
    rotate 7
    compress
    delaycompress
    copytruncate
    notifempty
}
EOF
ok "Log rotation configured"

# ── 11. Verify deployment health ─────────────────────────────────────────────
section "Verifying Deployment"
info "Waiting 15 seconds for services to initialise..."
sleep 15

RUNNING=$(docker compose ps --services --filter "status=running" 2>/dev/null || true)
if [[ -n "$RUNNING" ]]; then
    ok "Running services: $RUNNING"
else
    warn "No services reported as running yet — they may still be starting."
    warn "Check with: docker compose logs -f"
fi

# Quick webhook health check
if curl -sf "http://localhost:${WEBHOOK_PORT}/health" &>/dev/null; then
    ok "Webhook health check passed (http://localhost:${WEBHOOK_PORT}/health)"
else
    warn "Webhook not yet responding on port ${WEBHOOK_PORT} (may still be starting)"
fi

# ── 12. Final summary ─────────────────────────────────────────────────────────
section "✅  Deployment Complete"
echo -e "${GREEN}${BOLD}360 Crypto Eye Scalping bot is deployed!${RESET}"
echo ""
echo -e "${BOLD}Useful commands:${RESET}"
echo -e "  ${CYAN}docker compose logs -f${RESET}                  # Follow all logs"
echo -e "  ${CYAN}docker compose logs -f bot${RESET}              # Bot logs only"
echo -e "  ${CYAN}docker compose logs -f webhook${RESET}          # Webhook logs only"
echo -e "  ${CYAN}docker compose ps${RESET}                       # Service status"
echo -e "  ${CYAN}docker compose restart${RESET}                  # Restart all services"
echo -e "  ${CYAN}docker compose down && docker compose up -d${RESET}  # Full restart"
echo -e "  ${CYAN}systemctl status ${SERVICE_NAME}${RESET}        # systemd service status"
echo ""
echo -e "${BOLD}Install directory:${RESET} ${INSTALL_DIR}"
echo -e "${BOLD}Webhook URL:${RESET}       http://<your-vps-ip>:${WEBHOOK_PORT}/health"
