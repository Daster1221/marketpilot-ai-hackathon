"""Read-only API checks: no generation, polling, or Telegram messages."""
import json
import os
import urllib.error
import urllib.request

import app
from telegram_bot import allowed_user_ids


def check(name, url, token=None):
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=20) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        meaning = {401: 'ключ или токен не принят', 402: 'недостаточно средств', 429: 'слишком много запросов'}
        print(f'{name}: HTTP {status} — {meaning.get(status, "сервис отклонил запрос")}')
    except (urllib.error.URLError, TimeoutError):
        print(f'{name}: нет соединения или превышено время ожидания')
    except (ValueError, TypeError):
        print(f'{name}: неожиданный формат ответа')
    return None


def main():
    print('Файл настроек:', app.ROOT / '.env')
    print('Ключи не выводятся. Посты не генерируются, сообщения не отправляются.')
    print('Адрес AI:', app.ai_base_url())
    success = True
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    if not token:
        print('Telegram: заполните TELEGRAM_BOT_TOKEN')
        success = False
    else:
        result = check('Telegram', f'https://api.telegram.org/bot{token}/getMe')
        if result and result.get('ok'):
            print('Telegram: токен принят, бот @' + result['result'].get('username', ''))
        else:
            success = False
    owners = allowed_user_ids()
    print('Доступ:', f'настроен для {len(owners)} пользователей' if owners else 'не настроен — запустите бота и отправьте /start, затем внесите полученный ID в .env')
    key = os.environ.get('DEEPSEEK_API_KEY', '')
    if not key:
        print('DeepSeek: ключ пустой, будет деморежим')
    else:
        result = check(app.ai_service_name(), app.ai_base_url() + '/models', key)
        if result:
            models = [model.get('id') for model in result.get('data', []) if isinstance(model, dict)]
            selected = os.environ.get('DEEPSEEK_MODEL') or 'deepseek-flash'
            if selected in models:
                print('DeepSeek: ключ принят, выбранная модель доступна')
            else:
                print('DeepSeek: выбранная модель отсутствует. Доступные модели:', ', '.join(str(m) for m in models))
                success = False
        else:
            success = False
    print('Канал:', 'задан (права публикации проверяются при отправке)' if os.environ.get('TELEGRAM_CHANNEL_ID') else 'не задан, анкета и генерация доступны без него')
    print('Проверка моделей не подтверждает баланс и успешность генерации — это проверяется первым запросом в боте.')
    return 0 if success else 1


if __name__ == '__main__':
    raise SystemExit(main())
