#!/usr/bin/env bash
set -euo pipefail

# ---------------------------------------------------------------------------
# vps-clean.sh — Comprehensive VPS cleanup for 360 Crypto Eye
# ---------------------------------------------------------------------------

# Color helpers
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

info()    { echo -e "${CYAN}ℹ️  $*${NC}"; }
success() { echo -e "${GREEN}✅ $*${NC}"; }
warn()    { echo -e "${YELLOW}⚠️  $*${NC}"; }
error()   { echo -e "${RED}❌ $*${NC}"; }
header()  { echo -e "\n${BOLD}${CYAN}--- $* ---${NC}"; }

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
FORCE=false
for arg in "$@"; do
    case "$arg" in
        -f|--force) FORCE=true ;;
        *) error "Unknown argument: $arg"; echo "Usage: $0 [--force|-f]"; exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# Confirmation prompt
# ---------------------------------------------------------------------------
echo -e "${BOLD}${YELLOW}"
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║       360 Crypto Eye — VPS Full Cleanup                     ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

if [ "$FORCE" = false ]; then
    warn "This will remove ALL 360 Crypto Eye containers, images, volumes, and data."
    echo -n "Continue? (y/N) "
    read -r CONFIRM
    case "$CONFIRM" in
        [yY][eE][sS]|[yY]) ;;
        *) info "Aborted."; exit 0 ;;
    esac
fi

# Track what was cleaned for the summary
CLEANED=()

# ---------------------------------------------------------------------------
# Phase 1 — Stop running 360eye services
# ---------------------------------------------------------------------------
header "Phase 1 — Stop running 360 Crypto Eye services"

if [ -f docker-compose.yml ]; then
    info "Running docker compose down..."
    docker compose down 2>/dev/null && success "docker compose down complete." || warn "docker compose down had warnings (continuing)."
    CLEANED+=("docker compose down")
else
    warn "No docker-compose.yml in current directory — skipping compose down."
fi

for CNAME in 360eye-bot 360eye-webhook; do
    if docker ps -a --format '{{.Names}}' | grep -q "^${CNAME}$"; then
        info "Stopping and removing container: $CNAME"
        docker stop "$CNAME" 2>/dev/null || true
        docker rm   "$CNAME" 2>/dev/null || true
        success "Removed container: $CNAME"
        CLEANED+=("container:$CNAME")
    else
        info "Container not found (already removed): $CNAME"
    fi
done

# ---------------------------------------------------------------------------
# Phase 2 — Remove 360eye Docker images
# ---------------------------------------------------------------------------
header "Phase 2 — Remove 360 Crypto Eye Docker images"

