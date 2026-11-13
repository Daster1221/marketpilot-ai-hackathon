"""Telegram-first local prototype. Start with: python telegram_bot.py."""
import json
import os
import re
import secrets
import threading
import time
import urllib.error
from urllib.parse import urlparse

import app
import speech
import post_format
from html import escape

QUESTIONS = [
    ('company', 'Компания', 'Как называется компания и чем занимается?\nМожно сразу добавить ссылку на сайт. Пока сохраню её в профиле, без автоматического изучения.'),
    ('audience', 'Аудитория', 'Для кого будем писать?', ['Для сотрудников', 'Для клиентов', 'Для партнёров']),
    ('objective', 'Задача', 'Что хотите упростить?', ['Быстрее писать посты', 'Регулярно вести канал', 'Превращать интервью в посты', 'Рассказывать о мероприятиях']),
    ('style', 'Стиль', 'Как должна звучать компания?\nМожно написать свой вариант или прислать короткий пример.', ['Дружелюбно и просто', 'Сдержанно и по делу', 'Экспертно и полезно', 'Легко, с юмором']),
    ('limits', 'Ограничения', 'Что важно учитывать?\nЦенности, запрещённые слова, обращение на «вы». Если особых правил нет — пропустите.'),
]
MENU = [['✨ Новый пост', '🗂 Мои посты'], ['🏢 Профиль', '❔ Помощь']]


def btn(text, data):
    return {'text': text, 'callback_data': data}


def context(chat):
    with app.db() as con:
        row = con.execute('SELECT data FROM bot_context WHERE chat=?', (chat,)).fetchone()
    return json.loads(row['data']) if row else {}


def set_context(chat, value):
    with app.db() as con:
        con.execute('INSERT OR REPLACE INTO bot_context VALUES(?,?)', (chat, json.dumps(value, ensure_ascii=False)))


def allowed_user_ids():
    return {value for value in re.split(r'[,;\s]+', os.environ.get('TELEGRAM_OWNER_ID', '').strip()) if value.isdecimal()}


def init_db():
    with app.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS bot_sessions (chat INTEGER PRIMARY KEY, step INTEGER, answers TEXT, editing INTEGER)')
        con.execute('CREATE TABLE IF NOT EXISTS bot_posts (id INTEGER PRIMARY KEY, chat INTEGER, topic TEXT, body TEXT, image_prompt TEXT, source TEXT, status TEXT DEFAULT "draft", rev INTEGER DEFAULT 1, message_id TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS bot_meta (key TEXT PRIMARY KEY, value INTEGER)')
        con.execute('CREATE TABLE IF NOT EXISTS bot_context (chat INTEGER PRIMARY KEY, data TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS bot_confirmations (post INTEGER PRIMARY KEY, chat INTEGER, rev INTEGER, channel TEXT, nonce TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS bot_inbox (id INTEGER PRIMARY KEY, chat INTEGER, payload TEXT, status TEXT DEFAULT "queued")')
        con.execute('CREATE TABLE IF NOT EXISTS bot_versions (post INTEGER, rev INTEGER, body TEXT, instruction TEXT, kind TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(post,rev))')
        con.execute('CREATE TABLE IF NOT EXISTS bot_post_context (post INTEGER PRIMARY KEY, profile TEXT, task TEXT, clarification TEXT)')
        con.execute('UPDATE bot_inbox SET status="interrupted" WHERE status="running"')
        if not con.execute('SELECT 1 FROM bot_meta WHERE key="form_version"').fetchone():
            for row in con.execute('SELECT * FROM bot_sessions').fetchall():
                old = json.loads(row['answers'])
                answers = {'company': '\n'.join(old.get(k, '') for k in ('name', 'about', 'site') if old.get(k)),
                           'audience': old.get('audience', ''), 'objective': '\n'.join(old.get(k, '') for k in ('problem', 'goal') if old.get(k)),
                           'style': old.get('style', ''), 'limits': old.get('limits', '')}
                con.execute('UPDATE bot_sessions SET step=?, answers=?,editing=NULL WHERE chat=?', (5 if row['step'] >= 9 else 0, json.dumps(answers, ensure_ascii=False), row['chat']))
            con.execute('INSERT INTO bot_meta VALUES("form_version",2)')
        con.execute('UPDATE bot_posts SET status="delivery_unknown" WHERE status="publishing"')
        con.execute('INSERT OR IGNORE INTO bot_versions(post,rev,body,instruction,kind) SELECT id,rev,body,"","initial" FROM bot_posts')


