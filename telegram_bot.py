"""Telegram-first local prototype. Start with: python telegram_bot.py."""
import json
import os
import re
import secrets
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

import app
import speech
import post_format
import editorial
import telegram_screen
import bot_stages
import company_knowledge
import bot_features
from html import escape

QUESTIONS = [
    ('company', 'Компания', 'Название компании и чем занимаетесь?\nСайт — по желанию.'),
    ('audience', 'Аудитория', 'Для кого будем писать?', ['Для сотрудников', 'Для клиентов', 'Для партнёров']),
    ('objective', 'Задача', 'Что хотите упростить?', ['Быстрее писать посты', 'Регулярно вести канал', 'Превращать интервью в посты', 'Рассказывать о мероприятиях']),
    ('style', 'Стиль', 'Какой стиль? Выберите или напишите свой.', ['Дружелюбно и просто', 'Сдержанно и по делу', 'Экспертно и полезно', 'Легко, с юмором']),
    ('limits', 'Ограничения', 'Какие есть ограничения?\nНапример: «На вы, без сравнений с конкурентами».'),
]
MENU = [['✨ Новый пост', '🗂 Мои посты'], ['🏢 Профиль', '❔ Помощь']]
_ACK_POOL = ThreadPoolExecutor(max_workers=4)
_WAKE = {}
_BUSY = set()
_BUSY_LOCK = threading.Lock()


def loading(chat, label):
    with telegram_screen.chat_lock(chat):
        stage_header(chat, None)
    options={}
    if any(word in label.lower() for word in ('изображ','облож','макет')):
        import random,premium_emoji
        phases=['Собираю визуальную композицию','Работаю над оформлением','Создаю изображение по теме поста','Готовлю визуал для публикации','Продолжаю работу над макетом']
        random.shuffle(phases)
        # Verified animated corporate emoji, not a static refresh glyph.
        glyph=premium_emoji.render_private('💎',chat)
        options={'renderer':lambda frame: '<b>'+escape(label)+'</b>\n\n'+glyph+' '+phases[frame%len(phases)]+'…', 'interval':3,'action':'upload_photo'}
    return telegram_screen.Loading(chat, label, tg, background_api=lambda method, payload: tg(method, payload, timeout=3),**options)


def is_busy(chat):
    with _BUSY_LOCK:
        return chat in _BUSY


def clarification_screen(chat, question):
    if 'цитат' in question.lower():
        return say(chat, 'Подготовить пост без цитат?', inline=[[btn('Без цитат', 'without_quotes'), btn('↻ Повторить', 'retry')], [btn('✕ Отмена', 'task_cancel')]], stage='facts')
    return say(chat, question, inline=[[btn('✕ Отмена', 'task_cancel')]], stage='facts')


def btn(text, data, style=None):
    text = re.sub(r'^[\s✨🗂🏢❔⚙️✏🗑📤🕘📝✅⌂✓✕↻]+', '', text)
    if data == 'home':
        text = 'В меню'
    if data == 'new' or data.startswith('plan_draft:'):
        text, style = 'Создать пост', 'success'
    if data=='tg_app':
        from urllib.parse import urlsplit
        url=os.environ.get('MINI_APP_URL','').strip()
        parsed=urlsplit(url)
        if parsed.scheme=='https' and parsed.hostname and not parsed.username and not parsed.password:
            return {'text':text,'web_app':{'url':url},'style':'primary'}
    value = {'text': text, 'callback_data': data}
    if style:
        value['style'] = style
    return value


def context(chat):
    with app.db() as con:
        row = con.execute('SELECT data FROM bot_context WHERE chat=?', (chat,)).fetchone()
    return json.loads(row['data']) if row else {}


def set_context(chat, value):
    with app.db() as con:
        con.execute('INSERT OR REPLACE INTO bot_context VALUES(?,?)', (chat, json.dumps(value, ensure_ascii=False)))


def focus_post(chat, post=None):
    with app.db() as con:
        con.execute('DELETE FROM bot_post_focus WHERE chat=?', (chat,))
        if post and post['status'] in ('draft', 'approved'):
            con.execute('INSERT INTO bot_post_focus VALUES(?,?,?)', (chat, post['id'], post['rev']))


def focused_post(chat):
    with app.db() as con:
        return con.execute('SELECT p.* FROM bot_post_focus f JOIN bot_posts p ON p.id=f.post AND p.chat=f.chat AND p.rev=f.rev WHERE f.chat=? AND p.status IN ("draft","approved")', (chat,)).fetchone()


def allowed_user_ids():
    return __import__('user_access').allowed_ids()


def publication_channel(chat):
    return os.environ.get('TELEGRAM_CHANNEL_ID', '').strip() if str(chat) in allowed_user_ids() else ''


def activate_bot(bot_id):
    """Updates and message IDs belong to one Telegram bot; business data stays."""
    with app.db() as con:
        previous = con.execute('SELECT value FROM bot_meta WHERE key="active_bot"').fetchone()
        if not previous or previous['value'] != bot_id:
            con.execute('CREATE TABLE IF NOT EXISTS bot_inbox_archive (bot INTEGER, id INTEGER, chat INTEGER, payload TEXT, status TEXT)')
            con.execute('INSERT INTO bot_inbox_archive SELECT ?,id,chat,payload,status FROM bot_inbox', (previous['value'] if previous else 0,))
            con.execute('DELETE FROM bot_inbox')
            con.execute('DELETE FROM bot_screens')
            con.execute('DELETE FROM bot_stage_screens')
            con.execute('DELETE FROM bot_confirmations')
            con.execute('DELETE FROM bot_meta WHERE key="offset"')
            con.execute('INSERT OR REPLACE INTO bot_meta VALUES("active_bot",?)', (bot_id,))


def init_db():
    with app.db() as con:
        telegram_screen.init_db(con)
        __import__('user_access').init_db(con)
        bot_stages.init_db(con)
        company_knowledge.init_db(con)
        __import__('marketer').init_db(con)
        bot_features.init_db(con)
        con.execute('CREATE TABLE IF NOT EXISTS bot_list_positions (chat INTEGER PRIMARY KEY, page INTEGER)')
        con.execute('CREATE TABLE IF NOT EXISTS bot_post_focus (chat INTEGER PRIMARY KEY, post INTEGER, rev INTEGER)')
        con.execute('CREATE TABLE IF NOT EXISTS bot_sessions (chat INTEGER PRIMARY KEY, step INTEGER, answers TEXT, editing INTEGER)')
        con.execute('CREATE TABLE IF NOT EXISTS bot_posts (id INTEGER PRIMARY KEY, chat INTEGER, topic TEXT, body TEXT, image_prompt TEXT, source TEXT, status TEXT DEFAULT "draft", rev INTEGER DEFAULT 1, message_id TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS bot_meta (key TEXT PRIMARY KEY, value INTEGER)')
        con.execute('CREATE TABLE IF NOT EXISTS bot_context (chat INTEGER PRIMARY KEY, data TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS bot_confirmations (post INTEGER PRIMARY KEY, chat INTEGER, rev INTEGER, channel TEXT, nonce TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS bot_inbox (id INTEGER PRIMARY KEY, chat INTEGER, payload TEXT, status TEXT DEFAULT "queued")')
        con.execute('CREATE TABLE IF NOT EXISTS bot_versions (post INTEGER, rev INTEGER, body TEXT, instruction TEXT, kind TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(post,rev))')
        con.execute('CREATE TABLE IF NOT EXISTS bot_post_context (post INTEGER PRIMARY KEY, profile TEXT, task TEXT, clarification TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS bot_post_review (post INTEGER PRIMARY KEY, warnings TEXT, brand_name_mode TEXT, publication_date TEXT)')
        if 'fact_blocks' not in {row['name'] for row in con.execute('PRAGMA table_info(bot_post_review)')}:
            con.execute("ALTER TABLE bot_post_review ADD COLUMN fact_blocks TEXT NOT NULL DEFAULT '[]'")
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
        con.execute('CREATE INDEX IF NOT EXISTS bot_posts_chat_id ON bot_posts(chat,id)')
        con.execute('CREATE INDEX IF NOT EXISTS bot_inbox_chat_status ON bot_inbox(chat,status,id)')