# Gather image IDs that belong to this project (repository or tag contains '360eye' or '360-crypto-eye')
IMAGE_IDS=$(docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' \
    | grep -iE "(^|/)(360eye|360-crypto-eye)" | awk '{print $2}' | sort -u || true)

if [ -n "$IMAGE_IDS" ]; then
    echo "$IMAGE_IDS" | while read -r IMG_ID; do
        info "Removing image: $IMG_ID"
        docker rmi -f "$IMG_ID" 2>/dev/null && success "Removed image: $IMG_ID" || warn "Could not remove image $IMG_ID (may be in use)."
        CLEANED+=("image:$IMG_ID")
    done
else
    info "No 360-related Docker images found."
fi

# Also try to remove by compose project label (project name = directory name or "360-crypto-eye")
COMPOSE_IMGS=$(docker images --filter "label=com.docker.compose.project" --format '{{.Repository}}:{{.Tag}} {{.ID}}' \
    | grep -iE "(^|/)(360eye|360-crypto-eye)" | awk '{print $2}' | sort -u || true)
if [ -n "$COMPOSE_IMGS" ]; then
    echo "$COMPOSE_IMGS" | while read -r IMG_ID; do
        info "Removing compose-labelled image: $IMG_ID"
        docker rmi -f "$IMG_ID" 2>/dev/null && success "Removed image: $IMG_ID" || warn "Could not remove image $IMG_ID."
    done
fi

# ---------------------------------------------------------------------------
# Phase 3 — Clean Docker system
# ---------------------------------------------------------------------------
header "Phase 3 — Clean Docker system (unused images, networks, build cache)"

info "Running docker system prune -af --volumes..."
docker system prune -af --volumes 2>/dev/null && success "docker system prune complete." || warn "docker system prune had warnings."
CLEANED+=("docker system prune -af --volumes")

# Remove the compose-volume for 360eye-data (may be prefixed by project)
for VOL in 360eye-data 360-crypto-eye_360eye-data; do
    if docker volume ls --format '{{.Name}}' | grep -q "^${VOL}$"; then
        info "Removing Docker volume: $VOL"
        docker volume rm "$VOL" 2>/dev/null && success "Removed volume: $VOL" || warn "Could not remove volume $VOL (may be in use)."
        CLEANED+=("volume:$VOL")
    else
        info "Volume not found (already removed): $VOL"
    fi
done

info "Running docker builder prune -af (clear BuildKit cache)..."
docker builder prune -af 2>/dev/null && success "BuildKit cache cleared." || warn "docker builder prune had warnings."
CLEANED+=("docker builder prune -af")

# ---------------------------------------------------------------------------
# Phase 4 — Clean stale app data
# ---------------------------------------------------------------------------
header "Phase 4 — Clean stale app data"

APP_DATA_DIR="/opt/360-crypto-eye/data"
if [ -d "$APP_DATA_DIR" ]; then
    info "Removing contents of $APP_DATA_DIR (signals.json, dashboard.json, 360eye.db)..."
    rm -f "$APP_DATA_DIR/signals.json" \
          "$APP_DATA_DIR/dashboard.json" \
          "$APP_DATA_DIR/360eye.db"
    success "Cleared $APP_DATA_DIR contents (directory kept)."
    CLEANED+=("app data in $APP_DATA_DIR")
else
    info "App data directory not found: $APP_DATA_DIR — nothing to clean."
fi

# Also clean local data/ if we are running from the repo root
LOCAL_DATA_DIR="./data"
if [ -d "$LOCAL_DATA_DIR" ]; then
    info "Removing contents of local ./data/ directory..."
    rm -f "$LOCAL_DATA_DIR/signals.json" \
          "$LOCAL_DATA_DIR/dashboard.json" \
          "$LOCAL_DATA_DIR/360eye.db"
    success "Cleared ./data/ contents (directory kept)."
    CLEANED+=("app data in ./data/")
fi

# ---------------------------------------------------------------------------
# Phase 5 — Remove old systemd service (if installed)
# ---------------------------------------------------------------------------
header "Phase 5 — Remove old systemd service"

SYSTEMD_UNIT="/etc/systemd/system/360eye.service"
if systemctl list-unit-files 2>/dev/null | grep -q "360eye.service"; then
    info "Stopping systemd service 360eye.service..."
    sudo systemctl stop    360eye.service 2>/dev/null || warn "Could not stop 360eye.service."
    sudo systemctl disable 360eye.service 2>/dev/null || warn "Could not disable 360eye.service."
    CLEANED+=("systemd:360eye.service stopped+disabled")
else
    info "360eye.service is not loaded by systemd."
fi

if [ -f "$SYSTEMD_UNIT" ]; then
    info "Removing $SYSTEMD_UNIT..."
    sudo rm -f "$SYSTEMD_UNIT"
    sudo systemctl daemon-reload
    success "Removed $SYSTEMD_UNIT and reloaded systemd."
    CLEANED+=("systemd unit file removed")
else
    info "Systemd unit file not found: $SYSTEMD_UNIT"
fi

# ---------------------------------------------------------------------------
# Phase 6 — Optional: Remove old repo clone
# ---------------------------------------------------------------------------
header "Phase 6 — Optional: Remove old repo clone"

REPO_DIR="/opt/360-crypto-eye"
REMOVE_REPO=false

if [ -d "$REPO_DIR" ]; then
    if [ "$FORCE" = true ]; then
        REMOVE_REPO=true
    else
        warn "Found existing repo clone at $REPO_DIR."
        echo -n "Remove $REPO_DIR entirely? (y/N) "
        read -r REPO_CONFIRM
        case "$REPO_CONFIRM" in
            [yY][eE][sS]|[yY]) REMOVE_REPO=true ;;
            *) info "Keeping $REPO_DIR." ;;
        esac
    fi

    if [ "$REMOVE_REPO" = true ]; then
        info "Removing $REPO_DIR..."
        rm -rf "$REPO_DIR"
        success "Removed $REPO_DIR."
        CLEANED+=("repo dir:$REPO_DIR")
    fi
else
    info "Repo directory not found: $REPO_DIR — nothing to remove."
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════════════════════╗"
echo "║               Cleanup Summary                               ║"
echo -e "╚══════════════════════════════════════════════════════════════╝${NC}"

if [ ${#CLEANED[@]} -eq 0 ]; then
    info "Nothing was cleaned — environment was already tidy."
else
    echo -e "${GREEN}The following items were cleaned:${NC}"
    for ITEM in "${CLEANED[@]}"; do
        echo -e "  ${GREEN}✔${NC}  $ITEM"
    done
fi

echo ""
success "VPS cleanup complete. You can now run a fresh deployment:"
echo "   chmod +x deploy.sh && ./deploy.sh"