def tg(method, payload):
    token = os.environ['TELEGRAM_BOT_TOKEN']
    try:
        result = app.remote_json(f'https://api.telegram.org/bot{token}/{method}', payload)
    except urllib.error.HTTPError as error:
        status = error.code
        error.close()
        messages = {401: 'Telegram не принял TELEGRAM_BOT_TOKEN. Проверьте токен от BotFather.',
                    409: 'Конфликт Telegram: остановите второй экземпляр бота с этим токеном.',
                    403: 'Telegram запретил действие. Проверьте доступ бота к чату и права публикации.',
                    400: 'Telegram отклонил действие. Проверьте ID канала и формат сообщения.'}
        raise ValueError(messages.get(status, f'Ошибка Telegram HTTP {status}. Попробуйте позже.')) from None
    except (urllib.error.URLError, TimeoutError):
        raise ValueError('Нет соединения с Telegram. Проверьте интернет и доступ к api.telegram.org.') from None
    if not result.get('ok'):
        raise RuntimeError('Telegram отклонил запрос')
    return result['result']


def say(chat, text, options=None, inline=None, formatted=False):
    payload = {'chat_id': chat, 'text': text}
    if formatted:
        payload['parse_mode'] = 'HTML'
    if inline:
        payload['reply_markup'] = {'inline_keyboard': inline}
    else:
        rows = options or MENU
        payload['reply_markup'] = {'keyboard': [[{'text': value} for value in (row if isinstance(row, list) else [row])] for row in rows], 'resize_keyboard': True, 'input_field_placeholder': 'Напишите задачу для AI…'}
    return tg('sendMessage', payload)


def session(chat):
    with app.db() as con:
        row = con.execute('SELECT * FROM bot_sessions WHERE chat=?', (chat,)).fetchone()
    return dict(row) if row else {'chat': chat, 'step': 0, 'answers': '{}', 'editing': None}


def save(state):
    with app.db() as con:
        con.execute('INSERT OR REPLACE INTO bot_sessions VALUES(?,?,?,?)', (state['chat'], state['step'], state['answers'], state['editing']))


def brief(state):
    answers = json.loads(state['answers'])
    return '\n\n'.join(label + ': ' + answers.get(key, 'Не указано') for key, label, *_ in QUESTIONS)


def ask(state):
    question = QUESTIONS[state['step']]
    choices = list(question[3]) if len(question) > 3 else []
    buttons = [[btn(value, f'answer:{state["step"]}:{i}')] for i, value in enumerate(choices)]
    nav = []
    if state['step'] > 0:
        nav.append(btn('← Назад', f'back:{state["step"]}'))
    if question[0] == 'limits':
        nav.append(btn('Пропустить →', f'skip:{state["step"]}'))
    if nav:
        buttons.append(nav)
    say(state['chat'], f'Знакомство · {state["step"] + 1} из {len(QUESTIONS)}\n\n{question[2]}', inline=buttons or [[btn('❔ Что написать?', 'intro_help')]])


def show_post(chat, post_id):
    with app.db() as con:
        post = con.execute('SELECT * FROM bot_posts WHERE id=? AND chat=?', (post_id, chat)).fetchone()
    if not post:
        raise ValueError('Пост не найден')
    labels = {'draft': 'Черновик', 'approved': 'Готов к проверке', 'published': 'Опубликован', 'cancelled': 'Отменён', 'publishing': 'Отправляется', 'delivery_unknown': 'Проверьте доставку в канале вручную'}
    heading = f'{labels[post["status"]]} · №{post_id} · версия {post["rev"]}\n{post["topic"][:100]}'
    if post['source'] == 'demo':
        heading += '\nДемо: шаблон без AI'
    buttons = []
    def button(title, command):
        return btn(title, f'{command}:{post_id}:{post["rev"]}')
    if post['status'] in ('draft', 'approved'):
        buttons = [[button('✏️ Изменить', 'edit'), button('🗑 Отменить', 'cancel')], [button('📤 Отправить', 'send')]]
    elif post['status'] == 'cancelled':
        buttons = [[button('↩️ Восстановить', 'restore')]]
    if session(chat)['editing'] == post_id:
        heading += '\nМожно продолжить: напишите следующую правку.'
        buttons.append([btn('✓ Готово, закончить правки', 'stop_edit')])
    buttons.append([button('🕘 История правок', 'history'), btn('← К списку', 'posts')])
    body = post_format.normalize(post['body'])
    text = escape(heading) + '\n\n' + body
    if post_format.length(text) > 4096:
        say(chat, heading)
        text = body
    return say(chat, text, inline=buttons, formatted=True)


