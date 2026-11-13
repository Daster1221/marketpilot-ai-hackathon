"""A reusable stage header above the editable text screen."""
import os
import app
import telegram_screen

STAGES = ('home', 'event', 'facts', 'ideas', 'draft', 'edit', 'review', 'published')


def init_db(con):
    con.execute('CREATE TABLE IF NOT EXISTS bot_stage_screens (chat INTEGER PRIMARY KEY, message_id INTEGER, stage TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS bot_stage_files (bot TEXT, stage TEXT, file_id TEXT, PRIMARY KEY(bot,stage))')


def hide(chat, api):
    with app.db() as con:
        row = con.execute('SELECT * FROM bot_stage_screens WHERE chat=?', (chat,)).fetchone()
    if row:
        api('deleteMessage', {'chat_id': chat, 'message_id': row['message_id']})
        with app.db() as con:
            con.execute('DELETE FROM bot_stage_screens WHERE chat=?', (chat,))


def show(chat, stage, api):
    if stage is None:
        return hide(chat, api)
    if stage not in STAGES:
        raise ValueError('Unknown publication stage')
    path = app.ROOT / 'assets' / 'stages' / (stage + '.png')
    if not path.is_file():
        return
    bot = os.environ.get('TELEGRAM_BOT_TOKEN', '').split(':')[0]
    bot = bot if bot.isdecimal() else 'test'
    with app.db() as con:
        row = con.execute('SELECT * FROM bot_stage_screens WHERE chat=?', (chat,)).fetchone()
        cached = con.execute('SELECT file_id FROM bot_stage_files WHERE bot=? AND stage=?', (bot, stage)).fetchone()
    if row and row['stage'] == stage:
        return
    photo = cached['file_id'] if cached else 'attach://photo'
    payload = {'chat_id': chat}
    if not cached:
        payload['_photo_path'] = str(path)
    if row:
        payload.update(message_id=row['message_id'], media={'type': 'photo', 'media': photo})
        try:
            result = api('editMessageMedia', payload)
        except ValueError as error:
            if getattr(error, 'reason', None) != 'unavailable':
                raise
            row = None
    if not row:
        payload = {'chat_id': chat, 'disable_notification': True}
        payload.update({'photo': cached['file_id']} if cached else {'_photo_path': str(path)})
        result = api('sendPhoto', payload)
        old = telegram_screen.get(chat)
        if old and old['message_id']:
            with app.db() as con:
                con.execute('UPDATE bot_screens SET message_id=NULL,last_payload="" WHERE chat=?', (chat,))
            telegram_screen.delete(chat, old['message_id'], api)
    with app.db() as con:
        con.execute('INSERT OR REPLACE INTO bot_stage_screens VALUES(?,?,?)', (chat, result['message_id'], stage))
        photos = result.get('photo', [])
        if photos:
            con.execute('INSERT OR REPLACE INTO bot_stage_files VALUES(?,?,?)', (bot, stage, photos[-1]['file_id']))
