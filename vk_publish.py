"""Independent VK text-only approval and durable delivery, with no blind retries."""
import hashlib,json,os,re,secrets,urllib.parse,urllib.request
import app,post_format,premium_emoji

class VKError(ValueError):pass

def init_db(con):
    con.execute('CREATE TABLE IF NOT EXISTS bot_vk_delivery(post INTEGER PRIMARY KEY,chat INTEGER,rev INTEGER,target TEXT,nonce TEXT,state TEXT,text TEXT,remote_id INTEGER)')

def target():
    value=os.environ.get('VK_GROUP_ID','').strip().lstrip('-')
    if not re.fullmatch(r'[1-9][0-9]{1,15}',value):raise ValueError('Сообщество ВК не настроено.')
    return '-'+value

def configured(chat):
    import telegram_bot as b
    try:target()
    except ValueError:return False
    return bool(os.environ.get('VK_ACCESS_TOKEN') and str(chat) in b.allowed_user_ids())

def call(params):
    data=urllib.parse.urlencode({**params,'v':'5.199','access_token':os.environ['VK_ACCESS_TOKEN']}).encode()
    with urllib.request.urlopen(urllib.request.Request('https://api.vk.com/method/wall.post',data),timeout=30) as response:result=json.load(response)
    if 'error' in result:raise VKError('ВК отклонил публикацию: код '+str(result['error'].get('error_code','?'))+'.')
    return result['response']

def text_only(body):return post_format.plain(premium_emoji.remove_emoji(post_format.normalize(body))).strip()

def owned(con,chat,pid,rev):
    import telegram_bot as b
    if not configured(chat):raise PermissionError('Нет доступа к публикации в ВК.')
    row=con.execute('SELECT * FROM bot_posts WHERE id=? AND chat=?',(pid,chat)).fetchone()
    if not row or row['rev']!=rev or row['status'] not in ('draft','approved','published'):raise ValueError('Пост изменился или отменён. Откройте актуальную версию.')
    if b.session(chat)['editing']==pid:raise ValueError('Сначала завершите правки поста в боте.')
    return row

def status(chat,pid):
    with app.db() as con:
        init_db(con)
        row=con.execute('SELECT state,target,remote_id FROM bot_vk_delivery WHERE post=? AND chat=?',(pid,chat)).fetchone()
    if not row:return {'state':'not_sent'}
    return {'state':row['state'],'url':f'https://vk.ru/wall{row["target"]}_{row["remote_id"]}' if row['state']=='sent' else ''}

def prepare(chat,pid,rev):
    with app.db() as con:
        init_db(con);con.execute('BEGIN IMMEDIATE');p=owned(con,chat,pid,rev)
        old=con.execute('SELECT state FROM bot_vk_delivery WHERE post=?',(pid,)).fetchone()
        if old and old['state'] in ('sent','sending','unknown'):raise ValueError('Этот пост уже отправлен в ВК или требует ручной проверки доставки. Повтор запрещён.')
        text=text_only(p['body'])
        if not text or len(text)>16000:raise ValueError('Текст для ВК пустой или слишком длинный.')
        nonce=secrets.token_hex(6);group=target()
        con.execute('INSERT OR REPLACE INTO bot_vk_delivery(post,chat,rev,target,nonce,state,text) VALUES(?,?,?,?,?,"preview",?)',(pid,chat,rev,group,nonce,text))
    return {'post_id':pid,'rev':rev,'nonce':nonce,'text':text,'community_url':'https://vk.ru/club'+group[1:]}

def publish(chat,pid,rev,nonce):
    with app.db() as con:
        init_db(con);con.execute('BEGIN IMMEDIATE');p=owned(con,chat,pid,rev)
        row=con.execute('SELECT * FROM bot_vk_delivery WHERE post=? AND chat=?',(pid,chat)).fetchone()
        if not row or row['state']!='preview' or row['nonce']!=nonce or row['rev']!=rev or row['target']!=target() or row['text']!=text_only(p['body']):raise ValueError('Подтверждение ВК устарело. Откройте предпросмотр заново.')
        con.execute('UPDATE bot_vk_delivery SET state="sending" WHERE post=?',(pid,))
        text,group=row['text'],row['target']
    guid=hashlib.sha256(f'vk:{chat}:{pid}:{rev}:{group}'.encode()).hexdigest()[:32]
    try:
        result=call({'owner_id':group,'from_group':1,'message':text,'guid':guid})
        remote_id=result.get('post_id')
        if type(remote_id)!=int or remote_id<=0:raise ValueError('Не получен номер публикации.')
    except Exception as error:
        with app.db() as con:con.execute('UPDATE bot_vk_delivery SET state=? WHERE post=?',('failed' if isinstance(error,VKError) else 'unknown',pid))
        if isinstance(error,VKError):raise
        raise ValueError('Доставка в ВК не подтверждена. Проверьте стену вручную; автоматического повтора не будет.') from None
    with app.db() as con:con.execute('UPDATE bot_vk_delivery SET state="sent",remote_id=? WHERE post=?',(remote_id,pid))
    return {'url':f'https://vk.ru/wall{group}_{remote_id}'}

def callback(chat,data):
    import telegram_bot as b
    from html import escape
    parts=data.split(':');action=parts[0];pid=int(parts[1]);rev=int(parts[2])
    if action=='vk_preview':
        p=prepare(chat,pid,rev)
        return b.say(chat,'<b>ВК · только текст</b>\n'+p['community_url']+'\n\nИзображение не отправляется. Выделения и спойлеры станут обычным текстом. Публикация в Telegram не меняется.\n\n'+escape(p['text']),inline=[[b.btn('Опубликовать текст в ВК',f'vk_confirm:{pid}:{rev}:{p["nonce"]}',style='primary')],[b.btn('К посту',f'view:{pid}:{rev}')]],formatted=True)
    if action=='vk_confirm' and len(parts)==4:
        result=publish(chat,pid,rev,parts[3])
        return b.say(chat,'Текст опубликован в ВК.\n'+result['url'],inline=[[b.btn('К посту',f'view:{pid}:{rev}')]])
    raise ValueError('Неизвестное действие ВК.')