def post_memory(chat, post_id):
    with app.db() as con:
        history = [dict(row) for row in con.execute('SELECT v.rev AS revision,v.body,v.instruction,v.kind FROM bot_versions v JOIN bot_posts p ON p.id=v.post WHERE v.post=? AND p.chat=? ORDER BY v.rev', (post_id, chat))]
        row = con.execute('SELECT c.* FROM bot_post_context c JOIN bot_posts p ON p.id=c.post WHERE c.post=? AND p.chat=?', (post_id, chat)).fetchone()
    return history, dict(row) if row else {}


def remember_version(con, post_id, revision, body, instruction='', kind='initial'):
    con.execute('INSERT OR IGNORE INTO bot_versions(post,rev,body,instruction,kind) VALUES(?,?,?,?,?)', (post_id, revision, body, instruction, kind))


def list_posts(chat):
    with app.db() as con:
        posts = con.execute('SELECT * FROM bot_posts WHERE chat=? ORDER BY id DESC LIMIT 12', (chat,)).fetchall()
    if not posts:
        return say(chat, 'Пока нет постов. Расскажите, что подготовить.', inline=[[btn('✨ Создать пост', 'new')]])
    markers = {'draft': '📝', 'approved': '📝', 'published': '✅', 'cancelled': '🗑', 'delivery_unknown': '⚠️', 'publishing': '⏳'}
    buttons = [[btn(f'{markers[p["status"]]} №{p["id"]} · {p["topic"][:32]}', f'view:{p["id"]}:{p["rev"]}')] for p in posts]
    buttons.append([btn('✨ Новый пост', 'new'), btn('⌂ В меню', 'home')])
    return say(chat, 'Мои посты\n\nВыберите пост, чтобы открыть текст и действия. Показаны последние 12.', inline=buttons)


def preview(chat, post):
    channel = os.environ.get('TELEGRAM_CHANNEL_ID', '').strip()
    if not channel:
        return say(chat, 'Пост готов, но канал ещё не подключён.\n\nДобавьте TELEGRAM_CHANNEL_ID в .env и права публикации боту, затем перезапустите программу. Черновик сохранён.', inline=[[btn('← К посту', f'view:{post["id"]}:{post["rev"]}')]])
    destination = tg('getChat', {'chat_id': channel})
    nonce = secrets.token_hex(5)
    with app.db() as con:
        con.execute('INSERT OR REPLACE INTO bot_confirmations VALUES(?,?,?,?,?)', (post['id'], chat, post['rev'], channel, nonce))
    say(chat, f'Проверка перед отправкой\n\nКанал: {destination.get("title", channel)} ({channel})\nПост №{post["id"]} · версия {post["rev"]}\nВремя: сразу после подтверждения')
    say(chat, post_format.normalize(post['body']), inline=[[btn('✅ Подтвердить отправку', f'confirm:{post["id"]}:{post["rev"]}:{nonce}')], [btn('← Назад к посту', f'view:{post["id"]}:{post["rev"]}')]], formatted=True)


