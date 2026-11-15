"""Settings, content planning, draft images and explicit local deletion."""
import json
import secrets
import app


def init_db(con):
    import scheduling
    scheduling.init_db(con)
    __import__('vk_publish').init_db(con)
    import premium_emoji
    premium_emoji.init_db(con)
    import post_images
    post_images.init_db(con)
    con.execute('CREATE TABLE IF NOT EXISTS bot_preferences (chat INTEGER PRIMARY KEY, data TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS bot_content_plans (chat INTEGER PRIMARY KEY, nonce TEXT, data TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS bot_post_images (post INTEGER PRIMARY KEY, file_id TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS bot_feature_confirmations (chat INTEGER PRIMARY KEY, nonce TEXT, data TEXT)')


def preferences(chat):
    with app.db() as con:
        row = con.execute('SELECT data FROM bot_preferences WHERE chat=?', (chat,)).fetchone()
    return {'fast': False, 'auto_voice': False, 'confirm_publish': True, **(json.loads(row['data']) if row else {})}


def image_for(post):
    with app.db() as con:
        row = con.execute('SELECT file_id FROM bot_post_images WHERE post=?', (post,)).fetchone()
    return row['file_id'] if row else ''


def settings(chat):
    import telegram_bot as b
    p = preferences(chat)
    import model_selection as models
    return b.say(chat, '<b>Настройки</b>\n\nМодель: <b>'+b.escape(models.title(models.model_for(chat)))+'</b>\n\nВыберите удобный темп работы.\nБыстрый режим сразу пишет черновик; подробный предлагает факты и идеи.\n\nБез проверки отправки пост уйдёт в канал сразу после нажатия «Отправить».', inline=[
        [b.btn('Выбрать модель ИИ', 'feat_models')],
        [b.btn('Premium-эмодзи', 'feat_emoji')],
        [b.btn('Режим: ' + ('Быстрый' if p['fast'] else 'Подробный'), 'feat_toggle:fast')],
        [b.btn('Голос: ' + ('Принимать сразу' if p['auto_voice'] else 'Проверять текст'), 'feat_toggle:auto_voice')],
        [b.btn('Отправка: ' + ('С проверкой' if p['confirm_publish'] else 'Сразу'), 'feat_toggle:confirm_publish')],
        [b.btn('Функционал для презентации', 'project_info')],
        [b.btn('Очистить отменённые посты', 'feat_cleanup')],
        [b.btn('Сбросить компанию', 'company_reset', style='danger'), b.btn('← Меню', 'home')]], formatted=True)


def show_plan(chat):
    import telegram_bot as b
    with app.db() as con:
        row = con.execute('SELECT * FROM bot_content_plans WHERE chat=?', (chat,)).fetchone()
    if not row:
        return start_plan(chat)
    items = json.loads(row['data'])
    text = '<b>Контент-план</b>\n\n' + '\n\n'.join(f'<b>{i+1}. {b.escape(item["topic"])}</b>\n{b.escape(item["angle"])}' for i,item in enumerate(items))
    rows = [[b.btn(f'{i+1}. {item["topic"][:40]}', f'feat_plan_post:{row["nonce"]}:{i}')] for i,item in enumerate(items)]
    rows += [[b.btn('Новый план', 'feat_plan_new'), b.btn('← Меню', 'home')]]
    return b.say(chat, text, inline=rows, formatted=True, stage='ideas')


def start_plan(chat):
    import telegram_bot as b
    if b.session(chat)['editing']:
        raise ValueError('Завершите правки поста перед созданием плана.')
    if b.session(chat)['step'] < len(b.QUESTIONS):
        return b.ask(b.session(chat))
    b.focus_post(chat)
    b.set_context(chat, {'mode': 'content_plan_input'})
    return b.say(chat, '<b>Что запланируем?</b>\n\nНапишите период, число публикаций и цель.\nНапример: «5 постов на неделю о работе завода, для сотрудников».', inline=[[b.btn('← Меню', 'home')]], formatted=True, stage='ideas')


