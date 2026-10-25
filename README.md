# VoiceType

Speech-to-text input tool for Linux (KDE Wayland). Press a hotkey, speak, and the recognized text gets typed directly into any focused application.

## The Problem

Typing text by voice on Linux Wayland is painful:
- `wtype` doesn't work on KDE Wayland ("Compositor does not support the virtual keyboard protocol")
- `xdotool` only works with X11/XWayland windows
- `ydotool key` sends scancodes that map incorrectly on non-English keyboard layouts
- No simple tool exists that handles mixed-language input (e.g. Russian + English in one sentence)

## The Solution

VoiceType records audio via hotkey, cleans it with `ffmpeg`, sends it to **Deepgram Nova-3** (fast, accurate STT), and pastes the result into the focused window via the clipboard (`wl-copy` + Ctrl+V), so it works under any keyboard layout.

**Key features:**
- Works on **KDE Plasma Wayland** (tested on Plasma 6.4+)
- **Deepgram Nova-3** — fast, high accuracy for Russian (`language=ru`)
- **Audio cleanup** — de-clip, high-pass and loudness normalization before upload
- **Self-tuning mic gain** — lowers the mic volume after clipped takes, raises it when too quiet; tray menu has a manual calibration
- **Speakers** — when several voices are detected the text is labelled `Спикер N:`; words Deepgram is unsure about get `(?)`
- System tray icon with color-coded status
- Click the tray icon to start, click again to stop + Enter; hotkeys: F7 to start/stop, F8 to stop + Enter

## Requirements

- Linux with KDE Plasma (Wayland session)
- Python 3.7+
- Microphone
- Internet connection (for Deepgram API)
- Deepgram API key (free tier: 45,000 minutes)

### System packages

```bash
sudo apt install ydotool wl-clipboard ffmpeg
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
| **Tray click** | Start / stop recording → paste text + Enter |
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
3. Cleans it with `ffmpeg` (`adeclip`, high-pass, `loudnorm`) and downsamples to 16 kHz FLAC
4. Sends it to Deepgram Nova-3 (diarization on) and builds the text, marking low-confidence words with `(?)`
5. Puts the text on the clipboard, presses Ctrl+V (and Enter); the text stays on the clipboard

### Microphone

Gain control targets the physical mic set in `HW_MIC` (`voice_type.py`; list yours with `pactl list short sources`). For Telegram-like noise suppression and AGC, a PipeWire WebRTC `echo-cancel` virtual source can be set as the default mic — the app records from whatever the default source is.

## Autostart

```bash
cp voicetype.desktop ~/.config/autostart/
```

## License

MIT
