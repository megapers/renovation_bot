# Deploy to Oracle Cloud Always Free

Step-by-step guide to deploy the Renovation Bot on Oracle Cloud's free ARM instance.

## What You Get (Free Forever)

- 4 OCPUs ARM (Ampere A1)
- 24 GB RAM
- 200 GB boot volume
- 10 TB/month outbound data

This is more than enough for the bot + database + Ollama embeddings.

---

## Step 1 — Create an Oracle Cloud Account

1. Go to [cloud.oracle.com](https://cloud.oracle.com)
2. Sign up for a free account (requires credit card for verification, won't be charged)
3. Choose a home region close to your users (e.g., Frankfurt for Europe)

## Step 2 — Create an ARM VM Instance

1. Go to **Compute → Instances → Create Instance**
2. Configure:
   - **Name:** `renovation-bot`
   - **Image:** Ubuntu 22.04 (or 24.04)
   - **Shape:** VM.Standard.A1.Flex
     - OCPUs: **4** (free up to 4)
     - Memory: **24 GB** (free up to 24)
   - **Boot volume:** 100 GB (free up to 200)
   - **Networking:** Create new VCN + public subnet
   - **SSH key:** Upload your public key or generate one

3. Click **Create** — wait 2-3 minutes for provisioning

## Step 3 — Configure Networking

### Open port for SSH only

The bot uses **polling** (outbound only) — no inbound ports needed except SSH.

1. Go to **Networking → Virtual Cloud Networks → your VCN**
2. Click your **Security List**
3. Verify **Ingress Rule** exists for:
   - Source: `0.0.0.0/0`
   - Protocol: TCP
   - Destination Port: **22** (SSH)

> **DO NOT** open ports 5432 (PostgreSQL) or 11434 (Ollama) to the internet.

### Open ports on the instance firewall

```bash
# SSH into your instance
ssh -i your_key ubuntu@<PUBLIC_IP>

# Ubuntu's iptables may block Docker traffic — open it
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 22 -j ACCEPT
sudo netfilter-persistent save
```

## Step 4 — Deploy

### Option A: Automated (recommended)

```bash
# SSH into your instance
ssh ubuntu@<PUBLIC_IP>

# Download and run the setup script
curl -fsSL https://raw.githubusercontent.com/YOUR_REPO/main/deploy/oracle-setup.sh -o setup.sh
chmod +x setup.sh
./setup.sh
```

### Option B: Manual

```bash
# SSH into your instance
ssh ubuntu@<PUBLIC_IP>

# Install Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
# Log out and back in for group change
exit
ssh ubuntu@<PUBLIC_IP>

# Clone project
sudo mkdir -p /opt/chatbot && sudo chown $USER /opt/chatbot
git clone YOUR_REPO_URL /opt/chatbot
cd /opt/chatbot

# Configure
cp .env.example .env
nano .env   # Fill in your values

# Start
docker compose -f docker-compose.prod.yaml up -d timescaledb ollama
sleep 15

# Pull embedding model
docker compose -f docker-compose.prod.yaml exec ollama ollama pull bge-m3

# Run migrations
docker compose -f docker-compose.prod.yaml run --rm bot alembic upgrade head

# Start bot
docker compose -f docker-compose.prod.yaml up -d bot
```

## Step 5 — Verify

```bash
# Check all services are running
docker compose -f docker-compose.prod.yaml ps

# Expected:
# timescaledb   running (healthy)
# ollama        running (healthy)
# renovation-bot running

# Check bot logs
docker compose -f docker-compose.prod.yaml logs -f bot

# Expected:
# Starting Renovation Chatbot...
# Bot identity: @your_bot ...
# Run polling for bot ...
```

Then send `/start` to your bot in Telegram.

## Step 6 — Set Up Auto-Restart

The services already have `restart: unless-stopped` in docker-compose. To survive VM reboots:

```bash
# Enable Docker to start on boot
sudo systemctl enable docker

# That's it — Docker restarts all containers with restart policy on boot
```

---

## Maintenance

### View logs

```bash
cd /opt/chatbot
docker compose -f docker-compose.prod.yaml logs -f bot        # bot only
docker compose -f docker-compose.prod.yaml logs -f             # all services
docker compose -f docker-compose.prod.yaml logs --tail 100 bot # last 100 lines
```

### Update the bot

```bash
cd /opt/chatbot
git pull
docker compose -f docker-compose.prod.yaml up -d --build bot
```

### Run migrations after update

```bash
docker compose -f docker-compose.prod.yaml run --rm bot alembic upgrade head
docker compose -f docker-compose.prod.yaml restart bot
```

### Database backup

```bash
# Create backup
docker compose -f docker-compose.prod.yaml exec timescaledb \
    pg_dump -U megapers renovbot > backup_$(date +%Y%m%d).sql

# Restore
docker compose -f docker-compose.prod.yaml exec -T timescaledb \
    psql -U megapers renovbot < backup_20260223.sql
```

### Monitor resources

```bash
# Docker stats
docker stats

# Disk usage
docker system df
df -h
```

---

## Expected Resource Usage

| Service | RAM | CPU | Disk |
|---|---|---|---|
| PostgreSQL + TimescaleDB | ~2 GB | Low | ~5-50 GB (grows with data) |
| Ollama + BGE-M3 | ~2 GB | Low (only during embedding) | ~2 GB |
| Bot (Python) | ~200 MB | Very low | ~500 MB |
| **Total** | **~4.5 GB** | **<1 OCPU** | **~55 GB** |

Leaves ~19 GB RAM free for OS and future growth. Well within the 24 GB free tier.

---

## Troubleshooting

| Issue | Fix |
|---|---|
| Bot not responding | `docker compose -f docker-compose.prod.yaml logs bot` |
| Database connection refused | `docker compose -f docker-compose.prod.yaml restart timescaledb` |
| Ollama embedding slow | Normal on ARM CPU (~2-3 sec). Not a problem. |
| Out of disk space | `docker system prune -a` to clean unused images |
| VM runs out of memory | Reduce Ollama model or remove it (use cloud embedding API) |
| Can't SSH after reboot | Check Oracle Security List + instance firewall |
| Container won't start | Check `.env` is present: `ls -la /opt/chatbot/.env` |
