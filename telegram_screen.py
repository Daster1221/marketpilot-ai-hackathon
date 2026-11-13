"""One persisted, editable Telegram message per private chat."""
import json
import secrets
import threading
import time

import app
import post_format

_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def chat_lock(chat):
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(chat, threading.RLock())


def init_db(con):
    con.execute('CREATE TABLE IF NOT EXISTS bot_screens (chat INTEGER PRIMARY KEY, message_id INTEGER, pages TEXT, buttons TEXT, page INTEGER, formatted INTEGER, nonce TEXT, last_payload TEXT)')


def get(chat):
    with app.db() as con:
        row = con.execute('SELECT * FROM bot_screens WHERE chat=?', (chat,)).fetchone()
    return dict(row) if row else None


def save(state):
    with app.db() as con:
        con.execute('INSERT OR REPLACE INTO bot_screens VALUES(?,?,?,?,?,?,?,?)', tuple(state[k] for k in ('chat', 'message_id', 'pages', 'buttons', 'page', 'formatted', 'nonce', 'last_payload')))


def delete(chat, message_id, api):
    if not message_id:
        return
    current = get(chat)
    if current and current['message_id'] == message_id:
        return
    try:
        api('deleteMessage', {'chat_id': chat, 'message_id': message_id})
    except Exception:
        # Telegram may refuse deletion of old messages; never fail the task for cleanup.
        pass


def payload_for(state):
    pages = json.loads(state['pages'])
    buttons = json.loads(state['buttons'])
    index = state['page']
    text = pages[index]
    if len(pages) > 1:
        text += f'\n\n{index + 1} / {len(pages)}'
        nav = []
        if index:
            nav.append({'text': '← Назад', 'callback_data': f'page:{state["nonce"]}:{index - 1}'})
        if index + 1 < len(pages):
            nav.append({'text': 'Далее →', 'callback_data': f'page:{state["nonce"]}:{index + 1}'})
        # Approval is shown after the last part of a long preview/profile.
        if index + 1 < len(pages):
            buttons = [[b for b in row if not b.get('callback_data', '').startswith(('confirm:', 'profile_ok'))] for row in buttons]
            buttons = [row for row in buttons if row]
        buttons = [nav] + buttons
    payload = {'chat_id': state['chat'], 'text': text, 'reply_markup': {'inline_keyboard': buttons}, 'link_preview_options': {'is_disabled': True}}
    if state['formatted']:
        payload['parse_mode'] = 'HTML'
    return payload


def update(state, api):
    payload = payload_for(state)
    signature = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if state['last_payload'] == signature:
        save(state)
        return {'message_id': state['message_id']}
    old_id = state['message_id']
    if old_id:
        try:
            result = api('editMessageText', {**payload, 'message_id': old_id})
        except ValueError as error:
            if getattr(error, 'reason', None) == 'not_modified':
                result = {'message_id': old_id}
            elif getattr(error, 'reason', None) == 'unavailable':
                state['message_id'] = None
            else:
                raise
        else:
            state['last_payload'] = signature
            save(state)
            return result
        if state['message_id']:
            state['last_payload'] = signature
            save(state)
            return result
    # A message carrying ReplyKeyboardRemove may not be editable. Use a disposable
    # message to dismiss the old keyboard; the actual screen has an inline keyboard.
    cleanup_id = None
    if not old_id:
        removed = api('sendMessage', {'chat_id': state['chat'], 'text': 'Открываю рабочий экран…',
                                     'disable_notification': True, 'reply_markup': {'remove_keyboard': True}})
        cleanup_id = removed['message_id']
    sent = api('sendMessage', payload)
    state['message_id'] = sent['message_id']
    state['last_payload'] = signature
    save(state)
    if cleanup_id:
        delete(state['chat'], cleanup_id, api)
    if old_id and old_id != state['message_id']:
        delete(state['chat'], old_id, api)
    return sent


def show(chat, text, buttons, formatted, api):
    with chat_lock(chat):
        return _show(chat, text, buttons, formatted, api)


def _show(chat, text, buttons, formatted, api):
    old = get(chat)
    state = {'chat': chat, 'message_id': old['message_id'] if old else None,
             'pages': json.dumps(post_format.split_pages(text, formatted=formatted), ensure_ascii=False),
             'buttons': json.dumps(buttons, ensure_ascii=False), 'page': 0,
             'formatted': int(formatted), 'nonce': secrets.token_hex(5),
             'last_payload': old['last_payload'] if old else ''}
    return update(state, api)


def turn_page(chat, data, api):
    with chat_lock(chat):
        return _turn_page(chat, data, api)


def _turn_page(chat, data, api):
    _, nonce, target = data.split(':')
    state = get(chat)
    if not state or state['nonce'] != nonce:
        raise ValueError('Этот экран уже изменился. Используйте кнопки в последнем сообщении.')
    page = int(target)
    if not 0 <= page < len(json.loads(state['pages'])):
        raise ValueError('Страница не найдена.')
    state['page'] = page
    return update(state, api)


class Loading:
    """Animate only our own screen; never overwrite navigation or invent progress."""
    frames = ('● ○ ○', '○ ● ○', '○ ○ ●', '○ ● ○')

    def __init__(self, chat, label, api, background_api=None, threaded=True):
        self.chat, self.label, self.api = chat, label, api
        self.background_api = background_api or api
        self.threaded = threaded
        self.stop_event = threading.Event()
        self.thread = None
        self.frame = 0

    def __enter__(self):
        self.action_at = 0
        self.typing()
        show(self.chat, f'{self.label}\n\n{self.frames[0]}', [[{'text': '⌂ Меню', 'callback_data': 'home'}]], False, self.api)
        self.nonce = get(self.chat)['nonce']
        if self.threaded:
            self.thread = threading.Thread(target=self.run, daemon=True)
            self.thread.start()
        return self

    @property
    def visible(self):
        state = get(self.chat)
        return bool(state and state['nonce'] == self.nonce)

    def tick(self):
        with chat_lock(self.chat):
            if self.stop_event.is_set() or not self.visible:
                return False
            self.frame = (self.frame + 1) % len(self.frames)
            state = get(self.chat)
            self.typing()
            state['pages'] = json.dumps([f'{self.label}\n\n{self.frames[self.frame]}'], ensure_ascii=False)
            update(state, self.background_api)
            return True

    def typing(self):
        if time.monotonic() - self.action_at < 4:
            return
        self.action_at = time.monotonic()
        try:
            self.background_api('sendChatAction', {'chat_id': self.chat, 'action': 'typing'})
        except Exception:
            pass

    def run(self):
        while not self.stop_event.wait(1):
            try:
                if not self.tick():
                    break
            except Exception:
                break  # Animation failure must not fail or repeat the actual AI task.

    def __exit__(self, *exc):
        self.stop_event.set()
        if self.thread:
            self.thread.join()
