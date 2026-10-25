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

# 1. Configure custom VPS Name & ID if provided (e.g. bash setup.sh Muse-02)
if [ -n "$1" ]; then
    mkdir -p "$WORKSPACE"
    echo "$1" > "$WORKSPACE/.vps_name"
    CLEAN_ID=$(echo "$1" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9_-' '-')
    echo "worker-$CLEAN_ID" > "$WORKSPACE/.worker_id"
    echo "Identitas VPS disetel: $1 (ID: worker-$CLEAN_ID)"
fi

# 2. Install Python dependencies
echo "Installing Python packages..."
pip3 install --quiet --upgrade --break-system-packages -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null || \
pip install --quiet --upgrade -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null || true

# 3. Install Playwright Chromium browser binary
echo "Installing Playwright Chromium browser..."
python3 -m playwright install chromium || true

echo "=========================================================="
echo "Installation complete."
echo "=========================================================="
