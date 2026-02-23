#!/bin/bash
# ═══════════════════════════════════════════════════════════
# Oracle Cloud Always Free — Renovation Bot Setup Script
# Run this on a fresh Oracle Cloud ARM instance
# ═══════════════════════════════════════════════════════════

set -e

echo "═══════════════════════════════════════════"
echo "  Renovation Bot — Oracle Cloud Setup"
echo "═══════════════════════════════════════════"

# ── 1. Update system ─────────────────────────────────────
echo "1/6  Updating system packages..."
sudo apt-get update && sudo apt-get upgrade -y

# ── 2. Install Docker ────────────────────────────────────
echo "2/6  Installing Docker..."
if ! command -v docker &> /dev/null; then
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    rm get-docker.sh
    echo "Docker installed. You may need to log out and back in for group changes."
fi

# Install Docker Compose plugin
sudo apt-get install -y docker-compose-plugin

# ── 3. Install Git ───────────────────────────────────────
echo "3/6  Installing Git..."
sudo apt-get install -y git

# ── 4. Clone the project ────────────────────────────────
echo "4/6  Cloning project..."
if [ ! -d "/opt/chatbot" ]; then
    sudo mkdir -p /opt/chatbot
    sudo chown $USER:$USER /opt/chatbot
    git clone YOUR_REPO_URL /opt/chatbot
else
    echo "  Project already exists at /opt/chatbot"
    cd /opt/chatbot && git pull
fi

cd /opt/chatbot

# ── 5. Configure environment ────────────────────────────
echo "5/6  Setting up environment..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "  ⚠️  IMPORTANT: Edit .env with your values:"
    echo "     nano /opt/chatbot/.env"
    echo ""
    echo "  Required settings:"
    echo "    TELEGRAM_BOT_TOKEN=your_bot_token"
    echo "    ADMIN_TELEGRAM_IDS=your_telegram_id"
    echo "    AI_API_KEY=your_groq_api_key"
    echo "    AI_WHISPER_API_KEY=your_groq_api_key"
    echo ""
    echo "  Press Enter after editing .env to continue..."
    read
fi

# ── 6. Start services ───────────────────────────────────
echo "6/6  Starting services..."

# Start database + ollama first
docker compose -f docker-compose.prod.yaml up -d timescaledb ollama

echo "  Waiting for database to be ready..."
sleep 10

# Pull embedding model into Ollama
echo "  Pulling BGE-M3 embedding model..."
docker compose -f docker-compose.prod.yaml exec ollama ollama pull bge-m3

# Run database migrations
echo "  Running database migrations..."
docker compose -f docker-compose.prod.yaml run --rm bot \
    alembic upgrade head

# Start the bot
docker compose -f docker-compose.prod.yaml up -d bot

echo ""
echo "═══════════════════════════════════════════"
echo "  ✅ Deployment complete!"
echo ""
echo "  Services:"
echo "    docker compose -f docker-compose.prod.yaml ps"
echo ""
echo "  Logs:"
echo "    docker compose -f docker-compose.prod.yaml logs -f bot"
echo ""
echo "  Stop:"
echo "    docker compose -f docker-compose.prod.yaml down"
echo ""
echo "  Update:"
echo "    cd /opt/chatbot"
echo "    git pull"
echo "    docker compose -f docker-compose.prod.yaml up -d --build bot"
echo "═══════════════════════════════════════════"
