import os
import sys
import subprocess
import threading
import io
import array
import re
import time
import wave
import shutil
import json
import urllib.request
import urllib.error
import pyaudio
from dotenv import load_dotenv
from PyQt5.QtWidgets import QApplication, QSystemTrayIcon, QMenu, QAction, QWidget
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor, QBrush, QPen
from PyQt5.QtCore import pyqtSignal, QObject, QSize, QTimer
try:
    import evdev
    from evdev import ecodes
except ImportError:
    evdev = None
    ecodes = None

load_dotenv()
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")

COLORS = {
    "ready": "#4CAF50",
    "recording": "#F44336",
    "processing": "#FFC107",
    "done": "#2196F3",
}

RATE = 44100
CHANNELS = 1
CHUNK = 1024
FORMAT = pyaudio.paInt16

KEY_F7 = ecodes.KEY_F7
KEY_F8 = ecodes.KEY_F8


class Signals(QObject):
    set_state = pyqtSignal(str)
    insert_text = pyqtSignal(str, bool)
    notify = pyqtSignal(str, int)


def make_icon(hex_color, size=22):
    pix = QPixmap(QSize(size, size))
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QBrush(QColor(hex_color)))
    p.setPen(QPen(QColor("#FFFFFF"), 1))
    p.drawEllipse(1, 1, size - 2, size - 2)
    p.end()
    return QIcon(pix)


def find_keyboards():
    devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
    kbs = [d for d in devices if ecodes.EV_KEY in d.capabilities()]
    if not kbs:
        print("Не найдены устройства ввода! Добавь себя в группу input:")
        print("  sudo usermod -aG input $USER")
        print("  (перелогинься после)")
        sys.exit(1)
    for kb in kbs:
        print(f"  Клавиатура: {kb.name} ({kb.path})")
    return kbs


def is_wayland():
    return "WAYLAND_DISPLAY" in os.environ


YDOTOOL_SOCKET = "/tmp/.ydotool_socket"

def _ydotool_env():
    env = os.environ.copy()
    env["YDOTOOL_SOCKET"] = YDOTOOL_SOCKET
    return env


def paste_text(text, with_enter=False):
    # Clipboard + Ctrl+V instead of ydotool typing: instant, and independent of keyboard layout.
    # The text deliberately stays on the clipboard: restoring the old one raced slow apps (they pasted stale content),
    # and if Ctrl+V misses the window you can still paste by hand.
    # Ctrl+V goes by scancode (29 = Ctrl, 47 = V), so it works under the RU layout too.
    env = _ydotool_env()
    subprocess.run(["wl-copy"], input=text.encode(), check=False)
    time.sleep(0.1)
    subprocess.run(["ydotool", "key", "29:1", "47:1", "47:0", "29:0"], env=env, check=False, capture_output=True)
    if with_enter:
        time.sleep(0.15)
        subprocess.run(["ydotool", "key", "28:1", "28:0"], env=env, check=False, capture_output=True)


def adjust_mic_gain(pcm):
    """Self-tune the system mic volume after each take: back off on clipping, boost when too quiet."""
    loud = sorted(map(abs, pcm))
    clipped = sum(1 for v in loud if v >= 32000) / len(loud)
    p99 = loud[int(len(loud) * 0.99)]
    r = subprocess.run(["pactl", "get-source-volume", HW_MIC], capture_output=True, text=True)
    m = re.search(r"(\d+)%", r.stdout)
    if not m:
        return
    vol = int(m.group(1))
    if clipped > 0.001:
        # Heavy clipping needs a bigger step, otherwise convergence takes several dictations
        new = max(10, int(vol * (0.6 if clipped > 0.02 else 0.8)))
    elif p99 < 6000:
        new = min(100, int(vol * 1.2) + 1)
    else:
        return
    if new != vol:
        subprocess.run(["pactl", "set-source-volume", HW_MIC, f"{new}%"], capture_output=True)
        print(f">> Громкость микрофона {vol}% -> {new}% (клип {clipped:.2%}, p99 {p99})")


# loudnorm evens out quiet/loud speakers. A/B-tested on a clipped multi-speaker take: raw lost the opening
# phrase and punctuation, this got both back. adeclip added nothing on top but cost 16s of 24s on a 7-min take.
CLEAN_FILTER = "highpass=f=80,loudnorm=I=-18:TP=-2:LRA=11"
LOW_CONF = 0.5
FAILED_DIR = os.path.expanduser("~/Documents/voicetype-saved")
# Gain is tuned on the physical mic; the default source is now the WebRTC virtual one (~/.config/pipewire/pipewire.conf.d/50-voice-clean.conf)
HW_MIC = "alsa_input.pci-0000_00_1f.3.analog-stereo"


