#!/bin/bash
# install.sh — One-shot installer for AI Employee Vault
# Run once with: bash install.sh

set -e
VAULT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON=/usr/bin/python3

echo ""
echo "=================================================="
echo "  AI Employee Vault — Full Install"
echo "=================================================="

# 1. System libraries for Playwright Chromium
echo ""
echo "[1/3] Installing system libraries for Chromium..."
sudo apt-get update -qq
sudo apt-get install -y \
  libnspr4 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
  libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
  libxdamage1 libxfixes3 libxrandr2 libgbm1 \
  libasound2 libpango-1.0-0 libcairo2 \
  libx11-xcb1 libxcb-dri3-0 libxshmfence1 libgles2
echo "  ✓ System libraries installed."

# 2. Python packages
echo ""
echo "[2/3] Installing Python packages..."
$PYTHON -m pip install --user -q \
  watchdog \
  python-dotenv \
  google-api-python-client \
  google-auth-httplib2 \
  google-auth-oauthlib \
  playwright \
  mcp
echo "  ✓ Python packages installed."

# 3. Playwright Chromium browser
echo ""
echo "[3/3] Installing Playwright Chromium browser..."
$PYTHON -m playwright install chromium
echo "  ✓ Playwright Chromium installed."

echo ""
echo "=================================================="
echo "  Install complete!"
echo ""
echo "  Next steps:"
echo "  1. Run auth setup:  python3 auth_setup.py"
echo "  2. Start watchers:  bash run_watchers.sh"
echo "=================================================="