def generate_plan(chat, request):
    import telegram_bot as b
    b.set_context(chat, {'mode': 'content_plan_input', 'request': request})
    with b.loading(chat, 'Готовлю контент-план') as wait:
        result = app.ai_json('Ты контент-редактор. Предложи контент-план по профилю и запросу. От 1 до 14 публикаций, по умолчанию 5. Не утверждай выдуманные события, даты, достижения или цитаты: это идеи будущих публикаций. Темы разные, конкретные и полезные аудитории. JSON {"items":[{"topic":"короткая тема","angle":"ракурс и какие материалы собрать, 1–2 предложения"}]}.', {'profile': b.brief(b.session(chat)), 'request': request})
    items = result.get('items')
    if not isinstance(items, list) or not 1 <= len(items) <= 14 or any(not isinstance(x, dict) or any(not isinstance(x.get(k), str) or not x[k].strip() for k in ('topic','angle')) for x in items):
        raise ValueError('Не удалось составить план. Уточните задачу и повторите.')
    items = [{'topic': x['topic'][:120], 'angle': x['angle'][:500]} for x in items]
    with app.db() as con:
        con.execute('INSERT OR REPLACE INTO bot_content_plans VALUES(?,?,?)', (chat, secrets.token_hex(5), json.dumps(items, ensure_ascii=False)))
    b.set_context(chat, {})
    if wait.visible:
        return show_plan(chat)


def receive_photo(chat, photos):
    import telegram_bot as b
    p = b.focused_post(chat)
    if not p:
        raise ValueError('Сначала откройте черновик в «Мои посты», затем пришлите фото.')
    if b.context(chat).get('mode') not in ('', 'edit', 'replace', None):
        raise ValueError('Завершите текущую задачу, затем откройте пост и пришлите фото.')
    photo = photos[-1]
    if not isinstance(photo.get('file_id'), str):
        raise ValueError('Не удалось получить фото. Отправьте его как изображение.')
    with app.db() as con:
        con.execute('INSERT OR REPLACE INTO bot_post_images VALUES(?,?)', (p['id'], photo['file_id']))
        con.execute('UPDATE bot_posts SET rev=rev+1 WHERE id=? AND chat=?', (p['id'],chat))
        con.execute('DELETE FROM bot_confirmations WHERE post=?', (p['id'],))
    pending = b.context(chat)
    if b.session(chat)['editing'] == p['id']:
        pending['rev'] = p['rev'] + 1
        b.set_context(chat, pending)
    return b.show_post(chat, p['id'])


def confirm_deletion(chat, ids):
    import telegram_bot as b
    nonce = secrets.token_hex(5)
    with app.db() as con:
        con.execute('INSERT OR REPLACE INTO bot_feature_confirmations VALUES(?,?,?)', (chat,nonce,json.dumps(ids)))
    return b.say(chat, f'<b>Удалить посты: {len(ids)}?</b>\n\nТексты, изображения и история правок будут удалены из локальной базы. Публикации в канале останутся.', inline=[[b.btn('Удалить навсегда', 'feat_delete_confirm:'+nonce, style='danger')],[b.btn('← Не удалять', 'feat_delete_cancel')]],formatted=True)


