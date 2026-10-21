#!/bin/bash
# ==============================================================================
# VPS Channel Worker - Setup and Installation Script
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$HOME/workspace"

echo "=========================================================="
echo "🚀 Installing VPS Channel Worker..."
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

# 3. Create run script for daemon persistence
echo "⚙️ Creating startup launcher..."
cat << 'EOF_LAUNCH' > "$SCRIPT_DIR/run.sh"
#!/bin/bash
cd "$(dirname "$0")"
while true; do
    python3 worker.py >> worker.log 2>&1
    sleep 10
done
EOF_LAUNCH
chmod +x "$SCRIPT_DIR/run.sh"

# 4. Stop existing worker & launcher if running
pkill -f "run.sh" || true
pkill -f "worker.py" || true
sleep 1

# 5. Start worker via run.sh watchdog loop in background
echo "🚀 Starting worker via run.sh watchdog in background..."
nohup bash "$SCRIPT_DIR/run.sh" > /dev/null 2>&1 &

echo "=========================================================="
echo "✅ Worker successfully started in background!"
echo "📄 Logs: tail -f $SCRIPT_DIR/worker.log"
echo "=========================================================="
