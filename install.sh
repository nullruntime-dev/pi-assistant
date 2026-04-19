#!/bin/bash
#
# Pi Assistant - One-Click Installer
# Works on Raspberry Pi OS / Debian / Ubuntu
#
# Usage: curl -sSL https://raw.githubusercontent.com/yourrepo/pi-assistant/main/install.sh | bash
#    or: ./install.sh
#

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Config
INSTALL_DIR="$HOME/pi-assistant"
REPO_URL="https://github.com/yourrepo/pi-assistant.git"  # Update this
MIN_PYTHON="3.10"

#------------------------------------------
# Helper functions
#------------------------------------------
print_banner() {
    echo -e "${BLUE}"
    echo "╔═══════════════════════════════════════════╗"
    echo "║         Pi Assistant Installer            ║"
    echo "║     Your AI Voice Assistant for Pi 5      ║"
    echo "╚═══════════════════════════════════════════╝"
    echo -e "${NC}"
}

log_info() { echo -e "${GREEN}[✓]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[!]${NC} $1"; }
log_error() { echo -e "${RED}[✗]${NC} $1"; }
log_step() { echo -e "\n${BLUE}==>${NC} $1"; }

command_exists() { command -v "$1" &> /dev/null; }

version_gte() {
    printf '%s\n%s\n' "$2" "$1" | sort -V -C
}

#------------------------------------------
# Check system
#------------------------------------------
check_system() {
    log_step "Checking system requirements..."

    # Check if running on Linux
    if [[ "$(uname)" != "Linux" ]]; then
        log_error "This installer only works on Linux (Raspberry Pi OS / Debian / Ubuntu)"
        exit 1
    fi

    # Check architecture
    ARCH=$(uname -m)
    log_info "Architecture: $ARCH"

    # Check if Raspberry Pi
    if [[ -f /proc/device-tree/model ]]; then
        PI_MODEL=$(cat /proc/device-tree/model)
        log_info "Device: $PI_MODEL"
    fi

    # Check package manager
    if command_exists apt; then
        PKG_MANAGER="apt"
        log_info "Package manager: apt"
    else
        log_error "apt package manager not found. This script requires Debian/Ubuntu."
        exit 1
    fi
}

#------------------------------------------
# Install system dependencies
#------------------------------------------
install_system_deps() {
    log_step "Installing system dependencies..."

    sudo apt update

    # Core dependencies
    PACKAGES=(
        # Python
        python3
        python3-pip
        python3-venv
        python3-dev
        # Audio
        portaudio19-dev
        libsndfile1
        ffmpeg
        espeak-ng
        # Media player
        mpv
        # Display
        chromium-browser
        unclutter
        # Build tools
        build-essential
        git
        curl
        wget
    )

    log_info "Installing packages: ${PACKAGES[*]}"
    sudo apt install -y "${PACKAGES[@]}"

    log_info "System dependencies installed"
}

#------------------------------------------
# Check/Install Python
#------------------------------------------
setup_python() {
    log_step "Checking Python installation..."

    if command_exists python3; then
        PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        log_info "Python $PY_VERSION found"

        if version_gte "$PY_VERSION" "$MIN_PYTHON"; then
            log_info "Python version OK (>= $MIN_PYTHON)"
        else
            log_warn "Python $PY_VERSION is older than $MIN_PYTHON"
            log_info "Installing newer Python..."
            sudo apt install -y python3.11 python3.11-venv python3.11-dev || true
        fi
    else
        log_warn "Python not found, installing..."
        sudo apt install -y python3 python3-pip python3-venv python3-dev
    fi
}

