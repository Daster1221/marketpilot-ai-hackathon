"""Explicitly approved, revision-bound Telegram delivery. Never replay a send."""
from datetime import datetime,timedelta,timezone
import threading
import app

TZ=timezone(timedelta(hours=5))


def init_db(con):
    con.execute('CREATE TABLE IF NOT EXISTS bot_post_schedule(post INTEGER PRIMARY KEY,chat INTEGER,due TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS bot_delivery_schedule(post INTEGER PRIMARY KEY,chat INTEGER,rev INTEGER,due TEXT,channel TEXT,state TEXT,error TEXT DEFAULT "")')
    con.execute('CREATE INDEX IF NOT EXISTS bot_delivery_due ON bot_delivery_schedule(state,due)')


def parse_due(value):
    try:
        due=datetime.fromisoformat(value.strip().replace('Z','+00:00'))
    except (ValueError,AttributeError):
        try:due=datetime.strptime(value.strip(),'%d.%m.%Y %H:%M')
        except (ValueError,AttributeError):raise ValueError('Укажите дату и время, например: 15.11.2026 18:30. Часовой пояс: Уфа (UTC+5).') from None
    return due.replace(tzinfo=TZ) if due.tzinfo is None else due.astimezone(TZ)


def schedule(chat,pid,rev,value):
    import telegram_bot as bot
    import post_format
    channel=bot.publication_channel(chat)
    if not channel:raise ValueError('Канал для публикации не подключён.')
    if bot.session(chat)['editing']==pid:raise ValueError('Сначала завершите правки этого поста в боте кнопкой «Готово».')
    due=parse_due(value)
    if not datetime.now(TZ)<due<datetime.now(TZ)+timedelta(days=366):raise ValueError('Выберите будущее время в пределах года. Время указано по Уфе (UTC+5).')
    with app.db() as con:
        con.execute('BEGIN IMMEDIATE')
        p=con.execute('SELECT * FROM bot_posts WHERE id=? AND chat=?',(pid,chat)).fetchone()
        if not p or p['rev']!=rev or p['status'] not in ('draft','approved'):raise ValueError('Пост изменился или уже отправлен. Откройте актуальную версию.')
        prior=con.execute('SELECT state FROM bot_delivery_schedule WHERE post=?',(pid,)).fetchone()
        if prior and prior['state'] in ('sending','unknown','sent'):raise ValueError('Отправка уже началась или требует проверки канала. Повтор не запланирован.')
        if post_format.length(p['body'])>4096:raise ValueError('Сократите текст до 4096 символов перед планированием.')
        con.execute('INSERT OR REPLACE INTO bot_post_schedule VALUES(?,?,?)',(pid,chat,due.isoformat()))
        con.execute('INSERT OR REPLACE INTO bot_delivery_schedule VALUES(?,?,?,?,?,"queued","")',(pid,chat,rev,due.isoformat(),channel))
        con.execute('UPDATE bot_posts SET status="approved" WHERE id=?',(pid,))
        con.execute('DELETE FROM bot_confirmations WHERE post=?',(pid,))
    return due


def cancel(chat,pid,rev):
    with app.db() as con:
        con.execute('BEGIN IMMEDIATE')
        p=con.execute('SELECT rev,status FROM bot_posts WHERE id=? AND chat=?',(pid,chat)).fetchone()
        if not p or p['rev']!=rev or p['status'] not in ('draft','approved'):raise ValueError('Пост изменился или отправка уже началась.')
        con.execute('UPDATE bot_delivery_schedule SET state="cancelled" WHERE post=? AND chat=? AND state="queued"',(pid,chat))
        con.execute('UPDATE bot_posts SET status="draft" WHERE id=?',(pid,))


def recover_interrupted():
    with app.db() as con:
        con.execute('UPDATE bot_delivery_schedule SET state="unknown",error="Отправка прервана. Проверьте канал вручную." WHERE state="sending"')


def tick(now=None):
    import telegram_bot as bot
    import bot_features,post_format
    now=now or datetime.now(TZ)
    with app.db() as con:
        con.execute('BEGIN IMMEDIATE')
        item=con.execute('SELECT * FROM bot_delivery_schedule WHERE state="queued" AND datetime(due)<=datetime(?) ORDER BY due LIMIT 1',(now.isoformat(),)).fetchone()
        if not item:return False
        item=dict(item)
        p=con.execute('SELECT * FROM bot_posts WHERE id=? AND chat=?',(item['post'],item['chat'])).fetchone()
        editing=con.execute('SELECT editing FROM bot_sessions WHERE chat=?',(item['chat'],)).fetchone()
        if not p or p['rev']!=item['rev'] or p['status']!='approved' or (editing and editing['editing']==item['post']) or bot.publication_channel(item['chat'])!=item['channel']:
            con.execute('UPDATE bot_delivery_schedule SET state="needs_review",error="Пост или канал изменился. Согласуйте заново." WHERE post=?',(item['post'],))
            return True
        p=dict(p)
        con.execute('UPDATE bot_delivery_schedule SET state="sending" WHERE post=?',(p['id'],))
        con.execute('UPDATE bot_posts SET status="publishing" WHERE id=?',(p['id'],))
    # No database lock across network I/O. The durable claim prevents duplicates.
    try:
        image=bot_features.image_for(p['id'])
        import premium_emoji
        pages=post_format.split_pages(premium_emoji.render_publication(p['body'],item['chat'],item['channel']),limit=1000 if image else 4096,formatted=True)
        first=None
        for index,page in enumerate(pages):
            payload={'chat_id':item['channel'],'parse_mode':'HTML'}
            payload.update({**__import__('post_images').payload(image),'caption':page} if image and index==0 else {'text':page})
            result=bot.tg('sendPhoto' if image and index==0 else 'sendMessage',payload)
            first=first or result['message_id']
    except Exception:
        with app.db() as con:
            con.execute('UPDATE bot_posts SET status="delivery_unknown" WHERE id=?',(p['id'],))
            con.execute('UPDATE bot_delivery_schedule SET state="unknown",error="Доставка не подтверждена. Проверьте канал вручную; повтора не будет." WHERE post=?',(p['id'],))
        return True
    with app.db() as con:
        con.execute('UPDATE bot_posts SET status="published",message_id=? WHERE id=?',(str(first),p['id']))
        con.execute('UPDATE bot_delivery_schedule SET state="sent" WHERE post=?',(p['id'],))
        con.execute('DELETE FROM bot_confirmations WHERE post=?',(p['id'],))
    return True


def start(stop):
    recover_interrupted()
    def work():
        while not stop.is_set():
            try:tick()
            except Exception:print('Ошибка проверки расписания. Отправки не повторяются автоматически.',flush=True)
            stop.wait(2)
    thread=threading.Thread(target=work,daemon=True,name='scheduled-delivery');thread.start();return thread
