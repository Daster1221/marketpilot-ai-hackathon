"""One paid illustration per new AI draft; local assets shared by bot and Mini App."""
import base64
import ipaddress
import json
import os
from pathlib import Path
import socket
import urllib.request
from urllib.parse import urlsplit
import app
import post_format
import brand_visual
import secrets, time

MODEL = 'openai/gpt-image-2.6-flare'
MAX_BYTES = 10_000_000
RULES = ('Create the COMPLETE finished square social-media poster described below, '
         'including all specified Russian typography, panels, factual chips and graphic composition. '
         'Render quoted Cyrillic text accurately and legibly; no extra words. '
         'Do not draw a logo, watermark, AI label, outer mockup or design instructions. '
         'No logo will be added: no reserved logo space, blank rectangle or placeholder. '
         'No ambient signage or incidental lettering; only the specified text. Do not imply actual employee or factory photography.')


def init_db(con):
    con.execute('CREATE TABLE IF NOT EXISTS bot_visual_reviews(post INTEGER PRIMARY KEY,decision TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS bot_image_jobs(post INTEGER PRIMARY KEY,state TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS bot_visual_attempts(key TEXT PRIMARY KEY,post INTEGER,rev INTEGER,state TEXT,created REAL,decision TEXT)')
    con.execute('CREATE UNIQUE INDEX IF NOT EXISTS one_active_visual ON bot_visual_attempts(post) WHERE state="running"')


def local_path(value):
    """Accept only generated assets inside our private directory."""
    root = (app.ROOT / 'data' / 'generated_images').resolve()
    path = Path(value).resolve()
    return path if path.is_relative_to(root) and path.suffix in ('.png', '.jpg', '.webp') and path.is_file() else None


def payload(value):
    return {'_photo_path':str(path)} if (path := local_path(value)) else {'photo':value}


def attach_many(chat, ids, profile='', instruction=''):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(lambda pid:attach(chat,pid,profile,instruction),ids))


def refresh_cover(chat, post_id):
    try:return _refresh_cover(chat,post_id)
    except Exception:
        # A saved text must survive renderer failure; avoid publishing stale facts.
        import bot_features
        old=bot_features.image_for(post_id)
        if local_path(old):
            with app.db() as con:
                removed=con.execute('DELETE FROM bot_post_images WHERE post=? AND file_id=? AND EXISTS(SELECT 1 FROM bot_posts WHERE id=? AND chat=? AND status IN ("draft","approved"))',(post_id,old,post_id,chat)).rowcount
                if removed:con.execute('UPDATE bot_posts SET status="draft" WHERE id=? AND chat=? AND status="approved"',(post_id,chat))
        return False