#------------------------------------------
# Clone/Update repository
#------------------------------------------
setup_project() {
    log_step "Setting up Pi Assistant..."

    if [[ -d "$INSTALL_DIR" ]]; then
        log_info "Existing installation found at $INSTALL_DIR"
        read -p "Update existing installation? [Y/n] " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]] || [[ -z $REPLY ]]; then
            cd "$INSTALL_DIR"
            if [[ -d .git ]]; then
                git pull || log_warn "Git pull failed, continuing with existing files"
            fi
        fi
    else
        log_info "Creating installation directory..."
        mkdir -p "$INSTALL_DIR"

        # If running from repo, copy files
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        if [[ -f "$SCRIPT_DIR/run.py" ]]; then
            log_info "Copying project files..."
            cp -r "$SCRIPT_DIR"/* "$INSTALL_DIR/"
        else
            # Clone from git
            log_info "Cloning repository..."
            git clone "$REPO_URL" "$INSTALL_DIR" || {
                log_error "Failed to clone repository. Creating from template..."
                mkdir -p "$INSTALL_DIR"
            }
        fi
    fi

    cd "$INSTALL_DIR"
    log_info "Project directory: $INSTALL_DIR"
}

#------------------------------------------
# Setup Python virtual environment
#------------------------------------------
setup_venv() {
    log_step "Setting up Python virtual environment..."

    cd "$INSTALL_DIR"

    if [[ ! -d ".venv" ]]; then
        python3 -m venv .venv
        log_info "Virtual environment created"
    else
        log_info "Virtual environment exists"
    fi

    source .venv/bin/activate
    pip install --upgrade pip wheel setuptools

    log_info "Installing Python packages (this may take a few minutes)..."
    pip install -r requirements.txt

    log_info "Python packages installed"
}

#------------------------------------------
# Download AI models
#------------------------------------------
download_models() {
    log_step "Downloading AI models..."

    cd "$INSTALL_DIR"
    source .venv/bin/activate

    # Wake word model
    log_info "Downloading wake word model..."
    python3 -c "
from openwakeword import Model
m = Model()
print('Wake word model ready')
" || log_warn "Wake word model download failed (will retry on first run)"

    # Piper TTS voice
    log_info "Downloading TTS voice model..."
    mkdir -p ~/.cache/piper-voices
    cd ~/.cache/piper-voices

    if [[ ! -f "en_US-lessac-medium.onnx" ]]; then
        wget -q --show-progress https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
        wget -q https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
        log_info "TTS voice downloaded"
    else
        log_info "TTS voice already exists"
    fi

    # Whisper STT model
    log_info "Downloading speech recognition model..."
    cd "$INSTALL_DIR"
    python3 -c "
from faster_whisper import WhisperModel
model = WhisperModel('base', device='cpu', compute_type='int8')
print('Whisper model ready')
" || log_warn "Whisper model download failed (will retry on first run)"

    log_info "AI models ready"
}

#------------------------------------------
# Setup configuration
#------------------------------------------
setup_config() {
    log_step "Setting up configuration..."

    cd "$INSTALL_DIR"

    if [[ ! -f ".env" ]]; then
        cp .env.example .env
        log_warn "Created .env file - YOU MUST EDIT THIS!"
        echo ""
        echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo -e "${YELLOW}  IMPORTANT: Add your Google API key to .env file   ${NC}"
        echo -e "${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
        echo ""
        echo "  Get your free API key from:"
        echo "  https://aistudio.google.com/apikey"
        echo ""
        echo "  Then edit: nano $INSTALL_DIR/.env"
        echo ""
    else
        log_info "Configuration file exists"
    fi
}

#------------------------------------------
# Install systemd service
#------------------------------------------
install_service() {
    log_step "Installing systemd user service..."

    cd "$INSTALL_DIR"

    # Substitute any remaining $HOME placeholders in kiosk scripts
    sed -i "s|/home/pi|$HOME|g" scripts/kiosk.sh
    sed -i "s|/home/pi|$HOME|g" scripts/kiosk.desktop

    # Install as a user service so it inherits the user's audio session (PulseAudio/PipeWire)
    mkdir -p "$HOME/.config/systemd/user"
    cp scripts/pi-assistant.service "$HOME/.config/systemd/user/"
    systemctl --user daemon-reload
    systemctl --user enable pi-assistant

    # Remove any previous system-level install
    if [[ -f /etc/systemd/system/pi-assistant.service ]]; then
        log_info "Removing legacy system-level service..."
        sudo systemctl disable pi-assistant 2>/dev/null || true
        sudo systemctl stop pi-assistant 2>/dev/null || true
        sudo rm -f /etc/systemd/system/pi-assistant.service
        sudo systemctl daemon-reload
    fi

    # Enable lingering so the user service starts at boot without login
    sudo loginctl enable-linger "$USER"

    log_info "Systemd user service installed and enabled"
}

#------------------------------------------
# Setup kiosk autostart
#------------------------------------------
setup_kiosk() {
    log_step "Setting up kiosk autostart..."

    cd "$INSTALL_DIR"

    # Make scripts executable
    chmod +x scripts/*.sh

    # Setup autostart
    mkdir -p ~/.config/autostart
    cp scripts/kiosk.desktop ~/.config/autostart/

    log_info "Kiosk autostart configured"
}

#------------------------------------------
# Configure audio
#------------------------------------------
setup_audio() {
    log_step "Configuring audio..."

    # Add user to audio group
    sudo usermod -a -G audio "$USER" || true

    # Test audio
    if command_exists speaker-test; then
        log_info "Testing audio output..."
        timeout 2 speaker-test -t sine -f 440 -l 1 &>/dev/null || true
    fi

    log_info "Audio configured"
}

#------------------------------------------
# Print completion message
#------------------------------------------
print_complete() {
    echo ""
    echo -e "${GREEN}╔═══════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║      Installation Complete!               ║${NC}"
    echo -e "${GREEN}╚═══════════════════════════════════════════╝${NC}"
    echo ""
    echo "📁 Installed to: $INSTALL_DIR"
    echo ""
    echo "📝 Next steps:"
    echo "   1. Add your Google API key:"
    echo "      nano $INSTALL_DIR/.env"
    echo ""
    echo "   2. Test manually:"
    echo "      cd $INSTALL_DIR"
    echo "      source .venv/bin/activate"
    echo "      python run.py"
    echo ""
    echo "   3. Open browser: http://localhost:9091"
    echo ""
    echo "   4. Say 'Hey Jarvis' to activate!"
    echo ""
    echo "🔄 For auto-start on boot, reboot your Pi:"
    echo "      sudo reboot"
    echo ""
    echo "📖 Commands:"
    echo "   Start:   systemctl --user start pi-assistant"
    echo "   Stop:    systemctl --user stop pi-assistant"
    echo "   Logs:    journalctl --user -u pi-assistant -f"
    echo ""
}

#------------------------------------------
# Main
#------------------------------------------
main() {
    print_banner

    # Check if running as root
    if [[ $EUID -eq 0 ]]; then
        log_error "Don't run this script as root. Run as normal user."
        exit 1
    fi

    check_system
    install_system_deps
    setup_python
    setup_project
    setup_venv
    download_models
    setup_config
    install_service
    setup_kiosk
    setup_audio
    print_complete
}

# Run main
main "$@"
