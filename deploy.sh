#!/usr/bin/env bash
set -euo pipefail

echo "🚀 360 Crypto Eye — VPS Deployment"
echo "==================================="

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
DO_CLEAN=false
for arg in "$@"; do
    case "$arg" in
        --clean) DO_CLEAN=true ;;
        *) echo "❌ Unknown argument: $arg"; echo "Usage: $0 [--clean]"; exit 1 ;;
    esac
done

# Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "❌ Docker not installed. Run: curl -fsSL https://get.docker.com | sh"; exit 1; }
command -v docker compose >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1 || { echo "❌ Docker Compose not installed."; exit 1; }

# ---------------------------------------------------------------------------
# --clean: Docker-level cleanup before building
# ---------------------------------------------------------------------------
if [ "$DO_CLEAN" = true ]; then
    echo ""
    echo "🧹 --clean requested: performing Docker-level cleanup before build..."

    # Stop and remove existing compose services
    if [ -f docker-compose.yml ]; then
        echo "  Stopping existing services..."
        docker compose down 2>/dev/null || true
    fi

    # Remove any orphaned named containers
    for CNAME in 360eye-bot 360eye-webhook; do
        if docker ps -a --format '{{.Names}}' | grep -q "^${CNAME}$"; then
            echo "  Removing container: $CNAME"
            docker stop "$CNAME" 2>/dev/null || true
            docker rm   "$CNAME" 2>/dev/null || true
        fi
    done

    # Remove 360eye / 360-crypto-eye images (project-specific names only)
    IMAGE_IDS=$(docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' \
        | grep -iE "(^|/)(360eye|360-crypto-eye)" | awk '{print $2}' | sort -u || true)
    if [ -n "$IMAGE_IDS" ]; then
        echo "  Removing 360-related images..."
        echo "$IMAGE_IDS" | xargs -r docker rmi -f 2>/dev/null || true
    fi

    # Prune unused Docker resources (no --volumes to preserve data by default)
    echo "  Pruning unused Docker resources..."
    docker system prune -af 2>/dev/null || true

    # Clear BuildKit cache
    docker builder prune -af 2>/dev/null || true

    echo "✅ Docker-level cleanup complete."
    echo ""
fi

# Check .env exists
if [ ! -f .env ]; then
    echo "⚠️  No .env file found. Copying from .env.example..."
    cp .env.example .env
    echo "📝 Please edit .env with your credentials before continuing."
    echo "   nano .env"
    exit 1
fi

# Auto-generate WEBHOOK_SECRET if still a placeholder
if grep -q "generate_a_strong_random_secret" .env; then
    NEW_SECRET=$(openssl rand -hex 32)
    sed -i.bak "s/generate_a_strong_random_secret/$NEW_SECRET/" .env && rm -f .env.bak
    echo "🔑 Generated WEBHOOK_SECRET automatically."
fi

# Validate TELEGRAM_BOT_TOKEN is not still a placeholder
if grep -q "your_bot_token_from_botfather" .env; then
    echo "⚠️  TELEGRAM_BOT_TOKEN is still a placeholder. Please edit .env first."
    echo "   nano .env"
    exit 1
fi

# Ensure data directory exists (for non-Docker local testing)
mkdir -p data

# Build and start
echo "🔨 Building containers..."
docker compose build --no-cache

echo "🚀 Starting services..."
docker compose up -d

echo ""
echo "✅ Deployment complete!"
echo ""
echo "📊 Status:"
docker compose ps
echo ""
echo "📋 Useful commands:"
echo "  docker compose logs -f bot       # Follow bot logs"
echo "  docker compose logs -f webhook   # Follow webhook logs"
echo "  docker compose restart bot       # Restart bot"
echo "  docker compose down              # Stop all"
echo "  docker compose up -d --build     # Rebuild and restart"
