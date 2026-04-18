#!/bin/bash
# Pi Assistant Setup Script for Raspberry Pi 5
# Run: chmod +x scripts/setup_pi.sh && ./scripts/setup_pi.sh

set -e

echo "=========================================="
echo "  Pi Assistant Setup for Raspberry Pi 5"
echo "=========================================="

# Colors
GREEN='\033[0;32m'
NC='\033[0m'

step() { echo -e "\n${GREEN}[*] $1${NC}"; }

# System packages
step "Installing system dependencies..."
sudo apt update
sudo apt install -y \
    python3-pip \
    python3-venv \
    python3-dev \
    portaudio19-dev \
    libsndfile1 \
    ffmpeg \
    mpv \
    chromium-browser \
    unclutter \
    espeak-ng

# Python venv
step "Creating Python virtual environment..."
cd ~/pi-assistant
python3 -m venv .venv
source .venv/bin/activate

# Python packages
step "Installing Python packages..."
pip install --upgrade pip
pip install -r requirements.txt
pip install youtube-search-python yt-dlp

# Download models (wake word + TTS)
step "Downloading AI models (this takes a few minutes)..."
python -c "
from openwakeword import Model
Model()  # Downloads default models
print('Wake word models ready')
"

mkdir -p ~/.cache/piper-voices
cd ~/.cache/piper-voices
if [ ! -f en_US-lessac-medium.onnx ]; then
    wget -q https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
    wget -q https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
fi
echo "Piper TTS models ready"

# Whisper model
step "Downloading Whisper model..."
cd ~/pi-assistant
source .venv/bin/activate
python -c "from faster_whisper import WhisperModel; WhisperModel('base')"

# Setup .env if not exists
step "Setting up configuration..."
cd ~/pi-assistant
if [ ! -f .env ]; then
    cp .env.example .env
    echo ""
    echo "IMPORTANT: Edit .env and add your GOOGLE_API_KEY"
    echo "  nano ~/pi-assistant/.env"
fi

# Install systemd service
step "Installing systemd service..."
sudo cp scripts/pi-assistant.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable pi-assistant

# Setup autostart for kiosk
step "Setting up kiosk autostart..."
mkdir -p ~/.config/autostart
cp scripts/kiosk.desktop ~/.config/autostart/

echo ""
echo "=========================================="
echo "  Setup Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "1. Edit your API key:  nano ~/pi-assistant/.env"
echo "2. Test manually:      cd ~/pi-assistant && source .venv/bin/activate && python run.py"
echo "3. Start service:      sudo systemctl start pi-assistant"
echo "4. Reboot for kiosk:   sudo reboot"
echo ""
