#!/usr/bin/env bash
set -euo pipefail

echo "🚀 360 Crypto Eye — VPS Deployment"
echo "==================================="

# Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "❌ Docker not installed. Run: curl -fsSL https://get.docker.com | sh"; exit 1; }
command -v docker compose >/dev/null 2>&1 || command -v docker-compose >/dev/null 2>&1 || { echo "❌ Docker Compose not installed."; exit 1; }

# Check .env exists
if [ ! -f .env ]; then
    echo "⚠️  No .env file found. Copying from .env.example..."
    cp .env.example .env
    echo "📝 Please edit .env with your credentials before continuing."
    echo "   nano .env"
    exit 1
fi

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
