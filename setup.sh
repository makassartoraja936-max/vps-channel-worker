#!/bin/bash
# ==============================================================================
# VPS Channel Worker - Setup and Installation Script
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$HOME/workspace"

echo "=========================================================="
echo "Installing VPS Channel Worker Environment..."
echo "Directory: $SCRIPT_DIR"
echo "=========================================================="

# 1. Install Python dependencies
echo "Installing Python packages..."
pip3 install --quiet --upgrade --break-system-packages -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null || \
pip install --quiet --upgrade --break-system-packages -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null || \
pip3 install --quiet --upgrade -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null || true

# 2. Install Playwright Chromium browser binary
echo "Installing Playwright Chromium browser..."
python3 -m playwright install chromium || true

# 3. Create runner script
echo "Creating application runner..."
cat << 'EOF_LAUNCH' > "$SCRIPT_DIR/run.sh"
#!/bin/bash
cd "$(dirname "$0")"
export PYTHONUNBUFFERED=1

if ! pgrep -f "proxy_bridge.py" > /dev/null 2>&1; then
    python3 -u proxy_bridge.py >> bridge.log 2>&1 &
fi

while true; do
    if ! pgrep -f "proxy_bridge.py" > /dev/null 2>&1; then
        python3 -u proxy_bridge.py >> bridge.log 2>&1 &
    fi
    python3 -u worker.py >> worker.log 2>&1
    sleep 5
done
EOF_LAUNCH
chmod +x "$SCRIPT_DIR/run.sh"

echo "=========================================================="
echo "Installation complete."
echo "=========================================================="
