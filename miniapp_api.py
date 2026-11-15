"""Authenticated Mini App API sharing the Telegram bot's SQLite records."""
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import parse_qsl
import app
import telegram_bot as bot
import post_format
import editorial
import model_selection

POOL = ThreadPoolExecutor(max_workers=3)
LOCAL_TZ = timezone(timedelta(hours=5), 'Asia/Yekaterinburg')
REGISTERED_HOSTS = set()


def register_origin(url):
    from urllib.parse import urlsplit
    value=urlsplit(url)
    if value.scheme=='https' and value.hostname:
        REGISTERED_HOSTS.add(value.netloc)


def origin_allowed(origin, host):
    from urllib.parse import urlsplit
    if not origin:
        return True
    value=urlsplit(origin)
    configured=urlsplit(os.environ.get('MINI_APP_URL',''))
    # A valid Telegram signature is still mandatory. Host binds browser writes
    # to the actual page, even while a tunnel rotates between two live aliases.
    return value.scheme in ('https','http') and not value.username and not value.password and bool(value.netloc) and (value.netloc in (host,configured.netloc) or value.netloc in REGISTERED_HOSTS)


def init_db():
    with app.db() as con:
        exists = con.execute("SELECT 1 FROM sqlite_master WHERE name='bot_sessions'").fetchone()
    if not exists:
        bot.init_db()
    with app.db() as con:
        import bot_features, company_knowledge
        bot_features.init_db(con)
        company_knowledge.init_db(con)
        __import__('marketer').init_db(con)
        con.execute('CREATE TABLE IF NOT EXISTS mini_workflows (id TEXT PRIMARY KEY,chat INTEGER,task TEXT,clarification TEXT,plan TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS mini_jobs (id TEXT PRIMARY KEY,chat INTEGER,request_key TEXT,status TEXT,result TEXT,created REAL,UNIQUE(chat,request_key))')
        con.execute('CREATE INDEX IF NOT EXISTS mini_jobs_chat_created ON mini_jobs(chat,created DESC)')
        con.execute('CREATE INDEX IF NOT EXISTS bot_posts_chat_id ON bot_posts(chat,id DESC)')
        con.execute('CREATE TABLE IF NOT EXISTS mini_edit_memory (post INTEGER PRIMARY KEY,rev INTEGER,memory TEXT)')
        con.execute('CREATE TABLE IF NOT EXISTS bot_post_schedule (post INTEGER PRIMARY KEY,chat INTEGER,due TEXT)')
        con.execute('UPDATE mini_jobs SET status="failed",result=? WHERE status IN ("queued","running")', (json.dumps({'detail':'Обработка прервана перезапуском. Проверьте сохранённые посты перед повтором.'},ensure_ascii=False),))


def authenticate(raw):
    if not isinstance(raw,str) or not raw or len(raw)>16000:
        raise PermissionError('Откройте Mini App кнопкой в Telegram.')
    pairs=parse_qsl(raw,keep_blank_values=True)
    if len({k for k,v in pairs})!=len(pairs):
        raise PermissionError('Некорректная сессия Telegram.')
    fields=dict(pairs); supplied=fields.pop('hash','')
    secret=hmac.new(b'WebAppData',os.environ.get('TELEGRAM_BOT_TOKEN','').encode(),hashlib.sha256).digest()
    expected=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(fields.items())).encode(),hashlib.sha256).hexdigest()
    if not os.environ.get('TELEGRAM_BOT_TOKEN') or not hmac.compare_digest(expected,supplied):
        raise PermissionError('Не удалось проверить сессию Telegram. Закройте и откройте приложение.')
    try:
        age=time.time()-int(fields['auth_date']); user=json.loads(fields['user']); chat=int(user['id'])
        if age < -60 or age>86400 or str(chat) not in bot.allowed_user_ids():
            raise ValueError()
    except (ValueError,KeyError,TypeError):
        raise PermissionError('Сессия истекла или нет доступа к этому боту.') from None
    __import__('user_access').observe(user)
    return chat


