#!/bin/bash
cd "$(dirname "$0")"

pkill -f "python.*voice_type.py" 2>/dev/null
sleep 0.3

source venv/bin/activate
export QT_PLUGIN_PATH="$(python -c 'import PyQt5, os; print(os.path.join(os.path.dirname(PyQt5.__file__), "Qt5", "plugins"))')"
if [ -n "$WAYLAND_DISPLAY" ]; then
    export QT_QPA_PLATFORM=wayland
    if [ ! -S /tmp/.ydotool_socket ]; then
        ydotoold --socket-path=/tmp/.ydotool_socket --socket-perm=0660 &
        sleep 0.5
    fi
fi
export YDOTOOL_SOCKET=/tmp/.ydotool_socket

nohup python -u voice_type.py > voicetype.log 2>&1 &
echo "VoiceType запущен (PID: $!)"
echo "Логи: $(pwd)/voicetype.log"
