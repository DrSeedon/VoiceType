# VoiceType 🎤

Голосовой ввод текста для Linux. Запись по хоткею, распознавание через Google, автоматический ввод текста в любое приложение.

## Установка

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Требования:**

- `wtype` (Wayland) или `xdotool` (X11) для ввода текста:
  ```bash
  sudo apt install wtype  # Wayland
  # или
  sudo apt install xdotool  # X11
  ```
- Доступ к `/dev/input` (клавиатура):
  ```bash
  sudo usermod -aG input $USER
  # Перелогинься после выполнения!
  ```

## Запуск

```bash
./run.sh
```

Приложение запустится в системном трее.

## Управление

- **F7** — начать/остановить запись → вставить текст
- **F8** — остановить запись → вставить текст + Enter

## Цвета индикатора

- 🟢 **Зеленый** — готов к записи
- 🔴 **Красный** — идет запись
- 🟡 **Желтый** — распознавание речи
- 🔵 **Синий** — текст введен

## Логи

```bash
tail -f /tmp/voicetype.log
```

## Остановка

```bash
pkill -f voice_type.py
```

## Требования системы

- Linux (X11 или Wayland)
- Python 3.7+
- Микрофон
- Интернет (Google Speech API)
