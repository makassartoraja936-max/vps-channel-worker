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

# 1. Configure custom VPS Name & ID if provided (e.g. bash setup.sh Muse-03)
if [ -n "$1" ]; then
    mkdir -p "$WORKSPACE"
    echo "$1" > "$WORKSPACE/.vps_name"
    CLEAN_ID=$(echo "$1" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9_-' '-')
    echo "worker-$CLEAN_ID" > "$WORKSPACE/.worker_id"
    echo "Identitas VPS disetel: $1 (ID: worker-$CLEAN_ID)"
fi

# 2. Setup isolated Python Virtual Environment (venv)
echo "Setting up isolated Python virtual environment (venv)..."
VENV_DIR="$SCRIPT_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi

# 3. Install Python dependencies strictly inside venv
echo "Installing dependencies inside virtual environment..."
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet --upgrade -r "$SCRIPT_DIR/requirements.txt"

# 4. Install Playwright Chromium browser binary
echo "Installing Playwright Chromium browser binary..."
"$VENV_DIR/bin/python3" -m playwright install chromium || true

# 5. Create launcher script (run.sh)
cat << 'EOF_LAUNCHER' > "$SCRIPT_DIR/run.sh"
#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
exec "$SCRIPT_DIR/venv/bin/python3" worker.py "$@"
EOF_LAUNCHER
chmod +x "$SCRIPT_DIR/run.sh"

echo "=========================================================="
echo "Installation complete."
echo "Virtual environment ready at: $VENV_DIR"
echo "To run worker: bash run.sh (or nohup bash run.sh > ~/workspace/worker.log 2>&1 &)"
echo "=========================================================="
