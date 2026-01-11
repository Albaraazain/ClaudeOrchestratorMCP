#!/bin/bash
#
# Build script for Claude Orchestrator Dashboard Desktop App
#
# Prerequisites:
#   - Rust toolchain (rustup)
#   - Node.js 18+
#   - Python 3.10+
#   - PyInstaller: pip install pyinstaller
#
# Usage:
#   ./build-desktop.sh          # Build for current platform
#   ./build-desktop.sh --dev    # Development mode (skip PyInstaller)
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
TAURI_DIR="$SCRIPT_DIR/src-tauri"
SIDECARS_DIR="$TAURI_DIR/sidecars"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Detect platform and architecture
detect_platform() {
    local os=$(uname -s)
    local arch=$(uname -m)

    case "$os" in
        Darwin)
            case "$arch" in
                arm64) echo "aarch64-apple-darwin" ;;
                x86_64) echo "x86_64-apple-darwin" ;;
                *) log_error "Unsupported macOS architecture: $arch"; exit 1 ;;
            esac
            ;;
        Linux)
            case "$arch" in
                x86_64) echo "x86_64-unknown-linux-gnu" ;;
                aarch64) echo "aarch64-unknown-linux-gnu" ;;
                *) log_error "Unsupported Linux architecture: $arch"; exit 1 ;;
            esac
            ;;
        MINGW*|MSYS*|CYGWIN*)
            echo "x86_64-pc-windows-msvc"
            ;;
        *)
            log_error "Unsupported OS: $os"
            exit 1
            ;;
    esac
}

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check Rust
    if ! command -v cargo &> /dev/null; then
        log_error "Rust not found. Install from https://rustup.rs"
        exit 1
    fi
    log_info "Rust: $(cargo --version)"

    # Check Node.js
    if ! command -v node &> /dev/null; then
        log_error "Node.js not found. Install from https://nodejs.org"
        exit 1
    fi
    log_info "Node.js: $(node --version)"

    # Check npm
    if ! command -v npm &> /dev/null; then
        log_error "npm not found"
        exit 1
    fi

    # Check Python
    if ! command -v python3 &> /dev/null; then
        log_error "Python 3 not found"
        exit 1
    fi
    log_info "Python: $(python3 --version)"

    # Check PyInstaller
    if ! python3 -c "import PyInstaller" &> /dev/null; then
        log_warn "PyInstaller not found. Installing..."
        pip3 install pyinstaller
    fi

    # Check Tauri CLI
    if ! command -v cargo-tauri &> /dev/null; then
        log_warn "Tauri CLI not found. Installing..."
        cargo install tauri-cli
    fi
}

# Build Python backend as executable
build_backend() {
    log_info "Building Python backend with PyInstaller..."

    cd "$BACKEND_DIR"

    # Install backend dependencies
    if [ -f "requirements.txt" ]; then
        pip3 install -r requirements.txt
    fi

    # Run PyInstaller
    pyinstaller --clean --noconfirm dashboard-api.spec

    # Get target triple
    local target=$(detect_platform)
    local ext=""

    # Add .exe extension for Windows
    if [[ "$target" == *"windows"* ]]; then
        ext=".exe"
    fi

    # Copy to sidecars directory with correct naming
    mkdir -p "$SIDECARS_DIR"
    local sidecar_name="dashboard-api-${target}${ext}"

    log_info "Copying sidecar as: $sidecar_name"
    cp "dist/dashboard-api${ext}" "$SIDECARS_DIR/$sidecar_name"
    chmod +x "$SIDECARS_DIR/$sidecar_name"

    log_info "Backend built successfully: $SIDECARS_DIR/$sidecar_name"
}

# Build frontend
build_frontend() {
    log_info "Building frontend..."

    cd "$FRONTEND_DIR"

    # Install dependencies
    npm install

    # Build for production
    npm run build

    log_info "Frontend built successfully"
}

# Build Tauri app
build_tauri() {
    log_info "Building Tauri desktop app..."

    cd "$SCRIPT_DIR"

    # Build in release mode
    cargo tauri build

    log_info "Tauri app built successfully"

    # Show output location
    local target=$(detect_platform)
    case "$target" in
        *darwin*)
            log_info "Output: $TAURI_DIR/target/release/bundle/macos/"
            ;;
        *linux*)
            log_info "Output: $TAURI_DIR/target/release/bundle/appimage/"
            ;;
        *windows*)
            log_info "Output: $TAURI_DIR/target/release/bundle/msi/"
            ;;
    esac
}

# Development mode - just run without building sidecar
dev_mode() {
    log_info "Starting development mode..."

    cd "$SCRIPT_DIR"

    # Start backend in background
    log_info "Starting backend..."
    cd "$BACKEND_DIR"
    python3 -m uvicorn main:app --host 0.0.0.0 --port 8765 --reload &
    BACKEND_PID=$!

    # Wait for backend
    sleep 2

    # Start Tauri dev
    log_info "Starting Tauri dev mode..."
    cd "$SCRIPT_DIR"
    cargo tauri dev

    # Cleanup
    kill $BACKEND_PID 2>/dev/null || true
}

# Main
main() {
    log_info "Claude Orchestrator Dashboard - Desktop Build"
    log_info "============================================="

    # Parse arguments
    if [ "$1" == "--dev" ]; then
        check_prerequisites
        dev_mode
        exit 0
    fi

    check_prerequisites

    # Full build
    build_backend
    build_frontend
    build_tauri

    log_info "============================================="
    log_info "Build complete!"
}

main "$@"
