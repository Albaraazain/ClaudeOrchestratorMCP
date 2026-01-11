# Claude Orchestrator Dashboard - Desktop App

Convert the web dashboard into a native desktop application using Tauri v2.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Tauri Desktop App                        │
├─────────────────────────────────────────────────────────────┤
│  ┌────────────────────┐    ┌────────────────────────────┐  │
│  │   Native Webview   │    │    Python Sidecar          │  │
│  │   (React Frontend) │◄──►│    (FastAPI Backend)       │  │
│  │   Port: embedded   │    │    Port: 8765              │  │
│  └────────────────────┘    └────────────────────────────┘  │
│           │                           │                     │
│           └───────────WebSocket───────┘                     │
└─────────────────────────────────────────────────────────────┘
```

## Prerequisites

```bash
# Rust toolchain
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

# Tauri CLI
cargo install tauri-cli

# PyInstaller (for bundling Python backend)
pip3 install pyinstaller

# Node.js dependencies
cd dashboard/frontend && npm install
```

## Quick Start

### Development Mode

Run frontend and backend separately (hot reload):

```bash
# Terminal 1: Backend
cd dashboard/backend
python3 -m uvicorn main:app --port 8765 --reload

# Terminal 2: Frontend (Tauri dev)
cd dashboard
cargo tauri dev
```

Or use the build script:

```bash
cd dashboard
./build-desktop.sh --dev
```

### Production Build

Build the full desktop app:

```bash
cd dashboard
./build-desktop.sh
```

This will:
1. Compile Python backend with PyInstaller
2. Build React frontend with Vite
3. Bundle everything into a native app

Output locations:
- **macOS**: `src-tauri/target/release/bundle/macos/Claude Orchestrator.app`
- **Windows**: `src-tauri/target/release/bundle/msi/Claude Orchestrator_*.msi`
- **Linux**: `src-tauri/target/release/bundle/appimage/claude-orchestrator_*.AppImage`

## Project Structure

```
dashboard/
├── frontend/               # React + Vite frontend
│   ├── src/
│   │   ├── lib/
│   │   │   └── tauri.ts   # Tauri integration utilities
│   │   └── services/
│   │       └── api.ts     # API service (auto-detects Tauri)
│   └── package.json
├── backend/                # FastAPI backend
│   ├── main.py            # Server entry (accepts --port)
│   └── dashboard-api.spec # PyInstaller spec
├── src-tauri/             # Tauri Rust core
│   ├── Cargo.toml
│   ├── tauri.conf.json    # Tauri configuration
│   ├── src/
│   │   ├── main.rs
│   │   └── lib.rs         # Sidecar management
│   ├── icons/             # App icons
│   └── sidecars/          # Compiled Python backend
├── package.json           # Root scripts
└── build-desktop.sh       # Build script
```

## How It Works

### Sidecar Management

1. **App Launch**: Tauri starts → spawns Python sidecar on port 8765
2. **Health Check**: Rust code polls `/health` until backend ready
3. **Event Emission**: Once ready, emits `backend-ready` event to frontend
4. **Frontend Connect**: React app connects to `http://localhost:8765`
5. **Shutdown**: Tauri kills sidecar process on app close

### Frontend Auto-Detection

The `lib/tauri.ts` module detects if running in Tauri:

```typescript
// In browser (web mode)
isTauri() → false
getBackendUrl() → "http://localhost:8000" (env or default)

// In Tauri (desktop mode)
isTauri() → true
getBackendUrl() → invokes Rust command → "http://localhost:8765"
```

The API service auto-initializes on first request, waiting for the sidecar.

## Available Scripts

```bash
# Root dashboard directory
npm run dev              # Start frontend dev server
npm run build            # Build frontend
npm run tauri:dev        # Run Tauri in dev mode
npm run tauri:build      # Build Tauri app
npm run desktop:dev      # Dev mode with local backend
npm run desktop:build    # Full production build
npm run backend          # Run backend on port 8000 (web dev)
npm run backend:desktop  # Run backend on port 8765 (desktop)
```

## Icons

Replace placeholder icons in `src-tauri/icons/`:

```bash
# Generate all icons from a 1024x1024 PNG
cargo tauri icon /path/to/icon.png
```

Required files:
- `32x32.png`
- `128x128.png`
- `128x128@2x.png` (256x256)
- `icon.icns` (macOS)
- `icon.ico` (Windows)

## Troubleshooting

### Backend won't start

Check if port 8765 is in use:
```bash
lsof -i :8765
kill -9 <PID>
```

### PyInstaller issues

Rebuild with verbose output:
```bash
cd backend
pyinstaller --clean --noconfirm --debug all dashboard-api.spec
```

### Tauri build fails

Check Rust toolchain:
```bash
rustup update
cargo clean
cargo tauri build
```

### Frontend can't connect

Check sidecar logs in Tauri console output (`[API]` prefixed lines).

## Distribution

### macOS

The `.app` bundle is in `src-tauri/target/release/bundle/macos/`.

For distribution, you'll need to:
1. Sign with Apple Developer certificate
2. Notarize the app

### Windows

The `.msi` installer is in `src-tauri/target/release/bundle/msi/`.

For distribution:
1. Sign with code signing certificate (optional but recommended)

### Linux

The `.AppImage` is in `src-tauri/target/release/bundle/appimage/`.

No signing required for distribution.

## Performance

| Metric | Value |
|--------|-------|
| App size (macOS) | ~15-25 MB |
| App size (Windows) | ~20-30 MB |
| Memory usage | ~80-150 MB |
| Startup time | <2 seconds |