def post(chat, post_id, con=None):
    if con is None:
        with app.db() as db:
            return post(chat,post_id,db)
    row=con.execute('SELECT * FROM bot_posts WHERE id=? AND chat=?',(post_id,chat)).fetchone()
    if not row:
        raise ValueError('Пост не найден.')
    return dict(row)


def serialize(p,metadata=None,*,summary=False):
    statuses={'draft':'DRAFT','approved':'APPROVED','published':'PUBLISHED','cancelled':'CANCELLED','publishing':'SENDING','delivery_unknown':'FAILED'}
    if metadata is None:
        with app.db() as con:
            row=con.execute('SELECT s.due,i.file_id,r.warnings,d.state AS delivery_state,d.rev AS delivery_rev FROM bot_posts p LEFT JOIN bot_post_schedule s ON s.post=p.id AND s.chat=p.chat LEFT JOIN bot_post_images i ON i.post=p.id LEFT JOIN bot_post_review r ON r.post=p.id LEFT JOIN bot_delivery_schedule d ON d.post=p.id AND d.chat=p.chat WHERE p.id=? AND p.chat=?',(p['id'],p['chat'])).fetchone()
        metadata=dict(row) if row else {}
    due=metadata.get('due');planned=bool(due and p['status'] in ('draft','approved'))
    result={'id':p['id'],'title':p['topic'],'rev':p['rev'],'status':'SCHEDULED' if planned else statuses.get(p['status'],'DRAFT'),'platform':'telegram','due':due,'plan_id':p['id'] if due else None,'has_image':bool(metadata.get('file_id'))}
    if metadata.get('delivery_state')=='queued' and metadata.get('delivery_rev')==p['rev'] and p['status']=='approved':result['status']='QUEUED'
    result['delivery_state']=metadata.get('delivery_state')
    if result['delivery_state']=='queued' and result['status']!='QUEUED':result['delivery_state']='needs_review'
    if not summary:
        import premium_emoji
        result.update(body=p['body'],body_html=premium_emoji.render_private(post_format.normalize(p['body']),p['chat']),warnings=json.loads(metadata.get('warnings') or '[]'))
        with app.db() as con:
            visual=con.execute('SELECT decision FROM bot_visual_reviews WHERE post=?',(p['id'],)).fetchone()
        if visual:result['visual']=json.loads(visual['decision'])
    return result


def image(chat,pid):
    post(chat,pid)
    import bot_features
    from urllib.request import urlopen
    file_id=bot_features.image_for(pid)
    if not file_id: raise ValueError('Фото не найдено.')
    import post_images, mimetypes
    local=post_images.local_path(file_id)
    if local:
        return local.read_bytes(),mimetypes.guess_type(str(local))[0]
    info=bot.tg('getFile',{'file_id':file_id})
    path=info.get('file_path','')
    if not path.lower().endswith(('.jpg','.jpeg','.png','.webp')): raise ValueError('Фото недоступно.')
    with urlopen('https://api.telegram.org/file/bot'+os.environ['TELEGRAM_BOT_TOKEN']+'/'+path,timeout=20) as response:
        raw=response.read(10_000_001)
    if len(raw)>10_000_000: raise ValueError('Фото слишком большое для просмотра.')
    return raw,'image/png' if path.lower().endswith('.png') else 'image/webp' if path.lower().endswith('.webp') else 'image/jpeg'


