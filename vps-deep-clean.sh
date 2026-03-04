#!/usr/bin/env bash
# ==============================================================================
# 360 Crypto Eye Scalping — VPS Deep Clean Script
# Wipes all Docker resources, old bot installations, logs, and caches
# for a completely fresh deployment.
# ==============================================================================
set -euo pipefail

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
error()   { echo -e "${RED}[ERROR]${RESET} $1"; }
ok()      { echo -e "${GREEN}[OK]${RESET}    $1"; }

CLEANED_ITEMS=()

# ── 1. Current disk usage ─────────────────────────────────────────────────────
section "Current Disk Usage"
df -h / 2>/dev/null || true
DISK_BEFORE=$(df / | awk 'NR==2{print $3}')

# ── 2. Confirmation prompt ────────────────────────────────────────────────────
section "⚠  WARNING — Destructive Operation"
echo -e "${RED}This script will permanently delete:${RESET}"
echo "  • ALL Docker containers, images, volumes, and networks"
echo "  • Old bot installation directories (/opt/360-crypto-eye, /root/360*)"
echo "  • Old systemd services for the bot"
echo "  • Old Python virtual environments in bot directories"
echo "  • Pip cache"
echo "  • Old log files"
echo "  • Stale data files (signals.json, dashboard.json, 360eye.db)"
echo "  • Apt cache"
echo ""
read -rp "$(echo -e "${BOLD}Continue? [y/N]:${RESET} ")" CONFIRM
if [[ "${CONFIRM,,}" != "y" ]]; then
    echo -e "\n${YELLOW}Aborted. Nothing was changed.${RESET}"
    exit 0
fi

# ── 3. Stop all running Docker containers ─────────────────────────────────────
section "Stopping All Docker Containers"
if command -v docker &>/dev/null; then
    RUNNING=$(docker ps -q 2>/dev/null || true)
    if [[ -n "$RUNNING" ]]; then
        docker stop $RUNNING && ok "Stopped $(echo "$RUNNING" | wc -w) running container(s)"
        CLEANED_ITEMS+=("Stopped running Docker containers")
    else
        info "No running containers to stop"
    fi
else
    warn "Docker not installed — skipping container stop"
fi

# ── 4. Remove all Docker containers, images, volumes, networks ────────────────
section "Removing All Docker Containers"
if command -v docker &>/dev/null; then
    ALL_CONTAINERS=$(docker ps -aq 2>/dev/null || true)
    if [[ -n "$ALL_CONTAINERS" ]]; then
        docker rm -f $ALL_CONTAINERS && ok "Removed all containers"
        CLEANED_ITEMS+=("Removed all Docker containers")
    else
        info "No containers to remove"
    fi

    section "Removing All Docker Images"
    ALL_IMAGES=$(docker images -q 2>/dev/null || true)
    if [[ -n "$ALL_IMAGES" ]]; then
        docker rmi -f $ALL_IMAGES && ok "Removed all images"
        CLEANED_ITEMS+=("Removed all Docker images")
    else
        info "No images to remove"
    fi

    section "Removing All Docker Volumes"
    ALL_VOLUMES=$(docker volume ls -q 2>/dev/null || true)
    if [[ -n "$ALL_VOLUMES" ]]; then
        docker volume rm $ALL_VOLUMES && ok "Removed all volumes"
        CLEANED_ITEMS+=("Removed all Docker volumes")
    else
        info "No volumes to remove"
    fi

    section "Removing All Docker Networks"
    docker network prune -f && ok "Removed unused Docker networks"
    CLEANED_ITEMS+=("Pruned Docker networks")
fi

# ── 5. Docker system prune ────────────────────────────────────────────────────
section "Docker System Prune (--all --volumes)"
if command -v docker &>/dev/null; then
    docker system prune --all --volumes --force && ok "Docker system pruned"
    CLEANED_ITEMS+=("Docker system prune completed")
else
    warn "Docker not installed — skipping system prune"
fi