def callback(chat, data):
    import telegram_bot as b
    parts = data.split(':')
    action = parts[0]
    if action=='feat_art_cancel':
        pending=b.context(chat)
        if pending.get('mode')!='image_edit':return b.home(chat)
        b.set_context(chat,pending.get('previous',{}))
        return b.show_post(chat,pending['post'])
    if action=='feat_art':
        if len(parts)!=3:raise ValueError('Откройте пост заново.')
        with app.db() as con:p=con.execute('SELECT id,rev FROM bot_posts WHERE id=? AND chat=? AND rev=? AND status IN ("draft","approved")',(int(parts[1]),chat,int(parts[2]))).fetchone()
        if not p:raise ValueError('Пост изменился. Откройте актуальную версию.')
        previous=b.context(chat)
        if previous.get('mode')=='image_edit':previous=previous.get('previous',{})
        state=b.session(chat)
        if previous.get('mode')!='edit' or state['editing']!=p['id']:
            previous={}
            state['editing']=None;b.save(state)
        b.set_context(chat,{'mode':'image_edit','post':p['id'],'rev':p['rev'],'nonce':secrets.token_hex(12),'previous':previous})
        return b.say(chat,'Что изменить в картинке?\n\nОпишите сюжет, настроение или композицию. Создам новый AI-вариант через DeepSeek и FLUX; это платная генерация. Текст поста сохранится.',inline=[[b.btn('К посту','feat_art_cancel')]])
    if action.startswith('feat_emoji'):
        import premium_emoji
        return premium_emoji.callback(chat,data)
    if action in ('feat_models','feat_model'):
        import model_selection as models
        if action=='feat_model':
            item=next((m for m in models.MODELS if len(parts)==2 and m['key']==parts[1]),None)
            if not item:raise ValueError('Выберите модель из списка.')
            models.choose(chat,item['id'])
        selected=models.model_for(chat)
        rows=[[b.btn(('✓ ' if m['id']==selected else '')+m['title'],'feat_model:'+m['key'])] for m in models.MODELS]
        rows.append([b.btn('К настройкам','settings')])
        return b.say(chat,'<b>Модель ИИ</b>\n\nDeepSeek: экономия.\nGPT-4.1: сбалансированный вариант.\nClaude Sonnet 5.5: рекомендуем попробовать для инструкций и редактуры.\nGPT-6.1 Sol: усиленный режим для продуманных текстов, с оплатой рассуждений.\n\nВыбор общий для бота и Mini App, действует только на ваши новые запросы. Запрос в работе завершится на прежней модели. Оплата списывается с общего баланса ProxyAPI.',inline=rows,formatted=True)
    if action == 'feat_toggle':
        if len(parts)!=2 or parts[1] not in ('fast','auto_voice','confirm_publish'):
            raise ValueError('Неизвестная настройка.')
        p=preferences(chat); p[parts[1]]=not p[parts[1]]
        with app.db() as con:
            con.execute('INSERT OR REPLACE INTO bot_preferences VALUES(?,?)',(chat,json.dumps(p)))
        return settings(chat)
    if action == 'feat_plan':
        return show_plan(chat)
    if action == 'feat_plan_new':
        return start_plan(chat)
    if action == 'feat_plan_retry':
        pending=b.context(chat)
        if pending.get('mode')!='content_plan_input' or not pending.get('request'):
            raise ValueError('Откройте создание контент-плана.')
        return generate_plan(chat,pending['request'])
    if action == 'feat_plan_post':
        if b.session(chat)['editing']:
            raise ValueError('Сначала завершите правки открытого поста.')
        with app.db() as con:
            row=con.execute('SELECT * FROM bot_content_plans WHERE chat=?',(chat,)).fetchone()
        if not row or len(parts)!=3 or row['nonce']!=parts[1] or not parts[2].isdigit():
            raise ValueError('План изменился. Откройте его заново.')
        items=json.loads(row['data']); i=int(parts[2])
        if not 0<=i<len(items):
            raise ValueError('Тема не найдена.')
        selected=__import__('marketer').plan_topic(chat,row['nonce'],i)
        b.focus_post(chat)
        return b.create_posts(chat,selected['task'],selected['clarification']) if preferences(chat)['fast'] else b.plan_event(chat,selected['task'],selected['clarification'])
    if action in ('feat_delete','feat_cleanup'):
        with app.db() as con:
            if action=='feat_cleanup':
                rows=con.execute('SELECT id,rev,status FROM bot_posts WHERE chat=? AND status="cancelled"',(chat,)).fetchall()
            else:
                if len(parts)!=3 or not parts[1].isdigit() or not parts[2].isdigit():
                    raise ValueError('Откройте актуальную карточку поста.')
                rows=con.execute('SELECT id,rev,status FROM bot_posts WHERE chat=? AND id=? AND rev=? AND status NOT IN ("publishing","delivery_unknown")',(chat,int(parts[1]),int(parts[2]))).fetchall()
        if not rows:
            raise ValueError('Нет постов для удаления.')
        return confirm_deletion(chat,[dict(r) for r in rows])
    if action=='feat_delete_cancel':
        with app.db() as con:
            con.execute('DELETE FROM bot_feature_confirmations WHERE chat=?',(chat,))
        return b.list_posts(chat)
    if action=='feat_delete_confirm':
        with app.db() as con:
            row=con.execute('SELECT * FROM bot_feature_confirmations WHERE chat=?',(chat,)).fetchone()
            if not row or len(parts)!=2 or row['nonce']!=parts[1]:
                raise ValueError('Подтверждение устарело.')
            for item in json.loads(row['data']):
                vk=con.execute('SELECT state FROM bot_vk_delivery WHERE post=?',(item['id'],)).fetchone()
                if vk and vk['state'] in ('sending','unknown'):raise ValueError('Сначала проверьте доставку этого поста в ВК. Удаление пока заблокировано.')
                removed=con.execute('DELETE FROM bot_posts WHERE id=? AND chat=? AND rev=? AND status=?',(item['id'],chat,item['rev'],item['status'])).rowcount
                if removed:
                    if con.execute("SELECT 1 FROM sqlite_master WHERE name='mini_edit_memory'").fetchone():
                        con.execute('DELETE FROM mini_edit_memory WHERE post=?',(item['id'],))
                    if con.execute("SELECT 1 FROM sqlite_master WHERE name='bot_post_schedule'").fetchone():
                        con.execute('DELETE FROM bot_post_schedule WHERE post=?',(item['id'],))
                    for optional in ('bot_delivery_schedule','mini_edit_memory','bot_image_jobs','bot_visual_reviews','bot_visual_attempts','bot_vk_delivery'):
                        if con.execute('SELECT 1 FROM sqlite_master WHERE name=?',(optional,)).fetchone():
                            con.execute('DELETE FROM '+optional+' WHERE post=?',(item['id'],))
                    for table in ('bot_versions','bot_post_context','bot_post_review','bot_post_images','bot_confirmations','bot_post_focus'):
                        con.execute(f'DELETE FROM {table} WHERE post=?',(item['id'],))
                    state=b.session(chat)
                    if state['editing']==item['id']:
                        con.execute('UPDATE bot_sessions SET editing=NULL WHERE chat=?',(chat,))
                        con.execute('DELETE FROM bot_context WHERE chat=?',(chat,))
            con.execute('DELETE FROM bot_feature_confirmations WHERE chat=?',(chat,))
        return b.list_posts(chat)
    if action=='feat_image_remove':
        p=b.focused_post(chat)
        if not p or len(parts)!=3 or parts[1]!=str(p['id']) or parts[2]!=str(p['rev']):
            raise ValueError('Откройте черновик.')
        with app.db() as con:
            con.execute('DELETE FROM bot_post_images WHERE post=?',(p['id'],))
            con.execute('UPDATE bot_posts SET rev=rev+1 WHERE id=? AND chat=?',(p['id'],chat))
            con.execute('DELETE FROM bot_confirmations WHERE post=?',(p['id'],))
        pending=b.context(chat)
        if b.session(chat)['editing']==p['id']:
            pending['rev']=p['rev']+1
            b.set_context(chat,pending)
        return b.show_post(chat,p['id'])
    raise ValueError('Неизвестное действие.')