def data(chat):
    state=bot.session(chat); answers=json.loads(state['answers'])
    with app.db() as con:
        posts=[dict(r) for r in con.execute('SELECT p.id,p.chat,p.topic,p.status,p.rev,s.due,i.file_id,d.state AS delivery_state,d.rev AS delivery_rev FROM bot_posts p LEFT JOIN bot_post_schedule s ON s.post=p.id AND s.chat=p.chat LEFT JOIN bot_post_images i ON i.post=p.id LEFT JOIN bot_delivery_schedule d ON d.post=p.id AND d.chat=p.chat WHERE p.chat=? ORDER BY p.id DESC LIMIT 500',(chat,))]
    import company_knowledge
    knowledge=company_knowledge.get(chat)
    site=bot.company_site(state)
    rendered=[serialize(p,p,summary=True) for p in posts]
    return {'posts':rendered, 'counts':{'created':len(posts),'published':sum(p['status']=='published' for p in posts),'scheduled':sum(p['status'] in ('SCHEDULED','QUEUED') for p in rendered),'failed':sum(p['status']=='delivery_unknown' for p in posts)},'profile':{'can_manage_users':chat in __import__('user_access').admin_ids(),'model':model_selection.model_for(chat),'model_options':list(model_selection.MODELS),'audience':answers.get('audience',''),'tone':answers.get('style',''),'goals':answers.get('objective',''),'company':answers.get('company',''),'site':site,'summary':knowledge['summary'] if knowledge and knowledge['url']==site else '', 'accounts':[],'notifications':True},'sources':[{'title':'Сайт компании','url':site}] if site else [],'timezone':'Asia/Yekaterinburg'}


def save_generated(chat,wf,result):
    ids=[]; profile=bot.brief(bot.session(chat))
    with app.db() as con:
        for p in result['posts']:
            cur=con.execute('INSERT INTO bot_posts(chat,topic,body,image_prompt,source) VALUES(?,?,?,?,"deepseek")',(chat,p['topic'],p['body'],p.get('image_prompt','')))
            pid=cur.lastrowid;ids.append(pid)
            bot.remember_version(con,pid,1,p['body'])
            if p.get('due'):
                con.execute('INSERT INTO bot_post_schedule VALUES(?,?,?)',(pid,chat,p['due']))
            con.execute('INSERT INTO bot_post_context VALUES(?,?,?,?)',(pid,profile,wf['task'],wf['clarification']))
            con.execute('INSERT INTO bot_post_review(post,warnings,brand_name_mode,publication_date,fact_blocks) VALUES(?,?,?,?,?)',(pid,json.dumps(p.get('warnings',[]),ensure_ascii=False),p.get('brand_name_mode','brandbook'),p.get('publication_date'),json.dumps(p.get('fact_blocks',[]),ensure_ascii=False)))
    if wf.get('task')!='Ручной черновик из Mini App':
        import post_images
        post_images.attach_many(chat,ids,profile,wf['task']+'\n'+wf['clarification'])
    return [serialize(post(chat,pid)) for pid in ids]


def workflow(chat,request):
    with model_selection.for_chat(chat):return _workflow(chat,request)