def callback(chat, data):
    if data.startswith('speech:'):
        _, action, nonce = data.split(':')
        pending = context(chat)
        if pending.get('mode') != 'voice' or pending.get('nonce') != nonce:
            raise ValueError('Эта расшифровка уже обработана. Используйте последнее сообщение.')
        return navigation(chat, 'voice_' + action)
    if data in ('home', 'posts', 'new', 'profile', 'help', 'profile_edit', 'profile_ok', 'stop_edit', 'retry', 'task_cancel', 'intro_help', 'voice_use', 'voice_edit', 'voice_cancel') or data.startswith(('answer:', 'back:', 'skip:')):
        return navigation(chat, data)
    parts = data.split(':')
    if len(parts) not in (3, 4):
        raise ValueError('Кнопка устарела. Откройте меню через /start.')
    command, post_id, revision = parts[:3]
    with app.db() as con:
        post = con.execute('SELECT * FROM bot_posts WHERE id=? AND chat=?', (int(post_id), chat)).fetchone()
        if not post or post['rev'] != int(revision):
            raise ValueError('Это старая версия поста. Откройте «Мои посты».')
        if command == 'history':
            history, origin = post_memory(chat, post['id'])
            lines = [f'История поста №{post["id"]}']
            if origin.get('task'):
                lines.append('Исходная задача: ' + origin['task'])
            for version in history:
                lines.append(f'Версия {version["revision"]}: ' + (version['instruction'] or 'Исходный текст'))
            text = '\n\n'.join(lines)
            for start in range(0, len(text), 3500):
                say(chat, text[start:start + 3500], inline=[[btn('← К посту', f'view:{post["id"]}:{post["rev"]}')]])
            return
        if command == 'view':
            con.execute('DELETE FROM bot_confirmations WHERE post=?', (post['id'],))
            con.commit()
            return show_post(chat, post['id'])
        if command in ('edit', 'replace'):
            if post['status'] not in ('draft', 'approved'):
                raise ValueError('Этот пост уже нельзя изменить.')
            state = session(chat)
            state['editing'] = post['id']
            save(state)
            set_context(chat, {'mode': command, 'rev': post['rev'], 'awaiting': True})
            remember_version(con, post['id'], post['rev'], post['body'])
            con.execute('DELETE FROM bot_confirmations WHERE post=?', (post['id'],))
            con.commit()
            say(chat, f'Правка поста №{post["id"]}\n\n' + ('Пришлите новый текст целиком.' if command == 'replace' else 'Что изменить? Например: «Сократи вдвое и убери официальный тон». Изменю только этот пост.'), inline=([[btn('📝 Заменить текст целиком', f'replace:{post["id"]}:{post["rev"]}')]] if command == 'edit' else []) + [[btn('← Не менять', 'stop_edit')]])
            return
        if command in ('cancel', 'restore'):
            expected = ('draft', 'approved') if command == 'cancel' else ('cancelled',)
            if post['status'] not in expected:
                raise ValueError('Состояние поста уже изменилось. Откройте «Мои посты».')
            con.execute('UPDATE bot_posts SET status=?,rev=rev+1 WHERE id=?', ('cancelled' if command == 'cancel' else 'draft', post['id']))
            con.execute('DELETE FROM bot_confirmations WHERE post=?', (post['id'],))
            con.commit()
            state = session(chat)
            if state['editing'] == post['id']:
                state['editing'] = None
                save(state)
                set_context(chat, {})
        elif command in ('send', 'approve', 'publish', 'confirm'):
            if post['status'] not in ('draft', 'approved'):
                raise ValueError('Этот пост уже отправлен или отменён. Повторная отправка запрещена.')
            state = session(chat)
            if state['editing'] == post['id']:
                if context(chat).get('awaiting', True):
                    raise ValueError('Сначала сохраните правки или отмените редактирование.')
                state['editing'] = None
                save(state)
                set_context(chat, {})
            if command != 'confirm':
                return preview(chat, post)
            approval = con.execute('SELECT * FROM bot_confirmations WHERE post=? AND chat=?', (post['id'], chat)).fetchone()
            if not approval or len(parts) != 4 or approval['nonce'] != parts[3] or approval['rev'] != post['rev'] or approval['channel'] != os.environ.get('TELEGRAM_CHANNEL_ID', '').strip():
                raise ValueError('Подтверждение устарело. Снова нажмите «Отправить» у актуального поста.')
            channel = approval['channel']
            con.execute('DELETE FROM bot_confirmations WHERE post=?', (post['id'],))
            con.execute('UPDATE bot_posts SET status="publishing" WHERE id=?', (post['id'],))
            con.commit()
            try:
                result = tg('sendMessage', {'chat_id': channel, 'text': post_format.normalize(post['body']), 'parse_mode': 'HTML'})
            except Exception:
                con.execute('UPDATE bot_posts SET status="delivery_unknown" WHERE id=?', (post['id'],))
                con.commit()
                raise ValueError('Доставка не подтверждена. Проверьте канал вручную. Автоматического повтора не будет.')
            con.execute('UPDATE bot_posts SET status="published", message_id=? WHERE id=?', (str(result['message_id']), post['id']))
        else:
            raise ValueError('Неизвестное действие')
    show_post(chat, post['id'])


def home(chat):
    rows = [[btn('✨ Создать пост', 'new'), btn('🗂 Мои посты', 'posts')], [btn('🏢 Профиль', 'profile'), btn('❔ Помощь', 'help')]]
    if context(chat).get('mode') == 'task':
        rows.insert(0, [btn('↻ Повторить последнюю задачу', 'retry')])
    say(chat, 'MarketPilot · ваш редактор\n\nНапишите или надиктуйте задачу:\n«Подготовь два поста о волейбольном турнире для сотрудников».\n\nЯ подготовлю черновики. Вы сможете изменить, отменить или отправить каждый пост.', inline=rows)