class TelegramAPIError(ValueError):
    def __init__(self, message, reason='other'):
        super().__init__(message)
        self.reason = reason


class TelegramConnectionError(ValueError):
    """Temporary transport failure; safe to retry read-only startup checks."""


def tg(method, payload, timeout=None):
    token = os.environ['TELEGRAM_BOT_TOKEN']
    try:
        url = f'https://api.telegram.org/bot{token}/{method}'
        if '_document_path' in payload:
            values=dict(payload);path=values.pop('_document_path')
            result=app.remote_photo(url,values,path,timeout=timeout or 20,field='document')
        elif '_photo_path' in payload:
            values = dict(payload)
            path = values.pop('_photo_path')
            result = app.remote_photo(url, values, path, timeout=timeout or 20)
        else:
            result = app.remote_json(url, payload, timeout=timeout or (35 if method == 'getUpdates' else 12))
    except urllib.error.HTTPError as error:
        status = error.code
        reason = 'other'
        description=''
        try:
            description = str(json.loads(error.read(10000)).get('description', '')).lower()
            if 'message is not modified' in description:
                reason = 'not_modified'
            elif any(value in description for value in ('message to edit not found', "message can't be edited", 'message can not be edited')):
                reason = 'unavailable'
            elif "can't parse entities" in description or 'unsupported start tag' in description:
                reason = 'formatting'
            elif 'button_data_invalid' in description:
                reason = 'button'
            elif any(value in description for value in ('chat not found','user not found','user_id_invalid')):
                reason = 'chat_not_found'
        except Exception:
            pass
        error.close()
        if status==400 and 'emoji' in description and '<tg-emoji' in json.dumps(payload,ensure_ascii=False):
            import premium_emoji
            fallback=dict(payload)
            for field in ('text','caption'):
                if isinstance(fallback.get(field),str):fallback[field]=premium_emoji.remove_emoji(fallback[field])
            if isinstance(fallback.get('media'),dict):
                fallback['media']=dict(fallback['media'])
                if isinstance(fallback['media'].get('caption'),str):fallback['media']['caption']=premium_emoji.remove_emoji(fallback['media']['caption'])
            if fallback!=payload:return tg(method,fallback,timeout=timeout)
        messages = {401: 'Telegram не принял TELEGRAM_BOT_TOKEN. Проверьте токен от BotFather.',
                    409: 'Конфликт Telegram: остановите второй экземпляр бота с этим токеном.',
                    403: 'Telegram запретил действие. Проверьте доступ бота к чату и права публикации.',
                    400: 'Telegram отклонил действие. Проверьте ID канала и формат сообщения.'}
        message = messages.get(status, f'Ошибка Telegram HTTP {status}. Попробуйте позже.')
        if status == 400:
            if reason == 'unavailable':
                message = 'Telegram не может обновить старый экран. Создаю новое рабочее сообщение.'
            elif reason == 'formatting':
                message = 'Telegram не принял оформление текста. Черновик сохранён; требуется исправить разметку.'
            elif reason == 'button':
                message = 'Telegram не принял кнопку интерфейса. Вернитесь в меню через /start.'
            elif reason == 'chat_not_found':
                message = 'Telegram не нашёл чат. Проверьте ID канала и добавьте в него бота.'
            elif method.startswith('editMessage'):
                message = 'Telegram отклонил обновление рабочего экрана. Попробуйте /start.'
        print(f'Telegram API: {method}, HTTP {status}, reason={reason}')
        raise TelegramAPIError(message, reason) from None
    except (urllib.error.URLError, TimeoutError):
        raise TelegramConnectionError('Нет соединения с Telegram. Проверьте интернет и доступ к api.telegram.org.') from None
    if not result.get('ok'):
        raise RuntimeError('Telegram отклонил запрос')
    return result['result']


def stage_header(chat, stage):
    try:
        bot_stages.show(chat, stage, tg)
    except Exception:
        print('Stage banner unavailable; text interface remains usable.')


def say(chat, text, options=None, inline=None, formatted=False, stage=None, media=''):
    if formatted:
        import premium_emoji
        text=premium_emoji.render_private(text,chat)
    buttons = inline if inline is not None else [[btn('⌂ В меню', 'home')]]
    with telegram_screen.chat_lock(chat):
        stage_header(chat, None)
        path = app.ROOT / 'assets' / 'stages' / (str(stage) + '.png')
        # Decorative banners must not shorten a full draft to a photo caption.
        picture = media or (str(path) if stage and path.is_file() and post_format.length(text)<=950 else '')
        return telegram_screen.show(chat, text, buttons, formatted, tg, media=picture)


def session(chat):
    with app.db() as con:
        row = con.execute('SELECT * FROM bot_sessions WHERE chat=?', (chat,)).fetchone()
    return dict(row) if row else {'chat': chat, 'step': 0, 'answers': '{}', 'editing': None}


def save(state):
    with app.db() as con:
        con.execute('INSERT OR REPLACE INTO bot_sessions VALUES(?,?,?,?)', (state['chat'], state['step'], state['answers'], state['editing']))


def brief(state, *, include_documents=True):
    answers = json.loads(state['answers'])
    text = '\n\n'.join(label + ': ' + answers.get(key, 'Не указано') for key, label, *_ in QUESTIONS)
    site = company_site(state)
    if site:
        text += '\n\nПодтверждённый сайт компании: ' + site
    knowledge = company_knowledge.get(state['chat'])
    if knowledge and knowledge['url'] == site and knowledge['summary']:
        text += '\n\nСправка по прочитанному сайту (фоновые сведения, не программа текущего события):\n' + knowledge['summary']
    import company_documents
    documents=company_documents.context(state['chat']) if include_documents else ''
    if documents:text+='\n\nДокументы компании (фоновые сведения, не факты нового события):\n'+documents
    return text


def company_site(state):
    answers = json.loads(state['answers'])
    return answers.get('site') or company_knowledge.extract_url(answers.get('company', ''))


def study_company(chat, refresh=False):
    site = company_site(session(chat))
    if not site:
        navigation(chat, 'company_site')
        return False
    with loading(chat, 'Изучаю компанию') as wait:
        company_knowledge.study(chat, site, refresh=refresh)
    return wait.visible


def edit_brand_rules(state):
    answers = json.loads(state['answers'])
    text = '\n'.join(label + ': ' + str(answers[key])[:1000] for key, label in
                     [('audience', 'Аудитория'), ('style', 'Стиль'), ('limits', 'Ограничения')]
                     if answers.get(key))
    site = company_site(state)
    if site:
        text += '\nПодтверждённый сайт компании: ' + site
    knowledge = company_knowledge.get(state['chat'])
    if knowledge and knowledge['url'] == site and knowledge['summary']:
        text += '\nО компании: ' + knowledge['summary'][:900]
    return text


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
    say(state['chat'], f'{state["step"] + 1} / {len(QUESTIONS)}\n\n{question[2]}', inline=buttons or [[btn('Пример', 'intro_help')]])


def show_post(chat, post_id):
    with app.db() as con:
        post = con.execute('SELECT * FROM bot_posts WHERE id=? AND chat=?', (post_id, chat)).fetchone()
    if not post:
        raise ValueError('Пост не найден')
    focus_post(chat, post)
    review = review_metadata(post_id)
    buttons = []
    def button(title, command):
        return btn(title, f'{command}:{post_id}:{post["rev"]}')
    if post['status'] in ('draft', 'approved'):
        buttons = [[button('Изменить текст', 'edit'), button('🗑 Отменить', 'cancel')], [{**button('📤 Отправить', 'send'), 'style': 'primary'}]]
    elif post['status'] == 'cancelled':
        buttons = [[button('↩️ Восстановить', 'restore')]]
    if post['status'] in ('draft','approved'):
        with app.db() as con:
            delivery=con.execute('SELECT * FROM bot_delivery_schedule WHERE post=?',(post_id,)).fetchone()
        if delivery and delivery['state']=='queued' and delivery['rev']==post['rev']:
            buttons.append([button('Снять с расписания','unschedule')])
        else:buttons.append([button('Согласовать и запланировать','schedule')])
    if session(chat)['editing'] == post_id:
        buttons.append([btn('✓ Готово', 'stop_edit')])
    if review['warnings']:
        buttons.append([button(f'Заметки ({len(review["warnings"])})', 'notes')])
    buttons.append([button('🕘 История правок', 'history'), btn('← К списку', 'posts')])
    if post['status'] in ('draft', 'approved'):
        buttons.append([button('Изменить изображение','feat_art')])
        buttons.append([btn('Прикрепить фото', 'feat_photo_help'), btn('Убрать фото', f'feat_image_remove:{post_id}:{post["rev"]}')])
    if post['status'] not in ('publishing','delivery_unknown'):
        buttons.append([btn('Удалить из моих постов', f'feat_delete:{post_id}:{post["rev"]}')])
    if post['status'] in ('draft','approved','published') and __import__('vk_publish').configured(chat):
        vk=__import__('vk_publish').status(chat,post_id)
        if vk['state']=='sent':buttons.append([{'text':'Открыть пост в ВК','url':vk['url']}])
        else:buttons.append([button('ВК · только текст','vk_preview')])
    body = post_format.normalize(post['body'])
    stage = 'published' if post['status'] == 'published' else ('edit' if session(chat)['editing'] == post_id else 'draft')
    return say(chat, body, inline=buttons, formatted=True, stage=stage, media=bot_features.image_for(post_id))