def _workflow(chat,request):
    operation=request.get('operation')
    if operation=='marketer':return __import__('marketer').ask(chat,request.get('text',''))
    if operation=='document':return __import__('company_documents').ingest(chat,request.get('filename',''),request.get('document',b''))
    if operation=='document_delete':
        __import__('company_documents').delete(chat,int(request.get('document_id',0)))
        return {'documents':__import__('company_documents').listing(chat)}
    if operation=='plan_topic':
        selected=__import__('marketer').plan_topic(chat,request.get('plan_nonce',''),request.get('topic_index'))
        wf={'id':secrets.token_hex(16),'chat':chat,**selected,'plan':'{}'}
        result=app.plan_publication(bot.brief(bot.session(chat)),wf['task'],wf['clarification'])
        wf['plan']=json.dumps(result,ensure_ascii=False)
        with app.db() as con:con.execute('INSERT INTO mini_workflows VALUES(?,?,?,?,?)',(wf['id'],chat,wf['task'],wf['clarification'],wf['plan']))
        return {'workflow_id':wf['id'],'task':wf['task'],**result}
    if operation=='image':
        import post_images
        p=post(chat,int(request.get('post_id',0)))
        post_images.regenerate(chat,p['id'],request.get('rev'),request.get('instruction',''),request.get('request_id') or secrets.token_hex(16))
        return {'posts':[serialize(post(chat,p['id']))]}
    if operation in ('schedule','unschedule'):
        import scheduling
        pid=int(request.get('post_id',0));rev=request.get('rev')
        if operation=='schedule':scheduling.schedule(chat,pid,rev,request.get('due',''))
        else:scheduling.cancel(chat,pid,rev)
        return {'posts':[serialize(post(chat,pid))],'scheduled':operation=='schedule'}
    if operation=='transcribe':
        import speech
        raw=request.get('audio')
        if not isinstance(raw,bytes) or not 1<=len(raw)<=speech.MAX_AUDIO_BYTES:
            raise ValueError('Запись должна быть не больше 5 МБ.')
        return {'transcript':speech.transcribe(raw,filename='voice.webm',content_type=request.get('content_type','audio/webm'))}
    if operation=='calendar_plan':
        task=str(request.get('task','')).strip()
        if not 1<=len(task)<=6000: raise ValueError('Опишите тему и число постов.')
        import re
        count=app.requested_count(task) if re.search(r'(\d+|один|два|три|четыре|пять)\s+пост',task,re.I) else 3
        now=datetime.now(LOCAL_TZ)
        profile=bot.brief(bot.session(chat))
        result=app.ai_json(editorial.RULES+editorial.editorial_voice.company_instruction(profile,task)+post_format.AI_FORMAT_RULES+'\nСоздай контент-план и СРАЗУ напиши ровно count готовых черновиков. Один ответ JSON {"posts":[{"topic":"тема","body":"HTML-пост","due":"ISO 8601 с часовым поясом","warnings":[]}]}. Сам выбери будущие даты и время с учётом текущего времени, запроса, периода и ритма публикаций. По умолчанию распределяй посты на ближайшую неделю. Не придумывай события, скидки, достижения и факты: опирайся на профиль, для недостающих сведений предложи нейтральную информационную тему. Не заявляй о публикации или согласовании. Все результаты только черновики в календаре.',{'profile':profile,'task':task,'count':count,'current_datetime':now.isoformat(),'current_date':now.date().isoformat(),'timezone':'Asia/Yekaterinburg'})
        posts=result.get('posts')
        if not isinstance(posts,list) or len(posts)!=count: raise ValueError('Не удалось получить нужное число постов. Повторите создание плана.')
        prepared=[]
        for p in posts:
            if not isinstance(p,dict) or any(not isinstance(p.get(k),str) or not p[k].strip() for k in ('topic','body','due')):
                raise ValueError('В плане не хватает текста или даты. Повторите запрос.')
            try:
                due=datetime.fromisoformat(p['due'].replace('Z','+00:00'))
                due=due.replace(tzinfo=LOCAL_TZ) if due.tzinfo is None else due.astimezone(LOCAL_TZ)
                if due<=now or due>now+timedelta(days=366): raise ValueError()
            except ValueError:
                raise ValueError('AI предложил некорректную или прошедшую дату. Уточните период плана и повторите.') from None
            body,notes,blocks=editorial.clean_body(p['body'],profile+'\n'+task,publication_date=due.date().isoformat(),return_blocks=True)
            prepared.append({'topic':p['topic'][:150],'body':body,'due':due.isoformat(),'warnings':editorial.warnings_list(p.get('warnings'))+notes,'fact_blocks':blocks,'brand_name_mode':editorial.brand_mode(),'publication_date':due.date().isoformat()})
        return {'posts':save_generated(chat,{'task':task,'clarification':'Даты контент-плана выбраны AI; публикация не выполнялась.'},{'posts':prepared}),'calendar':True}
    if operation=='manual':
        body=request.get('body'); title=request.get('title')
        if not isinstance(body,str) or not 1<=post_format.length(body)<=4096 or not isinstance(title,str) or not title.strip():
            raise ValueError('Укажите заголовок и текст поста до 4096 символов.')
        wf={'task':'Ручной черновик из Mini App','clarification':''}
        return {'posts':save_generated(chat,wf,{'posts':[{'topic':title[:150],'body':post_format.normalize(body)}]})}
    if operation=='rewrite':
        p=post(chat,int(request.get('post_id',0)))
        if p['rev']!=request.get('rev') or p['status'] not in ('draft','approved'):
            raise ValueError('Пост изменился в боте. Откройте актуальную версию.')
        instruction=str(request.get('instruction','')).strip()
        if not 1<=len(instruction)<=4000:
            raise ValueError('Опишите правку, до 4000 символов.')
        review=bot.review_metadata(p['id'])
        with app.db() as con:
            memo=con.execute('SELECT * FROM mini_edit_memory WHERE post=?',(p['id'],)).fetchone()
        result=app.rewrite_post(bot.edit_brand_rules(bot.session(chat)),p['body'],instruction,memory=memo['memory'] if memo and memo['rev']==p['rev'] else '',brand_name_mode=review['brand_name_mode'],publication_date=review['publication_date'],fact_blocks=review['fact_blocks'])
        with app.db() as con:
            changed=con.execute('UPDATE bot_posts SET body=?,rev=rev+1,status="draft" WHERE id=? AND chat=? AND rev=? AND status IN ("draft","approved")',(result['body'],p['id'],chat,p['rev'])).rowcount
            if not changed:
                raise ValueError('Пост изменился во время обработки. Правки не перезаписаны.')
            bot.remember_version(con,p['id'],p['rev'],p['body'])
            bot.remember_version(con,p['id'],p['rev']+1,result['body'],instruction,'rewrite')
            con.execute('INSERT OR REPLACE INTO mini_edit_memory VALUES(?,?,?)',(p['id'],p['rev']+1,result['memory']))
            con.execute('DELETE FROM bot_confirmations WHERE post=?',(p['id'],))
            con.execute('INSERT OR REPLACE INTO bot_post_review VALUES(?,?,?,?,?)',(p['id'],json.dumps(result['warnings'],ensure_ascii=False),result['brand_name_mode'],result['publication_date'],json.dumps(result['fact_blocks'],ensure_ascii=False)))
        __import__('post_images').refresh_cover(chat,p['id'])
        return {'posts':[serialize(post(chat,p['id']))]}
    if operation not in ('plan','generate'):
        raise ValueError('Неизвестная операция.')
    wid=request.get('workflow_id')
    with app.db() as con:
        row=con.execute('SELECT * FROM mini_workflows WHERE id=? AND chat=?',(wid,chat)).fetchone() if wid else None
    if wid and not row:
        raise ValueError('Задача не найдена. Начните создание заново.')
    if row:
        wf=dict(row)
    else:
        task=str(request.get('task','')).strip()
        if not 1<=len(task)<=6000:
            raise ValueError('Опишите событие, до 6000 символов.')
        wf={'id':secrets.token_hex(12),'chat':chat,'task':task,'clarification':'','plan':'{}'}
    clarification=str(request.get('clarification','')).strip()
    if len(clarification)>4000:
        raise ValueError('Сократите уточнение до 4000 символов.')
    if clarification:
        if not wf['clarification'].endswith(clarification):
            wf['clarification']='\n'.join(x for x in (wf['clarification'],clarification) if x)[-14000:]
    with app.db() as con:
        con.execute('INSERT OR REPLACE INTO mini_workflows VALUES(?,?,?,?,?)',(wf['id'],chat,wf['task'],wf['clarification'],wf['plan']))
    profile=bot.brief(bot.session(chat))
    if operation=='plan':
        result=app.plan_publication(profile,wf['task'],wf['clarification'])
        wf['plan']=json.dumps(result,ensure_ascii=False)
    else:
        plan=json.loads(wf['plan']); index=request.get('idea',0); angle=''
        if plan.get('ideas'):
            if type(index)!=int or not 0<=index<len(plan['ideas']):
                raise ValueError('Выберите предложенную идею.')
            idea=plan['ideas'][index];angle=idea['title']+': '+idea['angle']
        result=app.prepare_posts(profile,wf['task'],wf['clarification'],angle=angle)
        if result.get('posts'):
            result={'posts':save_generated(chat,wf,result)}
    with app.db() as con:
        con.execute('INSERT OR REPLACE INTO mini_workflows VALUES(?,?,?,?,?)',(wf['id'],chat,wf['task'],wf['clarification'],wf['plan']))
    return {'workflow_id':wf['id'],**result}