def navigation(chat, data):
    state = session(chat)
    pending = context(chat)
    if data.startswith('voice_'):
        if pending.get('mode') != 'voice':
            raise ValueError('Эта расшифровка уже обработана.')
        if data == 'voice_edit':
            return say(chat, 'Пришлите исправленную расшифровку текстом. Продолжу с неё.', inline=[[btn('← Отмена', 'voice_cancel')]])
        set_context(chat, pending['previous'])
        if data == 'voice_cancel':
            return ask(state) if state['step'] < len(QUESTIONS) else say(chat, 'Голосовое отменено. Предыдущая задача сохранена.')
        return message(chat, pending['text'])
    if state['editing'] and data in ('new', 'profile_edit', 'home'):
        return say(chat, 'Сначала завершите правку или отмените её.', inline=[[btn('← Не менять', 'stop_edit')]])
    if data == 'intro_help':
        return say(chat, 'Например: «Салаватстекло. Производим стекло, ведём внутренний канал компании». Можете добавить ссылку на сайт в это же сообщение.')
    if data.startswith(('answer:', 'back:', 'skip:')):
        parts = data.split(':')
        if int(parts[1]) != state['step'] or state['step'] >= len(QUESTIONS):
            raise ValueError('Этот вопрос уже пройден. Продолжите с последнего сообщения.')
        if parts[0] == 'back':
            state['step'] = max(0, state['step'] - 1)
            save(state)
            return ask(state)
        if parts[0] == 'skip':
            return answer_question(state, 'Не указано')
        choices = QUESTIONS[state['step']][3]
        return answer_question(state, choices[int(parts[2])])
    if data == 'profile_edit':
        state.update(step=0, editing=None)
        save(state)
        set_context(chat, {'mode': 'form'})
        return ask(state)
    if data == 'profile_ok':
        if state['step'] < len(QUESTIONS):
            return ask(state)
        set_context(chat, {})
        say(chat, 'Профиль сохранён. Можно приступать к постам.')
        return home(chat)
    if data == 'stop_edit':
        post_id = state['editing']
        state['editing'] = None
        save(state)
        set_context(chat, {})
        return show_post(chat, post_id) if post_id else home(chat)
    if data == 'task_cancel':
        set_context(chat, {})
        say(chat, 'Задача отменена. Готовые посты остались в списке.')
        return home(chat)
    if data == 'posts':
        return list_posts(chat)
    if data == 'profile':
        return show_brief(state) if state['step'] == len(QUESTIONS) else ask(state)
    if data == 'help':
        return say(chat, 'Как работать\n\n1. Напишите или надиктуйте, сколько постов и на какую тему нужно (до пяти за раз).\n2. Ответьте на уточнение, если не хватает фактов.\n3. Под постом нажмите «Изменить», «Отменить» или «Отправить».\n4. Перед публикацией проверьте канал и подтвердите отправку.\n\nГолосовые: до 3 минут и 5 МБ; сначала покажу расшифровку. Сайт сохраняется ссылкой. Изображения и расписание пока не подключены.', inline=[[btn('✨ Создать пост', 'new'), btn('⌂ В меню', 'home')]])
    if state['step'] < len(QUESTIONS):
        return ask(state)
    if context(chat).get('mode') == 'review':
        return show_brief(state)
    if data == 'retry':
        pending = context(chat)
        if not pending.get('task'):
            return home(chat)
        return create_posts(chat, pending['task'], pending.get('clarification', ''))
    if data == 'new':
        state['editing'] = None
        save(state)
        set_context(chat, {'mode': 'new_task'})
        return say(chat, 'Новая задача\n\nЧто подготовить? Укажите тему, количество и важные факты.\n\nНапример: «Два поста для сотрудников о турнире 15 ноября в 18:00 в спортзале. Первый — анонс, второй — напоминание».', inline=[[btn('← В меню', 'home')]])
    if data == 'home':
        if state['editing']:
            return say(chat, 'Сначала завершите правку или отмените её.', inline=[[btn('← Не менять', 'stop_edit')]])
        set_context(chat, {})
        return home(chat)