def _refresh_cover(chat, post_id):
    """Update cover typography after text edits, without a paid image request."""
    import bot_features, post_cover
    previous=bot_features.image_for(post_id)
    if not local_path(previous):return False  # Never replace a user's photo.
    with app.db() as con:
        p=con.execute('SELECT * FROM bot_posts WHERE id=? AND chat=? AND status IN ("draft","approved")',(post_id,chat)).fetchone()
        review=con.execute('SELECT decision FROM bot_visual_reviews WHERE post=?',(post_id,)).fetchone()
    if not p:return False
    folder=app.ROOT/'data'/'generated_images'
    decision=json.loads(review['decision']) if review else brand_visual.brief(p['topic'],p['body'])
    if decision.get('director',{}).get('render_mode') in ('generated_poster','directed_layout'):
        import hashlib
        if decision['director'].get('body_hash')!=hashlib.sha256(p['body'].encode()).hexdigest():
            decision['image_text_needs_review']=True
            with app.db() as con:
                con.execute('UPDATE bot_visual_reviews SET decision=? WHERE post=?',(json.dumps(decision,ensure_ascii=False),post_id))
                row=con.execute('SELECT warnings FROM bot_post_review WHERE post=?',(post_id,)).fetchone()
                if row:
                    warnings=json.loads(row['warnings'] or '[]')
                    note='Текст поста изменён: проверьте надписи на обложке. Для их изменения используйте «Изменить изображение»; это новая генерация.'
                    if note not in warnings:warnings.append(note)
                    con.execute('UPDATE bot_post_review SET warnings=? WHERE post=?',(json.dumps(warnings,ensure_ascii=False),post_id))
        return False
    scene=local_path(str(folder/decision.get('scene_file',''))) if decision.get('scene_file') else None
    if scene is None:scene=next((f for f in folder.glob(str(post_id)+'-scene.*') if local_path(str(f))),None)
    # Older generated illustrations have no separate scene file yet.
    if scene is None:
        if '-cover' in Path(previous).stem:return False
        source=Path(previous);scene=folder/(str(post_id)+'-scene'+source.suffix)
        scene.write_bytes(source.read_bytes())
    raw=post_cover.render(scene.read_bytes(),p['topic'],p['body'],decision)
    path=folder/(str(post_id)+'-r'+str(p['rev'])+'-cover.png');path.write_bytes(raw)
    with app.db() as con:
        if not con.execute('SELECT 1 FROM bot_posts WHERE id=? AND chat=? AND rev=? AND status IN ("draft","approved")',(post_id,chat,p['rev'])).fetchone():return False
        changed=con.execute('UPDATE bot_post_images SET file_id=? WHERE post=? AND file_id=?',(str(path.resolve()),post_id,previous)).rowcount
        if changed:con.execute('INSERT OR REPLACE INTO bot_visual_reviews VALUES(?,?)',(post_id,json.dumps(decision,ensure_ascii=False)))
    return bool(changed)


def decode_image(result):
    item = result['data'][0]
    if item.get('b64_json'):
        encoded = item['b64_json']
        if len(encoded) > MAX_BYTES * 4 // 3 + 8: raise ValueError('Изображение слишком большое.')
        raw = base64.b64decode(encoded, validate=True)
    else:
        url = item.get('url', '')
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.port not in (None,443):
            raise ValueError('Некорректный адрес изображения.')
        addresses = socket.getaddrinfo(parsed.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError('Недопустимый адрес изображения.')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs): return None
        with urllib.request.build_opener(NoRedirect).open(url, timeout=45) as response:
            raw = response.read(MAX_BYTES+1)
    if not 1 <= len(raw) <= MAX_BYTES: raise ValueError('Некорректный размер изображения.')
    suffix = '.png' if raw.startswith(b'\x89PNG\r\n\x1a\n') else '.jpg' if raw.startswith(b'\xff\xd8\xff') else '.webp' if raw[:4]==b'RIFF' and raw[8:12]==b'WEBP' else ''
    if not suffix: raise ValueError('API вернуло неподдерживаемое изображение.')
    return raw,suffix


def generate_image(prompt,decision):
    """Use the customer's actual reference card when available, not just adjectives."""
    ref_name=decision.get('director',{}).get('reference') or ('sports' if decision.get('content_type')=='sports' else 'recognition')
    folder=app.ROOT/'assets'/'visual-references'
    reference=folder/(ref_name+'.jpg')
    if not reference.is_file():reference=folder/(ref_name+'.png')
    model=os.environ.get('IMAGE_MODEL',MODEL).strip() or MODEL
    decision['image_model']=model
    if not reference.is_file():
        raise ValueError('Не найден визуальный референс. Платный запрос не отправлен.')
    prompt=('Create a NEW complete designed social-media poster, using the attached full-resolution '
            'artwork as the visual quality and art-direction reference. Match the designed density, '
            'expressive type hierarchy, photographic depth, brush textures and carefully integrated '
            'teal/white/yellow graphic elements. Adapt the scene and composition to the new subject. '
            'This is a finished flat artwork, not a photograph of a poster or a design tutorial. '
            'Replace ALL original lettering with ONLY the new exact copy below. Do not retain any '
            'reference logo, emblem, dates, numbers, people identity or unrelated objects. '
            'No logo, watermark, AI disclosure footer or empty logo placeholder. '
            'Preserve Russian spelling and spaces between words. Keep all type inside safe margins.\n'+prompt)
    boundary='MarketPilotArt'+secrets.token_hex(16)
    fields={'model':model,'prompt':prompt,'size':'1024x1024'}
    parts=[]
    for name,value in fields.items():
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode('utf-8'))
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="image"; filename="reference{reference.suffix}"\r\nContent-Type: {"image/jpeg" if reference.suffix==".jpg" else "image/png"}\r\n\r\n'.encode())
    parts.extend([reference.read_bytes(),f'\r\n--{boundary}--\r\n'.encode()])
    request=urllib.request.Request(app.ai_base_url()+'/images/edits',b''.join(parts),{'Authorization':'Bearer '+os.environ['DEEPSEEK_API_KEY'],'Content-Type':'multipart/form-data; boundary='+boundary})
    with urllib.request.urlopen(request,timeout=180) as response:result=json.load(response)
    decision['style_reference']=reference.name
    return result