def post_memory(chat, post_id):
    with app.db() as con:
        history = [dict(row) for row in con.execute('SELECT v.rev AS revision,v.body,v.instruction,v.kind FROM bot_versions v JOIN bot_posts p ON p.id=v.post WHERE v.post=? AND p.chat=? ORDER BY v.rev', (post_id, chat))]
        row = con.execute('SELECT c.* FROM bot_post_context c JOIN bot_posts p ON p.id=c.post WHERE c.post=? AND p.chat=?', (post_id, chat)).fetchone()
    return history, dict(row) if row else {}


def remember_version(con, post_id, revision, body, instruction='', kind='initial'):
    con.execute('INSERT OR IGNORE INTO bot_versions(post,rev,body,instruction,kind) VALUES(?,?,?,?,?)', (post_id, revision, body, instruction, kind))


def review_metadata(post_id):
    with app.db() as con:
        row = con.execute('SELECT * FROM bot_post_review WHERE post=?', (post_id,)).fetchone()
    return {'warnings': json.loads(row['warnings']), 'brand_name_mode': row['brand_name_mode'], 'publication_date': row['publication_date'], 'fact_blocks': json.loads(row['fact_blocks'])} if row else {'warnings': [], 'brand_name_mode': editorial.brand_mode(), 'publication_date': None, 'fact_blocks': []}