def clean_audio(wav_bytes):
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", "pipe:0", "-af", CLEAN_FILTER,
         "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "24k", "-application", "voip",
         "-f", "ogg", "pipe:1"],
        input=wav_bytes, capture_output=True,
    )
    if r.returncode != 0 or not r.stdout:
        print(f">> ffmpeg не справился, шлю как есть: {r.stderr.decode()[:200]}")
        return wav_bytes, "audio/wav"
    return r.stdout, "audio/ogg"


def ensure_ydotoold():
    if not shutil.which("ydotool"):
        print("ydotool не найден! sudo apt install ydotool")
        return
    if not os.path.exists(YDOTOOL_SOCKET):
        subprocess.Popen(
            ["ydotoold", f"--socket-path={YDOTOOL_SOCKET}", "--socket-perm=0660"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(0.5)
        print("ydotoold запущен")


class VoiceType:
    def __init__(self):
        ensure_ydotoold()
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setApplicationName("VoiceType")

        self.signals = Signals()
        self.signals.set_state.connect(self._on_state)
        self.signals.insert_text.connect(self._on_insert)
        self.signals.notify.connect(self._on_notify)

        self.pa = pyaudio.PyAudio()
        self.recording = False
        self.mic_thread = None
        self.stop_event = threading.Event()
        self.pending_enter = False
        self.busy = False

        self.icons = {name: make_icon(color) for name, color in COLORS.items()}

        self._anchor = QWidget()
        self._anchor.setFixedSize(0, 0)
        self._anchor.show()
        self._anchor.hide()

        self.tray = QSystemTrayIcon(self._anchor)
        self.tray.setIcon(self.icons["ready"])
        self.tray.setToolTip("VoiceType — готов (F7)")

        menu = QMenu()
        calib_action = QAction("Калибровка микрофона (говори 10 с)")
        calib_action.triggered.connect(self.calibrate)
        menu.addAction(calib_action)
        quit_action = QAction("Выход")
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_click)
        self.tray.setVisible(True)
        self.tray.show()

        print("Ищу клавиатуры...")
        self.keyboards = find_keyboards()
        self.kb_threads = []
        for kb in self.keyboards:
            t = threading.Thread(target=self._watch_kb, args=(kb,), daemon=True)
            t.start()
            self.kb_threads.append(t)

        print("VoiceType запущен!")

    def _watch_kb(self, device):
        try:
            for event in device.read_loop():
                if event.type == ecodes.EV_KEY and event.value == 1:
                    if event.code == KEY_F7:
                        self.toggle(with_enter=False)
                    elif event.code == KEY_F8 and self.recording:
                        self.toggle(with_enter=True)
        except Exception as e:
            print(f"Ошибка чтения {device.name}: {e}")

    def calibrate(self):
        if self.busy or self.recording:
            return
        self.busy = True
        self.signals.set_state.emit("recording")
        self.signals.notify.emit("Калибровка: говори громко и ровно без пауз 10 секунд", 4000)
        threading.Thread(target=self._calibrate, daemon=True).start()

    def _calibrate(self):
        # Sweep from loud to quiet and keep the loudest level that does not clip — loudest = best for STT, clipping = worst
        chosen = 8
        try:
            stream = self.pa.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
            for vol in (70, 55, 42, 32, 24, 18, 13, 8):
                subprocess.run(["pactl", "set-source-volume", HW_MIC, f"{vol}%"], capture_output=True)
                stream.read(CHUNK * 8, exception_on_overflow=False)
                pcm = array.array("h", stream.read(int(RATE * 1.2), exception_on_overflow=False))
                loud = sorted(map(abs, pcm))
                clipped = sum(1 for v in loud if v >= 32000) / len(loud)
                p99 = loud[int(len(loud) * 0.99)]
                print(f">> Калибровка {vol}%: клип {clipped:.2%}, p99 {p99}")
                if clipped < 0.0005 and p99 <= 26000:
                    chosen = vol
                    break
            stream.stop_stream()
            stream.close()
        except Exception as e:
            print(f"Ошибка калибровки: {e}")
        subprocess.run(["pactl", "set-source-volume", HW_MIC, f"{chosen}%"], capture_output=True)
        print(f">> Калибровка: выбрано {chosen}%")
        self.signals.notify.emit(f"Калибровка готова: громкость микрофона {chosen}%", 3000)
        self.signals.set_state.emit("ready")

    def _on_tray_click(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.toggle(with_enter=True)

    def toggle(self, with_enter):
        # Ignore clicks while Deepgram/typing is in flight — otherwise icon states and pending_enter race
        if self.busy:
            return
        if self.recording:
            self.pending_enter = with_enter
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        self.recording = True
        self.stop_event.clear()
        self.signals.set_state.emit("recording")
        print(">> Запись...")

        def record():
            frames = []
            try:
                stream = self.pa.open(
                    format=FORMAT, channels=CHANNELS, rate=RATE,
                    input=True, frames_per_buffer=CHUNK,
                )
                while not self.stop_event.is_set():
                    data = stream.read(CHUNK, exception_on_overflow=False)
                    frames.append(data)
                stream.stop_stream()
                stream.close()
            except Exception as e:
                print(f"Ошибка записи: {e}")

            if len(frames) * CHUNK / RATE >= 0.4:
                self._transcribe(frames, self.pending_enter)
            else:
                self.signals.set_state.emit("ready")

        self.mic_thread = threading.Thread(target=record, daemon=True)
        self.mic_thread.start()

    def _stop_recording(self):
        self.recording = False
        self.busy = True
        self.stop_event.set()
        print(">> Стоп, распознаю...")

    def _transcribe(self, frames, with_enter):
        self.signals.set_state.emit("processing")
        try:
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(self.pa.get_sample_size(FORMAT))
                wf.setframerate(RATE)
                wf.writeframes(b"".join(frames))
            audio_data = buf.getvalue()
            pcm = array.array("h", b"".join(frames))
            print(f">> Аудио: {len(frames) * CHUNK / RATE:.1f}с, пик {max(map(abs, pcm))}/32767")
            adjust_mic_gain(pcm)
            with open("/tmp/voicetype_last.wav", "wb") as f:
                f.write(audio_data)
            audio_data, content_type = clean_audio(audio_data)
            text = self._deepgram_transcribe(audio_data, content_type)
            if text:
                print(f">> Текст: {text}")
                self.signals.insert_text.emit(text, with_enter)
            else:
                print(">> Не удалось распознать")
                self.signals.notify.emit("Не удалось распознать речь", 2000)
                self.signals.set_state.emit("ready")
        except Exception as e:
            # Never lose a take: /tmp/voicetype_last.wav is overwritten by the next recording
            os.makedirs(FAILED_DIR, exist_ok=True)
            saved = os.path.join(FAILED_DIR, time.strftime("take_%Y-%m-%d_%H%M%S.wav"))
            shutil.copy("/tmp/voicetype_last.wav", saved)
            print(f">> Ошибка: {e}. Запись сохранена: {saved}")
            self.signals.notify.emit(f"Ошибка STT: {e}", 3000)
            self.signals.set_state.emit("ready")

    def _deepgram_transcribe(self, audio_data: bytes, content_type: str) -> str:
        url = ("https://api.deepgram.com/v1/listen?model=nova-3&language=ru&smart_format=true"
               "&punctuate=true&diarize_model=latest")
        req = urllib.request.Request(url, data=audio_data, method="POST")
        req.add_header("Authorization", f"Token {DEEPGRAM_API_KEY}")
        req.add_header("Content-Type", content_type)
        # Goes through HTTPS_PROXY (Contabo): measured 3.3s steady vs 3.8-12s jittery direct from RU
        with urllib.request.urlopen(req, timeout=300) as resp:
            result = json.loads(resp.read().decode())
        words = result["results"]["channels"][0]["alternatives"][0]["words"]
        multi = len({w["speaker"] for w in words}) > 1
        # One line only: a newline would be typed as Enter and send the message mid-sentence
        parts = []
        last = None
        for w in words:
            token = w.get("punctuated_word") or w["word"]
            if w["confidence"] < LOW_CONF:
                token += "(?)"
            if multi and w["speaker"] != last:
                token = f"Спикер {w['speaker'] + 1}: {token}"
                last = w["speaker"]
            parts.append(token)
        return " ".join(parts)

    def _on_state(self, state):
        self.tray.setIcon(self.icons.get(state, self.icons["ready"]))
        tips = {
            "ready": "VoiceType — готов (клик/F7 — запись)",
            "recording": "VoiceType — ЗАПИСЬ... (клик — стоп + Enter)",
            "processing": "VoiceType — распознаю...",
            "done": "VoiceType — готов (F7)",
        }
        self.tray.setToolTip(tips.get(state, ""))
        if state == "ready":
            self.busy = False

    def _on_notify(self, msg, ms):
        self.tray.showMessage("VoiceType", msg, QSystemTrayIcon.Warning, ms)

    def _on_insert(self, text, with_enter):
        self.signals.set_state.emit("done")
        paste_text(text, with_enter)
        QTimer.singleShot(1500, lambda: self.signals.set_state.emit("ready"))

    def quit(self):
        self.pa.terminate()
        self.tray.hide()
        self.app.quit()

    def run(self):
        sys.exit(self.app.exec_())


if __name__ == "__main__":
    VoiceType().run()
