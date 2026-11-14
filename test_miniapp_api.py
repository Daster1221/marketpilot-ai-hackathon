import hashlib
import hmac
import json
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import patch,Mock
import app
import telegram_bot as bot
import miniapp_api as api


class MiniAppAPITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=patch.object(app,'ROOT',Path(self.temp.name));self.root.start()
        (app.ROOT/'data').mkdir()
        self.env=patch.dict(app.os.environ,{'TELEGRAM_BOT_TOKEN':'unit-test-token-not-real','TELEGRAM_OWNER_ID':'42'});self.env.start()
        bot.init_db();api.init_db()
        bot.save({'chat':42,'step':5,'answers':'{"company":"Тестовая компания"}','editing':None})

    def tearDown(self):
        self.env.stop();self.root.stop();self.temp.cleanup()

    def signed(self,chat=42,age=0):
        fields={'auth_date':str(int(time.time())-age),'user':json.dumps({'id':chat}),'query_id':'fixture'}
        secret=hmac.new(b'WebAppData',b'unit-test-token-not-real',hashlib.sha256).digest()
        fields['hash']=hmac.new(secret,'\n'.join(f'{k}={v}' for k,v in sorted(fields.items())).encode(),hashlib.sha256).hexdigest()
        return urlencode(fields)

    def test_auth_checks_signature_age_owner_and_duplicate_fields(self):
        self.assertEqual(api.authenticate(self.signed()),42)
        for value in ('',self.signed().replace('fixture','tampered'),self.signed(99),self.signed(age=90000),self.signed(age=-600),self.signed()+'&auth_date=1'):
            with self.assertRaises(PermissionError): api.authenticate(value)

    def test_bot_posts_are_visible_and_other_users_posts_are_not(self):
        with app.db() as con:
            mine=con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(42,"Мой пост","<b>Текст</b>","deepseek")').lastrowid
            other=con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(99,"Чужой","Текст","deepseek")').lastrowid
        self.assertEqual([p['id'] for p in api.data(42)['posts']],[mine])
        with self.assertRaises(ValueError): api.post(42,other)

    def test_list_is_lightweight_but_detail_keeps_full_formatted_text(self):
        with app.db() as con:
            for i in range(40):
                con.execute('INSERT INTO bot_posts(chat,topic,body,source) VALUES(42,?,?,"deepseek")',(str(i),'<b>'+('Подробный текст '*100)+'</b>'))
        with patch.object(api.post_format,'normalize',wraps=api.post_format.normalize) as normalize:
            listing=api.data(42)
            normalize.assert_not_called()
        self.assertEqual(len(listing['posts']),40)
        self.assertNotIn('body',listing['posts'][0])
        self.assertIn('<b>',api.serialize(api.post(42,listing['posts'][0]['id']))['body_html'])

    def test_generation_and_manual_edit_share_bot_versions_and_reject_stale_revision(self):
        plan={'facts':[{'label':'Событие','value':'Матч'}],'question':'','ideas':[{'title':str(i),'angle':'Анонс'} for i in range(3)]}
        with patch.object(app,'plan_publication',return_value=plan):
            first=api.workflow(42,{'operation':'plan','task':'Матч'})
        with patch.object(app,'prepare_posts',return_value={'posts':[{'topic':'Матч','body':'<b>Матч</b>','warnings':[],'fact_blocks':[],'brand_name_mode':'brandbook','publication_date':None}]}) as generate:
            result=api.workflow(42,{'operation':'generate','workflow_id':first['workflow_id'],'idea':1})
        p=result['posts'][0]
        self.assertEqual(p['status'],'DRAFT')
        self.assertEqual(bot.post_memory(42,p['id'])[0][0]['body'],'<b>Матч</b>')
        updated=api.save_post(42,p['id'],{'body':'<b>Новый текст</b>','rev':1})
        self.assertEqual(updated['rev'],2)
        self.assertEqual(api.post(42,p['id'])['body'],'<b>Новый текст</b>')
        with self.assertRaises(ValueError): api.save_post(42,p['id'],{'body':'Старая версия','rev':1})
        with patch.object(bot,'tg') as telegram:
            api.save_post(42,p['id'],{'body':'<b>Готово</b>','rev':2,'approve':True})
            telegram.assert_not_called()

    def test_job_requests_are_idempotent_and_owner_scoped(self):
        with patch.object(api.POOL,'submit') as submit:
            first=api.enqueue(42,{'operation':'plan','task':'Матч','request_id':'same-request'})
            again=api.enqueue(42,{'operation':'plan','task':'Матч','request_id':'same-request'})
        self.assertEqual(first,again);submit.assert_called_once()
        with self.assertRaises(ValueError): api.job(99,first['job_id'])
        with self.assertRaises(ValueError): api.enqueue(42,{'operation':'plan','request_id':'another-request'})

    def test_lost_upload_reply_is_recovered_by_owner_and_request_key(self):
        with patch.object(api.POOL,'submit'):
            result=api.enqueue(42,{'operation':'transcribe','audio':b'fixture','request_id':'voice-upload'})
        self.assertEqual(api.job_request(42,'voice-upload'),result)
        self.assertEqual(api.job_request(99,'voice-upload'),{'job_id':None})
        with app.db() as con:
            con.execute('UPDATE mini_jobs SET status="done",result=? WHERE id=?',(json.dumps({'transcript':'Распознанный текст'}),result['job_id']))
        self.assertEqual(api.last_transcript(42)['transcript'],'Распознанный текст')
        with self.assertRaises(ValueError):api.last_transcript(99)

    def test_failed_replanning_keeps_new_clarification(self):
        with patch.object(app,'plan_publication',return_value={'facts':[],'ideas':[],'question':'Когда?'}):
            result=api.workflow(42,{'operation':'plan','task':'Матч'})
        with patch.object(app,'plan_publication',side_effect=ValueError('Временно недоступно')):
            with self.assertRaises(ValueError): api.workflow(42,{'operation':'plan','workflow_id':result['workflow_id'],'clarification':'15 октября'})
        with app.db() as con:
            row=con.execute('SELECT clarification FROM mini_workflows WHERE id=?',(result['workflow_id'],)).fetchone()
        self.assertEqual(row['clarification'],'15 октября')

    def test_manual_draft_is_saved_without_ai_or_telegram_calls(self):
        with patch.object(app,'ai_json') as model,patch.object(bot,'tg') as telegram:
            result=api.workflow(42,{'operation':'manual','title':'Заголовок','body':'Мой текст'})
        model.assert_not_called();telegram.assert_not_called()
        self.assertEqual(result['posts'][0]['body'],'Мой текст')

    def test_same_origin_survives_rotating_tunnel_but_foreign_origin_is_rejected(self):
        with patch.dict(app.os.environ,{'MINI_APP_URL':'https://new.example'}):
            self.assertTrue(api.origin_allowed('https://old.example','old.example'))
            self.assertTrue(api.origin_allowed('https://new.example','127.0.0.1:8765'))
            self.assertFalse(api.origin_allowed('https://foreign.example','old.example'))
            self.assertFalse(api.origin_allowed('https://old.example.evil','old.example'))
            self.assertFalse(api.origin_allowed('https://user@old.example','old.example'))

    def test_calendar_creates_three_shared_drafts_with_future_dates_atomically(self):
        from datetime import datetime,timedelta
        now=datetime.now(api.LOCAL_TZ)
        payload={'posts':[{'topic':f'Тема {i}','body':'<b>Информация для коллег</b>\nТекст публикации.','due':(now+timedelta(days=i+1)).isoformat()} for i in range(3)]}
        with patch.object(app,'ai_json',return_value=payload) as model,patch.object(bot,'tg') as telegram:
            result=api.workflow(42,{'operation':'calendar_plan','task':'Сделай контент план на 3 поста'})
        telegram.assert_not_called()
        self.assertEqual(len(result['posts']),3)
        self.assertTrue(result['calendar'])
        self.assertEqual(model.call_args.args[1]['current_date'],now.date().isoformat())
        self.assertEqual(model.call_args.args[1]['timezone'],'Asia/Yekaterinburg')
        self.assertTrue(all(p['due'] and p['status']=='SCHEDULED' for p in result['posts']))
        self.assertEqual(api.data(99)['posts'],[])
        with app.db() as con:
            self.assertEqual(con.execute('SELECT count(*) FROM bot_posts WHERE status="draft"').fetchone()[0],3)
        payload['posts'][-1]['due']=(now-timedelta(days=1)).isoformat()
        with patch.object(app,'ai_json',return_value=payload),self.assertRaises(ValueError):
            api.workflow(42,{'operation':'calendar_plan','task':'Сделай 3 поста'})
        self.assertEqual(len(api.data(42)['posts']),3)

    def test_voice_uses_local_recognizer_without_language_model(self):
        import speech
        with patch.object(speech,'transcribe',return_value='Создай три поста') as recognize,patch.object(app,'ai_json') as model:
            result=api.workflow(42,{'operation':'transcribe','audio':b'fixture','content_type':'audio/mp4'})
        self.assertEqual(result['transcript'],'Создай три поста')
        self.assertEqual(recognize.call_args.args[0],b'fixture')
        model.assert_not_called()
        for value in (b'',b'x'*(speech.MAX_AUDIO_BYTES+1),'text'):
            with self.assertRaises(ValueError): api.workflow(42,{'operation':'transcribe','audio':value})