def list_posts(chat, page=None):
    with app.db() as con:
        count = con.execute('SELECT COUNT(*) FROM bot_posts WHERE chat=?', (chat,)).fetchone()[0]
        saved = con.execute('SELECT page FROM bot_list_positions WHERE chat=?', (chat,)).fetchone()
        pages = max(1, (count + 5) // 6)
        page = min(max(0, int(page if page is not None else (saved['page'] if saved else 0))), pages - 1)
        posts = con.execute('SELECT * FROM bot_posts WHERE chat=? ORDER BY id DESC LIMIT 6 OFFSET ?', (chat, page * 6)).fetchall()
        con.execute('INSERT OR REPLACE INTO bot_list_positions VALUES(?,?)', (chat, page))
    if not posts:
        return say(chat, 'Пока пусто.', inline=[[btn('✨ Создать пост', 'new')]])
    buttons = [[btn(f'№{p["id"]} · {p["topic"][:40]}', f'view:{p["id"]}:{p["rev"]}')] for p in posts]
    nav = []
    if page:
        nav.append(btn('← Назад', f'posts_page:{page - 1}'))
    if page + 1 < pages:
        nav.append(btn('Далее →', f'posts_page:{page + 1}'))
    if nav:
        buttons.append(nav)
    buttons.append([btn('✨ Новый пост', 'new'), btn('⌂ В меню', 'home')])
    return say(chat, f'Мои посты · {page + 1}/{pages}\nВыберите публикацию', inline=buttons)


def preview(chat, post):
    if post_format.length(post['body']) > editorial.MAX_TELEGRAM_UNITS:
        raise ValueError('Черновик сохранён, но превышает предел одного сообщения Telegram (4096 символов). Сократите или разделите его перед отправкой.')
    channel = publication_channel(chat)
    if not channel:
        return say(chat, 'Черновик сохранён. Можно скопировать текст в свой канал. Отправка в канал команды доступна администраторам.', inline=[[btn('← К посту', f'view:{post["id"]}:{post["rev"]}')]])
    destination = tg('getChat', {'chat_id': channel})
    nonce = secrets.token_hex(5)
    with app.db() as con:
        con.execute('INSERT OR REPLACE INTO bot_confirmations VALUES(?,?,?,?,?)', (post['id'], chat, post['rev'], channel, nonce))
    if not bot_features.preferences(chat)['confirm_publish']:
        return callback(chat, f'confirm:{post["id"]}:{post["rev"]}:{nonce}')
    heading = f'Отправить в «{destination.get("title", channel)}»?\n{channel}'
    if bot_features.image_for(post['id']) and post_format.length(post['body']) > 1000:
        heading += '\nФото с началом поста и продолжение отдельным сообщением.'
    notes = review_metadata(post['id'])['warnings']
    if notes:
        heading += '\n\nПроверить редактору:\n' + '\n'.join('- ' + note for note in notes)
    say(chat, escape(heading) + '\n\n' + post_format.normalize(post['body']), inline=[[btn('✅ Подтвердить отправку', f'confirm:{post["id"]}:{post["rev"]}:{nonce}')], [btn('← Назад к посту', f'view:{post["id"]}:{post["rev"]}')]], formatted=True, stage='review', media=bot_features.image_for(post['id']))


def callback(chat, data):
    if data.startswith(('vk_preview:', 'vk_confirm:')):return __import__('vk_publish').callback(chat,data)
    if data=='project_info':return project_handoff(chat)
    if data=='marketer':return __import__('marketer').menu(chat)
    if data=='knowledge':return __import__('marketer').documents_menu(chat)
    if data.startswith('knowledge_delete:'):
        __import__('company_documents').delete(chat,int(data.split(':')[1]))
        return __import__('marketer').documents_menu(chat)
    if context(chat).get('mode')=='emoji_palette' and not data.startswith('feat_emoji'):
        set_context(chat,context(chat).get('previous',{}))
    if context(chat).get('mode')=='schedule' and (data.startswith('view:') or data=='home'):set_context(chat,{})
    if data.startswith(('schedule:', 'unschedule:')):
        import scheduling
        command,pid,rev=data.split(':');pid,rev=int(pid),int(rev)
        if command=='unschedule':
            scheduling.cancel(chat,pid,rev);return show_post(chat,pid)
        with app.db() as con:
            p=con.execute('SELECT * FROM bot_posts WHERE id=? AND chat=?',(pid,chat)).fetchone()
        if not p or p['rev']!=rev or p['status'] not in ('draft','approved'):raise ValueError('Откройте актуальный черновик.')
        set_context(chat,{'mode':'schedule','post':pid,'rev':rev})
        return say(chat,'Согласовать пост и отправить по времени? Пришлите дату и время по Уфе (UTC+5), например: 15.11.2026 18:30. Отправка даты подтвердит публикацию.',inline=[[btn('Не планировать',f'view:{pid}:{rev}')]])
    if data.startswith('posts_page:'):
        value = data.split(':', 1)[1]
        if not value.isdecimal() or len(value) > 8:
            raise ValueError('Откройте список постов заново.')
        return list_posts(chat, int(value))
    if data == 'feat_photo_help':
        post = focused_post(chat)
        if not post:
            raise ValueError('Сначала откройте черновик.')
        return say(chat, 'Пришлите фото обычным сообщением. Оно прикрепится к открытому черновику.', inline=[[btn('← К посту', f'view:{post["id"]}:{post["rev"]}')]])
    if data.startswith('feat_'):
        return bot_features.callback(chat, data)
    if data.startswith('plan_'):
        return plan_callback(chat, data)
    if data == 'tg_app':
        return  # Placeholder: acknowledgment only, no navigation or state changes.
    if data in ('settings', 'company_reset', 'company_site', 'company_site_cancel', 'company_study', 'profile_skip') or data.startswith('company_reset_confirm:'):
        return navigation(chat, data)
    if not data.startswith(('confirm:', 'page:')):
        with app.db() as con:
            con.execute('DELETE FROM bot_confirmations WHERE chat=?', (chat,))
    if data.startswith('page:'):
        return telegram_screen.turn_page(chat, data, tg)
    if data.startswith('speech:'):
        _, action, nonce = data.split(':')
        pending = context(chat)
        if pending.get('mode') != 'voice' or pending.get('nonce') != nonce:
            raise ValueError('Эта расшифровка уже обработана. Используйте последнее сообщение.')
        return navigation(chat, 'voice_' + action)
    if data in ('home', 'posts', 'new', 'profile', 'help', 'profile_edit', 'profile_ok', 'stop_edit', 'retry', 'task_cancel', 'intro_help', 'voice_use', 'voice_edit', 'voice_cancel', 'voice_show', 'continue_task', 'without_quotes') or data.startswith(('answer:', 'back:', 'skip:')):
        return navigation(chat, data)
    parts = data.split(':')
    if len(parts) not in (3, 4):
        raise ValueError('Кнопка устарела. Откройте меню через /start.')
    command, post_id, revision = parts[:3]
    with app.db() as con:
        post = con.execute('SELECT * FROM bot_posts WHERE id=? AND chat=?', (int(post_id), chat)).fetchone()
        if not post or post['rev'] != int(revision):
            raise ValueError('Это старая версия поста. Откройте «Мои посты».')
        if command == 'notes':
            notes = review_metadata(post['id'])['warnings']
            return say(chat, 'Заметки\n\n' + '\n'.join('- ' + note for note in notes), inline=[[btn('← К посту', f'view:{post["id"]}:{post["rev"]}')]])
        if command == 'history':
            history, origin = post_memory(chat, post['id'])
            lines = [f'История поста №{post["id"]}']
            if origin.get('task'):
                lines.append('Исходная задача: ' + origin['task'])
            for version in history:
                lines.append(f'Версия {version["revision"]}: ' + (version['instruction'] or 'Исходный текст'))
            text = '\n\n'.join(lines)
            return say(chat, text, inline=[[btn('← К посту', f'view:{post["id"]}:{post["rev"]}')]])
        if command == 'view':
            con.execute('DELETE FROM bot_confirmations WHERE post=?', (post['id'],))
            con.commit()
            return show_post(chat, post['id'])
        if command in ('edit', 'replace'):
            if post['status'] not in ('draft', 'approved'):
                raise ValueError('Этот пост уже нельзя изменить.')
            state = session(chat)
            previous = context(chat)
            memory = previous.get('memory', '') if state['editing'] == post['id'] and previous.get('rev') == post['rev'] else ''
            state['editing'] = post['id']
            save(state)
            set_context(chat, {'mode': command, 'rev': post['rev'], 'awaiting': True, 'memory': memory})
            remember_version(con, post['id'], post['rev'], post['body'])
            con.execute('DELETE FROM bot_confirmations WHERE post=?', (post['id'],))
            con.commit()
            say(chat, 'Пришлите новый текст.' if command == 'replace' else 'Что изменить?\nНапример: «Короче и на вы».', inline=([[btn('📝 Свой текст', f'replace:{post["id"]}:{post["rev"]}')]] if command == 'edit' else []) + [[btn('← Назад', 'stop_edit')]], stage='edit')
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
            if not approval or len(parts) != 4 or approval['nonce'] != parts[3] or approval['rev'] != post['rev'] or approval['channel'] != publication_channel(chat):
                raise ValueError('Подтверждение устарело. Снова нажмите «Отправить» у актуального поста.')
            channel = approval['channel']
            if post_format.length(post['body']) > editorial.MAX_TELEGRAM_UNITS:
                raise ValueError('Текст превышает предел одного сообщения Telegram. Сократите его перед отправкой.')
            con.execute('DELETE FROM bot_confirmations WHERE post=?', (post['id'],))
            changed=con.execute('UPDATE bot_posts SET status="publishing" WHERE id=? AND rev=? AND status IN ("draft","approved")', (post['id'],post['rev'])).rowcount
            if not changed:raise ValueError('Отправка уже началась. Повтор запрещён.')
            con.commit()
            try:
                image = bot_features.image_for(post['id'])
                if image:
                    import premium_emoji
                    pages = post_format.split_pages(premium_emoji.render_publication(post['body'],chat,channel), limit=1000, formatted=True)
                    result = tg('sendPhoto', {'chat_id': channel, **__import__('post_images').payload(image), 'caption': pages[0], 'parse_mode': 'HTML'})
                    for page in pages[1:]:
                        tg('sendMessage', {'chat_id': channel, 'text': page, 'parse_mode': 'HTML'})
                else:
                    import premium_emoji
                    result = tg('sendMessage', {'chat_id': channel, 'text': premium_emoji.render_publication(post['body'],chat,channel), 'parse_mode': 'HTML'})
            except Exception:
                con.execute('UPDATE bot_posts SET status="delivery_unknown" WHERE id=?', (post['id'],))
                con.commit()
                raise ValueError('Доставка не подтверждена. Проверьте канал вручную. Автоматического повтора не будет.')
            con.execute('UPDATE bot_posts SET status="published", message_id=? WHERE id=?', (str(result['message_id']), post['id']))
        else:
            raise ValueError('Неизвестное действие')
    show_post(chat, post['id'])


def home(chat):
    if context(chat).get('mode')=='marketer':set_context(chat,{})
    focus_post(chat)
    rows = [[btn('Создать пост', 'new')],
            [btn('Мои посты', 'posts'), btn('Контент-план', 'feat_plan')],
            [btn('Маркетолог', 'marketer'), btn('Документы', 'knowledge')],
            [btn('Компания', 'profile'), btn('Настройки', 'settings')]]
    if context(chat).get('mode') in ('task', 'planning', 'plan_retry') or context(chat).get('retry_instruction'):
        if not is_busy(chat):
            rows.insert(0, [btn('↻ Повторить задачу', 'retry')])
    if context(chat).get('mode') == 'clarify':
        rows.insert(0, [btn('Продолжить задачу', 'continue_task')])
    if context(chat).get('mode') == 'voice':
        rows.insert(0, [btn('Голосовое готово', 'voice_show')])
    if context(chat).get('mode') in ('plan_facts', 'plan_ideas', 'plan_clarify', 'plan_correct'):
        rows.insert(1, [btn('Продолжить публикацию', 'plan_resume')])
    text = ('<b>Ваш AI-редактор</b>\n\n'
            'Превратим идею в публикацию. Расскажите о событии текстом или голосом, добавьте своё фото.\n\n'
            '<b>Посты</b> · тексты, оформление и правки\n'
            '<b>Контент-план</b> · темы на нужный период\n'
            '<b>Маркетолог</b> · идеи, память и контент-план\n'
            '<b>Документы</b> · знания компании из файлов и сайта\n\n'
            'Режим: <b>' + ('Быстрый' if bot_features.preferences(chat)['fast'] else 'Подробный') + '</b>')
    import model_selection
    text+='\nМодель: <b>'+escape(model_selection.title(model_selection.model_for(chat)))+'</b>'
    if is_busy(chat):
        text += '\n\nЗадача в работе.'
    say(chat, text, inline=rows, formatted=True, stage='home')


def navigation(chat, data):
    state = session(chat)
    pending = context(chat)
    if data == 'company_site_cancel':
        if pending.get('mode') == 'company_site':
            set_context(chat, pending.get('previous', {}))
        return show_brief(state) if state['step'] == len(QUESTIONS) else home(chat)
    if data == 'company_site':
        if state['editing']:
            raise ValueError('Сначала завершите правки поста, затем измените сайт компании.')
        set_context(chat, {'mode': 'company_site', 'previous': pending})
        return say(chat, 'Пришлите сайт компании. Я прочитаю доступные страницы и сохраню краткую справку.', inline=[[btn('← Не менять', 'company_site_cancel')]])
    if data == 'company_study':
        if study_company(chat, refresh=True):
            return show_brief(session(chat))
        return
    if data == 'profile_skip':
        set_context(chat, {})
        return home(chat)
    if data == 'settings':
        if 'reset_nonce' in pending:
            pending.pop('reset_nonce')
            set_context(chat, pending)
        return bot_features.settings(chat)
    if data == 'company_reset':
        if state['editing']:
            return say(chat, 'Сначала завершите правки поста.', inline=[[btn('← К правкам', 'stop_edit')]])
        nonce = secrets.token_hex(5)
        set_context(chat, {**pending, 'reset_nonce': nonce})
        return say(chat, 'Сбросить компанию?\nАнкета, документы, память маркетолога и текущая задача будут очищены. Посты останутся.',
                   inline=[[btn('Да, сбросить', 'company_reset_confirm:' + nonce, style='danger')], [btn('← Не сбрасывать', 'settings')]])
    if data.startswith('company_reset_confirm:'):
        if not pending.get('reset_nonce') or data.split(':', 1)[1] != pending['reset_nonce']:
            raise ValueError('Подтверждение устарело. Откройте настройки заново.')
        with app.db() as con:
            con.execute('DELETE FROM bot_sessions WHERE chat=?', (chat,))
            con.execute('DELETE FROM bot_context WHERE chat=?', (chat,))
            con.execute('DELETE FROM bot_confirmations WHERE chat=?', (chat,))
            con.execute('DELETE FROM bot_post_focus WHERE chat=?', (chat,))
            con.execute('DELETE FROM bot_company_knowledge WHERE chat=?', (chat,))
            con.execute('DELETE FROM company_document_chunks WHERE document IN (SELECT id FROM company_documents WHERE chat=?)',(chat,))
            con.execute('DELETE FROM company_documents WHERE chat=?',(chat,))
            con.execute('DELETE FROM marketer_memory WHERE chat=?',(chat,))
            con.execute('DELETE FROM bot_plan_context WHERE chat=?',(chat,))
            con.execute('DELETE FROM marketer_messages WHERE chat=?',(chat,))
            con.execute('DELETE FROM bot_content_plans WHERE chat=?', (chat,))
            con.execute('DELETE FROM bot_feature_confirmations WHERE chat=?', (chat,))
        return ask(session(chat))
    if data.startswith('voice_'):
        if pending.get('mode') != 'voice':
            raise ValueError('Эта расшифровка уже обработана.')
        if data == 'voice_show':
            return show_transcript(chat, pending)
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
        site = company_site(state)
        saved = company_knowledge.get(chat)
        if site and (not saved or saved['url'] != site):
            try:
                if not study_company(chat):
                    return
            except ValueError as error:
                return say(chat, str(error), inline=[[btn('Повторить', 'profile_ok'), btn('Продолжить без справки', 'profile_skip')]])
        set_context(chat, {})
        return home(chat)
    if data == 'stop_edit':
        post_id = state['editing']
        state['editing'] = None
        save(state)
        set_context(chat, {})
        return show_post(chat, post_id) if post_id else home(chat)
    if data == 'task_cancel':
        if state['editing']:
            state['editing'] = None
            save(state)
        set_context(chat, {})
        return home(chat)
    if data == 'continue_task':
        return clarification_screen(chat, pending.get('question', 'Уточните факты для поста.'))
    if data == 'without_quotes':
        if not pending.get('task'):
            return home(chat)
        task = pending['task'] + '\nРедактор: подготовь без цитат, без прямой речи и без blockquote. Используй только предоставленные факты.'
        return create_posts(chat, task, pending.get('clarification', ''))
    if data == 'posts':
        return list_posts(chat)
    if data == 'profile':
        return show_brief(state) if state['step'] == len(QUESTIONS) else ask(state)
    if data == 'help':
        return say(chat, 'Тема → черновик → правки → отправка.\n\nГолосовые: до 3 минут.\nСсылку для поста укажите в задаче.\nПубликация — после вашего подтверждения.', inline=[[btn('✨ Создать пост', 'new'), btn('⌂ Меню', 'home')]])
    if state['step'] < len(QUESTIONS):
        return ask(state)
    if context(chat).get('mode') == 'review':
        return show_brief(state)
    if data == 'retry':
        pending = context(chat)
        if state['editing'] and pending.get('retry_instruction'):
            return message(chat, pending['retry_instruction'])
        if not pending.get('task'):
            return home(chat)
        if pending.get('mode') in ('planning', 'plan_retry'):
            return plan_event(chat, pending['task'], pending.get('clarification', ''))
        return create_posts(chat, pending['task'], pending.get('clarification', ''), **({'angle': pending['angle']} if pending.get('angle') else {}))
    if data == 'new':
        focus_post(chat)
        state['editing'] = None
        save(state)
        set_context(chat, {'mode': 'new_task'})
        return say(chat, 'Что произошло или планируется?\nРасскажите текстом или голосом. Я соберу факты и предложу подачу.', inline=[[btn('← Меню', 'home')]], stage='event')
    if data == 'home':
        if state['editing']:
            return say(chat, 'Сначала завершите правку или отмените её.', inline=[[btn('← Не менять', 'stop_edit')]])
        set_context(chat, {})
        return home(chat)


def answer_question(state, text):
    if not 1 <= len(text) <= 1000:
        raise ValueError('Ответ должен содержать от 1 до 1000 символов.')
    answers = json.loads(state['answers'])
    if state['step'] == 0:
        company_knowledge.clear(state['chat'])
        with app.db() as con:
            con.execute('DELETE FROM bot_content_plans WHERE chat=?', (state['chat'],))
        answers.pop('site', None)
    answers[QUESTIONS[state['step']][0]] = text
    state['answers'] = json.dumps(answers, ensure_ascii=False)
    state['step'] += 1
    save(state)
    if state['step'] < len(QUESTIONS):
        return ask(state)
    set_context(state['chat'], {'mode': 'review'})
    return show_brief(state)


def plan_event(chat, task, clarification=''):
    app.requested_count(task)
    previous = context(chat)
    attempt = {**previous, 'mode': 'planning', 'task': task, 'clarification': clarification}
    set_context(chat, attempt)
    try:
        with loading(chat, 'Собираю факты и идеи') as wait:
            site = company_site(session(chat))
            known = company_knowledge.get(chat)
            if site and (not known or known['url'] != site):
                try:
                    company_knowledge.study(chat, site)
                except ValueError:
                    # Keep drafting from user facts; retry the site only on request.
                    with app.db() as con:
                        con.execute('INSERT OR REPLACE INTO bot_company_knowledge(chat,url,summary,sources) VALUES(?,?,?,?)', (chat, site, '', '[]'))
            result = app.plan_publication(brief(session(chat)), task, clarification)
    except Exception:
        set_context(chat, {**attempt, 'mode': 'plan_retry'})
        raise
    pending = {'mode': 'plan_clarify' if result['question'] else 'plan_facts', 'task': task,
               'clarification': clarification, 'facts': result['facts'], 'ideas': result['ideas'],
               'question': result['question'], 'plan_nonce': secrets.token_hex(5)}
    set_context(chat, pending)
    if wait.visible:
        return show_plan(chat, pending)


def show_plan(chat, pending=None, ideas=False):
    pending = pending or context(chat)
    if pending.get('mode') == 'plan_retry':
        return say(chat, 'Не удалось обновить факты. Исходная задача и все уточнения сохранены.',
                   inline=[[btn('↻ Повторить', 'retry'), btn('✕ Отменить задачу', 'task_cancel')]], stage='facts')
    if pending.get('mode') not in ('plan_facts', 'plan_ideas', 'plan_clarify', 'plan_correct'):
        raise ValueError('Этот этап уже завершён. Откройте актуальную задачу из меню.')
    nonce = pending['plan_nonce']
    facts = '\n'.join('<b>' + escape(f['label']) + ':</b> ' + escape(f['value']) for f in pending['facts'])
    if pending.get('mode') == 'plan_clarify':
        return say(chat, '<b>Что уже известно</b>\n\n' + facts + '\n\n<b>Уточните, пожалуйста:</b>\n' + escape(pending['question']),
                   inline=[[btn('✕ Отменить задачу', 'task_cancel')]], formatted=True, stage='facts')
    if pending.get('mode') == 'plan_correct':
        return say(chat, 'Что уточнить или исправить? Пришлите сообщение текстом или голосом.',
                   inline=[[btn('← К фактам', 'plan_facts:' + nonce)]], stage='facts')
    if ideas:
        text = '<b>Как расскажем об этом?</b>\n\n' + '\n\n'.join(
            f'<b>{i + 1}. {escape(idea["title"])}</b>\n{escape(idea["angle"])}' for i, idea in enumerate(pending['ideas']))
        rows = [[btn(f'{i + 1}. {idea["title"][:45]}', f'plan_draft:{nonce}:{i}')] for i, idea in enumerate(pending['ideas'])]
        rows.append([btn('← Факты', 'plan_facts:' + nonce), btn('✕ Отмена', 'task_cancel')])
        return say(chat, text, inline=rows, formatted=True, stage='ideas')
    first = pending['ideas'][0]
    text = '<b>Собранные факты</b>\n\n' + facts + '\n\n<b>Предлагаю подачу:</b> ' + escape(first['title']) + '\n' + escape(first['angle'])
    return say(chat, text, inline=[[btn('Создать пост', f'plan_draft:{nonce}:0', style='primary')],
               [btn('Другие идеи', 'plan_ideas:' + nonce), btn('Уточнить факты', 'plan_correct:' + nonce)],
               [btn('✕ Отменить задачу', 'task_cancel')]], formatted=True, stage='facts')


def plan_callback(chat, data):
    pending = context(chat)
    if data == 'plan_resume':
        return show_plan(chat, pending, ideas=pending.get('mode') == 'plan_ideas')
    parts = data.split(':')
    if len(parts) < 2 or not pending.get('plan_nonce') or parts[1] != pending['plan_nonce']:
        raise ValueError('Эта карточка устарела. Откройте актуальную задачу из меню.')
    if pending.get('mode') not in ('plan_facts', 'plan_ideas', 'plan_correct'):
        raise ValueError('Сначала ответьте на уточнение.')
    action = parts[0]
    if action == 'plan_draft':
        if len(parts) != 3 or not parts[2].isdigit() or not 0 <= int(parts[2]) < len(pending['ideas']):
            raise ValueError('Выберите одну из предложенных идей.')
        idea = pending['ideas'][int(parts[2])]
        return create_posts(chat, pending['task'], pending.get('clarification', ''), angle=idea['title'] + ': ' + idea['angle'])
    modes = {'plan_ideas': 'plan_ideas', 'plan_facts': 'plan_facts', 'plan_correct': 'plan_correct'}
    if action not in modes:
        raise ValueError('Неизвестное действие.')
    pending['mode'] = modes[action]
    set_context(chat, pending)
    return show_plan(chat, pending, ideas=action == 'plan_ideas')


def create_posts(chat, task, clarification='', *, angle=''):
    app.requested_count(task)
    previous = context(chat)
    preserved = {key: previous[key] for key in ('facts', 'ideas', 'plan_nonce') if key in previous}
    set_context(chat, {**preserved, 'mode': 'task', 'task': task, 'clarification': clarification, 'angle': angle})
    profile = brief(session(chat))
    with loading(chat, 'Готовлю черновик') as wait:
        result = app.prepare_posts(profile, task, clarification, **({'angle': angle} if angle else {}))
    if result.get('question'):
        set_context(chat, {**preserved, 'mode': 'clarify', 'task': task, 'question': result['question'], 'clarification': clarification, 'angle': angle})
        if wait.visible:
            return clarification_screen(chat, result['question'])
        return
    ids = []
    with app.db() as con:
        for post in result['posts']:
            cursor = con.execute('INSERT INTO bot_posts(chat,topic,body,image_prompt,source) VALUES(?,?,?,?,?)', (chat, post['topic'], post['body'], post['image_prompt'], 'deepseek'))
            ids.append(cursor.lastrowid)
            remember_version(con, cursor.lastrowid, 1, post['body'])
            con.execute('INSERT INTO bot_post_context VALUES(?,?,?,?)', (cursor.lastrowid, profile, task, clarification))
            con.execute('INSERT INTO bot_post_review(post,warnings,brand_name_mode,publication_date,fact_blocks) VALUES(?,?,?,?,?)', (cursor.lastrowid, json.dumps(post.get('warnings', []), ensure_ascii=False), post.get('brand_name_mode', editorial.brand_mode()), post.get('publication_date'), json.dumps(post.get('fact_blocks', []), ensure_ascii=False)))
    import post_images, contextlib
    with (loading(chat, 'Создаю изображение') if wait.visible else contextlib.nullcontext(wait)) as wait:
        post_images.attach_many(chat, ids, profile, task+'\n'+clarification)
    set_context(chat, {})
    rows = []
    with app.db() as con:
        for post_id in ids:
            post = con.execute('SELECT topic,rev FROM bot_posts WHERE id=?', (post_id,)).fetchone()
            rows.append([btn(f'📝 {post["topic"][:42]}', f'view:{post_id}:{post["rev"]}')])
    rows.append([btn('🗂 Все посты', 'posts'), btn('⌂ В меню', 'home')])
    if wait.visible:
        if len(ids) == 1:
            return show_post(chat, ids[0])
        return say(chat, 'Черновик готов' if len(ids) == 1 else f'Готово · {len(ids)} черновика', inline=rows)


def message(chat, text):
    if text.split('@')[0]=='/project':return project_handoff(chat)
    with app.db() as con:
        con.execute('DELETE FROM bot_confirmations WHERE chat=?', (chat,))
    state = session(chat)
    deep_link = re.fullmatch(r'/start\s+post_(\d+)', text)
    if deep_link:
        with app.db() as con:
            linked = con.execute('SELECT id,rev FROM bot_posts WHERE id=? AND chat=?',(int(deep_link[1]),chat)).fetchone()
        if not linked:
            raise ValueError('Пост не найден.')
        return callback(chat, f'view:{linked["id"]}:{linked["rev"]}')
    pending = context(chat)
    if pending.get('mode')=='marketer' and not text.startswith('/'):
        with loading(chat,'Маркетолог готовит ответ') as wait:result=__import__('marketer').ask(chat,text)
        if wait.visible:return say(chat,result['answer'],inline=[[btn('Контент-план','feat_plan'),btn('Документы','knowledge')],[btn('В меню','home')]],formatted=True)
        return
    if pending.get('mode')=='image_edit' and not text.startswith('/'):
        import post_images
        with loading(chat,'Создаю новый вариант изображения') as wait:
            post_images.regenerate(chat,pending['post'],pending['rev'],text,pending['nonce'])
        previous=pending.get('previous',{})
        with app.db() as con:updated=con.execute('SELECT rev FROM bot_posts WHERE id=? AND chat=?',(pending['post'],chat)).fetchone()
        if previous.get('mode')=='edit':previous['rev']=updated['rev']
        set_context(chat,previous)
        if wait.visible:return show_post(chat,pending['post'])
        return
    if pending.get('mode')=='schedule' and not text.startswith('/'):
        import scheduling
        due=scheduling.schedule(chat,pending['post'],pending['rev'],text)
        set_context(chat,{})
        return say(chat,'Публикация запланирована: '+due.strftime('%d.%m.%Y %H:%M')+' (Уфа, UTC+5).',inline=[[btn('К посту',f'view:{pending["post"]}:{pending["rev"]}')]])
    if pending.get('mode') == 'company_site' and not text.startswith('/'):
        site = company_knowledge.extract_url(text)
        if not site:
            raise ValueError('Не вижу ссылку. Например: https://company.ru')
        answers = json.loads(state['answers'])
        if company_site(state) != site:
            company_knowledge.clear(chat)
        answers['site'] = site
        state['answers'] = json.dumps(answers, ensure_ascii=False)
        save(state)
        set_context(chat, pending.get('previous', {}))
        if study_company(chat):
            return show_brief(session(chat))
        return
    aliases = {'✨ Новый пост': 'new', 'Подготовить посты': 'new', '/generate': 'new',
               '🗂 Мои посты': 'posts', 'Мои посты': 'posts', '/posts': 'posts',
               '🏢 Профиль': 'profile', 'Профиль бизнеса': 'profile', '/profile': 'profile',
               '❔ Помощь': 'help', '/help': 'help', 'Изменить анкету': 'profile_edit'}
    if text == '/start':
        if state['editing']:
            if context(chat).get('retry_instruction'):
                return say(chat, 'Правка сохранена. Применить её к открытому посту?',
                           inline=[[btn('↻ Применить правку', 'retry')], [btn('← К посту', 'stop_edit')]], stage='edit')
            return say(chat, 'Правки открыты. Что изменить?', inline=[[btn('✓ Готово', 'stop_edit')]])
        if state['step'] == len(QUESTIONS):
            return show_brief(state) if context(chat).get('mode') == 'review' else home(chat)
        return home(chat)
    if text in ('Отмена', '/cancel'):
        return navigation(chat, 'stop_edit' if state['editing'] else 'task_cancel')
    if text in aliases:
        if state['editing'] and aliases[text] not in ('help',):
            return say(chat, 'Завершите правки, чтобы продолжить.', inline=[[btn('✓ Готово', 'stop_edit')]])
        return navigation(chat, aliases[text])
    if context(chat).get('mode') == 'voice':
        pending = context(chat)
        set_context(chat, pending['previous'])
        return message(chat, text)
    if context(chat).get('mode') == 'content_plan_input':
        return bot_features.generate_plan(chat, text)
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
            updated_memory = ''  # A full manual replacement starts from the supplied text.
            edited = {}
        else:
            review = review_metadata(post_id)
            set_context(chat, {**pending, 'retry_instruction': text})
            edit_options = {'memory': pending.get('memory', ''), 'brand_name_mode': review['brand_name_mode'], 'publication_date': review['publication_date']}
            if review['fact_blocks']:
                edit_options['fact_blocks'] = review['fact_blocks']
            with loading(chat, 'Правлю текст') as wait:
                edited = app.rewrite_post(edit_brand_rules(state), post['body'], text, **edit_options)
            body, updated_memory = edited['body'], edited['memory']
        body = post_format.normalize(body)
        if not post_format.plain(body):
            raise ValueError('Текст пустой. Старая версия сохранена.')
        review = review_metadata(post_id)
        notes = list(dict.fromkeys(review['warnings'] + edited.get('warnings', [])))
        with app.db() as con:
            remember_version(con, post_id, post['rev'], post['body'])
            result = con.execute('UPDATE bot_posts SET body=?,status="draft",rev=rev+1 WHERE id=? AND chat=? AND rev=? AND status IN ("draft","approved")', (body, post_id, chat, post['rev']))
            if result.rowcount != 1:
                raise ValueError('Пост уже изменился. Старая версия не перезаписана.')
            con.execute('DELETE FROM bot_confirmations WHERE post=?', (post_id,))
            remember_version(con, post_id, post['rev'] + 1, body, text, 'replace' if pending.get('mode') == 'replace' else 'rewrite')
            con.execute('INSERT OR REPLACE INTO bot_post_review(post,warnings,brand_name_mode,publication_date,fact_blocks) VALUES(?,?,?,?,?)', (post_id, json.dumps(notes, ensure_ascii=False), edited.get('brand_name_mode', review['brand_name_mode']), edited.get('publication_date', review['publication_date']), json.dumps(edited.get('fact_blocks', []), ensure_ascii=False)))
        __import__('post_images').refresh_cover(chat,post_id)
        state['editing'] = post_id
        save(state)
        set_context(chat, {'mode': 'edit', 'rev': post['rev'] + 1, 'awaiting': False, 'memory': updated_memory})
        if pending.get('mode') == 'replace' or wait.visible:
            return show_post(chat, post_id)
        return
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
        clarification = '\n'.join(value for value in (pending.get('clarification', ''), text) if value)
        return create_posts(chat, pending['task'], clarification, **({'angle': pending['angle']} if pending.get('angle') else {}))
    if pending.get('mode') in ('plan_clarify', 'plan_correct', 'plan_facts', 'plan_ideas', 'plan_retry', 'planning'):
        clarification = '\n'.join(value for value in (pending.get('clarification', ''), text) if value)
        return plan_event(chat, pending['task'], clarification)
    if not pending:
        post = focused_post(chat)
        if post:
            callback(chat, f'edit:{post["id"]}:{post["rev"]}')
            return message(chat, text)
    if bot_features.preferences(chat)['fast']:
        return create_posts(chat, text)
    return plan_event(chat, text)


def show_brief(state):
    if state['step'] < len(QUESTIONS):
        return ask(state)
    text = 'Профиль компании\n\n' + brief(state)
    buttons = [[btn('✏️ Изменить профиль', 'profile_edit'), btn('⌂ В меню', 'home')]]
    if context(state['chat']).get('mode') == 'review':
        buttons = [[btn('✅ Всё верно', 'profile_ok')], [btn('✏️ Исправить', 'profile_edit')]]
    buttons.append([btn('Сайт компании', 'company_site'), btn('Обновить справку', 'company_study')])
    return say(state['chat'], text, inline=buttons)


def voice_message(chat, voice):
    if voice.get('duration', 0) > 180 or voice.get('file_size', 0) > speech.MAX_AUDIO_BYTES:
        raise ValueError('Отправьте голосовое до 3 минут и 5 МБ или напишите задачу текстом.')
    with loading(chat, 'Распознаю голос') as wait:
        text = recognize_voice(voice)
    previous = context(chat)
    if previous.get('mode') == 'voice':
        previous = previous['previous']
    if bot_features.preferences(chat)['auto_voice']:
        set_context(chat, previous)
        return message(chat, text)
    nonce = secrets.token_hex(4)
    pending = {'mode': 'voice', 'text': text, 'previous': previous, 'nonce': nonce}
    set_context(chat, pending)
    if wait.visible:
        show_transcript(chat, pending)


def recognize_voice(voice):
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
    return speech.transcribe(audio)


def show_transcript(chat, pending):
    nonce = pending['nonce']
    say(chat, 'Правильно распознал?\n\n' + pending['text'], inline=[[btn('✅ Да', f'speech:use:{nonce}'), btn('✏️ Исправить', f'speech:edit:{nonce}')], [btn('✕ Отмена', f'speech:cancel:{nonce}')]])


def read_navigation(data):
    return data in ('home', 'posts', 'profile', 'help', 'settings', 'tg_app', 'plan_resume') or data.startswith(('view:', 'history:', 'notes:', 'page:', 'posts_page:'))


def fast_navigation(chat, data):
    # Read-only browsing never waits behind generation and never clears edit memory.
    if data == 'home':
        return home(chat)
    if data == 'posts':
        return list_posts(chat)
    if data == 'profile':
        return show_brief(session(chat))
    if data == 'help':
        return navigation(chat, data)
    return callback(chat, data)


def acknowledge(query_id, text=None):
    try:
        payload = {'callback_query_id': query_id}
        if text:
            payload['text'] = text
        tg('answerCallbackQuery', payload, timeout=5)
    except Exception:
        pass


def dispatch_authorized(update):
    query = update.get('callback_query')
    msg = query.get('message', {}) if query else update.get('message', {})
    chat = msg['chat']['id']
    data = query.get('data', '') if query else ''
    blocked = bool(query and is_busy(chat) and not read_navigation(data))
    if query:
        update['_callback_answered'] = True
        _ACK_POOL.submit(acknowledge, query['id'], 'Задача ещё выполняется' if blocked else None)
    if query and read_navigation(data):
        update['_fast_ui'] = True
        if enqueue(update, status='running'):
            status = 'done'
            try:
                handle(update)
            except Exception:
                status = 'failed'
            with app.db() as con:
                con.execute('UPDATE bot_inbox SET status=? WHERE id=?', (status, update['update_id']))
    elif blocked:
        # Do not defer Send/Edit until the AI finishes and changes the post version.
        enqueue(update, status='done')
    else:
        enqueue(update)


def handle(update):
    import model_selection
    query=update.get('callback_query')
    msg=query.get('message',{}) if query else update.get('message',{})
    sender=query.get('from',{}) if query else msg.get('from',{})
    chat=msg.get('chat',{})
    if chat.get('type')=='private' and str(sender.get('id')) in allowed_user_ids():
        with model_selection.for_chat(chat['id']):return _handle(update)
    return _handle(update)


def _handle(update):
    query = update.get('callback_query')
    msg = query.get('message', {}) if query else update.get('message', {})
    sender = query.get('from', {}) if query else msg.get('from', {})
    chat = msg.get('chat', {})
    if chat.get('type') != 'private':
        return
    if str(sender.get('id')) not in allowed_user_ids():
        if query:
            acknowledge(query['id'], 'Нет доступа')
        return
    __import__('user_access').observe(sender)
    processed = False
    try:
        import premium_emoji
        if not query and premium_emoji.receive(chat['id'],msg):
            pass
        elif query:
            if not update.get('_callback_answered'):
                try:
                    tg('answerCallbackQuery', {'callback_query_id': query['id']})
                except ValueError:
                    pass
            if update.get('_fast_ui'):
                fast_navigation(chat['id'], query.get('data', ''))
            else:
                callback(chat['id'], query.get('data', ''))
        elif isinstance(msg.get('text'), str):
            message(chat['id'], msg['text'].strip())
        elif msg.get('voice'):
            voice_message(chat['id'], msg['voice'])
        elif msg.get('document'):
            __import__('marketer').receive_document(chat['id'],msg['document'])
        elif msg.get('photo'):
            bot_features.receive_photo(chat['id'], msg['photo'])
        else:
            say(chat['id'], 'Пришлите текст, голосовое, фото или документ PDF, DOCX, TXT.')
        processed = True
    except ValueError as error:
        pending = context(chat['id'])
        buttons = [[btn('↻ Повторить', 'retry'), btn('✕ Отменить задачу', 'task_cancel')]] if pending.get('mode') in ('task', 'planning', 'plan_retry') else None
        if pending.get('retry_instruction'):
            buttons = [[btn('↻ Повторить правку', 'retry'), btn('← К посту', 'stop_edit')]]
        if pending.get('mode') == 'content_plan_input' and pending.get('request'):
            buttons = [[btn('↻ Повторить', 'feat_plan_retry'), btn('← Меню', 'home')]]
        if pending.get('mode')=='emoji_palette':buttons=[[btn('К настройкам','feat_emoji_close')]]
        if pending.get('mode')=='image_edit':buttons=[[btn('К посту','feat_art_cancel')]]
        say(chat['id'], str(error), inline=buttons)
        processed = True
    except Exception:
        say(chat['id'], 'Не удалось выполнить запрос. Проверьте ключи и подключение. Сохранённые посты доступны в «Мои посты».')
        processed = True
    finally:
        # The durable inbox retains the input; only remove its visible chat bubble.
        # A callback may refer to an old bot card from before the single-screen update.
        if processed:
            telegram_screen.delete(chat['id'], msg.get('message_id'), tg)


def enqueue(update, status='queued'):
    query = update.get('callback_query')
    msg = query.get('message', {}) if query else update.get('message', {})
    chat = msg.get('chat', {}).get('id', 0)
    with app.db() as con:
        inserted = con.execute('INSERT OR IGNORE INTO bot_inbox(id,chat,payload,status) VALUES(?,?,?,?)', (update['update_id'], chat, json.dumps(update, ensure_ascii=False), status)).rowcount
        con.execute('INSERT OR REPLACE INTO bot_meta VALUES("offset",?)', (update['update_id'] + 1,))
    _WAKE.setdefault(chat, threading.Event()).set()
    return bool(inserted)


def consume_one(chat):
    with app.db() as con:
        row = con.execute('SELECT * FROM bot_inbox WHERE chat=? AND status="queued" ORDER BY id LIMIT 1', (chat,)).fetchone()
        if not row:
            return False
        con.execute('UPDATE bot_inbox SET status="running" WHERE id=?', (row['id'],))
    status = 'done'
    with _BUSY_LOCK:
        _BUSY.add(chat)
    try:
        handle(json.loads(row['payload']))
    except Exception:
        # Delivery may already have happened. Never replay this event automatically.
        status = 'failed'
        print('An incoming task failed. No automatic replay; check saved posts.')
    finally:
        with _BUSY_LOCK:
            _BUSY.discard(chat)
    with app.db() as con:
        con.execute('UPDATE bot_inbox SET status=? WHERE id=?', (status, row['id']))
    return True


def worker(chat, stop):
    wake = _WAKE.setdefault(chat, threading.Event())
    while not stop.is_set():
        try:
            wake.clear()
            if not consume_one(chat):
                wake.wait(0.5)
        except Exception:
            print('Local queue error. Retrying; credentials not logged.')
            stop.wait(1)


def configure_miniapp():
    url = os.environ.get('MINI_APP_URL', '').strip()
    parts = urlparse(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        return False
    tg('setChatMenuButton', {'menu_button': {'type': 'web_app', 'text': 'Открыть', 'web_app': {'url': url}}})
    for owner in allowed_user_ids():
        try:
            tg('setChatMenuButton', {'chat_id': int(owner), 'menu_button': {'type': 'web_app', 'text': 'Открыть', 'web_app': {'url': url}}})
        except TelegramAPIError as error:
            if error.reason!='chat_not_found':raise
            # New allowed users may not have pressed /start yet; default menu
            # is already configured and becomes available when they do.
    return True


def connect_telegram():
    delay=5
    while True:
        try:
            return tg('getMe',{}),tg('getWebhookInfo',{})
        except TelegramConnectionError:
            print(f'Telegram временно недоступен. Повторное подключение через {delay} сек. Окно можно оставить открытым.',flush=True)
            time.sleep(delay)
            delay=min(delay*2,30)


def main():
    if not os.environ.get('TELEGRAM_BOT_TOKEN'):
        print('Заполните TELEGRAM_BOT_TOKEN в .env. Инструкция: TELEGRAM.md')
        return
    init_db()
    print('Подключаюсь к Telegram… Ctrl+C для остановки.',flush=True)
    # Do not delete an existing webhook silently: a token must belong to this deployment.
    try:
        identity,webhook = connect_telegram()
    except ValueError as error:
        print(error)
        return
    if webhook.get('url'):
        print('У бота настроен webhook. Используйте отдельного тестового бота без webhook.')
        return
    activate_bot(identity['id'])
    print('Бот подключён и работает. Оставьте это окно открытым.',flush=True)
    try:
        configure_miniapp()
    except ValueError:
        print('Mini App menu unavailable; bot continues working.')
    with app.db() as con:
        row = con.execute('SELECT value FROM bot_meta WHERE key="offset"').fetchone()
    offset = row['value'] if row else 0
    stop = threading.Event()
    workers = {}
    import scheduling
    scheduling.start(stop)

    def ensure_worker(chat):
        if chat not in workers or not workers[chat].is_alive():
            thread = threading.Thread(target=worker, args=(chat, stop), daemon=True)
            workers[chat] = thread
            thread.start()

    with app.db() as con:
        queued_chats = [row['chat'] for row in con.execute('SELECT DISTINCT chat FROM bot_inbox WHERE status="queued"')]
    for chat in queued_chats:
        ensure_worker(chat)
    while True:
        try:
            updates = tg('getUpdates', {'offset': offset, 'timeout': 25, 'allowed_updates': ['message', 'callback_query']})
            for update in updates:
                query = update.get('callback_query')
                msg = query.get('message', {}) if query else update.get('message', {})
                sender = query.get('from', {}) if query else msg.get('from', {})
                if str(sender.get('id')) in allowed_user_ids() and msg.get('chat', {}).get('type') == 'private':
                    ensure_worker(msg['chat']['id'])
                    dispatch_authorized(update)
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




def project_handoff(chat):
    if str(chat) not in allowed_user_ids():raise PermissionError('Нет доступа.')
    source=app.ROOT/'docs'/'PROJECT_HANDOFF_RU.md'
    if not source.is_file():raise ValueError('Документ проекта пока не найден.')
    path=app.ROOT/'data'/'PROJECT_HANDOFF_RU.txt'
    path.write_text(source.read_text(encoding='utf-8'),encoding='utf-8-sig')
    return tg('sendDocument',{'chat_id':chat,'_document_path':str(path),'caption':'Функционал проекта для презентации: возможности, демонстрация, архитектура и ограничения. Версия от 15 ноября 2026.'})


if __name__ == '__main__':
    from runtime_lock import single_instance
    try:
        with single_instance(app.ROOT/'data'/'telegram_bot.lock'):
            main()
    except BlockingIOError:
        print('Бот уже работает. Второй запуск не нужен. Это окно можно закрыть.')
    except KeyboardInterrupt:
        print('Бот остановлен.')