def answer_question(state, text):
    if not 1 <= len(text) <= 1000:
        raise ValueError('Ответ должен содержать от 1 до 1000 символов.')
    answers = json.loads(state['answers'])
    answers[QUESTIONS[state['step']][0]] = text
    state['answers'] = json.dumps(answers, ensure_ascii=False)
    state['step'] += 1
    save(state)
    if state['step'] < len(QUESTIONS):
        return ask(state)
    set_context(state['chat'], {'mode': 'review'})
    return show_brief(state)


def create_posts(chat, task, clarification=''):
    app.requested_count(task)
    set_context(chat, {'mode': 'task', 'task': task, 'clarification': clarification})
    say(chat, 'Готовлю черновики… Обычно это занимает до двух минут.')
    profile = brief(session(chat))
    result = app.prepare_posts(profile, task, clarification)
    if result.get('question'):
        set_context(chat, {'mode': 'clarify', 'task': task})
        return say(chat, result['question'], inline=[[btn('✕ Отменить задачу', 'task_cancel')]])
    ids = []
    with app.db() as con:
        for post in result['posts']:
            cursor = con.execute('INSERT INTO bot_posts(chat,topic,body,image_prompt,source) VALUES(?,?,?,?,?)', (chat, post['topic'], post['body'], post['image_prompt'], 'deepseek'))
            ids.append(cursor.lastrowid)
            remember_version(con, cursor.lastrowid, 1, post['body'])
            con.execute('INSERT INTO bot_post_context VALUES(?,?,?,?)', (cursor.lastrowid, profile, task, clarification))
    set_context(chat, {})
    say(chat, f'Готово · {len(ids)} поста\n\nКаждый можно изменить или отправить отдельно.')
    for post_id in ids:
        show_post(chat, post_id)


def message(chat, text):
    state = session(chat)
    aliases = {'✨ Новый пост': 'new', 'Подготовить посты': 'new', '/generate': 'new',
               '🗂 Мои посты': 'posts', 'Мои посты': 'posts', '/posts': 'posts',
               '🏢 Профиль': 'profile', 'Профиль бизнеса': 'profile', '/profile': 'profile',
               '❔ Помощь': 'help', '/help': 'help', 'Изменить анкету': 'profile_edit'}
    if text == '/start':
        if state['editing']:
            return say(chat, 'У вас открыта правка поста. Напишите пожелание или отмените правку.', inline=[[btn('← Не менять', 'stop_edit')]])
        if state['step'] == len(QUESTIONS):
            return show_brief(state) if context(chat).get('mode') == 'review' else home(chat)
        set_context(chat, {'mode': 'form'})
        say(chat, 'Привет! Я помогу готовить посты для вашей компании.\n\nПять коротких вопросов — и можно ставить задачи. Профиль хранится локально, для генерации передаётся подключённому AI.')
        return ask(state)
    if text in ('Отмена', '/cancel'):
        return navigation(chat, 'stop_edit' if state['editing'] else 'task_cancel')
    if text in aliases:
        if state['editing'] and aliases[text] not in ('help',):
            return say(chat, 'Вы сейчас редактируете пост. Пришлите правку или нажмите «Не менять».', inline=[[btn('← Не менять', 'stop_edit')]])
        return navigation(chat, aliases[text])
    if context(chat).get('mode') == 'voice':
        pending = context(chat)
        set_context(chat, pending['previous'])
        return message(chat, text)
    if state['editing']:
        if not 1 <= len(text) <= 4000:
            raise ValueError('Пришлите правку от 1 до 4000 символов.')
        post_id = state['editing']
        pending = context(chat)
        with app.db() as con:
            post = con.execute('SELECT * FROM bot_posts WHERE id=? AND chat=?', (post_id, chat)).fetchone()
        if not post or post['status'] not in ('draft', 'approved') or post['rev'] != pending.get('rev'):
            raise ValueError('Пост уже изменился. Отмените правку и откройте актуальную карточку.')
        if pending.get('mode') == 'replace':
            body = post_format.normalize(text)
        else:
            say(chat, 'Применяю правку…')
            history, origin = post_memory(chat, post_id)
            body = app.rewrite_post(origin.get('profile') or brief(state), post['body'], text,
                                    history=history, task=origin.get('task', ''), clarification=origin.get('clarification', ''))
        body = post_format.normalize(body)
        if not post_format.plain(body):
            raise ValueError('Текст пустой. Старая версия сохранена.')
        if post_format.length(body) > 3800:
            raise ValueError('Текст слишком длинный. Сократите его до 3800 символов.')
        with app.db() as con:
            remember_version(con, post_id, post['rev'], post['body'])
            result = con.execute('UPDATE bot_posts SET body=?,status="draft",rev=rev+1 WHERE id=? AND chat=? AND rev=? AND status IN ("draft","approved")', (body, post_id, chat, post['rev']))
            if result.rowcount != 1:
                raise ValueError('Пост уже изменился. Старая версия не перезаписана.')
            con.execute('DELETE FROM bot_confirmations WHERE post=?', (post_id,))
            remember_version(con, post_id, post['rev'] + 1, body, text, 'replace' if pending.get('mode') == 'replace' else 'rewrite')
        state['editing'] = post_id
        save(state)
        set_context(chat, {'mode': 'edit', 'rev': post['rev'] + 1, 'awaiting': False})
        return show_post(chat, post_id)
    if state['step'] < len(QUESTIONS):
        if text in ('Назад', '← Назад'):
            state['step'] = max(0, state['step'] - 1)
            save(state)
            return ask(state)
        return answer_question(state, 'Не указано' if text == 'Пропустить' else text)
    pending = context(chat)
    if pending.get('mode') == 'review':
        return show_brief(state)
    if not 1 <= len(text) <= 6000:
        raise ValueError('Опишите задачу текстом до 6000 символов.')
    if pending.get('mode') == 'clarify':
        return create_posts(chat, pending['task'], text)
    return create_posts(chat, text)