# ── 6. Remove Docker build cache ──────────────────────────────────────────────
section "Removing Docker Build Cache"
if command -v docker &>/dev/null; then
    docker builder prune --all --force 2>/dev/null && ok "Docker build cache cleared" || warn "Could not clear builder cache (may not exist)"
    CLEANED_ITEMS+=("Docker build cache cleared")
fi

# ── 7. Remove old bot installation directories ────────────────────────────────
section "Removing Old Bot Installation Directories"
BOT_DIRS=(
    "/opt/360-crypto-eye"
    "/opt/360eye"
    "/opt/crypto-eye"
    "/root/360eye"
    "/home/ubuntu/360eye"
)
for DIR in "${BOT_DIRS[@]}"; do
    if [[ -d "$DIR" ]]; then
        rm -rf "$DIR" && ok "Removed $DIR"
        CLEANED_ITEMS+=("Removed directory: $DIR")
    fi
done
# Wildcard removal for /root/360* and /home/ubuntu/360* patterns not caught above
for DIR in /root/360* /home/ubuntu/360*; do
    if [[ -d "$DIR" ]]; then
        rm -rf "$DIR" && ok "Removed $DIR"
        CLEANED_ITEMS+=("Removed directory: $DIR")
    fi
done

# ── 8. Remove old systemd services ────────────────────────────────────────────
section "Removing Old systemd Services"
BOT_SERVICES=(
    "360eye.service"
    "360eye-bot.service"
    "crypto-eye.service"
    "crypto-scalping.service"
    "360-crypto-eye.service"
)
for SVC in "${BOT_SERVICES[@]}"; do
    SVC_PATH="/etc/systemd/system/${SVC}"
    if systemctl is-active --quiet "$SVC" 2>/dev/null; then
        systemctl stop "$SVC" && info "Stopped $SVC"
    fi
    if systemctl is-enabled --quiet "$SVC" 2>/dev/null; then
        systemctl disable "$SVC" && info "Disabled $SVC"
    fi
    if [[ -f "$SVC_PATH" ]]; then
        rm -f "$SVC_PATH" && ok "Removed $SVC_PATH"
        CLEANED_ITEMS+=("Removed systemd service: $SVC")
    fi
done
systemctl daemon-reload 2>/dev/null && ok "systemd daemon reloaded" || warn "Could not reload systemd daemon"

# ── 9. Remove old Python virtual environments ─────────────────────────────────
section "Removing Old Python Virtual Environments"
VENV_PATTERNS=(
    "/opt/360-crypto-eye/venv"
    "/opt/360eye/venv"
    "/root/360*/venv"
    "/root/360*/.venv"
    "/home/ubuntu/360*/venv"
    "/home/ubuntu/360*/.venv"
)
for PATTERN in "${VENV_PATTERNS[@]}"; do
    for VENV in $PATTERN; do
        if [[ -d "$VENV" ]]; then
            rm -rf "$VENV" && ok "Removed venv: $VENV"
            CLEANED_ITEMS+=("Removed Python venv: $VENV")
        fi
    done
done

# ── 10. Clean pip cache ───────────────────────────────────────────────────────
section "Cleaning Pip Cache"
if command -v pip &>/dev/null || command -v pip3 &>/dev/null; then
    PIP_CMD=$(command -v pip3 || command -v pip)
    $PIP_CMD cache purge 2>/dev/null && ok "Pip cache cleared" || warn "Could not clear pip cache"
    CLEANED_ITEMS+=("Pip cache cleared")
fi
if [[ -d "$HOME/.cache/pip" ]]; then
    rm -rf "$HOME/.cache/pip" && ok "Removed $HOME/.cache/pip"
    CLEANED_ITEMS+=("Removed ~/.cache/pip")
fi

# ── 11. Remove old log files ──────────────────────────────────────────────────
section "Removing Old Log Files"
LOG_PATHS=(
    "/var/log/360eye*"
    "/var/log/crypto-eye*"
    "/var/log/360-crypto*"
    "/opt/360-crypto-eye/*.log"
    "/root/360*/*.log"
    "/tmp/360eye*"
    "/tmp/crypto-eye*"
)
for PATTERN in "${LOG_PATHS[@]}"; do
    for F in $PATTERN; do
        if [[ -f "$F" || -d "$F" ]]; then
            rm -rf "$F" && ok "Removed: $F"
            CLEANED_ITEMS+=("Removed log: $F")
        fi
    done
