#!/bin/bash
# ==============================================================================
# VPS Channel Worker - Setup and Installation Script
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=========================================================="
echo "Installing VPS Channel Worker Environment..."
echo "Directory: $SCRIPT_DIR"
echo "=========================================================="

# 1. Install Python dependencies
echo "Installing Python packages..."
pip3 install --quiet --upgrade --break-system-packages -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null || \
pip install --quiet --upgrade -r "$SCRIPT_DIR/requirements.txt" 2>/dev/null || true

# 2. Install Playwright Chromium browser binary
echo "Installing Playwright Chromium browser..."
python3 -m playwright install chromium || true

echo "=========================================================="
echo "Installation complete."
echo "=========================================================="
