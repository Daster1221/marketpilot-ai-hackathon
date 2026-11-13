"""Local speech recognition. Audio never leaves the machine running this module."""
import io
import os
import threading
from pathlib import Path

MAX_AUDIO_BYTES = 5 * 1024 * 1024
_LOCK = threading.Lock()
_MODEL = None
_MODEL_CONFIG = None


def model_settings():
    root = Path(__file__).resolve().parent
    name = os.environ.get('WHISPER_MODEL') or 'small'
    local = root / 'data' / 'models' / ('whisper-' + name)
    source = str(local) if local.is_dir() else name
    return (source, os.environ.get('WHISPER_DEVICE') or 'cpu', os.environ.get('WHISPER_COMPUTE_TYPE') or 'int8')


def load_model():
    global _MODEL, _MODEL_CONFIG
    settings = model_settings()
    if _MODEL is not None and _MODEL_CONFIG == settings:
        return _MODEL
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise ValueError('Для локального голоса запустите install_speech.bat, затем перезапустите бота.') from None
    try:
        model = WhisperModel(settings[0], device=settings[1], compute_type=settings[2], local_files_only=True,
                             cpu_threads=max(1, min(4, (os.cpu_count() or 2) // 2)))
    except Exception:
        raise ValueError('Не удалось загрузить локальную модель речи. Запустите install_speech.bat или проверьте WHISPER_MODEL. Аудио внешнему AI не отправлялось.') from None
    _MODEL, _MODEL_CONFIG = model, settings
    return model


def warmup():
    with _LOCK:
        load_model()


def transcribe(audio, filename='voice.ogg', content_type='audio/ogg'):
    if len(audio) > MAX_AUDIO_BYTES:
        raise ValueError('Голосовое слишком большое. Отправьте запись до 5 МБ.')
    if not audio:
        raise ValueError('Голосовое пустое. Попробуйте записать его снова.')
    # One shared model prevents duplicate memory use and concurrent CPU overload.
    with _LOCK:
        model = load_model()
        try:
            segments, info = model.transcribe(io.BytesIO(audio), language=os.environ.get('WHISPER_LANGUAGE') or 'ru',
                                              beam_size=5, vad_filter=True, condition_on_previous_text=False)
            text = ' '.join(segment.text.strip() for segment in segments).strip()
        except Exception:
            raise ValueError('Локальная модель не смогла прочитать аудио. Отправьте голосовое заново или напишите задачу текстом.') from None
    if not text or len(text) > 6000:
        raise ValueError('Не удалось разобрать речь. Попробуйте записать сообщение короче и без фонового шума.')
    return text
