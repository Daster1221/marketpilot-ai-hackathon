import io,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
import app,company_documents as docs,marketer,telegram_bot as bot,miniapp_api

class CompanyDocumentsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=patch.object(app,'ROOT',Path(self.temp.name));self.root.start()
        (app.ROOT/'data').mkdir();bot.init_db();miniapp_api.init_db()
        self.env=patch.dict(app.os.environ,{'DEEPSEEK_API_KEY':'fixture-not-real'});self.env.start()
        self.response={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'summary':'Компания производит листовое стекло для строительства.'})}}]}
    def tearDown(self):self.env.stop();self.root.stop();self.temp.cleanup()
    def test_ingestion_is_cached_by_content_and_owned_by_user(self):
        raw='Компания производит листовое стекло для строительства.'.encode()
        with patch.object(app,'remote_json',return_value=self.response) as api:
            first=docs.ingest(42,'company.txt',raw);second=docs.ingest(42,'renamed.txt',raw)
        self.assertTrue(second['cached']);api.assert_called_once()
        self.assertIn('стекло',docs.context(42,'строительства'))
        self.assertEqual(docs.context(99),'');docs.delete(99,first['document_id']);self.assertTrue(docs.listing(42))
        docs.delete(42,first['document_id']);self.assertEqual(docs.context(42),'')
    def test_docx_extracts_paragraphs_and_pdf_scan_explains_limit(self):
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z:z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:p><w:r><w:t>Компания выпускает строительное стекло.</w:t></w:r></w:p></w:document>')
        self.assertIn('строительное стекло',docs.extract('test.docx',raw.getvalue()))
        from pypdf import PdfWriter
        writer=PdfWriter();writer.add_blank_page(width=100,height=100);out=io.BytesIO();writer.write(out)
        with self.assertRaisesRegex(ValueError,'OCR'):docs.extract('scan.pdf',out.getvalue())
        with self.assertRaises(ValueError):docs.extract('bad.exe',b'x'*30)
    def test_failed_summary_does_not_poison_cache_and_context_is_bounded(self):
        with patch.object(app,'remote_json',side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):docs.ingest(42,'test.txt',b'a'*100)
        self.assertEqual(docs.listing(42),[])
        with patch.object(app,'remote_json',return_value=self.response):docs.ingest(42,'test.txt',b'a'*100)
        self.assertLessEqual(len(docs.context(42,'',limit=200)),200)
    def test_marketer_reads_only_own_archive_and_compact_memory(self):
        with app.db() as c:
            c.execute('INSERT INTO bot_posts(chat,topic,body) VALUES(42,"Своя тема","Свой полный текст")')
            c.execute('INSERT INTO bot_posts(chat,topic,body) VALUES(99,"Чужая тема","Чужой полный текст")')
        value={'answer':'<b>План</b>\nПредлагаю рассказать о производстве.','memory':'Цель: знакомить с производством.','plan':[{'topic':'Как делают стекло','angle':'Показать этапы производства'}]}
        with patch.object(app,'ai_json',return_value=value) as api:
            r=marketer.ask(42,'Составь контент-план на неделю')
        self.assertTrue(r['plan_saved']);context=api.call_args.args[1]
        self.assertEqual(len(context['posts']),1);self.assertNotIn('Свой полный текст',str(context));self.assertNotIn('Чуж',str(context))
        with app.db() as c:self.assertIsNotNone(c.execute('SELECT data FROM bot_content_plans WHERE chat=42').fetchone())
        self.assertEqual(marketer.history(99),[])
        value['plan']=[]
        with patch.object(app,'ai_json',return_value=value) as api:marketer.ask(42,'Посмотри пост №1')
        self.assertEqual(api.call_args.args[1]['requested_posts'][0]['body'],'Свой полный текст')
        self.assertEqual(api.call_args.args[1]['memory'],'Цель: знакомить с производством.')
    def test_unrequested_plan_cannot_replace_existing_one(self):
        value={'answer':'Ответ','memory':'','plan':[{'topic':'Подмена','angle':'Не запрошена'}]}
        with patch.object(app,'ai_json',return_value=value):result=marketer.ask(42,'Что ты знаешь о компании?')
        self.assertFalse(result['plan_saved'])

    def test_explicit_no_plan_cannot_be_overwritten_by_model(self):
        value={'answer':'Две темы','memory':'','plan':[{'topic':'Подмена','angle':'Не запрошена'}]}
        with patch.object(app,'ai_json',return_value=value) as api:
            result=marketer.ask(42,'Предложи две темы, не создавай контент-план.')
        self.assertFalse(result['plan_saved']);self.assertFalse(api.call_args.args[1]['may_propose_plan'])

    def test_numbered_posts_become_plan_topics_without_implicit_publication(self):
        value={'answer':'Уточните команды и дату.','memory':'Нужны три темы.','plan':[{'topic':'Футбольный матч','angle':'Анонс'},{'topic':'Годовщина цеха','angle':'История'},{'topic':'Финал','angle':'Итоги'}]}
        with patch.object(app,'ai_json',return_value=value):r=marketer.ask(42,'Нужно 3 поста: матч, годовщина цеха и финал')
        self.assertTrue(r['plan_saved'])
        with app.db() as c:self.assertEqual(c.execute('SELECT count(*) FROM bot_posts WHERE chat=42').fetchone()[0],0)

    def test_plan_clarifications_reach_miniapp_and_bot_without_retyping(self):
        first={'answer':'Уточните дату и место','memory':'План: матч и юбилей.','plan':[{'topic':'Матч','angle':'Приглашение'},{'topic':'Юбилей','angle':'История'}]}
        with patch.object(app,'ai_json',return_value=first):marketer.ask(42,'Составь план на неделю')
        nonce=marketer.snapshot(42)['plan_nonce']
        second={'answer':'Сохранил','memory':'Матч 20 ноября в 19:00 на стадионе «Старт». Юбилей 30 июня.','plan':[{'topic':'Матч','angle':'Приглашение','facts':'20 ноября, 19:00, стадион «Старт»'},{'topic':'Юбилей','angle':'История','facts':'30 июня'}]}
        with patch.object(app,'ai_json',return_value=second):marketer.ask(42,'Матч 20 ноября в 19:00 на стадионе Старт. Юбилей 30 июня.')
        self.assertEqual(nonce,marketer.snapshot(42)['plan_nonce'])
        selected=marketer.plan_topic(42,nonce,0)
        self.assertIn('19:00',selected['clarification']);self.assertIn('Старт',selected['clarification'])
        with patch.object(app,'plan_publication',return_value={'facts':[],'ideas':[],'question':''}) as plan:
            result=miniapp_api.workflow(42,{'operation':'plan_topic','plan_nonce':nonce,'topic_index':0})
        self.assertIn('19:00',plan.call_args.args[2])
        with app.db() as c:
            workflow=c.execute('SELECT clarification FROM mini_workflows WHERE id=?',(result['workflow_id'],)).fetchone()
        self.assertIn('Старт',workflow['clarification'])
        with self.assertRaises(ValueError):marketer.plan_topic(99,nonce,0)
        with self.assertRaises(ValueError):marketer.plan_topic(42,'stale',0)
    def test_legacy_plan_and_memory_only_followup_keep_known_facts(self):
        with app.db() as c:
            c.execute('INSERT INTO bot_content_plans VALUES(42,"legacy",?)',(json.dumps([{'topic':'Матч','angle':'Анонс'}]),))
            c.execute('INSERT INTO marketer_memory VALUES(42,"Матч 20 ноября в Уфе")')
        self.assertIn('20 ноября',marketer.plan_topic(42,'legacy',0)['clarification'])
        with patch.object(app,'ai_json',return_value={'answer':'Понял','memory':'Матч перенесён на 21 ноября, Уфа.','plan':[]}):marketer.ask(42,'Перенос на 21 ноября')
        self.assertIn('21 ноября',marketer.plan_topic(42,'legacy',0)['clarification'])
