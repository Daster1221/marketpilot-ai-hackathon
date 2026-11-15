"""Verified custom-emoji catalogs. Custom emoji are private-preview only."""
import re,json
from functools import lru_cache
from html import escape
import app,post_format

PACKS = ('nowemoji', 'IconsInTg', 'Salavatsteklo')


def init_db(con):
    con.execute('CREATE TABLE IF NOT EXISTS bot_emoji_palette(chat INTEGER,emoji TEXT,emoji_id TEXT,PRIMARY KEY(chat,emoji))')


@lru_cache(maxsize=1)
def _catalog():
    from pathlib import Path
    result={}
    for pack in PACKS:
        items=json.loads(Path(__file__).with_name(pack+'.json').read_text(encoding='utf-8'))
        values={item['emoji']:item['custom_emoji_id'] for item in reversed(items)}
        # Later packs win shared glyphs: company artwork has highest priority.
        for glyph,identifier in values.items():
            result[glyph]=identifier
            result[glyph.replace('\ufe0f','')]=identifier
    return result


def palette(chat):
    return dict(_catalog())


# Match complete emoji sequences without touching ordinary digits or hashtags.
_EMOJI = re.compile(r'(?:[#*0-9]\ufe0f?\u20e3|[\U0001f1e6-\U0001f1ff]{2}|[\U0001f000-\U0001faff\u2600-\u27bf\u2300-\u23ff\u2b00-\u2bff\u2190-\u21ff\u00a9\u00ae\u203c\u2049\u2122\u2139\u3030\u303d\u3297\u3299](?:[\ufe0e\ufe0f\U0001f3fb-\U0001f3ff])?(?:\u200d[\U0001f000-\U0001faff\u2600-\u27bf](?:[\ufe0e\ufe0f\U0001f3fb-\U0001f3ff])?)*[\U000e0020-\U000e007f]*)')


def remove_emoji(body):
    return _EMOJI.sub('',plain_emoji(body))


def filter_body(body):
    allowed=palette(None)
    return _EMOJI.sub(lambda m:m[0] if m[0] in allowed else '',plain_emoji(body))

def store(chat,items):
    with app.db() as con:
        for item in items[:50]:
            glyph=item.get('emoji','');identifier=item.get('custom_emoji_id',item.get('id',''))
            if isinstance(glyph,str) and 0<len(glyph)<=32 and not any(c in glyph for c in '<>&\r\n') and any(ord(c)>127 for c in glyph) and re.fullmatch(r'[0-9]{1,25}',str(identifier)):
                con.execute('INSERT OR REPLACE INTO bot_emoji_palette VALUES(?,?,?)',(chat,glyph,str(identifier)))


def plain_emoji(body):
    return re.sub(r'</?tg-emoji\b[^>]*>','',body,flags=re.I)


def render_private(body,chat):
    import bot_features
    body=post_format.normalize(plain_emoji(body))
    mapping=palette(chat) if bot_features.preferences(chat).get('premium_emoji',True) else {}
    if not mapping:return remove_emoji(body)
    class Renderer(post_format.PostParser):
        def handle_data(self,data):
            for part in re.split(r'(https?://\S+)',data):
                if part.startswith(('https://','http://')):self.parts.append(escape(part,quote=False));continue
                def replace(match):
                    glyph=match[0];identifier=mapping.get(glyph)
                    return '<tg-emoji emoji-id="'+identifier+'">'+escape(glyph,quote=False)+'</tg-emoji>' if identifier else ''
                self.parts.append(_EMOJI.sub(replace,escape(part,quote=False)))
    p=Renderer();p.feed(body);p.close();p.close_all();return ''.join(p.parts)


def prompt_hint():
    return '\nEMOJI POLICY: only use these glyphs from the verified nowemoji, IconsInTg and Salavatsteklo sets: '+', '.join(palette(None))+'. Company artwork takes priority when glyphs overlap. Do not use any other ordinary emoji. The bot converts these glyphs to real Premium entities; never write tg-emoji tags or IDs yourself. For a normal editorial post, choose 1-3 context-relevant glyphs from this list, including one near the opening or key action. A sensitive or strictly technical notice may omit them. Never use square bullets or decorate every list item. If no suitable symbol exists, use no emoji.'


def menu(chat):
    import telegram_bot as b,bot_features
    previous=b.context(chat)
    if previous.get('mode')!='emoji_palette':b.set_context(chat,{'mode':'emoji_palette','previous':previous})
    values=palette(chat)
    enabled=bot_features.preferences(chat).get('premium_emoji',True)
    text='<b>Эмодзи для постов</b>\n\nnowemoji · IconsInTg · Salavatsteklo\n\nЕсли символ есть в нескольких наборах, выбираем фирменный. Посторонние эмодзи убираются.\n\nВ личке и подключённой группе доступны Premium-эмодзи; в канале без Fragment отправляем текст без них. Анимация работает в Telegram.'
    return b.say(chat,text,inline=[[b.btn('В личке: '+('включено' if enabled else 'выключено'),'feat_emoji_toggle')],[b.btn('К настройкам','feat_emoji_close')]],formatted=True)


def callback(chat,data):
    import telegram_bot as b,bot_features
    if data=='feat_emoji_close':
        pending=b.context(chat)
        if pending.get('mode')=='emoji_palette':b.set_context(chat,pending.get('previous',{}))
        return bot_features.settings(chat)
    if data=='feat_emoji_toggle':
        with app.db() as con:
            row=con.execute('SELECT data FROM bot_preferences WHERE chat=?',(chat,)).fetchone()
            prefs=json.loads(row['data']) if row else {};prefs['premium_emoji']=not prefs.get('premium_emoji',True)
            con.execute('INSERT OR REPLACE INTO bot_preferences VALUES(?,?)',(chat,json.dumps(prefs)))
    return menu(chat)


def receive(chat,msg):
    import telegram_bot as b
    mode=b.context(chat).get('mode')=='emoji_palette'
    text=msg.get('text',msg.get('caption',''))
    entities=msg.get('entities',msg.get('caption_entities',[]))
    custom=[e for e in entities if e.get('type')=='custom_emoji' and re.fullmatch(r'[0-9]{1,25}',str(e.get('custom_emoji_id','')))]
    raw=text.encode('utf-16-le');remainder=raw
    for e in sorted(custom,key=lambda e:e['offset'],reverse=True):remainder=remainder[:e['offset']*2]+remainder[(e['offset']+e['length'])*2:]
    standalone=bool(custom and isinstance(msg.get('text'),str) and not remainder.decode('utf-16-le',errors='ignore').strip())
    if not mode and not standalone:return False
    if not custom:raise ValueError('В сообщении нет Premium-эмодзи. Перешлите сообщение с ними или вернитесь к настройкам.')
    ids=list(dict.fromkeys(e['custom_emoji_id'] for e in custom))[:50]
    stickers=b.tg('getCustomEmojiStickers',{'custom_emoji_ids':ids})
    if any(s.get('set_name') not in PACKS for s in stickers):
        raise ValueError('Разрешены наборы nowemoji, IconsInTg и Salavatsteklo.')
    store(chat,stickers)
    menu(chat)
    return True


def render_publication(body,owner,target):
    """Premium only for the explicitly verified group; channels keep safe fallback."""
    import os
    group=os.environ.get('TELEGRAM_PREMIUM_GROUP_ID','').strip()
    if group and str(target)==group:
        return render_private(body,owner)
    return remove_emoji(post_format.normalize(body))