def attach(chat,post_id,profile='',instruction=''):
    # profile is deliberately not sent to the art director or FLUX.
    return _generate(chat,post_id,instruction=instruction,key='initial:'+str(post_id))


def regenerate(chat,post_id,rev,instruction,key):
    if not isinstance(instruction,str) or not 1<=len(instruction.strip())<=1200:
        raise ValueError('Опишите изменение изображения, до 1200 символов.')
    if not _generate(chat,post_id,instruction=instruction.strip(),key='edit:'+str(chat)+':'+key,replace=True,expected_rev=rev):
        raise ValueError('Новое изображение не сохранено. Проверьте заметки поста; текст и прежняя картинка сохранены.')


def _generate(chat,post_id,*,instruction,key,replace=False,expected_rev=None):
    import art_director,bot_features,post_cover
    with app.db() as con:
        con.execute('BEGIN IMMEDIATE');init_db(con)
        p=con.execute('SELECT * FROM bot_posts WHERE id=? AND chat=? AND status IN ("draft","approved")',(post_id,chat)).fetchone()
        if not p or (expected_rev is not None and p['rev']!=expected_rev):return False
        image=con.execute('SELECT file_id FROM bot_post_images WHERE post=?',(post_id,)).fetchone()
        if image and not replace:return False
        old_image=image['file_id'] if image else ''
        prior=con.execute('SELECT decision FROM bot_visual_reviews WHERE post=?',(post_id,)).fetchone()
        previous=json.loads(prior['decision']).get('director') if prior else None
        decision=brand_visual.brief(p['topic'],p['body'],instruction)
        if decision['media_mode']=='NO_VISUAL':
            con.execute('INSERT OR REPLACE INTO bot_visual_reviews VALUES(?,?)',(post_id,json.dumps(decision,ensure_ascii=False)))
            return False
        con.execute('UPDATE bot_visual_attempts SET state="interrupted" WHERE state="running" AND created<?',(time.time()-600,))
        if not con.execute('INSERT OR IGNORE INTO bot_visual_attempts VALUES(?,?,?,"running",?,"{}")',(key,post_id,p['rev'],time.time())).rowcount:return False
    try:
        # One small, separately pinned DeepSeek call; no profile, chat or text history.
        director=art_director.plan(p['topic'],p['body'],instruction if replace else '',previous if replace else None)
        decision['director']=director
        if director.get('render_mode')=='directed_layout':
            decision['art_direction']=director['concept']
            decision['layout']='directed_layout'
            decision['preflight']=director['preflight']
        with app.db() as con:
            con.execute('UPDATE bot_visual_attempts SET decision=? WHERE key=?',(json.dumps(decision,ensure_ascii=False),key))
            # Do not pay FLUX if the text/photo was already changed during planning.
            current=con.execute('SELECT rev,body,topic FROM bot_posts WHERE id=? AND chat=? AND status IN ("draft","approved")',(post_id,chat)).fetchone()
            if not current or current['rev']!=p['rev'] or current['body']!=p['body'] or current['topic']!=p['topic']:
                con.execute('UPDATE bot_visual_attempts SET state="superseded" WHERE key=?',(key,));return False
        if director.get('render_mode')=='directed_layout':
            prompt='Generate ONLY the visual scene, no letters, words, numbers, panels, logos or watermark. No mockup or poster inside the scene.\n'+director['prompt']
        else:
            prompt=RULES+'\n'+director['prompt']
            if director.get('texts'):prompt+='\nEXACT TEXT TO PRINT:\n'+json.dumps(director['texts'],ensure_ascii=False)
        result=generate_image(prompt,decision)
        raw,suffix=decode_image(result)
        folder=app.ROOT/'data'/'generated_images';folder.mkdir(parents=True,exist_ok=True)
        token=secrets.token_hex(6)
        scene=folder/(str(post_id)+'-'+token+'-scene'+suffix);scene.write_bytes(raw)
        decision['scene_file']=scene.name
        cover=post_cover.render(raw,p['topic'],p['body'],decision)
        path=folder/(str(post_id)+'-r'+str(p['rev']+1)+'-'+token+'-cover.png');path.write_bytes(cover)
        with app.db() as con:
            con.execute('BEGIN IMMEDIATE')
            current=con.execute('SELECT rev,body,topic FROM bot_posts WHERE id=? AND chat=? AND status IN ("draft","approved")',(post_id,chat)).fetchone()
            attached=con.execute('SELECT file_id FROM bot_post_images WHERE post=?',(post_id,)).fetchone()
            if not current or current['rev']!=p['rev'] or current['body']!=p['body'] or current['topic']!=p['topic'] or (attached['file_id'] if attached else '')!=old_image:
                con.execute('UPDATE bot_visual_attempts SET state="superseded" WHERE key=?',(key,));return False
            con.execute('INSERT OR REPLACE INTO bot_post_images VALUES(?,?)',(post_id,str(path.resolve())))
            con.execute('UPDATE bot_posts SET image_prompt=?,rev=rev+1,status="draft" WHERE id=?',(prompt,post_id))
            if con.execute('SELECT 1 FROM sqlite_master WHERE name="mini_edit_memory"').fetchone():
                con.execute('UPDATE mini_edit_memory SET rev=? WHERE post=? AND rev=?',(p['rev']+1,post_id,p['rev']))
            con.execute('DELETE FROM bot_confirmations WHERE post=?',(post_id,))
            con.execute('INSERT OR REPLACE INTO bot_visual_reviews VALUES(?,?)',(post_id,json.dumps(decision,ensure_ascii=False)))
            con.execute('UPDATE bot_visual_attempts SET state="done",decision=? WHERE key=?',(json.dumps(decision,ensure_ascii=False),key))
            row=con.execute('SELECT warnings FROM bot_post_review WHERE post=?',(post_id,)).fetchone()
            if row and director.get('render_mode')=='generated_poster':
                warnings=[w for w in json.loads(row['warnings'] or '[]') if not w.startswith('Текст поста изменён: проверьте надписи на обложке.')]
                note='Обложка сгенерирована целиком: проверьте написание русских надписей и факты перед отправкой.'
                if note not in warnings:warnings.append(note)
                con.execute('UPDATE bot_post_review SET warnings=? WHERE post=?',(json.dumps(warnings,ensure_ascii=False),post_id))
            import telegram_bot as bot
            bot.remember_version(con,post_id,p['rev']+1,p['body'],'Новый вариант изображения','image')
        return True
    except Exception as error:
        with app.db() as con:
            con.execute('UPDATE bot_visual_attempts SET state=? WHERE key=?',('failed:'+type(error).__name__+':'+str(getattr(error,'code','')),key))
            row=con.execute('SELECT warnings FROM bot_post_review WHERE post=?',(post_id,)).fetchone()
            if row:
                warnings=json.loads(row['warnings'] or '[]')
                warning='Новое изображение не получено. Текст и прежняя картинка сохранены; автоматического платного повтора не будет.'
                if warning not in warnings:warnings.append(warning)
                con.execute('UPDATE bot_post_review SET warnings=? WHERE post=?',(json.dumps(warnings,ensure_ascii=False),post_id))
        return False