done
# Rotate/clear Docker container logs
if [[ -d "/var/lib/docker/containers" ]]; then
    find /var/lib/docker/containers -name "*.log" -type f -exec truncate -s 0 {} \; 2>/dev/null && ok "Truncated Docker container logs" || warn "Could not truncate Docker logs (run as root?)"
    CLEANED_ITEMS+=("Truncated Docker container logs")
fi

# ── 12. Remove stale data files ───────────────────────────────────────────────
section "Removing Stale Data Files"
warn "The following stale data files will be removed (backup first if needed):"
STALE_FILES=(
    "/opt/360-crypto-eye/signals.json"
    "/opt/360-crypto-eye/dashboard.json"
    "/opt/360-crypto-eye/360eye.db"
    "/opt/360-crypto-eye/data/signals.json"
    "/opt/360-crypto-eye/data/dashboard.json"
    "/opt/360-crypto-eye/data/360eye.db"
    "/root/signals.json"
    "/root/dashboard.json"
    "/root/360eye.db"
)
for F in "${STALE_FILES[@]}"; do
    if [[ -f "$F" ]]; then
        warn "Removing: $F"
        rm -f "$F" && ok "Removed: $F"
        CLEANED_ITEMS+=("Removed stale data file: $F")
    fi
done

# Warn about any .env files found
warn "Checking for stale .env files (NOT removing — review manually):"
find /opt /root /home -name ".env" -not -name ".env.example" 2>/dev/null | while read -r ENVFILE; do
    warn "  Found: $ENVFILE  (NOT auto-removed — remove manually if stale)"
done || true

# ── 13. Clean apt cache ───────────────────────────────────────────────────────
section "Cleaning Apt Cache"
if command -v apt-get &>/dev/null; then
    apt-get autoremove -y 2>/dev/null && ok "apt autoremove done"
    apt-get clean 2>/dev/null && ok "apt clean done"
    CLEANED_ITEMS+=("apt cache cleaned")
else
    warn "apt-get not available — skipping"
fi

# ── 14. Optional: OS package update ──────────────────────────────────────────
section "Optional: OS Package Update"
read -rp "$(echo -e "${BOLD}Run apt update && apt upgrade now? [y/N]:${RESET} ")" DO_UPGRADE
if [[ "${DO_UPGRADE,,}" == "y" ]]; then
    if command -v apt-get &>/dev/null; then
        apt-get update -y && apt-get upgrade -y && ok "OS packages updated"
        CLEANED_ITEMS+=("OS packages updated")
    else
        warn "apt-get not available — skipping"
    fi
else
    info "Skipping OS upgrade"
fi

# ── 15. Final disk usage + summary ───────────────────────────────────────────
section "Final Disk Usage"
df -h / 2>/dev/null || true
DISK_AFTER=$(df / | awk 'NR==2{print $3}')
DISK_FREED=$(( DISK_BEFORE - DISK_AFTER ))

section "✅  Deep Clean Summary"
echo -e "${GREEN}Items cleaned:${RESET}"
for ITEM in "${CLEANED_ITEMS[@]}"; do
    echo "  ✔ $ITEM"
done

echo ""
echo -e "${GREEN}Disk used before: ${BOLD}${DISK_BEFORE} KB${RESET}"
echo -e "${GREEN}Disk used after:  ${BOLD}${DISK_AFTER} KB${RESET}"
if (( DISK_FREED > 0 )); then
    echo -e "${GREEN}Disk freed:       ${BOLD}${DISK_FREED} KB${RESET}"
else
    echo -e "${YELLOW}Note: Disk usage reporting may vary due to filesystem caching.${RESET}"
fi

echo ""
echo -e "${GREEN}${BOLD}VPS is now clean and ready for a fresh deployment.${RESET}"
echo -e "Run ${CYAN}./deploy.sh${RESET} to deploy the bot."
