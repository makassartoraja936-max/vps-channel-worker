#!/bin/bash
# ==============================================================================
# VPS Channel Worker - Setup and Installation Script
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$HOME/workspace"

echo "=========================================================="
echo "🚀 Installing VPS Channel Worker with Auto-Start Browser..."
echo "📁 Source Directory: $SCRIPT_DIR"
echo "=========================================================="

# 1. Install Python dependencies
echo "📦 Installing Python packages (PEP 668 compatible)..."
pip3 install --quiet --upgrade --break-system-packages -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null || \
pip install --quiet --upgrade --break-system-packages -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null || \
pip3 install --quiet --upgrade -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null || true

# 2. Install Playwright Chromium browser binary
echo "🌐 Installing Playwright Chromium browser..."
python3 -m playwright install chromium || true
python3 -m playwright install-deps chromium 2>/dev/null || true

# 3. Initialize default autostart URL if not already set
mkdir -p "$WORKSPACE"
if [ ! -f "$WORKSPACE/autostart_url.txt" ]; then
    echo "https://studiolab.sagemaker.aws/login" > "$WORKSPACE/autostart_url.txt"
fi

# 4. Create run script for daemon persistence
echo "⚙️ Creating startup launcher..."
cat << 'EOF_LAUNCH' > "$SCRIPT_DIR/run.sh"
#!/bin/bash
cd "$(dirname "$0")"

# Ensure unbuffered Python output for real-time logs
export PYTHONUNBUFFERED=1

# Ensure Python virtual environment if exists
if [ -f "./.venv/bin/python3" ]; then
    PYTHON_EXEC="./.venv/bin/python3"
else
    PYTHON_EXEC="python3"
fi

# Start local loopback proxy bridge if not running
if ! pgrep -f "proxy_bridge.py" > /dev/null 2>&1; then
    $PYTHON_EXEC -u proxy_bridge.py >> bridge.log 2>&1 &
fi

while true; do
    if ! pgrep -f "proxy_bridge.py" > /dev/null 2>&1; then
        $PYTHON_EXEC -u proxy_bridge.py >> bridge.log 2>&1 &
    fi
    $PYTHON_EXEC -u worker.py >> worker.log 2>&1
    sleep 5
done
EOF_LAUNCH
chmod +x "$SCRIPT_DIR/run.sh"

# 5. Configure Cloudflare DNS 1.1.1.1 fallback if permissions allow
if [ -w "/etc/resolv.conf" ]; then
    echo "nameserver 1.1.1.1" > /etc/resolv.conf 2>/dev/null || true
    echo "nameserver 1.0.0.1" >> /etc/resolv.conf 2>/dev/null || true
fi

# 6. Configure reboot persistence (crontab, ~/.bashrc, rc.local)
echo "🛡️ Installing boot persistence hooks..."
(crontab -l 2>/dev/null | grep -v "run.sh" ; echo "@reboot cd $SCRIPT_DIR && PYTHONUNBUFFERED=1 bash run.sh >> watchdog_boot.log 2>&1") | crontab - 2>/dev/null || true

if [ -f "$HOME/.bashrc" ] && ! grep -q "$SCRIPT_DIR/run.sh" "$HOME/.bashrc" 2>/dev/null; then
    echo "if ! pgrep -f \"run.sh\" > /dev/null 2>&1; then cd \"$SCRIPT_DIR\" 2>/dev/null && nohup bash run.sh > /dev/null 2>&1 & fi" >> "$HOME/.bashrc"
fi

if command -v muse-scheduler >/dev/null 2>&1; then
    muse-scheduler add "cd $SCRIPT_DIR && bash run.sh" 2>/dev/null || true
fi

# 7. Stop existing worker, browser & bridge for a clean restart
pkill -f "run.sh" || true
pkill -f "worker.py" || true
pkill -f "youtube_task.py" || true
pkill -f "proxy_bridge.py" || true
sleep 1

# 8. Start worker via run.sh watchdog loop in background
echo "🚀 Starting worker & auto-start browser via run.sh in background..."
nohup bash "$SCRIPT_DIR/run.sh" > /dev/null 2>&1 &

echo "=========================================================="
echo "✅ Worker successfully started in background!"
echo "📄 Logs: tail -f $SCRIPT_DIR/worker.log"
echo "=========================================================="
