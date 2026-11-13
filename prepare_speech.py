"""Explicitly download model weights once, then recognize speech offline."""
import os
from pathlib import Path

import app
import speech


def main():
    try:
        speech.warmup()
        print('Локальная модель уже доступна. Распознавание готово, скачивать ничего не нужно.')
        return
    except ValueError:
        pass
    from faster_whisper.utils import download_model
    name = os.environ.get('WHISPER_MODEL') or 'small'
    if name not in ('tiny', 'base', 'small', 'medium', 'large-v3', 'turbo'):
        raise SystemExit('Укажите WHISPER_MODEL=small или путь к уже скачанной модели.')
    target = Path(__file__).resolve().parent / 'data' / 'models' / ('whisper-' + name)
    print('Однократно скачиваю веса модели:', name)
    print('Аудио никуда не отправляется. Место хранения:', target)
    download_model(name, output_dir=str(target))
    speech.warmup()
    print('Локальная модель готова. Теперь запустите start_bot.bat.')


if __name__ == '__main__':
    main()
