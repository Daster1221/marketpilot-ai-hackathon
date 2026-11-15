"""Persistent bot access; only configured administrators can grant it."""
import os,re
import app

def configured_ids():
    return [int(x) for x in re.split(r'[,;\s]+',os.environ.get('TELEGRAM_OWNER_ID','')) if x.isdecimal()]

def admin_ids():
    explicit=[int(x) for x in re.split(r'[,;\s]+',os.environ.get('TELEGRAM_ADMIN_ID','')) if x.isdecimal()]
    return set(explicit or configured_ids()[:1])

def init_db(con):
    con.execute('CREATE TABLE IF NOT EXISTS bot_access_users(user_id INTEGER PRIMARY KEY,enabled INTEGER NOT NULL,added_by INTEGER)')
    con.execute('CREATE TABLE IF NOT EXISTS bot_user_profiles(user_id INTEGER PRIMARY KEY,username TEXT,first_name TEXT,last_name TEXT)')

def allowed_ids():
    ids=set(map(str,configured_ids()))
    with app.db() as con:
        if con.execute('SELECT 1 FROM sqlite_master WHERE name="bot_access_users"').fetchone():
            ids.update(str(r['user_id']) for r in con.execute('SELECT user_id FROM bot_access_users WHERE enabled=1'))
    return ids

def observe(user):
    uid=user.get('id')
    if not isinstance(uid,int) or uid<=0:return
    values=[str(user.get(k,'') or '')[:80] for k in ('username','first_name','last_name')]
    with app.db() as con:
        init_db(con)
        con.execute('INSERT OR REPLACE INTO bot_user_profiles VALUES(?,?,?,?)',(uid,*values))

def require_admin(actor):
    if actor not in admin_ids():raise PermissionError('Управлять доступом может только владелец бота.')

def listing(actor):
    require_admin(actor)
    with app.db() as con:
        init_db(con)
        profiles={r['user_id']:dict(r) for r in con.execute('SELECT * FROM bot_user_profiles')}
    result=[]
    for uid in sorted(map(int,allowed_ids())):
        profile=profiles.get(uid,{})
        result.append({'id':uid,'username':profile.get('username',''),'name':' '.join(filter(None,[profile.get('first_name'),profile.get('last_name')])),'admin':uid in admin_ids(),'removable':uid not in configured_ids() and uid not in admin_ids()})
    return {'users':result}

def grant(actor,value):
    require_admin(actor)
    text=str(value).strip()
    if not re.fullmatch(r'[1-9][0-9]{4,15}',text):raise ValueError('Укажите числовой Telegram ID, а не @ник.')
    uid=int(text)
    with app.db() as con:
        init_db(con)
        con.execute('INSERT OR REPLACE INTO bot_access_users VALUES(?,1,?)',(uid,actor))
    return uid

def revoke(actor,value):
    require_admin(actor)
    try:uid=int(value)
    except (TypeError,ValueError):raise ValueError('Некорректный ID пользователя.') from None
    if uid in configured_ids() or uid in admin_ids():raise ValueError('Постоянный доступ владельцев изменяется в настройках сервера.')
    with app.db() as con:
        init_db(con);con.execute('UPDATE bot_access_users SET enabled=0 WHERE user_id=?',(uid,))
