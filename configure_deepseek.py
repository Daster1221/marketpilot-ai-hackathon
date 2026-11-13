"""Validate a locally entered key before updating the settings file."""
import getpass
import json
import os
from pathlib import Path
import urllib.error
import urllib.request
import app

ROOT = Path(__file__).resolve().parent


def verify(key):
    request = urllib.request.Request(app.ai_base_url() + '/models', headers={'Authorization': 'Bearer ' + key})
    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.load(response)
    models = [item['id'] for item in data.get('data', []) if isinstance(item, dict) and isinstance(item.get('id'), str)]
    if not models:
        raise ValueError('API не вернул список моделей. Настройки не изменены.')
    return models


def save_key(path, key):
    lines = path.read_text(encoding='utf-8-sig').splitlines() if path.exists() else []
    # Remove duplicate assignments, preserving unrelated credentials verbatim.
    lines = [line for line in lines if line.split('=', 1)[0].strip() != 'DEEPSEEK_API_KEY']
    lines.append('DEEPSEEK_API_KEY=' + key)
    temporary = path.with_name(path.name + '.tmp')
    try:
        temporary.write_text('\n'.join(lines) + '\n', encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main():
    print('Прямая настройка DeepSeek. Ключ не выводится и не отправляется в Telegram.')
    print('Будет выполнена только проверка авторизации, без генерации постов.')
    print('Целевой файл:', ROOT / '.env')
    print('Провайдер:', app.ai_service_name(), 'Адрес:', app.ai_base_url())
    key = getpass.getpass('Вставьте свой полный ключ и нажмите Enter (ввод скрыт): ').strip()
    if len(key) >= 2 and key[0] == key[-1] and key[0] in ('"', "'"):
        key = key[1:-1].strip()
    if not key or not key.isascii() or any(c.isspace() for c in key):
        print('Ввод пустой или содержит пробелы/недопустимые символы. Файл не изменён.')
        return 1
    try:
        verify(key)
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        if status == 401:
            print(f'Введённый ключ отклонён {app.ai_service_name()} (401). Файл не изменён.')
            print('Проверьте соответствие ключа и DEEPSEEK_BASE_URL в .env. Ключ ProxyAPI работает только с адресом ProxyAPI.')
        else:
            print(f'DeepSeek вернул HTTP {status}. Файл не изменён.')
        return 1
    except (urllib.error.URLError, TimeoutError):
        print('Нет соединения с DeepSeek. Файл не изменён.')
        return 1
    except (ValueError, KeyError, TypeError):
        print('Неожиданный ответ DeepSeek. Файл не изменён.')
        return 1
    save_key(ROOT / '.env', key)
    print('DeepSeek принял ключ. Он сохранён в .env. Закройте старое окно бота и запустите start_bot.bat.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
