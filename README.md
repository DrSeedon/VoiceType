# VoiceType

Speech-to-text input tool for Linux (KDE Wayland). Press a hotkey, speak, and the recognized text gets typed directly into any focused application.

## The Problem

Typing text by voice on Linux Wayland is painful:
- `wtype` doesn't work on KDE Wayland ("Compositor does not support the virtual keyboard protocol")
- `xdotool` only works with X11/XWayland windows
- `ydotool key` sends scancodes that map incorrectly on non-English keyboard layouts
- No simple tool exists that handles mixed-language input (e.g. Russian + English in one sentence)

## The Solution

VoiceType records audio via hotkey, sends it to **Deepgram Nova-2** (fast, accurate STT), and types the result into the focused window using `ydotool type` with automatic keyboard layout switching via KDE DBus.

**Key features:**
- Works on **KDE Plasma Wayland** (tested on Plasma 6.4+)
- **Deepgram Nova-2** — ~100x realtime speed, high accuracy for Russian
- **Mixed language support** — automatically switches keyboard layout per word chunk (e.g. "Привет hello мир" types correctly)
- System tray icon with color-coded status
- Hotkey-driven: F7 to start/stop, F8 to stop + Enter

## Requirements

- Linux with KDE Plasma (Wayland session)
- Python 3.7+
- Microphone
- Internet connection (for Deepgram API)
- Deepgram API key (free tier: 45,000 minutes)

### System packages

```bash
sudo apt install ydotool wl-clipboard
```

### Input device access

```bash
sudo usermod -aG input $USER
# Log out and back in after this!
```

## Installation

```bash
git clone https://github.com/DrSeedon/VoiceType.git
cd VoiceType
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Create a `.env` file with your Deepgram API key:

```bash
cp .env.example .env
# Edit .env and add your key
```

Get a free API key at https://console.deepgram.com (45,000 minutes free).

## Usage

```bash
./run.sh
```

The app starts in the system tray.

| Hotkey | Action |
|--------|--------|
| **F7** | Start/stop recording → paste text |
| **F8** | Stop recording → paste text + Enter |

### Tray icon colors

- 🟢 Ready
- 🔴 Recording
- 🟡 Processing (sending to Deepgram)
- 🔵 Text inserted (returns to 🟢 after 1.5s)

## How it works

1. Listens for F7/F8 via `evdev` (reads `/dev/input` devices directly)
2. Records audio using PyAudio (44100 Hz, mono)
3. Sends WAV to Deepgram Nova-2 API (HTTP POST, ~100x realtime)
4. Splits recognized text into language chunks (Cyrillic vs Latin)
5. For each chunk: switches KDE keyboard layout via DBus, types via `ydotool type`
6. Restores original keyboard layout

## Autostart

```bash
cp voicetype.desktop ~/.config/autostart/
```

## License

MIT
