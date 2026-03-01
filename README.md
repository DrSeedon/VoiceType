# VoiceType

Speech-to-text input tool for Linux (KDE Wayland). Press a hotkey, speak, and the recognized text gets typed directly into any focused application.

## The Problem

Typing text by voice on Linux Wayland is painful:
- `wtype` doesn't work on KDE Wayland ("Compositor does not support the virtual keyboard protocol")
- `xdotool` only works with X11/XWayland windows
- `ydotool key` sends scancodes that map incorrectly on non-English keyboard layouts
- No simple tool exists that handles mixed-language input (e.g. Russian + English in one sentence)

## The Solution

VoiceType records audio via hotkey, sends it to Google Speech Recognition (free, no API key needed), and types the result into the focused window using `ydotool type` with automatic keyboard layout switching via KDE DBus.

**Key features:**
- Works on **KDE Plasma Wayland** (tested on Plasma 6.4+)
- **Mixed language support** — automatically switches keyboard layout per word chunk (e.g. "Привет hello мир" types correctly)
- **Free** — uses Google Web Speech API, no API keys required
- System tray icon with color-coded status
- Hotkey-driven: F7 to start/stop, F8 to stop + Enter

## Requirements

- Linux with KDE Plasma (Wayland session)
- Python 3.7+
- Microphone
- Internet connection (for Google Speech API)

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

| Icon | Status |
|------|--------|
| 🟢 | Ready |
| 🔴 | Recording |
| 🟡 | Processing (sending to Google) |
| 🔵 | Text inserted (returns to 🟢 after 1.5s) |

## Autostart

Copy the desktop file to autostart:

```bash
cp voicetype.desktop ~/.config/autostart/
```

Or create it manually:

```ini
[Desktop Entry]
Type=Application
Name=VoiceType
Exec=/path/to/VoiceType/run.sh
Terminal=false
```

## How it works

1. Listens for F7/F8 via `evdev` (reads `/dev/input` devices directly)
2. Records audio using PyAudio (44100 Hz, mono)
3. Sends WAV to Google Web Speech API (`speech_recognition` library)
4. Splits recognized text into language chunks (Cyrillic vs Latin)
5. For each chunk: switches KDE keyboard layout via DBus, types via `ydotool type`
6. Restores original keyboard layout

## Logs

```bash
tail -f /path/to/VoiceType/voicetype.log
```

## Stop

```bash
pkill -f voice_type.py
```

## License

MIT