def enqueue(chat,request):
    key=str(request.get('request_id',''))
    if not 8<=len(key)<=100:
        raise ValueError('Не удалось проверить запрос. Повторите действие.')
    with app.db() as con:
        con.execute('BEGIN IMMEDIATE')
        row=con.execute('SELECT id FROM mini_jobs WHERE chat=? AND request_key=?',(chat,key)).fetchone()
        if row:
            return {'job_id':row['id']}
        active=con.execute('SELECT 1 FROM mini_jobs WHERE chat=? AND status IN ("queued","running") AND created>?',(chat,time.time()-600)).fetchone()
        if active or bot.is_busy(chat):
            raise ValueError('Дождитесь завершения текущей задачи.')
        jid=secrets.token_hex(16)
        con.execute('INSERT INTO mini_jobs VALUES(?,?,?,"queued","{}",?)',(jid,chat,key,time.time()))
    def run():
        try:
            with app.db() as con:
                con.execute('UPDATE mini_jobs SET status="running" WHERE id=?',(jid,))
            result=workflow(chat,request);status='done'
        except ValueError as error:
            result={'detail':str(error)};status='failed'
        except Exception:
            result={'detail':'Не удалось обработать задачу. Проверьте сохранённые посты перед повтором.'};status='failed'
        with app.db() as con:
            con.execute('UPDATE mini_jobs SET status=?,result=? WHERE id=?',(status,json.dumps(result,ensure_ascii=False),jid))
    POOL.submit(run)
    return {'job_id':jid}


