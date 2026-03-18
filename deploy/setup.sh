#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="/home/pi/personal-team"
ENV_FILE="/home/pi/.env"
CREDS_DIR="/home/pi/.config/personal-team"
CREDS_FILE="$CREDS_DIR/drive-credentials.json"

echo "=== Personal Team Pi Setup ==="
echo ""

# ── 1. System packages ────────────────────────────────────────────────────────
echo "[1/9] Installing system packages..."
sudo apt update -qq
sudo apt install -y python3.11 python3.11-venv git sqlite3 fail2ban curl

# ── 2. uv ─────────────────────────────────────────────────────────────────────
echo "[2/9] Installing uv..."
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.cargo/bin:$PATH"

# ── 3. Clone repo ─────────────────────────────────────────────────────────────
echo "[3/9] Cloning repository..."
if [ ! -d "$REPO_DIR" ]; then
    read -rp "GitHub repo URL (e.g. https://github.com/you/personal-team.git): " REPO_URL
    git clone "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR"

# ── 4. Python environment ─────────────────────────────────────────────────────
echo "[4/9] Creating virtualenv and installing dependencies..."
uv venv .venv
uv pip install -r requirements.txt

# ── 5. Environment variables ──────────────────────────────────────────────────
echo "[5/9] Configuring environment variables..."
echo "Enter each value when prompted (leave blank to skip and set manually later):"

collect_var() {
    local key=$1
    local prompt=$2
    read -rp "  $prompt: " val
    echo "$key=$val"
}

{
    collect_var ANTHROPIC_API_KEY        "Anthropic API key"
    collect_var TELEGRAM_BOT_TOKEN       "Telegram bot token"
    collect_var ALLOWED_TELEGRAM_USER_ID "Your Telegram user ID"
    collect_var TELEGRAM_CHAT_ID         "Your Telegram chat ID with the bot"
    collect_var DRIVE_MEAL_PLANS_FOLDER_ID "Google Drive meal plans folder ID"
    collect_var DRIVE_BACKUP_FOLDER_ID    "Google Drive backup folder ID"
    echo "GOOGLE_CREDENTIALS_PATH=$CREDS_FILE"
} > "$ENV_FILE"
chmod 600 "$ENV_FILE"
echo "  Written to $ENV_FILE"

# ── 6. Drive service account credentials ─────────────────────────────────────
echo "[6/9] Setting up Google Drive credentials..."
mkdir -p "$CREDS_DIR"
echo "Paste your Drive service account JSON below, then press Enter and Ctrl+D:"
cat > "$CREDS_FILE"
chmod 600 "$CREDS_FILE"
echo "  Written to $CREDS_FILE"

# ── 7. SSH hardening ──────────────────────────────────────────────────────────
_harden_ssh() {
    sudo sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
    sudo sed -i 's/^#\?ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' /etc/ssh/sshd_config
    grep -q "^AllowUsers" /etc/ssh/sshd_config || echo "AllowUsers pi" | sudo tee -a /etc/ssh/sshd_config
    sudo systemctl restart sshd
    echo "  SSH hardened: password auth disabled, AllowUsers pi set."
}

echo "[7/9] SSH hardening..."
if [ ! -f "$HOME/.ssh/authorized_keys" ] || [ ! -s "$HOME/.ssh/authorized_keys" ]; then
    echo ""
    echo "  ⚠️  No SSH public key found in ~/.ssh/authorized_keys"
    echo "  You must add your SSH public key before disabling password auth."
    echo "  From your local machine, run:"
    echo "    ssh-copy-id pi@<pi-ip-address>"
    echo ""
    read -rp "  Have you added your SSH key? (yes/no): " KEY_CONFIRMED
    if [ "$KEY_CONFIRMED" != "yes" ]; then
        echo "  Skipping SSH hardening. Re-run setup.sh after adding your SSH key."
    else
        _harden_ssh
    fi
else
    _harden_ssh
fi

# ── 8. fail2ban ───────────────────────────────────────────────────────────────
echo "[8/9] Configuring fail2ban..."
sudo systemctl enable fail2ban
sudo systemctl start fail2ban
echo "  fail2ban active."

# ── 9. Tailscale ─────────────────────────────────────────────────────────────
echo "[9/9] Installing Tailscale..."
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
echo "  Tailscale up. Authenticate in the browser if prompted."

# ── systemd services ──────────────────────────────────────────────────────────
echo ""
echo "=== Installing systemd services ==="
sudo cp deploy/bot.service /etc/systemd/system/personal-team-bot.service
sudo cp deploy/scheduler.service /etc/systemd/system/personal-team-scheduler.service
sudo systemctl daemon-reload
sudo systemctl enable personal-team-bot personal-team-scheduler
sudo systemctl start personal-team-bot personal-team-scheduler

# ── Initialise database ───────────────────────────────────────────────────────
echo "Initialising database..."
.venv/bin/python -c "from agents.db import init_db; init_db(); print('Database ready.')"

# ── Smoke test ────────────────────────────────────────────────────────────────
echo ""
echo "=== Smoke test ==="
echo "Sending test Telegram message..."
source "$ENV_FILE"
.venv/bin/python - <<'PYEOF'
import os, asyncio, telegram
from dotenv import load_dotenv
load_dotenv("/home/pi/.env")
async def send():
    bot = telegram.Bot(token=os.environ["TELEGRAM_BOT_TOKEN"])
    await bot.send_message(
        chat_id=os.environ["TELEGRAM_CHAT_ID"],
        text="✅ Personal Team bot is live on the Pi!"
    )
asyncio.run(send())
PYEOF

echo ""
echo "=== Setup complete ==="
echo "Services running:"
sudo systemctl status personal-team-bot --no-pager -l | head -5
sudo systemctl status personal-team-scheduler --no-pager -l | head -5
echo ""
echo "To deploy updates:"
echo "  cd $REPO_DIR && git pull && sudo systemctl restart personal-team-bot personal-team-scheduler"