def show_brief(state):
    if state['step'] < len(QUESTIONS):
        return ask(state)
    text = 'Профиль компании\n\n' + brief(state)
    buttons = [[btn('✏️ Изменить профиль', 'profile_edit'), btn('⌂ В меню', 'home')]]
    if context(state['chat']).get('mode') == 'review':
        buttons = [[btn('✅ Всё верно', 'profile_ok')], [btn('✏️ Исправить', 'profile_edit')]]
    for start in range(0, len(text), 3800):
        say(state['chat'], text[start:start + 3800], inline=buttons if start + 3800 >= len(text) else None)


def voice_message(chat, voice):
    if voice.get('duration', 0) > 180 or voice.get('file_size', 0) > speech.MAX_AUDIO_BYTES:
        raise ValueError('Отправьте голосовое до 3 минут и 5 МБ или напишите задачу текстом.')
    say(chat, 'Распознаю голосовое на нашем компьютере… Аудио не отправляется в DeepSeek или ProxyAPI.')
    info = tg('getFile', {'file_id': voice['file_id']})
    path = info.get('file_path')
    if not isinstance(path, str) or not path:
        raise ValueError('Telegram не вернул голосовое. Попробуйте отправить его снова.')
    url = f'https://api.telegram.org/file/bot{os.environ["TELEGRAM_BOT_TOKEN"]}/' + path.lstrip('/')
    try:
        with app.urllib.request.urlopen(url, timeout=30) as response:
            audio = response.read(speech.MAX_AUDIO_BYTES + 1)
    except Exception:
        raise ValueError('Не удалось скачать голосовое. Напишите задачу текстом или попробуйте ещё раз.') from None
    text = speech.transcribe(audio)
    previous = context(chat)
    if previous.get('mode') == 'voice':
        previous = previous['previous']
    nonce = secrets.token_hex(4)
    set_context(chat, {'mode': 'voice', 'text': text, 'previous': previous, 'nonce': nonce})
    for start in range(0, len(text), 3000):
        say(chat, ('Расшифровка\n\n' if start == 0 else '') + text[start:start + 3000])
    say(chat, 'Правильно распознал? Проверьте даты, имена и названия.', inline=[[btn('✅ Использовать', f'speech:use:{nonce}'), btn('✏️ Исправить', f'speech:edit:{nonce}')], [btn('✕ Отмена', f'speech:cancel:{nonce}')]])


def handle(update):
    query = update.get('callback_query')
    msg = query.get('message', {}) if query else update.get('message', {})
    sender = query.get('from', {}) if query else msg.get('from', {})
    chat = msg.get('chat', {})
    if chat.get('type') != 'private':
        return
    if str(sender.get('id')) not in allowed_user_ids():
        if query:
            tg('answerCallbackQuery', {'callback_query_id': query['id'], 'text': 'Нет доступа'})
        else:
            say(chat['id'], f'Бот пока доступен владельцу проекта. Ваш Telegram ID: {sender.get("id")}. Владелец может добавить его в TELEGRAM_OWNER_ID в .env.')
        return
    try:
        if query:
            if not update.get('_callback_answered'):
                try:
                    tg('answerCallbackQuery', {'callback_query_id': query['id']})
                except ValueError:
                    pass
            callback(chat['id'], query.get('data', ''))
        elif isinstance(msg.get('text'), str):
            message(chat['id'], msg['text'].strip())
        elif msg.get('voice'):
            voice_message(chat['id'], msg['voice'])
        else:
            say(chat['id'], 'Пока принимаю текстовые ответы. Документы и изображения добавим следующим этапом.')
    except ValueError as error:
        pending = context(chat['id'])
        buttons = [[btn('↻ Повторить', 'retry'), btn('✕ Отменить задачу', 'task_cancel')]] if pending.get('mode') == 'task' else None
        say(chat['id'], str(error), inline=buttons)
    except Exception:
        say(chat['id'], 'Не удалось выполнить запрос. Проверьте ключи и подключение. Сохранённые посты доступны в «Мои посты».')