def job(chat,jid):
    with app.db() as con:
        row=con.execute('SELECT * FROM mini_jobs WHERE id=? AND chat=?',(jid,chat)).fetchone()
    if not row:
        raise ValueError('Задача не найдена.')
    return {'status':row['status'],'result':json.loads(row['result'])}


def job_request(chat,key):
    with app.db() as con:
        row=con.execute('SELECT id FROM mini_jobs WHERE chat=? AND request_key=?',(chat,key)).fetchone()
    return {'job_id':row['id']} if row else {'job_id':None}


def last_transcript(chat):
    with app.db() as con:
        rows=con.execute('SELECT id,result FROM mini_jobs WHERE chat=? AND status="done" AND created>? ORDER BY created DESC LIMIT 50',(chat,time.time()-86400)).fetchall()
    for row in rows:
        value=json.loads(row['result'])
        if isinstance(value.get('transcript'),str) and value['transcript'].strip():
            return {'job_id':row['id'],'transcript':value['transcript']}
    raise ValueError('За последние сутки нет сохранённой расшифровки.')


def save_post(chat,pid,request):
    p=post(chat,pid); body=request.get('body')
    if p['rev']!=request.get('rev') or p['status'] not in ('draft','approved'):
        raise ValueError('Пост изменился в боте. Откройте актуальную версию.')
    if not isinstance(body,str) or not 1<=post_format.length(body)<=4096:
        raise ValueError('Текст поста должен содержать от 1 до 4096 символов.')
    body=post_format.normalize(body);status='approved' if request.get('approve') is True else 'draft'
    with app.db() as con:
        if not con.execute('UPDATE bot_posts SET body=?,topic=?,status=?,rev=rev+1 WHERE id=? AND chat=? AND rev=? AND status IN ("draft","approved")',(body,str(request.get('title',p['topic']))[:150],status,pid,chat,p['rev'])).rowcount:
            raise ValueError('Пост уже изменён. Обновите карточку.')
        bot.remember_version(con,pid,p['rev'],p['body'])
        bot.remember_version(con,pid,p['rev']+1,body,'Правка в Mini App','replace')
        con.execute('DELETE FROM bot_confirmations WHERE post=?',(pid,))
        con.execute('DELETE FROM mini_edit_memory WHERE post=?',(pid,))
    __import__('post_images').refresh_cover(chat,pid)
    return serialize(post(chat,pid))
