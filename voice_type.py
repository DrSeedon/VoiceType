import os
import sys
import subprocess
import threading
import io
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

EN2RU = dict(zip(
    "qwertyuiop[]asdfghjkl;'zxcvbnm,.QWERTYUIOP{}ASDFGHJKL:\"ZXCVBNM<>`~",
    "йцукенгшщзхъфывапролджэячсмитьбюЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮёЁ",
))
RU2EN = {v: k for k, v in EN2RU.items()}


def _ydotool_env():
    env = os.environ.copy()
    env["YDOTOOL_SOCKET"] = YDOTOOL_SOCKET
    return env


def _get_layout():
    r = subprocess.run(
        ["busctl", "--user", "call", "org.kde.keyboard",
         "/Layouts", "org.kde.KeyboardLayouts", "getLayout"],
        capture_output=True, text=True,
    )
    try:
        return int(r.stdout.strip().split()[-1])
    except (ValueError, IndexError):
        return 0


def _set_layout(n):
    subprocess.run(
        ["busctl", "--user", "call", "org.kde.keyboard",
         "/Layouts", "org.kde.KeyboardLayouts", "setLayout", "u", str(n)],
        capture_output=True, text=True,
    )


def _split_by_lang(text):
    chunks = []
    cur = ""
    cur_ru = None
    neutral = ""
    for ch in text:
        is_cyr = ch in RU2EN
        is_lat = ch.isascii() and ch.isalpha()
        if not is_cyr and not is_lat:
            neutral += ch
            continue
        need_ru = is_cyr
        if cur_ru is not None and need_ru != cur_ru:
            cur += neutral
            chunks.append((cur, cur_ru))
            cur = ""
            neutral = ""
        else:
            cur += neutral
            neutral = ""
        cur_ru = need_ru
        cur += ch
    cur += neutral
    if cur:
        chunks.append((cur, cur_ru if cur_ru is not None else False))
    return chunks


def type_text(text, with_enter=False):
    saved = _get_layout()
    env = _ydotool_env()
    chunks = _split_by_lang(text)
    for chunk, is_ru in chunks:
        if is_ru:
            mapped = "".join(RU2EN.get(ch, ch) for ch in chunk)
            _set_layout(1)
        else:
            mapped = chunk
            _set_layout(0)
        time.sleep(0.05)
        subprocess.run(["ydotool", "type", "--", mapped], env=env, check=False, capture_output=True)
    if with_enter:
        time.sleep(0.05)
        subprocess.run(["ydotool", "key", "28:1", "28:0"], env=env, check=False, capture_output=True)
    _set_layout(saved)


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

        self.pa = pyaudio.PyAudio()
        self.recording = False
        self.mic_thread = None
        self.stop_event = threading.Event()
        self.pending_enter = False

        self.icons = {name: make_icon(color) for name, color in COLORS.items()}

        self._anchor = QWidget()
        self._anchor.setFixedSize(0, 0)
        self._anchor.show()
        self._anchor.hide()

        self.tray = QSystemTrayIcon(self._anchor)
        self.tray.setIcon(self.icons["ready"])
        self.tray.setToolTip("VoiceType — готов (F7)")

        menu = QMenu()
        quit_action = QAction("Выход")
        quit_action.triggered.connect(self.quit)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
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
                        if not self.recording:
                            self._start_recording()
                        else:
                            self.pending_enter = False
                            self._stop_recording()
                    elif event.code == KEY_F8:
                        if self.recording:
                            self.pending_enter = True
                            self._stop_recording()
        except Exception as e:
            print(f"Ошибка чтения {device.name}: {e}")

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

            if frames:
                self._transcribe(frames)
            else:
                self.signals.set_state.emit("ready")

        self.mic_thread = threading.Thread(target=record, daemon=True)
        self.mic_thread.start()

    def _stop_recording(self):
        self.recording = False
        self.stop_event.set()
        print(">> Стоп, распознаю...")

    def _transcribe(self, frames):
        self.signals.set_state.emit("processing")
        try:
            buf = io.BytesIO()
            with wave.open(buf, "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(self.pa.get_sample_size(FORMAT))
                wf.setframerate(RATE)
                wf.writeframes(b"".join(frames))
            audio_data = buf.getvalue()
            text = self._deepgram_transcribe(audio_data)
            if text:
                print(f">> Текст: {text}")
                self.signals.insert_text.emit(text, self.pending_enter)
            else:
                print(">> Не удалось распознать")
                self.tray.showMessage("VoiceType", "Не удалось распознать речь", QSystemTrayIcon.Warning, 2000)
                self.signals.set_state.emit("ready")
        except Exception as e:
            print(f">> Ошибка: {e}")
            self.tray.showMessage("VoiceType", f"Ошибка STT: {e}", QSystemTrayIcon.Critical, 3000)
            self.signals.set_state.emit("ready")

    def _deepgram_transcribe(self, audio_data: bytes) -> str:
        url = "https://api.deepgram.com/v1/listen?model=nova-2&language=ru&smart_format=true"
        req = urllib.request.Request(url, data=audio_data, method="POST")
        req.add_header("Authorization", f"Token {DEEPGRAM_API_KEY}")
        req.add_header("Content-Type", "audio/wav")
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
        transcript = result["results"]["channels"][0]["alternatives"][0]["transcript"]
        return transcript.strip()

    def _on_state(self, state):
        self.tray.setIcon(self.icons.get(state, self.icons["ready"]))
        tips = {
            "ready": "VoiceType — готов (F7)",
            "recording": "VoiceType — ЗАПИСЬ... (F7/F8 стоп)",
            "processing": "VoiceType — распознаю...",
            "done": "VoiceType — готов (F7)",
        }
        self.tray.setToolTip(tips.get(state, ""))

    def _on_insert(self, text, with_enter):
        self.signals.set_state.emit("done")
        type_text(text, with_enter)
        QTimer.singleShot(1500, lambda: self.signals.set_state.emit("ready"))

    def quit(self):
        self.pa.terminate()
        self.tray.hide()
        self.app.quit()

    def run(self):
        sys.exit(self.app.exec_())


if __name__ == "__main__":
    VoiceType().run()