def enqueue(update):
    query = update.get('callback_query')
    msg = query.get('message', {}) if query else update.get('message', {})
    chat = msg.get('chat', {}).get('id', 0)
    with app.db() as con:
        con.execute('INSERT OR IGNORE INTO bot_inbox(id,chat,payload) VALUES(?,?,?)', (update['update_id'], chat, json.dumps(update, ensure_ascii=False)))
        con.execute('INSERT OR REPLACE INTO bot_meta VALUES("offset",?)', (update['update_id'] + 1,))


def consume_one(chat):
    with app.db() as con:
        row = con.execute('SELECT * FROM bot_inbox WHERE chat=? AND status="queued" ORDER BY id LIMIT 1', (chat,)).fetchone()
        if not row:
            return False
        con.execute('UPDATE bot_inbox SET status="running" WHERE id=?', (row['id'],))
    status = 'done'
    try:
        handle(json.loads(row['payload']))
    except Exception:
        # Delivery may already have happened. Never replay this event automatically.
        status = 'failed'
        print('An incoming task failed. No automatic replay; check saved posts.')
    with app.db() as con:
        con.execute('UPDATE bot_inbox SET status=? WHERE id=?', (status, row['id']))
    return True


def worker(chat, stop):
    while not stop.is_set():
        try:
            if not consume_one(chat):
                stop.wait(0.3)
        except Exception:
            print('Local queue error. Retrying; credentials not logged.')
            stop.wait(1)


def main():
    if not os.environ.get('TELEGRAM_BOT_TOKEN'):
        print('Заполните TELEGRAM_BOT_TOKEN в .env. Инструкция: TELEGRAM.md')
        return
    init_db()
    print('MarketPilot Telegram bot started. Keep this window open. Ctrl+C to stop.')
    # Do not delete an existing webhook silently: a token must belong to this deployment.
    try:
        webhook = tg('getWebhookInfo', {})
    except ValueError as error:
        print(error)
        return
    if webhook.get('url'):
        print('У бота настроен webhook. Используйте отдельного тестового бота без webhook.')
        return
    with app.db() as con:
        row = con.execute('SELECT value FROM bot_meta WHERE key="offset"').fetchone()
    offset = row['value'] if row else 0
    stop = threading.Event()
    for owner in allowed_user_ids():
        threading.Thread(target=worker, args=(int(owner), stop), daemon=True).start()
    while True:
        try:
            updates = tg('getUpdates', {'offset': offset, 'timeout': 25, 'allowed_updates': ['message', 'callback_query']})
            for update in updates:
                query = update.get('callback_query')
                msg = query.get('message', {}) if query else update.get('message', {})
                sender = query.get('from', {}) if query else msg.get('from', {})
                if str(sender.get('id')) in allowed_user_ids() and msg.get('chat', {}).get('type') == 'private':
                    if query:
                        try:
                            tg('answerCallbackQuery', {'callback_query_id': query['id']})
                            update['_callback_answered'] = True
                        except ValueError:
                            pass
                    enqueue(update)
                else:
                    handle(update)
                    with app.db() as con:
                        con.execute('INSERT OR REPLACE INTO bot_meta VALUES("offset",?)', (update['update_id'] + 1,))
                offset = update['update_id'] + 1
        except KeyboardInterrupt:
            stop.set()
            break
        except ValueError as error:
            print(error)
            if 'Конфликт Telegram' in str(error) or 'TELEGRAM_BOT_TOKEN' in str(error):
                stop.set()
                break
            time.sleep(5)
        except Exception:
            print('Telegram connection error. Retrying in 5 seconds. No tokens logged.')
            time.sleep(5)


if __name__ == '__main__':
    main()
